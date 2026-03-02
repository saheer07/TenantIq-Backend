# backend/accounts/auth_service.py
from django.contrib.auth import authenticate
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from datetime import timedelta
from rest_framework_simplejwt.tokens import RefreshToken
import secrets
from .models import User, Tenant,  AuditLog


class AuthService:
    MAX_LOGIN_ATTEMPTS = 5
    LOCKOUT_DURATION = timedelta(minutes=30)
    
    @staticmethod
    def get_client_ip(request):
        """Extract client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    @staticmethod
    def create_audit_log(action, user=None, tenant=None, description='', request=None, metadata=None):
        """Create audit log entry"""
        log = AuditLog.objects.create(
            action=action,
            user=user,
            tenant=tenant or (user.tenant if user else None),
            description=description,
            ip_address=AuthService.get_client_ip(request) if request else None,
            user_agent=request.META.get('HTTP_USER_AGENT', '') if request else '',
            metadata=metadata or {}
        )
        return log
    
    @staticmethod
    def login_with_password(email, password, request=None):
        """Handle password-based login"""
        try:
            user = User.objects.select_related('tenant').get(email=email)
        except User.DoesNotExist:
            if request:
                AuthService.create_audit_log(
                    'user_login_failed',
                    description=f'Login attempt for non-existent email: {email}',
                    request=request
                )
            return {
                'success': False,
                'message': 'Invalid email or password'
            }
        
        # Check if account is locked
        if user.is_account_locked():
            minutes_left = int((user.account_locked_until - timezone.now()).total_seconds() / 60)
            return {
                'success': False,
                'message': f'Account locked due to multiple failed attempts. Try again in {minutes_left} minutes.',
                'locked': True
            }
        
        # Update last login attempt
        user.last_login_attempt = timezone.now()
        
        # Authenticate user
        authenticated_user = authenticate(username=email, password=password)
        
        if authenticated_user is None:
            # Increment failed attempts
            user.failed_login_attempts += 1
            
            # Lock account if max attempts reached
            if user.failed_login_attempts >= AuthService.MAX_LOGIN_ATTEMPTS:
                user.account_locked_until = timezone.now() + AuthService.LOCKOUT_DURATION
                user.save()
                
                if request:
                    AuthService.create_audit_log(
                        'user_login_failed',
                        user=user,
                        description=f'Account locked after {AuthService.MAX_LOGIN_ATTEMPTS} failed attempts',
                        request=request
                    )
                
                return {
                    'success': False,
                    'message': f'Account locked after {AuthService.MAX_LOGIN_ATTEMPTS} failed attempts. Try again in 30 minutes.',
                    'locked': True
                }
            
            user.save()
            
            if request:
                AuthService.create_audit_log(
                    'user_login_failed',
                    user=user,
                    description='Invalid password',
                    request=request
                )
            
            attempts_left = AuthService.MAX_LOGIN_ATTEMPTS - user.failed_login_attempts
            return {
                'success': False,
                'message': f'Invalid email or password. {attempts_left} attempts remaining.'
            }
        
        # Check if user is active
        if not user.is_active:
            return {
                'success': False,
                'message': 'Your account has been deactivated. Contact support.'
            }
        
        # Check if tenant is active
        if user.tenant and user.tenant.status != 'active':
            return {
                'success': False,
                'message': 'Your organization account is inactive. Contact support.'
            }
        
        # Check if email is verified
        if not user.email_verified and user.role != 'super_admin':
            return {
                'success': False,
                'message': 'Please verify your email address before logging in.',
                'requires_verification': True
            }
        
        # Successful login - reset failed attempts
        user.failed_login_attempts = 0
        user.account_locked_until = None
        user.last_login = timezone.now()
        user.save()
        
        # Create audit log
        if request:
            AuthService.create_audit_log(
                'user_login',
                user=user,
                description=f'Successful login via password',
                request=request
            )
        
        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        
        return {
            'success': True,
            'user': AuthService._serialize_user(user),
            'tokens': {
                'access': str(refresh.access_token),
                'refresh': str(refresh),
            }
        }
    
    @staticmethod
    def send_otp(email, request=None):
        """Send OTP to user's email"""
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return {
                'success': False,
                'message': 'Email not registered'
            }
        
        if not user.is_active:
            return {
                'success': False,
                'message': 'Your account has been deactivated'
            }
        
        # Generate OTP
        otp_code = user.generate_otp()
        
        # Send email
        try:
            send_mail(
                'Your Login Code',
                f'Your login code is: {otp_code}\n\nThis code will expire in 10 minutes.',
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=False,
            )
            
            if request:
                AuthService.create_audit_log(
                    'user_login',
                    user=user,
                    description='OTP sent to email',
                    request=request
                )
            
            return {
                'success': True,
                'message': 'OTP sent to your email',
                'expires_in': 600  # 10 minutes
            }
        except Exception as e:
            return {
                'success': False,
                'message': f'Failed to send OTP: {str(e)}'
            }
    
    @staticmethod
    def verify_otp(email, otp_code, request=None):
        """Verify OTP and login user"""
        try:
            user = User.objects.select_related('tenant').get(email=email)
        except User.DoesNotExist:
            return {
                'success': False,
                'message': 'Invalid email or OTP'
            }
        
        if not user.verify_otp(otp_code):
            if request:
                AuthService.create_audit_log(
                    'user_login_failed',
                    user=user,
                    description='Invalid OTP code',
                    request=request
                )
            return {
                'success': False,
                'message': 'Invalid or expired OTP'
            }
        
        # Check if user/tenant is active
        if not user.is_active:
            return {
                'success': False,
                'message': 'Your account has been deactivated'
            }
        
        if user.tenant and user.tenant.status != 'active':
            return {
                'success': False,
                'message': 'Your organization account is inactive'
            }
        
        # Update login info
        user.last_login = timezone.now()
        user.save()
        
        # Create audit log
        if request:
            AuthService.create_audit_log(
                'user_login',
                user=user,
                description='Successful login via OTP',
                request=request
            )
        
        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        
        return {
            'success': True,
            'user': AuthService._serialize_user(user),
            'tokens': {
                'access': str(refresh.access_token),
                'refresh': str(refresh),
            }
        }
    
    @staticmethod
    def signup(data, request=None):
        """Handle user signup and tenant creation"""
        try:
            # Check if email already exists
            if User.objects.filter(email=data['email']).exists():
                return {
                    'success': False,
                    'message': 'Email already registered'
                }
            
            # Create tenant
            tenant = Tenant.objects.create(
                name=data['company_name'],
                slug=data['company_name'].lower().replace(' ', '-'),
                plan='free',
                has_ai_access=False,
                max_ai_queries_per_month=0,
                max_users=5,
                current_users=1
            )
            
            # Generate email verification token
            verification_token = secrets.token_urlsafe(32)
            
            # Create user as tenant admin
            user = User.objects.create_user(
                email=data['email'],
                full_name=data['full_name'],
                password=data['password'],
                role='tenant_admin',
                tenant=tenant,
                email_verification_token=verification_token
            )
            
            # Send verification email
            verification_url = f"{settings.FRONTEND_URL}/verify-email/{verification_token}"
            send_mail(
                'Verify Your Email',
                f'Welcome to AI Knowledge Platform!\n\nPlease verify your email by clicking: {verification_url}',
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=True,
            )
            
            # Create audit log
            if request:
                AuthService.create_audit_log(
                    'user_created',
                    user=user,
                    description=f'New user registered: {user.email}',
                    request=request
                )
                AuthService.create_audit_log(
                    'tenant_created',
                    tenant=tenant,
                    description=f'New tenant created: {tenant.name}',
                    request=request
                )
            
            return {
                'success': True,
                'message': 'Account created successfully! Please check your email to verify your account.',
                'user_id': str(user.id),
                'requires_verification': True
            }
        
        except Exception as e:
            return {
                'success': False,
                'message': f'Failed to create account: {str(e)}'
            }
    
    @staticmethod
    def verify_email(token):
        """Verify user email with token"""
        try:
            user = User.objects.get(email_verification_token=token)
            user.email_verified = True
            user.email_verification_token = None
            user.save()
            
            return {
                'success': True,
                'message': 'Email verified successfully! You can now log in.'
            }
        except User.DoesNotExist:
            return {
                'success': False,
                'message': 'Invalid or expired verification token'
            }
    
    @staticmethod
    def request_password_reset(email, request=None):
        """Send password reset email"""
        try:
            user = User.objects.get(email=email)
            
            # Generate reset token
            reset_token = secrets.token_urlsafe(32)
            user.password_reset_token = reset_token
            user.password_reset_expires = timezone.now() + timedelta(hours=1)
            user.save()
            
            # Send email
            reset_url = f"{settings.FRONTEND_URL}/reset-password/{reset_token}"
            send_mail(
                'Password Reset Request',
                f'Click here to reset your password: {reset_url}\n\nThis link expires in 1 hour.',
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=False,
            )
            
            if request:
                AuthService.create_audit_log(
                    'password_reset',
                    user=user,
                    description='Password reset requested',
                    request=request
                )
            
            return {
                'success': True,
                'message': 'Password reset link sent to your email'
            }
        except User.DoesNotExist:
            # Don't reveal if email exists
            return {
                'success': True,
                'message': 'If that email exists, a reset link has been sent'
            }
    
    @staticmethod
    def reset_password(token, new_password, request=None):
        """Reset password with token"""
        try:
            user = User.objects.get(
                password_reset_token=token,
                password_reset_expires__gt=timezone.now()
            )
            
            user.set_password(new_password)
            user.password_reset_token = None
            user.password_reset_expires = None
            user.last_password_change = timezone.now()
            user.save()
            
            if request:
                AuthService.create_audit_log(
                    'password_changed',
                    user=user,
                    description='Password reset completed',
                    request=request
                )
            
            return {
                'success': True,
                'message': 'Password reset successfully'
            }
        except User.DoesNotExist:
            return {
                'success': False,
                'message': 'Invalid or expired reset token'
            }
    
    @staticmethod
    def _serialize_user(user):
        """Serialize user data for response"""
        return {
            'id': str(user.id),
            'email': user.email,
            'full_name': user.full_name,
            'role': user.role,
            'role_display': user.get_role_display(),
            'avatar': user.avatar,
            'department': user.department,
            'job_title': user.job_title,
            'tenant': {
                'id': str(user.tenant.id),
                'name': user.tenant.name,
                'plan': user.tenant.plan,
                'status': user.tenant.status,
                'has_ai_access': user.tenant.has_ai_access,
                'ai_queries_remaining': user.tenant.max_ai_queries_per_month - user.tenant.ai_queries_used_this_month,
            } if user.tenant else None,
            'permissions': user.get_permissions(),
            'can_use_ai': user.can_use_ai(),
            'email_verified': user.email_verified,
        }