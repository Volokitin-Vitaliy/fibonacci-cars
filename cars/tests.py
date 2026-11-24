import re
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

from cars.importers.hollmann import (HollmannImporter, detect_fuel, parse_detail, parse_offers,
                                     parse_price, specs_to_fields)
from cars.models import Car, Favorite, ListingPeriod, Make, Payment
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

    def test_detect_fuel(self):
        self.assertEqual(detect_fuel('Plugin Hybrid (Petrol/Electricity)'), 'hybrid')
        self.assertEqual(detect_fuel('Electric Motor (Electricity)'), 'electric')
        self.assertEqual(detect_fuel('Combustion Engine (Diesel)'), 'diesel')
        self.assertEqual(detect_fuel('Combustion Engine (Petrol)'), 'petrol')
        self.assertEqual(detect_fuel('Combustion Engine (LPG)'), 'gas')
        self.assertEqual(detect_fuel(''), '')


class FakeResponse:
    def __init__(self, text, content=b''):
        self.text = text
        self.content = content

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, pages):
        self.pages = pages
        self.headers = {}
        self.downloads = []

    def get(self, url, timeout=None):
        if 'cache.hollmann.international' in url:
            self.downloads.append(url)
            buf = BytesIO()
            Image.new('RGBA' if 'employee' in url else 'RGB', (1600, 1200), (200, 0, 0, 255)).save(buf, 'PNG')
            return FakeResponse('', buf.getvalue())
        path = url.replace('https://hollmann.international/', '')
        return FakeResponse(self.pages.get(path, listing_page()))


class ImporterTests(TestCase):
    def run_import(self, pages):
        return HollmannImporter(session=FakeSession(pages), delay=0).run()

    def test_import_creates_updates_and_unpublishes(self):
        pages = {
            'vehicles/': listing_page(offer_html('T1', 'Porsche', '911 GT3', '200,000.00', '168,000.00'),
                                      offer_html('T2', 'Brand New Make', 'X', '50,000.00', '42,000.00')),
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
        self.assertEqual(t1.fuel, 'petrol')
        self.assertTrue(Car.objects.get(external_id='T2').is_new)
        self.assertEqual(t1.country.code, 'DE')
        self.assertTrue(Make.objects.filter(name='Brand New Make').exists())

        # Next day T2 is gone from the source site and T1's price changed.
        pages['vehicles/'] = listing_page(offer_html('T1', 'Porsche', '911 GT3', '190,000.00', '159,000.00'))
        run = self.run_import(pages)
        self.assertEqual((run.created, run.updated, run.unpublished), (0, 1, 1))
        self.assertEqual(Car.objects.get(external_id='T1').price, Decimal('190000.00'))
        self.assertFalse(Car.objects.visible().filter(external_id='T2').exists())

    @override_settings(MEDIA_ROOT='/tmp/fibonacci-test-media', HOLLMANN_MAX_PHOTOS=3, HOLLMANN_PHOTO_WIDTH=800)
    def test_photos_description_and_contacts(self):
        cache = 'https://cache.hollmann.international'
        page = f'''<main><section><div class="strip"><div class="content">
            <img src="{cache}/vehicle/T1/images/1/900/"><img src="{cache}/vehicle/T1/images/2/900/">
            <img src="{cache}/vehicle/T1/images/3/900/"><img src="{cache}/vehicle/T1/images/4/900/">
            </div></div></section>{DETAIL}
            <div class="description"><b onclick="x()">NEW G 63</b><br><script>alert(1)</script>
              <a href="http://evil">link</a> <code>197</code></div>
            <div class="contacts"><div class="contact"><div><img src="{cache}/employee/anna-k/portrait/circle/180/">
              <div><div class="name">Anna K</div><div class="languages">English &amp; Russian</div></div></div>
              <div><a class="phone" href="tel:+491"><div>Phone</div>+49 421 1</a>
              <a class="whatsapp" href="https://wa.me/492"><div>WhatsApp</div>+49 176 2</a></div></div></div>
            </main>'''
        pages = {'vehicles/': listing_page(offer_html('T1', 'Mercedes-Benz', 'G 63', '300,000.00', '252,000.00')),
                 'vehicle/T1/': page}
        session = FakeSession(pages)
        HollmannImporter(session=session, delay=0, photo_delay=0, import_media=True).run()
        car = Car.objects.get(external_id='T1')
        photos = list(car.photos.order_by('position'))
        self.assertEqual(len(photos), 3)  # HOLLMANN_MAX_PHOTOS
        with Image.open(photos[0].image.path) as img:
            self.assertEqual((img.format, img.width), ('JPEG', 800))
        html = car.description_html
        self.assertIn('<b>NEW G 63</b>', html)
        self.assertIn('<code>197</code>', html)
        for bad in ('script', 'alert', 'onclick', 'href', '<a'):
            self.assertNotIn(bad, html)
        self.assertEqual(car.dealer_contacts, [{
            'name': 'Anna K', 'languages': 'English & Russian', 'phone': '+49 421 1', 'mobile': '',
            'whatsapp': '+49 176 2', 'photo': 'hollmann/staff/anna-k.jpg'}])

        # Next day: same photos are not downloaded again, a removed photo is deleted.
        session.downloads.clear()
        pages['vehicle/T1/'] = page.replace(f'<img src="{cache}/vehicle/T1/images/2/900/">', '')
        HollmannImporter(session=session, delay=0, photo_delay=0, import_media=True).run()
        self.assertEqual([u.split('/images/')[1] for u in session.downloads], ['4/900/'])
        self.assertEqual(car.photos.count(), 3)

        # Sold: the car disappears from their site -> hidden here, photos deleted.
        path = car.photos.first().image.path
        pages['vehicles/'] = listing_page(offer_html('T9', 'Audi', 'R8', '1.00', '1.00'))
        HollmannImporter(session=session, delay=0, photo_delay=0, import_media=True).run()
        car.refresh_from_db()
        self.assertFalse(car.is_published)
        self.assertEqual(car.photos.count(), 0)
        import os
        self.assertFalse(os.path.exists(path))

        self.client.cookies.load(LANG)
        self.assertEqual(self.client.get(car.get_absolute_url()).status_code, 404)

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
        response = self.client.post(reverse('cars:add'), {'photos': png(),
            'make': Make.get_by_name('Tesla').pk, 'model': 'Model S Plaid',
            'description': 'Like new', 'year': 2023, 'mileage_km': 12000, 'fuel': 'electric',
            'transmission': 'automatic', 'power_hp': 1020, 'color': 'White', 'price': '79000',
            'currency': 'USD', 'accident': 'False', 'contact_name': 'Ivan Petrov', 'contact_phone': '+49 151 0000001', 'country': 'DE',
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
        self.assertEqual(car.fuel, 'electric')
        self.assertEqual(car.photos.count(), 2)
        page = self.client.get(car.get_absolute_url())
        self.assertContains(page, '$79,000')
        self.assertContains(page, 'Ivan Petrov')

    def test_contact_name_and_phone_are_required(self):
        response = self.client.post(reverse('cars:add'), {'photos': png(),
            'make': Make.get_by_name('Audi').pk, 'model': 'A6', 'price': '1000', 'currency': 'EUR', 'accident': 'False',
            'fuel': 'petrol',
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

    def test_guest_favorites_kept_in_session_and_moved_on_login(self):
        self.client.cookies.load(LANG)
        owner = make_user('owner@example.com', '+49 151 0000003')
        car1, car2 = make_listing(owner), make_listing(owner)
        response = self.client.post(reverse('cars:favorite', args=[car1.pk]),
                                    HTTP_X_REQUESTED_WITH='fetch')
        self.assertEqual(response.json(), {'favorite': True, 'count': 1})
        self.client.post(reverse('cars:favorite', args=[car2.pk]))
        page = self.client.get(reverse('cars:favorites'))
        self.assertEqual([c.pk for c in page.context['cars']], [car2.pk, car1.pk])
        self.assertContains(page, '30 days')
        self.assertEqual(Favorite.objects.count(), 0)
        # Guest session lasts 30 days and is extended on every visit.
        self.assertEqual(settings.SESSION_COOKIE_AGE, 60 * 60 * 24 * 30)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)

        user = make_user('guest@example.com', '+49 151 0000004')
        self.client.post(reverse('users:login'), {'username': user.email, 'password': 'Sup3r-secret-pw'})
        self.assertEqual(set(user.favorites.values_list('car_id', flat=True)), {car1.pk, car2.pk})
        self.assertEqual(len(self.client.get(reverse('cars:favorites')).context['cars']), 2)

    def test_guest_toggle_off_and_hidden_cars_skipped(self):
        self.client.cookies.load(LANG)
        car = make_listing(make_user())
        self.client.post(reverse('cars:favorite', args=[car.pk]))
        self.client.post(reverse('cars:favorite', args=[car.pk]))
        self.assertEqual(self.client.get(reverse('cars:favorites')).context['cars'], [])
        self.client.post(reverse('cars:favorite', args=[car.pk]))
        car.deactivate()
        self.assertEqual(self.client.get(reverse('cars:favorites')).context['cars'], [])

    def test_bottom_menu_on_every_page(self):
        self.client.cookies.load(LANG)
        for url in (reverse('cars:home'), reverse('cars:list'), reverse('users:login')):
            page = self.client.get(url)
            self.assertContains(page, 'aria-label="Main menu"')
            self.assertContains(page, reverse('cars:add'))
        self.assertContains(self.client.get(reverse('cars:list')), 'bn-item bn-active', count=1)


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
        self.assertContains(page, 'Дизель')


class RegistrationTests(TestCase):
    def setUp(self):
        self.client.cookies.load(LANG)

    def test_register_with_profile_fields(self):
        response = self.client.post(reverse('users:register'), {
            'last_name': 'Petrov', 'first_name': 'Ivan',
            'email': 'Ivan@Example.com', 'country': 'DE',
            'password1': 'Sup3r-secret-pw', 'password2': 'Sup3r-secret-pw',
        })
        self.assertRedirects(response, reverse('users:verify_sent'))
        user = CustomUser.objects.get(email='ivan@example.com')
        self.assertEqual((user.phone, user.country.code), (None, 'DE'))
        self.assertEqual(user.full_name, 'Petrov Ivan')
        from users.forms import RegistrationForm
        self.assertNotIn('middle_name', RegistrationForm().fields)

    def test_email_must_be_confirmed(self):
        from django.core import mail
        self.client.post(reverse('users:register'), {
            'last_name': 'Petrov', 'first_name': 'Ivan', 'email': 'ivan@example.com', 'country': 'DE',
            'password1': 'Sup3r-secret-pw', 'password2': 'Sup3r-secret-pw',
        })
        user = CustomUser.objects.get(email='ivan@example.com')
        self.assertTrue(user.awaits_verification)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(len(mail.outbox), 1)
        # Logging in before confirming explains what to do.
        page = self.client.post(reverse('users:login'), {'username': 'ivan@example.com',
                                                        'password': 'Sup3r-secret-pw'})
        self.assertContains(page, 'Please confirm your email first')
        wrong = self.client.post(reverse('users:login'), {'username': 'ivan@example.com',
                                                         'password': 'wrong-password'})
        self.assertNotContains(wrong, 'Please confirm your email first')
        # The link activates the account and signs in; it works only once.
        link = re.search(r'https?://\S+/verify/\S+/', mail.outbox[0].body).group(0)
        path = link.split('testserver', 1)[1]
        self.assertRedirects(self.client.get(path), reverse('cars:my_cars'))
        user.refresh_from_db()
        self.assertTrue(user.is_active and user.email_verified)
        self.client.logout()
        self.client.cookies.load(LANG)
        again = self.client.get(path)
        self.assertEqual(again.status_code, 400, again.get("Location"))

    def test_resend_link_is_limited(self):
        from django.core import mail
        from django.core.cache import cache
        cache.clear()
        user = CustomUser.objects.create_user('p@example.com', 'P', 'Q', 'Sup3r-secret-pw', is_active=False)
        for _ in range(3):
            self.client.post(reverse('users:verify_sent'), {'email': 'p@example.com'})
        self.client.post(reverse('users:verify_sent'), {'email': 'nobody@example.com'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [user.email])

    def test_login_is_locked_after_five_wrong_passwords(self):
        CustomUser.objects.create_user('lock@example.com', 'L', 'K', 'Right-pass-123', email_verified=True)
        for _ in range(5):
            self.client.post(reverse('users:login'), {'username': 'lock@example.com', 'password': 'nope'})
        page = self.client.post(reverse('users:login'), {'username': 'lock@example.com',
                                                        'password': 'Right-pass-123'})
        self.assertEqual(page.status_code, 429)
        self.assertContains(page, 'Too many attempts', status_code=429)
        self.assertNotIn('_auth_user_id', self.client.session)
        # Another account from the same address is not affected.
        CustomUser.objects.create_user('ok@example.com', 'O', 'K', 'Right-pass-123', email_verified=True)
        ok = self.client.post(reverse('users:login'), {'username': 'ok@example.com', 'password': 'Right-pass-123'})
        self.assertEqual(ok.status_code, 302)

    @override_settings(TURNSTILE_SITE_KEY='site-key', TURNSTILE_SECRET_KEY='secret')
    def test_captcha_blocks_bots_at_signup(self):
        data = {'last_name': 'Bot', 'first_name': 'Bot', 'email': 'bot@example.com', 'country': 'DE',
                'password1': 'Sup3r-secret-pw', 'password2': 'Sup3r-secret-pw'}
        page = self.client.get(reverse('users:register'))
        self.assertContains(page, 'data-sitekey="site-key"')
        response = self.client.post(reverse('users:register'), data)  # no token
        self.assertContains(response, 'not a robot')
        self.assertFalse(CustomUser.objects.filter(email='bot@example.com').exists())
        with mock.patch('users.captcha.requests.post') as post:
            post.return_value.json.return_value = {'success': False}
            self.client.post(reverse('users:register'), {**data, 'cf-turnstile-response': 'fake'})
            self.assertFalse(CustomUser.objects.filter(email='bot@example.com').exists())
            post.return_value.json.return_value = {'success': True}
            response = self.client.post(reverse('users:register'), {**data, 'cf-turnstile-response': 'ok'})
            self.assertRedirects(response, reverse('users:verify_sent'))
            self.assertEqual(post.call_args.kwargs['data']['secret'], 'secret')

    def test_robots_does_not_reveal_admin(self):
        self.assertNotContains(self.client.get('/robots.txt'), 'admin')

    def test_social_login_takes_over_unconfirmed_account(self):
        from users.adapters import SocialAccountAdapter
        user = CustomUser.objects.create_user('v@example.com', 'V', 'W', 'attacker-pw-123', is_active=False)
        login = mock.Mock(user=user)
        SocialAccountAdapter().pre_social_login(None, login)
        user.refresh_from_db()
        self.assertTrue(user.is_active and user.email_verified)
        self.assertFalse(user.check_password('attacker-pw-123'))
        # A confirmed account that an admin switched off stays off.
        banned = CustomUser.objects.create_user('b@example.com', 'B', 'C', 'pw-12345678', is_active=False,
                                                email_verified=True)
        SocialAccountAdapter().pre_social_login(None, mock.Mock(user=banned))
        banned.refresh_from_db()
        self.assertFalse(banned.is_active)

    def test_russia_is_not_offered(self):
        page = self.client.get(reverse('users:register'))
        self.assertNotContains(page, 'value="RU"')
        self.assertContains(page, 'value="DE"')
        response = self.client.post(reverse('users:register'), {
            'last_name': 'Petrov', 'first_name': 'Ivan', 'email': 'b@example.com', 'country': 'RU',
            'password1': 'Sup3r-secret-pw', 'password2': 'Sup3r-secret-pw',
        })
        self.assertIn('country', response.context['form'].errors)

    def test_phone_is_not_asked_at_signup(self):
        page = self.client.get(reverse('users:register'))
        self.assertNotIn('phone', page.context['form'].fields)
        response = self.client.post(reverse('users:register'), {
            'last_name': 'Petrov', 'first_name': 'Ivan', 'email': 'a@example.com',
            'password1': 'Sup3r-secret-pw', 'password2': 'Sup3r-secret-pw',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('country', response.context['form'].errors)

    def test_no_social_buttons_without_keys(self):
        page = self.client.get(reverse('users:login'))
        self.assertNotContains(page, 'Continue with Google')

    @override_settings(SOCIALACCOUNT_PROVIDERS={
        'google': {'APP': {'client_id': 'gid', 'secret': 'gsecret'}},
        'apple': {'APP': {'client_id': 'com.example.web', 'secret': 'KEYID', 'key': 'TEAMID',
                          'settings': {'certificate_key': 'x'}}},
    })
    def test_social_buttons_with_keys(self):
        page = self.client.get(reverse('users:register'))
        self.assertContains(page, 'Continue with Google')
        self.assertContains(page, 'Continue with Apple')
        redirect = self.client.get('/accounts/google/login/?process=login')
        self.assertEqual(redirect.status_code, 302)
        self.assertTrue(redirect['Location'].startswith('https://accounts.google.com/'))
        self.assertIn('client_id=gid', redirect['Location'])

    def test_google_signup_creates_user_with_name(self):
        from allauth.socialaccount.models import SocialAccount, SocialLogin
        from django.test import RequestFactory
        from users.adapters import SocialAccountAdapter
        request = RequestFactory().get('/')
        account = SocialAccount(provider='google', uid='1',
                                extra_data={'given_name': 'Anna', 'family_name': 'Ivanova'})
        login = SocialLogin(account=account, user=CustomUser())
        user = SocialAccountAdapter().populate_user(request, login, {'email': 'Anna@Gmail.com'})
        self.assertEqual((user.first_name, user.last_name, user.email),
                         ('Anna', 'Ivanova', 'anna@gmail.com'))


@override_settings(MEDIA_ROOT='/tmp/fibonacci-test-media')
class ContactTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.cookies.load(LANG)
        self.client.force_login(self.user)

    def post(self, **contacts):
        data = {'make': Make.get_by_name('Audi').pk, 'model': 'Q8', 'price': '1000', 'currency': 'EUR', 'accident': 'False',
                'fuel': 'petrol', 'contact_name': 'Ivan',
                'contact_phone': '+49 151 0000001', 'country': 'DE'}
        data.update(contacts)
        return self.client.post(reverse('cars:add'), {'photos': png(), **data})

    def test_separate_whatsapp_and_telegram(self):
        self.post(contact_whatsapp='+49 151 999 88 77', contact_telegram='https://t.me/ivan_cars')
        car = Car.objects.get(model='Q8')
        self.assertEqual(car.contact_telegram, 'ivan_cars')
        self.assertEqual(car.whatsapp_url, 'https://wa.me/491519998877')
        self.assertEqual(car.telegram_url, 'https://t.me/ivan_cars')
        services.approve(car)
        page = self.client.get(car.get_absolute_url())
        self.assertContains(page, 'href="tel:+491510000001"')
        self.assertContains(page, 'https://wa.me/491519998877')
        self.assertContains(page, '@ivan_cars')

    def test_optional_messengers_hidden_when_empty(self):
        self.post()
        car = Car.objects.get(model='Q8')
        services.approve(car)
        page = self.client.get(car.get_absolute_url())
        self.assertNotContains(page, 'wa.me')
        self.assertNotContains(page, 't.me/')

    def test_telegram_phone_and_validation(self):
        self.post(contact_telegram='+7 999 123 45 67')
        self.assertEqual(Car.objects.get(model='Q8').telegram_url, 'https://t.me/+79991234567')
        response = self.post(contact_telegram='@a!')
        self.assertIn('contact_telegram', response.context['form'].errors)


@override_settings(MEDIA_ROOT='/tmp/fibonacci-test-media')
class LayoutTests(TestCase):
    def setUp(self):
        self.client.cookies.load(LANG)

    def test_home_has_two_actions_and_new_offers(self):
        make_listing(make_user())
        page = self.client.get(reverse('cars:home'))
        self.assertContains(page, 'Choose a car')
        self.assertContains(page, 'Sell a car')
        self.assertContains(page, 'Cars worldwide.')
        self.assertContains(page, 'View all')
        self.assertNotContains(page, 'p-6 h-32')  # collection tiles are gone from the home page
        self.assertContains(page, 'img/logo-96.png')

    def test_category_and_make_are_separate_and_combine(self):
        owner = make_user()
        bmw_diesel = make_listing(owner, fuel='diesel')
        bmw_petrol = make_listing(owner, fuel='petrol')
        audi_diesel = Car.objects.create(source=Car.Source.USER, owner=owner, make=Make.get_by_name('Audi'),
                                         model='A6', price=Decimal('50000'), fuel='diesel',
                                         contact_name='Ivan', contact_phone='+49 151 0000001')
        audi_diesel.activate()

        def ids(url, **params):
            return {c.pk for c in self.client.get(url, params).context['page']}

        self.assertEqual(ids(reverse('cars:list'), fuel='diesel'), {bmw_diesel.pk, audi_diesel.pk})
        self.assertEqual(ids(reverse('cars:list'), make='bmw'), {bmw_diesel.pk, bmw_petrol.pk})
        self.assertEqual(ids(reverse('cars:list'), fuel='diesel', make='bmw'), {bmw_diesel.pk})
        self.assertEqual(ids(reverse('cars:fuel', args=['diesel'])), {bmw_diesel.pk, audi_diesel.pk})
        self.assertEqual(ids(reverse('cars:make', args=['audi'])), {audi_diesel.pk})
        self.assertEqual(self.client.get(reverse('cars:fuel', args=['tuning'])).status_code, 404)

        page = self.client.get(reverse('cars:list'), {'fuel': 'diesel', 'sort': 'price-ascending'})
        # The make picker keeps the category and the sort, and counts within the category.
        self.assertContains(page, '/en/vehicles/?fuel=diesel&amp;sort=price-ascending&amp;make=bmw')
        makes = {o['label']: o['count'] for o in page.context['make_options']}
        self.assertEqual(makes, {'Audi': 1, 'BMW': 1})
        fuels = {o['value']: o['count'] for o in page.context['fuel_options']}
        self.assertEqual((fuels['diesel'], fuels['petrol'], fuels['gas']), (2, 1, 0))

    def test_accident_filter(self):
        owner = make_user()
        clean = make_listing(owner, accident=False)
        damaged = make_listing(owner, accident=True)
        unknown = make_listing(owner)

        def ids(**params):
            return {c.pk for c in self.client.get(reverse('cars:list'), params).context['page']}

        self.assertEqual(ids(accident='no'), {clean.pk})
        self.assertEqual(ids(accident='yes'), {damaged.pk})
        self.assertEqual(ids(), {clean.pk, damaged.pk, unknown.pk})
        page = self.client.get(reverse('cars:list'), {'accident': 'yes'})
        self.assertContains(page, 'After an accident')
        self.assertContains(self.client.get(clean.get_absolute_url()), 'No accidents')

    def test_listing_form_requires_accident_answer(self):
        user = make_user('seller2@example.com', '+49 151 0000009')
        self.client.force_login(user)
        response = self.client.post(reverse('cars:add'), {'photos': png(),
            'make': Make.get_by_name('Audi').pk, 'model': 'S8', 'price': '1000', 'currency': 'EUR',
            'fuel': 'petrol', 'contact_name': 'Ivan', 'contact_phone': '+49 151 0000001', 'country': 'DE'})
        self.assertIn('accident', response.context['form'].errors)
        self.client.post(reverse('cars:add'), {'photos': png(),
            'make': Make.get_by_name('Audi').pk, 'model': 'S8', 'price': '1000', 'currency': 'EUR',
            'fuel': 'petrol', 'accident': 'True', 'contact_name': 'Ivan', 'contact_phone': '+49 151 0000001', 'country': 'DE'})
        self.assertIs(Car.objects.get(model='S8').accident, True)

    def test_all_pickers_are_dropdowns(self):
        page = self.client.get(reverse('cars:list'), {'fuel': 'diesel'})
        content = page.content.decode()
        self.assertEqual(content.count('data-dropdown-button aria-haspopup'), 5)
        self.assertNotIn('<select name="sort"', content)
        self.assertContains(page, '/en/vehicles/?fuel=diesel&amp;sort=price-ascending')
        self.assertContains(page, 'All countries')
        self.assertNotContains(page, 'All sellers')

    def test_mobile_menu_and_partnership(self):
        page = self.client.get(reverse('cars:home'))
        menu = page.content.decode().split('id="mobile-nav"')[1].split('</header>')[0]
        self.assertNotIn('/en/category/', menu)
        for url in (reverse('cars:list'), reverse('cars:new'), reverse('cars:add'),
                    reverse('cars:favorites'), reverse('cars:partnership')):
            self.assertIn(url, menu)
        self.assertLess(menu.index(reverse('cars:favorites')), menu.index(reverse('cars:partnership')))
        self.assertLess(menu.index(reverse('users:register')), menu.index(reverse('cars:partnership')))
        partnership = self.client.get(reverse('cars:partnership'))
        for link in ('https://t.me/fibonaccicars', 'https://www.tiktok.com/@fibonacci_io',
                     'https://www.instagram.com/fibonacci_io', 'https://t.me/fibonacci_io',
                     'mailto:fibonacci.iox@gmail.com'):
            self.assertContains(partnership, link)

    def test_sort_by_date_and_price_only(self):
        page = self.client.get(reverse('cars:list'))
        self.assertNotContains(page, 'name-ascending')
        self.assertContains(page, 'price-ascending')
        self.assertEqual(self.client.get(reverse('cars:list'), {'sort': 'name-ascending'}).context['sort'],
                         'date-descending')

    def test_categories_are_engine_types(self):
        page = self.client.get(reverse('cars:list'))
        labels = [o['label'] for o in page.context['fuel_options']][1:]
        self.assertEqual(labels, ['Combustion (petrol)', 'Diesel', 'Hybrid', 'Electric', 'Gas (LPG/CNG)'])
        self.assertNotContains(page, 'Armoured')
        self.assertNotContains(page, 'Oldtimer')

    def test_favicon(self):
        page = self.client.get(reverse('cars:home'))
        self.assertContains(page, 'favicon.ico')
        self.assertEqual(self.client.get('/favicon.ico').status_code, 301)



@override_settings(MEDIA_ROOT='/tmp/fibonacci-test-media', MODERATION_EMAILS=['mod@example.com'])
class ModerationTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.user.language = 'ru'
        self.user.save()
        self.client.cookies.load(LANG)
        self.client.force_login(self.user)

    def create(self):
        self.client.post(reverse('cars:add'), {'photos': png(),
            'make': Make.get_by_name('Audi').pk, 'model': 'RS6', 'price': '100000', 'currency': 'EUR', 'accident': 'False',
            'fuel': 'petrol', 'contact_name': 'Ivan',
            'contact_phone': '+49 151 0000001', 'country': 'DE',
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
            'make': car.make.pk, 'model': 'M5 Competition', 'price': '95000', 'currency': 'EUR', 'accident': 'False',
            'fuel': 'petrol', 'contact_name': 'Ivan',
            'contact_phone': '+49 151 0000001', 'country': 'DE',
        })
        car.refresh_from_db()
        self.assertTrue(car.is_pending)
        self.assertFalse(Car.objects.visible().filter(pk=car.pk).exists())
        services.approve(car)
        car.refresh_from_db()
        self.assertEqual(car.active_until, until)
        self.assertTrue(Car.objects.visible().filter(pk=car.pk).exists())

    def test_admin_pages_open(self):
        admin = CustomUser.objects.create_superuser('admin@example.com', 'A', 'B', 'pw-123456789')
        car = self.create()
        self.client.force_login(admin)
        for url in (reverse('admin:index'), reverse('admin:cars_car_changelist'),
                    reverse('admin:cars_car_changelist') + '?moderation=pending',
                    reverse('admin:cars_car_change', args=[car.pk]),
                    reverse('admin:users_customuser_changelist'),
                    reverse('admin:users_customuser_change', args=[self.user.pk]),
                    reverse('admin:cars_payment_changelist'), reverse('admin:cars_importrun_changelist'),
                    reverse('admin:socialaccount_socialaccount_changelist'),
                    reverse('admin:auth_group_changelist')):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        dashboard = self.client.get(reverse('admin:index'))
        self.assertContains(dashboard, 'RS6')  # in "waiting for review"

    def test_admin_login_opens_admin(self):
        CustomUser.objects.create_superuser('admin@example.com', 'A', 'B', 'pw-123456789')
        self.assertRedirects(self.client.get('/admin/login/'), '/admin/login/?next=/admin/',
                             fetch_redirect_response=False)
        response = self.client.post('/admin/login/?next=/admin/',
                                    {'username': 'admin@example.com', 'password': 'pw-123456789'})
        self.assertRedirects(response, '/admin/', fetch_redirect_response=False)

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
        self.assertEqual(self.ids(price_max=20000), {self.cheap_old.pk})
        # $100,000 = €92,000 with the default rate
        self.assertEqual(self.ids(price_min=91000, price_max=93000), {self.usd.pk})
        self.assertEqual(self.ids(price_min='abc'), {self.usd.pk, self.cheap_old.pk})

    def test_search(self):
        self.usd.model = 'Cullinan Black Badge'
        self.usd.save()
        self.assertEqual(self.ids(q='cullinan'), {self.usd.pk})
        self.assertEqual(self.ids(q='bmw black'), {self.usd.pk})
        self.assertEqual(self.ids(q='бмв'), {self.usd.pk, self.cheap_old.pk})
        self.assertEqual(self.ids(q='2005'), {self.cheap_old.pk})
        self.assertEqual(self.ids(q='nothing-like-this'), set())
        page = self.client.get(reverse('cars:list'), {'q': 'cullinan'})
        self.assertContains(page, 'Search: cullinan')
        data = self.client.get(reverse('cars:search_suggest'), {'q': 'cull'}).json()
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['results'][0]['title'], 'Cullinan Black Badge')
        self.assertEqual(data['results'][0]['url'], self.usd.get_absolute_url())
        self.assertIn('q=cull', data['all_url'])
        self.assertEqual(self.client.get(reverse('cars:search_suggest'), {'q': 'c'}).json()['total'], 0)

    def test_price_in_dollars(self):
        # $16,000 = €14,720 < €15,000; $17,000 = €15,640 > €15,000
        self.assertEqual(self.ids(price_max=16000, cur='USD'), set())
        self.assertEqual(self.ids(price_max=17000, cur='USD'), {self.cheap_old.pk})
        self.assertEqual(self.ids(price_max='20 000'), {self.cheap_old.pk})

    def test_year_presets_and_no_mileage(self):
        page = self.client.get(reverse('cars:list'))
        self.assertContains(page, 'class="form-field combo"', count=2)
        self.assertContains(page, 'data-value="1970"')
        self.assertContains(page, 'data-value="1985"')
        self.assertNotContains(page, 'mileage_max')
        self.assertContains(page, 'name="cur" value="USD"')

    def test_country_filter_lists_only_countries_with_cars(self):
        Car.objects.filter(pk=self.usd.pk).update(country='AE')
        Car.objects.filter(pk=self.cheap_old.pk).update(country='DE')
        page = self.client.get(reverse('cars:list'))
        self.assertContains(page, '?country=AE')
        self.assertContains(page, '?country=DE')
        self.assertNotContains(page, '?country=FR')
        self.assertEqual(self.ids(country='AE'), {self.usd.pk})
        self.assertEqual(self.ids(country='de'), {self.cheap_old.pk})


class FakeSessionObj(dict):
    def __getattr__(self, key):
        return self[key]


@override_settings(LISTING_PAYMENT_REQUIRED=True, PAYMENT_PROVIDER='stripe', STRIPE_SECRET_KEY='sk_test_x',
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
        self.assertEqual(kwargs['line_items'][0]['price_data']['unit_amount'], 1000)
        self.assertEqual(kwargs['line_items'][0]['price_data']['currency'], 'eur')
        self.assertEqual(kwargs['metadata']['car_id'], str(self.car.pk))
        self.assertEqual(Payment.objects.get().status, Payment.Status.PENDING)
        self.car.refresh_from_db()
        self.assertFalse(self.car.is_listing_active)

    def paid_session(self):
        Payment.objects.create(car=self.car, user=self.user, amount=Decimal('10.00'),
                               provider='stripe', reference='cs_test_2')
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
        self.assertEqual((period.amount, period.method), (Decimal('10.00'), 'stripe'))
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


WFP = dict(LISTING_PAYMENT_REQUIRED=True, PAYMENT_PROVIDER='wayforpay', LISTING_PRICE_EUR='10.00',
           WAYFORPAY_MERCHANT_ACCOUNT='test_merch_n1', WAYFORPAY_SECRET_KEY='flk3409refn54t54t*FNJRET',
           WAYFORPAY_DOMAIN='fibonacci.example', WAYFORPAY_CURRENCY='EUR',
           MEDIA_ROOT='/tmp/fibonacci-test-media')


@override_settings(**WFP)
class WayForPayTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.cookies.load(LANG)
        self.client.force_login(self.user)

    def submit(self):
        return self.client.post(reverse('cars:add'), {'photos': png(),
            'make': Make.get_by_name('Audi').pk, 'model': 'RS7', 'price': '120000', 'currency': 'EUR',
            'accident': 'False', 'fuel': 'petrol', 'contact_name': 'Ivan', 'contact_phone': '+49 151 0000001', 'country': 'DE'})

    def callback(self, payment, status='Approved', amount=None, tamper=False):
        import hashlib, hmac, json
        data = {'merchantAccount': 'test_merch_n1', 'orderReference': payment.reference,
                'amount': amount or str(payment.amount), 'currency': 'EUR', 'authCode': '123456',
                'cardPan': '41****1111', 'transactionStatus': status, 'reasonCode': '1100'}
        msg = ';'.join(data[k] for k in ('merchantAccount', 'orderReference', 'amount', 'currency',
                                         'authCode', 'cardPan', 'transactionStatus', 'reasonCode'))
        data['merchantSignature'] = hmac.new(b'flk3409refn54t54t*FNJRET', msg.encode(), hashlib.md5).hexdigest()
        if tamper:
            data['merchantSignature'] = '0' * 32
        return self.client.post(reverse('wayforpay_callback'), json.dumps(data), content_type='application/json')

    def test_submitting_a_listing_opens_wayforpay_with_signed_form(self):
        import hashlib, hmac
        page = self.submit()
        car = Car.objects.get(model='RS7')
        self.assertEqual(car.moderation, Car.Moderation.AWAITING_PAYMENT)
        self.assertFalse(Car.objects.visible().filter(pk=car.pk).exists())
        self.assertContains(page, 'action="https://secure.wayforpay.com/pay"')
        fields = page.context['fields']
        self.assertEqual((fields['amount'], fields['currency'], fields['merchantDomainName']),
                         ('10.00', 'EUR', 'fibonacci.example'))
        msg = ';'.join(str(fields[k]) for k in ('merchantAccount', 'merchantDomainName', 'orderReference',
                                                 'orderDate', 'amount', 'currency', 'productName[]',
                                                 'productCount[]', 'productPrice[]'))
        expected = hmac.new(b'flk3409refn54t54t*FNJRET', msg.encode(), hashlib.md5).hexdigest()
        self.assertEqual(fields['merchantSignature'], expected)
        self.assertTrue(fields['serviceUrl'].endswith('/payments/wayforpay/callback/'))

    def test_paid_listing_goes_to_review_and_month_starts_on_approval(self):
        self.submit()
        car = Car.objects.get(model='RS7')
        payment = Payment.objects.get(car=car)
        response = self.callback(payment)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'accept')
        self.assertEqual(len(response.json()['signature']), 32)
        self.callback(payment)  # duplicate notification
        car.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual((car.moderation, payment.status), (Car.Moderation.PENDING, Payment.Status.PAID))
        self.assertFalse(car.is_listing_active)

        services.approve(car)
        car.refresh_from_db()
        self.assertTrue(car.is_listing_active)
        self.assertEqual(car.days_left, 30)
        period = car.periods.get()
        self.assertEqual((period.amount, period.method), (Decimal('10.00'), 'wayforpay'))
        payment.refresh_from_db()
        self.assertIsNotNone(payment.used_at)

    def test_rejects_bad_signature_wrong_amount_and_declined(self):
        self.submit()
        payment = Payment.objects.get()
        self.assertEqual(self.callback(payment, tamper=True).status_code, 400)
        self.assertEqual(self.callback(payment, amount='1.00').status_code, 400)
        self.callback(payment, status='Declined')
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.FAILED)
        self.assertEqual(Car.objects.get().moderation, Car.Moderation.AWAITING_PAYMENT)

    def test_return_page_redirects_to_signed_in_page(self):
        self.submit()
        payment = Payment.objects.get()
        self.callback(payment)
        response = self.client.post(reverse('wayforpay_return'), {'orderReference': payment.reference})
        self.assertRedirects(response, reverse('wayforpay_done') + f'?order={payment.reference}',
                             fetch_redirect_response=False)
        done = self.client.get(response['Location'], follow=True)
        self.assertContains(done, 'Payment received')

    def test_reactivation_of_expired_listing_is_paid(self):
        car = make_listing(self.user)
        car.deactivate()
        page = self.client.post(reverse('cars:activate', args=[car.pk]))
        self.assertContains(page, 'secure.wayforpay.com')
        self.callback(Payment.objects.get(car=car))
        car.refresh_from_db()
        self.assertTrue(car.is_listing_active)

    @override_settings(WAYFORPAY_SECRET_KEY='')
    def test_not_configured_keeps_listing_saved(self):
        response = self.submit()
        self.assertRedirects(response, reverse('cars:my_cars'))
        self.assertEqual(Car.objects.get().moderation, Car.Moderation.AWAITING_PAYMENT)


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
        self.assertContains(sitemap, '/ru/category/diesel/')
        self.assertContains(sitemap, '/en/vehicles/')

    def test_user_language_follows_the_site(self):
        user = make_user()
        self.client.force_login(user)
        self.client.cookies.load({settings.LANGUAGE_COOKIE_NAME: 'ru'})
        self.client.get('/ru/')
        user.refresh_from_db()
        self.assertEqual(user.language, 'ru')


class SimilarCarsTests(TestCase):
    def setUp(self):
        self.client.cookies.load(LANG)
        owner = make_user()

        def listing(make, price, fuel='petrol', model='X'):
            car = make_listing(owner, fuel=fuel)
            car.make, car.model, car.price = Make.get_by_name(make), model, Decimal(price)
            car.save()
            return car
        self.car = listing('BMW', 100000)
        self.bmw_close = listing('BMW', 110000)
        self.bmw_far = listing('BMW', 400000)          # more than twice the price
        self.audi_petrol = listing('Audi', 95000)
        self.audi_diesel = listing('Audi', 100000, fuel='diesel')
        self.cheap = listing('Fiat', 10000)             # less than half the price

    def test_similar_cars_by_price_make_and_category(self):
        from cars.views import similar_cars
        ids = [c.pk for c in similar_cars(self.car)]
        self.assertEqual(ids[0], self.bmw_close.pk)            # same make first
        self.assertEqual(ids[1:3], [self.audi_petrol.pk, self.audi_diesel.pk])  # same category first
        self.assertNotIn(self.car.pk, ids)
        self.assertNotIn(self.bmw_far.pk, ids[:3])
        self.assertEqual(len(ids), 4)  # topped up to four with the closest prices

    def test_detail_page_has_gallery_and_similar(self):
        from django.utils import translation
        with translation.override('en'):
            page = self.client.get(self.car.get_absolute_url())
            self.assertContains(page, 'Similar vehicles')
            self.assertContains(page, self.bmw_close.get_absolute_url())
        self.assertNotContains(page, 'hollmann.international')


@override_settings(MEDIA_ROOT='/tmp/fibonacci-test-media')
class DeepFixTests(TestCase):
    def setUp(self):
        self.client.cookies.load(LANG)

    def test_confirmed_account_keeps_password_on_google_sign_in(self):
        from allauth.account.models import EmailAddress
        from allauth.socialaccount.internal.flows.email_authentication import wipe_password
        from django.core import mail
        self.client.post(reverse('users:register'), {
            'last_name': 'P', 'first_name': 'I', 'email': 'keep@example.com', 'country': 'DE',
            'password1': 'Sup3r-secret-pw', 'password2': 'Sup3r-secret-pw'})
        link = re.search(r'https?://\S+/verify/\S+/', mail.outbox[0].body).group(0)
        self.client.get(link.split('testserver', 1)[1])
        user = CustomUser.objects.get(email='keep@example.com')
        self.assertTrue(EmailAddress.objects.filter(user=user, email='keep@example.com', verified=True,
                                                    primary=True).exists())
        wipe_password(None, user, 'keep@example.com')  # what allauth does on Google sign-in
        user.refresh_from_db()
        self.assertTrue(user.check_password('Sup3r-secret-pw'))
        # Accounts made by an admin are confirmed too.
        admin = CustomUser.objects.create_superuser('boss@example.com', 'B', 'S', 'Adm1n-pass-123')
        self.assertTrue(admin.email_verified)
        self.assertTrue(EmailAddress.objects.filter(user=admin, verified=True).exists())

    def test_email_change_needs_confirmation(self):
        from django.core import mail
        user = CustomUser.objects.create_user('old@example.com', 'O', 'L', 'Sup3r-secret-pw')
        self.client.force_login(user)
        self.client.post(reverse('users:account'), {'last_name': 'L', 'first_name': 'O',
                                                    'email': 'new@example.com', 'country': 'DE'})
        user.refresh_from_db()
        self.assertEqual(user.email, 'old@example.com')
        self.assertEqual(mail.outbox[-1].to, ['new@example.com'])
        path = re.search(r'https?://\S+', mail.outbox[-1].body).group(0).split('testserver', 1)[1]
        self.client.get(path)
        user.refresh_from_db()
        self.assertEqual(user.email, 'new@example.com')
        self.assertEqual(self.client.get(path).status_code, 400)  # used once

    def test_uploaded_photo_is_cleaned_resized_and_files_removed_with_it(self):
        import os
        from django.test import TestCase as _T  # noqa: F401
        from PIL import Image as PILImage
        owner = make_user()
        self.client.force_login(owner)
        big = PILImage.new('RGB', (3000, 2000), 'blue')
        exif = PILImage.Exif()
        exif[0x8825] = {2: (55.0, 45.0, 0.0), 4: (37.0, 36.0, 0.0)}  # GPS position
        buf = BytesIO()
        big.save(buf, 'JPEG', exif=exif)
        upload = SimpleUploadedFile('IMG_home_street_5.jpg', buf.getvalue(), content_type='image/jpeg')
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('cars:add'), {
                'photos': upload, 'make': Make.get_by_name('Audi').pk, 'model': 'RS6', 'price': '100000',
                'currency': 'EUR', 'fuel': 'petrol', 'accident': 'False', 'contact_name': 'Ivan',
                'contact_phone': '+49 151 0000001', 'country': 'DE'})
        photo = Car.objects.get(model='RS6').photos.get()
        self.assertNotIn('home_street', photo.image.name)
        with PILImage.open(photo.image.path) as saved:
            self.assertEqual(max(saved.size), 2000)
            self.assertFalse(saved.getexif())
        self.assertEqual(photo.variants, [240, 480, 960, 1600, 2000])
        self.assertIn('-480.webp', photo.small_url)
        files = [photo.image.path] + [os.path.join(os.path.dirname(photo.image.path), 'v', f)
                                      for f in os.listdir(os.path.join(os.path.dirname(photo.image.path), 'v'))]
        self.assertTrue(all(os.path.exists(f) for f in files))
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('cars:delete', args=[photo.car_id]))
        self.assertFalse(any(os.path.exists(f) for f in files))

    def test_new_listing_needs_a_photo(self):
        self.client.force_login(make_user())
        page = self.client.post(reverse('cars:add'), {
            'make': Make.get_by_name('Audi').pk, 'model': 'NoPhoto', 'price': '1000', 'currency': 'EUR',
            'fuel': 'petrol', 'accident': 'False', 'contact_name': 'I', 'contact_phone': '+49 151 0000001',
            'country': 'DE'})
        self.assertContains(page, 'Add at least one photo')
        self.assertFalse(Car.objects.filter(model='NoPhoto').exists())

    def test_branded_404(self):
        page = self.client.get('/en/no-such-page/')
        self.assertEqual(page.status_code, 404)
        self.assertContains(page, 'car was sold', status_code=404)
