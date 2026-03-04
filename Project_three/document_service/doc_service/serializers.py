"""
Document Service Serializers - Multi-tenant
Validates and enforces tenant isolation
"""
from rest_framework import serializers
from django.core.exceptions import ValidationError
from django.conf import settings

from .models import (
    Document,
    DocumentCategory,
    DocumentChunk,
    DocumentAccessLog,
)


class DocumentCategorySerializer(serializers.ModelSerializer):
    """Serializer for DocumentCategory with tenant validation"""
    full_path = serializers.SerializerMethodField()
    document_count = serializers.SerializerMethodField()
    
    class Meta:
        model = DocumentCategory
        fields = [
            'id',
            'tenant_id',
            'name',
            'description',
            'parent_id',
            'full_path',
            'order',
            'color',
            'icon',
            'document_count',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'tenant_id', 'created_at', 'updated_at', 'full_path']
    
    def get_full_path(self, obj):
        """Get full category path"""
        return obj.get_full_path()
    
    def get_document_count(self, obj):
        """Count documents in this category"""
        return Document.objects.filter(category_id=obj.id, tenant_id=obj.tenant_id).count()
    
    def validate_parent_id(self, value):
        """Ensure parent belongs to same tenant"""
        if value and self.instance:
            try:
                parent = DocumentCategory.objects.get(id=value)
                if parent.tenant_id != self.instance.tenant_id:
                    raise serializers.ValidationError(
                        "Parent category must belong to the same tenant"
                    )
            except DocumentCategory.DoesNotExist:
                raise serializers.ValidationError("Parent category not found")
        return value


class DocumentSerializer(serializers.ModelSerializer):
    """
    Full document serializer with tenant validation.
    Used for create, update, and detail views.
    """
    category_name = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()
    
    class Meta:
        model = Document
        fields = [
            'id',
            'tenant_id',
            'title',
            'description',
            'file',
            'file_name',
            'file_size',
            'file_type',
            'uploaded_by_id',
            'category_id',
            'category_name',
            'is_public',
            'is_indexed',
            'indexing_status',
            'shared_with_ids',
            'tags',
            'can_edit',
            'can_delete',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'tenant_id',
            'uploaded_by_id',
            'file_name',
            'file_size',
            'file_type',
            'is_indexed',
            'indexing_status',
            'created_at',
            'updated_at',
        ]
    
    def get_category_name(self, obj):
        """Get category name"""
        if obj.category_id:
            try:
                category = DocumentCategory.objects.get(id=obj.category_id)
                return category.name
            except DocumentCategory.DoesNotExist:
                return None
        return None
    
    def get_can_edit(self, obj):
        """Check if current user can edit"""
        request = self.context.get('request')
        if not request or not hasattr(request, 'user'):
            return False
        return str(obj.uploaded_by_id) == str(request.user.id)
    
    def get_can_delete(self, obj):
        """Check if current user can delete"""
        request = self.context.get('request')
        if not request or not hasattr(request, 'user'):
            return False
        return str(obj.uploaded_by_id) == str(request.user.id)
    
    def validate_category_id(self, value):
        """Ensure category belongs to same tenant"""
        if value:
            request = self.context.get('request')
            if request and hasattr(request, 'tenant_id') and request.tenant_id:
                try:
                    category = DocumentCategory.objects.get(id=value)
                    if str(category.tenant_id) != str(request.tenant_id):
                        raise serializers.ValidationError(
                            "Category must belong to your organization"
                        )
                except DocumentCategory.DoesNotExist:
                    raise serializers.ValidationError("Category not found")
        return value
    
    def validate(self, data):
        """Additional validation"""
        # Validate file size
        if 'file' in data:
            file = data['file']
            max_size = 100 * 1024 * 1024  # 100 MB
            if file.size > max_size:
                raise serializers.ValidationError({
                    'file': f'File size cannot exceed {max_size / (1024 * 1024):.0f} MB'
                })
        
        return data


class ActiveDocumentIDSerializer(serializers.ModelSerializer):
    """Serializer for Internal Reconciliation Audit"""
    class Meta:
        model = Document
        fields = ['id', 'tenant_id']


class DocumentListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for document lists.
    Excludes heavy fields for better performance.
    """
    category_name = serializers.SerializerMethodField()
    
    class Meta:
        model = Document
        fields = [
            'id',
            'title',
            'description',
            'file',
            'file_name',
            'file_size',
            'file_type',
            'uploaded_by_id',
            'category_id',
            'category_name',
            'is_public',
            'is_indexed',
            'indexing_status',
            'tags',
            'created_at',
            'updated_at',
        ]
    
    def get_category_name(self, obj):
        """Get category name"""
        if obj.category_id:
            try:
                category = DocumentCategory.objects.get(id=obj.category_id)
                return category.name
            except DocumentCategory.DoesNotExist:
                return None
        return None


class DocumentChunkSerializer(serializers.ModelSerializer):
    """Serializer for document chunks"""
    
    class Meta:
        model = DocumentChunk
        fields = [
            'id',
            'document_id',
            'chunk_index',
            'chunk_size',
            'content',
            'embedding_status',
            'page_number',
            'metadata',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']
    
    def validate_document_id(self, value):
        """Ensure document belongs to request tenant"""
        request = self.context.get('request')
        if request and hasattr(request, 'tenant_id') and request.tenant_id:
            try:
                document = Document.objects.get(id=value)
                if str(document.tenant_id) != str(request.tenant_id):
                    raise serializers.ValidationError(
                        "Document must belong to your organization"
                    )
            except Document.DoesNotExist:
                raise serializers.ValidationError("Document not found")
        return value


class DocumentShareSerializer(serializers.Serializer):
    """Serializer for sharing documents"""
    user_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=100,  # Prevent abuse
    )
    
    def validate_user_ids(self, value):
        """Validate user IDs"""
        # Remove duplicates
        value = list(set(str(uid) for uid in value))
        
        # Ensure we're not sharing with too many users
        if len(value) > 100:
            raise serializers.ValidationError(
                "Cannot share with more than 100 users at once"
            )
        
        return value


class DocumentAccessLogSerializer(serializers.ModelSerializer):
    """Serializer for access logs"""
    document_title = serializers.SerializerMethodField()
    
    class Meta:
        model = DocumentAccessLog
        fields = [
            'id',
            'document_id',
            'document_title',
            'user_id',
            'action',
            'ip_address',
            'user_agent',
            'metadata',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']
    
    def get_document_title(self, obj):
        """Get document title"""
        try:
            document = Document.objects.get(id=obj.document_id)
            return document.title
        except Document.DoesNotExist:
            return None


class DocumentUploadSerializer(serializers.Serializer):
    """
    Specialized serializer for file uploads.
    Handles multipart form data efficiently.
    """
    file = serializers.FileField(required=True)
    title = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    category_id = serializers.UUIDField(required=False, allow_null=True)
    is_public = serializers.BooleanField(default=False)
    tags = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
        allow_empty=True,
        max_length=20  # Max 20 tags
    )
    subscription = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    
    def validate_file(self, value):
        """Validate uploaded file"""
        # Check file size
        # Check file size
        max_size = 100 * 1024 * 1024  # 100 MB default
        
        # You could implement subscription-based limits here
        # request = self.context.get('request')
        # if request and hasattr(request.user, 'subscription'):
        #     if request.user.subscription == 'free':
        #         max_size = 10 * 1024 * 1024 # 10MB for free tier
        
        if value.size > max_size:
            raise serializers.ValidationError(
                f'File size ({value.size / (1024 * 1024):.1f} MB) exceeds limit of {max_size / (1024 * 1024):.0f} MB'
            )
        
        # Check file type
        allowed_types = getattr(settings, 'ALLOWED_DOCUMENT_TYPES', [
            'application/pdf',
            'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'text/plain',
        ])
        
        if value.content_type and value.content_type not in allowed_types:
            raise serializers.ValidationError(
                f'File type {value.content_type} is not supported'
            )
        
        return value
    
    def validate_category_id(self, value):
        """Validate category exists and belongs to tenant"""
        if value:
            request = self.context.get('request')
            if request and hasattr(request, 'tenant_id') and request.tenant_id:
                try:
                    category = DocumentCategory.objects.get(
                        id=value,
                        tenant_id=request.tenant_id
                    )
                    return category.id
                except DocumentCategory.DoesNotExist:
                    raise serializers.ValidationError(
                        "Category not found in your organization"
                    )
        return value


class BulkDocumentOperationSerializer(serializers.Serializer):
    """Serializer for bulk operations on documents"""
    document_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=100,  # Limit bulk operations
    )
    action = serializers.ChoiceField(
        choices=['delete', 'share', 'move_to_category', 'make_public', 'make_private']
    )
    # Additional parameters based on action
    category_id = serializers.UUIDField(required=False, allow_null=True)
    user_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
    )
    
    def validate(self, data):
        """Validate based on action"""
        action = data.get('action')
        
        if action == 'move_to_category' and not data.get('category_id'):
            raise serializers.ValidationError({
                'category_id': 'Required for move_to_category action'
            })
        
        if action == 'share' and not data.get('user_ids'):
            raise serializers.ValidationError({
                'user_ids': 'Required for share action'
            })
        
        return data