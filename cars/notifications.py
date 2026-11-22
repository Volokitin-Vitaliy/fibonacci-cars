"""Emails to listing owners and moderators, sent in the owner's language."""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation

logger = logging.getLogger(__name__)


def absolute(path):
    return settings.SITE_URL + path


def _send(template, to, language, context):
    with translation.override(language or settings.LANGUAGE_CODE):
        subject = render_to_string(f'cars/email/{template}_subject.txt', context).strip()
        body = render_to_string(f'cars/email/{template}.txt', context)
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, to)
        return True
    except Exception:  # an email problem must not break the request or the job
        logger.exception('Could not send %s email to %s', template, to)
        return False


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
