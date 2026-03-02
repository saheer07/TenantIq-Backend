# backend/accounts/permissions.py - UPDATED VERSION

from datetime import timezone
from rest_framework.permissions import BasePermission
from rest_framework.exceptions import PermissionDenied


class IsAuthenticated(BasePermission):
    """User must be authenticated"""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


class IsSuperAdmin(BasePermission):
    """Only super admins"""
    def has_permission(self, request, view):
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.role == 'SUPER_ADMIN'
        )


class IsTenantAdmin(BasePermission):
    """Tenant admin or super admin"""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.role in ['SUPER_ADMIN', 'TENANT_ADMIN']


class IsTenantAdminOrManager(BasePermission):
    """Tenant admin, manager, or super admin"""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.role in ['SUPER_ADMIN', 'TENANT_ADMIN', 'TENANT_MANAGER']


class HasPermission(BasePermission):
    """Check if user has specific permission"""
    required_permission = None
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        permission = self.required_permission or getattr(view, 'required_permission', None)
        if not permission:
            return True
        
        return permission in request.user.get_permissions()


# ✅ FIXED: Make CanManageUsers work with just role check
class CanManageUsers(BasePermission):
    """Can invite and manage users - based on role"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Allow SUPER_ADMIN and TENANT_ADMIN
        if request.user.role in ['SUPER_ADMIN', 'TENANT_ADMIN']:
            return True
        
        # Fallback to permission check if available
        if hasattr(request.user, 'get_permissions'):
            return 'manage_tenant_users' in request.user.get_permissions()
        
        return False
    
    def has_object_permission(self, request, view, obj):
        """Check object-level permissions for user management"""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Super admin can manage all users
        if request.user.role == 'SUPER_ADMIN':
            return True
        
        # Tenant admin can manage users in their tenant
        if request.user.role == 'TENANT_ADMIN':
            # Check if target user is in same tenant
            if hasattr(obj, 'tenant'):
                return obj.tenant == request.user.tenant
            return True
        
        return False


# ✅ FIXED: Make CanInviteUsers work with just role check
class CanInviteUsers(BasePermission):
    """Can invite users - based on role"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Allow SUPER_ADMIN and TENANT_ADMIN
        if request.user.role in ['SUPER_ADMIN', 'TENANT_ADMIN']:
            return True
        
        # Fallback to permission check if available
        if hasattr(request.user, 'get_permissions'):
            return 'invite_users' in request.user.get_permissions()
        
        return False


class CanAccessAI(BasePermission):
    """Check if user has AI access"""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # ✅ FIXED: Check if method exists before calling
        if not hasattr(request.user, 'can_use_ai'):
            return True  # If method doesn't exist, allow by default
        
        if not request.user.can_use_ai():
            self.message = self._get_error_message(request.user)
            return False
        
        return True
    
    def _get_error_message(self, user):
        """Generate specific error message"""
        if hasattr(user, 'can_access_ai') and not user.can_access_ai:
            return "Your AI access has been disabled. Contact your administrator."
        
        if not user.tenant:
            return "No organization associated with your account."
        
        if hasattr(user.tenant, 'status') and user.tenant.status != 'active':
            return "Your organization account is inactive."
        
        if hasattr(user.tenant, 'plan') and user.tenant.plan == 'free':
            return "AI access requires upgrading to Pro or Enterprise plan."
        
        if hasattr(user.tenant, 'has_ai_access') and not user.tenant.has_ai_access:
            return "AI access is not enabled for your organization."
        
        if hasattr(user.tenant, 'has_available_ai_queries'):
            if not user.tenant.has_available_ai_queries():
                if hasattr(user.tenant, 'ai_queries_reset_date'):
                    remaining_days = (user.tenant.ai_queries_reset_date - timezone.now()).days
                    return f"Monthly AI query limit reached. Resets in {remaining_days} days."
                return "Monthly AI query limit reached."
        
        return "You do not have permission to access AI features."


class CanUploadDocuments(BasePermission):
    """Can upload documents - based on role"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Allow all authenticated users by default
        # Or restrict to specific roles:
        # return request.user.role in ['SUPER_ADMIN', 'TENANT_ADMIN', 'TENANT_USER']
        
        # Fallback to permission check if available
        if hasattr(request.user, 'get_permissions'):
            return 'upload_documents' in request.user.get_permissions()
        
        return True  # Allow by default


class CanManageDocuments(BasePermission):
    """Can manage documents"""
    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Super admin can manage all
        if request.user.role == ['SUPER_ADMIN', "TENANT_ADMIN"]:
            return True
        
        # Must be same tenant
        if hasattr(obj, 'tenant') and obj.tenant != request.user.tenant:
            return False
        
        # Owner can manage own documents
        if hasattr(obj, 'uploaded_by') and obj.uploaded_by == request.user:
            return True
        
        # Tenant admin can manage all tenant documents
        if request.user.role == 'TENANT_ADMIN':
            return True
        
        return False


class CanViewDocument(BasePermission):
    """Can view document"""
    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # ✅ FIXED: Check if method exists before calling
        if hasattr(obj, 'can_access'):
            return obj.can_access(request.user)
        
        # Fallback: same tenant check
        if hasattr(obj, 'tenant'):
            return obj.tenant == request.user.tenant
        
        return True


class IsSameTenant(BasePermission):
    """Resource belongs to same tenant"""
    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Super admin can access everything
        if request.user.role == 'SUPER_ADMIN':
            return True
        
        # Check if object belongs to same tenant
        if hasattr(obj, 'tenant'):
            return obj.tenant == request.user.tenant
        
        if hasattr(obj, 'user') and hasattr(obj.user, 'tenant'):
            return obj.user.tenant == request.user.tenant
        
        return False


class CanViewAuditLogs(BasePermission):
    """Can view audit logs"""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        if request.user.role == 'SUPER_ADMIN':
            return True
        
        # Fallback to permission check if available
        if hasattr(request.user, 'get_permissions'):
            return 'view_tenant_audit_logs' in request.user.get_permissions()
        
        # Allow tenant admins by default
        return request.user.role == 'TENANT_ADMIN'