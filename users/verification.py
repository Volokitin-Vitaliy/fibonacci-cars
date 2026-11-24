"""Email confirmation for accounts created with email and password."""

import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.core.cache import cache
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from enf import mail

logger = logging.getLogger(__name__)
RESEND_INTERVAL = 60  # seconds between "send again" emails for one account


def link_for(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return request.build_absolute_uri(reverse('users:verify_email', args=[uid, token]))


def send_link(request, user):
    mail.send('users/email/verify', [user.email], user.language,
              {'user': user, 'link': link_for(request, user)})


def may_resend(request, user):
    """At most one email per minute per account."""
    return cache.add(f'verify-resend:{user.pk}', 1, RESEND_INTERVAL)


def user_from_link(uidb64, token):
    try:
        user = get_user_model().objects.get(pk=urlsafe_base64_decode(uidb64).decode())
    except (TypeError, ValueError, OverflowError, get_user_model().DoesNotExist):
        return None
    return user if default_token_generator.check_token(user, token) else None


# ---- Changing the email address: the new address must be confirmed first ----
EMAIL_CHANGE_SALT = 'users.email-change'
EMAIL_CHANGE_MAX_AGE = 60 * 60 * 24 * 3  # 3 days


def send_change_link(request, user, new_email):
    token = signing.dumps({'u': user.pk, 'old': user.email, 'new': new_email}, salt=EMAIL_CHANGE_SALT)
    link = request.build_absolute_uri(reverse('users:confirm_email_change', args=[token]))
    mail.send('users/email/change', [new_email], user.language,
              {'user': user, 'link': link, 'new_email': new_email})


def email_change_from_link(token):
    """(user, new_email) for a valid link, else None. A link stops working once the
    address it was sent from has changed."""
    try:
        data = signing.loads(token, salt=EMAIL_CHANGE_SALT, max_age=EMAIL_CHANGE_MAX_AGE)
        user = get_user_model().objects.get(pk=data['u'])
    except (signing.BadSignature, KeyError, TypeError, get_user_model().DoesNotExist):
        return None
    if user.email != data.get('old'):
        return None
    return user, data['new']
