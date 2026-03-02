

import os
import time
from celery import shared_task
from django.utils import timezone
from django.conf import settings
from .models import DocumentIndex, RAGUsageStats
from .rag.document_processor import DocumentProcessor
from .rag.embeddings import EmbeddingGenerator
from .rag.vector_store import VectorStore
import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def index_document_task(self, document_id: str, tenant_id: str, file_path: str = None, user_id: str = None, metadata: dict = None):
    """
    Async task to index a document
    """
    import requests
    start_time = time.time()
    metadata = metadata or {}
    
    def _notify_document_service(status_str, is_indexed=False):
        """
        Update the document status directly in the shared PostgreSQL database.

        IMPORTANT: We use a direct SQL update instead of an HTTP callback to
        avoid a single-threaded deadlock that occurs when Celery runs tasks
        eagerly (synchronously) inside the Django request/response cycle:

          1. doc_service (8003) sends a webhook → chatbot_service (8002)
          2. chatbot_service runs index_document_task *inline* (ALWAYS_EAGER)
          3. that task would then HTTP POST back to doc_service (8003) …
          4. … but doc_service is still waiting for step 1 to return → DEADLOCK

        Since both microservices share the same PostgreSQL database
        (tenantiq_db) we can write directly to doc_service_document, which is
        always safe and never blocks.
        """
        # Prefer direct DB write when both services share Postgres.
        # If that fails (e.g. separate DBs in dev like SQLite), fall back to HTTP.
        rows_updated = 0
        db_error = None
        try:
            from django.db import connection, transaction
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE doc_service_document
                        SET indexing_status = %s,
                            is_indexed      = %s,
                            updated_at      = NOW()
                        WHERE id = %s::uuid
                        """,
                        [status_str, is_indexed, str(document_id)]
                    )
                    rows_updated = cursor.rowcount

        except Exception as e:
            db_error = e
            logger.warning(
                f"[TASK] Direct DB status update failed for {document_id} "
                f"(likely separate DBs). Will try HTTP callback. Error: {e}"
            )

        if rows_updated:
            logger.info(
                f"[TASK] DB-updated doc_service_document → "
                f"{document_id}: status={status_str}, is_indexed={is_indexed}"
            )
            return

        # ── HTTP callback fallback ──────────────────────────────────────────
        try:
            callback_url = (
                f"{settings.DOCUMENT_SERVICE_URL}"
                f"/api/doc/documents/{document_id}/update-index-status/"
            )
            payload = {
                'indexing_status': status_str,
                'is_indexed': is_indexed,
                'tenant_id': str(tenant_id).strip().lower(),
            }
            response = requests.post(
                callback_url,
                json=payload,
                headers={
                    'X-API-Key': getattr(settings, 'DOCUMENT_SERVICE_WEBHOOK_API_KEY', settings.WEBHOOK_API_KEY),
                    'Content-Type': 'application/json',
                },
                timeout=10,
            )
            logger.info(
                f"[TASK] HTTP status callback → {response.status_code} for doc {document_id}. "
                f"Body={response.text[:300]}"
            )
        except Exception as http_err:
            logger.error(
                f"[TASK] Failed to update document status via HTTP for {document_id}. "
                f"DB_rows={rows_updated} DB_error={db_error} HTTP_error={http_err}"
            )

    try:
        # Get or create document record
        tenant_id = str(tenant_id).strip().lower()
        doc_index, created = DocumentIndex.objects.get_or_create(
            id=document_id,
            defaults={
                'tenant_id': tenant_id,
                'title': metadata.get('title', 'Untitled'),
                'file_name': metadata.get('file_name', 'unknown'),
                'file_type': metadata.get('file_type', 'application/pdf'),
                'file_size': metadata.get('file_size', 0),
                'indexing_status': 'processing',
            }
        )
        
        if not created:
            doc_index.indexing_status = 'processing'
            doc_index.save(update_fields=['indexing_status', 'updated_at'])
            logger.info(f"[TASK] Updated local status to 'processing' for document {document_id}")
        
        _notify_document_service('processing')
        logger.info(f"[TASK] Starting indexing for document {document_id} (Tenant: {tenant_id})")
        
        # Use provided file_path or fall back to model
        if not file_path:
            if doc_index.file:
                file_path = doc_index.file.path
            else:
                raise ValueError(f"No file path provided and document {document_id} has no file attached")
        
        if not os.path.exists(file_path):
            logger.error(f"[TASK] File not found at path: {file_path}")
            raise FileNotFoundError(f"File not found: {file_path}")
        
        logger.info(f"[TASK] 📁 Processing file: {file_path}")
        
        # Initialize processors
        processor = DocumentProcessor(
            chunk_size=settings.DOCUMENT_CHUNK_SIZE,
            chunk_overlap=settings.DOCUMENT_CHUNK_OVERLAP
        )
        embedding_gen = EmbeddingGenerator(model=settings.EMBEDDING_MODEL)
        vector_store = VectorStore()
        
        # Merge metadata
        rag_metadata = {
            'document_id': str(document_id),
            'tenant_id': str(tenant_id),
            'title': doc_index.title,
            'file_name': doc_index.file_name,
            'file_type': doc_index.file_type,
            **metadata
        }
        
        # Process document into chunks
        logger.info(f"[TASK] Splitting document into chunks...")
        chunks = processor.process_document(
            file_path=file_path,
            document_id=str(document_id),
            metadata=rag_metadata
        )
        
        if not chunks:
            logger.error(f"[TASK] Extraction failed - no content for {document_id}")
            raise ValueError("No text content could be extracted from the document")

        logger.info(f"[TASK] Successfully extracted {len(chunks)} chunks.")

        # Generate embeddings
        logger.info(f"[TASK] Generating embeddings for {len(chunks)} chunks...")
        chunk_texts = [chunk.content for chunk in chunks]
        embeddings = embedding_gen.generate_embeddings_batch(chunk_texts)
        
        # Prepare metadatas - ensure they are serializable for ChromaDB
        from .views import sanitize_metadata_for_chromadb
        chunk_metadatas = [sanitize_metadata_for_chromadb(chunk.metadata) for chunk in chunks]
        
        # Add to vector store
        logger.info(f"[TASK] Adding embeddings to vector store (ChromaDB)...")
        vector_store.add_documents(
            tenant_id=str(tenant_id),
            documents=chunk_texts,
            embeddings=embeddings,
            metadatas=chunk_metadatas,
            document_id=str(document_id)
        )
        
        # Calculate total tokens
        total_tokens = sum(getattr(chunk, 'token_count', 0) for chunk in chunks)
        
        # Update document index using standardized method
        doc_index.mark_indexed(
            num_chunks=len(chunks),
            total_tokens=total_tokens,
            processing_time=time.time() - start_time
        )
        
        logger.info(f"[TASK] ✅ Indexing complete in {time.time() - start_time:.2f}s. Notifying document service...")
        _notify_document_service('indexed', is_indexed=True)
        
        # Update usage stats
        try:
            RAGUsageStats.increment_documents(
                tenant_id=tenant_id,
                user_id=user_id or tenant_id,
                num_chunks=len(chunks),
                total_tokens=total_tokens
            )
            logger.info(f"[TASK] Stats updated for tenant {tenant_id}")
        except Exception as stats_error:
            logger.warning(f"[TASK] Failed to update stats: {str(stats_error)}")
        
        logger.info(f"✅ Document {document_id} indexed successfully.")
        return {
            'success': True,
            'document_id': str(document_id),
            'num_chunks': len(chunks),
            'processing_time': time.time() - start_time
        }
    
    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ [TASK] Error indexing {document_id}: {error_msg}", exc_info=True)
        
        try:
            doc_index = DocumentIndex.objects.get(id=document_id)
            doc_index.indexing_status = 'failed'
            doc_index.error_message = error_msg[:1000]
            doc_index.save()
        except Exception as save_err:
            logger.error(f"[TASK] Failed to save error status locally: {save_err}")
        
        try:
            _notify_document_service('failed')
        except Exception as notify_err:
            logger.error(f"[TASK] Failed to send failure notification: {notify_err}")
        
        # Retry logic
        if self.request.retries < self.max_retries:
            logger.info(f"[TASK] Retrying indexing for {document_id} (Attempt {self.request.retries + 1}/{self.max_retries})...")
            raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))
        
        return {'success': False, 'error': error_msg}


@shared_task
def reindex_document_task(document_id: str, tenant_id: str):
    """
    Reindex an existing document
    
    Args:
        document_id: UUID of the document
        tenant_id: Tenant identifier
    """
    try:
        logger.info(f"🔄 Reindexing document: {document_id}")
        
        # Get document record
        doc_index = DocumentIndex.objects.get(id=document_id)
        
        # Delete existing chunks from vector store
        vector_store = VectorStore()
        deleted_count = vector_store.delete_document(str(tenant_id), str(document_id))
        
        logger.info(f"🗑️ Deleted {deleted_count} existing chunks")
        
        # Reset status to pending
        doc_index.indexing_status = 'pending'
        doc_index.chunks_count = 0
        doc_index.total_tokens = 0
        doc_index.error_message = None
        doc_index.save()
        
        # Trigger new indexing task
        index_document_task.delay(str(document_id), str(tenant_id))
        
        logger.info(f"✅ Reindexing task queued")
        
        return {
            'success': True,
            'deleted_chunks': deleted_count
        }
    
    except DocumentIndex.DoesNotExist:
        error_msg = f'Document {document_id} not found'
        logger.error(f"❌ {error_msg}")
        return {
            'success': False,
            'error': error_msg
        }
    
    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Error reindexing document: {error_msg}")
        return {
            'success': False,
            'error': error_msg
        }


@shared_task
def cleanup_old_documents_task(tenant_id: str, days: int = 90):
    """
    Clean up documents older than specified days
    
    Args:
        tenant_id: Tenant identifier
        days: Number of days to keep
    """
    from datetime import timedelta
    
    try:
        logger.info(f"🧹 Cleaning up documents older than {days} days for tenant {tenant_id}")
        
        cutoff_date = timezone.now() - timedelta(days=days)
        
        # Get old documents
        old_docs = DocumentIndex.objects.filter(
            tenant_id=tenant_id,
            created_at__lt=cutoff_date
        )
        
        doc_count = old_docs.count()
        vector_store = VectorStore()
        deleted_chunks = 0
        
        for doc in old_docs:
            # Delete from vector store
            deleted_chunks += vector_store.delete_document(str(tenant_id), str(doc.id))
            # Delete file if exists
            if doc.file and os.path.exists(doc.file.path):
                os.remove(doc.file.path)
            # Delete from database
            doc.delete()
        
        logger.info(f"✅ Cleaned up {doc_count} documents ({deleted_chunks} chunks)")
        
        return {
            'success': True,
            'deleted_documents': doc_count,
            'deleted_chunks': deleted_chunks
        }
    
    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Cleanup failed: {error_msg}")
        return {
            'success': False,
            'error': error_msg
        }


@shared_task
def update_usage_stats_task(tenant_id: str):
    """
    Update and aggregate usage statistics
    
    Args:
        tenant_id: Tenant identifier
    """
    from datetime import timedelta
    from django.db.models import Sum
    
    try:
        today = timezone.now().date()
        last_7_days = today - timedelta(days=7)
        last_30_days = today - timedelta(days=30)
        
        # Get stats
        stats_7d = RAGUsageStats.objects.filter(
            tenant_id=tenant_id,
            date__gte=last_7_days
        ).aggregate(
            total_queries=Sum('queries_count'),
            total_documents=Sum('documents_indexed'),
            total_chunks=Sum('total_chunks'),
            total_tokens=Sum('total_tokens')
        )
        
        stats_30d = RAGUsageStats.objects.filter(
            tenant_id=tenant_id,
            date__gte=last_30_days
        ).aggregate(
            total_queries=Sum('queries_count'),
            total_documents=Sum('documents_indexed'),
            total_chunks=Sum('total_chunks'),
            total_tokens=Sum('total_tokens')
        )
        
        logger.info(f"📊 Updated usage stats for tenant {tenant_id}")
        
        return {
            'success': True,
            'stats_7d': stats_7d,
            'stats_30d': stats_30d
        }
    
    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Stats update failed: {error_msg}")
        return {
            'success': False,
            'error': error_msg
        }