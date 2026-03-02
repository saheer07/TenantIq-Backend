# accounts/management/commands/make_tenant_admin.py
from django.core.management.base import BaseCommand
from accounts.models import User, Tenant


class Command(BaseCommand):
    help = 'Make a user a tenant admin'

    def add_arguments(self, parser):
        parser.add_argument('email', type=str, help='User email address')

    def handle(self, *args, **kwargs):
        email = kwargs['email']
        
        try:
            user = User.objects.get(email=email)
            
            # Check if user has a tenant
            if not user.tenant:
                self.stdout.write(self.style.WARNING('⚠️  User has no tenant assigned'))
                
                # Try to get or create a tenant
                tenant = Tenant.objects.first()
                if not tenant:
                    self.stdout.write(self.style.ERROR('❌ No tenants exist in the database'))
                    self.stdout.write('Please create a tenant first or provide tenant details')
                    return
                
                user.tenant = tenant
                self.stdout.write(self.style.SUCCESS(f'✅ Assigned tenant: {tenant.name}'))
            
            # Update user role to TENANT_ADMIN
            old_role = user.role
            user.role = 'TENANT_ADMIN'
            user.save()
            
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('=' * 60))
            self.stdout.write(self.style.SUCCESS('  ✅ USER UPDATED SUCCESSFULLY'))
            self.stdout.write(self.style.SUCCESS('=' * 60))
            self.stdout.write(f'  Email: {user.email}')
            self.stdout.write(f'  Old Role: {old_role}')
            self.stdout.write(f'  New Role: {user.role}')
            self.stdout.write(f'  Tenant: {user.tenant.name if user.tenant else "None"}')
            self.stdout.write(self.style.SUCCESS('=' * 60))
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('🎉 User can now subscribe to plans!'))
            
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'❌ User with email "{email}" not found'))
            self.stdout.write('')
            self.stdout.write('Available users:')
            for u in User.objects.all()[:5]:
                self.stdout.write(f'  - {u.email} (Role: {u.role})')