"""
URL configuration for tenantiq project.
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Auth endpoints
    path('api/auth/', include('accounts.urls')),
    
    # Global API endpoints (Audit Logs, AI Usage)
    path('api/', include('accounts.urls_api')),
    
    # Other core services
    path('api/core/', include('core.urls')),
    path('api/tenants/', include('tenants.urls')),
    path('api/subscription/', include('subscriptions.urls', namespace='subscriptions')),
    path('api/user-management/', include('user_management.urls')),
]