import uuid
from django.db import models
from django.utils import timezone


class DocumentIndex(models.Model):
    """
    Tracks indexed documents in the vector store
    """
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('indexed', 'Indexed'),
        ('failed', 'Failed'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.CharField(max_length=63, db_index=True)
    
    # Document information
    title = models.CharField(max_length=500)
    file_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=255)
    file_size = models.BigIntegerField()
    file = models.FileField(upload_to='documents/%Y/%m/%d/', null=True, blank=True)
    
    # Indexing status
    indexing_status = models.CharField(
        max_length=100,
        choices=STATUS_CHOICES,
        default='pending'
    )
    error_message = models.TextField(null=True, blank=True)
    
    # Processing metadata
    num_chunks = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)
    processing_time = models.FloatField(null=True, blank=True)  # seconds
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    indexed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'document_indexes'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant_id', 'indexing_status']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.title} ({self.indexing_status})"
    
    def mark_processing(self):
        """Mark document as being processed"""
        self.indexing_status = 'processing'
        self.save(update_fields=['indexing_status', 'updated_at'])
    
    def mark_completed(self, num_chunks: int, total_tokens: int, processing_time: float):
        """
        Backwards-compatible alias for a successfully indexed document.
        
        Older code paths (e.g. webhooks) still call `mark_completed`, while the
        canonical status value in the model has been migrated from
        'completed' → 'indexed'. This helper keeps those callers working by
        delegating to `mark_indexed` and ensuring `indexing_status` is set to
        'indexed', which is what the rest of the system (chat queries, stats,
        filters) expects for a ready-to-use document.
        """
        self.mark_indexed(num_chunks=num_chunks, total_tokens=total_tokens, processing_time=processing_time)
    
    def mark_indexed(self, num_chunks: int, total_tokens: int, processing_time: float):
        """Mark document as successfully indexed"""
        self.indexing_status = 'indexed'
        self.num_chunks = num_chunks
        self.total_tokens = total_tokens
        self.processing_time = processing_time
        self.indexed_at = timezone.now()
        self.save(update_fields=[
            'indexing_status', 'num_chunks', 'total_tokens',
            'processing_time', 'indexed_at', 'updated_at'
        ])
    
    def mark_failed(self, error_message: str):
        """Mark document indexing as failed"""
        self.indexing_status = 'failed'
        self.error_message = error_message
        self.save(update_fields=['indexing_status', 'error_message', 'updated_at'])


class Conversation(models.Model):
    """
    Represents a conversation thread
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.CharField(max_length=63, db_index=True)
    user_id = models.CharField(max_length=63, db_index=True)
    
    title = models.CharField(max_length=500, blank=True)
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'conversations'
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['tenant_id', 'user_id']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return self.title or f"Conversation {self.id}"


class ChatMessage(models.Model):
    """
    Individual messages in a conversation
    """
    
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='messages'
    )
    
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    
    # RAG metadata (for assistant messages)
    num_sources = models.IntegerField(default=0)
    confidence_score = models.FloatField(null=True, blank=True)
    tokens_used = models.IntegerField(default=0)
    
    # User feedback
    feedback = models.CharField(
        max_length=20,
        choices=[('helpful', 'Helpful'), ('not_helpful', 'Not Helpful')],
        null=True,
        blank=True
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'chat_messages'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.role}: {self.content[:50]}..."


class MessageSource(models.Model):
    """
    Links messages to source documents used for generation
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(
        ChatMessage,
        on_delete=models.CASCADE,
        related_name='sources'
    )
    document = models.ForeignKey(
        DocumentIndex,
        on_delete=models.CASCADE,
        related_name='cited_in'
    )
    
    chunk_index = models.IntegerField()
    relevance_score = models.FloatField()
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'message_sources'
        ordering = ['-relevance_score']
        indexes = [
            models.Index(fields=['message']),
            models.Index(fields=['document']),
        ]
    
    def __str__(self):
        return f"Source: {self.document.title} (chunk {self.chunk_index})"


class RAGUsageStats(models.Model):
    """
    Tracks RAG system usage for analytics and billing
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.CharField(max_length=63, db_index=True)
    user_id = models.CharField(max_length=63, db_index=True)
    
    # Usage metrics
    queries_count = models.IntegerField(default=0)
    documents_indexed = models.IntegerField(default=0)
    total_chunks = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)
    
    # Date tracking
    date = models.DateField(db_index=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'rag_usage_stats'
        unique_together = ['tenant_id', 'user_id', 'date']
        ordering = ['-date']
        indexes = [
            models.Index(fields=['tenant_id', 'date']),
            models.Index(fields=['date']),
        ]
    
    def __str__(self):
        return f"Stats for {self.date} - Tenant {self.tenant_id}"
    
    @classmethod
    def increment_queries(cls, tenant_id, user_id):
        """Increment query count for today"""
        from django.db.models import F
        today = timezone.now().date()
        
        stats, created = cls.objects.get_or_create(
            tenant_id=tenant_id,
            user_id=user_id,
            date=today,
            defaults={'queries_count': 0}
        )
        
        stats.queries_count = F('queries_count') + 1
        stats.save(update_fields=['queries_count', 'updated_at'])
    
    @classmethod
    def increment_documents(
        cls,
        tenant_id,
        user_id,
        num_chunks: int,
        total_tokens: int
    ):
        """Increment document indexing stats for today"""
        from django.db.models import F
        today = timezone.now().date()
        
        stats, created = cls.objects.get_or_create(
            tenant_id=tenant_id,
            user_id=user_id,
            date=today,
            defaults={
                'documents_indexed': 0,
                'total_chunks': 0,
                'total_tokens': 0
            }
        )
        
        stats.documents_indexed = F('documents_indexed') + 1
        stats.total_chunks = F('total_chunks') + num_chunks
        stats.total_tokens = F('total_tokens') + total_tokens
        stats.save(update_fields=[
            'documents_indexed', 'total_chunks', 'total_tokens', 'updated_at'
        ])


class TenantSettings(models.Model):
    """
    Per-tenant configuration for RAG system
    """
    
    tenant_id = models.CharField(max_length=63, primary_key=True)
    
    # Feature flags
    rag_enabled = models.BooleanField(default=True)
    
    # Limits
    max_documents = models.IntegerField(default=100)
    max_chunks_per_document = models.IntegerField(default=1000)
    max_queries_per_day = models.IntegerField(default=1000)
    
    # RAG configuration
    chunk_size = models.IntegerField(default=500)
    chunk_overlap = models.IntegerField(default=50)
    retrieval_top_k = models.IntegerField(default=5)
    relevance_threshold = models.FloatField(default=0.3)
    
    # LLM settings
    llm_model = models.CharField(max_length=100, default='gpt-3.5-turbo')
    max_response_tokens = models.IntegerField(default=500)
    temperature = models.FloatField(default=0.7)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'tenant_settings'
    
    def __str__(self):
        return f"Settings for tenant {self.tenant_id}"
    
    @classmethod
    def get_or_create_settings(cls, tenant_id):
        """Get or create settings for a tenant"""
        settings, created = cls.objects.get_or_create(tenant_id=tenant_id)
        return settings