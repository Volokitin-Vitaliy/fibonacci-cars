from django.core.management.base import BaseCommand

from cars import translation
from cars.models import Car


class Command(BaseCommand):
    """Translate descriptions that are new or changed (imported cars after the import,
    and any seller listing whose instant translation failed). Run daily by run_scheduler;
    the first run after setting DEEPL_API_KEY translates the whole catalog."""

    help = 'Translate new or changed listing descriptions into the other site language.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=0, help='Translate at most this many cars.')

    def handle(self, *args, **options):
        if not translation.enabled():
            self.stdout.write('DEEPL_API_KEY is not set: nothing translated.')
            return
        done = failed = 0
        cars = Car.objects.filter(is_published=True).order_by('-created_at')
        for car in cars:
            if options['limit'] and done >= options['limit']:
                break
            if not translation.needs_translation(car):
                continue
            try:
                if translation.translate_car(car):
                    done += 1
            except translation.TranslationError as exc:
                failed += 1
                self.stderr.write(f'Car {car.pk}: {exc}')
                if 'HTTP 456' in str(exc) or 'HTTP 403' in str(exc):
                    break  # quota used up or a wrong key: stop until the next run
        self.stdout.write(f'Translated {done} descriptions, failed {failed}.')
