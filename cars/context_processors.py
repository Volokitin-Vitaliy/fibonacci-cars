from django.db.models import Count, Q

from . import favorites
from django.urls import reverse

from .models import Car, Make


def navigation(request):
    if request.path.startswith('/admin/'):
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
    }
