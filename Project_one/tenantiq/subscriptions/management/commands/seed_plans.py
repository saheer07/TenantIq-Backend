# subscriptions/management/commands/seed_plans.py
from django.core.management.base import BaseCommand
from subscriptions.models import SubscriptionPlan


class Command(BaseCommand):
    help = 'Seed subscription plans with monthly and yearly pricing'

    def handle(self, *args, **kwargs):
        self.stdout.write('🌱 Seeding subscription plans...')
        
        plans_data = [
            {
                'name': 'Starter',
                'description': 'Perfect for small teams getting started',
                'plan_type': 'starter',
                'monthly_price': 2999.00,  # ₹2,999/month
                'yearly_price': 29990.00,  # ₹29,990/year (Save 16%)
                'ai_enabled': True,
                'max_users': 10,
                'max_documents': 100,
                'max_ai_queries': 1000,
                'features': {
                    'Email support': True,
                    '5GB storage': True,
                    'Standard analytics': True,
                    'Basic integrations': True,
                },
                'is_active': True,
                'recommended': False,
            },
            {
                'name': 'Professional',
                'description': 'For growing teams that need more power',
                'plan_type': 'professional',
                'monthly_price': 7999.00,  # ₹7,999/month
                'yearly_price': 79990.00,  # ₹79,990/year (Save 16%)
                'ai_enabled': True,
                'max_users': 50,
                'max_documents': 1000,
                'max_ai_queries': 10000,
                'features': {
                    'Priority support': True,
                    '50GB storage': True,
                    'API access': True,
                    'Advanced analytics': True,
                    'All standard integrations': True,
                },
                'is_active': True,
                'recommended': True,
            },
            {
                'name': 'Enterprise',
                'description': 'For large organizations with custom needs',
                'plan_type': 'enterprise',
                'monthly_price': 19999.00,  # ₹19,999/month
                'yearly_price': 199990.00,  # ₹1,99,990/year (Save 16%)
                'ai_enabled': True,
                'max_users': 9999,
                'max_documents': 9999,
                'max_ai_queries': 100000,
                'features': {
                    '24/7 dedicated support': True,
                    'Unlimited storage': True,
                    'Full API access': True,
                    'Enterprise analytics': True,
                    'All integrations + Custom': True,
                    'SSO integration': True,
                    '99.9% Uptime SLA': True,
                    'White label solution': True,
                    'Dedicated account manager': True,
                },
                'is_active': True,
                'recommended': False,
            },
        ]
        
        created_count = 0
        updated_count = 0
        
        for plan_data in plans_data:
            plan, created = SubscriptionPlan.objects.update_or_create(
                name=plan_data['name'],
                defaults=plan_data
            )
            
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f'✅ Created: {plan.name} - ₹{plan.monthly_price}/mo, ₹{plan.yearly_price}/yr'
                    )
                )
            else:
                updated_count += 1
                self.stdout.write(
                    self.style.WARNING(
                        f'⚠️  Updated: {plan.name} - ₹{plan.monthly_price}/mo, ₹{plan.yearly_price}/yr'
                    )
                )
        
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('═' * 60))
        self.stdout.write(self.style.SUCCESS(' 🎉 Seeding Complete!'))
        self.stdout.write(self.style.SUCCESS(f'    Created: {created_count} plans'))
        self.stdout.write(self.style.SUCCESS(f'    Updated: {updated_count} plans'))
        self.stdout.write(self.style.SUCCESS('═' * 60))