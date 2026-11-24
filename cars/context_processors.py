from django.conf import settings
from django.db.models import Count, Q

from . import favorites
from django.urls import reverse

from .models import Car, Make


def navigation(request):
    if request.path.startswith('/' + settings.ADMIN_URL):
        return {}
    visible = Car.objects.visible()
    makes = (Make.objects
             .annotate(n=Count('cars', filter=Q(cars__in=visible)))
             .filter(n__gt=0))
    favorite_ids = favorites.favorite_ids(request)
    return {
        'nav_fuels': [{'label': label, 'url': reverse('cars:fuel', args=[value])}
                      for value, label in Car.Fuel.choices],
        'nav_makes': makes,
        'favorite_ids': favorite_ids,
        'TURNSTILE_SITE_KEY': settings.TURNSTILE_SITE_KEY if settings.TURNSTILE_SECRET_KEY else '',
    }
