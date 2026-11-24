"""Structured data (schema.org JSON-LD) so search engines can show the site and its cars
as rich results: price, photo and availability in search, and the site search box."""

from django.urls import reverse

from . import partnership


def site_data(request):
    home = request.build_absolute_uri(reverse('cars:home'))
    logo = request.build_absolute_uri('/static/img/icon-512.png')
    return [
        {
            '@context': 'https://schema.org', '@type': ['Organization', 'AutoDealer'],
            'name': 'FIBONACCI', 'url': home, 'logo': logo, 'image': logo,
            'description': 'Exclusive cars worldwide: supercars, luxury and customized vehicles.',
            'sameAs': [url for _name, url, _icon, private in partnership.LINKS if not private],
        },
        {
            '@context': 'https://schema.org', '@type': 'WebSite', 'name': 'FIBONACCI', 'url': home,
            'potentialAction': {
                '@type': 'SearchAction',
                'target': {'@type': 'EntryPoint',
                           'urlTemplate': request.build_absolute_uri(reverse('cars:list')) + '?q={search_term_string}'},
                'query-input': 'required name=search_term_string',
            },
        },
    ]


FUEL_TYPES = {'petrol': 'Gasoline', 'diesel': 'Diesel', 'hybrid': 'Hybrid', 'electric': 'Electric', 'gas': 'LPG'}


def car_data(request, car, photos):
    url = request.build_absolute_uri(car.get_absolute_url())
    data = {
        '@context': 'https://schema.org', '@type': 'Car',
        'name': f'{car.make.name} {car.model}', 'url': url,
        'brand': {'@type': 'Brand', 'name': car.make.name}, 'model': car.model,
        'image': [request.build_absolute_uri(p.image.url) for p in photos[:6]],
    }
    if car.year:
        data['vehicleModelDate'] = str(car.year)
    if car.mileage_km is not None:
        data['mileageFromOdometer'] = {'@type': 'QuantitativeValue', 'value': car.mileage_km, 'unitCode': 'KMT'}
    if car.fuel in FUEL_TYPES:
        data['fuelType'] = FUEL_TYPES[car.fuel]
    if car.color:
        data['color'] = car.color
    if car.power_hp:
        data['vehicleEngine'] = {'@type': 'EngineSpecification',
                                 'enginePower': {'@type': 'QuantitativeValue', 'value': car.power_hp, 'unitCode': 'BHP'}}
    if car.main_price:
        offer = {'@type': 'Offer', 'url': url, 'price': f'{car.main_price:.2f}', 'priceCurrency': car.currency,
                 'availability': 'https://schema.org/InStock', 'itemCondition': 'https://schema.org/UsedCondition'}
        if car.country:
            offer['availableAtOrFrom'] = {'@type': 'Place', 'address': {'@type': 'PostalAddress',
                                                                        'addressCountry': str(car.country)}}
        data['offers'] = offer
    if car.description:
        data['description'] = car.description[:500]
    crumbs = {
        '@context': 'https://schema.org', '@type': 'BreadcrumbList',
        'itemListElement': [
            {'@type': 'ListItem', 'position': 1, 'name': 'Vehicles',
             'item': request.build_absolute_uri(reverse('cars:list'))},
            {'@type': 'ListItem', 'position': 2, 'name': car.make.name,
             'item': request.build_absolute_uri(car.make.get_absolute_url())},
            {'@type': 'ListItem', 'position': 3, 'name': car.model, 'item': url},
        ],
    }
    return [data, crumbs]
