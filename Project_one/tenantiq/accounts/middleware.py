# ==================== middleware.py (UPDATED) ====================
import time
import logging
from django.utils.deprecation import MiddlewareMixin
from .models import AuditLog

logger = logging.getLogger(__name__)


# ==========================
# CORS MIDDLEWARE
# ==========================
class CorsMiddleware(MiddlewareMixin):
    """
    Handles CORS headers for cross-origin requests.
    Note: This works alongside django-corsheaders. If you're already
    using that package fully, this can be removed to avoid duplication.
    """
    CORS_ORIGIN = "http://localhost:5173"
    CORS_METHODS = "GET, POST, PUT, DELETE, PATCH, OPTIONS"
    CORS_HEADERS = "Content-Type, Authorization, X-Requested-With"

    def process_request(self, request):
        if request.method == "OPTIONS":
            response = self.get_response(request)
            self._set_cors_headers(response)
            response["Access-Control-Max-Age"] = "86400"
            return response
        return None

    def process_response(self, request, response):
        self._set_cors_headers(response)
        return response

    def _set_cors_headers(self, response):
        response["Access-Control-Allow-Origin"] = self.CORS_ORIGIN
        response["Access-Control-Allow-Methods"] = self.CORS_METHODS
        response["Access-Control-Allow-Headers"] = self.CORS_HEADERS
        response["Access-Control-Allow-Credentials"] = "true"


# ==========================
# TENANT MIDDLEWARE
# ==========================
class TenantMiddleware:
    """
    Automatically attaches the tenant to the request object.
    Requires AuthenticationMiddleware to run before it in MIDDLEWARE settings.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        self._attach_tenant(request)
        response = self.get_response(request)
        return response

    def _attach_tenant(self, request):
        try:
            if request.user.is_authenticated and request.user.tenant:
                request.tenant = request.user.tenant

                # Block access entirely if the tenant has been deactivated
                if not request.tenant.is_active:
                    request.tenant = None
                    logger.warning(
                        "Request from user %s blocked — tenant '%s' is inactive.",
                        request.user.email,
                        request.user.tenant.company_name,
                    )
            else:
                request.tenant = None
        except Exception:
            request.tenant = None
            logger.exception("TenantMiddleware: unexpected error attaching tenant.")


# ==========================
# AUDIT LOG MIDDLEWARE
# ==========================
class AuditLogMiddleware:
    """
    Logs security-relevant actions (login, logout, password change) to the AuditLog table.
    Only logs on successful responses (HTTP 200).
    """

    # Maps URL paths to AuditLog action choices defined in the AuditLog model.
    ACTION_MAP = {
        "/api/auth/login/":           "login",
        "/api/auth/logout/":          "logout",
        "/api/auth/change-password/": "password_change",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        self._maybe_log_action(request, response)
        return response

    def _maybe_log_action(self, request, response):
        """Create an AuditLog entry if the request matches a tracked action."""
        if not request.user.is_authenticated:
            return

        action = self.ACTION_MAP.get(request.path)
        if not action:
            return

        # Only log successful responses
        if response.status_code != 200:
            return

        try:
            AuditLog.objects.create(
                user=request.user,
                tenant=getattr(request, "tenant", None) or request.user.tenant,
                action=action,
                ip_address=self._get_client_ip(request),
            )
        except Exception:
            # Audit logging should never crash the main request/response cycle
            logger.exception(
                "AuditLogMiddleware: failed to log action '%s' for user %s.",
                action,
                request.user.email,
            )

    @staticmethod
    def _get_client_ip(request):
        """
        Extract the real client IP, accounting for proxies.
        Takes the first (leftmost) address from X-Forwarded-For,
        which is the original client IP before any proxy hops.
        """
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")


# ==========================
# REQUEST TIMING MIDDLEWARE
# ==========================
class RequestTimingMiddleware:
    """
    Adds an X-Response-Time header (in milliseconds) to every response.
    Useful for performance monitoring and identifying slow endpoints.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        duration_ms = round((time.monotonic() - start) * 1000, 2)
        response["X-Response-Time"] = f"{duration_ms}ms"
        return response


# ==========================
# INACTIVE TENANT MIDDLEWARE
# ==========================
class BlockInactiveTenantMiddleware:
    """
    Returns HTTP 403 for any authenticated user whose tenant is inactive.
    Place this after TenantMiddleware in the MIDDLEWARE list so that
    request.tenant is already resolved before this check runs.
    """
    EXEMPT_PATHS = {"/api/auth/login/", "/api/auth/logout/", "/admin/"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._should_block(request):
            from django.http import JsonResponse
            return JsonResponse(
                {"detail": "Your organisation's account is inactive. Please contact support."},
                status=403,
            )
        return self.get_response(request)

    def _should_block(self, request):
        if request.path in self.EXEMPT_PATHS:
            return False
        tenant = getattr(request, "tenant", None)
        return request.user.is_authenticated and tenant is not None and not tenant.is_active