"""Cloudflare Turnstile: an invisible check that the visitor is not a bot.

Switched on when TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY are set in .env.
"""

import logging

import requests
from django.conf import settings
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)
VERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'
ERROR = _('Please confirm that you are not a robot and try again.')


def enabled():
    return bool(settings.TURNSTILE_SITE_KEY and settings.TURNSTILE_SECRET_KEY)


def passed(request):
    """True if the form was sent by a person (or the check is switched off)."""
    if not enabled():
        return True
    token = request.POST.get('cf-turnstile-response', '')
    if not token:
        return False
    try:
        response = requests.post(VERIFY_URL, timeout=5, data={
            'secret': settings.TURNSTILE_SECRET_KEY,
            'response': token,
            'remoteip': request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR'),
        })
        return bool(response.json().get('success'))
    except (requests.RequestException, ValueError):
        # Cloudflare unreachable: let people through rather than block every sign-up.
        logger.warning('Turnstile check could not be completed', exc_info=True)
        return True


def check(request, form):
    """Adds an error to the form if the check failed. Returns True when it passed."""
    if passed(request):
        return True
    form.add_error(None, ERROR)
    return False
