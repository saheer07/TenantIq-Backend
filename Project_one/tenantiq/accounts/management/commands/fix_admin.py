# accounts/management/commands/fix_admin.py
from django.core.management.base import BaseCommand
from accounts.models import User, Tenant


class Command(BaseCommand):
    help = 'Fix user admin permissions'

    def handle(self, *args, **kwargs):
        email = 'bluex92@gmail.com'
        
        try:
            user = User.objects.get(email=email)
            
            # Assign tenant if missing
            if not user.tenant:
                tenant = Tenant.objects.first()
                if not tenant:
                    self.stdout.write('Creating default tenant...')
                    tenant = Tenant.objects.create(name='My Company')
                user.tenant = tenant
            
            # Set as admin
            user.role = 'TENANT_ADMIN'
            user.save()
            
            self.stdout.write(self.style.SUCCESS(f'✅ Fixed! {user.email} is now TENANT_ADMIN'))
            
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User not found: {email}'))