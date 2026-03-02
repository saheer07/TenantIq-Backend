from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    """
    Custom manager for the User model which uses email as the unique identifier
    instead of a username.
    """

    def _create_user(self, email, password, full_name, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set.")
        if not full_name:
            raise ValueError("The Full Name field must be set.")

        email = self.normalize_email(email)
        
        # ✅ ADDED: Normalize role to uppercase
        if 'role' in extra_fields and extra_fields['role']:
            extra_fields['role'] = extra_fields['role'].upper()
        
        user = self.model(email=email, full_name=full_name, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, full_name="", **extra_fields):
        """
        Create and return a regular user.
        
        Supports both 'name' and 'full_name' parameters for compatibility.
        """
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        
        # ✅ ADDED: Handle 'name' parameter (convert to full_name)
        if 'name' in extra_fields:
            if not full_name:  # Only use 'name' if full_name is empty
                full_name = extra_fields.pop('name')
            else:
                extra_fields.pop('name')  # Remove 'name' to avoid conflicts
        
        # ✅ ADDED: Default full_name to email prefix if empty
        if not full_name:
            full_name = email.split('@')[0]
        
        return self._create_user(email, password, full_name, **extra_fields)

    def create_superuser(self, email, password=None, full_name="", **extra_fields):
        """
        Create and return a superuser with admin privileges.
        """
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_verified", True)
        extra_fields.setdefault("role", "SUPER_ADMIN")  # ✅ FIXED: Uppercase

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        # ✅ ADDED: Handle 'name' parameter
        if 'name' in extra_fields:
            if not full_name:
                full_name = extra_fields.pop('name')
            else:
                extra_fields.pop('name')
        
        if not full_name:
            full_name = email.split('@')[0]

        return self._create_user(email, password, full_name, **extra_fields)

    def create_tenant_admin(self, email, password=None, full_name="", tenant=None, **extra_fields):
        """
        Create and return a tenant admin user.
        """
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("role", "TENANT_ADMIN")  # ✅ FIXED: Uppercase
        extra_fields["tenant"] = tenant
        
        # ✅ ADDED: Handle 'name' parameter
        if 'name' in extra_fields:
            if not full_name:
                full_name = extra_fields.pop('name')
            else:
                extra_fields.pop('name')
        
        if not full_name:
            full_name = email.split('@')[0]
        
        return self._create_user(email, password, full_name, **extra_fields)