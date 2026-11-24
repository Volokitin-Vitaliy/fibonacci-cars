"""Daily import of the vehicle list from hollmann.international.

Imported with Hollmann International's permission: make, model, prices,
the specification table, photos (copied and re-compressed), the description
and the dealer contacts. Cars that are no longer listed on their site are
hidden here and their photos are deleted.
"""

import logging
import re
import time
import uuid
from decimal import Decimal, InvalidOperation
from io import BytesIO
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone
from PIL import Image

from cars.models import Car, CarPhoto, ImportRun, Make

ALLOWED_TAGS = {'b', 'strong', 'i', 'em', 'br', 'p', 'ul', 'ol', 'li', 'code', 'hr'}

logger = logging.getLogger(__name__)

USER_AGENT = 'FibonacciCarsBot/1.0 (daily vehicle index)'

PRICE_RE = re.compile(r'([€$])\s*([\d.,]+)')


def parse_price(text):
    """'Gross: €168,980.00' -> (Decimal('168980.00'), 'EUR')."""
    if not text:
        return None, None
    match = PRICE_RE.search(text)
    if not match:
        return None, None
    symbol, number = match.groups()
    try:
        value = Decimal(number.replace(',', ''))
    except InvalidOperation:
        return None, None
    return value, 'USD' if symbol == '$' else 'EUR'


def clean_cell(cell):
    for footnote in cell.select('.footnote'):
        footnote.decompose()
    return ' '.join(cell.get_text(' ', strip=True).split())


def parse_offers(html, base_url):
    """Parse a listing page (/vehicles/, /new/)."""
    soup = BeautifulSoup(html, 'html.parser')
    offers = []
    for card in soup.select('a.offer'):
        href = card.get('href', '')
        match = re.search(r'/vehicle/([^/]+)/?', href)
        if not match:
            continue
        manufacturer = card.select_one('.manufacturer')
        model = card.select_one('.model')
        gross, currency = parse_price(card.select_one('.gross-price') and
                                      card.select_one('.gross-price').get_text())
        net, _ = parse_price(card.select_one('.net-price') and
                             card.select_one('.net-price').get_text())
        offers.append({
            'external_id': unquote(match.group(1)),
            'url': urljoin(base_url, href),
            'make': manufacturer.get_text(strip=True) if manufacturer else '',
            'model': model.get_text(strip=True) if model else '',
            'price': gross if gross is not None else net,
            'price_net': net,
            'currency': currency or 'EUR',
        })
    return offers


def parse_offer_ids(html):
    soup = BeautifulSoup(html, 'html.parser')
    ids = set()
    for card in soup.select('a.offer'):
        match = re.search(r'/vehicle/([^/]+)/?', card.get('href', ''))
        if match:
            ids.add(unquote(match.group(1)))
    return ids


def parse_detail(html):
    """Return the specification table of a vehicle page as [label, value]."""
    soup = BeautifulSoup(html, 'html.parser')
    specs = []
    table = soup.select_one('.details table')
    if not table:
        return specs
    for row in table.select('tr'):
        cells = row.find_all('td')
        if len(cells) < 2:
            continue
        label, value = clean_cell(cells[0]), clean_cell(cells[1])
        if label and value:
            specs.append([label, value])
    return specs


def sanitize_description(element):
    """Keep only simple formatting tags without attributes."""
    if element is None:
        return ''
    for bad in element.find_all(['script', 'style', 'iframe', 'object', 'img', 'form']):
        bad.decompose()
    for tag in element.find_all(True):
        if tag.name in ALLOWED_TAGS:
            tag.attrs = {}
        else:
            tag.unwrap()
    html = element.decode_contents().strip()
    return re.sub(r'(<br/?>\s*){3,}', '<br/><br/>', html)


def parse_contacts(soup):
    contacts = []
    for block in soup.select('.contacts .contact'):
        name = block.select_one('.name')
        if not name:
            continue

        def number(selector):
            link = block.select_one(selector)
            if not link:
                return ''
            for label in link.find_all('div'):
                label.decompose()
            return ' '.join(link.get_text(' ', strip=True).split())

        img = block.select_one('img')
        languages = block.select_one('.languages')
        contacts.append({
            'name': name.get_text(strip=True),
            'languages': languages.get_text(' ', strip=True) if languages else '',
            'phone': number('a.phone'),
            'mobile': number('a.mobilephone'),
            'whatsapp': number('a.whatsapp'),
            'photo_url': img.get('src', '') if img else '',
        })
    return contacts


def parse_vehicle_page(html):
    """Everything we take from a vehicle page."""
    soup = BeautifulSoup(html, 'html.parser')
    photos = []
    for img in soup.select('main section .strip .content img'):
        src = img.get('src')
        if src and src not in photos:
            photos.append(src)
    return {
        'specs': parse_detail(str(soup.select_one('.details') or '')),
        'photos': photos,
        'description_html': sanitize_description(soup.select_one('.description')),
        'contacts': parse_contacts(soup),
    }


def detect_fuel(drive):
    """'Plugin Hybrid (Petrol/Electricity)' -> hybrid, 'Electric Motor' -> electric.
    Hybrids are checked first: their description also mentions electricity."""
    drive = drive.lower()
    if 'hybrid' in drive:
        return Car.Fuel.HYBRID
    if 'electric' in drive:
        return Car.Fuel.ELECTRIC
    if any(word in drive for word in ('lpg', 'cng', 'gas', 'autogas')):
        return Car.Fuel.GAS
    if 'diesel' in drive:
        return Car.Fuel.DIESEL
    if 'petrol' in drive or 'gasoline' in drive or 'combustion' in drive:
        return Car.Fuel.PETROL
    return ''


def specs_to_fields(specs):
    """Extract the short characteristics used for cards and filters."""
    data = dict(specs)
    fields = {}
    mileage = re.sub(r'[^\d]', '', data.get('Mileage', ''))
    if mileage:
        fields['mileage_km'] = int(mileage)
    power = re.sub(r'[^\d]', '', data.get('Power (PS)', ''))
    if power:
        fields['power_hp'] = int(power)
    transmission = data.get('Transmission', '').lower()
    if 'auto' in transmission:
        fields['transmission'] = Car.Transmission.AUTOMATIC
    elif 'manual' in transmission:
        fields['transmission'] = Car.Transmission.MANUAL
    fuel = detect_fuel(data.get('Drive', ''))
    if fuel:
        fields['fuel'] = fuel
    registration = re.search(r'(19|20)\d{2}', data.get('First Registration', ''))
    if registration:
        fields['year'] = int(registration.group(0))
    if data.get('Color'):
        fields['color'] = re.sub(r'\s+\S*\d\S*$', '', data['Color'])
    return fields


class HollmannImporter:
    def __init__(self, base_url=None, delay=None, fetch_details=True, session=None, stdout=None,
                 import_media=None, limit=None, photo_delay=0.2):
        self.base_url = (base_url or settings.HOLLMANN_BASE_URL).rstrip('/') + '/'
        self.delay = settings.HOLLMANN_REQUEST_DELAY if delay is None else delay
        self.fetch_details = fetch_details
        self.import_media = settings.HOLLMANN_IMPORT_MEDIA if import_media is None else import_media
        self.limit = limit
        self.photo_delay = photo_delay
        self.session = session or requests.Session()
        self.session.headers['User-Agent'] = USER_AGENT
        self.stdout = stdout

    def log(self, message):
        logger.info(message)
        if self.stdout:
            self.stdout.write(message)

    def get(self, path):
        response = self.session.get(urljoin(self.base_url, path), timeout=30)
        response.raise_for_status()
        if self.delay:
            time.sleep(self.delay)
        return response.text

    def run(self):
        run = ImportRun.objects.create(source=Car.Source.HOLLMANN)
        try:
            self._run(run)
            run.ok = True
        except Exception as exc:  # keep the error for the admin, then re-raise
            run.error = repr(exc)
            raise
        finally:
            run.finished_at = timezone.now()
            run.save()
        return run

    def download(self, url):
        response = self.session.get(url, timeout=60)
        response.raise_for_status()
        if self.photo_delay:
            time.sleep(self.photo_delay)
        return response.content

    def compress(self, data, max_width):
        image = Image.open(BytesIO(data))
        if image.mode in ('P', 'RGBA', 'LA'):  # transparent portraits: put them on the site's dark background
            image = image.convert('RGBA')
            background = Image.new('RGB', image.size, (17, 17, 17))
            background.paste(image, mask=image.split()[-1])
            image = background
        image = image.convert('RGB')
        if image.width > max_width:
            image = image.resize((max_width, round(image.height * max_width / image.width)), Image.LANCZOS)
        out = BytesIO()
        image.save(out, 'JPEG', quality=settings.HOLLMANN_PHOTO_QUALITY, optimize=True, progressive=True)
        return out.getvalue()

    def sync_photos(self, car, urls):
        """Download new photos, keep the ones we already have, drop removed ones."""
        urls = urls[:settings.HOLLMANN_MAX_PHOTOS]
        existing = {p.source_url: p for p in car.photos.all()}
        for photo in existing.values():
            if photo.source_url not in urls:
                photo.image.delete(save=False)
                photo.delete()
        added = 0
        for position, url in enumerate(urls):
            photo = existing.get(url)
            if photo:
                if photo.position != position:
                    CarPhoto.objects.filter(pk=photo.pk).update(position=position)
                continue
            try:
                data = self.compress(self.download(url), settings.HOLLMANN_PHOTO_WIDTH)
            except (requests.RequestException, OSError) as exc:
                self.log(f'  {car.external_id}: photo failed ({exc})')
                continue
            photo = CarPhoto(car=car, position=position, source_url=url)
            # A new name every time, so a replaced photo is never served from a stale cache.
            photo.image.save(f'{position + 1:02d}-{uuid.uuid4().hex[:8]}.jpg', ContentFile(data), save=True)
            added += 1
        return added

    def sync_contacts(self, contacts):
        """Store staff portraits once (they are shared by all cars)."""
        for contact in contacts:
            url = contact.pop('photo_url', '')
            contact['photo'] = ''
            match = re.search(r'/employee/([^/]+)/', url)
            if not match:
                continue
            path = f'hollmann/staff/{match.group(1)}.jpg'
            if not default_storage.exists(path):
                try:
                    default_storage.save(path, ContentFile(self.compress(self.download(url), 180)))
                except (requests.RequestException, OSError) as exc:
                    self.log(f'  portrait failed ({exc})')
                    continue
            contact['photo'] = path
        return contacts

    def remove_photos(self, cars):
        for photo in CarPhoto.objects.filter(car__in=cars):
            photo.image.delete(save=False)
            photo.delete()

    def _run(self, run):
        offers = parse_offers(self.get('vehicles/'), self.base_url)
        if not offers:
            raise RuntimeError('No vehicles found on the listing page; the site layout may have changed.')
        if self.limit:
            offers = offers[:self.limit]
        self.log(f'Found {len(offers)} vehicles')

        new_ids = parse_offer_ids(self.get('new/'))

        now = timezone.now()
        seen = set()
        photos_added = 0
        for offer in offers:
            if not offer['make'] or offer['price'] is None:
                continue
            ext_id = offer['external_id']
            seen.add(ext_id)
            page = None
            if self.fetch_details:
                try:
                    page = parse_vehicle_page(self.get(f'vehicle/{ext_id}/'))
                except requests.RequestException as exc:
                    self.log(f'  {ext_id}: details failed ({exc}), keeping previous data')

            with transaction.atomic():
                make = Make.get_by_name(offer['make'])
                defaults = {
                    'make': make,
                    'model': offer['model'][:200],
                    'price': offer['price'],
                    'price_net': offer['price_net'],
                    'currency': offer['currency'],
                    'country': 'DE',  # Hollmann is in Germany
                    'source_url': offer['url'],
                    'is_published': True,
                    'is_new': ext_id in new_ids,
                    'last_synced_at': now,
                }
                if page is not None:
                    defaults['specs'] = page['specs']
                    defaults.update(specs_to_fields(page['specs']))
                    if self.import_media:
                        defaults['description_html'] = page['description_html']
                car, created = Car.objects.update_or_create(
                    source=Car.Source.HOLLMANN, external_id=ext_id, defaults=defaults)
            if page is not None and self.import_media:
                photos_added += self.sync_photos(car, page['photos'])
                Car.objects.filter(pk=car.pk).update(dealer_contacts=self.sync_contacts(page['contacts']))
            if created:
                run.created += 1
            else:
                run.updated += 1

        # Sold / removed on hollmann.international: hide here and free the disk.
        gone = (Car.objects.filter(source=Car.Source.HOLLMANN, is_published=True)
                .exclude(external_id__in=seen))
        if self.limit:
            gone = gone.none()  # a partial run must not unpublish the rest
        gone_ids = list(gone.values_list('pk', flat=True))
        self.remove_photos(gone_ids)
        run.unpublished = Car.objects.filter(pk__in=gone_ids).update(is_published=False)
        self.log(f'Created {run.created}, updated {run.updated}, unpublished {run.unpublished}, '
                 f'photos downloaded {photos_added}')
