from .models import Subscription
from django.utils import timezone

def get_active_subscription(tenant):
    return Subscription.objects.filter(
        tenant=tenant,
        status='active',
        end_date__gte=timezone.now().date()
    ).first()
