from datetime import date

from django import forms
from django.conf import settings
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

from .models import Car, Category, Make

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
    category = forms.ModelChoiceField(
        queryset=Category.objects.all(), label=_('Category'),
        empty_label=_('Choose a category'))
    photos = MultipleImageField(
        label=_('Photos'), required=False,
        help_text=_('Up to %(n)s images.') % {'n': settings.LISTING_MAX_PHOTOS})
    contact_phone = forms.CharField(label=_('Contact phone'), max_length=30,
                                    validators=[phone_validator])

    class Meta:
        model = Car
        fields = ('make', 'model', 'category', 'description', 'year', 'mileage_km',
                  'fuel', 'transmission', 'power_hp', 'color', 'price', 'currency',
                  'contact_name', 'contact_phone')
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
        for name in ('fuel', 'transmission'):
            self.fields[name].choices = [('', '—')] + list(self.fields[name].choices)[1:]
        self.fields['year'].widget.attrs.update(min=1900, max=date.today().year + 1)
        self.fields['price'].widget.attrs.update(min=1, step='1')
        if self.instance.pk:
            self.fields['category'].initial = self.instance.categories.first()

    def clean_year(self):
        year = self.cleaned_data.get('year')
        if year and not 1900 <= year <= date.today().year + 1:
            raise forms.ValidationError(_('Enter a year between 1900 and next year.'))
        return year

    def clean_price(self):
        price = self.cleaned_data.get('price')
        if price is not None and price <= 0:
            raise forms.ValidationError(_('The price must be greater than zero.'))
        return price

    def clean_photos(self):
        photos = self.cleaned_data.get('photos') or []
        existing = self.instance.photos.count() if self.instance.pk else 0
        if existing + len(photos) > settings.LISTING_MAX_PHOTOS:
            raise forms.ValidationError(
                _('A listing can have at most %(n)s photos.') % {'n': settings.LISTING_MAX_PHOTOS})
        return photos

    def save(self, commit=True):
        car = super().save(commit=commit)
        if commit:
            car.categories.set([self.cleaned_data['category']])
            start = car.photos.count()
            for i, image in enumerate(self.cleaned_data.get('photos') or []):
                car.photos.create(image=image, position=start + i)
        return car


class CarFilterForm(forms.Form):
    """Catalog filters. Prices are compared in EUR (USD is converted)."""

    price_min = forms.IntegerField(label=_('Price from, €'), required=False, min_value=0)
    price_max = forms.IntegerField(label=_('Price to, €'), required=False, min_value=0)
    year_min = forms.IntegerField(label=_('Year from'), required=False, min_value=1900, max_value=2100)
    year_max = forms.IntegerField(label=_('Year to'), required=False, min_value=1900, max_value=2100)
    mileage_max = forms.IntegerField(label=_('Mileage up to, km'), required=False, min_value=0)

    def apply(self, cars):
        if not self.is_valid():
            return cars
        data = self.cleaned_data
        if data.get('price_min') is not None:
            cars = cars.filter(price_eur__gte=data['price_min'])
        if data.get('price_max') is not None:
            cars = cars.filter(price_eur__lte=data['price_max'])
        if data.get('year_min') is not None:
            cars = cars.filter(year__gte=data['year_min'])
        if data.get('year_max') is not None:
            cars = cars.filter(year__lte=data['year_max'])
        if data.get('mileage_max') is not None:
            cars = cars.filter(mileage_km__lte=data['mileage_max'])
        return cars

    @property
    def active_count(self):
        if not self.is_valid():
            return 0
        return sum(1 for v in self.cleaned_data.values() if v is not None)
