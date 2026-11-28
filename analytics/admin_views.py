"""The analytics page in the admin."""

import json
import zoneinfo
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import admin
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _

from . import report
from .models import PageView

LIMIT_CARS = 25


def _query(params, **changes):
    merged = {k: v for k, v in params.items() if v}
    for key, value in changes.items():
        if value in (None, ''):
            merged.pop(key, None)
        else:
            merged[key] = value
    return '?' + urlencode(merged) if merged else '?'


def _kpi(title, key, now, before, suffix='', hint=''):
    value, previous = now[key], before[key]
    return {'title': title, 'value': value, 'suffix': suffix, 'previous': previous,
            'change': report.change(value, previous), 'hint': hint}


def dashboard(request):
    with timezone.override(zoneinfo.ZoneInfo(settings.ADMIN_TIME_ZONE)):
        return _dashboard(request)


def _dashboard(request):
    from cars.models import Make

    params = {k: request.GET.get(k, '') for k in ('period', 'month', 'year', 'from', 'to', 'sort', 'cars', *report.FILTERS)}
    if request.GET.get('online') == '1':  # live counter refresh
        return JsonResponse(report.online())
    period = report.Period(params)
    filters = {k: params[k] for k in report.FILTERS if params[k]}
    now_totals = report.totals(period.start, period.end, filters)
    before = report.totals(period.prev_start, period.prev_end, filters)
    views = report.views_between(period.start, period.end, filters)
    chart = report.chart(period, filters)
    sort = params['sort'] if params['sort'] in report.CAR_SORTS else 'views'
    cars, cars_total = report.top_cars(period, filters, sort, None if params['cars'] == 'all' else LIMIT_CARS)
    year = int(period.year) if period.key == 'year' else timezone.localtime(period.start).year
    month_rows = report.months(year, filters)
    month_max = max([m['visitors'] for m in month_rows] + [1])

    # Choices for the filters: only values that exist in the data.
    year_ago = timezone.now() - timedelta(days=400)
    recent = PageView.objects.filter(created_at__gte=year_ago)
    first = PageView.objects.order_by('created_at').values_list('created_at', flat=True).first()
    first_year = timezone.localtime(first).year if first else timezone.localtime().year
    choices = {
        'device': list(PageView.Device.choices),
        'kind': list(PageView.Kind.choices),
        'lang': [('ru', 'Русский'), ('en', 'English')],
        'visitor': [('new', _('New visitors')), ('returning', _('Returning visitors'))],
        'member': [('yes', _('Signed in')), ('no', _('Guests'))],
        'country': sorted(((c, report.country_name(c)) for c in recent.exclude(country='')
                           .values_list('country', flat=True).distinct()), key=lambda x: x[1][3:]),
        'source': [('direct', _('Direct'))] + [(s, s) for s in recent.exclude(source='').values('source')
                                                 .annotate(n=Count('id')).order_by('-n').values_list('source', flat=True)[:40]],
        'make': list(Make.objects.filter(cars__isnull=False).distinct().order_by('name').values_list('slug', 'name')),
    }
    filter_labels = {'device': _('Device'), 'country': _('Country'), 'source': _('Source'), 'lang': _('Language'),
                     'kind': _('Page'), 'visitor': _('Visitors'), 'member': _('Account'), 'make': _('Make')}
    active_filters = []
    for key, value in filters.items():
        label = dict(choices.get(key, [])).get(value, value)
        active_filters.append({'name': filter_labels[key], 'value': label, 'remove': _query(params, **{key: None})})

    def chart_json(values, label, color):
        return {'label': label, 'data': values, 'borderColor': color, 'backgroundColor': color, 'tension': .35,
                'pointRadius': 0 if len(values) > 40 else 2, 'borderWidth': 2, 'fill': False}

    chart_data = json.dumps({'labels': chart['labels'], 'datasets': [
        chart_json(chart['visitors'], _('Visitors'), 'var(--color-primary-500)'),
        chart_json(chart['pageviews'], _('Page views'), 'rgb(148, 163, 184)'),
    ]})

    t = now_totals
    context = {
        **admin.site.each_context(request),
        'title': _('Analytics'),
        'period': period, 'params': params, 'filters': filters, 'choices': choices,
        'keep_period': [(k, params[k]) for k in ('period', 'month', 'year', 'from', 'to', 'sort') if params[k]],
        'keep_filters': [(k, params[k]) for k in ('period', 'sort', *report.FILTERS) if params[k]],
        'filter_fields': [(k, filter_labels[k], choices[k]) for k in report.FILTERS],
        'active_filters': active_filters, 'clear_filters': _query({k: params[k] for k in ('period', 'month', 'year', 'from', 'to')}),
        'periods': [(key, label, _query(params, period=key)) for key, label in (
            ('realtime', _('Now')), ('hour', _('Hour')), ('today', _('Today')), ('yesterday', _('Yesterday')),
            ('7d', _('7 days')), ('30d', _('30 days')), ('month', _('Month')), ('year', _('Year')),
            ('custom', _('Dates')))],
        'online': report.online(),
        'kpis': [
            _kpi(_('Visitors'), 'visitors', t, before, hint=_('Different people (by device and network)')),
            _kpi(_('New visitors'), 'new', t, before, hint=_('Opened the site for the first time')),
            _kpi(_('Page views'), 'pageviews', t, before, hint=_('%(n)s pages per visitor') % {'n': t['per_visitor']}),
            _kpi(_('Vehicle views'), 'car_views', t, before),
            _kpi(_('Contact clicks'), 'contacts', t, before, hint=_('Call, WhatsApp, Telegram on vehicle pages')),
            _kpi(_('Contact rate'), 'contact_rate', t, before, suffix='%',
                 hint=_('Of those who opened a vehicle, contacted the seller')),
            _kpi(_('Saved to favorites'), 'favorites', t, before),
        ],
        'chart_data': chart_data,
        'chart_options': json.dumps({
            'responsive': True, 'maintainAspectRatio': False, 'interaction': {'mode': 'index', 'intersect': False},
            'plugins': {'legend': {'display': True, 'position': 'bottom', 'align': 'start'}},
            'scales': {'x': {'grid': {'display': False}, 'ticks': {'maxTicksLimit': 16}},
                       'y': {'beginAtZero': True, 'ticks': {'precision': 0}, 'grid': {}}},
        }),
        'tables': [
            (_('Sources'), report.sources(views), 'source'),
            (_('Countries'), report.breakdown(views, 'country', label=report.country_name), 'country'),
            (_('Devices'), report.breakdown(views, 'device', label=lambda v: dict(PageView.Device.choices).get(v, v)), 'device'),
            (_('Pages'), report.breakdown(views, 'kind', label=lambda v: dict(PageView.Kind.choices).get(v, v)), 'kind'),
            (_('Browsers'), report.breakdown(views, 'browser'), None),
            (_('Systems'), report.breakdown(views, 'os'), None),
            (_('Site language'), report.breakdown(views, 'lang', label=lambda v: {'ru': 'Русский', 'en': 'English'}.get(v, v)), 'lang'),
            (_('Referring sites'), report.breakdown(views, 'referrer', limit=12), None),
        ],
        'top_paths': report.breakdown(views, 'path', limit=15),
        'cars': cars, 'cars_total': cars_total, 'cars_sort': sort, 'cars_all': params['cars'] == 'all',
        'car_sorts': [(key, label, _query(params, sort=key)) for key, label in (
            ('views', _('Most viewed')), ('least', _('Least viewed')), ('visitors', _('Most visitors')),
            ('contacts', _('Most contacts')), ('favorites', _('Most saved')), ('recent', _('Viewed recently')))],
        'cars_all_url': _query(params, cars='all'), 'cars_less_url': _query(params, cars=None),
        'months': month_rows, 'month_max': month_max, 'months_year': year,
        'years': list(range(timezone.localtime().year, first_year - 1, -1)),
        'time_zone': settings.ADMIN_TIME_ZONE,
    }
    for name, rows, key in context['tables']:
        for row in rows:
            row['filter'] = _query(params, **{key: row['value']}) if key else None
    for m in month_rows:
        m['url'] = _query(params, period='month', month=f"{year}-{m['month']:02d}")
        m['bar'] = round(100 * m['visitors'] / month_max)
    return render(request, 'admin/analytics/dashboard.html', context)
