from django.core.management.base import BaseCommand

from cars.importers.hollmann import HollmannImporter


class Command(BaseCommand):
    help = 'Import the vehicle list from hollmann.international (run once a day).'

    def add_arguments(self, parser):
        parser.add_argument('--no-details', action='store_true',
                            help='Only read listing pages, skip each vehicle page.')
        parser.add_argument('--delay', type=float, default=None,
                            help='Seconds to wait between requests.')

    def handle(self, *args, **options):
        importer = HollmannImporter(fetch_details=not options['no_details'],
                                    delay=options['delay'], stdout=self.stdout)
        importer.run()
