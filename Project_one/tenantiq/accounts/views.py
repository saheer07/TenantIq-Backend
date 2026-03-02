# backend/accounts/views.py
import random
import re
import secrets
import logging
from datetime import timedelta
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.contrib.auth import authenticate
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken

from .email_service import send_otp_email
from .models import OTP, User, Tenant, AuditLog, AIUsageLog
from .serializers import (
    PasswordResetConfirmSerializer, UserSerializer, UserCreateSerializer, UserUpdateSerializer,
    LoginSerializer, OTPRequestSerializer, OTPVerifySerializer,
    SignupSerializer, PasswordResetRequestSerializer, PasswordResetSerializer,
    ChangePasswordSerializer, TenantSerializer, TenantStatsSerializer,
    UserInvitationSerializer,
    AuditLogSerializer, AIUsageLogSerializer, VerifyEmailSerializer
)

logger = logging.getLogger(__name__)


# ==================== AUTH ENDPOINTS ====================

class LoginAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        try:
            email = request.data.get("email", "").strip()
            password = request.data.get("password", "")

            if not email or not password:
                return Response(
                    {"error": "Email and password are required"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                return Response(
                    {"error": "Invalid email or password"},
                    status=status.HTTP_401_UNAUTHORIZED
                )

            if not user.check_password(password):
                return Response(
                    {"error": "Invalid email or password"},
                    status=status.HTTP_401_UNAUTHORIZED
                )

            if not user.is_active:
                return Response(
                    {"error": "Account is disabled"},
                    status=status.HTTP_403_FORBIDDEN
                )

            refresh = RefreshToken.for_user(user)
            if hasattr(user, 'tenant') and user.tenant:
                refresh['tenant_id'] = user.tenant.schema_name

            name = getattr(user, "full_name", None) or user.email
            role = getattr(user, "role", None)
            tenant_id = user.tenant.schema_name if hasattr(user, "tenant") and user.tenant else None
            tenant_name = user.tenant.company_name if hasattr(user, "tenant") and user.tenant else None
            is_verified = getattr(user, "is_verified", False)

            # Update last login
            user.save(update_fields=[])

            return Response({
                "success": True,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": {
                    "id": str(user.id),
                    "email": user.email,
                    "name": name,
                    "full_name": name,
                    "role": role,
                    "tenant_id": tenant_id,
                    "company_name": tenant_name,
                    "is_verified": is_verified,
                    "email_verified": is_verified,
                    "is_active": user.is_active,
                },
                "message": "Login successful"
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("LOGIN API ERROR")
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SendOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = OTPRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = User.objects.get(email=serializer.validated_data["email"])
        otp_code = str(random.randint(100000, 999999))

        OTP.objects.create(
            user=user,
            otp_code=otp_code,
            purpose="email_verification",
            expires_at=timezone.now() + timedelta(minutes=10),
        )

        send_otp_email(user.email, otp_code)

        return Response(
            {"success": True, "message": "OTP sent successfully"},
            status=status.HTTP_200_OK
        )


class VerifyEmailView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get("email")
        otp = request.data.get("otp")

        if not email or not otp:
            return Response(
                {"error": "Email and OTP are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user = User.objects.get(email=email)

            otp_obj = OTP.objects.filter(
                user=user,
                otp_code=otp,
                purpose="email_verification",
                is_used=False
            ).first()

            if not otp_obj:
                return Response({"error": "Invalid OTP"}, status=status.HTTP_400_BAD_REQUEST)

            if not otp_obj.is_valid():
                return Response({"error": "OTP expired"}, status=status.HTTP_400_BAD_REQUEST)

            user.is_verified = True
            user.save(update_fields=["is_verified"])
            otp_obj.mark_as_used()

            return Response(
                {"success": True, "message": "Email verified successfully"},
                status=status.HTTP_200_OK
            )

        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)


class ResendVerificationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')

        if not email:
            return Response({'error': 'Email is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email=email)

            if user.is_verified:
                return Response({'message': 'Email already verified'}, status=status.HTTP_400_BAD_REQUEST)

            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            verification_link = f"{settings.FRONTEND_URL}/verify-email/{uid}/{token}/"

            send_mail(
                subject='Verify Your Email',
                message=f'Hello,\n\nPlease click the link below to verify your email:\n{verification_link}\n\nThank you!',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False,
            )

            return Response(
                {'message': 'Verification email sent successfully', 'email': email},
                status=status.HTTP_200_OK
            )

        except User.DoesNotExist:
            return Response(
                {'message': 'If the email exists, a verification link has been sent'},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            logger.error(f"Error sending verification email: {str(e)}")
            return Response(
                {'error': 'Failed to send verification email. Please try again later.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SignupView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SignupSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                {"success": False, "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer.save()

        return Response(
            {"success": True, "message": "Account created successfully. Please verify your email."},
            status=status.HTTP_201_CREATED
        )


class RequestPasswordResetView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({
                'success': True,
                'message': 'If an account exists with this email, you will receive a password reset code.'
            }, status=status.HTTP_200_OK)

        otp_code = str(random.randint(100000, 999999))

        OTP.objects.filter(user=user, purpose='password_reset', is_used=False).delete()
        OTP.objects.create(
            user=user,
            otp_code=otp_code,
            purpose='password_reset',
            expires_at=timezone.now() + timedelta(minutes=10)
        )

        try:
            send_mail(
                subject='Password Reset Code',
                message=f'Hello {user.full_name},\n\nYour password reset code is:\n\n{otp_code}\n\nThis code expires in 10 minutes.',
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
                recipient_list=[email],
                fail_silently=False,
            )
        except Exception as e:
            logger.error(f"Error sending password reset email: {str(e)}")
            return Response({
                'success': False,
                'message': 'Failed to send verification code. Please try again.'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            'success': True,
            'message': 'If an account exists with this email, you will receive a password reset code.'
        }, status=status.HTTP_200_OK)


class ResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')
        otp_code = request.data.get('otp')
        new_password = request.data.get('new_password')

        if not all([email, otp_code, new_password]):
            return Response({
                'success': False,
                'message': 'Email, OTP code, and new password are required.'
            }, status=status.HTTP_400_BAD_REQUEST)

        if len(new_password) < 8:
            return Response({
                'success': False,
                'message': 'Password must be at least 8 characters long.'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Invalid verification code or email.'
            }, status=status.HTTP_400_BAD_REQUEST)

        otp_obj = OTP.objects.filter(
            user=user, otp_code=otp_code, purpose='password_reset', is_used=False
        ).first()

        if not otp_obj:
            return Response({
                'success': False,
                'message': 'Invalid or expired verification code.'
            }, status=status.HTTP_400_BAD_REQUEST)

        if not otp_obj.is_valid():
            return Response({
                'success': False,
                'message': 'Verification code has expired. Please request a new one.'
            }, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.last_password_change = timezone.now()
        user.save()
        otp_obj.mark_as_used()

        _create_audit_log(user=user, tenant=user.tenant, action='password_reset',
                          ip_address=request.META.get('REMOTE_ADDR'))

        return Response({
            'success': True,
            'message': 'Password has been reset successfully. You can now login with your new password.'
        }, status=status.HTTP_200_OK)


class ConfirmPasswordResetView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        # Reuse ResetPasswordView logic
        return ResetPasswordView().post(request)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        old_password = request.data.get("old_password")
        new_password = request.data.get("new_password")

        if not old_password or not new_password:
            return Response(
                {"message": "Old and new password required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not user.check_password(old_password):
            return Response(
                {"message": "Old password is incorrect"},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.set_password(new_password)
        user.save()

        return Response(
            {"success": True, "message": "Password changed successfully"},
            status=status.HTTP_200_OK
        )


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        _create_audit_log(
            user=request.user,
            tenant=getattr(request.user, 'tenant', None),
            action='logout',
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')
        )
        return Response({'message': 'Logged out successfully'})


# ==================== CURRENT USER ====================

class CurrentUserProfileView(APIView):
    """
    GET  /auth/me/  → return full profile
    PUT  /auth/me/  → update profile fields
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            user = request.user
            tenant = getattr(user, 'tenant', None)

            # Try to get extended profile
            profile = getattr(user, 'user_profile', None)

            data = {
                "id": str(user.id),
                "email": user.email,
                # ✅ FIX: use full_name, not name
                "name": user.full_name or "",
                "full_name": user.full_name or "",
                "phone": user.phone or "",
                "department": user.department or "",
                "role": user.role,
                "is_verified": user.is_verified,
                "is_active": user.is_active,
                "company_name": tenant.company_name if tenant else "",
                "tenant_id": tenant.schema_name if tenant else None,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "last_login": user.last_password_change.isoformat() if user.last_password_change else None,
            }

            # Merge profile fields if profile exists
            if profile:
                data["avatar_url"] = profile.avatar_url or ""
                data["bio"] = profile.bio or ""
                data["address"] = profile.address or ""

            return Response(data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("Error in CurrentUserProfileView.get")
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def put(self, request):
        try:
            user = request.user
            data = request.data

            # Update allowed User model fields
            allowed_user_fields = ['full_name', 'phone', 'department']
            user_updated = False
            for field in allowed_user_fields:
                if field in data:
                    setattr(user, field, data[field])
                    user_updated = True

            # Also accept 'name' as alias for full_name from frontend
            if 'name' in data and 'full_name' not in data:
                user.full_name = data['name']
                user_updated = True

            if user_updated:
                user.save()

            # Update profile fields if profile exists
            profile = getattr(user, 'user_profile', None)
            if profile:
                profile_fields = ['bio', 'avatar_url', 'address', 'company_name']
                profile_updated = False
                for field in profile_fields:
                    if field in data:
                        setattr(profile, field, data[field])
                        profile_updated = True
                if profile_updated:
                    profile.save()

            # Return the full updated profile by calling get
            return self.get(request)

        except Exception as e:
            logger.exception("Error in CurrentUserProfileView.put")
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ==================== USER MANAGEMENT ====================

class UserManagementView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            user = request.user

            if user.role not in ['SUPER_ADMIN', 'TENANT_ADMIN', 'TENANT_MANAGER']:
                return Response(
                    {'error': 'You do not have permission to view users'},
                    status=status.HTTP_403_FORBIDDEN
                )

            if user.role == 'SUPER_ADMIN':
                users = User.objects.select_related('tenant').all()
            elif user.role in ['TENANT_ADMIN', 'TENANT_MANAGER']:
                if not user.tenant:
                    return Response(
                        {'error': 'No tenant associated with your account'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                users = User.objects.filter(tenant=user.tenant).select_related('tenant')
            else:
                users = User.objects.filter(id=user.id).select_related('tenant')

            serializer = UserSerializer(users, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("ERROR in UserManagementView")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CreateUserView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        email = request.data.get('email')
        password = request.data.get('password')
        role = request.data.get('role', 'TENANT_USER')
        full_name = request.data.get('full_name', '')
        phone = request.data.get('phone', '')
        department = request.data.get('department', '')
        send_email = request.data.get('send_email', True)

        if not email or not password:
            return Response({'error': 'Email and password are required'}, status=status.HTTP_400_BAD_REQUEST)

        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_regex, email):
            return Response({'error': 'Invalid email format'}, status=status.HTTP_400_BAD_REQUEST)

        if user.role not in ['SUPER_ADMIN', 'TENANT_ADMIN']:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        if User.objects.filter(email=email).exists():
            return Response({'error': 'User with this email already exists'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            new_user = User.objects.create_user(
                email=email,
                password=password,
                full_name=full_name,
                phone=phone,
                department=department,
                role=role,
                tenant=user.tenant if user.tenant else None,
                is_verified=True,
                is_active=True
            )

            _create_audit_log(
                user=user,
                tenant=user.tenant,
                action='login',  # closest available action
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )

            serializer = UserSerializer(new_user)
            return Response({
                'success': True,
                'message': f'User created successfully for {email}',
                'user': serializer.data
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.exception("Error creating user")
            return Response({'error': f'Failed to create user: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class UserListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        if user.role not in ['SUPER_ADMIN', 'TENANT_ADMIN', 'TENANT_MANAGER']:
            return Response({'error': 'You do not have permission to view users'}, status=status.HTTP_403_FORBIDDEN)

        try:
            if user.role == 'SUPER_ADMIN':
                users = User.objects.select_related('tenant').all()
            elif user.role in ['TENANT_ADMIN', 'TENANT_MANAGER']:
                if not user.tenant:
                    return Response({'error': 'No tenant associated with your account'}, status=status.HTTP_400_BAD_REQUEST)
                users = User.objects.filter(tenant=user.tenant).select_related('tenant')
            else:
                users = User.objects.filter(id=user.id).select_related('tenant')

            search = request.query_params.get('search', '')
            if search:
                users = users.filter(
                    Q(email__icontains=search) | Q(full_name__icontains=search)
                )

            ordering = request.query_params.get('ordering', '-created_at')
            users = users.order_by(ordering)

            serializer = UserSerializer(users, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("Error in UserListCreateView.get")
            return Response({'error': f'Error fetching users: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        if request.user.role not in ['SUPER_ADMIN', 'TENANT_ADMIN']:
            return Response({'error': 'You do not have permission to create users'}, status=status.HTTP_403_FORBIDDEN)

        try:
            serializer = UserCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            new_user = serializer.save(tenant=request.user.tenant)

            return Response(UserSerializer(new_user).data, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.exception("Error in UserListCreateView.post")
            return Response({'error': f'Error creating user: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class UserDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, pk, request_user):
        user = get_object_or_404(User, pk=pk)
        if request_user.role == 'SUPER_ADMIN':
            return user
        elif request_user.role in ['TENANT_ADMIN', 'TENANT_MANAGER']:
            if user.tenant == request_user.tenant:
                return user
        elif user == request_user:
            return user
        return None

    def get(self, request, pk):
        user = self.get_object(pk, request.user)
        if not user:
            return Response({'error': 'User not found or access denied'}, status=status.HTTP_404_NOT_FOUND)
        return Response(UserSerializer(user).data)

    def put(self, request, pk):
        user = self.get_object(pk, request.user)
        if not user:
            return Response({'error': 'User not found or access denied'}, status=status.HTTP_404_NOT_FOUND)

        serializer = UserUpdateSerializer(user, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(user).data)

    def patch(self, request, pk):
        user = self.get_object(pk, request.user)
        if not user:
            return Response({'error': 'User not found or access denied'}, status=status.HTTP_404_NOT_FOUND)

        serializer = UserUpdateSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(user).data)

    def delete(self, request, pk):
        if request.user.role not in ['SUPER_ADMIN', 'TENANT_ADMIN']:
            return Response({'error': 'You do not have permission to delete users'}, status=status.HTTP_403_FORBIDDEN)

        try:
            if request.user.role == 'SUPER_ADMIN':
                user = User.objects.get(pk=pk)
            else:
                user = User.objects.get(pk=pk, tenant=request.user.tenant)
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

        if user.id == request.user.id:
            return Response({'error': 'You cannot delete yourself'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            email = user.email
            tenant = user.tenant
            user.delete()
            logger.info(f"User {email} deleted by {request.user.email}")
            return Response({'success': True, 'message': 'User deleted successfully'}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.exception("Error deleting user")
            return Response({'error': f'Failed to delete user: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class UserChangeRoleView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        new_role = request.data.get('role')

        if new_role not in dict(User.ROLE_CHOICES).keys():
            return Response({'error': 'Invalid role'}, status=status.HTTP_400_BAD_REQUEST)

        if request.user.role != 'SUPER_ADMIN' and new_role == 'SUPER_ADMIN':
            return Response({'error': 'You cannot assign super admin role'}, status=status.HTTP_403_FORBIDDEN)

        if user.tenant != request.user.tenant and request.user.role != 'SUPER_ADMIN':
            return Response({'error': 'You can only manage users in your organization'}, status=status.HTTP_403_FORBIDDEN)

        user.role = new_role
        user.save()
        return Response(UserSerializer(user).data)


class UserToggleActiveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role not in ['SUPER_ADMIN', 'TENANT_ADMIN']:
            return Response({'error': 'You do not have permission to manage users'}, status=status.HTTP_403_FORBIDDEN)

        try:
            if request.user.role == 'SUPER_ADMIN':
                user = get_object_or_404(User, pk=pk)
            else:
                user = get_object_or_404(User, pk=pk, tenant=request.user.tenant)

            if user == request.user:
                return Response({'error': 'You cannot deactivate your own account'}, status=status.HTTP_400_BAD_REQUEST)

            user.is_active = not user.is_active
            user.save()

            action = 'activated' if user.is_active else 'deactivated'
            return Response({'success': True, 'message': f'User {action} successfully', 'is_active': user.is_active})

        except Exception as e:
            logger.exception("Error toggling user status")
            return Response({'error': f'Failed to update user status: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==================== TENANT MANAGEMENT ====================

class TenantListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != 'SUPER_ADMIN':
            return Response({'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        tenants = Tenant.objects.all()
        return Response(TenantSerializer(tenants, many=True).data)

    def post(self, request):
        if request.user.role != 'SUPER_ADMIN':
            return Response({'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        company_name = request.data.get('company_name')
        if not company_name:
            return Response({'message': 'company_name is required'}, status=400)

        tenant = Tenant.objects.create(
            company_name=company_name,
            plan='free',
            max_users=5,
            max_documents=10,
            max_ai_queries=100
        )
        return Response({'message': 'Tenant created', 'tenant_id': str(tenant.id)})


class TenantDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        tenant = get_object_or_404(Tenant, pk=pk)
        if request.user.role != 'SUPER_ADMIN' and request.user.tenant != tenant:
            return Response({'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        return Response(TenantSerializer(tenant).data)

    def put(self, request, pk):
        tenant = get_object_or_404(Tenant, pk=pk)
        if request.user.role != 'SUPER_ADMIN' and request.user.tenant != tenant:
            return Response({'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        serializer = TenantSerializer(tenant, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def patch(self, request, pk):
        tenant = get_object_or_404(Tenant, pk=pk)
        if request.user.role != 'SUPER_ADMIN' and request.user.tenant != tenant:
            return Response({'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        serializer = TenantSerializer(tenant, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk):
        if request.user.role != 'SUPER_ADMIN':
            return Response({'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        tenant = get_object_or_404(Tenant, pk=pk)
        tenant.delete()
        return Response({'message': 'Tenant deleted successfully'}, status=status.HTTP_204_NO_CONTENT)


class TenantStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        tenant = get_object_or_404(Tenant, pk=pk)
        if request.user.role != 'SUPER_ADMIN' and request.user.tenant != tenant:
            return Response({'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        total = tenant.users.count()
        active = tenant.users.filter(is_active=True).count()
        stats = {
            'total_users': total,
            'active_users': active,
            'inactive_users': total - active,   # ✅ FIX: provide inactive_users
        }
        return Response(TenantStatsSerializer(stats).data)


class TenantChangePlanView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role != 'SUPER_ADMIN':
            return Response({'message': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        tenant = get_object_or_404(Tenant, pk=pk)
        new_plan = request.data.get('plan')

        if new_plan not in dict(Tenant.PLAN_CHOICES).keys():
            return Response({'message': 'Invalid plan'}, status=status.HTTP_400_BAD_REQUEST)

        tenant.plan = new_plan
        if new_plan == 'free':
            tenant.max_ai_queries_per_month = 0
            tenant.has_ai_access = False
            tenant.max_users = 5
        elif new_plan == 'pro':
            tenant.max_ai_queries_per_month = 1000
            tenant.has_ai_access = True
            tenant.max_users = 20
        elif new_plan == 'enterprise':
            tenant.max_ai_queries_per_month = 10000
            tenant.has_ai_access = True
            tenant.max_users = 100
        tenant.save()
        return Response(TenantSerializer(tenant).data)


# ==================== AUDIT LOGS ====================

class AuditLogListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.role == 'SUPER_ADMIN':
            logs = AuditLog.objects.all().order_by('-timestamp')
        else:
            logs = AuditLog.objects.filter(tenant=user.tenant).order_by('-timestamp')

        serializer = AuditLogSerializer(logs, many=True)
        return Response(serializer.data)


class AuditLogDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            log = AuditLog.objects.get(pk=pk)
        except AuditLog.DoesNotExist:
            return Response({'message': 'Audit log not found'}, status=status.HTTP_404_NOT_FOUND)

        if request.user.role != 'SUPER_ADMIN' and log.tenant != request.user.tenant:
            return Response({'message': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)

        return Response(AuditLogSerializer(log).data)


# ==================== AI USAGE ====================

class AIUsageLogListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.role == 'SUPER_ADMIN':
            logs = AIUsageLog.objects.all()
        else:
            logs = AIUsageLog.objects.filter(tenant=user.tenant)
        return Response(AIUsageLogSerializer(logs, many=True).data)


class AIUsageLogDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            log = AIUsageLog.objects.get(pk=pk)
        except AIUsageLog.DoesNotExist:
            return Response({"detail": "Not found."}, status=404)

        if request.user.role != "SUPER_ADMIN" and log.tenant != request.user.tenant:
            return Response({"detail": "Permission denied."}, status=403)

        return Response(AIUsageLogSerializer(log).data)


# ==================== SUBSCRIPTION ====================

class CheckSubscriptionStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        if user.role == 'SUPER_ADMIN':
            return Response({'is_active': True, 'plan_name': 'Super Admin', 'plan_type': 'unlimited', 'role': 'SUPER_ADMIN'})
        if user.role == 'TENANT_ADMIN':
            return Response({'is_active': True, 'plan_name': 'Free Trial', 'plan_type': 'trial', 'max_users': 5, 'ai_enabled': True})
        if user.role == 'TENANT_USER':
            return Response({'is_active': True, 'plan_name': 'Team Access', 'plan_type': 'inherited'})

        return Response({'is_active': False, 'message': 'No subscription found'})


# ==================== HELPER FUNCTION ====================

def _create_audit_log(user, tenant, action, ip_address=None, user_agent=None, extra_data=None):
    """
    Safely create an audit log entry.
    Only uses action values that exist in AuditLog.ACTION_CHOICES.
    """
    valid_actions = [choice[0] for choice in AuditLog.ACTION_CHOICES]
    if action not in valid_actions:
        # Default to a safe fallback rather than crashing
        action = 'login'

    try:
        AuditLog.objects.create(
            user=user,
            tenant=tenant,
            action=action,
            ip_address=ip_address,
            user_agent=user_agent or '',
            extra_data=extra_data,
        )
    except Exception as e:
        logger.warning(f"Could not create audit log: {e}")