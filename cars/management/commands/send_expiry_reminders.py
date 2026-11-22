from django.core.management.base import BaseCommand

from cars.services import send_expiry_reminders


class Command(BaseCommand):
    help = 'Email owners whose listing expires in the next few days.'

    def handle(self, *args, **options):
        self.stdout.write(f'Reminders sent: {send_expiry_reminders()}')
