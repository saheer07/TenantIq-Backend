import logging
from django.conf import settings
from .webhook_sender import webhook_sender

logger = logging.getLogger(__name__)

def _build_endpoint(document_id: str) -> str:
    """Construct the chatbot service endpoint for a given document ID."""
    base_url = getattr(settings, "CHATBOT_SERVICE_URL", "http://127.0.0.1:8002").strip().rstrip('/')
    return f"{base_url}/api/documents/{document_id}/index/"

def trigger_document_uploaded(document) -> bool:
    """Notify the chatbot service that a new document has been uploaded.

    This will cause the chatbot service to start indexing the document.
    Returns True if the webhook was sent successfully, False otherwise.
    """
    try:
        payload = {
            "document_id": str(document.id),
            "tenant_id": str(document.tenant_id),
            "title": document.title,
            "description": getattr(document, "description", ""),
        }
        endpoint = _build_endpoint(str(document.id))
        logger.info(f"[WEBHOOK EVENT] Triggering upload webhook for document {document.id} to {endpoint}")
        return webhook_sender.send(endpoint, payload, event_type="document.uploaded", document_id=str(document.id))
    except Exception as e:
        logger.error(f"[WEBHOOK EVENT] Failed to trigger upload webhook for document {document.id}: {e}")
        return False

def trigger_document_deleted(document_id: str, tenant_id: str) -> bool:
    """Notify the chatbot service that a document has been deleted.

    The chatbot service will remove the document and its chunks from the vector store.
    Returns True if the webhook was sent successfully, False otherwise.
    """
    try:
        payload = {
            "document_id": document_id,
            "tenant_id": tenant_id,
        }
        endpoint = _build_endpoint(document_id)
        logger.info(f"[WEBHOOK EVENT] Triggering delete webhook for document {document_id} to {endpoint}")
        return webhook_sender.send(endpoint, payload, event_type="document.deleted", document_id=document_id)
    except Exception as e:
        logger.error(f"[WEBHOOK EVENT] Failed to trigger delete webhook for document {document_id}: {e}")
        return False

def trigger_document_reindex(document) -> bool:
    """Re‑trigger indexing for an existing document.

    This is used when a previous indexing attempt failed or when the document content
    has changed and needs to be re‑processed.
    Returns True if the webhook was sent successfully, False otherwise.
    """
    try:
        payload = {
            "document_id": str(document.id),
            "tenant_id": str(document.tenant_id),
            "title": document.title,
            "reindex": True,
        }
        endpoint = _build_endpoint(str(document.id))
        logger.info(f"[WEBHOOK EVENT] Triggering re‑index webhook for document {document.id} to {endpoint}")
        return webhook_sender.send(endpoint, payload, event_type="document.reindex", document_id=str(document.id))
    except Exception as e:
        logger.error(f"[WEBHOOK EVENT] Failed to trigger re‑index webhook for document {document.id}: {e}")
        return False
