"""
document_service/doc_service/webhook_events.py

All webhook event trigger functions.
Import and call these from views.py after each event occurs.

Usage in views.py:
    from .webhook_events import trigger_document_uploaded
    trigger_document_uploaded(document)
"""

import logging
import os

from django.conf import settings

logger = logging.getLogger(__name__)


def trigger_document_uploaded(document) -> bool:
    """
    Fire 'document.uploaded' webhook → chatbot service indexes the document.

    Call this immediately after saving a new document in views.py.
    Replaces the old notify_chatbot_for_indexing() function entirely.
    """
    from .webhook_sender import webhook_sender

    chatbot_url = getattr(settings, 'CHATBOT_SERVICE_URL', 'http://127.0.0.1:8002')
    endpoint = f"{chatbot_url}/api/chat/webhooks/index-document/"

    # ── Resolve absolute file path ──
    try:
        file_path = os.path.abspath(document.file.path)
    except Exception as e:
        logger.error(f"[EVENT] Cannot resolve file path: {e}")
        file_path = str(document.file)

    logger.info(f"[EVENT] document.uploaded → document={document.id}")
    logger.info(f"[EVENT] File path: {file_path}")
    logger.info(f"[EVENT] Endpoint: {endpoint}")

    # ── Verify file exists before sending ──
    if not os.path.exists(file_path):
        logger.error(f"[EVENT] File not found on disk: {file_path}")
        try:
            document.indexing_status = 'failed'
            document.save(update_fields=['indexing_status'])
        except Exception:
            pass
        return False

    payload = {
        "document_id": str(document.id),
        "tenant_id":   str(document.tenant_id),
        "user_id":     str(document.uploaded_by_id),
        "file_path":   file_path,
        "file_type":   document.file_type or 'application/pdf',
        "title":       document.title or document.file_name,
        "file_name":   document.file_name,
        "file_size":   document.file_size,
    }

    return webhook_sender.send(
        endpoint=endpoint,
        payload=payload,
        event_type='document.uploaded',
        document_id=str(document.id),
    )


def trigger_document_deleted(document_id: str, tenant_id: str) -> bool:
    """
    Fire 'document.deleted' webhook → chatbot removes document from vector store.
    Call this after deleting a document from the DB.
    """
    from .webhook_sender import webhook_sender

    chatbot_url = getattr(settings, 'CHATBOT_SERVICE_URL', 'http://127.0.0.1:8002')
    endpoint = f"{chatbot_url}/api/chat/webhooks/delete-document/"

    payload = {
        "document_id": document_id,
        "tenant_id":   tenant_id,
    }

    logger.info(f"[EVENT] document.deleted → document={document_id}")

    return webhook_sender.send(
        endpoint=endpoint,
        payload=payload,
        event_type='document.deleted',
    )


def trigger_document_reindex(document) -> bool:
    """
    Fire 'document.reindex' webhook → chatbot re-indexes an existing document.
    Useful if the document content was updated.
    """
    return trigger_document_uploaded(document)