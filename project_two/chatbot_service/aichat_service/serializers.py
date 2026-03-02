from rest_framework import serializers
from .models import (
    DocumentIndex,
    Conversation,
    ChatMessage,
    MessageSource,
    RAGUsageStats,
    TenantSettings
)


class DocumentIndexSerializer(serializers.ModelSerializer):
   
    
    class Meta:
        model = DocumentIndex
        fields = [
            'id',
            'tenant_id',
            'title',
            'file_name',
            'file_type',
            'file_size',
            'indexing_status',
            'error_message',
            'num_chunks',
            'total_tokens',
            'processing_time',
            'created_at',
            'updated_at',
            'indexed_at',
        ]
        read_only_fields = [
            'id',
            'indexing_status',
            'error_message',
            'num_chunks',
            'total_tokens',
            'processing_time',
            'created_at',
            'updated_at',
            'indexed_at',
        ]


class DocumentIndexListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for listing documents
    """
    
    class Meta:
        model = DocumentIndex
        fields = [
            'id',
            'title',
            'file_name',
            'file_type',
            'file_size',
            'indexing_status',
            'num_chunks',
            'created_at',
            'indexed_at',
        ]


class MessageSourceSerializer(serializers.ModelSerializer):
    """
    Serializer for MessageSource model
    """
    document_title = serializers.CharField(source='document.title', read_only=True)
    document_file_name = serializers.CharField(source='document.file_name', read_only=True)
    
    class Meta:
        model = MessageSource
        fields = [
            'id',
            'document',
            'document_title',
            'document_file_name',
            'chunk_index',
            'relevance_score',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class ChatMessageSerializer(serializers.ModelSerializer):
    """
    Serializer for ChatMessage model
    """
    sources = MessageSourceSerializer(many=True, read_only=True)
    
    class Meta:
        model = ChatMessage
        fields = [
            'id',
            'conversation',
            'role',
            'content',
            'num_sources',
            'confidence_score',
            'tokens_used',
            'feedback',
            'sources',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'num_sources',
            'confidence_score',
            'tokens_used',
            'created_at',
        ]


class ChatMessageCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating chat messages
    """
    
    class Meta:
        model = ChatMessage
        fields = ['conversation', 'role', 'content']
    
    def validate_role(self, value):
        """Validate that role is user when creating via API"""
        if value not in ['user', 'system']:
            raise serializers.ValidationError(
                "Only 'user' and 'system' roles can be created via API"
            )
        return value


class ConversationSerializer(serializers.ModelSerializer):
    """
    Serializer for Conversation model with messages
    """
    messages = ChatMessageSerializer(many=True, read_only=True)
    message_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Conversation
        fields = [
            'id',
            'tenant_id',
            'user_id',
            'title',
            'is_active',
            'message_count',
            'messages',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_message_count(self, obj):
        """Get total number of messages in conversation"""
        return obj.messages.count()


class ConversationListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for listing conversations
    """
    message_count = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    
    class Meta:
        model = Conversation
        fields = [
            'id',
            'title',
            'is_active',
            'message_count',
            'last_message',
            'created_at',
            'updated_at',
        ]
    
    def get_message_count(self, obj):
        """Get total number of messages"""
        return obj.messages.count()
    
    def get_last_message(self, obj):
        """Get preview of last message"""
        last_msg = obj.messages.last()
        if last_msg:
            return {
                'role': last_msg.role,
                'content': last_msg.content[:100] + ('...' if len(last_msg.content) > 100 else ''),
                'created_at': last_msg.created_at,
            }
        return None


class ConversationCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating conversations
    """
    
    class Meta:
        model = Conversation
        fields = ['tenant_id', 'user_id', 'title']


class RAGUsageStatsSerializer(serializers.ModelSerializer):
    """
    Serializer for RAGUsageStats model
    """
    
    class Meta:
        model = RAGUsageStats
        fields = [
            'id',
            'tenant_id',
            'user_id',
            'queries_count',
            'documents_indexed',
            'total_chunks',
            'total_tokens',
            'date',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class RAGUsageStatsSummarySerializer(serializers.Serializer):
    """
    Serializer for aggregated usage statistics
    """
    total_queries = serializers.IntegerField()
    total_documents = serializers.IntegerField()
    total_chunks = serializers.IntegerField()
    total_tokens = serializers.IntegerField()
    date_range_start = serializers.DateField()
    date_range_end = serializers.DateField()


class TenantSettingsSerializer(serializers.ModelSerializer):
    """
    Serializer for TenantSettings model
    """
    
    class Meta:
        model = TenantSettings
        fields = [
            'tenant_id',
            'rag_enabled',
            'max_documents',
            'max_chunks_per_document',
            'max_queries_per_day',
            'chunk_size',
            'chunk_overlap',
            'retrieval_top_k',
            'relevance_threshold',
            'llm_model',
            'max_response_tokens',
            'temperature',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['tenant_id', 'created_at', 'updated_at']
    
    def validate_chunk_size(self, value):
        """Validate chunk size is reasonable"""
        if value < 100 or value > 2000:
            raise serializers.ValidationError(
                "Chunk size must be between 100 and 2000"
            )
        return value
    
    def validate_chunk_overlap(self, value):
        """Validate chunk overlap"""
        if value < 0 or value > 500:
            raise serializers.ValidationError(
                "Chunk overlap must be between 0 and 500"
            )
        return value
    
    def validate_retrieval_top_k(self, value):
        """Validate retrieval top k"""
        if value < 1 or value > 20:
            raise serializers.ValidationError(
                "Retrieval top_k must be between 1 and 20"
            )
        return value
    
    def validate_relevance_threshold(self, value):
        """Validate relevance threshold"""
        if value < 0 or value > 1:
            raise serializers.ValidationError(
                "Relevance threshold must be between 0 and 1"
            )
        return value
    
    def validate_temperature(self, value):
        """Validate temperature"""
        if value < 0 or value > 2:
            raise serializers.ValidationError(
                "Temperature must be between 0 and 2"
            )
        return value


class ChatMessageFeedbackSerializer(serializers.Serializer):
    
    feedback = serializers.ChoiceField(
        choices=['helpful', 'not_helpful'],
        required=True
    )


class DocumentIndexStatusSerializer(serializers.Serializer):
  
    pending = serializers.IntegerField()
    processing = serializers.IntegerField()
    indexed = serializers.IntegerField()
    failed = serializers.IntegerField()
    total = serializers.IntegerField()