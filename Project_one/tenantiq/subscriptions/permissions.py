from rest_framework.permissions import BasePermission


class HasActiveSubscription(BasePermission):
    """
    Check if user's tenant has an active subscription
    """
    message = "Your subscription has expired. Please renew to continue."

    def has_permission(self, request, view):
        user = request.user
        
        # User must be authenticated
        if not user or not user.is_authenticated:
            self.message = "Authentication required"
            return False
        
        # Super admin always has access
        if user.role == 'super_admin':
            return True
        
        # Check if user has a tenant
        if not user.tenant:
            self.message = "No organization associated with your account"
            return False
        
        # Check if tenant has a subscription
        if not hasattr(user.tenant, 'subscription'):
            self.message = "No active subscription found. Please subscribe to continue."
            return False
        
        subscription = user.tenant.subscription
        
        # Check if subscription is expired
        if subscription.is_expired():
            subscription.check_and_update_status()
            self.message = f"Your subscription expired on {subscription.end_date.strftime('%Y-%m-%d')}. Please renew."
            return False
        
        # Check if subscription is active
        if not subscription.is_active or subscription.status != 'active':
            self.message = f"Your subscription is {subscription.status}. Please contact support."
            return False
        
        return True


class HasAIAccess(BasePermission):
    """
    Check if user has AI access through subscription
    Combines subscription check with AI feature check
    """
    message = "AI access not available in your current plan"

    def has_permission(self, request, view):
        user = request.user
        
        # User must be authenticated
        if not user or not user.is_authenticated:
            self.message = "Authentication required"
            return False
        
        # Super admin always has access
        if user.role == 'super_admin':
            return True
        
        # Check individual AI access flag
        if user.has_ai_access:
            return True
        
        # Check if user has a tenant
        if not user.tenant:
            self.message = "No organization associated with your account"
            return False
        
        # Check if tenant has active subscription
        if not hasattr(user.tenant, 'subscription'):
            self.message = "No active subscription. Please subscribe to access AI features."
            return False
        
        subscription = user.tenant.subscription
        
        # Check if subscription is active
        if subscription.is_expired() or not subscription.is_active:
            self.message = "Your subscription has expired. Please renew to access AI features."
            return False
        
        # Check if plan includes AI
        if not subscription.plan or not subscription.plan.ai_enabled:
            self.message = "AI access not available in your current plan. Please upgrade."
            return False
        
        # Check AI query limits
        if user.tenant.ai_queries_used >= user.tenant.max_ai_queries:
            self.message = f"AI query limit reached ({user.tenant.max_ai_queries}/month). Please upgrade your plan."
            return False
        
        return True


class CanManageSubscription(BasePermission):
    """
    Check if user can manage subscriptions
    Only tenant admins and super admins can manage subscriptions
    """
    message = "Only administrators can manage subscriptions"

    def has_permission(self, request, view):
        user = request.user
        
        if not user or not user.is_authenticated:
            return False
        
        # Super admin and tenant admin can manage
        return user.role in ['super_admin', 'tenant_admin']


class IsSubscriptionOwner(BasePermission):
    """
    Check if user belongs to the tenant that owns the subscription
    """
    message = "You can only manage your organization's subscription"

    def has_object_permission(self, request, view, obj):
        user = request.user
        
        if not user or not user.is_authenticated:
            return False
        
        # Super admin can access any subscription
        if user.role == 'super_admin':
            return True
        
        # User must belong to the same tenant
        return obj.tenant == user.tenant


class HasFeatureAccess(BasePermission):
    """
    Generic permission to check if user has access to a specific feature
    Usage: Set `required_feature` in view
    """
    message = "This feature is not available in your current plan"

    def has_permission(self, request, view):
        user = request.user
        
        # Get required feature from view
        required_feature = getattr(view, 'required_feature', None)
        if not required_feature:
            return True  # No specific feature required
        
        if not user or not user.is_authenticated:
            return False
        
        # Super admin always has access
        if user.role == 'super_admin':
            return True
        
        # Check if user has tenant and subscription
        if not user.tenant or not hasattr(user.tenant, 'subscription'):
            self.message = "No active subscription found"
            return False
        
        subscription = user.tenant.subscription
        
        # Check if subscription is active
        if subscription.is_expired() or not subscription.is_active:
            self.message = "Your subscription has expired"
            return False
        
        # Check if plan has the required feature
        if not subscription.plan:
            return False
        
        plan_features = subscription.plan.features
        if isinstance(plan_features, dict):
            return plan_features.get(required_feature, False)
        
        return False
    


from rest_framework.permissions import BasePermission
from .utils import get_active_subscription


class HasActiveSubscription(BasePermission):
    """
    Allow access only if tenant has active subscription
    """

    message = "Active subscription required to access this feature."

    def has_permission(self, request, view):
        user = request.user

        if not user.is_authenticated:
            return False

        tenant = getattr(user, "tenant", None)
        if not tenant:
            return False

        subscription = get_active_subscription(tenant)
        return subscription is not None
