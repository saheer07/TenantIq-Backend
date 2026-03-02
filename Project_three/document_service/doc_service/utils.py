"""
Document Service Webhook Integration
Add this to your document service to notify the chatbot service when documents are uploaded

File: document_service/doc_service/utils.py (or create new file)
"""

import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


def notify_chatbot_for_indexing(document):
    """
    Notify chatbot service to index a newly uploaded document
    
    Args:
        document: Document model instance
    
    Returns:
        bool: True if notification successful, False otherwise
    """
    try:
        # Get chatbot service URL from settings
        chatbot_url = getattr(
            settings, 
            'CHATBOT_SERVICE_URL', 
            'http://127.0.0.1:8002'
        )
        
        # Webhook endpoint
        webhook_url = f"{chatbot_url}/api/chat/index-document/"
        
        # Prepare payload
        payload = {
            "document_id": str(document.id),
            "tenant_id": str(document.user.tenant_id) if hasattr(document.user, 'tenant_id') else str(document.user.id),
            "file_path": document.file.path,  # Full file system path
            "file_type": document.file_type or 'application/pdf',
            "title": document.title or document.file_name
        }
        
        # Prepare headers
        webhook_api_key = getattr(settings, 'WEBHOOK_API_KEY', '')
        headers = {
            "X-API-Key": webhook_api_key,
            "Content-Type": "application/json"
        }
        
        # Send webhook request
        logger.info(f"📤 Sending document {document.id} to chatbot service for indexing")
        
        response = requests.post(
            webhook_url,
            json=payload,
            headers=headers,
            timeout=30  # 30 second timeout
        )
        
        # Check response
        if response.status_code == 200:
            logger.info(f"✅ Document {document.id} successfully sent for indexing")
            logger.info(f"Response: {response.json()}")
            return True
        else:
            logger.error(f"❌ Failed to index document {document.id}")
            logger.error(f"Status: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return False
            
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Network error notifying chatbot service: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Error notifying chatbot service: {e}")
        return False


def update_document_indexing_status(document, status, error_message=None):
    """
    Update the indexing status of a document
    
    Args:
        document: Document model instance
        status: 'pending', 'processing', 'completed', 'failed'
        error_message: Optional error message if failed
    """
    try:
        document.indexing_status = status
        if error_message:
            document.indexing_error = error_message
        document.save(update_fields=['indexing_status', 'indexing_error', 'updated_at'])
        logger.info(f"📝 Updated document {document.id} indexing status to: {status}")
    except Exception as e:
        logger.error(f"❌ Failed to update document status: {e}")


# ==================== INTEGRATION IN VIEWS ====================

"""
Add this to your DocumentUploadView or DocumentCreateView:

Example for DRF ViewSet:
"""

from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from .utils import notify_chatbot_for_indexing, update_document_indexing_status


class DocumentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Document operations
    """
    
    def create(self, request, *args, **kwargs):
        """
        Handle document upload
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Save the document
        self.perform_create(serializer)
        document = serializer.instance
        
        # Set initial indexing status
        update_document_indexing_status(document, 'pending')
        
        # Notify chatbot service for indexing (async recommended in production)
        # For now, we'll do it synchronously
        indexing_success = notify_chatbot_for_indexing(document)
        
        if indexing_success:
            update_document_indexing_status(document, 'processing')
        else:
            update_document_indexing_status(
                document, 
                'failed',
                'Failed to send document to AI service for indexing'
            )
        
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )
    
    @action(detail=True, methods=['post'])
    def reindex(self, request, pk=None):
        """
        Manually trigger re-indexing of a document
        """
        document = self.get_object()
        
        # Update status
        update_document_indexing_status(document, 'pending')
        
        # Notify chatbot service
        indexing_success = notify_chatbot_for_indexing(document)
        
        if indexing_success:
            update_document_indexing_status(document, 'processing')
            return Response({
                'message': 'Document re-indexing started',
                'status': 'processing'
            })
        else:
            update_document_indexing_status(
                document,
                'failed',
                'Failed to send document to AI service'
            )
            return Response({
                'error': 'Failed to start re-indexing'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


"""
Example for APIView:
"""

from rest_framework.views import APIView


class DocumentUploadView(APIView):
    """
    Handle document upload
    """
    
    def post(self, request):
        try:
            # Your existing upload logic
            serializer = DocumentSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(user=request.user)
            
            document = serializer.instance
            
            # Set initial status
            update_document_indexing_status(document, 'pending')
            
            # Notify chatbot service
            indexing_success = notify_chatbot_for_indexing(document)
            
            if indexing_success:
                update_document_indexing_status(document, 'processing')
            else:
                update_document_indexing_status(
                    document,
                    'failed',
                    'Failed to send to AI service'
                )
            
            return Response(
                serializer.data,
                status=status.HTTP_201_CREATED
            )
            
        except Exception as e:
            logger.error(f"Document upload failed: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


# ==================== SETTINGS CONFIGURATION ====================

"""
Add to document_service/document_service/settings.py:

# Chatbot Service Configuration
CHATBOT_SERVICE_URL = os.environ.get(
    'CHATBOT_SERVICE_URL',
    'http://127.0.0.1:8002'
)

WEBHOOK_API_KEY = os.environ.get(
    'WEBHOOK_API_KEY',
    'your-webhook-api-key-here'
)

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'doc_service': {
            'handlers': ['console'],
            'level': 'DEBUG',
        },
    },
}
"""


# ==================== CELERY ASYNC VERSION (PRODUCTION) ====================

"""
For production, use Celery for async processing:

File: document_service/doc_service/tasks.py
"""

from celery import shared_task


@shared_task
def index_document_async(document_id):
    """
    Asynchronously index a document
    """
    from .models import Document
    
    try:
        document = Document.objects.get(id=document_id)
        update_document_indexing_status(document, 'processing')
        
        success = notify_chatbot_for_indexing(document)
        
        if success:
            logger.info(f"✅ Document {document_id} indexing initiated")
        else:
            update_document_indexing_status(
                document,
                'failed',
                'Failed to notify AI service'
            )
            
    except Document.DoesNotExist:
        logger.error(f"❌ Document {document_id} not found")
    except Exception as e:
        logger.error(f"❌ Error indexing document {document_id}: {e}")


"""
Then in your view:

from .tasks import index_document_async

def create(self, request, *args, **kwargs):
    serializer.save()
    document = serializer.instance
    
    # Trigger async indexing
    index_document_async.delay(document.id)
    
    return Response(serializer.data, status=status.HTTP_201_CREATED)
"""