import math
import re
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import models
from django_countries.fields import CountryField
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _


def to_eur(amount, currency):
    if amount is None:
        return None
    if currency == 'USD':
        return (Decimal(amount) * Decimal(str(settings.USD_TO_EUR_RATE))).quantize(Decimal('0.01'))
    return amount


class Make(models.Model):
    name = models.CharField(_('name'), max_length=100, unique=True)
    slug = models.SlugField(max_length=110, unique=True)

    class Meta:
        ordering = ('name',)
        verbose_name = _('make')
        verbose_name_plural = _('makes')

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or 'make'
            slug, n = base, 2
            while Make.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f'{base}-{n}', n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    @classmethod
    def get_by_name(cls, name):
        name = ' '.join(name.split())
        return cls.objects.filter(name__iexact=name).first() or cls.objects.create(name=name)

    def get_absolute_url(self):
        return reverse('cars:make', args=[self.slug])

    @property
    def logo_url(self):
        """Monochrome logo of the make, or a neutral car icon."""
        from django.templatetags.static import static

        from .makes_data import logo_key
        key = logo_key(self.name)
        return static(f'img/makes/{key}.svg' if key else 'img/makes/_car.svg')

    @property
    def has_logo(self):
        from .makes_data import logo_key
        return logo_key(self.name) is not None


class CarQuerySet(models.QuerySet):
    def visible(self):
        """Cars that may be shown publicly right now.

        Imported cars are visible while they are still listed on the source
        site. User listings are visible while active and not expired; the
        expiry check happens here, so a listing disappears the moment its
        month is over even if the daily job has not run yet."""
        now = timezone.now()
        return self.filter(
            Q(source=Car.Source.HOLLMANN, is_published=True)
            | Q(source=Car.Source.USER, status=Car.Status.ACTIVE, active_until__gt=now,
                moderation=Car.Moderation.APPROVED)
        )

    def new_offers(self):
        recent = timezone.now() - timedelta(days=14)
        return self.visible().filter(
            Q(source=Car.Source.HOLLMANN, is_new=True)
            | Q(source=Car.Source.USER, activated_at__gte=recent)
        )


class Car(models.Model):
    class Source(models.TextChoices):
        HOLLMANN = 'hollmann', 'hollmann.international'
        USER = 'user', _('User listing')

    class Status(models.TextChoices):
        ACTIVE = 'active', _('Active')
        INACTIVE = 'inactive', _('Inactive')

    class Moderation(models.TextChoices):
        AWAITING_PAYMENT = 'awaiting_payment', _('Awaiting payment')
        PENDING = 'pending', _('Pending review')
        APPROVED = 'approved', _('Approved')
        REJECTED = 'rejected', _('Rejected')

    class Currency(models.TextChoices):
        EUR = 'EUR', '€ EUR'
        USD = 'USD', '$ USD'

    class Fuel(models.TextChoices):
        # Fuel types, as on the big classifieds.
        PETROL = 'petrol', _('Petrol')
        DIESEL = 'diesel', _('Diesel')
        GAS = 'gas', _('Gas')
        LPG_PETROL = 'lpg_petrol', _('LPG / Petrol')
        CNG_PETROL = 'cng_petrol', _('CNG / Petrol')
        HYBRID = 'hybrid', _('Hybrid (HEV)')
        PHEV = 'phev', _('Plug-in hybrid (PHEV)')
        MHEV = 'mhev', _('Mild hybrid (MHEV)')
        ELECTRIC = 'electric', _('Electric')
        OTHER = 'other', _('Other')

    class Transmission(models.TextChoices):
        MANUAL = 'manual', _('Manual')
        AUTOMATIC = 'automatic', _('Automatic')
        TIPTRONIC = 'tiptronic', _('Tiptronic')
        ROBOT = 'robot', _('Robotic')
        CVT = 'cvt', _('CVT')
        REDUCER = 'reducer', _('Reduction gear')

    source = models.CharField(_('source'), max_length=20, choices=Source.choices, default=Source.USER)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              null=True, blank=True, related_name='cars', verbose_name=_('owner'))

    make = models.ForeignKey(Make, on_delete=models.PROTECT, related_name='cars',
                             verbose_name=_('make'))
    model = models.CharField(_('model / title'), max_length=200)
    description = models.TextField(_('description'), blank=True)
    # Imported cars: the dealer's description (sanitized HTML) and contacts,
    # a list of {name, languages, phone, mobile, whatsapp, photo}.
    description_html = models.TextField(_('description (HTML)'), blank=True)
    dealer_contacts = models.JSONField(_('dealer contacts'), default=list, blank=True)

    # Short characteristics (user listings fill these in).
    year = models.PositiveIntegerField(_('year'), null=True, blank=True)
    mileage_km = models.PositiveIntegerField(_('mileage, km'), null=True, blank=True)
    fuel = models.CharField(_('category'), max_length=20, choices=Fuel.choices, blank=True,
                            db_index=True)
    transmission = models.CharField(_('transmission'), max_length=20,
                                    choices=Transmission.choices, blank=True)
    power_hp = models.PositiveIntegerField(_('power, hp'), null=True, blank=True)
    color = models.CharField(_('color'), max_length=100, blank=True)
    # Was the car damaged in an accident? None = not stated (imported cars).
    accident = models.BooleanField(_('accident damage'), null=True, blank=True, db_index=True)
    # Where the car is. Imported Hollmann cars are in Germany.
    country = CountryField(_('country'), blank=True, db_index=True)

    # Full specification table as [label, value] pairs (imported cars).
    specs = models.JSONField(default=list, blank=True)

    price = models.DecimalField(_('price'), max_digits=12, decimal_places=2)
    currency = models.CharField(_('currency'), max_length=3, choices=Currency.choices,
                                default=Currency.EUR)
    # Net export price shown by hollmann.international next to the gross price.
    price_net = models.DecimalField(_('net price'), max_digits=12, decimal_places=2, null=True, blank=True)
    # Price converted to EUR, used for filtering and sorting across currencies.
    price_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                    db_index=True, editable=False)

    contact_name = models.CharField(_('contact person'), max_length=150, blank=True)
    contact_phone = models.CharField(_('contact phone'), max_length=30, blank=True)
    contact_whatsapp = models.CharField(_('WhatsApp'), max_length=30, blank=True)
    # Telegram username (without @) or phone number.
    contact_telegram = models.CharField(_('Telegram'), max_length=40, blank=True)

    # User listing lifecycle.
    status = models.CharField(_('status'), max_length=20, choices=Status.choices, default=Status.ACTIVE)
    activated_at = models.DateTimeField(_('activated at'), null=True, blank=True)
    active_until = models.DateTimeField(_('active until'), null=True, blank=True)
    reminder_sent_at = models.DateTimeField(null=True, blank=True)

    # Moderation of user listings.
    moderation = models.CharField(_('moderation'), max_length=20, choices=Moderation.choices,
                                  default=Moderation.APPROVED)
    rejection_reason = models.TextField(_('rejection reason'), blank=True)
    # The reason of the last rejection, kept when the owner resubmits, so the moderator
    # sees what was asked to be fixed. Cleared on approval.
    previous_rejection_reason = models.TextField(_('previous rejection reason'), blank=True)
    # Telegram moderation message (chat id, message id) of the current review.
    telegram_messages = models.JSONField(default=list, blank=True)

    # Import bookkeeping.
    external_id = models.CharField(max_length=50, blank=True)
    source_url = models.URLField(blank=True)
    is_published = models.BooleanField(_('published'), default=True)
    is_new = models.BooleanField(_('new offer'), default=False)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(_('created'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated'), auto_now=True)

    objects = CarQuerySet.as_manager()

    class Meta:
        ordering = ('-created_at',)
        verbose_name = _('vehicle')
        verbose_name_plural = _('vehicles')
        constraints = [
            models.UniqueConstraint(
                fields=('source', 'external_id'),
                condition=~Q(external_id=''),
                name='unique_external_vehicle',
            ),
        ]

    def __str__(self):
        return f'{self.make} {self.model}'

    def save(self, *args, **kwargs):
        self.price_eur = to_eur(self.price, self.currency)
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'price' in update_fields:
            kwargs['update_fields'] = set(update_fields) | {'price_eur'}
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('cars:detail', args=[self.pk])

    def get_fuel_url(self):
        return reverse('cars:fuel', args=[self.fuel]) if self.fuel else ''

    @property
    def is_pending(self):
        return self.moderation == self.Moderation.PENDING

    @property
    def is_rejected(self):
        return self.moderation == self.Moderation.REJECTED

    @property
    def is_approved(self):
        return self.moderation == self.Moderation.APPROVED

    @property
    def is_imported(self):
        return self.source == self.Source.HOLLMANN

    @property
    def is_new_offer(self):
        if self.is_imported:
            return self.is_new
        return bool(self.activated_at and self.activated_at >= timezone.now() - timedelta(days=14))

    @property
    def main_price(self):
        """Dealers show the net export price first; private sellers one price."""
        return self.price_net or self.price

    @property
    def is_listing_active(self):
        """For user listings: active and the paid/free month is not over."""
        return (self.status == self.Status.ACTIVE and self.active_until is not None
                and self.active_until > timezone.now())

    @property
    def days_left(self):
        if not self.is_listing_active:
            return 0
        seconds = (self.active_until - timezone.now()).total_seconds()
        return max(math.ceil(seconds / 86400), 0)

    @property
    def phone_url(self):
        digits = re.sub(r'[^\d+]', '', self.contact_phone)
        return f'tel:{digits}' if digits else ''

    @property
    def whatsapp_url(self):
        digits = re.sub(r'\D', '', self.contact_whatsapp)
        return f'https://wa.me/{digits}' if digits else ''

    @property
    def telegram_url(self):
        value = self.contact_telegram.strip()
        if not value:
            return ''
        if re.fullmatch(r'\+?[\d\s()\-]+', value):
            return 'https://t.me/+' + re.sub(r'\D', '', value)
        return 'https://t.me/' + value.lstrip('@')

    @property
    def telegram_display(self):
        value = self.contact_telegram.strip()
        if value and not re.fullmatch(r'\+?[\d\s()\-]+', value):
            return '@' + value.lstrip('@')
        return value

    @property
    def currency_symbol(self):
        return '$' if self.currency == self.Currency.USD else '€'

    @property
    def cover(self):
        photos = getattr(self, '_prefetched_objects_cache', {}).get('photos')
        if photos is not None:
            return photos[0] if photos else None
        return self.photos.first()

    def spec_rows(self):
        """Rows of the details table: the imported table, or one built from
        the short characteristics of a user listing."""
        if self.specs:
            return [tuple(row) for row in self.specs]
        rows = []
        if self.year:
            rows.append((_('Year'), str(self.year)))
        if self.mileage_km is not None:
            rows.append((_('Mileage'), f'{self.mileage_km:,} km'.replace(',', ' ')))
        if self.fuel:
            rows.append((_('Category'), self.get_fuel_display()))
        if self.transmission:
            rows.append((_('Transmission'), self.get_transmission_display()))
        if self.power_hp:
            rows.append((_('Power'), f'{self.power_hp} {_("hp")}'))
        if self.color:
            rows.append((_('Color'), self.color))
        if self.accident is not None:
            rows.append((_('Accident damage'), _('Yes, after an accident') if self.accident else _('No accidents')))
        return rows

    def activate(self, days=None, paid_amount=Decimal('0'), method='free'):
        """Start a new listing period (one month by default)."""
        days = days or settings.LISTING_DURATION_DAYS
        now = timezone.now()
        self.status = self.Status.ACTIVE
        self.activated_at = now
        self.active_until = now + timedelta(days=days)
        self.reminder_sent_at = None
        self.save(update_fields=['status', 'activated_at', 'active_until', 'reminder_sent_at',
                                 'updated_at'])
        ListingPeriod.objects.create(car=self, starts_at=now, ends_at=self.active_until,
                                     amount=paid_amount, method=method)

    def deactivate(self):
        self.status = self.Status.INACTIVE
        self.save(update_fields=['status', 'updated_at'])


def car_photo_path(instance, filename):
    return f'cars/{instance.car_id}/{filename}'


class CarPhoto(models.Model):
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to=car_photo_path)
    position = models.PositiveIntegerField(default=0)
    # Original address of an imported photo, so the daily import downloads it only once.
    source_url = models.URLField(max_length=500, blank=True, db_index=True)
    # Widths of the WebP copies made by cars.images (the last one is the full size).
    variants = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ('position', 'id')

    def _variant_url(self, width):
        from .images import variant_path
        return default_storage.url(variant_path(self.image.name, width))

    def url_for(self, width):
        """The smallest copy at least `width` pixels wide (or the largest there is)."""
        if not self.variants:
            return self.image.url
        fitting = [w for w in self.variants if w >= width]
        return self._variant_url(min(fitting) if fitting else max(self.variants))

    @property
    def thumb_url(self):
        return self.url_for(240)

    @property
    def small_url(self):
        return self.url_for(480)

    @property
    def card_url(self):
        return self.url_for(960)

    @property
    def large_url(self):
        return self.url_for(10_000)

    @property
    def srcset(self):
        return ', '.join(f'{self._variant_url(w)} {w}w' for w in sorted(self.variants))


class Favorite(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='favorites')
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='favorited_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [
            models.UniqueConstraint(fields=('user', 'car'), name='unique_favorite'),
        ]


class ListingPeriod(models.Model):
    """One month of a user listing. Kept as history and as the hook for the
    planned paid activation (5 EUR per month)."""

    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='periods')
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    amount = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0'))
    method = models.CharField(max_length=20, default='free')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-starts_at',)


class ImportRun(models.Model):
    source = models.CharField(max_length=20, default=Car.Source.HOLLMANN)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created = models.PositiveIntegerField(default=0)
    updated = models.PositiveIntegerField(default=0)
    unpublished = models.PositiveIntegerField(default=0)
    ok = models.BooleanField(default=False)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ('-started_at',)


class Payment(models.Model):
    """A payment for one listing period (WayForPay or Stripe)."""

    class Provider(models.TextChoices):
        WAYFORPAY = 'wayforpay', 'WayForPay'
        STRIPE = 'stripe', 'Stripe'

    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        PAID = 'paid', _('Paid')
        FAILED = 'failed', _('Failed')

    car = models.ForeignKey(Car, on_delete=models.SET_NULL, null=True, related_name='payments')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                             related_name='payments')
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    currency = models.CharField(max_length=3, default='EUR')
    provider = models.CharField(max_length=20, choices=Provider.choices, default=Provider.STRIPE)
    # Stripe Checkout session id or WayForPay orderReference.
    reference = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    # When the paid period was started (paid at submission, used on approval).
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)
