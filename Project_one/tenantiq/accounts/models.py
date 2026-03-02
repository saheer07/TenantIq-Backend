# backend/accounts/models.py
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.utils import timezone
from datetime import timedelta
import uuid
import secrets

from django_tenants.models import TenantMixin, DomainMixin
from .managers import UserManager


# ==========================
# TENANT MODEL
# ==========================
class Tenant(TenantMixin):

    company_name = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    slug = models.SlugField(unique=True, blank=True, null=True)

    PLAN_CHOICES = [
        ('free', 'Free'),
        ('pro', 'Pro'),
        ('enterprise', 'Enterprise'),
    ]
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default='free')

    is_active = models.BooleanField(default=True)
    has_ai_access = models.BooleanField(default=True)

    max_users = models.IntegerField(default=5)
    max_documents = models.IntegerField(default=10)
    max_ai_queries_per_month = models.IntegerField(default=100)

    created_at = models.DateTimeField(auto_now_add=True)

    auto_create_schema = True

    def get_current_user_count(self):
        return self.users.count()

    def has_user_capacity(self):
        return self.get_current_user_count() < self.max_users

    def __str__(self):
        return self.company_name

    class Meta:
        db_table = "tenants"


# ==========================
# DOMAIN MODEL
# ==========================
class Domain(DomainMixin):
    class Meta:
        db_table = "tenant_domains"


# ==========================
# CUSTOM USER MODEL
# ==========================
class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=15, null=True, blank=True)

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="users",
        null=True,
        blank=True
    )

    ROLE_CHOICES = [
        ('SUPER_ADMIN', 'Super Admin'),
        ('TENANT_ADMIN', 'Tenant Admin'),
        ('TENANT_MANAGER', 'Tenant Manager'),
        ('TENANT_USER', 'Tenant User'),
    ]
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='TENANT_USER')

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)

    failed_login_attempts = models.IntegerField(default=0)
    account_locked_until = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    last_password_change = models.DateTimeField(default=timezone.now)
    department = models.CharField(max_length=100, blank=True, null=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']

    objects = UserManager()

    # ✅ Property so any code using user.name still works
    @property
    def name(self):
        return self.full_name

    def is_account_locked(self):
        return self.account_locked_until and self.account_locked_until > timezone.now()

    def increment_failed_login(self):
        self.failed_login_attempts += 1
        if self.failed_login_attempts >= 5:
            self.account_locked_until = timezone.now() + timedelta(minutes=30)
        self.save()

    def reset_failed_login(self):
        self.failed_login_attempts = 0
        self.account_locked_until = None
        self.save()

    def __str__(self):
        return self.email

    class Meta:
        db_table = "accounts_user"


# ==========================
# OTP MODEL
# ==========================
class OTP(models.Model):
    PURPOSE_CHOICES = [
        ('email_verification', 'Email Verification'),
        ('password_reset', 'Password Reset'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='otps')
    otp_code = models.CharField(max_length=6)
    purpose = models.CharField(max_length=30, choices=PURPOSE_CHOICES)
    is_used = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def is_valid(self):
        return not self.is_used and timezone.now() < self.expires_at

    def mark_as_used(self):
        self.is_used = True
        self.save(update_fields=["is_used"])

    def __str__(self):
        return f"{self.user.email} - {self.purpose} - {self.otp_code}"

    class Meta:
        db_table = "otps"
        ordering = ['-created_at']


# ==========================
# PASSWORD RESET TOKEN MODEL
# ==========================
class PasswordResetToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="password_reset_tokens")
    token = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(hours=24)
        super().save(*args, **kwargs)

    def is_valid(self):
        return not self.used and timezone.now() < self.expires_at

    def mark_as_used(self):
        self.used = True
        self.save(update_fields=["used"])

    def __str__(self):
        return f"Password reset token for {self.user.email}"

    class Meta:
        db_table = "password_reset_tokens"
        ordering = ['-created_at']


# ==========================
# AUDIT LOG
# ✅ FIX: expanded ACTION_CHOICES to cover all actions used in views
# ==========================
class AuditLog(models.Model):
    ACTION_CHOICES = [
        # Auth actions
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('signup', 'Signup'),
        ('password_change', 'Password Change'),
        ('password_reset', 'Password Reset'),
        ('email_verified', 'Email Verified'),
        ('account_locked', 'Account Locked'),
        # User management actions
        ('user_created', 'User Created'),
        ('user_updated', 'User Updated'),
        ('user_deleted', 'User Deleted'),
        ('user_role_changed', 'User Role Changed'),
        ('user_activated', 'User Activated'),
        ('user_deactivated', 'User Deactivated'),
        # Tenant actions
        ('tenant_created', 'Tenant Created'),
        ('tenant_updated', 'Tenant Updated'),
        ('tenant_deleted', 'Tenant Deleted'),
        ('subscription_changed', 'Subscription Changed'),
        # Document actions
        ('document_uploaded', 'Document Uploaded'),
        ('document_deleted', 'Document Deleted'),
        ('document_shared', 'Document Shared'),
    ]

    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs'
    )
    tenant = models.ForeignKey(
        Tenant, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs'
    )
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    extra_data = models.JSONField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        user_str = self.user.email if self.user else "anonymous"
        return f"{user_str} - {self.action} at {self.timestamp:%Y-%m-%d %H:%M}"

    class Meta:
        db_table = "audit_logs"
        ordering = ['-timestamp']


# ==========================
# AI USAGE LOG
# ==========================
class AIUsageLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ai_usage_logs')
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='ai_usage_logs')
    query = models.TextField()
    response_summary = models.TextField(null=True, blank=True)
    tokens_used = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.email} | {self.tokens_used} tokens | {self.created_at:%Y-%m-%d}"

    class Meta:
        db_table = "ai_usage_logs"
        ordering = ['-created_at']


# ==========================
# USER PROFILE
# ✅ Defined ONLY here — removed duplicate in user_management app
# ==========================
class UserProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='user_profile')

    company_name = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    bio = models.TextField(blank=True, null=True)
    avatar_url = models.URLField(max_length=500, blank=True, null=True)
    preferences = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile for {self.user.email}"

    class Meta:
        db_table = "user_profiles"
        ordering = ['-created_at']