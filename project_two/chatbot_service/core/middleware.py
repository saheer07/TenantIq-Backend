from django.conf import settings
from django.db import connection, Http404
from django_tenants.utils import get_tenant_model, get_public_schema_name

class HeaderTenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 1. Try to get tenant from header
        tenant_schema = request.headers.get('X-Tenant-ID') or request.headers.get('X-Schema-Name')

        if tenant_schema:
            try:
                # Resolve tenant by schema_name
                model = get_tenant_model()
                tenant = model.objects.get(schema_name=tenant_schema)
                
                # Set the tenant and schema
                request.tenant = tenant
                connection.set_tenant(request.tenant)
                
            except model.DoesNotExist:
                # If tenant id/schema invalid, maybe 404 or fall back to public?
                # For microservices, if explicit header is sent but invalid, we likely want to error.
                # But to avoid breaking valid non-tenant requests if any, we could fallback.
                # However, usually strict is better for 'X-Tenant-ID'.
                 raise Http404(f"Tenant with schema '{tenant_schema}' not found.")
        else:
            # Fallback (optional): if you want to support domain-based as well, 
            # you can leave it to django-tenants middleware or handle it here.
            # For now, if no header, we assume public or let downstream handle it.
            # But django-tenants often needs a tenant set.
            # If standard TenantMainMiddleware is NOT used, we must set public here.
            # If TenantMainMiddleware IS used, it will overwrite this if it runs after, 
            # or we should rely on it if header is missing.
            
            # If we want to support ONLY header or Public:
             public_schema = get_public_schema_name()
             connection.set_schema_to_public()
             # We might want to set request.tenant to public tenant instance if possible, 
             # but often just schema is enough for shared apps.
        
        response = self.get_response(request)
        return response
