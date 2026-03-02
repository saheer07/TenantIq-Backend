from django.db import models
from django_tenants.models import TenantMixin, DomainMixin

class Tenant(TenantMixin):
    # BASIC INFO
    company_name = models.CharField(max_length=255) # Removed unique=True to avoid index creation issues in managed=False
    name = models.CharField(max_length=255, blank=True, null=True)
    slug = models.SlugField(blank=True, null=True) # Removed unique=True

    # PLAN / SUBSCRIPTION
    PLAN_CHOICES = [
        ('free', 'Free'),
        ('pro', 'Pro'),
        ('enterprise', 'Enterprise'),
    ]
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default='free')

    # STATUS
    is_active = models.BooleanField(default=True)
    has_ai_access = models.BooleanField(default=True)

    # LIMITS
    max_users = models.IntegerField(default=5)
    max_documents = models.IntegerField(default=10)
    max_ai_queries_per_month = models.IntegerField(default=100)

    # TIMESTAMPS
    created_at = models.DateTimeField(auto_now_add=True)

    # Required by django-tenants
    auto_create_schema = False # We don't want to create schemas from here

    def __str__(self):
        return self.company_name

    class Meta:
        managed = False # Managed by Project_one
        db_table = "tenants"


class Domain(DomainMixin):
    class Meta:
        managed = False # Managed by Project_one
        db_table = "tenant_domains"
