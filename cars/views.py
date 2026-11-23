from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import favorites, payments, services
from .forms import CarFilterForm, CarForm
from .models import Car, CarPhoto, Favorite, Make, Payment

SORTS = {
    'date-descending': ('-created_at',),
    'date-ascending': ('created_at',),
    'price-ascending': ('price_eur',),
    'price-descending': ('-price_eur',),
}
PER_PAGE = 24


def with_cover(queryset):
    return (queryset.select_related('make')
            .prefetch_related(Prefetch('photos', queryset=CarPhoto.objects.order_by('position', 'id'))))


def choose_language(request):
    next_url = request.GET.get('next') or '/'
    if not url_has_allowed_host_and_scheme(next_url, {request.get_host()}):
        next_url = '/'
    return render(request, 'choose_language.html', {'next': next_url})


def home(request):
    new_offers = list(with_cover(Car.objects.new_offers()).order_by('-created_at')[:8])
    latest = [] if new_offers else with_cover(Car.objects.visible()).order_by('-created_at')[:8]
    return render(request, 'cars/home.html', {'new_offers': new_offers, 'latest': latest})


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

    source = request.GET.get('source')
    if source in Car.Source.values:
        base = base.filter(source=source)
    filters = CarFilterForm(request.GET or None)
    base = filters.apply(base)

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

    title = _('New Offers') if new else _('All Vehicles')
    if fuel or make:
        title = ' · '.join(str(x) for x in (make.name if make else '',
                                            Car.Fuel(fuel).label if fuel else '') if x)
    return render(request, 'cars/list.html', {
        'page': page, 'title': title, 'sort': sort, 'is_new': new, 'source': source,
        'filters': filters, 'fuel': fuel, 'make': make,
        'fuel_label': Car.Fuel(fuel).label if fuel else _('All categories'),
        'fuel_options': fuel_options, 'make_options': make_options,
        'all_makes_href': link(make=''),
        'hidden_params': {k: v for k, v in params.items() if v and k not in ('sort', 'source')},
    })


def car_detail(request, pk):
    car = get_object_or_404(with_cover(Car.objects.all()), pk=pk)
    is_owner = request.user.is_authenticated and car.owner_id == request.user.id
    if not Car.objects.visible().filter(pk=pk).exists() and not is_owner:
        raise Http404
    related = with_cover(Car.objects.visible().filter(make=car.make).exclude(pk=car.pk))[:4]
    return render(request, 'cars/detail.html', {
        'car': car, 'photos': list(car.photos.all()), 'related': related,
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
        'listing_price': settings.LISTING_PRICE_EUR,
        'duration': settings.LISTING_DURATION_DAYS,
        'moderation': settings.LISTING_MODERATION,
    })


@login_required
def car_create(request):
    phone = request.user.phone or ''
    initial = {'contact_name': request.user.full_name, 'contact_phone': phone,
               'contact_whatsapp': phone}
    form = CarForm(request.POST or None, request.FILES or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        form.instance.owner = request.user
        form.instance.source = Car.Source.USER
        form.instance.status = Car.Status.INACTIVE
        car = form.save()
        if services.submit_for_review(car):
            messages.success(request, _('Thank you! Your listing has been sent for review. We will email you once it is approved.'))  # noqa: E501
        elif settings.LISTING_PAYMENT_REQUIRED:
            messages.success(request, _('Your listing is saved. Activate it to publish it.'))
            return redirect('cars:my_cars')
        else:
            car.activate()
            messages.success(request, _('Your listing is published for %(days)s days.')
                             % {'days': settings.LISTING_DURATION_DAYS})
        return redirect(car)
    return render(request, 'cars/cabinet/car_form.html', {
        'form': form, 'section': 'add', 'duration': settings.LISTING_DURATION_DAYS,
        'moderation': settings.LISTING_MODERATION})


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
        if services.submit_for_review(car):
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
    elif not car.is_approved:
        messages.error(request, _('The listing can be activated after it has been approved.'))
    elif settings.LISTING_PAYMENT_REQUIRED:
        try:
            url = payments.create_checkout(
                car, request.user,
                success_url=request.build_absolute_uri(reverse('cars:payment_success')),
                cancel_url=request.build_absolute_uri(reverse('cars:my_cars')))
        except payments.PaymentsNotConfigured:
            messages.error(request, _('Online payment is not available yet.'))
        except Exception:
            messages.error(request, _('The payment could not be started. Please try again later.'))
        else:
            return redirect(url)
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


@login_required
def payment_success(request):
    """Stripe redirects here after checkout. The webhook activates the
    listing; checking the session here makes it immediate."""
    session_id = request.GET.get('session_id', '')
    payment = Payment.objects.filter(stripe_session_id=session_id, user=request.user).first()
    if payment is None:
        return redirect('cars:my_cars')
    if payment.status != Payment.Status.PAID:
        try:
            payments.fulfill(payments.retrieve_session(session_id))
        except Exception:
            pass
        payment.refresh_from_db()
    if payment.status == Payment.Status.PAID:
        messages.success(request, _('Payment received. Your listing is active for %(days)s days.')
                         % {'days': settings.LISTING_DURATION_DAYS})
    else:
        messages.info(request, _('We are waiting for the payment confirmation. Your listing will be activated in a moment.'))  # noqa: E501
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
    if event['type'] in ('checkout.session.completed', 'checkout.session.async_payment_succeeded'):
        payments.fulfill(event['data']['object'])
    elif event['type'] in ('checkout.session.expired', 'checkout.session.async_payment_failed'):
        Payment.objects.filter(stripe_session_id=event['data']['object']['id'],
                               status=Payment.Status.PENDING).update(status=Payment.Status.FAILED)
    return HttpResponse(status=200)


def robots_txt(request):
    lines = [
        'User-agent: *',
        'Disallow: /admin/',
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
