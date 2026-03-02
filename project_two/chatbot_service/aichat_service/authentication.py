# from rest_framework.authentication import BaseAuthentication
# from rest_framework.exceptions import AuthenticationFailed
# from django.conf import settings
# import jwt
# import logging

# logger = logging.getLogger(__name__)


# class MicroserviceJWTAuthentication(BaseAuthentication):
  
    
#     def authenticate(self, request):
#         auth_header = request.headers.get('Authorization')
        
#         if not auth_header:
#             logger.warning("No Authorization header found")
#             return None
        
#         try:
#             # Extract token
#             parts = auth_header.split()
#             if len(parts) != 2 or parts[0].lower() != 'bearer':
#                 logger.warning(f"Invalid Authorization header format: {auth_header}")
#                 return None
            
#             token = parts[1]
            
#             # Decode JWT token
#             try:
#                 payload = jwt.decode(
#                     token,
#                     settings.SECRET_KEY,
#                     algorithms=['HS256']
#                 )
#             except jwt.ExpiredSignatureError:
#                 logger.error("Token has expired")
#                 raise AuthenticationFailed('Token has expired')
#             except jwt.InvalidTokenError as e:
#                 logger.error(f"Invalid token: {e}")
#                 raise AuthenticationFailed('Invalid token')
            
#             # Create a simple user object with required attributes
#             class User:
#                 def __init__(self, payload):
#                     self.id = payload.get('user_id')
#                     self.user_id = payload.get('user_id')
#                     self.tenant_id = payload.get('tenant_id')
#                     self.email = payload.get('email', '')
#                     self.is_authenticated = True
                
#                 def __str__(self):
#                     return f"User(id={self.user_id}, tenant={self.tenant_id})"
            
#             user = User(payload)
            
#             # ✅ CRITICAL: Validate that we have required fields
#             if not user.user_id:
#                 logger.error(f"Missing user_id in token payload: {payload}")
#                 raise AuthenticationFailed('Invalid token: missing user_id')
            
#             if not user.tenant_id:
#                 logger.error(f"Missing tenant_id in token payload: {payload}")
#                 raise AuthenticationFailed('Invalid token: missing tenant_id')
            
#             logger.info(f"✅ Authenticated user: {user}")
#             return (user, None)
            
#         except AuthenticationFailed:
#             raise
#         except Exception as e:
#             logger.error(f"Authentication error: {e}", exc_info=True)
#             raise AuthenticationFailed(f'Authentication failed: {str(e)}')


# class APIKeyAuthentication(BaseAuthentication):
#     """
#     API Key authentication for webhooks
#     """
    
#     def authenticate(self, request):
#         api_key = request.headers.get('X-API-Key')
        
#         if not api_key:
#             logger.warning("No API Key provided")
#             return None
        
#         expected_key = getattr(settings, 'WEBHOOK_API_KEY', 'webhook-secret-key-12345')
        
#         if api_key != expected_key:
#             logger.error("Invalid API Key")
#             raise AuthenticationFailed('Invalid API Key')
        
#         # Create a system user for webhook requests
#         class SystemUser:
#             def __init__(self):
#                 self.id = 'system'
#                 self.user_id = 'system'
#                 self.tenant_id = None
#                 self.is_authenticated = True
            
#             def __str__(self):
#                 return "SystemUser(webhook)"
        
#         return (SystemUser(), None)


"""
chatbot_service/aichat_service/authentication.py

FIX: APIKeyAuthentication now reads X-API-Key in all common capitalisation
variants so the webhook from document_service always passes authentication.
"""

import jwt
import logging
from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

logger = logging.getLogger(__name__)


# ==================== JWT AUTHENTICATION ====================

class MicroserviceJWTAuthentication(BaseAuthentication):
    """
    Validates JWT tokens issued by the auth service.
    Expects: Authorization: Bearer <token>
    """

    def authenticate(self, request):
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')

        if not auth_header.startswith('Bearer '):
            return None

        token = auth_header.split(' ', 1)[1].strip()

        try:
            jwt_secret = getattr(settings, 'JWT_SECRET_KEY', settings.SECRET_KEY)
            payload = jwt.decode(
                token,
                jwt_secret,
                algorithms=[getattr(settings, 'JWT_ALGORITHM', 'HS256')]
            )
            return (JWTUser(payload), token)

        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed('Token has expired')
        except jwt.InvalidTokenError as e:
            raise AuthenticationFailed(f'Invalid token: {e}')

    def authenticate_header(self, request):
        return 'Bearer'


class JWTUser:
    """Lightweight user object populated from JWT payload"""

    def __init__(self, payload):
        self.id = payload.get('user_id') or payload.get('id')
        self.pk = self.id           # ← required by DRF UserRateThrottle
        self.tenant_id = payload.get('tenant_id')
        self.email = payload.get('email', '')
        self.is_authenticated = True
        self.is_active = True
        self.payload = payload

    def __str__(self):
        return f"JWTUser(id={self.id}, tenant={self.tenant_id})"


# ==================== API KEY AUTHENTICATION ====================

class APIKeyAuthentication(BaseAuthentication):
    """
    Validates a static API key sent by the document service webhook.

    Accepts the key in any of these headers (case-insensitive via Django's
    META normalisation):
        X-API-Key        → HTTP_X_API_KEY
        X-Api-Key        → HTTP_X_API_KEY   (same after normalisation)
        Authorization    → as "ApiKey <key>" (fallback)

    The expected key is read from settings.WEBHOOK_API_KEY.
    """

    def authenticate(self, request):
        expected_key = getattr(settings, 'WEBHOOK_API_KEY', '').strip()

        if not expected_key:
            logger.error(
                "[APIKeyAuth] WEBHOOK_API_KEY is not set in settings! "
                "All webhook requests will be rejected."
            )
            raise AuthenticationFailed('Server misconfiguration: webhook key not set')

        # ── Step 1: Try HMAC Signature Validation (Secure) ──────────────────
        signature = request.META.get('HTTP_X_WEBHOOK_SIGNATURE', '')
        if signature:
            import hmac
            import hashlib
            
            body = request.body
            expected_signature = hmac.new(
                expected_key.encode(),
                body,
                hashlib.sha256
            ).hexdigest()
            
            if hmac.compare_digest(signature, expected_signature):
                logger.debug("[APIKeyAuth] HMAC signature validated successfully")
                return (WebhookUser(), signature)
            else:
                logger.warning(f"[APIKeyAuth] Invalid HMAC signature provided: {signature[:10]}...")
                raise AuthenticationFailed('Invalid webhook signature')

        # ── Step 2: Fallback to static API Key (Legacy/Internal) ───────────
        # Django normalises headers to uppercase with HTTP_ prefix
        provided_key = (
            request.META.get('HTTP_X_API_KEY', '').strip()
            or request.META.get('HTTP_X_Api_Key', '').strip()
        )

        # Fallback: Authorization: ApiKey <key>
        if not provided_key:
            auth_header = request.META.get('HTTP_AUTHORIZATION', '')
            if auth_header.lower().startswith('apikey '):
                provided_key = auth_header.split(' ', 1)[1].strip()

        if not provided_key:
            logger.warning(
                "[APIKeyAuth] Request missing API key or signature. "
                "Expected header: X-Webhook-Signature (HMAC) or X-API-Key."
            )
            raise AuthenticationFailed('Authentication required (X-Webhook-Signature or X-API-Key)')

        if provided_key != expected_key:
            logger.warning(
                f"[APIKeyAuth] Invalid API key provided. "
                f"Got: {provided_key[:8]}... Expected: {expected_key[:8]}..."
            )
            raise AuthenticationFailed('Invalid API key')

        logger.debug("[APIKeyAuth] API key validated successfully (Static Fallback)")
        return (WebhookUser(), provided_key)

    def authenticate_header(self, request):
        return 'ApiKey'


class WebhookUser:
    """
    Sentinel user object for authenticated webhook calls.

    Must have 'pk' because DRF's UserRateThrottle calls
    request.user.pk to build the throttle cache key.
    """
    pk = 'webhook'          # ← fixes: 'WebhookUser has no attribute pk'
    id = 'webhook'
    is_authenticated = True
    is_active = True

    def __str__(self):
        return "WebhookUser"