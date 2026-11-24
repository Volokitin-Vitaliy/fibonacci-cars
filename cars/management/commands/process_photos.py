from django.core.management.base import BaseCommand

from cars import images
from cars.models import CarPhoto


class Command(BaseCommand):
    help = ('Make the small WebP copies for photos that do not have them yet. With '
            '--clean-uploads, also re-save photos uploaded by sellers without metadata (GPS).')

    def add_arguments(self, parser):
        parser.add_argument('--clean-uploads', action='store_true',
                            help='Re-save seller photos: upright, max 2000 px, no EXIF/GPS.')
        parser.add_argument('--all', action='store_true', help='Remake copies for every photo.')

    def handle(self, *args, **options):
        if options['clean_uploads']:
            cleaned = 0
            for photo in CarPhoto.objects.filter(source_url='').iterator():
                old_name, old_widths = photo.image.name, list(photo.variants or [])
                try:
                    with photo.image.open('rb') as f:
                        content = images.clean_upload(f)
                except (OSError, ValueError) as exc:
                    self.stderr.write(f'photo {photo.pk}: {exc}')
                    continue
                photo.image.save(content.name, content, save=False)
                photo.variants = []
                photo.save(update_fields=['image', 'variants'])
                images.delete_files(old_name, old_widths)
                images.make_variants(photo)
                cleaned += 1
            self.stdout.write(f'Cleaned {cleaned} seller photos.')
        photos = CarPhoto.objects.all() if options['all'] else CarPhoto.objects.filter(variants=[])
        done = 0
        for photo in photos.iterator():
            if images.make_variants(photo):
                done += 1
                if done % 200 == 0:
                    self.stdout.write(f'  {done} photos...')
        self.stdout.write(f'Made copies for {done} photos.')
