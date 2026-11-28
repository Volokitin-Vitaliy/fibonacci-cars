"""Site analytics kept in our own database (no third-party service).

A visitor is identified by a hash of the IP address and the browser (with the site's
secret), so no cookie is stored on the device and the IP itself is never saved.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class PageView(models.Model):
    class Kind(models.TextChoices):
        HOME = 'home', _('Home page')
        CATALOG = 'catalog', _('Catalog')
        CAR = 'car', _('Vehicle page')
        SELL = 'sell', _('Selling and cabinet')
        ACCOUNT = 'account', _('Sign-in and account')
        OTHER = 'other', _('Other pages')

    class Device(models.TextChoices):
        DESKTOP = 'desktop', _('Computer')
        MOBILE = 'mobile', _('Phone')
        TABLET = 'tablet', _('Tablet')

    created_at = models.DateTimeField(db_index=True)
    visitor = models.CharField(max_length=16, db_index=True)
    is_new = models.BooleanField(default=False)          # the visitor's first page ever
    is_member = models.BooleanField(default=False)       # signed in
    path = models.CharField(max_length=300)
    kind = models.CharField(max_length=10, choices=Kind.choices, db_index=True)
    car = models.ForeignKey('cars.Car', null=True, blank=True, on_delete=models.SET_NULL,
                            related_name='pageviews')
    lang = models.CharField(max_length=2, blank=True)
    device = models.CharField(max_length=10, choices=Device.choices, blank=True)
    browser = models.CharField(max_length=20, blank=True)
    os = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=2, blank=True)
    # Where the visitor came from (utm_source or the referring site); empty inside the site.
    source = models.CharField(max_length=40, blank=True)
    referrer = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = _('page view')
        verbose_name_plural = _('page views')
        indexes = [models.Index(fields=['car', 'created_at'])]


class Event(models.Model):
    """Actions that matter for sellers: contact clicks and saving to favorites."""

    class Kind(models.TextChoices):
        PHONE = 'phone', _('Call')
        WHATSAPP = 'whatsapp', 'WhatsApp'
        TELEGRAM = 'telegram', 'Telegram'
        EMAIL = 'email', _('Email')
        FAVORITE = 'favorite', _('Saved to favorites')

    CONTACTS = ('phone', 'whatsapp', 'telegram', 'email')

    created_at = models.DateTimeField(db_index=True)
    visitor = models.CharField(max_length=16, db_index=True)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    car = models.ForeignKey('cars.Car', null=True, blank=True, on_delete=models.SET_NULL,
                            related_name='events')
    device = models.CharField(max_length=10, blank=True)
    country = models.CharField(max_length=2, blank=True)

    class Meta:
        verbose_name = _('event')
        verbose_name_plural = _('events')
        indexes = [models.Index(fields=['car', 'created_at'])]


class Presence(models.Model):
    """Who has the site open right now: refreshed by a ping from open pages."""

    visitor = models.CharField(max_length=16, primary_key=True)
    last_seen = models.DateTimeField(db_index=True)
    path = models.CharField(max_length=300)
    car = models.ForeignKey('cars.Car', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    device = models.CharField(max_length=10, blank=True)
    country = models.CharField(max_length=2, blank=True)
