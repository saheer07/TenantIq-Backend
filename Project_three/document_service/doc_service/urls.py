"""
Document Service URLs - Multi-tenant
Matches views available in views_v2.py
"""
from django.urls import path
from .views import (
    # Categories
    CategoryListCreateView,
    CategoryDetailView,
    
    # Documents
    DocumentListCreateView,
    DocumentDetailView,
    DocumentShareView,
    DocumentIndexStatusView,
    DocumentAccessLogView,
    BulkDocumentOperationsView,
    DocumentReIndexView,
    ActiveDocumentIDsView,
)

urlpatterns = [
    # Category endpoints
    path('categories/', CategoryListCreateView.as_view(), name='category-list-create'),
    path('categories/<uuid:pk>/', CategoryDetailView.as_view(), name='category-detail'),
    
    # Document endpoints
    path('documents/', DocumentListCreateView.as_view(), name='document-list-create'),
    path('documents/<uuid:pk>/', DocumentDetailView.as_view(), name='document-detail'),
    path('documents/<uuid:pk>/share/', DocumentShareView.as_view(), name='document-share'),
    path('documents/<uuid:pk>/update-index-status/', DocumentIndexStatusView.as_view(), name='document-index-status'),
    path('documents/<uuid:pk>/access-logs/', DocumentAccessLogView.as_view(), name='document-access-logs'),
    path('documents/<uuid:pk>/re-index/', DocumentReIndexView.as_view(), name='document-re-index'),
    
    # Access logs for all user's documents
    path('access-logs/', DocumentAccessLogView.as_view(), name='access-logs-list'),
    
    # Bulk operations
    path('bulk-operations/', BulkDocumentOperationsView.as_view(), name='bulk-operations'),

    # Internal reconciliation
    path('internal/active-document-ids/', ActiveDocumentIDsView.as_view(), name='active-document-ids'),
]