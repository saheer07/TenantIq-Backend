from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import UserProfile

User = get_user_model()


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['phone', 'department']


class UserSerializer(serializers.ModelSerializer):
    """Serializer for reading user data"""
    phone = serializers.CharField(source='profile.phone', required=False, allow_blank=True, read_only=True)
    department = serializers.CharField(source='profile.department', required=False, allow_blank=True, read_only=True)
    joined_at = serializers.DateTimeField(source='date_joined', read_only=True)
    # Use SerializerMethodField to get the name safely
    name = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = [
            'id', 'name', 'email', 'role', 'is_verified', 
            'is_active', 'phone', 'department', 'joined_at'
        ]
        read_only_fields = ['id', 'email', 'is_verified', 'joined_at']
    
    def get_name(self, obj):
        """Get user's display name"""
        # Try different name field combinations
        if hasattr(obj, 'name') and obj.name:
            return obj.name
        elif hasattr(obj, 'first_name') and hasattr(obj, 'last_name'):
            full_name = f"{obj.first_name} {obj.last_name}".strip()
            return full_name if full_name else obj.email.split('@')[0]
        elif hasattr(obj, 'username'):
            return obj.username
        else:
            return obj.email.split('@')[0]


class CreateUserSerializer(serializers.Serializer):
    """Serializer for creating new users"""
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    name = serializers.CharField(required=False, allow_blank=True)
    role = serializers.ChoiceField(
        choices=['TENANT_USER', 'TENANT_ADMIN'],
        default='TENANT_USER'
    )
    phone = serializers.CharField(required=False, allow_blank=True)
    department = serializers.CharField(required=False, allow_blank=True)
    
    def validate_email(self, value):
        """Check if email already exists"""
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("User with this email already exists")
        return value
    
    def validate_role(self, value):
        """Validate role"""
        allowed_roles = ['TENANT_USER', 'TENANT_ADMIN']
        if value not in allowed_roles:
            raise serializers.ValidationError(f"Role must be one of: {', '.join(allowed_roles)}")
        return value
    
    def create(self, validated_data):
        """Create user with profile"""
        phone = validated_data.pop('phone', '')
        department = validated_data.pop('department', '')
        name = validated_data.pop('name', '')
        email = validated_data['email']
        password = validated_data['password']
        role = validated_data.get('role', 'TENANT_USER')
        
        # Get tenant from request context
        request = self.context.get('request')
        tenant = request.user.tenant if hasattr(request.user, 'tenant') else None
        
        # Determine what fields the User model has and create accordingly
        user_data = {
            'email': email,
            'password': password,
            'role': role,
            'is_verified': True,  # Auto-verify since admin is creating
            'is_active': True
        }
        
        # Add tenant if the model has it
        if tenant:
            user_data['tenant'] = tenant
        
        # Handle name field based on what the User model has
        if hasattr(User, 'name'):
            # Model has a 'name' field
            user_data['name'] = name or email.split('@')[0]
        elif hasattr(User, 'first_name') and hasattr(User, 'last_name'):
            # Model has first_name and last_name
            if name:
                name_parts = name.split(' ', 1)
                user_data['first_name'] = name_parts[0]
                user_data['last_name'] = name_parts[1] if len(name_parts) > 1 else ''
            else:
                user_data['first_name'] = email.split('@')[0]
                user_data['last_name'] = ''
        elif hasattr(User, 'username'):
            # Model has username
            user_data['username'] = email.split('@')[0] if not name else name.lower().replace(' ', '_')
        
        # Create user using the manager's create_user method
        user = User.objects.create_user(**user_data)
        
        # Create or update profile
        UserProfile.objects.update_or_create(
            user=user,
            defaults={
                'phone': phone,
                'department': department
            }
        )
        
        return user


class UpdateUserSerializer(serializers.Serializer):
    """Serializer for updating existing users"""
    name = serializers.CharField(required=False, allow_blank=True)
    role = serializers.ChoiceField(
        choices=['TENANT_USER', 'TENANT_ADMIN'],
        required=False
    )
    phone = serializers.CharField(required=False, allow_blank=True)
    department = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
    
    def update(self, instance, validated_data):
        """Update user and profile"""
        # Extract profile fields
        phone = validated_data.pop('phone', None)
        department = validated_data.pop('department', None)
        name = validated_data.pop('name', None)
        
        # Update user fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        # Handle name field based on what the User model has
        if name is not None:
            if hasattr(instance, 'name'):
                instance.name = name
            elif hasattr(instance, 'first_name') and hasattr(instance, 'last_name'):
                name_parts = name.split(' ', 1)
                instance.first_name = name_parts[0]
                instance.last_name = name_parts[1] if len(name_parts) > 1 else ''
            elif hasattr(instance, 'username'):
                instance.username = name.lower().replace(' ', '_')
        
        instance.save()
        
        # Update profile if phone or department provided
        if phone is not None or department is not None:
            profile, created = UserProfile.objects.get_or_create(user=instance)
            if phone is not None:
                profile.phone = phone
            if department is not None:
                profile.department = department
            profile.save()
        
        return instance