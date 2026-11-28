import time
import traceback
from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from cars.models import ImportRun


DAILY = ('expire_listings', 'send_expiry_reminders', 'import_hollmann', 'translate_listings',
         'update_geoip', 'analytics_cleanup', 'process_photos', 'clearsessions')
FREQUENT_SECONDS = 300
RETRY_AFTER = timedelta(hours=2)


class Command(BaseCommand):
    """Run the daily jobs forever: import from hollmann.international and
    expire finished listings. Used by the `scheduler` service in
    docker-compose; a system cron calling the two commands works too."""

    help = 'Run daily jobs (vehicle import, listing expiry) in a loop.'

    def add_arguments(self, parser):
        parser.add_argument('--interval-hours', type=float, default=24)

    def handle(self, *args, **options):
        interval = timedelta(hours=options['interval_hours'])
        self.mark_interrupted()
        while True:
            # Every few minutes, first: the next post in the Telegram channel (one an hour, not at night).
            self.run('telegram_channel')
            if self.daily_due(interval):
                self.stdout.write(f'[{timezone.now():%Y-%m-%d %H:%M}] running daily jobs')
                for command in DAILY:
                    self.run(command)
            time.sleep(FREQUENT_SECONDS)

    def mark_interrupted(self):
        """An import still 'running' when the scheduler starts was cut off by a restart
        (e.g. a site update): say so instead of leaving it as an unexplained error."""
        ImportRun.objects.filter(finished_at__isnull=True).update(
            finished_at=timezone.now(), ok=False, error=ImportRun.INTERRUPTED)

    def daily_due(self, interval):
        """Daily jobs run a day after the last import, not on every restart: updating the site
        no longer starts (and then cuts off) a new import each time. A failed import is
        retried after RETRY_AFTER; an interrupted one at once."""
        last = ImportRun.objects.exclude(error=ImportRun.INTERRUPTED).first()
        if last is None:
            return True
        wait = interval if last.ok else RETRY_AFTER
        return timezone.now() - last.started_at >= wait

    def run(self, command):
        try:
            call_command(command, stdout=self.stdout)
        except Exception:
            self.stderr.write(traceback.format_exc())
