import math
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _


class Category(models.Model):
    """A vehicle collection, mirroring hollmann.international's collections
    (Customized, Armoured, Oldtimer, Electric)."""

    slug = models.SlugField(unique=True)
    name_en = models.CharField(_('name (English)'), max_length=100)
    name_ru = models.CharField(_('name (Russian)'), max_length=100)
    # Collection id on hollmann.international (/vehicle-collection/<id>/).
    hollmann_id = models.PositiveIntegerField(null=True, blank=True, unique=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ('position', 'name_en')
        verbose_name = _('category')
        verbose_name_plural = _('categories')

    def __str__(self):
        return self.name

    @property
    def name(self):
        return self.name_ru if get_language() == 'ru' and self.name_ru else self.name_en

    def get_absolute_url(self):
        return reverse('cars:category', args=[self.slug])


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
            | Q(source=Car.Source.USER, status=Car.Status.ACTIVE, active_until__gt=now)
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

    class Currency(models.TextChoices):
        EUR = 'EUR', '€ EUR'
        USD = 'USD', '$ USD'

    class Fuel(models.TextChoices):
        PETROL = 'petrol', _('Petrol')
        DIESEL = 'diesel', _('Diesel')
        HYBRID = 'hybrid', _('Hybrid')
        ELECTRIC = 'electric', _('Electric')
        OTHER = 'other', _('Other')

    class Transmission(models.TextChoices):
        AUTOMATIC = 'automatic', _('Automatic')
        MANUAL = 'manual', _('Manual')

    source = models.CharField(max_length=20, choices=Source.choices, default=Source.USER)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              null=True, blank=True, related_name='cars')

    make = models.ForeignKey(Make, on_delete=models.PROTECT, related_name='cars',
                             verbose_name=_('make'))
    model = models.CharField(_('model / title'), max_length=200)
    categories = models.ManyToManyField(Category, blank=True, related_name='cars',
                                        verbose_name=_('categories'))
    description = models.TextField(_('description'), blank=True)

    # Short characteristics (user listings fill these in).
    year = models.PositiveIntegerField(_('year'), null=True, blank=True)
    mileage_km = models.PositiveIntegerField(_('mileage, km'), null=True, blank=True)
    fuel = models.CharField(_('fuel'), max_length=20, choices=Fuel.choices, blank=True)
    transmission = models.CharField(_('transmission'), max_length=20,
                                    choices=Transmission.choices, blank=True)
    power_hp = models.PositiveIntegerField(_('power, hp'), null=True, blank=True)
    color = models.CharField(_('color'), max_length=100, blank=True)

    # Full specification table as [label, value] pairs (imported cars).
    specs = models.JSONField(default=list, blank=True)

    price = models.DecimalField(_('price'), max_digits=12, decimal_places=2)
    currency = models.CharField(_('currency'), max_length=3, choices=Currency.choices,
                                default=Currency.EUR)
    # Net export price shown by hollmann.international next to the gross price.
    price_net = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    contact_name = models.CharField(_('contact person'), max_length=150, blank=True)
    contact_phone = models.CharField(_('contact phone'), max_length=30, blank=True)

    # User listing lifecycle.
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    activated_at = models.DateTimeField(null=True, blank=True)
    active_until = models.DateTimeField(null=True, blank=True)

    # Import bookkeeping.
    external_id = models.CharField(max_length=50, blank=True)
    source_url = models.URLField(blank=True)
    is_published = models.BooleanField(default=True)
    is_new = models.BooleanField(default=False)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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

    def get_absolute_url(self):
        return reverse('cars:detail', args=[self.pk])

    @property
    def is_imported(self):
        return self.source == self.Source.HOLLMANN

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
            rows.append((_('Fuel'), self.get_fuel_display()))
        if self.transmission:
            rows.append((_('Transmission'), self.get_transmission_display()))
        if self.power_hp:
            rows.append((_('Power'), f'{self.power_hp} {_("hp")}'))
        if self.color:
            rows.append((_('Color'), self.color))
        return rows

    def activate(self, days=None, paid_amount=Decimal('0'), method='free'):
        """Start a new listing period (one month by default)."""
        days = days or settings.LISTING_DURATION_DAYS
        now = timezone.now()
        self.status = self.Status.ACTIVE
        self.activated_at = now
        self.active_until = now + timedelta(days=days)
        self.save(update_fields=['status', 'activated_at', 'active_until', 'updated_at'])
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

    class Meta:
        ordering = ('position', 'id')


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
