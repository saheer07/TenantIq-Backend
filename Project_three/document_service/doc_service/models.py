# from django.db import models
# import uuid


# class Document(models.Model):
#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     title = models.CharField(max_length=255)
#     description = models.TextField(blank=True)

#     file = models.FileField(upload_to='documents/')
#     file_name = models.CharField(max_length=255, blank=True, null=True)
#     file_size = models.BigIntegerField(blank=True, null=True)
#     file_type = models.CharField(max_length=50, blank=True, null=True)

#     uploaded_by_id = models.UUIDField()
#     tenant_id = models.UUIDField(null=True, blank=True)

#     is_public = models.BooleanField(default=False)
#     is_indexed = models.BooleanField(default=False)
#     indexing_status = models.CharField(
#         max_length=50,
#         default='pending',
#         choices=[
#             ('pending', 'Pending'),
#             ('processing', 'Processing'),
#             ('indexed', 'Indexed'),
#             ('failed', 'Failed'),
#         ]
#     )

#     shared_with_ids = models.JSONField(default=list, blank=True)
#     tags = models.JSONField(default=list, blank=True)

#     created_at = models.DateTimeField(auto_now_add=True)
#     updated_at = models.DateTimeField(auto_now=True)

#     class Meta:
#         ordering = ['-created_at']

#     def __str__(self):
#         return self.title


# class DocumentChunk(models.Model):
#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     document = models.ForeignKey(
#         Document,
#         related_name='chunks',
#         on_delete=models.CASCADE
#     )
#     chunk_index = models.IntegerField()
#     chunk_size = models.IntegerField()
#     content = models.TextField(blank=True)          # ✅ ADDED: store actual chunk text
#     embedding_status = models.CharField(
#         max_length=50,
#         default='pending',
#         choices=[
#             ('pending', 'Pending'),
#             ('processing', 'Processing'),
#             ('embedded', 'Embedded'),
#             ('failed', 'Failed'),
#         ]
#     )

#     created_at = models.DateTimeField(auto_now_add=True)

#     class Meta:
#         ordering = ['chunk_index']

#     def __str__(self):
#         return f"Chunk {self.chunk_index} of {self.document.title}"


# class DocumentAccessLog(models.Model):
#     ACTION_CHOICES = [
#         ('view', 'View'),
#         ('download', 'Download'),
#         ('delete', 'Delete'),
#         ('share', 'Share'),
#         ('update', 'Update'),
#     ]

#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     document = models.ForeignKey(
#         Document,
#         related_name='access_logs',
#         on_delete=models.CASCADE
#     )
#     user_id = models.UUIDField()
#     action = models.CharField(max_length=50, choices=ACTION_CHOICES)
#     ip_address = models.GenericIPAddressField(null=True, blank=True)
#     user_agent = models.TextField(blank=True)

#     created_at = models.DateTimeField(auto_now_add=True)

#     class Meta:
#         ordering = ['-created_at']

#     def __str__(self):
#         return f"{self.action} - {self.document_id}"













"""
Document Service Models - Multi-tenant with Shared Tenant Model
References Tenant model from First Service (same database)
"""
from django.db import models
from django.core.exceptions import ValidationError
import uuid


class Document(models.Model):
    """
    Document model with tenant isolation.
    References Tenant from First Service via tenant_id.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Tenant relationship (references First Service Tenant model)
    # Using schema_name for tenant identification
    tenant_id = models.CharField(max_length=63, db_index=True)
    
    # Document metadata
    title = models.CharField(max_length=255, db_index=True)
    description = models.TextField(blank=True)
    
    # File information
    file = models.FileField(upload_to='documents/%Y/%m/%d/')
    file_name = models.CharField(max_length=255, blank=True, null=True)
    file_size = models.BigIntegerField(blank=True, null=True)
    file_type = models.CharField(max_length=255, blank=True, null=True)
    
    # Ownership (user_id from JWT, not FK to avoid coupling)
    uploaded_by_id = models.UUIDField(db_index=True)
    
    # Access control
    is_public = models.BooleanField(default=False)
    shared_with_ids = models.JSONField(default=list, blank=True)
    
    # Indexing status for AI/search
    is_indexed = models.BooleanField(default=False, db_index=True)
    indexing_status = models.CharField(
        max_length=100,
        default='pending',
        db_index=True,
        choices=[
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('indexed', 'Indexed'),
            ('failed', 'Failed'),
        ]
    )
    
    # Organization
    category_id = models.UUIDField(null=True, blank=True, db_index=True)
    tags = models.JSONField(default=list, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'doc_service_document'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant_id', '-created_at']),
            models.Index(fields=['tenant_id', 'uploaded_by_id']),
            models.Index(fields=['tenant_id', 'is_indexed']),
            models.Index(fields=['tenant_id', 'indexing_status']),
            models.Index(fields=['tenant_id', 'category_id']),
        ]

    def __str__(self):
        return self.title
    
    def save(self, *args, **kwargs):
        """Ensure tenant_id is set before saving"""
        if not self.tenant_id:
            raise ValidationError("Document must have a tenant_id")

        # Normalise tenant_id to avoid case/whitespace mismatches across services
        self.tenant_id = str(self.tenant_id).strip().lower()
        
        super().save(*args, **kwargs)
    
    def can_be_accessed_by(self, user_id):
        """Check if a user can access this document"""
        # Owner can always access
        if str(self.uploaded_by_id) == str(user_id):
            return True
        # Public documents can be accessed by anyone in the tenant
        if self.is_public:
            return True
        # Shared documents
        if str(user_id) in [str(uid) for uid in self.shared_with_ids]:
            return True
        return False


class DocumentCategory(models.Model):
    """
    Document categories/folders for organization.
    Each tenant can create their own category structure.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Tenant relationship
    tenant_id = models.CharField(max_length=63, db_index=True)
    
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    
    # Hierarchical structure
    parent_id = models.UUIDField(null=True, blank=True, db_index=True)
    
    # Order and display
    order = models.IntegerField(default=0)
    color = models.CharField(max_length=7, default='#3B82F6')  # Hex color
    icon = models.CharField(max_length=50, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'doc_service_documentcategory'
        ordering = ['order', 'name']
        indexes = [
            models.Index(fields=['tenant_id', 'parent_id']),
            models.Index(fields=['tenant_id', 'order']),
        ]

    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        """Ensure tenant_id is set before saving"""
        if not self.tenant_id:
            raise ValidationError("DocumentCategory must have a tenant_id")
        self.tenant_id = str(self.tenant_id).strip().lower()
        super().save(*args, **kwargs)
    
    def get_full_path(self):
        """Get full category path (e.g., 'Parent / Child / Grandchild')"""
        path = [self.name]
        parent_id = self.parent_id
        
        # Prevent infinite loops
        max_depth = 10
        depth = 0
        
        while parent_id and depth < max_depth:
            try:
                parent = DocumentCategory.objects.get(id=parent_id)
                path.insert(0, parent.name)
                parent_id = parent.parent_id
                depth += 1
            except DocumentCategory.DoesNotExist:
                break
        
        return ' / '.join(path)


class DocumentChunk(models.Model):
    """
    Document chunks for vector embeddings and AI processing.
    Inherits tenant relationship through Document.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Document relationship (we'll get tenant_id from document)
    document_id = models.UUIDField(db_index=True)
    
    # Chunk data
    chunk_index = models.IntegerField()
    chunk_size = models.IntegerField()
    content = models.TextField(blank=True)
    
    # Embedding status
    embedding_status = models.CharField(
        max_length=50,
        default='pending',
        choices=[
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('embedded', 'Embedded'),
            ('failed', 'Failed'),
        ]
    )
    
    # Metadata for better retrieval
    page_number = models.IntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'doc_service_documentchunk'
        ordering = ['document_id', 'chunk_index']
        indexes = [
            models.Index(fields=['document_id', 'chunk_index']),
            models.Index(fields=['document_id', 'embedding_status']),
        ]

    def __str__(self):
        return f"Chunk {self.chunk_index} of document {self.document_id}"
    
    @property
    def tenant_id(self):
        """Get tenant_id from parent document"""
        try:
            doc = Document.objects.get(id=self.document_id)
            return doc.tenant_id
        except Document.DoesNotExist:
            return None


class DocumentAccessLog(models.Model):
    """
    Audit log for document access.
    Tracks all document operations for security and compliance.
    """
    ACTION_CHOICES = [
        ('view', 'View'),
        ('download', 'Download'),
        ('delete', 'Delete'),
        ('share', 'Share'),
        ('update', 'Update'),
        ('upload', 'Upload'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Document relationship
    document_id = models.UUIDField(db_index=True)
    
    # User info (from JWT, not FK)
    user_id = models.UUIDField(db_index=True)
    
    # Action details
    action = models.CharField(max_length=50, choices=ACTION_CHOICES, db_index=True)
    
    # Request metadata
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    
    # Additional context
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'doc_service_documentaccesslog'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['document_id', '-created_at']),
            models.Index(fields=['user_id', '-created_at']),
            models.Index(fields=['document_id', 'action', '-created_at']),
        ]

    def __str__(self):
        return f"{self.action} - document {self.document_id} by user {self.user_id}"
    
    @property
    def tenant_id(self):
        """Get tenant_id from parent document"""
        try:
            doc = Document.objects.get(id=self.document_id)
            return doc.tenant_id
        except Document.DoesNotExist:
            return None


# Manager for tenant-scoped queries (optional but recommended)
class TenantManager(models.Manager):
    """Manager that automatically filters by tenant"""
    
    def __init__(self, *args, **kwargs):
        self.tenant_id_field = kwargs.pop('tenant_id_field', 'tenant_id')
        super().__init__(*args, **kwargs)
    
    def for_tenant(self, tenant_id):
        """Filter queryset by tenant_id"""
        return self.filter(**{self.tenant_id_field: tenant_id})


# You can add this to Document model for easier querying:
# objects = TenantManager()
# all_objects = models.Manager()  # Unfiltered manager for admin/superuser