from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import (
    DocumentIndex,
    Conversation,
    ChatMessage,
    MessageSource,
    RAGUsageStats,
    TenantSettings
)

@admin.register(TenantSettings)
class TenantSettingsAdmin(admin.ModelAdmin):
    list_display = ['tenant_id', 'rag_enabled', 'max_chunks_per_document', 'retrieval_top_k']
    list_filter = ['rag_enabled']
    search_fields = ['tenant_id']
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('tenant_id',)
        }),
        ('RAG Settings', {
            'fields': (
                'rag_enabled',
                'max_chunks_per_document',
                'chunk_size',
                'chunk_overlap',
                'retrieval_top_k',
                'relevance_threshold',
            )
        }),
    )

@admin.register(DocumentIndex)
class DocumentIndexAdmin(admin.ModelAdmin):
    list_display = ('id',)


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ['title', 'tenant_id', 'user_id', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['title', 'tenant_id', 'user_id']

@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ['conversation', 'role', 'content_preview', 'created_at']
    list_filter = ['role', 'feedback']
    search_fields = ['content']
    
    def content_preview(self, obj):
        return obj.content[:50] + '...' if len(obj.content) > 50 else obj.content
    content_preview.short_description = 'Content'