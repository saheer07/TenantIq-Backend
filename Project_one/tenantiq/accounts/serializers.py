# backend/accounts/serializers.py
from django.contrib.auth import get_user_model, password_validation
from django.db import transaction, IntegrityError
from django.utils import timezone
from datetime import timedelta
import random
import re

from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Tenant, OTP, AuditLog, AIUsageLog
from .utils import send_otp_email

User = get_user_model()


# ======================
# SCHEMA NAME HELPER
# ======================
def generate_schema_name(company_name):
    schema = company_name.lower().strip()
    schema = re.sub(r'[^a-z0-9]', '_', schema)
    schema = re.sub(r'_+', '_', schema)
    schema = schema.strip('_')
    if schema and schema[0].isdigit():
        schema = f"t_{schema}"
    return schema or "tenant"


# ======================
# TENANT SERIALIZER
# ======================
class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = "__all__"


# ======================
# USER PROFILE SERIALIZER
# ======================
class UserProfileSerializer(serializers.Serializer):
    """
    Read-only serializer that reads from the user_profile related object.
    Uses Serializer (not ModelSerializer) to avoid import coupling with
    user_management app — safe even if the profile doesn't exist.
    """
    company_name = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    address = serializers.SerializerMethodField()
    bio = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()
    preferences = serializers.SerializerMethodField()

    def get_company_name(self, obj):
        return getattr(obj, 'company_name', '') or ''

    def get_phone(self, obj):
        return getattr(obj, 'phone', '') or ''

    def get_address(self, obj):
        return getattr(obj, 'address', '') or ''

    def get_bio(self, obj):
        return getattr(obj, 'bio', '') or ''

    def get_avatar_url(self, obj):
        return getattr(obj, 'avatar_url', '') or ''

    def get_preferences(self, obj):
        return getattr(obj, 'preferences', {}) or {}


class UserProfileUpdateSerializer(serializers.Serializer):
    """Used for updating profile fields."""
    company_name = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True)
    address = serializers.CharField(required=False, allow_blank=True)
    bio = serializers.CharField(required=False, allow_blank=True)
    avatar_url = serializers.URLField(required=False, allow_blank=True)
    preferences = serializers.DictField(required=False)


# ======================
# USER SERIALIZER (READ)
# ✅ FIX: uses full_name (correct field name), exposes 'name' alias for frontend
# ======================
class UserSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source="tenant.company_name", read_only=True)
    # Expose 'name' as an alias so the frontend Profile.jsx works without changes
    name = serializers.CharField(source="full_name", read_only=True)
    company_name = serializers.CharField(source="tenant.company_name", read_only=True)
    profile = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "name",           # alias for full_name
            "phone",
            "department",
            "role",
            "tenant",
            "tenant_name",
            "company_name",
            "is_verified",
            "is_active",
            "created_at",
            "profile",
        ]

    def get_profile(self, obj):
        profile = getattr(obj, 'user_profile', None)
        if profile:
            return UserProfileSerializer(profile).data
        return None


# ======================
# USER DETAIL SERIALIZER
# ======================
class UserDetailSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source="tenant.company_name", read_only=True)
    name = serializers.CharField(source="full_name", read_only=True)
    profile = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "email", "full_name", "name", "phone", "role",
            "tenant", "tenant_name", "is_verified", "is_active",
            "is_staff", "department", "created_at", "last_password_change", "profile",
        ]

    def get_profile(self, obj):
        profile = getattr(obj, 'user_profile', None)
        if profile:
            return UserProfileSerializer(profile).data
        return None


# ======================
# USER CREATE
# ======================
class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ["email", "full_name", "phone", "role", "tenant", "password"]

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User.objects.create_user(password=password, **validated_data)

        # Try to create profile, don't fail if it errors
        try:
            from .models import UserProfile
            UserProfile.objects.get_or_create(user=user)
        except Exception as e:
            print(f"Warning: Could not create profile for {user.email}: {e}")

        return user


# ======================
# USER UPDATE
# ======================
class UserUpdateSerializer(serializers.ModelSerializer):
    profile = UserProfileUpdateSerializer(source='user_profile', required=False)

    class Meta:
        model = User
        fields = ["full_name", "phone", "role", "is_active", "is_verified", "department", "profile"]

    def update(self, instance, validated_data):
        profile_data = validated_data.pop('user_profile', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if profile_data:
            try:
                from .models import UserProfile
                profile, _ = UserProfile.objects.get_or_create(user=instance)
                for attr, value in profile_data.items():
                    setattr(profile, attr, value)
                profile.save()
            except Exception as e:
                print(f"Warning: Could not update profile: {e}")

        return instance


# ======================
# SIGNUP
# ======================
class SignupSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=100)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)
    company_name = serializers.CharField(max_length=150)

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Email already registered.")
        return value

    def validate_company_name(self, value):
        value = value.strip().lower()
        if Tenant.objects.filter(company_name__iexact=value).exists():
            raise serializers.ValidationError("Company name already exists. Please choose another.")
        return value

    def validate(self, data):
        if data["password"] != data["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return data

    @transaction.atomic
    def create(self, validated_data):
        validated_data.pop("confirm_password")
        company_name = validated_data.pop("company_name").strip().lower()

        base_schema = generate_schema_name(company_name)
        schema_name = base_schema
        counter = 1
        while Tenant.objects.filter(schema_name=schema_name).exists():
            schema_name = f"{base_schema}_{counter}"
            counter += 1

        try:
            tenant = Tenant.objects.create(
                company_name=company_name,
                schema_name=schema_name,
            )
        except IntegrityError:
            raise serializers.ValidationError({"company_name": "Company name already exists."})

        user = User.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            full_name=validated_data["full_name"],
            tenant=tenant,
            role="TENANT_ADMIN",
            is_active=True,
            is_verified=False,
        )

        try:
            from .models import UserProfile
            UserProfile.objects.create(user=user, preferences={})
        except Exception as e:
            print(f"Warning: Could not create profile for {user.email}: {e}")

        otp_code = str(random.randint(100000, 999999))
        OTP.objects.create(
            user=user,
            otp_code=otp_code,
            purpose="email_verification",
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        send_otp_email(user.email, otp_code)
        return user


# ======================
# VERIFY EMAIL
# ======================
class VerifyEmailSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6)

    def validate(self, data):
        try:
            user = User.objects.get(email=data["email"])
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found.")

        otp_obj = OTP.objects.filter(user=user, otp_code=data["otp"], is_used=False).first()
        if not otp_obj or not otp_obj.is_valid():
            raise serializers.ValidationError("Invalid or expired OTP.")

        data["user"] = user
        data["otp_obj"] = otp_obj
        return data


# ======================
# OTP VERIFY
# ======================
class OTPVerifySerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp_code = serializers.CharField(max_length=6)

    def validate(self, data):
        try:
            user = User.objects.get(email=data["email"])
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found.")

        otp_obj = OTP.objects.filter(
            user=user, otp_code=data["otp_code"], purpose="email_verification", is_used=False
        ).first()

        if not otp_obj or not otp_obj.is_valid():
            raise serializers.ValidationError("Invalid or expired OTP.")

        data["user"] = user
        data["otp_obj"] = otp_obj
        return data


# ======================
# LOGIN
# ======================
class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        try:
            user = User.objects.get(email=data["email"])
        except User.DoesNotExist:
            raise serializers.ValidationError("Invalid email or password.")

        if not user.check_password(data["password"]):
            raise serializers.ValidationError("Invalid email or password.")

        data["user"] = user
        return data


# ======================
# OTP REQUEST
# ======================
class OTPRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        try:
            user = User.objects.get(email=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found.")

        if user.is_verified:
            raise serializers.ValidationError("Email already verified.")

        self.context["user"] = user
        return value


# ======================
# PASSWORD RESET REQUEST
# ======================
class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        if not User.objects.filter(email=value).exists():
            raise serializers.ValidationError("No account found with this email address.")
        return value


# ======================
# PASSWORD RESET CONFIRM
# ======================
class PasswordResetConfirmSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6)
    new_password = serializers.CharField(min_length=8, write_only=True)

    def validate(self, data):
        try:
            user = User.objects.get(email=data["email"])
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found.")

        otp_obj = OTP.objects.filter(user=user, otp_code=data["otp"], is_used=False).first()
        if not otp_obj or not otp_obj.is_valid():
            raise serializers.ValidationError("Invalid or expired OTP.")

        data["user"] = user
        data["otp_obj"] = otp_obj
        return data


# Alias for backward compatibility
PasswordResetSerializer = PasswordResetConfirmSerializer


# ======================
# CHANGE PASSWORD
# ======================
class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect.")
        return value

    def validate_new_password(self, value):
        password_validation.validate_password(value)
        return value

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save()
        return user


# ======================
# TENANT STATS
# ✅ FIX: added inactive_users field that views now provide
# ======================
class TenantStatsSerializer(serializers.Serializer):
    total_users = serializers.IntegerField()
    active_users = serializers.IntegerField()
    inactive_users = serializers.IntegerField()
    created_at = serializers.DateTimeField(required=False)


# ======================
# USER INVITATION
# ======================
class UserInvitationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=[("TENANT_ADMIN", "Tenant Admin"), ("TENANT_USER", "User")])
    tenant_id = serializers.UUIDField()


# ======================
# AUDIT LOG
# ✅ FIX: uses 'timestamp' (correct model field), not 'created_at'
# ======================
class AuditLogSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source="user.email", read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "user",
            "user_email",
            "action",
            "timestamp",      # ✅ correct field name from model
            "ip_address",
        ]


# ======================
# CUSTOM TOKEN SERIALIZER
# ======================
class MyTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        if hasattr(user, 'tenant') and user.tenant:
            token['tenant_id'] = user.tenant.schema_name
        return token


# ======================
# AI USAGE LOG
# ======================
class AIUsageLogSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source="user.email", read_only=True)
    tenant_name = serializers.CharField(source="tenant.company_name", read_only=True)

    class Meta:
        model = AIUsageLog
        fields = [
            "id", "user", "user_email", "tenant", "tenant_name",
            "query", "tokens_used", "created_at",
        ]