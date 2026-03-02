from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class MicroserviceUser:
    """
    Lightweight user object for microservices.
    Doesn't require database - just holds JWT claims.
    """
    def __init__(self, user_id, tenant_id=None, subscription=None, **extra_claims):
        self.id = user_id
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.subscription = subscription
        self.is_authenticated = True
        self.is_active = True
        self.is_anonymous = False
        
        # Store any extra claims from JWT
        for key, value in extra_claims.items():
            setattr(self, key, value)
    
    def __str__(self):
        return f"MicroserviceUser(id={self.id}, tenant={self.tenant_id}, sub={self.subscription})"


class MicroserviceJWTAuthentication(JWTAuthentication):
    """
    Custom JWT Authentication for microservices.
    Doesn't look up user in database - creates user from JWT claims.
    """
    
    def get_user(self, validated_token):
        """
        Extract user information from JWT token without database lookup.
        """
        try:
            user_id = validated_token.get('user_id')
            if user_id is None:
                raise InvalidToken('Token contained no recognizable user identification')
            
            # Extract tenant_id and other claims
            tenant_id = validated_token.get('tenant_id')
            subscription = validated_token.get('subscription') or validated_token.get('plan')
            
            extra_claims = {
                'email': validated_token.get('email'),
                'username': validated_token.get('username'),
                'role': validated_token.get('role'),
            }
            
            # Remove None values
            extra_claims = {k: v for k, v in extra_claims.items() if v is not None}
            
            return MicroserviceUser(
                user_id=user_id, 
                tenant_id=tenant_id, 
                subscription=subscription,
                **extra_claims
            )
            
        except KeyError:
            raise InvalidToken('Token contained no recognizable user identification')


class APIKeyAuthentication(BaseAuthentication):
    """
    Validates a static API key sent by the chatbot service webhook.
    """

    def authenticate(self, request):
        expected_key = getattr(settings, 'WEBHOOK_API_KEY', '').strip()

        if not expected_key:
            logger.error("[APIKeyAuth] WEBHOOK_API_KEY is not set in settings!")
            raise AuthenticationFailed('Server misconfiguration: webhook key not set')

        provided_key = (
            request.META.get('HTTP_X_API_KEY', '').strip()
            or request.META.get('HTTP_X_Api_Key', '').strip()
        )

        if not provided_key:
            auth_header = request.META.get('HTTP_AUTHORIZATION', '')
            if auth_header.lower().startswith('apikey '):
                provided_key = auth_header.split(' ', 1)[1].strip()

        if not provided_key:
            raise AuthenticationFailed('Authentication required (X-API-Key)')

        if provided_key != expected_key:
            raise AuthenticationFailed('Invalid API key')

        class WebhookUser:
            pk = 'webhook'
            id = 'webhook'
            is_authenticated = True
            is_active = True
            def __str__(self): return "WebhookUser"

        return (WebhookUser(), provided_key)

    def authenticate_header(self, request):
        return 'ApiKey'