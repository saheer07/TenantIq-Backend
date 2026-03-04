import os
import warnings
import logging
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

warnings.filterwarnings("ignore", message=".*OPENAI_API_KEY.*")
warnings.filterwarnings("ignore", category=UserWarning, module="langchain")
warnings.filterwarnings("ignore", category=UserWarning, module="langchain_community")

from django.conf import settings
from django.db import transaction, OperationalError
from django.db.models import Q, Sum, Count
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.pagination import PageNumberPagination
import requests
from .authentication import MicroserviceJWTAuthentication, APIKeyAuthentication
from .models import (
    DocumentIndex, Conversation, ChatMessage,
    MessageSource, RAGUsageStats, TenantSettings
)
from .serializers import (
    DocumentIndexSerializer, DocumentIndexListSerializer,
    ConversationSerializer, ConversationListSerializer,
    ConversationCreateSerializer, ChatMessageSerializer,
    ChatMessageCreateSerializer, ChatMessageFeedbackSerializer,
    MessageSourceSerializer, RAGUsageStatsSerializer,
    RAGUsageStatsSummarySerializer, TenantSettingsSerializer,
    DocumentIndexStatusSerializer,
)

from .rag.embeddings import EmbeddingGenerator
from .rag.vector_store import VectorStore, calculate_relevance_score
from .rag.document_processor import DocumentProcessor

# NOTE: No Celery/tasks import -- indexing is done synchronously inline.

logger = logging.getLogger(__name__)


def get_tenant_id_from_request(request, fallback: str = None) -> str:
    if getattr(request.user, 'is_authenticated', False):
        tenant_id = getattr(request.user, 'tenant_id', None)
        if tenant_id:
            return str(tenant_id)
    return (
        request.headers.get('X-Tenant-ID') or
        request.headers.get('X-Tenant-Id') or
        request.data.get('tenant_id') or
        request.query_params.get('tenant_id') or
        fallback
    )


def get_user_id_from_request(request, fallback: str = None) -> str:
    if getattr(request.user, 'is_authenticated', False):
        user_id = getattr(request.user, 'id', None) or getattr(request.user, 'user_id', None)
        if user_id and str(user_id) != 'webhook':
            return str(user_id)
    return (
        request.data.get('user_id') or
        request.query_params.get('user_id') or
        fallback
    )


def sanitize_metadata_for_chromadb(metadata: dict) -> dict:
    """ChromaDB only accepts str, int, float, bool, or None as metadata values."""
    import json
    sanitized = {}
    for key, value in metadata.items():
        if value is None or isinstance(value, (str, int, float, bool)):
            sanitized[key] = value
        elif isinstance(value, list):
            sanitized[key] = ", ".join(str(v) for v in value) if value else ""
        elif isinstance(value, dict):
            sanitized[key] = json.dumps(value)
        else:
            sanitized[key] = str(value)
    return sanitized


def db_create_with_retry(create_fn, max_retries: int = 3, delay: float = 0.5):
    """Retry helper for SQLite 'database is locked' errors."""
    import time
    last_exc = None
    for attempt in range(max_retries):
        try:
            return create_fn()
        except OperationalError as e:
            if 'database is locked' in str(e).lower():
                last_exc = e
                logger.warning(f"[DB] database is locked -- retry {attempt + 1}/{max_retries} in {delay}s")
                time.sleep(delay)
                delay *= 2
            else:
                raise
    raise last_exc


# ==================== GROQ CLIENT ====================

groq_client = None
try:
    from groq import Groq
    groq_api_key = getattr(settings, 'GROQ_API_KEY', '').strip()
    if groq_api_key and groq_api_key != 'PASTE_YOUR_GROQ_KEY_HERE':
        groq_client = Groq(api_key=groq_api_key)
        logger.info("Groq client initialized successfully (FREE AI)")
    else:
        logger.warning("GROQ_API_KEY not configured - get free key at https://console.groq.com")
except ImportError:
    logger.warning("groq package not installed. Run: pip install groq")
except Exception as e:
    logger.error(f"Failed to initialize Groq client: {e}")


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


embedding_generator = EmbeddingGenerator(model=getattr(settings, 'EMBEDDING_MODEL', 'all-MiniLM-L6-v2'))
vector_store = VectorStore(persist_directory=os.path.join(settings.BASE_DIR, 'chromadb_data'))
document_processor = DocumentProcessor(
    chunk_size=getattr(settings, 'DOCUMENT_CHUNK_SIZE', 500),
    chunk_overlap=getattr(settings, 'DOCUMENT_CHUNK_OVERLAP', 50)
)


# ==================== VIEWSETS ====================

class DocumentIndexViewSet(viewsets.ModelViewSet):
    authentication_classes = [MicroserviceJWTAuthentication]
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        tenant_id = getattr(self.request.user, 'tenant_id', None)
        if not tenant_id:
            return DocumentIndex.objects.none()
        return DocumentIndex.objects.filter(tenant_id=tenant_id).order_by('-created_at')


class ConversationViewSet(viewsets.ModelViewSet):
    authentication_classes = [MicroserviceJWTAuthentication]
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        tenant_id = getattr(self.request.user, 'tenant_id', None)
        user_id = getattr(self.request.user, 'id', None)
        if not tenant_id or not user_id:
            return Conversation.objects.none()
        return Conversation.objects.filter(
            tenant_id=tenant_id, user_id=user_id
        ).order_by('-updated_at')

    def get_serializer_class(self):
        if self.action == 'list':
            return ConversationListSerializer
        elif self.action == 'create':
            return ConversationCreateSerializer
        return ConversationSerializer

    def perform_create(self, serializer):
        serializer.save(
            tenant_id=self.request.user.tenant_id,
            user_id=self.request.user.id
        )

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        conversation = self.get_object()
        conversation.is_active = False
        conversation.save()
        return Response({'message': 'Conversation archived'})

    @action(detail=True, methods=['post'])
    def restore(self, request, pk=None):
        conversation = self.get_object()
        conversation.is_active = True
        conversation.save()
        return Response({'message': 'Conversation restored'})


class ChatMessageViewSet(viewsets.ModelViewSet):
    authentication_classes = [MicroserviceJWTAuthentication]
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        tenant_id = getattr(self.request.user, 'tenant_id', None)
        user_id = getattr(self.request.user, 'id', None)
        if not tenant_id or not user_id:
            return ChatMessage.objects.none()

        conversation_id = self.request.query_params.get('conversation_id')
        if conversation_id:
            return ChatMessage.objects.filter(
                conversation_id=conversation_id,
                conversation__tenant_id=tenant_id,
                conversation__user_id=user_id
            ).select_related('conversation').prefetch_related('sources').order_by('created_at')

        latest = Conversation.objects.filter(
            tenant_id=tenant_id, user_id=user_id, is_active=True
        ).order_by('-updated_at').first()

        if latest:
            return ChatMessage.objects.filter(
                conversation=latest
            ).select_related('conversation').prefetch_related('sources').order_by('created_at')

        return ChatMessage.objects.none()

    def get_serializer_class(self):
        if self.action == 'create':
            return ChatMessageCreateSerializer
        return ChatMessageSerializer

    @action(detail=True, methods=['post'])
    def feedback(self, request, pk=None):
        message = self.get_object()
        serializer = ChatMessageFeedbackSerializer(data=request.data)
        if serializer.is_valid():
            message.feedback = serializer.validated_data['feedback']
            message.save(update_fields=['feedback'])
            return Response({'message': 'Feedback recorded'})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class TenantSettingsViewSet(viewsets.ModelViewSet):
    authentication_classes = [MicroserviceJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = TenantSettingsSerializer

    def get_queryset(self):
        tenant_id = getattr(self.request.user, 'tenant_id', None)
        if not tenant_id:
            return TenantSettings.objects.none()
        return TenantSettings.objects.filter(tenant_id=tenant_id)

    def get_object(self):
        tenant_id = self.request.user.tenant_id
        obj, _ = TenantSettings.objects.get_or_create(tenant_id=tenant_id)
        return obj

    def list(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            return Response(self.get_serializer(instance).data)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# ==================== CHAT QUERY VIEW ====================

MAX_CONTEXT_CHARS = getattr(settings, 'MAX_CONTEXT_CHARS', 12000)
STRICT_FALLBACK_MESSAGE = "Information not available in the current document context."
NO_DOCS_MESSAGE = "No documents are currently uploaded for this tenant."
SUPPORTED_FILE_TYPES = [
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'text/plain',
    'text/csv',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
]


class ChatQueryView(APIView):
    authentication_classes = [MicroserviceJWTAuthentication]
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            message = request.data.get('message')
            conversation_id = request.data.get('conversation_id')

            logger.info(f"Received chat query. Message length: {len(message) if message else 0}")

            if not message:
                return Response({'error': 'Message is required'}, status=status.HTTP_400_BAD_REQUEST)

            tenant_id = get_tenant_id_from_request(request, fallback='default')
            user_id   = get_user_id_from_request(request,   fallback='default')

            if not tenant_id or not user_id:
                return Response({'error': 'Missing tenant_id or user_id'}, status=status.HTTP_400_BAD_REQUEST)

            tenant_id_str = str(tenant_id).strip().lower()
            logger.info(f"[CHAT] Resolved tenant_id={tenant_id_str}, user_id={user_id}")

            if conversation_id:
                try:
                    conversation = Conversation.objects.get(id=conversation_id)
                except Conversation.DoesNotExist:
                    return Response({'error': 'Conversation not found'}, status=status.HTTP_404_NOT_FOUND)
            else:
                conversation = Conversation.objects.filter(
                    tenant_id=tenant_id, user_id=user_id, is_active=True
                ).order_by('-updated_at').first()

                if conversation:
                    logger.info(f"Auto-resumed conversation: {conversation.id}")
                else:
                    conversation = db_create_with_retry(
                        lambda: Conversation.objects.create(
                            tenant_id=tenant_id, user_id=user_id, title=message[:100]
                        )
                    )
                    logger.info(f"Created new conversation: {conversation.id}")

            try:
                tenant_settings = TenantSettings.get_or_create_settings(tenant_id)
            except Exception as e:
                logger.error(f"Error getting tenant settings: {e}")
                return Response({'error': 'Configuration error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            user_message = db_create_with_retry(
                lambda: ChatMessage.objects.create(
                    conversation=conversation, role='user', content=message
                )
            )

            # ── Vector search ──────────────────────────────────────────────────
            results = {'documents': [], 'metadatas': [], 'distances': [], 'count': 0}
            generic_keywords = ["summarize", "summary", "explain", "overview", "describe", "what is in", "list documents"]
            is_generic = any(kw in message.lower() for kw in generic_keywords)

            try:
                k_val = 20 if is_generic else tenant_settings.retrieval_top_k
                query_embedding = embedding_generator.generate_embedding(message)

                active_doc_ids = list(DocumentIndex.objects.filter(
                    tenant_id=tenant_id_str,
                    indexing_status='indexed'
                ).values_list('id', flat=True))

                if not active_doc_ids:
                    logger.warning(f"[CHAT] No indexed documents found for tenant {tenant_id_str}")
                    return Response({
                        'conversation_id': str(conversation.id),
                        'response': NO_DOCS_MESSAGE,
                        'sources': [],
                        'has_context': False
                    }, status=status.HTTP_200_OK)

                search_filter = {'document_id': {'$in': [str(d) for d in active_doc_ids]}}
                logger.info(f"[CHAT] Filtering by {len(active_doc_ids)} indexed documents")

                results = vector_store.query(
                    tenant_id=tenant_id_str,
                    query_embedding=query_embedding,
                    n_results=k_val,
                    filter_metadata=search_filter
                )

                logger.info(f"Vector search returned {results['count']} documents (Filter active: {bool(search_filter)})")
            except Exception as e:
                logger.error(f"Vector store search error: {e}", exc_info=True)

            # ── Build context ──────────────────────────────────────────────────
            context = ""
            sources_data = []
            total_context_chars = 0
            RELEVANCE_THRESHOLD = tenant_settings.relevance_threshold
            GRACE_MARGIN = 0.05

            for i, (doc_content, meta, dist) in enumerate(
                zip(results['documents'], results['metadatas'], results['distances'])
            ):
                similarity = calculate_relevance_score(dist)
                is_top = (i == 0)

                if not is_generic and similarity < RELEVANCE_THRESHOLD:
                    if is_top and similarity >= (RELEVANCE_THRESHOLD - GRACE_MARGIN):
                        logger.info(f"[CHAT] Allowing top chunk via grace margin (score={similarity:.4f})")
                    else:
                        continue

                if total_context_chars + len(doc_content) > MAX_CONTEXT_CHARS:
                    remaining = MAX_CONTEXT_CHARS - total_context_chars
                    if remaining > 100:
                        doc_content = doc_content[:remaining]
                    else:
                        break

                context += f"\n\n[Document Content]\n{doc_content}"
                total_context_chars += len(doc_content)
                sources_data.append({
                    'document_id':    meta.get('document_id'),
                    'chunk_index':    meta.get('chunk_index', 0),
                    'content':        doc_content,
                    'relevance_score': similarity,
                    'metadata':       meta,
                    'file_name':      meta.get('file_name', ''),
                    'title':          meta.get('title', ''),
                    'page':           meta.get('page'),
                    'upload_date':    meta.get('upload_date', ''),
                })

            logger.info(f"Context built: {len(sources_data)} source(s), {total_context_chars} chars")

            ai_response = self._generate_ai_response(message, context, sources_data)

            if ai_response == STRICT_FALLBACK_MESSAGE:
                sources_data = []

            assistant_message = db_create_with_retry(
                lambda: ChatMessage.objects.create(
                    conversation=conversation,
                    role='assistant',
                    content=ai_response,
                    num_sources=len(sources_data),
                    confidence_score=sources_data[0]['relevance_score'] if sources_data else None,
                    tokens_used=0
                )
            )

            for source_data in sources_data:
                try:
                    document = DocumentIndex.objects.get(id=source_data['document_id'])
                    MessageSource.objects.create(
                        message=assistant_message,
                        document=document,
                        chunk_index=source_data['chunk_index'],
                        relevance_score=source_data['relevance_score']
                    )
                except DocumentIndex.DoesNotExist:
                    logger.warning(f"Document {source_data['document_id']} not found")
                except Exception as e:
                    logger.error(f"Error creating MessageSource: {e}")

            try:
                RAGUsageStats.increment_queries(tenant_id, user_id)
            except Exception as e:
                logger.error(f"Error incrementing usage stats: {e}")

            return Response({
                'conversation_id': str(conversation.id),
                'message_id':      str(assistant_message.id),
                'response':        ai_response,
                'sources': [
                    {
                        'content':         s['content'][:200] + '...' if len(s['content']) > 200 else s['content'],
                        'relevance_score': round(s['relevance_score'], 4),
                        'document_id':     str(s['document_id']),
                        'file_name':       s.get('file_name', ''),
                        'title':           s.get('title', ''),
                        'page':            s.get('page'),
                        'upload_date':     s.get('upload_date', ''),
                    }
                    for s in sources_data
                ],
                'has_context': bool(context) and len(sources_data) > 0,
                'num_sources': len(sources_data)
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Unexpected error in ChatQueryView: {e}", exc_info=True)
            return Response(
                {'error': f'Internal server error: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _generate_ai_response(self, message: str, context: str, sources_data: List[Dict]) -> str:
        if groq_client:
            try:
                system_prompt = (
                    "You are a document-based AI assistant named TenantIQ. "
                    "Answer STRICTLY based on the provided document context. "
                    "If the answer is in the documents, give a clear, factual, direct response. "
                    "Use professional Markdown: tables for tabular data, bullet points for lists, bold for key terms. "
                    "Do not use general knowledge. Do not guess. Only use provided document data. "
                    "If information is missing say: 'Information not available in the current document context.' "
                    "Return only the answer with NO technical metadata or document IDs."
                )

                if not context:
                    logger.info("No context available -- returning fallback.")
                    return STRICT_FALLBACK_MESSAGE

                user_prompt = f"Context from uploaded documents:\n{context}\n\nQuestion: {message}"
                groq_model = getattr(settings, 'GROQ_MODEL', 'llama-3.1-8b-instant')
                logger.info(f"Calling Groq API: model={groq_model}, context={len(context)} chars")

                response = groq_client.chat.completions.create(
                    model=groq_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_prompt}
                    ],
                    temperature=0.3,
                    max_tokens=800
                )

                ai_response = response.choices[0].message.content.strip()
                ai_response = ai_response.replace("[Document Content]", "").strip()
                logger.info(f"Groq response received ({groq_model})")
                return ai_response

            except Exception as e:
                logger.error(f"Groq API error: {e}", exc_info=True)

        return STRICT_FALLBACK_MESSAGE


# ==================== WEBHOOK VIEW ====================

class DocumentIndexWebhookView(APIView):
    authentication_classes = [APIKeyAuthentication]
    throttle_classes = []

    def post(self, request):
        doc_index = None
        try:
            # Support both flat payload and WebhookSender envelope {"data": {...}}
            payload_wrapper = request.data
            data = payload_wrapper.get('data', payload_wrapper)

            document_id = data.get('document_id')
            tenant_id   = data.get('tenant_id')
            user_id     = data.get('user_id')
            file_path   = data.get('file_path')
            file_type   = data.get('file_type')
            title       = data.get('title', 'Untitled')
            file_name   = data.get('file_name', 'unknown')
            file_size   = data.get('file_size', 0)
            category    = data.get('category', '')
            tags        = data.get('tags', [])

            logger.info(f"[WEBHOOK] Indexing request -- document: {document_id}, tenant: {tenant_id}")
            logger.info(f"[WEBHOOK] File: {file_path} ({file_type})")

            required = {
                'document_id': document_id,
                'tenant_id':   tenant_id,
                'user_id':     user_id,
                'file_path':   file_path,
                'file_type':   file_type,
            }
            missing = [k for k, v in required.items() if not v]
            if missing:
                logger.error(f"[WEBHOOK] Missing fields: {missing}")
                return Response({'error': f'Missing required fields: {missing}'}, status=status.HTTP_400_BAD_REQUEST)

            if file_type not in SUPPORTED_FILE_TYPES:
                logger.warning(f"[WEBHOOK] Unsupported file type: {file_type} -- will attempt anyway")

            if not os.path.exists(file_path):
                logger.error(f"[WEBHOOK] File not found: {file_path}")
                return Response({'error': f'File not found: {file_path}'}, status=status.HTTP_400_BAD_REQUEST)

            logger.info(f"[WEBHOOK] File confirmed on disk: {file_path}")
            tenant_id = str(tenant_id).strip().lower()
            tenant_settings = TenantSettings.get_or_create_settings(tenant_id)

            # ── Upsert DocumentIndex record ──────────────────────────────────
            with transaction.atomic():
                doc_index, created = DocumentIndex.objects.get_or_create(
                    id=document_id,
                    defaults={
                        'tenant_id':       tenant_id,
                        'title':           title,
                        'file_name':       file_name,
                        'file_type':       file_type,
                        'file_size':       file_size,
                        'indexing_status': 'pending',
                    }
                )
                if not created:
                    doc_index.indexing_status = 'pending'
                    doc_index.save(update_fields=['indexing_status'])

            logger.info(f"[WEBHOOK] Document record {'created' if created else 'found'}: {document_id}")
            doc_index.mark_processing()

            # Force sync processing if worker is down (or CELERY_TASK_ALWAYS_EAGER is True)
            try:
                from .tasks import index_document_task
                if getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False):
                    logger.info(f"[WEBHOOK] Running indexing task in background thread for {document_id}")
                    # Use a background thread instead of direct synchronous call to avoid 10s webhook timeout!
                    import threading
                    metadata_payload = {
                        "title": title,
                        "file_name": file_name,
                        "file_type": file_type,
                        "file_size": file_size,
                        "category": category,
                        "tags": tags,
                    }
                    def run_task():
                        # The task object's __call__ expects the task as the first argument, 
                        # but as a background thread, we should invoke the original function.
                        # Since it's a @shared_task, we can just call it like a function.
                        # Celery handles bind=True correctly when called eagerly.
                        try:
                            index_document_task(
                                str(document_id),
                                str(tenant_id),
                                file_path=str(file_path),
                                user_id=str(user_id),
                                metadata=metadata_payload,
                            )
                        except Exception as e:
                            logger.error(f"[WEBHOOK-THREAD] Background task failed: {e}")

                    t = threading.Thread(target=run_task)
                    t.start()
                    
                    return Response(
                        {"message": "Indexing started (background thread)", "document_id": str(document_id), "status": "processing"},
                        status=status.HTTP_202_ACCEPTED,
                    )
                else:
                    index_document_task.delay(
                        str(document_id),
                        str(tenant_id),
                        file_path=str(file_path),
                        user_id=str(user_id),
                        metadata={
                            "title": title,
                            "file_name": file_name,
                            "file_type": file_type,
                            "file_size": file_size,
                            "category": category,
                            "tags": tags,
                        },
                    )
                    logger.info(f"[WEBHOOK] Queued Celery indexing task for {document_id} (tenant={tenant_id})")
                    return Response(
                        {"message": "Indexing started (async)", "document_id": str(document_id), "status": "processing"},
                        status=status.HTTP_202_ACCEPTED,
                    )
            except Exception as queue_err:
                logger.warning(
                    f"[WEBHOOK] Celery queueing failed; falling back to sync indexing for {document_id}. "
                    f"Error: {queue_err}"
                )

            start_time = timezone.now()

            # Sanitize initial metadata (converts tags list -> comma string, etc.)
            initial_metadata = sanitize_metadata_for_chromadb({
                'document_id': str(document_id),
                'tenant_id':   str(tenant_id),
                'title':       title,
                'file_name':   file_name,
                'file_type':   file_type,
                'file_size':   file_size,
                'category':    category,
                'tags':        tags,
                'upload_date': timezone.now().isoformat()
            })

            # ── Process document into chunks ─────────────────────────────────
            try:
                chunks = document_processor.process_document(
                    file_path=file_path,
                    document_id=str(document_id),
                    metadata=initial_metadata
                )
            except ValueError as e:
                logger.error(f"[WEBHOOK] Processing error: {e}")
                doc_index.mark_failed(str(e))
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

            if not chunks:
                logger.error(f"[WEBHOOK] No chunks extracted from: {file_path}")
                doc_index.mark_failed("No chunks extracted")
                return Response({'error': 'No text content extracted'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            logger.info(f"[WEBHOOK] Extracted {len(chunks)} chunks")

            if len(chunks) > tenant_settings.max_chunks_per_document:
                msg = f"Exceeds chunk limit ({tenant_settings.max_chunks_per_document})"
                doc_index.mark_failed(msg)
                return Response({'error': 'Document too large'}, status=status.HTTP_400_BAD_REQUEST)

            # ── Generate embeddings ──────────────────────────────────────────
            try:
                chunk_texts = [chunk.content for chunk in chunks]
                embeddings = embedding_generator.generate_embeddings_batch(chunk_texts)
                # Sanitize each chunk's metadata -- document_processor may add list fields
                chunk_metadatas = [
                    sanitize_metadata_for_chromadb(chunk.metadata) for chunk in chunks
                ]
            except Exception as e:
                logger.error(f"[WEBHOOK] Embedding error: {e}")
                doc_index.mark_failed(f"Embedding failed: {str(e)}")
                return Response({'error': 'Failed to generate embeddings'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # ── Add to vector store ──────────────────────────────────────────
            logger.info(f"[WEBHOOK] Adding {len(chunks)} chunks to vector store...")
            try:
                vector_store.add_documents(
                    tenant_id=str(tenant_id),
                    documents=chunk_texts,
                    embeddings=embeddings,
                    metadatas=chunk_metadatas,
                    document_id=str(document_id)
                )
                success = True
            except Exception as e:
                logger.error(f"[WEBHOOK] Vector store error: {e}")
                success = False

            if success:
                processing_time = (timezone.now() - start_time).total_seconds()
                total_tokens = sum(chunk.token_count for chunk in chunks)

                with transaction.atomic():
                    doc_index.mark_completed(
                        num_chunks=len(chunks),
                        total_tokens=total_tokens,
                        processing_time=processing_time
                    )

                # Notify document service that this document is now indexed / ready
                try:
                    callback_url = (
                        f"{settings.DOCUMENT_SERVICE_URL}"
                        f"/api/doc/documents/{document_id}/update-index-status/"
                    )
                    payload = {
                        "indexing_status": "indexed",
                        "is_indexed": True,
                        "tenant_id": str(tenant_id),
                    }
                    resp = requests.post(
                        callback_url,
                        json=payload,
                        headers={
                            "X-API-Key": getattr(settings, "DOCUMENT_SERVICE_WEBHOOK_API_KEY", getattr(settings, "WEBHOOK_API_KEY", "")),
                            "Content-Type": "application/json",
                        },
                        timeout=5,
                    )
                    logger.info(
                        f"[WEBHOOK] Notified document service of indexed status "
                        f"for {document_id}: HTTP {resp.status_code} Body={resp.text[:300]}"
                    )
                except Exception as notify_err:
                    logger.warning(
                        f"[WEBHOOK] Failed to notify document service for {document_id}: "
                        f"{notify_err}"
                    )

                try:
                    RAGUsageStats.increment_documents(
                        str(tenant_id), str(user_id),
                        num_chunks=len(chunks), total_tokens=total_tokens
                    )
                except Exception as e:
                    logger.error(f"Error updating usage stats: {e}")

                logger.info(
                    f"[WEBHOOK] SUCCESS -- Document {document_id} indexed (sync): "
                    f"{len(chunks)} chunks in {processing_time:.2f}s"
                )

                return Response({
                    'message':          'Document indexed successfully',
                    'document_id':      str(document_id),
                    'chunks_created':   len(chunks),
                    'total_tokens':     total_tokens,
                    'processing_time':  processing_time
                }, status=status.HTTP_200_OK)

            else:
                doc_index.mark_failed("Failed to add to vector store")
                return Response({'error': 'Failed to index document'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        except Exception as e:
            logger.error(f"[WEBHOOK] Unexpected error: {e}", exc_info=True)
            if doc_index is not None:
                try:
                    doc_index.mark_failed(str(e))
                except Exception:
                    pass

            # Best-effort failure notification back to document service
            try:
                if 'document_id' in locals() and 'tenant_id' in locals():
                    callback_url = (
                        f"{settings.DOCUMENT_SERVICE_URL}"
                        f"/api/doc/documents/{document_id}/update-index-status/"
                    )
                    payload = {
                        "indexing_status": "failed",
                        "is_indexed": False,
                        "tenant_id": str(tenant_id),
                    }
                    resp = requests.post(
                        callback_url,
                        json=payload,
                        headers={
                            "X-API-Key": getattr(settings, "DOCUMENT_SERVICE_WEBHOOK_API_KEY", getattr(settings, "WEBHOOK_API_KEY", "")),
                            "Content-Type": "application/json",
                        },
                        timeout=5,
                    )
                    logger.info(
                        f"[WEBHOOK] Notified document service of failed status "
                        f"for {document_id}: HTTP {resp.status_code} Body={resp.text[:300]}"
                    )
            except Exception as notify_err:
                logger.warning(
                    f"[WEBHOOK] Failed to notify document service about failure "
                    f"for {document_id}: {notify_err}"
                )

            return Response(
                {'error': f'Internal server error: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DocumentDeleteWebhookView(APIView):
    authentication_classes = [APIKeyAuthentication]
    throttle_classes = []

    def post(self, request):
        try:
            # Support both flat payload and WebhookSender envelope {"data": {...}}
            payload_wrapper = request.data
            data = payload_wrapper.get('data', payload_wrapper)

            document_id = data.get('document_id')
            tenant_id   = data.get('tenant_id')

            if not document_id or not tenant_id:
                logger.error(f"[WEBHOOK] Delete request missing IDs. Data: {data}")
                return Response(
                    {'error': 'document_id and tenant_id are required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            logger.info(f"[WEBHOOK] Delete request -- document: {document_id}, tenant: {tenant_id}")

            # ── IMMEDIATE LOCKOUT (Synchronous) ──
            # Delete index and citation records immediately so they are hidden from the retriever,
            # even if the background vector store purge is still pending.
            try:
                from django.db import transaction
                from .models import DocumentIndex, MessageSource

                with transaction.atomic():
                    sources_deleted, _ = MessageSource.objects.filter(document_id=document_id).delete()
                    docs_deleted, _ = DocumentIndex.objects.filter(id=document_id).delete()

                    if sources_deleted or docs_deleted:
                        logger.info(f"[WEBHOOK] Immediate lockout: deleted {docs_deleted} index and {sources_deleted} source records for {document_id}")
            except Exception as lockout_e:
                logger.error(f"[WEBHOOK] Sync lockout failed for {document_id}: {lockout_e}")

            # ── ASYNC PURGE (Background) ──
            try:
                from .tasks import delete_document_task
                delete_document_task.delay(str(document_id), str(tenant_id))
                logger.info(f"[WEBHOOK] Queued delete_document_task for {document_id}")
            except Exception as e:
                logger.error(f"[WEBHOOK] Failed to queue delete task: {e}")
                # Fallback to sync deletion if Celery fails
                try:
                    num_deleted = vector_store.delete_document(str(tenant_id), str(document_id))
                    DocumentIndex.objects.filter(id=document_id).delete()
                    logger.info(f"[WEBHOOK] Synced deletion fallback for {document_id} (chunks: {num_deleted})")
                except Exception as sync_e:
                    logger.error(f"[WEBHOOK] Sync deletion fallback failed: {sync_e}")

            return Response({
                'status':      'accepted',
                'document_id': str(document_id),
                'message':     'Document deletion queued'
            }, status=status.HTTP_202_ACCEPTED)

        except Exception as e:
            logger.error(f"[WEBHOOK] Unexpected delete webhook error: {e}", exc_info=True)
            return Response(
                {'error': 'Internal server error during document deletion'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ==================== STATS & HEALTH VIEWS ====================

class RAGStatsView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            tenant_id = get_tenant_id_from_request(request, fallback='default')
            logger.info(f"[STATS] Resolved tenant_id={tenant_id}")

            doc_stats = DocumentIndex.objects.filter(tenant_id=tenant_id).aggregate(
                total_documents=Count('id'),
                completed_documents=Count('id', filter=Q(indexing_status='indexed')),
                failed_documents=Count('id', filter=Q(indexing_status='failed')),
                total_chunks=Sum('num_chunks'),
                total_tokens=Sum('total_tokens')
            )

            thirty_days_ago = timezone.now().date() - timedelta(days=30)
            usage_stats = RAGUsageStats.objects.filter(
                tenant_id=tenant_id, date__gte=thirty_days_ago
            ).aggregate(
                total_queries=Sum('queries_count'),
                total_documents_indexed=Sum('documents_indexed')
            )

            vs_stats = vector_store.get_stats(str(tenant_id))

            return Response({
                'documents': {
                    'total':        doc_stats['total_documents'] or 0,
                    'completed':    doc_stats['completed_documents'] or 0,
                    'failed':       doc_stats['failed_documents'] or 0,
                    'total_chunks': doc_stats['total_chunks'] or 0,
                    'total_tokens': doc_stats['total_tokens'] or 0,
                },
                'usage_last_30_days': {
                    'queries':           usage_stats['total_queries'] or 0,
                    'documents_indexed': usage_stats['total_documents_indexed'] or 0,
                },
                'vector_store_ready':   True,
                'vector_store_backend': 'chroma',
                'vector_store_stats':   vs_stats
            })
        except Exception as e:
            logger.error(f"Error in RAGStatsView: {e}", exc_info=True)
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class UsageStatsView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            tenant_id  = get_tenant_id_from_request(request, fallback='default')
            user_id    = get_user_id_from_request(request,   fallback='default')
            end_date   = request.query_params.get('end_date')
            start_date = request.query_params.get('start_date')
            end_date   = datetime.strptime(end_date,   '%Y-%m-%d').date() if end_date   else timezone.now().date()
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date() if start_date else end_date - timedelta(days=30)

            stats = RAGUsageStats.objects.filter(
                tenant_id=tenant_id, user_id=user_id,
                date__gte=start_date, date__lte=end_date
            ).order_by('date')

            summary = stats.aggregate(
                total_queries=Sum('queries_count'),
                total_documents=Sum('documents_indexed'),
                total_chunks=Sum('total_chunks'),
                total_tokens=Sum('total_tokens')
            )

            return Response({
                'summary': RAGUsageStatsSummarySerializer({
                    'total_queries':    summary['total_queries']   or 0,
                    'total_documents':  summary['total_documents'] or 0,
                    'total_chunks':     summary['total_chunks']    or 0,
                    'total_tokens':     summary['total_tokens']    or 0,
                    'date_range_start': start_date,
                    'date_range_end':   end_date
                }).data,
                'daily_stats': RAGUsageStatsSerializer(stats, many=True).data
            })
        except Exception as e:
            logger.error(f"Error in UsageStatsView: {e}", exc_info=True)
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class HealthCheckView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({
            'status':               'healthy',
            'service':              'AI Chat Service',
            'ai_provider':          getattr(settings, 'AI_PROVIDER', 'groq'),
            'groq_configured':      groq_client is not None,
            'groq_model':           getattr(settings, 'GROQ_MODEL', 'llama-3.1-8b-instant'),
            'embeddings':           'sentence-transformers (FREE, local)',
            'vector_store_backend': 'chroma',
            'max_context_chars':    MAX_CONTEXT_CHARS,
            'supported_file_types': ['.pdf', '.docx', '.txt'],
            'timestamp':            timezone.now().isoformat()
        })



# End of views
