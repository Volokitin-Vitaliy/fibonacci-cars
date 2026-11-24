from django.core.management.base import BaseCommand

from cars.services import expire_listings


class Command(BaseCommand):
    help = 'Deactivate user listings whose month is over.'

    def handle(self, *args, **options):
        self.stdout.write(f'Expired listings: {expire_listings()}')
