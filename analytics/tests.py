from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cars.models import Car, Make
from users.models import CustomUser

from . import report, tracking
from .models import Event, PageView, Presence

IPHONE = ('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 '
          '(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1')
DESKTOP = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
           'Chrome/130.0 Safari/537.36')


def make_car(**kwargs):
    return Car.objects.create(source=Car.Source.HOLLMANN, external_id=kwargs.pop('ext', 'A1'),
                              make=Make.get_by_name(kwargs.pop('make', 'Ferrari')), model=kwargs.pop('model', 'Roma'),
                              price=Decimal('100000'), **kwargs)


class TrackingTests(TestCase):
    def setUp(self):
        self.car = make_car()

    def test_vehicle_page_is_recorded_with_details(self):
        self.client.get(f'/ru/vehicle/{self.car.pk}/', HTTP_USER_AGENT=IPHONE,
                        HTTP_REFERER='https://www.google.com/search?q=ferrari', HTTP_X_REAL_IP='1.2.3.4')
        view = PageView.objects.get()
        self.assertEqual((view.kind, view.car_id, view.lang, view.device, view.browser, view.os),
                         ('car', self.car.pk, 'ru', 'mobile', 'Safari', 'iOS'))
        self.assertEqual((view.source, view.referrer), ('Google', 'google.com'))
        self.assertTrue(view.is_new)
        self.assertNotIn('1.2.3.4', view.visitor)

    def test_same_person_is_one_visitor_and_not_new_again(self):
        for path in ('/ru/', '/ru/vehicles/?utm_source=instagram'):
            self.client.get(path, HTTP_USER_AGENT=DESKTOP, HTTP_X_REAL_IP='5.6.7.8')
        first, second = PageView.objects.order_by('pk')
        self.assertEqual(first.visitor, second.visitor)
        self.assertEqual((first.is_new, second.is_new), (True, False))
        self.assertEqual((first.kind, second.kind, second.source), ('home', 'catalog', 'instagram'))
        self.client.get('/ru/', HTTP_USER_AGENT=DESKTOP, HTTP_X_REAL_IP='9.9.9.9')
        self.assertEqual(PageView.objects.values('visitor').distinct().count(), 2)

    def test_internal_links_are_not_a_source(self):
        self.client.get('/ru/vehicles/', HTTP_USER_AGENT=DESKTOP, HTTP_REFERER='http://testserver/ru/')
        self.assertEqual(PageView.objects.get().source, '')

    def test_bots_staff_admin_json_and_errors_are_not_counted(self):
        self.client.get('/ru/', HTTP_USER_AGENT='Mozilla/5.0 (compatible; Googlebot/2.1)')
        self.client.get('/ru/', HTTP_USER_AGENT='')
        self.client.get('/ru/search/suggest/?q=fer', HTTP_USER_AGENT=DESKTOP)
        self.client.get('/ru/vehicle/999999/', HTTP_USER_AGENT=DESKTOP)
        self.client.get('/ru/', HTTP_USER_AGENT=DESKTOP, HTTP_SEC_PURPOSE='prefetch')
        staff = CustomUser.objects.create_superuser('boss@example.com', 'B', 'O', 'Boss-pass-12345')
        self.client.force_login(staff)
        self.client.get('/ru/', HTTP_USER_AGENT=DESKTOP)
        self.client.get(reverse('admin_analytics'), HTTP_USER_AGENT=DESKTOP)
        self.assertEqual(PageView.objects.count(), 0)

    @override_settings(ANALYTICS_DISABLED=True)
    def test_can_be_switched_off(self):
        self.client.get('/ru/', HTTP_USER_AGENT=DESKTOP)
        self.assertEqual(PageView.objects.count(), 0)

    def test_ping_marks_the_visitor_online(self):
        url = reverse('analytics_ping')
        self.client.post(url, {'path': '/ru/', 'car': str(self.car.pk)}, HTTP_USER_AGENT=IPHONE,
                         HTTP_SEC_FETCH_SITE='same-origin')
        presence = Presence.objects.get()
        self.assertEqual((presence.path, presence.car_id, presence.device), ('/ru/', self.car.pk, 'mobile'))
        self.client.post(url, {'path': '/ru/vehicles/'}, HTTP_USER_AGENT=IPHONE, HTTP_SEC_FETCH_SITE='same-origin')
        self.assertEqual(Presence.objects.get().path, '/ru/vehicles/')     # updated, not duplicated
        self.client.post(url, {'path': '/x/'}, HTTP_USER_AGENT=DESKTOP, HTTP_SEC_FETCH_SITE='cross-site')
        self.assertEqual(Presence.objects.count(), 1)                       # other sites cannot ping
        self.assertEqual(report.online()['count'], 1)

    def test_contact_clicks_are_counted_for_real_cars_only(self):
        url = reverse('analytics_event')
        same = {'HTTP_USER_AGENT': IPHONE, 'HTTP_SEC_FETCH_SITE': 'same-origin'}
        self.client.post(url, {'kind': 'whatsapp', 'car': self.car.pk}, **same)
        self.client.post(url, {'kind': 'whatsapp', 'car': 999999}, **same)
        self.client.post(url, {'kind': 'hack', 'car': self.car.pk}, **same)
        self.client.post(url, {'kind': 'phone', 'car': self.car.pk}, HTTP_USER_AGENT=IPHONE, HTTP_ORIGIN='https://evil.example')
        self.assertEqual(list(Event.objects.values_list('kind', 'car_id')), [('whatsapp', self.car.pk)])

    def test_saving_to_favorites_is_an_event(self):
        self.client.post(reverse('cars:favorite', args=[self.car.pk]), HTTP_USER_AGENT=DESKTOP)
        self.assertEqual(Event.objects.get().kind, 'favorite')

    def test_parse_agent_and_sources(self):
        self.assertEqual(tracking.parse_agent(DESKTOP), ('desktop', 'Chrome', 'Windows'))
        self.assertEqual(tracking.parse_agent('Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) Safari/604.1')[0], 'tablet')
        request = RequestFactory().get('/', HTTP_REFERER='https://l.instagram.com/?u=x')
        self.assertEqual(tracking.source_of(request), ('Instagram', 'l.instagram.com'))
        request = RequestFactory().get('/', HTTP_REFERER='https://t.me/fibonaccicars')
        self.assertEqual(tracking.source_of(request)[0], 'Telegram')

    def test_country_is_empty_without_the_database(self):
        with override_settings(MEDIA_ROOT='/tmp/fibonacci-no-geoip'):
            self.assertEqual(tracking.country_of('8.8.8.8'), '')

    def test_cleanup_deletes_old_rows(self):
        old = timezone.now() - timedelta(days=900)
        PageView.objects.create(created_at=old, visitor='a', path='/', kind='home')
        PageView.objects.create(created_at=timezone.now(), visitor='a', path='/', kind='home')
        Presence.objects.create(visitor='b', last_seen=old, path='/')
        call_command('analytics_cleanup', stdout=StringIO())
        self.assertEqual(PageView.objects.count(), 1)
        self.assertEqual(Presence.objects.count(), 0)


class DashboardTests(TestCase):
    def setUp(self):
        self.popular = make_car(ext='P', model='Purosangue')
        self.quiet = make_car(ext='Q', model='Roma', make='Porsche')
        now = timezone.now()
        for i in range(5):
            PageView.objects.create(created_at=now - timedelta(minutes=i), visitor=f'v{i}', is_new=True,
                                    path=f'/ru/vehicle/{self.popular.pk}/', kind='car', car=self.popular,
                                    device='mobile' if i < 3 else 'desktop', country='DE', lang='ru',
                                    source='Google' if i == 0 else '')
        PageView.objects.create(created_at=now - timedelta(days=40), visitor='old', is_new=True, path='/ru/', kind='home')
        Event.objects.create(created_at=now, visitor='v0', kind='whatsapp', car=self.popular)
        self.admin = CustomUser.objects.create_superuser('boss@example.com', 'B', 'O', 'Boss-pass-12345')

    def test_totals_and_filters(self):
        period = report.Period({'period': 'today'})
        t = report.totals(period.start, period.end, {})
        self.assertEqual((t['visitors'], t['pageviews'], t['car_views'], t['contacts']), (5, 5, 5, 1))
        self.assertEqual(t['contact_rate'], 20.0)
        self.assertEqual(report.totals(period.start, period.end, {'device': 'mobile'})['visitors'], 3)
        self.assertEqual(report.totals(period.start, period.end, {'source': 'direct'})['visitors'], 4)
        self.assertEqual(report.totals(period.start, period.end, {'make': 'porsche'})['visitors'], 0)

    def test_cars_from_most_to_least_viewed_include_unviewed(self):
        period = report.Period({'period': '30d'})
        most, total = report.top_cars(period, {}, 'views')
        self.assertEqual([c.pk for c in most], [self.popular.pk, self.quiet.pk])
        self.assertEqual((most[0].views, most[0].visitors, most[0].contacts, most[1].views), (5, 5, 1, 0))
        least, _ = report.top_cars(period, {}, 'least')
        self.assertEqual(least[0].pk, self.quiet.pk)

    def test_chart_has_every_hour_of_today(self):
        data = report.chart(report.Period({'period': 'today'}), {})
        self.assertEqual(len(data['labels']), 24)
        self.assertEqual(sum(data['visitors']), 5)
        year = report.chart(report.Period({'period': 'year'}), {})
        self.assertEqual(len(year['labels']), 12)

    def test_months_of_the_year(self):
        rows = report.months(timezone.now().year, {})
        self.assertEqual(len(rows), 12)
        self.assertGreaterEqual(sum(r['visitors'] for r in rows), 5)

    def test_page_opens_for_every_period_and_filter(self):
        self.client.force_login(self.admin)
        url = reverse('admin_analytics')
        for query in ('', 'period=realtime', 'period=hour', 'period=yesterday', 'period=7d', 'period=30d',
                      'period=month&month=2026-01', 'period=year&year=2025', 'period=custom&from=2026-01-01&to=2026-02-01',
                      'period=30d&device=mobile&country=DE&source=Google&lang=ru&kind=car&visitor=new&member=no'
                      '&make=ferrari&sort=least&cars=all', 'period=month&month=garbage'):
            response = self.client.get(f'{url}?{query}')
            self.assertEqual(response.status_code, 200, query)
        response = self.client.get(f'{url}?period=today')
        self.assertContains(response, 'Purosangue')
        self.assertEqual(self.client.get(f'{url}?online=1').json()['count'], 2)  # viewed in the last 2 minutes

    def test_only_staff_can_open_it(self):
        user = CustomUser.objects.create_user('u@example.com', 'U', 'S', 'User-pass-12345')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('admin_analytics')).status_code, 302)
