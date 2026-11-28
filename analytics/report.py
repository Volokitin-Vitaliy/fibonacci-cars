"""Numbers for the analytics page in the admin: periods, filters, totals, charts, tables."""

from datetime import datetime, time, timedelta

from django.db.models import Count, IntegerField, Max, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce, TruncDay, TruncHour, TruncMinute, TruncMonth
from django.utils import timezone
from django.utils.translation import gettext as _
from django_countries import countries

from .models import Event, PageView, Presence

ONLINE_MINUTES = 2
PERIODS = ('realtime', 'hour', 'today', 'yesterday', '7d', '30d', 'month', 'year', 'custom')
FILTERS = ('device', 'country', 'source', 'lang', 'kind', 'visitor', 'member', 'make')


def _local_midnight(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def _parse_date(value):
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


class Period:
    """The chosen time range, its chart step and the range before it (for comparison)."""

    def __init__(self, params, now=None):
        now = now or timezone.now()
        local = timezone.localtime(now)
        today = local.date()
        self.key = params.get('period') if params.get('period') in PERIODS else 'today'
        self.month = params.get('month') or f'{today:%Y-%m}'
        self.year = params.get('year') or str(today.year)
        key = self.key
        if key == 'realtime':
            self.start, self.end, self.step = now - timedelta(minutes=30), now, 'minute'
        elif key == 'hour':
            self.start, self.end, self.step = now - timedelta(hours=1), now, 'minute'
        elif key == 'today':
            self.start, self.end, self.step = _local_midnight(today), now, 'hour'
        elif key == 'yesterday':
            self.start, self.end, self.step = _local_midnight(today - timedelta(days=1)), _local_midnight(today), 'hour'
        elif key in ('7d', '30d'):
            days = 7 if key == '7d' else 30
            self.start, self.end, self.step = _local_midnight(today - timedelta(days=days - 1)), now, 'day'
        elif key == 'month':
            first = _parse_date(self.month + '-01') or today.replace(day=1)
            self.month = f'{first:%Y-%m}'
            nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
            self.start, self.end, self.step = _local_midnight(first), min(_local_midnight(nxt), now), 'day'
            self.full_end = _local_midnight(nxt)
        elif key == 'year':
            year = int(self.year) if str(self.year).isdigit() else today.year
            self.year = str(year)
            first = datetime(year, 1, 1).date()
            self.start = _local_midnight(first)
            self.end = min(_local_midnight(datetime(year + 1, 1, 1).date()), now)
            self.step = 'month'
            self.full_end = _local_midnight(datetime(year + 1, 1, 1).date())
        else:  # custom
            start = _parse_date(params.get('from')) or today - timedelta(days=29)
            end = _parse_date(params.get('to')) or today
            if end < start:
                start, end = end, start
            self.start, self.end = _local_midnight(start), min(_local_midnight(end + timedelta(days=1)), now)
            self.step = 'month' if (end - start).days > 120 else 'day'
        self.date_from = timezone.localtime(self.start).date()
        self.date_to = timezone.localtime(self.end - timedelta(seconds=1)).date()
        # The same length right before, to compare with.
        length = self.end - self.start
        if key == 'month':
            prev_first = (self.start - timedelta(days=1)).replace(day=1)
            self.prev_start, self.prev_end = prev_first, prev_first + length
        elif key == 'year':
            self.prev_start = self.start.replace(year=self.start.year - 1)
            self.prev_end = self.prev_start + length
        else:
            self.prev_start, self.prev_end = self.start - length, self.start

    def buckets(self):
        """Every step of the chart, so empty hours/days show as zero."""
        tz = timezone.get_current_timezone()
        end = getattr(self, 'full_end', self.end)
        if self.step == 'minute':
            current = self.start.replace(second=0, microsecond=0)
            delta = timedelta(minutes=1)
        elif self.step == 'hour':
            current = timezone.localtime(self.start).replace(minute=0, second=0, microsecond=0)
            if self.key == 'today':
                end = self.start + timedelta(days=1)
            delta = timedelta(hours=1)
        elif self.step == 'day':
            current = timezone.localtime(self.start).replace(hour=0, minute=0, second=0, microsecond=0)
            delta = timedelta(days=1)
        else:
            current = timezone.localtime(self.start).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            delta = None
        result = []
        while current < end and len(result) < 400:
            result.append(current)
            if delta:
                current = (current + delta).astimezone(tz) if self.step != 'day' else \
                    timezone.make_aware(datetime.combine((current + delta).date(), time.min))
            else:
                year, month = (current.year + 1, 1) if current.month == 12 else (current.year, current.month + 1)
                current = current.replace(year=year, month=month)
        return result

    def label(self, moment):
        moment = timezone.localtime(moment)
        if self.step == 'minute':
            return f'{moment:%H:%M}'
        if self.step == 'hour':
            return f'{moment:%H}:00'
        if self.step == 'day':
            return f'{moment:%d.%m}'
        return f'{moment:%m.%Y}'

    def trunc(self, field='created_at'):
        tz = timezone.get_current_timezone()
        return {'minute': TruncMinute, 'hour': TruncHour, 'day': TruncDay, 'month': TruncMonth}[self.step](field, tzinfo=tz)


def filter_views(qs, filters, start, end):
    f = filters
    firsts = PageView.objects.filter(is_new=True, created_at__gte=start, created_at__lt=end).values('visitor')
    if f.get('device'):
        qs = qs.filter(device=f['device'])
    if f.get('country'):
        qs = qs.filter(country=f['country'])
    if f.get('lang'):
        qs = qs.filter(lang=f['lang'])
    if f.get('kind'):
        qs = qs.filter(kind=f['kind'])
    if f.get('source') == 'direct':
        qs = qs.exclude(visitor__in=qs.exclude(source='').values('visitor'))
    elif f.get('source'):
        qs = qs.filter(visitor__in=qs.filter(source=f['source']).values('visitor'))
    if f.get('visitor') == 'new':
        qs = qs.filter(visitor__in=firsts)  # first came in this period
    elif f.get('visitor') == 'returning':
        qs = qs.exclude(visitor__in=firsts)
    if f.get('member') == 'yes':
        qs = qs.filter(is_member=True)
    elif f.get('member') == 'no':
        qs = qs.filter(is_member=False)
    if f.get('make'):
        qs = qs.filter(car__make__slug=f['make'])
    return qs


def views_between(start, end, filters):
    qs = PageView.objects.filter(created_at__gte=start, created_at__lt=end)
    return filter_views(qs, filters, start, end)


def events_between(start, end, filters):
    qs = Event.objects.filter(created_at__gte=start, created_at__lt=end, car__isnull=False)
    if filters.get('device'):
        qs = qs.filter(device=filters['device'])
    if filters.get('country'):
        qs = qs.filter(country=filters['country'])
    if filters.get('make'):
        qs = qs.filter(car__make__slug=filters['make'])
    return qs


def totals(start, end, filters):
    views = views_between(start, end, filters)
    events = events_between(start, end, filters)
    contacts = events.filter(kind__in=Event.CONTACTS)
    visitors = views.values('visitor').distinct().count()
    car_viewers = views.filter(kind='car').values('visitor').distinct().count()
    contacting = contacts.values('visitor').distinct().count()
    pageviews = views.count()
    return {
        'visitors': visitors,
        'new': views.filter(is_new=True).values('visitor').distinct().count(),
        'pageviews': pageviews,
        'car_views': views.filter(kind='car').count(),
        'per_visitor': round(pageviews / visitors, 1) if visitors else 0,
        'contacts': contacts.count(),
        'favorites': events.filter(kind='favorite').count(),
        'contact_rate': round(100 * contacting / car_viewers, 1) if car_viewers else 0,
    }


def change(now_value, before):
    if not before:
        return None
    return round(100 * (now_value - before) / before)


def online(now=None):
    now = now or timezone.now()
    since = now - timedelta(minutes=ONLINE_MINUTES)
    present = Presence.objects.filter(last_seen__gte=since)
    ids = set(present.values_list('visitor', flat=True))
    ids |= set(PageView.objects.filter(created_at__gte=since).values_list('visitor', flat=True))
    pages = (present.values('path').annotate(n=Count('visitor')).order_by('-n')[:10])
    devices = dict(present.values_list('device').annotate(n=Count('visitor')))
    return {'count': len(ids), 'pages': list(pages), 'devices': devices}


def _bucket_key(moment, step):
    local = timezone.localtime(moment).replace(tzinfo=None, second=0, microsecond=0)
    if step in ('hour', 'day', 'month'):
        local = local.replace(minute=0)
    if step in ('day', 'month'):
        local = local.replace(hour=0)
    if step == 'month':
        local = local.replace(day=1)
    return local


def chart(period, filters):
    views = views_between(period.start, period.end, filters)
    rows = views.annotate(b=period.trunc()).values('b').annotate(
        visitors=Count('visitor', distinct=True), pageviews=Count('id'))
    by_bucket = {_bucket_key(r['b'], period.step): r for r in rows}
    labels, visitors, pageviews = [], [], []
    for moment in period.buckets():
        row = by_bucket.get(_bucket_key(moment, period.step), {})
        labels.append(period.label(moment))
        visitors.append(row.get('visitors', 0))
        pageviews.append(row.get('pageviews', 0))
    return {'labels': labels, 'visitors': visitors, 'pageviews': pageviews}


def breakdown(views, field, limit=10, label=None):
    total = views.values('visitor').distinct().count() or 1
    rows = (views.exclude(**{field: ''}).values(field)
            .annotate(visitors=Count('visitor', distinct=True), views=Count('id'))
            .order_by('-visitors', '-views')[:limit])
    result = []
    for r in rows:
        value = r[field]
        result.append({'value': value, 'label': label(value) if label else value, 'visitors': r['visitors'],
                       'views': r['views'], 'share': round(100 * r['visitors'] / total)})
    return result


def sources(views, limit=12):
    """Visitors by where they came from; those with no outside link are 'Direct'."""
    total = views.values('visitor').distinct().count() or 1
    rows = list(views.exclude(source='').values('source')
                .annotate(visitors=Count('visitor', distinct=True), views=Count('id')).order_by('-visitors')[:limit])
    sourced = views.exclude(source='').values('visitor').distinct().count()
    direct = max(total - sourced, 0) if views.exists() else 0
    result = [{'value': r['source'], 'label': r['source'], 'visitors': r['visitors'], 'views': r['views'],
               'share': round(100 * r['visitors'] / total)} for r in rows]
    if direct:
        result.append({'value': 'direct', 'label': _('Direct (typed address, bookmarks, apps)'),
                       'visitors': direct, 'views': None, 'share': round(100 * direct / total)})
    return sorted(result, key=lambda r: -r['visitors'])


def country_name(code):
    return f'{flag(code)} {countries.name(code) or code}'


def flag(code):
    return ''.join(chr(0x1F1E6 + ord(c) - 65) for c in (code or '').upper() if 'A' <= c <= 'Z')


CAR_SORTS = {
    'views': ('-views', '-visitors'), 'least': ('views', 'visitors'), 'visitors': ('-visitors', '-views'),
    'contacts': ('-contacts', '-views'), 'favorites': ('-favorites', '-views'), 'recent': ('-last_view',),
}


def top_cars(period, filters, sort='views', limit=25):
    """Vehicles with their views in the period: from the most viewed to the ones nobody opens.
    'least' lists every car on the site, including those with no views at all."""
    from cars.models import Car
    views = views_between(period.start, period.end, filters).filter(car=OuterRef('pk'))
    events = events_between(period.start, period.end, filters).filter(car=OuterRef('pk'))

    def count(qs, distinct_field=None):
        expr = Count(distinct_field, distinct=True) if distinct_field else Count('id')
        return Coalesce(Subquery(qs.values('car').annotate(n=expr).values('n')[:1], output_field=IntegerField()),
                        Value(0))

    on_site = Car.objects.visible().values('pk')
    viewed = views_between(period.start, period.end, filters).filter(car__isnull=False).values('car')
    base = Car.objects.filter(Q(pk__in=on_site) | Q(pk__in=viewed))
    if filters.get('make'):
        base = base.filter(make__slug=filters['make'])
    cars = (base.select_related('make')
            .annotate(views=count(views), visitors=count(views, 'visitor'),
                      contacts=count(events.filter(kind__in=Event.CONTACTS)),
                      favorites=count(events.filter(kind='favorite')),
                      last_view=Subquery(PageView.objects.filter(car=OuterRef('pk')).values('car')
                                         .annotate(m=Max('created_at')).values('m')[:1]))
            .order_by(*CAR_SORTS.get(sort, CAR_SORTS['views']), '-pk'))
    total = cars.count()
    rows = list(cars[:limit] if limit else cars)
    visible_ids = set(Car.objects.visible().filter(pk__in=[c.pk for c in rows]).values_list('pk', flat=True))
    for car in rows:
        car.on_site = car.pk in visible_ids
        car.contact_rate = round(100 * car.contacts / car.visitors) if car.visitors else 0
    return rows, total


def months(year, filters):
    """Every month of a year: visitors, new visitors, pages, vehicle views, contacts."""
    start = _local_midnight(datetime(year, 1, 1).date())
    end = _local_midnight(datetime(year + 1, 1, 1).date())
    tz = timezone.get_current_timezone()
    views = views_between(start, end, filters).annotate(m=TruncMonth('created_at', tzinfo=tz))
    rows = {timezone.localtime(r['m']).month: r for r in views.values('m').annotate(
        visitors=Count('visitor', distinct=True), pageviews=Count('id'),
        car_views=Count('id', filter=Q(kind='car')))}
    new = {timezone.localtime(r['m']).month: r['n'] for r in views.filter(is_new=True).values('m')
           .annotate(n=Count('visitor', distinct=True))}
    contacts = {timezone.localtime(r['m']).month: r['n'] for r in events_between(start, end, filters)
                .filter(kind__in=Event.CONTACTS).annotate(m=TruncMonth('created_at', tzinfo=tz))
                .values('m').annotate(n=Count('id'))}
    result = []
    for month in range(1, 13):
        r = rows.get(month, {})
        result.append({'month': month, 'start': datetime(year, month, 1), 'visitors': r.get('visitors', 0),
                       'new': new.get(month, 0), 'pageviews': r.get('pageviews', 0),
                       'car_views': r.get('car_views', 0), 'contacts': contacts.get(month, 0)})
    return result
