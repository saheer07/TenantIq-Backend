from django.utils.timezone import now, timedelta
from .models import Subscription

def activate_subscription(company, plan):
    end_date = now() + timedelta(days=plan.duration_days)

    subscription, _ = Subscription.objects.update_or_create(
        company=company,
        defaults={
            "plan": plan,
            "end_date": end_date,
            "is_active": True
        }
    )

    company.is_ai_enabled = plan.ai_enabled
    company.save()

    return subscription
