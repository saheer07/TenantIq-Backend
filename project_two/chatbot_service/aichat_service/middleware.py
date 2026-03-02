import logging
import jwt
from django.conf import settings
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)

class HeaderTenantMiddleware(MiddlewareMixin):
    """
    Middleware to extract tenant_id from JWT token payload or X-Tenant-ID header.
    Sets request.tenant_id for downstream views and processes.
    """

    def process_request(self, request):
        tenant_id = self._extract_tenant_id(request)
        request.tenant_id = tenant_id
        
        if tenant_id:
            # Optionally log tenant context for debugging
            # logger.debug(f"[TenantMiddleware] Tenant context set: {tenant_id}")
            pass
        
        return None

    def _extract_tenant_id(self, request):
        """
        Logic to resolve tenant_id:
        1. Access token claim 'tenant_id'
        2. X-Tenant-ID header (fallback)
        """
        tenant_id = None

        # 1. Try JWT claim (without full verification here, leave that to DRF auth)
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
            try:
                # Decode without verification just to get the claim
                # Signature verification happens later in MicroserviceJWTAuthentication
                decoded = jwt.decode(token, options={"verify_signature": False})
                tenant_id = decoded.get('tenant_id')
            except Exception:
                pass

        # 2. Try X-Tenant-ID header
        if not tenant_id:
            tenant_id = (
                request.META.get('HTTP_X_TENANT_ID') or 
                request.META.get('HTTP_X_TENANT_ID'.replace('-', '_')) or
                request.headers.get('X-Tenant-ID')
            )

        return tenant_id
