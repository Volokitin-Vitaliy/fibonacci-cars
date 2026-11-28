"""Small beacons from open pages: 'still here' pings and contact clicks."""

import logging

from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import tracking
from .models import Event, Presence

logger = logging.getLogger(__name__)


def _same_site(request):
    """Only beacons sent by our own pages (browsers set Sec-Fetch-Site / Origin)."""
    site = request.headers.get('Sec-Fetch-Site')
    if site:
        return site == 'same-origin'
    origin = request.headers.get('Origin', '')
    return origin.split('://')[-1] == request.get_host()


def _car_id(value):
    from cars.models import Car
    return value if value.isdigit() and Car.objects.filter(pk=value).exists() else None


@csrf_exempt  # no state of the visitor is changed; only counted
@require_POST
def ping(request):
    if _same_site(request) and not tracking.is_bot(request) and tracking.should_count_user(request):
        try:
            Presence.objects.update_or_create(visitor=tracking.visitor_id(request), defaults={
                'last_seen': timezone.now(), 'path': request.POST.get('path', '')[:300],
                'car_id': _car_id(request.POST.get('car', '')),
                'device': tracking.parse_agent(request.META.get('HTTP_USER_AGENT', ''))[0],
                'country': tracking.country_of(tracking.client_ip(request)),
            })
        except Exception:
            logger.exception('Analytics: ping not recorded')
    return HttpResponse(status=204)


@csrf_exempt
@require_POST
def event(request):
    kind = request.POST.get('kind', '')
    car_id = _car_id(request.POST.get('car', ''))
    if _same_site(request) and kind in Event.CONTACTS and car_id:
        try:
            tracking.record_event(request, kind, car_id)
        except Exception:
            logger.exception('Analytics: event not recorded')
    return HttpResponse(status=204)
