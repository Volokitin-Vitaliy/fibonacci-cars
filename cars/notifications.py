"""Emails to listing owners and moderators, sent in the owner's language."""

import logging

from django.conf import settings

from enf import mail
from django.urls import reverse
from django.utils import translation

logger = logging.getLogger(__name__)


def absolute(path):
    return settings.SITE_URL + path


def _send(template, to, language, context):
    return mail.send(f'cars/email/{template}', to, language, context)


def _owner_context(car, language):
    with translation.override(language):
        return {
            'car': car,
            'user': car.owner,
            'car_url': absolute(car.get_absolute_url()),
            'cabinet_url': absolute(reverse('cars:my_cars')),
        }


def notify_expiring(car):
    owner = car.owner
    return _send('expiring', [owner.email], owner.language, _owner_context(car, owner.language))


def notify_approved(car):
    owner = car.owner
    return _send('approved', [owner.email], owner.language, _owner_context(car, owner.language))


def notify_rejected(car):
    owner = car.owner
    return _send('rejected', [owner.email], owner.language, _owner_context(car, owner.language))


def notify_moderators(car):
    if not settings.MODERATION_EMAILS:
        return False
    return _send('moderation', settings.MODERATION_EMAILS, settings.LANGUAGE_CODE, {
        'car': car,
        'admin_url': absolute(reverse('admin:cars_car_change', args=[car.pk])),
    })
