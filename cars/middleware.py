from urllib.parse import urlencode

from django.conf import settings
from django.shortcuts import redirect

EXEMPT_PREFIXES = ('/admin/', '/static/', '/media/', '/i18n/', '/choose-language/',
                   '/favicon.ico', '/robots.txt')


class LanguageChoiceMiddleware:
    """On the first visit, whatever page is opened, show the language picker
    before anything else. The choice is stored in the language cookie."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (request.method == 'GET'
                and settings.LANGUAGE_COOKIE_NAME not in request.COOKIES
                and not request.path.startswith(EXEMPT_PREFIXES)
                and not request.headers.get('HX-Request')):
            return redirect('/choose-language/?' + urlencode({'next': request.get_full_path()}))
        return self.get_response(request)
