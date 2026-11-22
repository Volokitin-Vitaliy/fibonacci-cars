from django.db.models import Count, Q

from .models import Car, Category, Make


def navigation(request):
    if request.path.startswith('/admin/'):
        return {}
    visible = Car.objects.visible()
    makes = (Make.objects
             .annotate(n=Count('cars', filter=Q(cars__in=visible)))
             .filter(n__gt=0))
    favorite_ids = set()
    if request.user.is_authenticated:
        favorite_ids = set(request.user.favorites.values_list('car_id', flat=True))
    return {
        'nav_categories': Category.objects.all(),
        'nav_makes': makes,
        'favorite_ids': favorite_ids,
    }
