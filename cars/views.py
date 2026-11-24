import json

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

from . import favorites, payments, search, services
from .forms import CarFilterForm, CarForm
from .models import Car, CarPhoto, Favorite, Make, Payment

SORTS = {
    'date-descending': ('-created_at',),
    'date-ascending': ('created_at',),
    'price-ascending': ('price_eur',),
    'price-descending': ('-price_eur',),
}
PER_PAGE = 24
ACCIDENT_FILTERS = {'no': False, 'yes': True}


def with_cover(queryset):
    return (queryset.select_related('make')
            .prefetch_related(Prefetch('photos', queryset=CarPhoto.objects.order_by('position', 'id'))))


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
        'new_offers': new_offers, 'latest': latest, 'hero_cars': hero_cars,
        'top_makes': top_makes,
        'stats': {'vehicles': visible.count(), 'makes': Make.objects.filter(cars__in=visible).distinct().count()},
        'social': [l for l in partnership.LINKS if not l[3]], 'followers': partnership.FOLLOWERS,
    })


def car_list(request, make_slug=None, fuel=None, new=False):
    """Catalog. Category (engine type) and make are separate choices that can
    be combined with each other and with the filters, e.g. diesel + BMW."""
    base = Car.objects.new_offers() if new else Car.objects.visible()
    base_url = reverse('cars:new') if new else reverse('cars:list')

    fuel = fuel or request.GET.get('fuel', '')
    if fuel and fuel not in Car.Fuel.values:
        raise Http404
    make_slug = make_slug or request.GET.get('make', '')
    make = get_object_or_404(Make, slug=make_slug) if make_slug else None

    # Countries offered in the picker: only those with cars matching the other choices.
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
    for_countries = base.filter(fuel=fuel) if fuel else base
    if make:
        for_countries = for_countries.filter(make=make)
    country_counts = dict(for_countries.exclude(country='').order_by().values_list('country')
                          .annotate(n=Count('pk', distinct=True)))
    if country not in country_counts:
        country = ''
    if country:
        base = base.filter(country=country)

    cars = base
    if fuel:
        cars = cars.filter(fuel=fuel)
    if make:
        cars = cars.filter(make=make)

    sort = request.GET.get('sort', 'date-descending')
    if sort not in SORTS:
        sort = 'date-descending'
    cars = with_cover(cars.distinct()).order_by(*SORTS[sort], '-pk')
    page = Paginator(cars, PER_PAGE).get_page(request.GET.get('page'))

    # Links for the two pickers keep everything else that is selected.
    params = request.GET.copy()
    params.pop('page', None)
    params['fuel'], params['make'] = fuel, make.slug if make else ''
    params['sort'] = '' if sort == 'date-descending' else sort

    def link(**changes):
        query = params.copy()
        for key, value in changes.items():
            query[key] = value
        query = {k: v for k, v in query.items() if v}
        return base_url + ('?' + urlencode(query) if query else '')

    for_fuels = base.filter(make=make) if make else base
    for_makes = base.filter(fuel=fuel) if fuel else base
    fuel_counts = dict(for_fuels.order_by().values_list('fuel').annotate(n=Count('pk', distinct=True)))
    make_counts = dict(for_makes.order_by().values_list('make').annotate(n=Count('pk', distinct=True)))
    fuel_options = [{'value': '', 'label': _('All categories'), 'href': link(fuel=''),
                     'active': not fuel, 'count': sum(fuel_counts.values())}]
    fuel_options += [{'value': value, 'label': label, 'href': link(fuel=value),
                      'active': fuel == value, 'count': fuel_counts.get(value, 0)}
                     for value, label in Car.Fuel.choices]
    make_options = [{'value': m.slug, 'label': m.name, 'href': link(make=m.slug),
                     'active': make == m, 'count': make_counts[m.pk]}
                    for m in Make.objects.filter(pk__in=make_counts).order_by('name')]

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
    elif fuel or make:
        title = ' · '.join(str(x) for x in (make.name if make else '',
                                            Car.Fuel(fuel).label if fuel else '') if x)
    return render(request, 'cars/list.html', {
        'page': page, 'title': title, 'sort': sort, 'is_new': new, 'country': country, 'query': query,
        'filters': filters, 'fuel': fuel, 'make': make,
        'fuel_label': Car.Fuel(fuel).label if fuel else _('All categories'),
        'fuel_options': fuel_options, 'make_options': make_options,
        'all_makes_href': link(make=''),
        'accident': accident, 'accident_options': accident_options,
        'country_options': country_options, 'sort_options': sort_options,
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
            'image': cover.image.url if cover else '',
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
    if not Car.objects.visible().filter(pk=pk).exists() and not is_owner:
        raise Http404
    photos = list(car.photos.all())
    return render(request, 'cars/detail.html', {
        'car': car, 'photos': photos, 'similar': similar_cars(car),
        'photo_urls_json': json.dumps([p.image.url for p in photos]),
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
