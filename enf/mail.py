"""Emails as plain text plus, when a .html template exists, a designed HTML version."""

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.utils import translation

logger = logging.getLogger(__name__)


def send(template, to, language, context):
    """Render `<template>_subject.txt`, `<template>.txt` and, if present,
    `<template>.html` in the given language and send them. Never raises."""
    context = {'site_url': settings.SITE_URL, 'logo_url': settings.SITE_URL + static('img/logo-96.png'),
               **context}
    with translation.override(language or settings.LANGUAGE_CODE):
        subject = ' '.join(render_to_string(f'{template}_subject.txt', context).split())
        text = render_to_string(f'{template}.txt', context)
        try:
            html = render_to_string(f'{template}.html', context)
        except TemplateDoesNotExist:
            html = None
    message = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, to)
    if html:
        message.attach_alternative(html, 'text/html')
    try:
        message.send()
        return True
    except Exception:  # an email problem must not break the request or the job
        logger.exception('Could not send %s email to %s', template, to)
        return False
