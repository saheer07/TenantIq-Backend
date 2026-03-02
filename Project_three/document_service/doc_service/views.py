from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.shortcuts import get_object_or_404
from django.views.decorators.clickjacking import xframe_options_exempt
from django.utils.decorators import method_decorator
from django.db.models import Q
from django.conf import settings
import traceback
import requests
import logging
import time
import os

from .models import (
    Document,
    DocumentCategory,
    DocumentChunk,
    DocumentAccessLog,
)
from .serializers import (
    DocumentSerializer,
    DocumentListSerializer,
    DocumentCategorySerializer,
    DocumentShareSerializer,
    DocumentAccessLogSerializer,
    DocumentUploadSerializer,
    BulkDocumentOperationSerializer,
)
from .authentication import MicroserviceJWTAuthentication, APIKeyAuthentication
from .webhook_events import (
    trigger_document_uploaded,
    trigger_document_deleted,
    trigger_document_reindex
)

logger = logging.getLogger(__name__)


# ==================== HELPER FUNCTIONS ====================

def require_tenant(view_func):
    """Decorator to ensure tenant_id is present in request."""
    def wrapped_view(self, request, *args, **kwargs):
        tenant_id = getattr(request, 'tenant_id', None)
        if not tenant_id:
            logger.error(f"[AUTH] Tenant ID missing for {request.method} {request.path}")
            return Response(
                {
                    "error": "Tenant identification failed",
                    "detail": "No tenant ID found in JWT or X-Tenant-ID header.",
                    "code": "tenant_missing"
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        return view_func(self, request, *args, **kwargs)
    return wrapped_view


def log_document_access(document, user_id, action, request):
    """Helper to log document access."""
    try:
        DocumentAccessLog.objects.create(
            document_id=document.id,
            user_id=user_id,
            action=action,
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
        )
    except Exception as e:
        logger.warning(f"Failed to log access: {e}")


def get_client_ip(request):
    """Extract client IP from request."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


# ==================== CATEGORY VIEWS ====================

class CategoryListCreateView(APIView):
    """List and create document categories."""
    authentication_classes = [MicroserviceJWTAuthentication]
    permission_classes = [IsAuthenticated]

    @require_tenant
    def get(self, request):
        try:
            categories = DocumentCategory.objects.filter(
                tenant_id=request.tenant_id
            ).order_by('order', 'name')
            serializer = DocumentCategorySerializer(categories, many=True, context={'request': request})
            return Response(serializer.data)
        except Exception as e:
            logger.error(f"Error listing categories: {e}\n{traceback.format_exc()}")
            return Response({"error": "Failed to list categories"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @require_tenant
    def post(self, request):
        try:
            serializer = DocumentCategorySerializer(data=request.data, context={'request': request})
            if serializer.is_valid():
                category = serializer.save(tenant_id=request.tenant_id)
                logger.info(f"Category created: {category.name} for tenant {request.tenant_id}")
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error creating category: {e}\n{traceback.format_exc()}")
            return Response({"error": f"Failed to create category: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CategoryDetailView(APIView):
    """Retrieve, update, delete category."""
    authentication_classes = [MicroserviceJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get_object(self, pk, tenant_id):
        return get_object_or_404(DocumentCategory, pk=pk, tenant_id=tenant_id)

    @require_tenant
    def get(self, request, pk):
        try:
            category = self.get_object(pk, request.tenant_id)
            serializer = DocumentCategorySerializer(category, context={'request': request})
            return Response(serializer.data)
        except Exception as e:
            logger.error(f"Error viewing category {pk}: {e}")
            return Response({"error": "Category not found"}, status=status.HTTP_404_NOT_FOUND)

    @require_tenant
    def put(self, request, pk):
        try:
            category = self.get_object(pk, request.tenant_id)
            serializer = DocumentCategorySerializer(
                category, data=request.data, partial=True, context={'request': request}
            )
            if serializer.is_valid():
                serializer.save()
                logger.info(f"Category updated: {category.name}")
                return Response(serializer.data)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error updating category {pk}: {e}")
            return Response({"error": "Failed to update category"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @require_tenant
    def delete(self, request, pk):
        try:
            category = self.get_object(pk, request.tenant_id)

            doc_count = Document.objects.filter(category_id=category.id, tenant_id=request.tenant_id).count()
            if doc_count > 0:
                return Response(
                    {"error": f"Cannot delete category with {doc_count} documents"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            subcat_count = DocumentCategory.objects.filter(parent_id=category.id, tenant_id=request.tenant_id).count()
            if subcat_count > 0:
                return Response(
                    {"error": f"Cannot delete category with {subcat_count} subcategories"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            category_name = category.name
            category.delete()
            logger.info(f"Category deleted: {category_name}")
            return Response({"message": "Category deleted successfully"}, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error deleting category {pk}: {e}")
            return Response({"error": "Failed to delete category"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==================== DOCUMENT VIEWS ====================

class DocumentListCreateView(APIView):
    """List and upload documents with tenant isolation."""
    authentication_classes = [MicroserviceJWTAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @require_tenant
    def get(self, request):
        try:
            queryset = Document.objects.filter(tenant_id=request.tenant_id).order_by('-created_at')

            user_id_str = str(request.user.id)

            # FIX: SQLite does not support __contains on JSONFields.
            # shared_with_ids is a JSON array of user ID strings stored as text.
            # We use a raw LIKE query instead, which works on SQLite and PostgreSQL.
            user_filter = (
                Q(uploaded_by_id=request.user.id) |
                Q(is_public=True) |
                Q(shared_with_ids__icontains=user_id_str)
            )
            queryset = queryset.filter(user_filter)

            category_id = request.query_params.get('category')
            if category_id:
                queryset = queryset.filter(category_id=category_id)

            search = request.query_params.get('search')
            if search:
                queryset = queryset.filter(
                    Q(title__icontains=search) |
                    Q(description__icontains=search) |
                    Q(file_name__icontains=search)
                )

            indexing_status = request.query_params.get('status')
            if indexing_status:
                queryset = queryset.filter(indexing_status=indexing_status)

            # FIX: SQLite does not support tags__contains=[tag] on JSONFields.
            # Use icontains on the serialised JSON text instead.
            tag = request.query_params.get('tag')
            if tag:
                queryset = queryset.filter(tags__icontains=tag)

            serializer = DocumentListSerializer(queryset, many=True, context={'request': request})
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Error listing documents: {e}\n{traceback.format_exc()}")
            return Response({"error": "Failed to list documents"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @require_tenant
    def post(self, request):
        """Upload a new document and trigger indexing in chatbot service."""
        try:
            logger.info(f"[UPLOAD] User: {request.user.id}, Tenant: {request.tenant_id}")

            upload_serializer = DocumentUploadSerializer(data=request.data, context={'request': request})
            if not upload_serializer.is_valid():
                logger.error(f"[UPLOAD] Validation failed: {upload_serializer.errors}")
                return Response(upload_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            file = upload_serializer.validated_data['file']
            logger.info(f"[UPLOAD] File: {file.name} ({file.size} bytes)")

            data = {
                'title': upload_serializer.validated_data.get('title', file.name),
                'description': upload_serializer.validated_data.get('description', ''),
                'file': file,
                'is_public': upload_serializer.validated_data.get('is_public', False),
                'tags': upload_serializer.validated_data.get('tags', []),
                'category_id': upload_serializer.validated_data.get('category_id'),
            }

            serializer = DocumentSerializer(data=data, context={'request': request})
            if serializer.is_valid():
                document = serializer.save(
                    tenant_id=request.tenant_id,
                    uploaded_by_id=request.user.id,
                    indexing_status='processing',
                    is_indexed=False
                )
                logger.info(f"[UPLOAD] Document saved to DB: {document.id}")
                log_document_access(document, request.user.id, 'upload', request)

                # Brief pause to ensure file is fully written to disk
                time.sleep(0.5)

                logger.info(f"[UPLOAD] Triggering chatbot indexing for document {document.id}...")
                index_success = trigger_document_uploaded(document)

                if index_success:
                    logger.info(f"[UPLOAD] Document {document.id} queued for indexing successfully")
                else:
                    logger.warning(
                        f"[UPLOAD] Document {document.id} saved but indexing failed. "
                        f"Use the re-index endpoint to retry."
                    )

                return Response(serializer.data, status=status.HTTP_201_CREATED)

            else:
                logger.error(f"[UPLOAD] Serializer errors: {serializer.errors}")
                return Response(
                    {
                        "error": "Document creation failed",
                        "validation_errors": serializer.errors
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

        except Exception as e:
            logger.error(f"[UPLOAD] ERROR: {str(e)}\n{traceback.format_exc()}")
            return Response({"error": f"Upload failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(xframe_options_exempt, name='dispatch')
class DocumentDetailView(APIView):
    """View, update, delete document with tenant isolation."""
    authentication_classes = [MicroserviceJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get_object(self, pk, tenant_id, user_id):
        document = get_object_or_404(Document, pk=pk, tenant_id=tenant_id)
        if not document.can_be_accessed_by(user_id):
            raise PermissionError("You don't have access to this document")
        return document

    @require_tenant
    def get(self, request, pk):
        try:
            document = self.get_object(pk, request.tenant_id, request.user.id)
            log_document_access(document, request.user.id, 'view', request)
            serializer = DocumentSerializer(document, context={'request': request})
            return Response(serializer.data)
        except PermissionError as e:
            return Response({"error": str(e)}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            logger.error(f"Error viewing document {pk}: {str(e)}")
            return Response({"error": "Document not found"}, status=status.HTTP_404_NOT_FOUND)

    @require_tenant
    def put(self, request, pk):
        try:
            document = self.get_object(pk, request.tenant_id, request.user.id)

            if str(document.uploaded_by_id) != str(request.user.id):
                return Response({"error": "Only owner can update document"}, status=status.HTTP_403_FORBIDDEN)

            serializer = DocumentSerializer(document, data=request.data, partial=True, context={'request': request})
            if serializer.is_valid():
                serializer.save()
                log_document_access(document, request.user.id, 'update', request)
                logger.info(f"Document updated: {document.id}")
                return Response(serializer.data)

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except PermissionError as e:
            return Response({"error": str(e)}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            logger.error(f"Error updating document {pk}: {e}")
            return Response({"error": "Failed to update document"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @require_tenant
    def delete(self, request, pk):
        """Delete a document — related records deleted first to avoid FK violations."""
        try:
            logger.info(f"DELETE request for document {pk}")
            document = self.get_object(pk, request.tenant_id, request.user.id)

            if str(document.uploaded_by_id) != str(request.user.id):
                return Response({"error": "Only owner can delete document"}, status=status.HTTP_403_FORBIDDEN)

            document_id = document.id
            file_name = document.file_name

            # Step 1: Delete related records first
            access_log_count = DocumentAccessLog.objects.filter(document_id=document_id).count()
            DocumentAccessLog.objects.filter(document_id=document_id).delete()
            logger.info(f"Deleted {access_log_count} access logs for document {document_id}")

            chunk_count = DocumentChunk.objects.filter(document_id=document_id).count()
            DocumentChunk.objects.filter(document_id=document_id).delete()
            logger.info(f"Deleted {chunk_count} chunks for document {document_id}")

            # Step 2: Delete the physical file
            if document.file:
                try:
                    document.file.delete(save=False)
                    logger.info(f"File deleted: {file_name}")
                except Exception as e:
                    logger.warning(f"Could not delete file: {e}")

            # Step 3: Trigger deletion sync with chatbot service
            trigger_document_deleted(str(document_id), str(request.tenant_id))

            # Step 4: Delete the document record
            document.delete()
            logger.info(f"Document {pk} deleted successfully")

            return Response(
                {"success": True, "message": "Document deleted successfully"},
                status=status.HTTP_200_OK
            )

        except PermissionError as e:
            return Response({"error": str(e)}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            logger.error(f"DELETE ERROR for document {pk}: {str(e)}\n{traceback.format_exc()}")
            return Response(
                {"error": f"Failed to delete document: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DocumentShareView(APIView):
    """Share document with other users in the same tenant."""
    authentication_classes = [MicroserviceJWTAuthentication]
    permission_classes = [IsAuthenticated]

    @require_tenant
    def post(self, request, pk):
        try:
            document = get_object_or_404(Document, pk=pk, tenant_id=request.tenant_id)

            if str(document.uploaded_by_id) != str(request.user.id):
                return Response({"error": "Only owner can share document"}, status=status.HTTP_403_FORBIDDEN)

            serializer = DocumentShareSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            user_ids = [str(uid) for uid in serializer.validated_data["user_ids"]]
            document.shared_with_ids = user_ids
            document.save(update_fields=['shared_with_ids', 'updated_at'])

            log_document_access(document, request.user.id, 'share', request)
            logger.info(f"Document {pk} shared with {len(user_ids)} users")

            return Response({
                "message": "Document shared successfully",
                "shared_with_count": len(user_ids)
            })

        except Exception as e:
            logger.error(f"Error sharing document: {e}")
            return Response(
                {"error": f"Failed to share document: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DocumentIndexStatusView(APIView):
    """Webhook for chatbot to update indexing status back on the document record."""
    authentication_classes = [APIKeyAuthentication, MicroserviceJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            # Try to get tenant_id from request (middleware) or body
            tenant_id = getattr(request, 'tenant_id', None) or request.data.get('tenant_id')
            if not tenant_id:
                logger.error(f"[STATUS] Tenant ID missing in request for doc {pk}")
                return Response({'error': 'tenant_id required'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Stringify tenant_id for consistency
            tenant_id = str(tenant_id)
            
            logger.info(f"[STATUS] Attempting update for doc {pk} (Tenant: {tenant_id})")
            document = get_object_or_404(Document, pk=pk, tenant_id=tenant_id)
            indexing_status = request.data.get('indexing_status')
            is_indexed = request.data.get('is_indexed', False)

            if not indexing_status:
                logger.warning(f"[STATUS] Missing indexing_status in request for doc {pk}")
                return Response({'error': 'indexing_status required'}, status=status.HTTP_400_BAD_REQUEST)

            logger.info(f"[STATUS] Received update for doc {pk}: {indexing_status} (is_indexed={is_indexed})")
            
            document.indexing_status = indexing_status
            document.is_indexed = is_indexed
            document.save(update_fields=['indexing_status', 'is_indexed', 'updated_at'])
            logger.info(f"[STATUS] Successfully updated document {pk} in DB: indexing_status={document.indexing_status}, is_indexed={document.is_indexed}")

            return Response({
                'message': 'Status updated successfully',
                'document_id': str(pk),
                'indexing_status': document.indexing_status,
                'is_indexed': document.is_indexed
            })

        except Exception as e:
            logger.error(f"Error updating status: {e}")
            return Response({'error': 'Failed to update status'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DocumentReIndexView(APIView):
    """
    Re-trigger indexing for a document that previously failed or needs refreshing.

    POST /api/documents/<pk>/re-index/
    """
    authentication_classes = [MicroserviceJWTAuthentication]
    permission_classes = [IsAuthenticated]

    @require_tenant
    def post(self, request, pk):
        try:
            document = get_object_or_404(Document, pk=pk, tenant_id=request.tenant_id)

            if str(document.uploaded_by_id) != str(request.user.id):
                return Response(
                    {"error": "Only the document owner can trigger re-indexing"},
                    status=status.HTTP_403_FORBIDDEN
                )

            if not document.file:
                return Response(
                    {"error": "Document has no file attached"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            logger.info(f"[RE-INDEX] Triggered for document {document.id} by user {request.user.id}")

            # Reset status before re-indexing
            Document.objects.filter(id=document.id).update(
                indexing_status='pending',
                is_indexed=False
            )
            document.refresh_from_db()

            success = trigger_document_reindex(document)

            if success:
                return Response({
                    "message": "Re-indexing triggered successfully",
                    "document_id": str(document.id),
                    "indexing_status": "processing"
                })
            else:
                return Response(
                    {"error": "Failed to trigger re-indexing — check chatbot service logs"},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE
                )

        except Exception as e:
            logger.error(f"Re-index error for document {pk}: {e}\n{traceback.format_exc()}")
            return Response(
                {"error": f"Re-index failed: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DocumentAccessLogView(APIView):
    """View access logs for documents."""
    authentication_classes = [MicroserviceJWTAuthentication]
    permission_classes = [IsAuthenticated]

    @require_tenant
    def get(self, request, pk=None):
        try:
            if pk:
                document = get_object_or_404(Document, pk=pk, tenant_id=request.tenant_id)
                if str(document.uploaded_by_id) != str(request.user.id):
                    return Response({"error": "Only owner can view access logs"}, status=status.HTTP_403_FORBIDDEN)
                logs = DocumentAccessLog.objects.filter(document_id=document.id).order_by('-created_at')
            else:
                user_doc_ids = Document.objects.filter(
                    tenant_id=request.tenant_id,
                    uploaded_by_id=request.user.id
                ).values_list('id', flat=True)
                logs = DocumentAccessLog.objects.filter(document_id__in=user_doc_ids).order_by('-created_at')

            serializer = DocumentAccessLogSerializer(logs, many=True)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Error fetching access logs: {e}")
            return Response({"error": "Failed to fetch access logs"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class BulkDocumentOperationsView(APIView):
    """Perform bulk operations on documents."""
    authentication_classes = [MicroserviceJWTAuthentication]
    permission_classes = [IsAuthenticated]

    @require_tenant
    def post(self, request):
        try:
            serializer = BulkDocumentOperationSerializer(data=request.data, context={'request': request})
            serializer.is_valid(raise_exception=True)

            document_ids = serializer.validated_data['document_ids']
            action = serializer.validated_data['action']

            documents = Document.objects.filter(
                id__in=document_ids,
                tenant_id=request.tenant_id,
                uploaded_by_id=request.user.id
            )

            if documents.count() != len(document_ids):
                return Response(
                    {"error": "Some documents not found or not accessible"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if action == 'delete':
                count = documents.count()
                doc_ids = list(documents.values_list('id', flat=True))

                DocumentAccessLog.objects.filter(document_id__in=doc_ids).delete()
                DocumentChunk.objects.filter(document_id__in=doc_ids).delete()

                for doc in documents:
                    # Sync deletion to chatbot service
                    trigger_document_deleted(str(doc.id), str(request.tenant_id))

                    if doc.file:
                        try:
                            doc.file.delete(save=False)
                        except Exception as e:
                            logger.warning(f"Could not delete file for doc {doc.id}: {e}")

                documents.delete()
                return Response({"message": f"{count} documents deleted successfully"})

            elif action == 'move_to_category':
                category_id = serializer.validated_data['category_id']
                documents.update(category_id=category_id)
                return Response({"message": f"{documents.count()} documents moved successfully"})

            elif action == 'make_public':
                documents.update(is_public=True)
                return Response({"message": f"{documents.count()} documents made public"})

            elif action == 'make_private':
                documents.update(is_public=False)
                return Response({"message": f"{documents.count()} documents made private"})

            elif action == 'share':
                user_ids = serializer.validated_data['user_ids']
                user_ids_str = [str(uid) for uid in user_ids]
                documents.update(shared_with_ids=user_ids_str)
                return Response({"message": f"{documents.count()} documents shared"})

            elif action == 're_index':
                # ── NEW: bulk re-index failed/stale documents ──
                success_count = 0
                fail_count = 0
                for doc in documents:
                    Document.objects.filter(id=doc.id).update(
                        indexing_status='pending', is_indexed=False
                    )
                    doc.refresh_from_db()
                    if trigger_document_reindex(doc):
                        success_count += 1
                    else:
                        fail_count += 1
                return Response({
                    "message": f"Re-index triggered for {success_count} document(s). {fail_count} failed."
                })

            else:
                return Response(
                    {"error": f"Unknown action: {action}"},
                    status=status.HTTP_400_BAD_REQUEST
                )

        except Exception as e:
            logger.error(f"Bulk operation error: {e}")
            return Response(
                {"error": f"Bulk operation failed: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )