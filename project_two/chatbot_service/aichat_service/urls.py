from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    # ViewSets
    DocumentIndexViewSet,
    ConversationViewSet,
    ChatMessageViewSet,
    TenantSettingsViewSet,

    # API Views
    ChatQueryView,
    DocumentIndexWebhookView,
    DocumentDeleteWebhookView,
    RAGStatsView,
    UsageStatsView,
    HealthCheckView,
    TriggerDocumentIndexView,
)

# ==================== ROUTER ====================
# NOTE: Router is registered ONLY for viewsets that don't conflict
# with custom URL patterns below.

router = DefaultRouter()
# REMOVED DocumentIndexViewSet from router — it was intercepting
# /documents/index/ and /webhooks/index-document/ paths.
# DocumentIndex is accessed via the webhook only (not a user-facing ViewSet).
router.register(r'conversations', ConversationViewSet, basename='conversation')
router.register(r'messages', ChatMessageViewSet, basename='message')
router.register(r'settings', TenantSettingsViewSet, basename='settings')

app_name = 'aichat'

urlpatterns = [

    # ==================== HEALTH ====================
    # No authentication required
    path('health/', HealthCheckView.as_view(), name='health-check'),

    # ==================== WEBHOOKS ====================
    # IMPORTANT: Webhook routes must come BEFORE router.urls and any
    # wildcard/pk patterns to avoid being intercepted.
    path('webhooks/index-document/', DocumentIndexWebhookView.as_view(), name='index-document-webhook'),
    path('webhooks/delete-document/', DocumentDeleteWebhookView.as_view(), name='delete-document-webhook'),

    # ==================== CUSTOM ENDPOINTS ====================
    path('query/', ChatQueryView.as_view(), name='chat-query'),
    path('stats/', RAGStatsView.as_view(), name='rag-stats'),
    path('usage-stats/', UsageStatsView.as_view(), name='usage-stats'),
    path('documents/index/', TriggerDocumentIndexView.as_view(), name='trigger-index'),

    # ==================== VIEWSET ROUTES ====================
    # Router urls come LAST so they don't shadow the custom paths above.
    path('', include(router.urls)),
]