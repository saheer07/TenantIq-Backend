from django.urls import path
from accounts.views import (
    TenantListCreateView,
    TenantDetailView,
    TenantStatsView,
    TenantChangePlanView
)

urlpatterns = [
    path("", TenantListCreateView.as_view(), name="tenant-list-create"),
    path("<uuid:pk>/", TenantDetailView.as_view(), name="tenant-detail"),
    path("<uuid:pk>/stats/", TenantStatsView.as_view(), name="tenant-stats"),
    path("<uuid:pk>/change-plan/", TenantChangePlanView.as_view(), name="tenant-change-plan"),
]
