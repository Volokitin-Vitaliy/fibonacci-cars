"""Daily import of the vehicle list from hollmann.international.

Only factual data is imported: make, model, prices and the specification
table, together with a link to the original offer. Photos,
descriptions and staff contacts are not copied.
"""

import logging
import re
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from cars.models import Car, ImportRun, Make

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
    def __init__(self, base_url=None, delay=None, fetch_details=True, session=None, stdout=None):
        self.base_url = (base_url or settings.HOLLMANN_BASE_URL).rstrip('/') + '/'
        self.delay = settings.HOLLMANN_REQUEST_DELAY if delay is None else delay
        self.fetch_details = fetch_details
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

    def _run(self, run):
        offers = parse_offers(self.get('vehicles/'), self.base_url)
        if not offers:
            raise RuntimeError('No vehicles found on the listing page; the site layout may have changed.')
        self.log(f'Found {len(offers)} vehicles')

        new_ids = parse_offer_ids(self.get('new/'))

        now = timezone.now()
        seen = set()
        for offer in offers:
            if not offer['make'] or offer['price'] is None:
                continue
            ext_id = offer['external_id']
            seen.add(ext_id)
            specs = None
            if self.fetch_details:
                try:
                    specs = parse_detail(self.get(f'vehicle/{ext_id}/'))
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
                    'source_url': offer['url'],
                    'is_published': True,
                    'is_new': ext_id in new_ids,
                    'last_synced_at': now,
                }
                if specs is not None:
                    defaults['specs'] = specs
                    defaults.update(specs_to_fields(specs))
                car, created = Car.objects.update_or_create(
                    source=Car.Source.HOLLMANN, external_id=ext_id, defaults=defaults)
            if created:
                run.created += 1
            else:
                run.updated += 1

        run.unpublished = (Car.objects
                           .filter(source=Car.Source.HOLLMANN, is_published=True)
                           .exclude(external_id__in=seen)
                           .update(is_published=False))
        self.log(f'Created {run.created}, updated {run.updated}, unpublished {run.unpublished}')
