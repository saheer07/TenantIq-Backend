"""
Tenant Middleware for Document Service - FIXED VERSION
Handles cases where tenant_id might not be in JWT yet
"""
from django.http import JsonResponse
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
import logging
import uuid
import jwt

logger = logging.getLogger(__name__)


class TenantMiddleware:
    """
    Middleware to extract and set tenant ID from JWT token or X-Tenant-ID header.
    Windows-compatible version (no emoji characters in log messages).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Extract tenant ID
        tenant_id = self._extract_tenant_id(request)

        # Set tenant ID on request object
        request.tenant_id = tenant_id

        if tenant_id:
            logger.info("[Tenant: %s] %s %s", tenant_id, request.method, request.path)
        
        response = self.get_response(request)
        return response

    def _extract_tenant_id(self, request):
        """Extract tenant ID from JWT token or X-Tenant-ID header."""
        
        tenant_id = None

        # 1. Try to extract from JWT token first
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
            try:
                # Decode without verification to get claims
                decoded = jwt.decode(
                    token,
                    options={"verify_signature": False}
                )
                tenant_id = decoded.get('tenant_id')
                
                if tenant_id:
                    logger.debug("Tenant ID from JWT token: %s", tenant_id)
                else:
                    logger.debug("JWT token does not contain 'tenant_id' claim - will use X-Tenant-ID header")
                    
            except Exception as e:
                logger.debug("Could not decode JWT token: %s", str(e))

        # 2. Fall back to X-Tenant-ID header
        if not tenant_id:
            tenant_id = request.META.get('HTTP_X_TENANT_ID')
            if tenant_id:
                logger.info("Tenant ID from X-Tenant-ID header: %s", tenant_id)

        if not tenant_id:
            return None
        # Normalise for consistent multi-tenant isolation across services
        return str(tenant_id).strip().lower()

class RequestLoggingMiddleware:
    """
    Optional middleware to log all requests for audit purposes.
    Useful for debugging tenant isolation issues.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.logger = logging.getLogger('request_audit')
    
    def __call__(self, request):
        # Log request
        tenant_id = getattr(request, 'tenant_id', 'none')
        user_id = getattr(request.user, 'id', 'anonymous') if hasattr(request, 'user') else 'anonymous'
        
        self.logger.info(
            f"REQUEST: {request.method} {request.path} | "
            f"Tenant: {tenant_id} | User: {user_id} | "
            f"IP: {self._get_client_ip(request)}"
        )
        
        response = self.get_response(request)
        
        # Log response
        self.logger.info(
            f"RESPONSE: {request.method} {request.path} | "
            f"Status: {response.status_code} | "
            f"Tenant: {tenant_id}"
        )
        
        return response
    
    def _get_client_ip(self, request):
        """Get client IP from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', '')
        return ip