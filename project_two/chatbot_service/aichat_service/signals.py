import logging
from django.db.models.signals import post_delete
from django.dispatch import receiver
from .models import DocumentIndex
from .views import vector_store

logger = logging.getLogger(__name__)

@receiver(post_delete, sender=DocumentIndex)
def delete_document_from_vector_store(sender, instance, **kwargs):
    """
    Sync document deletion with vector store.
    When a DocumentIndex record is deleted, remove its chunks from ChromaDB.
    """
    try:
        tenant_id = str(instance.tenant_id)
        document_id = str(instance.id)
        
        logger.info(f"[SIGNAL] Document {document_id} deleted. Syncing with vector store for tenant {tenant_id}...")
        
        num_deleted = vector_store.delete_document(tenant_id, document_id)
        
        if num_deleted > 0:
            logger.info(f"[SIGNAL] Successfully deleted {num_deleted} chunks from vector store.")
        else:
            logger.info(f"[SIGNAL] No chunks found in vector store for document {document_id}.")
            
    except Exception as e:
        logger.error(f"[SIGNAL] Error syncing document deletion for {instance.id}: {e}")
