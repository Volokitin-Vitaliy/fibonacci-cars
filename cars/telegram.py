"""Moderation in Telegram.

When a listing is submitted (or resubmitted after a rejection), the moderators get its
photos and details with two buttons: Approve / Reject. Rejecting asks for the reason,
which the moderator sends as a reply. Decisions go through cars.services, exactly like
the admin: the owner gets an email, the listing goes live or shows the reason in the
cabinet. Decisions made in the admin also close the buttons in Telegram.

Settings (.env): TELEGRAM_BOT_TOKEN, TELEGRAM_MODERATOR_CHAT_IDS (comma-separated).
The webhook is registered with `python manage.py telegram_webhook`.
"""

import hashlib
import html
import logging
import re

import requests
from django.conf import settings
from django.urls import reverse
from django.utils import translation

logger = logging.getLogger(__name__)

API = 'https://api.telegram.org/bot{token}/{method}'
REASON_PROMPT = 'Напишите причину отказа для объявления #{pk} ответом на это сообщение'
REASON_RE = re.compile(r'причину отказа для объявления #(\d+)')


def bot_configured():
    """A token is set: the bot answers (e.g. /start shows the chat id needed for setup)."""
    return bool(settings.TELEGRAM_BOT_TOKEN)


def enabled():
    """Token and moderators are set: listings are sent for review in Telegram."""
    return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_MODERATOR_CHAT_IDS)


def webhook_secret():
    """Secret Telegram sends back in a header with every update (proves it is Telegram)."""
    if settings.TELEGRAM_WEBHOOK_SECRET:
        return settings.TELEGRAM_WEBHOOK_SECRET
    return hashlib.sha256(f'telegram:{settings.SECRET_KEY}'.encode()).hexdigest()[:48]


def api(method, **data):
    try:
        response = requests.post(API.format(token=settings.TELEGRAM_BOT_TOKEN, method=method),
                                 json=data, timeout=15)
        result = response.json()
    except (requests.RequestException, ValueError):
        logger.warning('Telegram %s failed', method, exc_info=True)
        return None
    if not result.get('ok'):
        logger.warning('Telegram %s: %s', method, result.get('description'))
        return None
    return result.get('result')


def _absolute(path):
    return settings.SITE_URL + path


def _admin_url(car):
    return _absolute(reverse('admin:cars_car_change', args=[car.pk]))


def listing_text(car, resubmitted=False):
    """Details of a listing for the moderator, in Russian (Telegram HTML)."""
    e = lambda value: html.escape(str(value))  # noqa: E731
    with translation.override('ru'):
        head = '🔁 <b>Исправленное объявление</b>' if resubmitted else '🆕 <b>Новое объявление</b>'
        lines = [f'{head} #{car.pk}', '', f'<b>{e(car.make.name)} {e(car.model)}</b>']
        price = f'{car.currency_symbol}{car.price:,.0f}'.replace(',', ' ') if car.price else '—'
        facts = [
            ('Цена', price),
            ('Год', car.year),
            ('Пробег', f'{car.mileage_km:,} км'.replace(',', ' ') if car.mileage_km is not None else None),
            ('Мощность', f'{car.power_hp} л.с.' if car.power_hp else None),
            ('Топливо', car.get_fuel_display() if car.fuel else None),
            ('Коробка', car.get_transmission_display() if car.transmission else None),
            ('Цвет', car.color),
            ('ДТП', None if car.accident is None else ('было' if car.accident else 'не было')),
            ('Страна', car.country.name if car.country else None),
        ]
        lines += [f'{label}: {e(value)}' for label, value in facts if value not in (None, '')]
        lines += ['', f'Продавец: {e(car.contact_name)}', f'Телефон: {e(car.contact_phone)}']
        if car.contact_whatsapp:
            lines.append(f'WhatsApp: {e(car.contact_whatsapp)}')
        if car.contact_telegram:
            lines.append(f'Telegram: {e(car.telegram_display)}')
        if car.owner_id:
            lines.append(f'Аккаунт: {e(car.owner.email)}')
        if car.description:
            text = car.description.strip()
            lines += ['', e(text[:700] + ('…' if len(text) > 700 else ''))]
        if resubmitted and car.previous_rejection_reason:
            lines += ['', f'⚠️ <b>Вы просили исправить:</b>\n{e(car.previous_rejection_reason)}']
        lines += ['', f'Фото: {car.photos.count()}']
    return '\n'.join(lines)[:4000]


def _keyboard(car):
    return {'inline_keyboard': [
        [{'text': '✅ Одобрить', 'callback_data': f'approve:{car.pk}'},
         {'text': '❌ Отклонить', 'callback_data': f'reject:{car.pk}'}],
        [{'text': 'Открыть в админке', 'url': _admin_url(car)}],
    ]}


def notify_new_listing(car, resubmitted=False):
    """Send the listing to every moderator chat. Never raises."""
    if not enabled():
        return
    photos = [_absolute(p.image.url) for p in car.photos.all()[:6]]
    text = listing_text(car, resubmitted)
    sent = []
    for chat_id in settings.TELEGRAM_MODERATOR_CHAT_IDS:
        if len(photos) > 1:
            api('sendMediaGroup', chat_id=chat_id, media=[{'type': 'photo', 'media': url} for url in photos])
        elif photos:
            api('sendPhoto', chat_id=chat_id, photo=photos[0])
        message = api('sendMessage', chat_id=chat_id, text=text, parse_mode='HTML',
                      disable_web_page_preview=True, reply_markup=_keyboard(car))
        if message:
            sent.append([chat_id, message['message_id']])
    type(car).objects.filter(pk=car.pk).update(telegram_messages=sent)
    car.telegram_messages = sent


def listing_decided(car):
    """Close the buttons of the review messages and say what was decided."""
    if not enabled() or not car.telegram_messages:
        return
    if car.moderation == car.Moderation.APPROVED:
        status = f'✅ Одобрено, объявление #{car.pk} опубликовано'
    else:
        reason = html.escape(car.rejection_reason) if car.rejection_reason else 'без причины'
        status = f'❌ Отклонено #{car.pk}: {reason}'
    for chat_id, message_id in car.telegram_messages:
        api('editMessageReplyMarkup', chat_id=chat_id, message_id=message_id,
            reply_markup={'inline_keyboard': [[{'text': 'Открыть в админке', 'url': _admin_url(car)}]]})
        api('sendMessage', chat_id=chat_id, text=status, parse_mode='HTML', reply_to_message_id=message_id)
    type(car).objects.filter(pk=car.pk).update(telegram_messages=[])
    car.telegram_messages = []


def _is_moderator(*ids):
    allowed = set(settings.TELEGRAM_MODERATOR_CHAT_IDS)
    return any(i in allowed for i in ids if i is not None)


def handle_update(update):
    """Process one update from the webhook."""
    from . import services
    from .models import Car

    callback = update.get('callback_query')
    if callback:
        chat_id = (callback.get('message') or {}).get('chat', {}).get('id')
        user_id = (callback.get('from') or {}).get('id')
        if not _is_moderator(chat_id, user_id):
            api('answerCallbackQuery', callback_query_id=callback['id'], text='Нет доступа')
            return
        action, _, pk = (callback.get('data') or '').partition(':')
        car = Car.objects.filter(pk=pk, source=Car.Source.USER).first() if pk.isdigit() else None
        if car is None:
            api('answerCallbackQuery', callback_query_id=callback['id'], text='Объявление не найдено')
        elif car.moderation != Car.Moderation.PENDING:
            api('answerCallbackQuery', callback_query_id=callback['id'],
                text=f'Уже решено: {car.get_moderation_display()}')
        elif action == 'approve':
            services.approve(car)
            api('answerCallbackQuery', callback_query_id=callback['id'], text='Одобрено ✅')
        elif action == 'reject':
            api('answerCallbackQuery', callback_query_id=callback['id'])
            api('sendMessage', chat_id=chat_id, text=REASON_PROMPT.format(pk=car.pk) + ' (или «-» без причины).',
                reply_markup={'force_reply': True, 'input_field_placeholder': 'Что нужно исправить'})
        return

    message = update.get('message') or {}
    chat_id = message.get('chat', {}).get('id')
    text = (message.get('text') or '').strip()
    if text.startswith('/start') or text.startswith('/id'):
        api('sendMessage', chat_id=chat_id,
            text=f'Ваш chat id: <code>{chat_id}</code>\nДобавьте его в TELEGRAM_MODERATOR_CHAT_IDS в .env.',
            parse_mode='HTML')
        return
    match = REASON_RE.search((message.get('reply_to_message') or {}).get('text') or '')
    if not match or not _is_moderator(chat_id, (message.get('from') or {}).get('id')):
        return
    car = Car.objects.filter(pk=match.group(1), source=Car.Source.USER).first()
    if car is None or car.moderation != Car.Moderation.PENDING:
        api('sendMessage', chat_id=chat_id, text='Это объявление уже не ждёт проверки.')
        return
    services.reject(car, '' if text == '-' else text)
