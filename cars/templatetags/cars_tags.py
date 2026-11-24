import json

from django import template
from django.utils.safestring import mark_safe
from django.utils.translation import gettext, gettext_noop

register = template.Library()

# Labels and values of the imported specification table. Marked for
# translation so the Russian site shows them in Russian.
SPEC_TERMS = [
    gettext_noop('Offer Number'), gettext_noop('Color'), gettext_noop('Upholstery'),
    gettext_noop('Mileage'), gettext_noop('Seats'), gettext_noop('Transmission'),
    gettext_noop('Drive'), gettext_noop('Capacity'), gettext_noop('Power (kW)'),
    gettext_noop('Power (PS)'), gettext_noop('Emission Standard'),
    gettext_noop('Energy Consumption (combined)'), gettext_noop('Fuel Consumption (combined)'),
    gettext_noop('Fuel Consumption (City)'), gettext_noop('Fuel Consumption (Suburban)'),
    gettext_noop('Fuel Consumption (Rural)'), gettext_noop('Fuel Consumption (Highway)'),
    gettext_noop('CO₂ Emissions (combined)'),
    gettext_noop('CO₂ Class based on CO₂ Emissions (combined)'),
    gettext_noop('German Vehicle Tax (yearly)'), gettext_noop('First Registration'),
    gettext_noop('Electric Range'), gettext_noop('Battery Capacity'),
    gettext_noop('Automatic'), gettext_noop('Manual'),
    gettext_noop('Combustion Engine (Petrol)'), gettext_noop('Combustion Engine (Diesel)'),
    gettext_noop('Electric'), gettext_noop('Hybrid (Petrol/Electric)'),
    gettext_noop('Hybrid (Diesel/Electric)'), gettext_noop('Plug-in Hybrid'),
    gettext_noop('Previous Owners'),
    gettext_noop('Electric Range (EAER)'),
    gettext_noop('Electric Range (max.)'),
    gettext_noop('Electricity Consumption (combined)'),
    gettext_noop('Electricity Consumption (City)'),
    gettext_noop('Electricity Consumption (Suburban)'),
    gettext_noop('Electricity Consumption (Rural)'),
    gettext_noop('Electricity Consumption (Highway)'),
    gettext_noop('Electricity Consumption (weighted, combined)'),
    gettext_noop('Fuel Consumption (weighted, combined)'),
    gettext_noop('Fuel Consumption with a Discharged Battery (combined)'),
    gettext_noop('Fuel Consumption with a Discharged Battery (City)'),
    gettext_noop('Fuel Consumption with a Discharged Battery (Suburban)'),
    gettext_noop('Fuel Consumption with a Discharged Battery (Rural)'),
    gettext_noop('Fuel Consumption with a Discharged Battery (Highway)'),
    gettext_noop('CO₂ Emissions (weighted, combined)'),
    gettext_noop('CO₂ Class based on CO₂ Emissions (weighted, combined)'),
    gettext_noop('CO₂ Emissions with a Discharged Battery'),
    gettext_noop('CO₂ Class based on CO₂ Emissions with a Discharged Battery'),
    gettext_noop('Electric Motor (Electricity)'),
    gettext_noop('Plugin Hybrid (Petrol/Electricity)'),
]


@register.filter
def spec(value):
    """Translate a known spec label or value, leave anything else as is."""
    return gettext(value) if value else value


@register.simple_tag
def json_ld(data):
    """<script type="application/ld+json"> with the data, safe to embed in HTML."""
    text = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    text = text.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    return mark_safe(f'<script type="application/ld+json">{text}</script>')


@register.filter
def photo_main_url(photo):
    """Photo size for the big picture on the vehicle page (sharp on phones and laptops)."""
    return photo.url_for(1600)


@register.filter
def money(value):
    """168980.00 -> '168,980' ; keeps cents only when present."""
    if value is None:
        return ''
    if value == int(value):
        return f'{int(value):,}'
    return f'{value:,.2f}'


@register.filter
def thousands(value):
    if value in (None, ''):
        return ''
    return f'{int(value):,}'.replace(',', ' ')


@register.simple_tag(takes_context=True)
def url_with(context, **kwargs):
    """Current query string with some parameters replaced."""
    query = context['request'].GET.copy()
    for key, value in kwargs.items():
        if value in (None, ''):
            query.pop(key, None)
        else:
            query[key] = value
    return '?' + query.urlencode() if query else '?'


@register.inclusion_tag('includes/hreflang.html', takes_context=True)
def hreflang(context):
    """<link rel="alternate" hreflang> for every language of the current page."""
    from django.conf import settings
    from django.urls import translate_url

    request = context['request']
    url = request.build_absolute_uri(request.path)
    links = [(code, translate_url(url, code)) for code, _name in settings.LANGUAGES]
    return {'links': links, 'canonical': url, 'default': translate_url(url, settings.LANGUAGE_CODE)}
