"""Automatic translation of listing descriptions between the two site languages.

A seller writes the description in Russian or English; the other version is made
with the DeepL API and stored on the car (description_translated). Imported
Hollmann descriptions are HTML and are translated with their tags kept, then
sanitized again. The translation is redone only when the description changes
(translation_source_hash). Without DEEPL_API_KEY nothing is translated and the
original is shown in both languages.
"""

import hashlib
import logging
import re
import threading

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.db import close_old_connections, transaction

logger = logging.getLogger(__name__)

LANGUAGES = ('ru', 'en')
TARGET_CODES = {'ru': 'RU', 'en': 'EN-GB'}
TIMEOUT = 30
CYRILLIC = re.compile(r'[а-яё]', re.IGNORECASE)
LATIN = re.compile(r'[a-z]', re.IGNORECASE)


class TranslationError(Exception):
    pass


def enabled():
    return bool(settings.DEEPL_API_KEY)


def detect_language(text):
    """'ru' when the letters are mostly Cyrillic, otherwise 'en'."""
    plain = re.sub(r'<[^>]+>', ' ', text or '')
    cyrillic, latin = len(CYRILLIC.findall(plain)), len(LATIN.findall(plain))
    return 'ru' if cyrillic and cyrillic >= latin * 0.5 else 'en'


def source_of(car):
    """The text that is translated: (text, is_html)."""
    if car.description:
        return car.description, False
    return car.description_html, True


def text_hash(text, is_html):
    return hashlib.sha256(f'{int(is_html)}:{text}'.encode()).hexdigest()


def api_url():
    host = 'api-free.deepl.com' if settings.DEEPL_API_KEY.endswith(':fx') else 'api.deepl.com'
    return f'https://{host}/v2/translate'


def deepl(text, source, target, is_html):
    payload = {'text': [text], 'target_lang': TARGET_CODES[target]}
    if source == 'ru':
        payload['source_lang'] = 'RU'
    # Latin-script text is left to DeepL to detect: dealer texts mix English with German.
    if is_html:
        # Option codes like <code>ACC1</code> stay as they are.
        payload.update(tag_handling='html', ignore_tags=['code'])
    try:
        response = requests.post(api_url(), json=payload, timeout=TIMEOUT,
                                 headers={'Authorization': f'DeepL-Auth-Key {settings.DEEPL_API_KEY}'})
    except requests.RequestException as exc:
        raise TranslationError(str(exc)) from exc
    if response.status_code != 200:
        raise TranslationError(f'DeepL HTTP {response.status_code}: {response.text[:200]}')
    try:
        return response.json()['translations'][0]['text']
    except (ValueError, KeyError, IndexError) as exc:
        raise TranslationError('Unexpected DeepL response') from exc


def clean_html(html):
    """The translated HTML gets the same sanitizing as the imported original."""
    from .importers.hollmann import sanitize_description
    return sanitize_description(BeautifulSoup(f'<div>{html}</div>', 'html.parser').div)


def needs_translation(car):
    text, is_html = source_of(car)
    if not text.strip():
        return bool(car.description_translated or car.translation_source_hash)
    return car.translation_source_hash != text_hash(text, is_html)


def translate_car(car):
    """Translate the car's description if it changed. Returns True when the car was updated."""
    from .models import Car
    if not needs_translation(car):
        return False
    text, is_html = source_of(car)
    if not text.strip():
        fields = {'description_lang': '', 'description_translated': '', 'translation_source_hash': ''}
    else:
        if not enabled():
            return False
        source = detect_language(text)
        target = 'en' if source == 'ru' else 'ru'
        translated = deepl(text, source, target, is_html)
        if is_html:
            translated = clean_html(translated)
        fields = {'description_lang': source, 'description_translated': translated,
                  'translation_source_hash': text_hash(text, is_html)}
    # A direct update: no save() signals, and the description may have been edited meanwhile.
    Car.objects.filter(pk=car.pk).update(**fields)
    for name, value in fields.items():
        setattr(car, name, value)
    return True


def translate_in_background(car_pk):
    """After the transaction commits, translate one listing in a thread so the
    seller does not wait for the API. Failures are retried by the daily job."""
    if not enabled():
        return

    def run():
        from .models import Car
        try:
            car = Car.objects.filter(pk=car_pk).first()
            if car is not None:
                translate_car(car)
        except Exception:
            logger.exception('Translation of car %s failed', car_pk)
        finally:
            close_old_connections()

    transaction.on_commit(lambda: threading.Thread(target=run, daemon=True).start())
