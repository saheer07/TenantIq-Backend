"""
URL configuration for tenantiq project.
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('accounts.urls')),
    path('api/core/', include('core.urls')),
    path('api/tenants/', include('tenants.urls')),
    path('api/subscription/', include('subscriptions.urls', namespace='subscriptions')),  # ← fixed: plural → singular
    path('api/user-management/', include('user_management.urls')),
]