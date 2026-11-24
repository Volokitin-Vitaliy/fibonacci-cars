"""Keep allauth's email records in step with our own email confirmation.

allauth decides whether a Google / Apple sign-in may keep the account's password by
looking at its EmailAddress table. Accounts confirmed by our own link (or created by an
admin) must be recorded there as verified, otherwise allauth wipes their password on the
first Google sign-in.
"""

from allauth.account.models import EmailAddress
from django.db import transaction


def sync_verified_email(sender, instance, **kwargs):
    if not instance.email_verified or not instance.email:
        return
    email = instance.email.lower()
    with transaction.atomic():
        EmailAddress.objects.filter(user=instance).exclude(email__iexact=email).update(primary=False)
        address = EmailAddress.objects.filter(user=instance, email__iexact=email).first()
        if address is None:
            EmailAddress.objects.create(user=instance, email=email, verified=True, primary=True)
        elif not (address.verified and address.primary):
            address.verified = address.primary = True
            address.save(update_fields=['verified', 'primary'])
