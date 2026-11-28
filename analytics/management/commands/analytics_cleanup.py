from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from analytics.models import Event, PageView, Presence


class Command(BaseCommand):
    help = 'Delete analytics older than ANALYTICS_RETENTION_DAYS and stale presence rows.'

    def handle(self, *args, **options):
        now = timezone.now()
        border = now - timedelta(days=settings.ANALYTICS_RETENTION_DAYS)
        views = PageView.objects.filter(created_at__lt=border).delete()[0]
        events = Event.objects.filter(created_at__lt=border).delete()[0]
        Presence.objects.filter(last_seen__lt=now - timedelta(days=1)).delete()
        self.stdout.write(f'Analytics: deleted {views} old page views and {events} events.')
