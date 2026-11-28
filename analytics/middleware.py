import logging

from . import tracking

logger = logging.getLogger(__name__)


class AnalyticsMiddleware:
    """Counts every page a visitor opens. A failure here never breaks the page."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            if tracking.should_track(request, response):
                tracking.record_pageview(request)
        except Exception:
            logger.exception('Analytics: page view not recorded')
        return response
