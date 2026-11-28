import time
import traceback

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone


DAILY = ('expire_listings', 'send_expiry_reminders', 'import_hollmann', 'translate_listings',
         'update_geoip', 'analytics_cleanup', 'process_photos', 'clearsessions')
FREQUENT_SECONDS = 300


class Command(BaseCommand):
    """Run the daily jobs forever: import from hollmann.international and
    expire finished listings. Used by the `scheduler` service in
    docker-compose; a system cron calling the two commands works too."""

    help = 'Run daily jobs (vehicle import, listing expiry) in a loop.'

    def add_arguments(self, parser):
        parser.add_argument('--interval-hours', type=float, default=24)

    def handle(self, *args, **options):
        interval = options['interval_hours'] * 3600
        last_daily = None
        while True:
            if last_daily is None or time.monotonic() - last_daily >= interval:
                last_daily = time.monotonic()
                self.stdout.write(f'[{timezone.now():%Y-%m-%d %H:%M}] running daily jobs')
                for command in DAILY:
                    self.run(command)
            # Every few minutes: the next post in the Telegram channel (one an hour, not at night).
            self.run('telegram_channel')
            time.sleep(FREQUENT_SECONDS)

    def run(self, command):
        try:
            call_command(command, stdout=self.stdout)
        except Exception:
            self.stderr.write(traceback.format_exc())
