import uuid
from django.test import TestCase, RequestFactory
from django.http import HttpResponse
from .middleware import TenantMiddleware
from .authentication import MicroserviceUser
from unittest.mock import MagicMock

class MiddlewareTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = TenantMiddleware(lambda r: HttpResponse())

    def test_extract_tenant_id_from_header(self):
        tenant_id = "black_rigs"
        request = self.factory.get('/api/doc/documents/', HTTP_X_TENANT_ID=tenant_id)
        self.middleware(request)
        self.assertEqual(request.tenant_id, tenant_id)

    def test_extract_tenant_id_missing(self):
        request = self.factory.get('/api/doc/documents/')
        self.middleware(request)
        self.assertIsNone(request.tenant_id)

class AuthenticationTest(TestCase):
    def test_microservice_user_creation(self):
        user_id = uuid.uuid4()
        tenant_id = "black_rigs"
        user = MicroserviceUser(user_id=user_id, tenant_id=tenant_id, subscription='pro')
        self.assertEqual(user.id, user_id)
        self.assertEqual(user.tenant_id, tenant_id)
        self.assertEqual(user.subscription, 'pro')
        self.assertTrue(user.is_authenticated)

# You can add more integration tests here if the environment supports it
# For now, these unit tests verify the core logic changes.
