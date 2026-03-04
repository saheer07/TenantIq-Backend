from django.urls import path
from accounts.views import (
    AuditLogListView,
    AuditLogDetailView,
    AIUsageLogListView,
    AIUsageLogDetailView
)

urlpatterns = [
    path("audit-logs/", AuditLogListView.as_view(), name="audit-log-list"),
    path("audit-logs/<uuid:pk>/", AuditLogDetailView.as_view(), name="audit-log-detail"),
    path("ai-usage/", AIUsageLogListView.as_view(), name="ai-usage-log-list"),
    path("ai-usage/<uuid:pk>/", AIUsageLogDetailView.as_view(), name="ai-usage-log-detail"),
]
