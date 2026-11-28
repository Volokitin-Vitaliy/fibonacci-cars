"""Posts about new cars in the Telegram channel.

Every car that appears on the site (an approved private listing or a new Hollmann car)
gets a short post: an album of up to 5 photos with the key facts and a link to the site.
Posts go out one at a time from a queue (one an hour by default, nothing at night),
so a big import does not flood the channel. When a car leaves the site its post is
marked "❌ Продано"; if it comes back, the mark is removed.

Settings (.env): TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL (@name or -100… id),
TELEGRAM_CHANNEL_INTERVAL_MINUTES (60), TELEGRAM_CHANNEL_QUIET_HOURS ("23-8").
Run by run_scheduler every few minutes (`python manage.py telegram_channel`).
"""

import html
import json
import logging
import zoneinfo
from datetime import timedelta

import requests
from django.conf import settings
from django.utils import timezone, translation

from .telegram import API, api

logger = logging.getLogger(__name__)

PHOTOS = 5
MAX_ATTEMPTS = 5
SOLD = '❌ <b>Продано</b>'


def enabled():
    return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHANNEL)


def _thousands(value):
    return f'{value:,.0f}'.replace(',', ' ')


def caption(car, sold=False):
    """The post text, in Russian (Telegram HTML), well under Telegram's 1024 characters."""
    e = lambda value: html.escape(str(value))  # noqa: E731
    with translation.override('ru'):
        title = f'{e(car.make.name)} {e(car.model)}' + (f' · {car.year}' if car.year else '')
        lines = [f'🔥 <b>{title}</b>', '']
        price = f'💶 <b>{car.currency_symbol}{_thousands(car.main_price)}</b>'
        if car.price_net:
            price += ' (нетто, экспорт)'
        lines.append(price)
        place = [f'📍 {e(car.country.name)}'] if car.country else []
        if car.accident is not None:
            place.append('⚠️ После ДТП' if car.accident else '✅ Без ДТП')
        if place:
            lines.append(' · '.join(place))
        run = []
        if car.mileage_km is not None:
            run.append(f'🛣 {_thousands(car.mileage_km)} км')
        if car.power_hp:
            run.append(f'⚡ {car.power_hp} л.с.')
        if run:
            lines.append(' · '.join(run))
        tech = []
        if car.fuel:
            tech.append(f'⛽ {e(car.get_fuel_display())}')
        if car.transmission:
            tech.append(f'⚙️ {e(car.get_transmission_display())}')
        if tech:
            lines.append(' · '.join(tech))
        if car.color:
            lines.append(f'🎨 {e(car.color)}')
        url = settings.SITE_URL + car.get_absolute_url()
        lines += ['', f'👉 <a href="{e(url)}">Смотреть подробнее</a>']
    text = '\n'.join(lines)
    return (SOLD + '\n\n' + text) if sold else text


def _upload(method, data, files):
    """A Telegram call with photos uploaded from our disk (no need for Telegram to fetch them)."""
    try:
        response = requests.post(API.format(token=settings.TELEGRAM_BOT_TOKEN, method=method),
                                 data=data, files=files, timeout=60)
        result = response.json()
    except (requests.RequestException, ValueError) as exc:
        return None, str(exc)
    if not result.get('ok'):
        return None, result.get('description', 'error')
    return result.get('result'), ''


def publish(car):
    """Send the post now. Returns (message ids, kind, error)."""
    photos = list(car.photos.all()[:PHOTOS])
    text = caption(car)
    chat = settings.TELEGRAM_CHANNEL
    if not photos:
        message = api('sendMessage', chat_id=chat, text=text, parse_mode='HTML', disable_web_page_preview=False)
        return ([message['message_id']], 'text', '') if message else ([], '', 'sendMessage failed')
    handles = []
    try:
        files = {}
        for i, photo in enumerate(photos):
            handle = photo.image.open('rb')
            handles.append(handle)
            files[f'photo{i}'] = (f'photo{i}.jpg', handle, 'image/jpeg')
        if len(photos) == 1:
            result, error = _upload('sendPhoto', {'chat_id': chat, 'caption': text, 'parse_mode': 'HTML',
                                                  'photo': 'attach://photo0'}, files)
            return ([result['message_id']], 'media', '') if result else ([], '', error)
        media = [{'type': 'photo', 'media': f'attach://photo{i}'} for i in range(len(photos))]
        media[0].update(caption=text, parse_mode='HTML')  # the album's caption sits on its first photo
        result, error = _upload('sendMediaGroup', {'chat_id': chat, 'media': json.dumps(media)}, files)
        return ([m['message_id'] for m in result], 'media', '') if result else ([], '', error)
    except OSError as exc:
        return [], '', f'photo file: {exc}'
    finally:
        for handle in handles:
            handle.close()


def set_sold(post, sold):
    """Add or remove the "❌ Продано" mark on a published post."""
    car, message_id = post.car, post.message_ids[0]
    text = caption(car, sold=sold)
    if post.kind == 'text':
        done = api('editMessageText', chat_id=post.chat, message_id=message_id, text=text, parse_mode='HTML')
    else:
        done = api('editMessageCaption', chat_id=post.chat, message_id=message_id, caption=text, parse_mode='HTML')
    return done is not None


def quiet_now(now=None):
    """Night hours (in ADMIN_TIME_ZONE) when nothing is posted, e.g. "23-8"."""
    spec = (settings.TELEGRAM_CHANNEL_QUIET_HOURS or '').replace(' ', '')
    if '-' not in spec:
        return False
    start, _, end = spec.partition('-')
    if not (start.isdigit() and end.isdigit()):
        return False
    hour = timezone.localtime(now or timezone.now(), zoneinfo.ZoneInfo(settings.ADMIN_TIME_ZONE)).hour
    start, end = int(start), int(end)
    return start <= hour or hour < end if start > end else start <= hour < end


def queue_new_cars():
    """Every car on the site without a post gets one in the queue."""
    from .models import Car, ChannelPost
    fresh = Car.objects.listed().exclude(channel_post__isnull=False).order_by('created_at')
    created = 0
    for car in fresh:
        ChannelPost.objects.get_or_create(car=car, defaults={'status': ChannelPost.Status.QUEUED})
        created += 1
    return created


def send_one(post):
    """Publish one queued post; failures are retried on the next run, up to MAX_ATTEMPTS."""
    from .models import ChannelPost
    car = post.car
    if not type(car).objects.listed().filter(pk=car.pk).exists():
        post.status = ChannelPost.Status.SKIPPED  # left the site before its turn
        post.save(update_fields=['status'])
        return False
    ids, kind, error = publish(car)
    post.attempts += 1
    if ids:
        post.status, post.message_ids, post.kind = ChannelPost.Status.SENT, ids, kind
        post.chat, post.sent_at, post.error = str(settings.TELEGRAM_CHANNEL), timezone.now(), ''
    else:
        post.error = error[:500]
        if post.attempts >= MAX_ATTEMPTS:
            post.status = ChannelPost.Status.FAILED
    post.save()
    return bool(ids)


def update_sold_marks():
    """Mark posts of cars that left the site, unmark the ones that came back."""
    from .models import Car, ChannelPost
    listed = set(Car.objects.listed().values_list('pk', flat=True))
    changed = 0
    for post in ChannelPost.objects.filter(status=ChannelPost.Status.SENT).select_related('car', 'car__make'):
        if post.car is None:
            continue
        should_be_sold = post.car_id not in listed
        if should_be_sold != post.sold and set_sold(post, should_be_sold):
            post.sold = should_be_sold
            post.save(update_fields=['sold'])
            changed += 1
    return changed


def run(now=None):
    """One pass: queue new cars, post the next one if it is time, update the sold marks."""
    from .models import ChannelPost
    if not enabled():
        return 'TELEGRAM_CHANNEL is not set: nothing posted.'
    if not ChannelPost.objects.exists():  # first run: the 3 newest now, older cars are not posted
        skipped, results = start()
        return f'Channel started: posted {sum(ok for _, ok, _ in results)} newest cars, {skipped} older skipped.'
    now = now or timezone.now()
    queued = queue_new_cars()
    sent = 0
    last = ChannelPost.objects.filter(status=ChannelPost.Status.SENT).order_by('-sent_at').first()
    interval = timedelta(minutes=settings.TELEGRAM_CHANNEL_INTERVAL_MINUTES)
    if not quiet_now(now) and (last is None or last.sent_at is None or now - last.sent_at >= interval):
        post = ChannelPost.objects.filter(status=ChannelPost.Status.QUEUED).select_related('car', 'car__make') \
            .order_by('queued_at').first()
        if post is not None:
            sent = int(send_one(post))
    marked = update_sold_marks()
    return f'Channel: queued {queued}, posted {sent}, sold marks changed {marked}.'


def start(test_count=3):
    """First launch: the cars already on the site are not posted, except the `test_count`
    newest ones, which are posted right away; from then on new cars go out one an hour."""
    from .models import Car, ChannelPost
    cars = list(Car.objects.listed().exclude(channel_post__isnull=False).order_by('-created_at'))
    test, rest = cars[:test_count], cars[test_count:]
    ChannelPost.objects.bulk_create([ChannelPost(car=c, status=ChannelPost.Status.SKIPPED) for c in rest])
    results = []
    for car in reversed(test):  # oldest of the three first, so the newest ends up on top
        post = ChannelPost.objects.create(car=car, status=ChannelPost.Status.QUEUED)
        results.append((car, send_one(post), post.error))
    return len(rest), results
