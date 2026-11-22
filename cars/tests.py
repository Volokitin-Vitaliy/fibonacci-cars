from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from unittest import mock

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from cars.importers.hollmann import (HollmannImporter, parse_detail, parse_offers,
                                     parse_price, specs_to_fields)
from cars.models import Car, Category, Favorite, ListingPeriod, Make, Payment
from cars import payments, services
from cars.services import expire_listings, send_expiry_reminders
from users.models import CustomUser

LANG = {settings.LANGUAGE_COOKIE_NAME: 'en'}


def offer_html(ext_id, make, model, gross, net):
    return f'''
    <a class="offer" href="/vehicle/{ext_id}/">
      <img src="x.jpg"><div>
        <div class="manufacturer">{make}</div><div class="model">{model}</div>
        <div class="gross-price">Gross: €{gross}</div>
        <div class="net-price">Net (Export): €{net}</div>
      </div>
    </a>'''


def listing_page(*offers):
    return f'<main><div class="offers">{"".join(offers)}</div></main>'


DETAIL = '''
<div class="details"><table>
  <tr><td>Offer Number</td><td>T1</td></tr>
  <tr><td>Color</td><td><div class="color"></div>Obsidian Black <code>197</code></td></tr>
  <tr><td>Mileage</td><td>1,250 km</td></tr>
  <tr><td>Transmission</td><td>Automatic</td></tr>
  <tr><td>Drive</td><td>Combustion Engine <br>(Petrol)</td></tr>
  <tr><td>Power <br>(PS)</td><td>472 PS</td></tr>
  <tr><td>CO₂ Emissions <br>(combined)</td><td>247 g/km<span class="footnote">¹</span></td></tr>
</table></div>'''


class ParserTests(TestCase):
    def test_parse_price(self):
        self.assertEqual(parse_price('Gross: €168,980.00'), (Decimal('168980.00'), 'EUR'))
        self.assertEqual(parse_price('$1,000'), (Decimal('1000'), 'USD'))
        self.assertEqual(parse_price('on request'), (None, None))

    def test_parse_offers(self):
        offers = parse_offers(listing_page(offer_html('T1', 'Mercedes-Benz', 'G 63', '100,000.00', '84,000.00')),
                              'https://hollmann.international/')
        self.assertEqual(offers, [{
            'external_id': 'T1', 'url': 'https://hollmann.international/vehicle/T1/',
            'make': 'Mercedes-Benz', 'model': 'G 63', 'price': Decimal('100000.00'),
            'price_net': Decimal('84000.00'), 'currency': 'EUR',
        }])

    def test_parse_detail_and_fields(self):
        specs = parse_detail(DETAIL)
        self.assertIn(['Power (PS)', '472 PS'], specs)
        self.assertIn(['Drive', 'Combustion Engine (Petrol)'], specs)
        self.assertIn(['CO₂ Emissions (combined)', '247 g/km'], specs)  # footnote removed
        self.assertEqual(specs_to_fields(specs), {
            'mileage_km': 1250, 'power_hp': 472, 'transmission': 'automatic',
            'fuel': 'petrol', 'color': 'Obsidian Black',
        })


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, pages):
        self.pages = pages
        self.headers = {}

    def get(self, url, timeout=None):
        path = url.replace('https://hollmann.international/', '')
        return FakeResponse(self.pages.get(path, listing_page()))


class ImporterTests(TestCase):
    def run_import(self, pages):
        return HollmannImporter(session=FakeSession(pages), delay=0).run()

    def test_import_creates_updates_and_unpublishes(self):
        pages = {
            'vehicles/': listing_page(offer_html('T1', 'Porsche', '911 GT3', '200,000.00', '168,000.00'),
                                      offer_html('T2', 'Brand New Make', 'X', '50,000.00', '42,000.00')),
            'vehicle-collection/2/': listing_page(offer_html('T1', 'Porsche', '911 GT3', '1', '1')),
            'new/': listing_page(offer_html('T2', 'Brand New Make', 'X', '1', '1')),
            'vehicle/T1/': DETAIL,
        }
        run = self.run_import(pages)
        self.assertTrue(run.ok)
        self.assertEqual((run.created, run.updated), (2, 0))
        t1 = Car.objects.get(external_id='T1')
        self.assertEqual(t1.make.name, 'Porsche')
        self.assertEqual(t1.price, Decimal('200000.00'))
        self.assertEqual(t1.power_hp, 472)
        self.assertEqual(list(t1.categories.values_list('slug', flat=True)), ['armoured'])
        self.assertTrue(Car.objects.get(external_id='T2').is_new)
        self.assertTrue(Make.objects.filter(name='Brand New Make').exists())

        # Next day T2 is gone from the source site and T1's price changed.
        pages['vehicles/'] = listing_page(offer_html('T1', 'Porsche', '911 GT3', '190,000.00', '159,000.00'))
        run = self.run_import(pages)
        self.assertEqual((run.created, run.updated, run.unpublished), (0, 1, 1))
        self.assertEqual(Car.objects.get(external_id='T1').price, Decimal('190000.00'))
        self.assertFalse(Car.objects.visible().filter(external_id='T2').exists())

    def test_empty_listing_page_fails_without_unpublishing(self):
        Car.objects.create(source=Car.Source.HOLLMANN, external_id='OLD', make=Make.get_by_name('Audi'),
                           model='R8', price=1)
        with self.assertRaises(RuntimeError):
            self.run_import({'vehicles/': '<html>maintenance</html>'})
        self.assertTrue(Car.objects.get(external_id='OLD').is_published)


def make_user(email='seller@example.com', phone='+49 151 0000001'):
    return CustomUser.objects.create_user(email, 'Ivan', 'Petrov', 'Sup3r-secret-pw', phone=phone,
                                          country='DE')


def make_listing(owner, **kwargs):
    car = Car.objects.create(source=Car.Source.USER, owner=owner, make=Make.get_by_name('BMW'),
                             model='M5', price=Decimal('90000'), contact_name='Ivan',
                             contact_phone='+49 151 0000001', status=Car.Status.INACTIVE, **kwargs)
    car.activate()
    return car


def png():
    buf = BytesIO()
    Image.new('RGB', (40, 30), 'red').save(buf, 'PNG')
    return SimpleUploadedFile('p.png', buf.getvalue(), content_type='image/png')


@override_settings(MEDIA_ROOT='/tmp/fibonacci-test-media')
class ListingLifecycleTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.cookies.load(LANG)
        self.client.force_login(self.user)

    def test_listing_is_active_for_a_month_then_hidden(self):
        car = make_listing(self.user)
        self.assertEqual((car.active_until - car.activated_at).days, 30)
        self.assertEqual(car.days_left, 30)
        self.assertTrue(Car.objects.visible().filter(pk=car.pk).exists())
        self.assertEqual(ListingPeriod.objects.filter(car=car).count(), 1)

        # A month later the listing is hidden immediately, even before the daily job runs.
        Car.objects.filter(pk=car.pk).update(active_until=timezone.now() - timedelta(minutes=1))
        self.assertFalse(Car.objects.visible().filter(pk=car.pk).exists())
        self.assertEqual(expire_listings(), 1)
        car.refresh_from_db()
        self.assertEqual(car.status, Car.Status.INACTIVE)

        # Stays inactive until the owner reactivates it manually.
        self.assertEqual(expire_listings(), 0)
        self.client.post(reverse('cars:activate', args=[car.pk]))
        car.refresh_from_db()
        self.assertTrue(car.is_listing_active)
        self.assertEqual(ListingPeriod.objects.filter(car=car).count(), 2)

    @override_settings(LISTING_PAYMENT_REQUIRED=True)
    def test_activation_blocked_when_payment_required(self):
        car = make_listing(self.user)
        car.deactivate()
        self.client.post(reverse('cars:activate', args=[car.pk]))
        car.refresh_from_db()
        self.assertFalse(car.is_listing_active)

    def test_create_listing_from_cabinet(self):
        category = Category.objects.get(slug='electric')
        response = self.client.post(reverse('cars:add'), {
            'make': Make.get_by_name('Tesla').pk, 'model': 'Model S Plaid', 'category': category.pk,
            'description': 'Like new', 'year': 2023, 'mileage_km': 12000, 'fuel': 'electric',
            'transmission': 'automatic', 'power_hp': 1020, 'color': 'White', 'price': '79000',
            'currency': 'USD', 'contact_name': 'Ivan Petrov', 'contact_phone': '+49 151 0000001',
            'photos': [png(), png()],
        })
        car = Car.objects.get(model='Model S Plaid')
        self.assertRedirects(response, car.get_absolute_url())
        self.assertEqual(car.owner, self.user)
        self.assertEqual(car.currency, 'USD')
        self.assertEqual(car.price_eur, Decimal('72680.00'))  # 79000 * 0.92
        # Waits for moderation: not public, no month started yet.
        self.assertTrue(car.is_pending)
        self.assertFalse(Car.objects.visible().filter(pk=car.pk).exists())
        services.approve(car)
        car.refresh_from_db()
        self.assertTrue(car.is_listing_active)
        self.assertEqual(car.days_left, 30)
        self.assertEqual(list(car.categories.all()), [category])
        self.assertEqual(car.photos.count(), 2)
        page = self.client.get(car.get_absolute_url())
        self.assertContains(page, '$79,000')
        self.assertContains(page, 'Ivan Petrov')

    def test_contact_name_and_phone_are_required(self):
        response = self.client.post(reverse('cars:add'), {
            'make': Make.get_by_name('Audi').pk, 'model': 'A6', 'price': '1000', 'currency': 'EUR',
            'category': Category.objects.first().pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Car.objects.filter(model='A6').exists())
        self.assertIn('contact_name', response.context['form'].errors)
        self.assertIn('contact_phone', response.context['form'].errors)

    def test_cannot_manage_someone_elses_listing(self):
        other = make_listing(make_user('other@example.com', '+49 151 0000002'))
        self.assertEqual(self.client.post(reverse('cars:delete', args=[other.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('cars:edit', args=[other.pk])).status_code, 404)

    def test_inactive_listing_visible_only_to_owner(self):
        car = make_listing(self.user)
        car.deactivate()
        self.assertEqual(self.client.get(car.get_absolute_url()).status_code, 200)
        self.client.logout()  # also clears cookies
        self.client.cookies.load(LANG)
        self.assertEqual(self.client.get(car.get_absolute_url()).status_code, 404)


class FavoriteTests(TestCase):
    def test_toggle_and_list_favorites(self):
        user = make_user()
        car = make_listing(make_user('other@example.com', '+49 151 0000002'))
        self.client.cookies.load(LANG)
        self.client.force_login(user)
        self.client.post(reverse('cars:favorite', args=[car.pk]))
        self.assertTrue(Favorite.objects.filter(user=user, car=car).exists())
        self.assertContains(self.client.get(reverse('cars:favorites')), 'M5')
        self.client.post(reverse('cars:favorite', args=[car.pk]))
        self.assertFalse(Favorite.objects.filter(user=user, car=car).exists())

    def test_favorites_require_login(self):
        self.client.cookies.load(LANG)
        response = self.client.get(reverse('cars:favorites'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('users:login'), response['Location'])


class LanguageTests(TestCase):
    def test_first_visit_shows_language_choice(self):
        response = self.client.get('/en/vehicles/')
        self.assertRedirects(response, '/choose-language/?next=%2Fen%2Fvehicles%2F',
                             fetch_redirect_response=False)
        page = self.client.get(response['Location'])
        self.assertContains(page, 'Русский')

    def test_choosing_russian_translates_the_site(self):
        response = self.client.post('/i18n/setlang/', {'language': 'ru', 'next': '/en/vehicles/'})
        self.assertEqual(response['Location'], '/ru/vehicles/')
        page = self.client.get('/ru/vehicles/')
        self.assertContains(page, 'Все автомобили')
        self.assertContains(page, 'Бронированные')


class RegistrationTests(TestCase):
    def setUp(self):
        self.client.cookies.load(LANG)

    def test_register_with_profile_fields(self):
        response = self.client.post(reverse('users:register'), {
            'last_name': 'Petrov', 'first_name': 'Ivan', 'middle_name': 'Sergeevich',
            'email': 'Ivan@Example.com', 'phone': '+7 999 123-45-67', 'country': 'RU',
            'password1': 'Sup3r-secret-pw', 'password2': 'Sup3r-secret-pw',
        })
        self.assertRedirects(response, reverse('cars:my_cars'))
        user = CustomUser.objects.get(email='ivan@example.com')
        self.assertEqual((user.phone, user.country.code), ('+7 999 123-45-67', 'RU'))
        self.assertEqual(user.full_name, 'Petrov Ivan Sergeevich')

    def test_phone_and_country_required(self):
        response = self.client.post(reverse('users:register'), {
            'last_name': 'Petrov', 'first_name': 'Ivan', 'email': 'a@example.com',
            'password1': 'Sup3r-secret-pw', 'password2': 'Sup3r-secret-pw',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('phone', response.context['form'].errors)
        self.assertIn('country', response.context['form'].errors)


@override_settings(MEDIA_ROOT='/tmp/fibonacci-test-media', MODERATION_EMAILS=['mod@example.com'])
class ModerationTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.user.language = 'ru'
        self.user.save()
        self.client.cookies.load(LANG)
        self.client.force_login(self.user)

    def create(self):
        self.client.post(reverse('cars:add'), {
            'make': Make.get_by_name('Audi').pk, 'model': 'RS6', 'price': '100000', 'currency': 'EUR',
            'category': Category.objects.first().pk, 'contact_name': 'Ivan',
            'contact_phone': '+49 151 0000001',
        })
        return Car.objects.get(model='RS6')

    def test_new_listing_notifies_moderators_and_waits(self):
        car = self.create()
        self.assertTrue(car.is_pending)
        self.assertEqual(mail.outbox[-1].to, ['mod@example.com'])
        # Owner cannot activate before approval.
        self.client.post(reverse('cars:activate', args=[car.pk]))
        car.refresh_from_db()
        self.assertFalse(car.is_listing_active)

    def test_approve_starts_month_and_emails_owner_in_their_language(self):
        car = self.create()
        CustomUser.objects.filter(pk=self.user.pk).update(language='ru')  # last used the Russian site
        car.refresh_from_db()
        services.approve(car)
        car.refresh_from_db()
        self.assertTrue(car.is_listing_active)
        self.assertEqual(mail.outbox[-1].to, [self.user.email])
        self.assertIn('одобрено', mail.outbox[-1].subject)

    def test_reject_with_reason(self):
        car = self.create()
        CustomUser.objects.filter(pk=self.user.pk).update(language='ru')
        car.refresh_from_db()
        services.reject(car, 'Нет фотографий')
        car.refresh_from_db()
        self.assertTrue(car.is_rejected)
        self.assertIn('Нет фотографий', mail.outbox[-1].body)
        self.assertIn('не прошло', mail.outbox[-1].subject)
        page = self.client.get(reverse('cars:my_cars'))
        self.assertContains(page, 'Нет фотографий')

    def test_editing_approved_listing_sends_it_back_to_review_keeping_its_period(self):
        car = make_listing(self.user)
        until = car.active_until
        self.client.post(reverse('cars:edit', args=[car.pk]), {
            'make': car.make.pk, 'model': 'M5 Competition', 'price': '95000', 'currency': 'EUR',
            'category': Category.objects.first().pk, 'contact_name': 'Ivan',
            'contact_phone': '+49 151 0000001',
        })
        car.refresh_from_db()
        self.assertTrue(car.is_pending)
        self.assertFalse(Car.objects.visible().filter(pk=car.pk).exists())
        services.approve(car)
        car.refresh_from_db()
        self.assertEqual(car.active_until, until)
        self.assertTrue(Car.objects.visible().filter(pk=car.pk).exists())

    def test_admin_approve_action(self):
        car = self.create()
        admin = CustomUser.objects.create_superuser('admin@example.com', 'A', 'B', 'pw-123456789')
        self.client.force_login(admin)
        self.client.post(reverse('admin:cars_car_changelist'), {
            'action': 'approve_selected', '_selected_action': [car.pk]})
        car.refresh_from_db()
        self.assertTrue(car.is_approved)
        self.assertTrue(car.is_listing_active)

    @override_settings(LISTING_MODERATION=False)
    def test_without_moderation_listing_goes_live(self):
        car = self.create()
        self.assertTrue(car.is_listing_active)


class ReminderTests(TestCase):
    def test_one_reminder_three_days_before_expiry(self):
        user = make_user()
        soon = make_listing(user)
        later = make_listing(user)
        Car.objects.filter(pk=soon.pk).update(active_until=timezone.now() + timedelta(days=2, hours=12))
        self.assertEqual(send_expiry_reminders(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(str(soon), mail.outbox[0].subject)
        self.assertEqual(send_expiry_reminders(), 0)  # only once per period
        # Reactivating starts a new period with a new reminder.
        soon.refresh_from_db()
        soon.activate()
        self.assertIsNone(Car.objects.get(pk=soon.pk).reminder_sent_at)
        self.assertNotEqual(later.pk, soon.pk)


class FilterTests(TestCase):
    def setUp(self):
        self.client.cookies.load(LANG)
        owner = make_user()
        self.cheap_old = make_listing(owner, year=2005, mileage_km=200000)
        Car.objects.filter(pk=self.cheap_old.pk).update(price=Decimal('15000'), price_eur=Decimal('15000'))
        self.usd = make_listing(owner, year=2022, mileage_km=10000)
        self.usd.price, self.usd.currency, self.usd.model = Decimal('100000'), 'USD', 'USD car'
        self.usd.save()

    def ids(self, **params):
        response = self.client.get(reverse('cars:list'), params)
        return {c.pk for c in response.context['page']}

    def test_filters(self):
        self.assertEqual(self.ids(year_min=2010), {self.usd.pk})
        self.assertEqual(self.ids(mileage_max=50000), {self.usd.pk})
        self.assertEqual(self.ids(price_max=20000), {self.cheap_old.pk})
        # $100,000 = €92,000 with the default rate
        self.assertEqual(self.ids(price_min=91000, price_max=93000), {self.usd.pk})
        self.assertEqual(self.ids(price_min='abc'), {self.usd.pk, self.cheap_old.pk})


class FakeSessionObj(dict):
    def __getattr__(self, key):
        return self[key]


@override_settings(LISTING_PAYMENT_REQUIRED=True, STRIPE_SECRET_KEY='sk_test_x',
                   STRIPE_WEBHOOK_SECRET='whsec_x')
class PaymentTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.cookies.load(LANG)
        self.client.force_login(self.user)
        self.car = make_listing(self.user)
        self.car.deactivate()

    @mock.patch('cars.payments.stripe.checkout.Session.create')
    def test_activation_redirects_to_stripe_checkout(self, create):
        create.return_value = FakeSessionObj(id='cs_test_1', url='https://checkout.stripe.com/c/cs_test_1')
        response = self.client.post(reverse('cars:activate', args=[self.car.pk]))
        self.assertRedirects(response, 'https://checkout.stripe.com/c/cs_test_1', fetch_redirect_response=False)
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs['line_items'][0]['price_data']['unit_amount'], 500)
        self.assertEqual(kwargs['line_items'][0]['price_data']['currency'], 'eur')
        self.assertEqual(kwargs['metadata']['car_id'], str(self.car.pk))
        self.assertEqual(Payment.objects.get().status, Payment.Status.PENDING)
        self.car.refresh_from_db()
        self.assertFalse(self.car.is_listing_active)

    def paid_session(self):
        Payment.objects.create(car=self.car, user=self.user, amount=Decimal('5.00'),
                               stripe_session_id='cs_test_2')
        return {'id': 'cs_test_2', 'payment_status': 'paid'}

    @mock.patch('cars.payments.stripe.Webhook.construct_event')
    def test_webhook_activates_once(self, construct):
        session = self.paid_session()
        construct.return_value = {'type': 'checkout.session.completed', 'data': {'object': session}}
        url = reverse('stripe_webhook')
        self.assertEqual(self.client.post(url, b'{}', content_type='application/json',
                                          HTTP_STRIPE_SIGNATURE='sig').status_code, 200)
        self.client.post(url, b'{}', content_type='application/json', HTTP_STRIPE_SIGNATURE='sig')
        self.car.refresh_from_db()
        self.assertTrue(self.car.is_listing_active)
        period = ListingPeriod.objects.filter(car=self.car).first()
        self.assertEqual((period.amount, period.method), (Decimal('5.00'), 'stripe'))
        self.assertEqual(ListingPeriod.objects.filter(car=self.car, method='stripe').count(), 1)

    @mock.patch('cars.payments.stripe.Webhook.construct_event', side_effect=ValueError('bad sig'))
    def test_webhook_rejects_bad_signature(self, construct):
        response = self.client.post(reverse('stripe_webhook'), b'{}', content_type='application/json')
        self.assertEqual(response.status_code, 400)

    @mock.patch('cars.payments.stripe.checkout.Session.retrieve')
    def test_success_page_activates_if_webhook_is_late(self, retrieve):
        retrieve.return_value = self.paid_session()
        self.client.get(reverse('cars:payment_success'), {'session_id': 'cs_test_2'})
        self.car.refresh_from_db()
        self.assertTrue(self.car.is_listing_active)

    @override_settings(STRIPE_SECRET_KEY=None)
    def test_without_keys_shows_error(self):
        self.client.post(reverse('cars:activate', args=[self.car.pk]))
        self.car.refresh_from_db()
        self.assertFalse(self.car.is_listing_active)


class SeoTests(TestCase):
    def test_bots_skip_language_picker(self):
        page = self.client.get('/ru/vehicles/', HTTP_USER_AGENT='Mozilla/5.0 (compatible; Googlebot/2.1)')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Все автомобили')
        self.assertContains(page, 'hreflang="en" href="http://testserver/en/vehicles/"')

    def test_people_still_get_the_picker(self):
        page = self.client.get('/ru/vehicles/', HTTP_USER_AGENT='Mozilla/5.0 (iPhone) Safari')
        self.assertEqual(page.status_code, 302)

    def test_robots_and_sitemap(self):
        make_listing(make_user())
        robots = self.client.get('/robots.txt')
        self.assertContains(robots, 'Sitemap: http://testserver/sitemap.xml')
        self.assertContains(robots, 'Disallow: /en/cabinet/')
        sitemap = self.client.get('/sitemap.xml')
        self.assertContains(sitemap, '/ru/vehicle-collection/armoured/')
        self.assertContains(sitemap, '/en/vehicles/')

    def test_user_language_follows_the_site(self):
        user = make_user()
        self.client.force_login(user)
        self.client.cookies.load({settings.LANGUAGE_COOKIE_NAME: 'ru'})
        self.client.get('/ru/')
        user.refresh_from_db()
        self.assertEqual(user.language, 'ru')
