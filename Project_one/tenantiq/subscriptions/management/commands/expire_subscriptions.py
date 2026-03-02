from django.core.management.base import BaseCommand
from django.utils.timezone import now
from subscriptions.models import Subscription

class Command(BaseCommand):
    help = "Expire subscriptions automatically"

    def handle(self, *args, **kwargs):
        expired = Subscription.objects.filter(end_date__lt=now(), is_active=True)

        for sub in expired:
            sub.is_active = False
            sub.company.is_ai_enabled = False
            sub.company.save()
            sub.save()

        self.stdout.write("Expired subscriptions processed")
