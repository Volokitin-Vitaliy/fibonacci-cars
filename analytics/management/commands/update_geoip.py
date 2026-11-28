import gzip
import os
import shutil
import tempfile
import time
from datetime import timedelta

import requests
from django.core.management.base import BaseCommand
from django.utils import timezone

from analytics import tracking

URL = 'https://download.db-ip.com/free/dbip-country-lite-{:%Y-%m}.mmdb.gz'
MAX_AGE_DAYS = 25


class Command(BaseCommand):
    """Download the free DB-IP Lite country database (CC BY 4.0, https://db-ip.com), used to
    show visitors' countries. Run by run_scheduler; refreshed when older than 25 days."""

    help = 'Download or refresh the IP-to-country database for analytics.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true')

    def handle(self, *args, **options):
        path = tracking.geoip_path()
        if (not options['force'] and os.path.exists(path)
                and time.time() - os.path.getmtime(path) < MAX_AGE_DAYS * 86400):
            self.stdout.write('GeoIP database is up to date.')
            return
        now = timezone.now()
        last_month = now.replace(day=1) - timedelta(days=1)
        for month in (now, last_month):  # the new month's file appears in its first days
            response = requests.get(URL.format(month), timeout=120, stream=True)
            if response.status_code == 200:
                break
        else:
            self.stderr.write(f'GeoIP download failed: HTTP {response.status_code}')
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=os.path.dirname(path), delete=False) as tmp:
            with gzip.GzipFile(fileobj=response.raw) as unpacked:
                shutil.copyfileobj(unpacked, tmp)
        os.replace(tmp.name, path)  # readers switch to the new file on their next lookup
        self.stdout.write(f'GeoIP database updated ({os.path.getsize(path) // 1024} KB).')
