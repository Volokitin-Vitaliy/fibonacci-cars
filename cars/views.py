import json
import logging
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Case, Count, F, IntegerField, Prefetch, Q, Value, When
from django.db.models.functions import Abs
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django_countries.fields import Country

from users import captcha

from . import favorites, payments, search, seo, services
from .forms import CarFilterForm, CarForm
from .models import Car, CarPhoto, Make, Payment

SORTS = {
    'date-descending': ('-created_at',),
    'date-ascending': ('created_at',),
    'price-ascending': ('price_eur',),
    'price-descending': ('-price_eur',),
}
logger = logging.getLogger(__name__)
PER_PAGE = 24
ACCIDENT_FILTERS = {'no': False, 'yes': True}


def with_cover(queryset):
    return (queryset.select_related('make')
            .prefetch_related(Prefetch('photos', queryset=CarPhoto.objects.order_by('position', 'id'))))


@csrf_exempt
@require_POST
def telegram_webhook(request):
    """Updates from the Telegram moderation bot (see cars/telegram.py)."""
    from hmac import compare_digest

    from . import telegram
    if not telegram.bot_configured() or not compare_digest(
            request.headers.get('X-Telegram-Bot-Api-Secret-Token', ''), telegram.webhook_secret()):
        return HttpResponse(status=403)
    try:
        update = json.loads(request.body)
    except ValueError:
        return HttpResponseBadRequest()
    try:
        telegram.handle_update(update)
    except Exception:  # answer 200 anyway, or Telegram keeps resending the same update
        logger.exception('Telegram update failed')
    return HttpResponse('ok')


def set_language(request):
    """Django's language switch, made to work when the page's language differs from the
    saved one: '/en/...' is read as an English address even if the cookie says Russian,
    so it is translated to '/ru/...' instead of being sent back unchanged."""
    from urllib.parse import urlsplit

    from django.utils import translation
    from django.views.i18n import set_language as django_set_language

    page_language = translation.get_language_from_path(urlsplit(request.POST.get('next') or '').path)
    if not page_language:
        return django_set_language(request)
    with translation.override(page_language):  # only for this request, never leaks to the next
        return django_set_language(request)


def choose_language(request):
    next_url = request.GET.get('next') or '/'
    if not url_has_allowed_host_and_scheme(next_url, {request.get_host()}):
        next_url = '/'
    return render(request, 'choose_language.html', {'next': next_url})


def home(request):
    from . import partnership

    visible = Car.objects.visible()
    new_offers = list(with_cover(Car.objects.new_offers()).order_by('-created_at')[:10])
    latest = [] if new_offers else list(with_cover(visible).order_by('-created_at')[:10])
    # Hero: the most impressive cars that have photos.
    hero_cars = list(with_cover(visible.filter(photos__isnull=False).distinct())
                     .order_by('-price_eur')[:5])
    top_makes = (Make.objects.annotate(n=Count('cars', filter=Q(cars__in=visible)))
                 .filter(n__gt=0).order_by('-n', 'name')[:8])
    return render(request, 'cars/home.html', {
        'structured_data': seo.site_data(request),
        'new_offers': new_offers, 'latest': latest, 'hero_cars': hero_cars,
        'top_makes': top_makes,
        'stats': {'vehicles': visible.count(), 'makes': Make.objects.filter(cars__in=visible).distinct().count()},
        'social': [l for l in partnership.LINKS if not l[3]], 'followers': partnership.FOLLOWERS,
    })


def car_list(request, make_slug=None, fuel=None, new=False):
    """Catalog. Fuel types and gearboxes are multi-choice (checkboxes), make is a single
    choice; all combine with each other and with the filters, e.g. diesel + PHEV + BMW."""
    base = Car.objects.new_offers() if new else Car.objects.visible()
    base_url = reverse('cars:new') if new else reverse('cars:list')

    fuels = [f for f in request.GET.getlist('fuel') if f in Car.Fuel.values]
    if fuel:  # /category/<fuel>/ pages
        if fuel not in Car.Fuel.values:
            raise Http404
        fuels.insert(0, fuel)
    fuels = list(dict.fromkeys(fuels))
    transmissions = list(dict.fromkeys(t for t in request.GET.getlist('transmission')
                                       if t in Car.Transmission.values))
    make_slug = make_slug or request.GET.get('make', '')
    make = get_object_or_404(Make, slug=make_slug) if make_slug else None

    country = request.GET.get('country', '').upper()
    accident = request.GET.get('accident', '')
    if accident not in ACCIDENT_FILTERS:
        accident = ''
    if accident:
        base = base.filter(accident=ACCIDENT_FILTERS[accident])
    query = ' '.join(request.GET.get('q', '').split())[:100]
    if query:
        base = search.search(base, query)
    filters = CarFilterForm(request.GET or None)
    base = filters.apply(base)

    def narrow(qs, skip=None):
        """Apply the fuel / gearbox / make choices, except `skip` (for its own counts)."""
        if fuels and skip != 'fuel':
            qs = qs.filter(fuel__in=fuels)
        if transmissions and skip != 'transmission':
            qs = qs.filter(transmission__in=transmissions)
        if make and skip != 'make':
            qs = qs.filter(make=make)
        return qs

    def counts(qs, field):
        return dict(qs.order_by().values_list(field).annotate(n=Count('pk', distinct=True)))

    # Countries offered in the picker: only those with cars matching the other choices.
    country_counts = counts(narrow(base).exclude(country=''), 'country')
    if country not in country_counts:
        country = ''
    if country:
        base = base.filter(country=country)

    sort = request.GET.get('sort', 'date-descending')
    if sort not in SORTS:
        sort = 'date-descending'
    cars = with_cover(narrow(base).distinct()).order_by(*SORTS[sort], '-pk')
    page = Paginator(cars, PER_PAGE).get_page(request.GET.get('page'))

    # Links and forms keep everything else that is selected.
    params = request.GET.copy()
    params.pop('page', None)
    params.setlist('fuel', fuels)
    params.setlist('transmission', transmissions)
    params['make'] = make.slug if make else ''
    params['sort'] = '' if sort == 'date-descending' else sort

    def pairs(query, exclude=()):
        return [(k, v) for k in query for v in query.getlist(k) if v and k not in exclude]

    def link(**changes):
        query = params.copy()
        for key, value in changes.items():
            query[key] = value
        items = pairs(query)
        return base_url + ('?' + urlencode(items) if items else '')

    def multi_picker(name, label, choices, selected, own_counts):
        chosen = [str(lbl) for value, lbl in choices if value in selected]
        summary = chosen[0] + (f' +{len(chosen) - 1}' if len(chosen) > 1 else '') if chosen else _('Any')
        return {
            'name': name, 'label': label, 'summary': summary, 'selected': bool(chosen),
            # Only choices that have cars (or are already ticked).
            'options': [{'value': value, 'label': lbl, 'checked': value in selected,
                         'count': own_counts.get(value, 0)} for value, lbl in choices
                        if own_counts.get(value) or value in selected],
            'hidden': pairs(params, exclude=(name,)), 'reset_href': link(**{name: ''}),
        }

    fuel_picker = multi_picker('fuel', _('Fuel'), Car.Fuel.choices, fuels,
                               counts(narrow(base, skip='fuel'), 'fuel'))
    transmission_picker = multi_picker('transmission', _('Gearbox'), Car.Transmission.choices, transmissions,
                                       counts(narrow(base, skip='transmission'), 'transmission'))
    make_counts = counts(narrow(base, skip='make'), 'make')
    # Only makes that have cars (the full list is in the listing form).
    shown_makes = Make.objects.filter(Q(pk__in=make_counts) | Q(pk=make.pk if make else None)).order_by('name')
    make_options = [{'value': m.slug, 'label': m.name, 'href': link(make=m.slug), 'logo': m.logo_url,
                     'active': make == m, 'count': make_counts.get(m.pk, 0)} for m in shown_makes]

    def options(key, current, choices):
        return [{'value': value, 'label': label, 'href': link(**{key: value}),
                 'active': current == value} for value, label in choices]

    accident_options = options('accident', accident, [
        ('', _('Any')), ('no', _('No accidents')), ('yes', _('After an accident'))])
    country_options = options('country', country, [('', _('All countries'))] + sorted(
        ((code, Country(code).name) for code in country_counts), key=lambda c: str(c[1])))
    sort_options = options('sort', sort, [
        ('date-descending', _('Newest first')), ('date-ascending', _('Oldest first')),
        ('price-ascending', _('Price: low to high')), ('price-descending', _('Price: high to low'))])

    title = _('New Offers') if new else _('All Vehicles')
    if query:
        title = _('Search: %(query)s') % {'query': query}
    elif make or len(fuels) == 1:
        title = ' · '.join(str(x) for x in (make.name if make else '',
                                            Car.Fuel(fuels[0]).label if len(fuels) == 1 else '') if x)
    return render(request, 'cars/list.html', {
        'page': page, 'title': title, 'sort': sort, 'is_new': new, 'country': country, 'query': query,
        'filters': filters, 'make': make, 'base_url': base_url,
        'fuel_picker': fuel_picker, 'transmission_picker': transmission_picker,
        'make_options': make_options,
        'all_makes_href': link(make=''),
        'accident': accident, 'accident_options': accident_options,
        'country_options': country_options, 'sort_options': sort_options,
        'filter_hidden': pairs(params, exclude=('price_min', 'price_max', 'cur', 'year_min', 'year_max')),
        'any_filter': bool(fuels or transmissions or make or country or accident or query
                           or filters.active_count),
    })


def search_suggest(request):
    """Instant search results for the search box (JSON)."""
    query = ' '.join(request.GET.get('q', '').split())[:100]
    if len(query) < 2:
        return JsonResponse({'results': [], 'total': 0})
    found = search.search(Car.objects.visible(), query)
    cars = with_cover(found).order_by('-is_new', '-created_at', '-pk')[:6]
    results = []
    for car in cars:
        cover = car.cover
        results.append({
            'title': car.model, 'make': car.make.name, 'year': car.year,
            'price': f'{car.currency_symbol}{car.main_price:,.0f}' if car.main_price else '',
            'url': car.get_absolute_url(),
            'image': cover.thumb_url if cover else '',
        })
    return JsonResponse({
        'results': results, 'total': found.count(),
        'all_url': reverse('cars:list') + '?' + urlencode({'q': query}),
    })


def similar_cars(car, limit=8):
    """Cars a buyer of this one would also look at: close in price, preferring the same
    make, then the same category. Up to half the list comes from the same make."""
    others = with_cover(Car.objects.visible().exclude(pk=car.pk))
    if not car.price_eur:
        return list(others.filter(make=car.make).order_by('-created_at')[:limit])
    price = car.price_eur
    in_range = others.filter(price_eur__gte=price / 2, price_eur__lte=price * 2)
    by_price = Abs(F('price_eur') - price)
    same_make = list(in_range.filter(make=car.make).annotate(diff=by_price).order_by('diff')[:limit // 2])
    taken = [c.pk for c in same_make]
    rest = in_range.exclude(pk__in=taken).exclude(make=car.make).annotate(
        diff=by_price, same_fuel=Case(When(fuel=car.fuel, then=1), default=0, output_field=IntegerField()))
    if not car.fuel:
        rest = rest.annotate(same_fuel=Value(0, output_field=IntegerField()))
    result = same_make + list(rest.order_by('-same_fuel', 'diff')[:limit - len(same_make)])
    if len(result) < 4:  # rare or very expensive cars: fill with the closest prices overall
        result += list(others.exclude(pk__in=[c.pk for c in result]).annotate(diff=by_price)
                       .order_by('diff')[:4 - len(result)])
    return result


def car_detail(request, pk):
    car = get_object_or_404(with_cover(Car.objects.all()), pk=pk)
    is_owner = request.user.is_authenticated and car.owner_id == request.user.id
    is_public = Car.objects.visible().filter(pk=pk).exists()
    if not is_public and not is_owner:
        raise Http404
    photos = list(car.photos.all())
    price = f'{car.currency_symbol}{car.main_price:,.0f}' if car.main_price else ''
    message = _('Hello! I am interested in %(car)s%(year)s%(price)s on FIBONACCI: %(url)s') % {
        'car': f'{car.make.name} {car.model}', 'year': f', {car.year}' if car.year else '',
        'price': f', {price}' if price else '', 'url': request.build_absolute_uri(car.get_absolute_url())}
    return render(request, 'cars/detail.html', {
        'structured_data': seo.car_data(request, car, photos) if is_public else None,
        'wa_query': 'text=' + quote(message, safe=''),
        'car': car, 'photos': photos, 'similar': similar_cars(car),
        'photo_urls_json': json.dumps([p.large_url for p in photos]),
        'photo_main_json': json.dumps([p.url_for(1600) for p in photos]),
        'photo_thumbs_json': json.dumps([p.thumb_url for p in photos]),
        'is_owner': is_owner,
    })


@require_POST
def toggle_favorite(request, pk):
    """Works for guests too (kept in the session for 30 days)."""
    car = get_object_or_404(Car, pk=pk)
    is_favorite = favorites.toggle(request, car)
    if request.headers.get('X-Requested-With') == 'fetch':
        return JsonResponse({'favorite': is_favorite,
                             'count': len(favorites.favorite_ids(request))})
    next_url = request.POST.get('next')
    if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()}):
        return redirect(next_url)
    return redirect(car)


def favorites_page(request):
    cars = favorites.favorite_cars(request)
    template = 'cars/cabinet/favorites.html' if request.user.is_authenticated else 'cars/favorites_guest.html'
    return render(request, template, {'cars': cars, 'section': 'favorites'})


# --- Cabinet -------------------------------------------------------------

@login_required
def my_cars(request):
    cars = with_cover(request.user.cars.all()).order_by('-created_at')
    return render(request, 'cars/cabinet/my_cars.html', {
        'cars': cars, 'section': 'cars',
        'payment_required': settings.LISTING_PAYMENT_REQUIRED,
        'listing_price': payments.price(),
        'duration': settings.LISTING_DURATION_DAYS,
        'moderation': settings.LISTING_MODERATION,
    })


@login_required
def car_create(request):
    phone = request.user.phone or ''
    initial = {'contact_name': request.user.full_name, 'contact_phone': phone,
               'contact_whatsapp': phone, 'country': str(request.user.country or '')}
    form = CarForm(request.POST or None, request.FILES or None, initial=initial)
    if request.method == 'POST' and form.is_valid() and captcha.check(request, form):
        form.instance.owner = request.user
        form.instance.source = Car.Source.USER
        form.instance.status = Car.Status.INACTIVE
        if settings.LISTING_PAYMENT_REQUIRED:
            form.instance.moderation = Car.Moderation.AWAITING_PAYMENT
            car = form.save()
            return _start_payment(request, car)
        car = form.save()
        if services.submit_for_review(car):
            messages.success(request, _('Thank you! Your listing has been sent for review. We will email you once it is approved.'))  # noqa: E501
        else:
            car.activate()
            messages.success(request, _('Your listing is published for %(days)s days.')
                             % {'days': settings.LISTING_DURATION_DAYS})
        return redirect(car)
    return render(request, 'cars/cabinet/car_form.html', {
        'form': form, 'section': 'add', 'duration': settings.LISTING_DURATION_DAYS,
        'moderation': settings.LISTING_MODERATION,
        'payment_required': settings.LISTING_PAYMENT_REQUIRED, 'listing_price': payments.price()})


def _own_car(request, pk):
    return get_object_or_404(Car, pk=pk, owner=request.user, source=Car.Source.USER)


@login_required
def car_edit(request, pk):
    car = _own_car(request, pk)
    form = CarForm(request.POST or None, request.FILES or None, instance=car)
    if request.method == 'POST' and form.is_valid():
        form.save()
        remove = request.POST.getlist('remove_photo')
        if remove:
            car.photos.filter(pk__in=remove).delete()
        if car.moderation == Car.Moderation.AWAITING_PAYMENT:
            messages.success(request, _('Listing updated.'))
        elif services.submit_for_review(car):
            messages.success(request, _('Listing updated and sent for review.'))
        else:
            messages.success(request, _('Listing updated.'))
        return redirect('cars:my_cars')
    return render(request, 'cars/cabinet/car_form.html', {
        'form': form, 'car': car, 'photos': car.photos.all(), 'section': 'cars',
    })


@login_required
@require_POST
def car_delete(request, pk):
    _own_car(request, pk).delete()
    messages.success(request, _('Listing deleted.'))
    return redirect('cars:my_cars')


@login_required
@require_POST
def car_activate(request, pk):
    car = _own_car(request, pk)
    if car.is_listing_active:
        messages.info(request, _('This listing is already active.'))
    elif car.moderation == Car.Moderation.AWAITING_PAYMENT:
        return _start_payment(request, car)
    elif not car.is_approved:
        messages.error(request, _('The listing can be activated after it has been approved.'))
    elif settings.LISTING_PAYMENT_REQUIRED:
        return _start_payment(request, car)
    else:
        car.activate()
        messages.success(request, _('Listing activated for %(days)s days.')
                         % {'days': settings.LISTING_DURATION_DAYS})
    return redirect('cars:my_cars')


@login_required
@require_POST
def car_deactivate(request, pk):
    car = _own_car(request, pk)
    car.deactivate()
    messages.success(request, _('Listing deactivated.'))
    return redirect('cars:my_cars')


def _start_payment(request, car):
    try:
        return payments.start(request, car)
    except payments.PaymentsNotConfigured:
        messages.error(request, _('Online payment is not available yet. Your listing is saved.'))
    except Exception:
        messages.error(request, _('The payment could not be started. Please try again later.'))
    return redirect('cars:my_cars')


def _payment_message(request, payment):
    if payment is None:
        messages.error(request, _('We could not confirm the payment.'))
    elif payment.status == Payment.Status.PAID:
        car = payment.car
        if car and car.is_listing_active:
            messages.success(request, _('Payment received. Your listing is active for %(days)s days.')
                             % {'days': settings.LISTING_DURATION_DAYS})
        else:
            messages.success(request, _('Payment received. Your listing has been sent for review; the paid month starts when it is approved.'))  # noqa: E501
    elif payment.status == Payment.Status.FAILED:
        messages.error(request, _('The payment was not completed. You can try again from your cabinet.'))
    else:
        messages.info(request, _('We are waiting for the payment confirmation. Your listing will be activated in a moment.'))  # noqa: E501


@login_required
def payment_success(request):
    """Stripe redirects here after checkout."""
    session_id = request.GET.get('session_id', '')
    payment = Payment.objects.filter(reference=session_id, user=request.user).first()
    if payment is None:
        return redirect('cars:my_cars')
    if payment.status != Payment.Status.PAID:
        try:
            payments.stripe_fulfill(payments.retrieve_session(session_id))
        except Exception:
            pass
        payment.refresh_from_db()
    _payment_message(request, payment)
    return redirect('cars:my_cars')


@csrf_exempt
@require_POST
def stripe_webhook(request):
    try:
        event = payments.parse_webhook(request.body, request.headers.get('Stripe-Signature', ''))
    except payments.PaymentsNotConfigured:
        return HttpResponse(status=503)
    except Exception:
        return HttpResponseBadRequest()
    session = event['data']['object']
    if event['type'] in ('checkout.session.completed', 'checkout.session.async_payment_succeeded'):
        payments.stripe_fulfill(session)
    elif event['type'] in ('checkout.session.expired', 'checkout.session.async_payment_failed'):
        payments.fulfill(session['id'], paid=False)
    return HttpResponse(status=200)


@csrf_exempt
@require_POST
def wayforpay_callback(request):
    """serviceUrl: WayForPay reports the result here (server to server)."""
    data = payments.parse_callback_body(request.body)
    payment = payments.wayforpay_process(data)
    if payment is None:
        return HttpResponseBadRequest()
    return JsonResponse(payments.wayforpay_answer(payment.reference))


@csrf_exempt
def wayforpay_return(request):
    """returnUrl: WayForPay posts the result here when the buyer comes back.
    That cross-site POST carries no session cookie, so record the result and
    continue with a normal GET where the user is signed in again."""
    data = request.POST.dict() if request.method == 'POST' else {}
    if data:
        payments.wayforpay_process(data)
    order = data.get('orderReference', '')
    return redirect(reverse('wayforpay_done') + (f'?{urlencode({"order": order})}' if order else ''))


@login_required
def wayforpay_done(request):
    payment = Payment.objects.filter(reference=request.GET.get('order', ''), user=request.user).first()
    _payment_message(request, payment)
    return redirect('cars:my_cars')


def robots_txt(request):
    lines = [
        'User-agent: *',
        'Disallow: /choose-language/',
        'Disallow: /en/cabinet/',
        'Disallow: /ru/cabinet/',
        'Disallow: /en/users/',
        'Disallow: /ru/users/',
        'Disallow: /en/favorites/',
        'Disallow: /ru/favorites/',
        f'Sitemap: {request.build_absolute_uri("/sitemap.xml")}',
    ]
    return HttpResponse('\n'.join(lines) + '\n', content_type='text/plain')


def partnership_page(request):
    from . import partnership
    return render(request, 'cars/partnership.html', {
        'links': partnership.LINKS, 'email': partnership.EMAIL, 'followers': partnership.FOLLOWERS,
    })
