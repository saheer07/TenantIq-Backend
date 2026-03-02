import os
import uuid
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from aichat_service.models import DocumentIndex
from aichat_service.views import document_processor, embedding_generator, vector_store

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Re-index all documents with fixed cleaning and normalized collection names'

    def add_arguments(self, parser):
        parser.add_argument('--tenant-id', type=str, help='Re-index only for this tenant')
        parser.add_argument('--dry-run', action='store_true', help='Do not actually update the vector store or database')
        parser.add_argument('--force', action='store_true', help='Force re-indexing even if not completed')

    def handle(self, *args, **options):
        tenant_id_arg = options.get('tenant_id')
        dry_run = options.get('dry_run')
        force = options.get('force')

        queryset = DocumentIndex.objects.all()
        if not force:
            queryset = queryset.filter(indexing_status__in=['completed', 'indexed'])
        
        if tenant_id_arg:
            try:
                tenant_id = uuid.UUID(tenant_id_arg)
                queryset = queryset.filter(tenant_id=tenant_id)
            except ValueError:
                self.stderr.write(self.style.ERROR(f"Invalid tenant-id: {tenant_id_arg}"))
                return

        count = queryset.count()
        self.stdout.write(f"Found {count} documents to re-index.")

        if count == 0:
            return

        for doc in queryset:
            self.stdout.write(f"Processing document: {doc.title} (ID: {doc.id}, Tenant: {doc.tenant_id})")
            
            # Use doc.file.path if available, otherwise check file field
            file_path = None
            if doc.file:
                try:
                    file_path = doc.file.path
                except (ValueError, AttributeError):
                    pass
            
            if not file_path or not os.path.exists(file_path):
                # Try fallback: look in the document service's media directory
                # Both services are on the same machine/host in this environment
                doc_service_media = os.path.abspath(os.path.join(settings.BASE_DIR, '..', '..', 'Project_three', 'document_service', 'media'))
                
                # If d.file has a path like 'documents/2026/02/24/file.pdf', append it to doc_service_media
                if doc.file:
                    fallback_path = os.path.join(doc_service_media, str(doc.file))
                    if os.path.exists(fallback_path):
                        file_path = fallback_path
                        self.stdout.write(self.style.SUCCESS(f"Found file in document service fallback: {file_path}"))
                
                if not file_path or not os.path.exists(file_path):
                    # Second fallback: search by filename in the document service media
                    if doc.file_name:
                        import glob
                        search_pattern = os.path.join(doc_service_media, 'documents', '**', f"*{doc.file_name}*")
                        matches = glob.glob(search_pattern, recursive=True)
                        if matches:
                            file_path = matches[0]
                            self.stdout.write(self.style.SUCCESS(f"Found file by name search: {file_path}"))

            if not file_path or not os.path.exists(file_path):
                self.stdout.write(self.style.WARNING(f"File not found for document {doc.id}: {file_path or 'No file path'}"))
                continue

            if dry_run:
                self.stdout.write(self.style.SUCCESS(f"[DRY-RUN] Would re-index document {doc.id}"))
                continue

            try:
                # 1. Re-process (chunk)
                initial_metadata = {
                    'document_id': str(doc.id),
                    'tenant_id': str(doc.tenant_id),
                    'title': doc.title,
                    'file_name': doc.file_name,
                    'file_type': doc.file_type,
                    'file_size': doc.file_size,
                    'upload_date': doc.created_at.isoformat()
                }
                
                chunks = document_processor.process_document(
                    file_path=file_path,
                    document_id=str(doc.id),
                    metadata=initial_metadata
                )
                
                if not chunks:
                    self.stdout.write(self.style.ERROR(f"No chunks extracted for document {doc.id}"))
                    continue

                # 2. Re-generate embeddings
                chunk_texts = [chunk.content for chunk in chunks]
                embeddings = embedding_generator.generate_embeddings_batch(chunk_texts)
                chunk_metadatas = [chunk.metadata for chunk in chunks]

                # 3. Update Vector Store (deletes old and adds new under normalized tenant_id)
                # update_document internally calls delete_document then add_documents
                vector_store.update_document(
                    tenant_id=str(doc.tenant_id),
                    document_id=str(doc.id),
                    documents=chunk_texts,
                    embeddings=embeddings,
                    metadatas=chunk_metadatas
                )

                # 4. Update Database Record
                doc.mark_indexed(
                    num_chunks=len(chunks),
                    total_tokens=sum(chunk.token_count for chunk in chunks),
                    processing_time=doc.processing_time or 0.0
                )
                self.stdout.write(self.style.SUCCESS(f"Successfully re-indexed document {doc.id}"))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error re-indexing document {doc.id}: {str(e)}"))
                # Optionally mark as failed if it wasn't already
                # doc.mark_failed(str(e))

        self.stdout.write(self.style.SUCCESS("Re-indexing complete."))
