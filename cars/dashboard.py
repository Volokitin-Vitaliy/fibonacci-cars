"""Admin dashboard (django-unfold): key numbers and what needs attention."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import Car, Favorite, ImportRun, Payment


def pending_badge(request):
    count = Car.objects.filter(source=Car.Source.USER, moderation=Car.Moderation.PENDING).count()
    return count or None


def dashboard_callback(request, context):
    now = timezone.now()
    week_ago = now - timedelta(days=7)
    User = get_user_model()
    user_cars = Car.objects.filter(source=Car.Source.USER)
    pending = user_cars.filter(moderation=Car.Moderation.PENDING).select_related('make', 'owner')
    changelist = reverse('admin:cars_car_changelist')
    paid = Payment.objects.filter(status=Payment.Status.PAID)
    expiring = (Car.objects.visible().filter(source=Car.Source.USER,
                                              active_until__lte=now + timedelta(days=3))
                .select_related('make', 'owner').order_by('active_until'))
    last_import = ImportRun.objects.first()

    context.update({
        'kpis': [
            {'title': _('Waiting for review'), 'value': pending.count(),
             'href': changelist + '?moderation=pending', 'accent': pending.exists()},
            {'title': _('Active private listings'), 'value': Car.objects.visible().filter(source=Car.Source.USER).count(),
             'href': changelist + '?source__exact=user&status__exact=active'},
            {'title': _('Vehicles from Hollmann'), 'value': Car.objects.visible().filter(source=Car.Source.HOLLMANN).count(),
             'href': changelist + '?source__exact=hollmann&is_published__exact=1'},
            {'title': _('Users'), 'value': User.objects.count(),
             'note': _('+%(n)s this week') % {'n': User.objects.filter(date_joined__gte=week_ago).count()},
             'href': reverse('admin:users_customuser_changelist')},
            {'title': _('Saved to favorites'), 'value': Favorite.objects.count(),
             'href': reverse('admin:cars_favorite_changelist')},
            {'title': _('Paid, €'), 'value': paid.aggregate(s=Sum('amount'))['s'] or 0,
             'note': _('%(n)s payments') % {'n': paid.count()},
             'href': reverse('admin:cars_payment_changelist')},
        ],
        'pending_cars': pending.order_by('created_at')[:8],
        'expiring_cars': expiring[:8],
        'last_import': last_import,
        'recent_users': User.objects.order_by('-date_joined')[:6],
    })
    return context
