"""Favorites for everyone.

Signed-in users keep favorites in the database. Guests keep them in their
session: it lives 30 days after the last visit (SESSION_COOKIE_AGE with
SESSION_SAVE_EVERY_REQUEST, so every visit extends it), which is the usual
lifetime on shops and marketplaces. When a guest signs in or registers, the
saved cars move to their account.
"""

from .models import Car, Favorite

SESSION_KEY = 'guest_favorites'
MAX_GUEST_FAVORITES = 200


def _guest_ids(request):
    try:
        return [int(i) for i in request.session.get(SESSION_KEY, [])]
    except (TypeError, ValueError):
        return []


def favorite_ids(request):
    if request.user.is_authenticated:
        return set(request.user.favorites.values_list('car_id', flat=True))
    return set(_guest_ids(request))


def toggle(request, car):
    """Add or remove a car; returns True if it is a favorite afterwards."""
    if request.user.is_authenticated:
        favorite, created = Favorite.objects.get_or_create(user=request.user, car=car)
        if not created:
            favorite.delete()
        return created
    ids = _guest_ids(request)
    if car.pk in ids:
        ids.remove(car.pk)
        added = False
    else:
        ids.insert(0, car.pk)
        added = True
    request.session[SESSION_KEY] = ids[:MAX_GUEST_FAVORITES]
    return added


def favorite_cars(request):
    """Cars to show on the favorites page, newest first."""
    if request.user.is_authenticated:
        return [f.car for f in request.user.favorites.select_related('car__make')
                .prefetch_related('car__photos')]
    ids = _guest_ids(request)
    cars = {c.pk: c for c in Car.objects.visible().filter(pk__in=ids)
            .select_related('make').prefetch_related('photos')}
    return [cars[i] for i in ids if i in cars]


def merge_guest_favorites(sender, request, user, **kwargs):
    """user_logged_in handler: move a guest's favorites to the account."""
    if request is None or not hasattr(request, 'session'):
        return
    ids = _guest_ids(request)
    if not ids:
        return
    existing = set(Favorite.objects.filter(user=user).values_list('car_id', flat=True))
    valid = Car.objects.filter(pk__in=ids).values_list('pk', flat=True)
    Favorite.objects.bulk_create([Favorite(user=user, car_id=pk) for pk in valid if pk not in existing],
                                 ignore_conflicts=True)
    request.session.pop(SESSION_KEY, None)
