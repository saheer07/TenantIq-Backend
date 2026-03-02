from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.conf import settings
from django.db.models import Q

from .serializers import UserSerializer, CreateUserSerializer, UpdateUserSerializer
from .models import UserProfile

User = get_user_model()


class UserListView(APIView):
    """List all users in the tenant"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        
        # Normalize role to handle both lowercase and uppercase
        user_role = getattr(user, 'role', '').upper() if hasattr(user, 'role') else None
        
        print(f"🔍 UserListView - User: {user.email}, Role: {user_role}")
        
        # Check permissions
        if user_role not in ['SUPER_ADMIN', 'TENANT_ADMIN']:
            return Response(
                {
                    'error': 'Permission denied',
                    'detail': f'Your role ({user_role}) does not have permission to view users. Required: SUPER_ADMIN or TENANT_ADMIN'
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get users based on role
        if user_role == 'SUPER_ADMIN':
            users = User.objects.all()
        else:
            if not hasattr(user, 'tenant') or user.tenant is None:
                return Response(
                    {'error': 'No tenant associated with your account'},
                    status=status.HTTP_403_FORBIDDEN
                )
            users = User.objects.filter(tenant=user.tenant)
        
        # Apply search filter if provided
        search = request.query_params.get('search', '')
        if search:
            users = users.filter(
                Q(name__icontains=search) |
                Q(email__icontains=search) |
                Q(profile__department__icontains=search)
            )
        
        print(f"✅ Returning {users.count()} users")
        serializer = UserSerializer(users, many=True)
        return Response(serializer.data)


class CreateUserView(APIView):
    """Create a new user directly (no invitation)"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        user = request.user
        
        # Normalize role
        user_role = getattr(user, 'role', '').upper() if hasattr(user, 'role') else None
        
        print(f"🔍 CreateUserView - User: {user.email}, Role: {user_role}")
        print(f"📝 Request data: {request.data}")
        
        # Check permissions
        if user_role not in ['SUPER_ADMIN', 'TENANT_ADMIN']:
            return Response(
                {
                    'error': 'Permission denied. Only admins can create users.',
                    'detail': f'Your role ({user_role}) does not have permission to create users.'
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if tenant exists
        if user_role == 'TENANT_ADMIN':
            if not hasattr(user, 'tenant') or user.tenant is None:
                return Response(
                    {'error': 'No tenant associated with your account'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        # Check subscription limits if applicable
        if user_role == 'TENANT_ADMIN' and hasattr(user, 'tenant') and user.tenant:
            try:
                from subscriptions.models import Subscription
                subscription = Subscription.objects.filter(
                    tenant=user.tenant,
                    status='active'
                ).first()
                
                if subscription:
                    current_users = User.objects.filter(tenant=user.tenant).count()
                    if current_users >= subscription.plan.max_users:
                        return Response(
                            {'error': f'User limit reached ({subscription.plan.max_users} users). Please upgrade your plan.'},
                            status=status.HTTP_403_FORBIDDEN
                        )
            except ImportError:
                print("⚠️ Subscription module not found, skipping limit check")
                pass
            except Exception as e:
                print(f"⚠️ Subscription check failed: {e}")
                pass
        
        # Create user
        serializer = CreateUserSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            new_user = serializer.save()
            
            print(f"✅ User created: {new_user.email}")
            
            # Send welcome email with login credentials
            try:
                tenant_name = user.tenant.name if hasattr(user, 'tenant') and user.tenant else "the Platform"
                send_mail(
                    subject=f'Welcome to {tenant_name}',
                    message=f"""
Hello {new_user.name},

Your account has been created by {user.name}.

Login Details:
Email: {new_user.email}
Password: [The password you set]

You can now login at: {settings.FRONTEND_URL}/login

Role: {new_user.role.replace('_', ' ')}

If you have any questions, please contact your administrator.

Best regards,
{tenant_name}
                    """,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[new_user.email],
                    fail_silently=True,
                )
            except Exception as e:
                print(f"Failed to send welcome email: {e}")
            
            # Log the action
            try:
                from accounts.models import AuditLog
                AuditLog.objects.create(
                    user=user,
                    action='USER_CREATED',
                    tenant=user.tenant if hasattr(user, 'tenant') else None,
                    details=f'Created user: {new_user.email} with role {new_user.role}',
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')
                )
            except Exception as e:
                print(f"Failed to create audit log: {e}")
            
            return Response({
                'success': True,
                'message': f'User {new_user.email} created successfully',
                'user': UserSerializer(new_user).data
            }, status=status.HTTP_201_CREATED)
        
        print(f"❌ Validation errors: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserDetailView(APIView):
    """Get, update, or delete a specific user"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, pk):
        try:
            user_obj = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Normalize role
        user_role = getattr(request.user, 'role', '').upper() if hasattr(request.user, 'role') else None
        
        # Check permissions
        if user_role == 'SUPER_ADMIN':
            pass
        elif user_role == 'TENANT_ADMIN' and hasattr(user_obj, 'tenant') and hasattr(request.user, 'tenant') and user_obj.tenant == request.user.tenant:
            pass
        else:
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = UserSerializer(user_obj)
        return Response(serializer.data)
    
    def put(self, request, pk):
        try:
            user_obj = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Normalize role
        user_role = getattr(request.user, 'role', '').upper() if hasattr(request.user, 'role') else None
        
        # Check permissions
        if user_role not in ['SUPER_ADMIN', 'TENANT_ADMIN']:
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if user_role == 'TENANT_ADMIN':
            if not (hasattr(user_obj, 'tenant') and hasattr(request.user, 'tenant') and user_obj.tenant == request.user.tenant):
                return Response(
                    {'error': 'Permission denied'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        serializer = UpdateUserSerializer(user_obj, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            
            # Log the action
            try:
                from accounts.models import AuditLog
                AuditLog.objects.create(
                    user=request.user,
                    action='USER_UPDATED',
                    tenant=request.user.tenant if hasattr(request.user, 'tenant') else None,
                    details=f'Updated user: {user_obj.email}',
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')
                )
            except Exception as e:
                print(f"Failed to create audit log: {e}")
            
            return Response({
                'success': True,
                'message': 'User updated successfully',
                'user': UserSerializer(user_obj).data
            })
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def delete(self, request, pk):
        try:
            user_obj = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Normalize role
        user_role = getattr(request.user, 'role', '').upper() if hasattr(request.user, 'role') else None
        
        # Check permissions
        if user_role not in ['SUPER_ADMIN', 'TENANT_ADMIN']:
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if user_role == 'TENANT_ADMIN':
            if not (hasattr(user_obj, 'tenant') and hasattr(request.user, 'tenant') and user_obj.tenant == request.user.tenant):
                return Response(
                    {'error': 'Permission denied'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        # Prevent self-deletion
        if user_obj == request.user:
            return Response(
                {'error': 'You cannot delete your own account'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        email = user_obj.email
        user_obj.delete()
        
        # Log the action
        try:
            from accounts.models import AuditLog
            AuditLog.objects.create(
                user=request.user,
                action='USER_DELETED',
                tenant=request.user.tenant if hasattr(request.user, 'tenant') else None,
                details=f'Deleted user: {email}',
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )
        except Exception as e:
            print(f"Failed to create audit log: {e}")
        
        return Response({
            'success': True,
            'message': f'User {email} deleted successfully'
        })


class ToggleUserActiveView(APIView):
    """Toggle user active status"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request, pk):
        try:
            user_obj = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Normalize role
        user_role = getattr(request.user, 'role', '').upper() if hasattr(request.user, 'role') else None
        
        # Check permissions
        if user_role not in ['SUPER_ADMIN', 'TENANT_ADMIN']:
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if user_role == 'TENANT_ADMIN':
            if not (hasattr(user_obj, 'tenant') and hasattr(request.user, 'tenant') and user_obj.tenant == request.user.tenant):
                return Response(
                    {'error': 'Permission denied'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        # Toggle status
        user_obj.is_active = not user_obj.is_active
        user_obj.save()
        
        # Log the action
        try:
            from accounts.models import AuditLog
            AuditLog.objects.create(
                user=request.user,
                action='USER_STATUS_CHANGED',
                tenant=request.user.tenant if hasattr(request.user, 'tenant') else None,
                details=f'{"Activated" if user_obj.is_active else "Deactivated"} user: {user_obj.email}',
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )
        except Exception as e:
            print(f"Failed to create audit log: {e}")
        
        return Response({
            'success': True,
            'message': f'User {"activated" if user_obj.is_active else "deactivated"} successfully',
            'is_active': user_obj.is_active
        })