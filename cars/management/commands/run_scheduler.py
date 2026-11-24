import time
import traceback

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    """Run the daily jobs forever: import from hollmann.international and
    expire finished listings. Used by the `scheduler` service in
    docker-compose; a system cron calling the two commands works too."""

    help = 'Run daily jobs (vehicle import, listing expiry) in a loop.'

    def add_arguments(self, parser):
        parser.add_argument('--interval-hours', type=float, default=24)

    def handle(self, *args, **options):
        interval = options['interval_hours'] * 3600
        while True:
            self.stdout.write(f'[{timezone.now():%Y-%m-%d %H:%M}] running daily jobs')
            for command in ('expire_listings', 'send_expiry_reminders', 'import_hollmann', 'process_photos',
                            'clearsessions'):
                try:
                    call_command(command, stdout=self.stdout)
                except Exception:
                    self.stderr.write(traceback.format_exc())
            time.sleep(interval)
