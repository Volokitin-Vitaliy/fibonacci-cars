import re
from datetime import date
from decimal import Decimal

from django import forms
from django.conf import settings
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

from django_countries import countries

from . import images
from .models import Car, CarPhoto, Make

EXCLUDED_COUNTRIES = {'RU'}


def country_choices():
    """All countries in the visitor's language, without excluded ones (Russia)."""
    return [('', '—')] + [(c.code, c.name) for c in countries if c.code not in EXCLUDED_COUNTRIES]

phone_validator = RegexValidator(
    r'^\+?[\d\s()\-]{6,25}$',
    _('Enter a valid phone number, for example +49 151 1234567.'),
)


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', MultipleFileInput(attrs={'accept': 'image/*'}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if not data:
            return []
        files = data if isinstance(data, (list, tuple)) else [data]
        return [super(MultipleImageField, self).clean(f, initial) for f in files]


class CarForm(forms.ModelForm):
    photos = MultipleImageField(
        label=_('Photos'), required=False,
        help_text=_('Up to %(n)s images.') % {'n': settings.LISTING_MAX_PHOTOS})
    accident = forms.TypedChoiceField(
        label=_('Was the car in an accident?'), widget=forms.RadioSelect,
        choices=[('False', _('No')), ('True', _('Yes'))],
        coerce=lambda value: value == 'True')
    contact_phone = forms.CharField(label=_('Phone'), max_length=30,
                                    validators=[phone_validator])
    contact_whatsapp = forms.CharField(label='WhatsApp', max_length=30, required=False,
                                       validators=[phone_validator],
                                       help_text=_('Number with country code, e.g. +49 151 1234567'))
    contact_telegram = forms.CharField(label='Telegram', max_length=60, required=False,
                                       help_text=_('@username or phone number'))
    country = forms.ChoiceField(label=_('Country where the car is'), choices=country_choices)

    class Meta:
        model = Car
        fields = ('make', 'model', 'fuel', 'country', 'description', 'year', 'mileage_km',
                  'transmission', 'power_hp', 'color', 'accident', 'price', 'currency',
                  'contact_name', 'contact_phone', 'contact_whatsapp', 'contact_telegram')
        widgets = {
            'description': forms.Textarea(attrs={'rows': 6}),
            'currency': forms.RadioSelect,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['make'].queryset = Make.objects.all()
        self.fields['make'].empty_label = _('Choose a make')
        self.fields['make'].label = _('Make')
        self.fields['model'].label = _('Model / title')
        self.fields['contact_name'].required = True
        self.fields['fuel'].required = True
        self.fields['fuel'].label = _('Category')
        self.fields['fuel'].choices = [('', _('Choose a category'))] + list(Car.Fuel.choices)
        self.fields['transmission'].choices = [('', '—')] + list(self.fields['transmission'].choices)[1:]
        self.fields['year'].widget.attrs.update(min=1900, max=date.today().year + 1)
        self.fields['price'].widget.attrs.update(min=1, step='1')
        if self.instance.pk and self.instance.accident is not None:
            self.initial['accident'] = str(self.instance.accident)

    def clean_year(self):
        year = self.cleaned_data.get('year')
        if year and not 1900 <= year <= date.today().year + 1:
            raise forms.ValidationError(_('Enter a year between 1900 and next year.'))
        return year

    def clean_contact_telegram(self):
        value = self.cleaned_data.get('contact_telegram', '').strip()
        if not value:
            return ''
        value = re.sub(r'^(https?://)?(www\.)?(t\.me|telegram\.me)/', '', value).strip('/')
        if re.fullmatch(r'\+?[\d\s()\-]{6,25}', value):
            return ' '.join(value.split())
        username = value.lstrip('@')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{4,31}', username):
            raise forms.ValidationError(_('Enter a Telegram username like @name or a phone number.'))
        return username

    def clean_price(self):
        price = self.cleaned_data.get('price')
        if price is not None and price <= 0:
            raise forms.ValidationError(_('The price must be greater than zero.'))
        return price

    def clean_photos(self):
        photos = self.cleaned_data.get('photos') or []
        existing = self.instance.photos.count() if self.instance.pk else 0
        if not photos and not existing and not self.instance.pk:
            raise forms.ValidationError(_('Add at least one photo of the car.'))
        if existing + len(photos) > settings.LISTING_MAX_PHOTOS:
            raise forms.ValidationError(
                _('A listing can have at most %(n)s photos.') % {'n': settings.LISTING_MAX_PHOTOS})
        return photos

    def save(self, commit=True):
        car = super().save(commit=commit)
        if commit:
            start = car.photos.count()
            for i, image in enumerate(self.cleaned_data.get('photos') or []):
                photo = CarPhoto(car=car, position=start + i)
                cleaned = images.clean_upload(image)
                photo.image.save(cleaned.name, cleaned, save=False)
                photo.save()
        return car


class LooseIntegerField(forms.IntegerField):
    """Accepts numbers typed with spaces, commas or dots as thousand separators."""

    def to_python(self, value):
        if isinstance(value, str):
            value = re.sub(r'[\s,.\u00a0\u202f€$km]', '', value, flags=re.I)
        return super().to_python(value)


def year_presets():
    """Every year from next year down to 1970."""
    return [(y, str(y)) for y in range(date.today().year + 1, 1969, -1)]


class CarFilterForm(forms.Form):
    """Catalog filters. Prices are typed in EUR or USD and compared in EUR."""

    price_min = LooseIntegerField(label=_('From'), required=False, min_value=0)
    price_max = LooseIntegerField(label=_('To'), required=False, min_value=0)
    cur = forms.ChoiceField(choices=[('EUR', '€'), ('USD', '$')], required=False)
    year_min = LooseIntegerField(label=_('Year from'), required=False, min_value=1900, max_value=2100)
    year_max = LooseIntegerField(label=_('Year to'), required=False, min_value=1900, max_value=2100)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('year_min', 'year_max'):
            self.fields[name].presets = year_presets()

    @property
    def currency(self):
        value = self.data.get('cur') if self.is_bound else None
        return value if value in ('EUR', 'USD') else 'EUR'

    @property
    def currency_symbol(self):
        return '$' if self.currency == 'USD' else '€'

    @property
    def price_summary(self):
        """Text on the closed price dropdown, e.g. "€50 000 – €200 000"."""
        if not self.price_active:
            return ''
        sym = self.currency_symbol
        fmt = lambda v: sym + f'{v:,}'.replace(',', '\u202f')  # noqa: E731
        low, high = self.cleaned_data.get('price_min'), self.cleaned_data.get('price_max')
        if low is not None and high is not None:
            return f'{fmt(low)} – {fmt(high)}'
        if low is not None:
            return _('from %(price)s') % {'price': fmt(low)}
        return _('up to %(price)s') % {'price': fmt(high)}

    @property
    def price_fields(self):
        return [self['price_min'], self['price_max']]

    @property
    def year_fields(self):
        return [self['year_min'], self['year_max']]

    def apply(self, cars):
        if not self.is_valid():
            return cars
        data = self.cleaned_data
        rate = Decimal(str(settings.USD_TO_EUR_RATE)) if self.currency == 'USD' else Decimal(1)
        if data.get('price_min') is not None:
            cars = cars.filter(price_eur__gte=data['price_min'] * rate)
        if data.get('price_max') is not None:
            cars = cars.filter(price_eur__lte=data['price_max'] * rate)
        if data.get('year_min') is not None:
            cars = cars.filter(year__gte=data['year_min'])
        if data.get('year_max') is not None:
            cars = cars.filter(year__lte=data['year_max'])
        return cars

    @property
    def active_count(self):
        if not self.is_valid():
            return 0
        return sum(1 for k, v in self.cleaned_data.items() if k != 'cur' and v is not None)

    @property
    def price_active(self):
        return self.is_valid() and any(self.cleaned_data.get(k) is not None
                                       for k in ('price_min', 'price_max'))
