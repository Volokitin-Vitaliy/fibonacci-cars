import re
from urllib.parse import urlencode

from django.conf import settings
from django.shortcuts import redirect

EXEMPT_PREFIXES = ('/admin/', '/static/', '/media/', '/i18n/', '/choose-language/',
                   '/payments/', '/accounts/', '/favicon.ico', '/robots.txt', '/sitemap.xml')

# Search engines and link previews must see the page itself, not the picker.
BOT_RE = re.compile(
    r'bot|crawl|spider|slurp|yandex|bingpreview|facebookexternalhit|embedly|'
    r'whatsapp|telegram|skype|vkshare|pinterest|lighthouse|headlesschrome-seo',
    re.IGNORECASE)


def is_bot(request):
    return bool(BOT_RE.search(request.headers.get('User-Agent', '')))


class LanguageChoiceMiddleware:
    """On the first visit, whatever page is opened, show the language picker
    before anything else. The choice is stored in the language cookie.
    Bots skip the picker and get the language from the URL (/en/, /ru/)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (request.method == 'GET'
                and settings.LANGUAGE_COOKIE_NAME not in request.COOKIES
                and not request.path.startswith(EXEMPT_PREFIXES)
                and not request.headers.get('HX-Request')
                and not is_bot(request)):
            return redirect('/choose-language/?' + urlencode({'next': request.get_full_path()}))
        response = self.get_response(request)
        self.remember_language(request)
        return response

    @staticmethod
    def remember_language(request):
        """Keep the user's language for emails in sync with the site."""
        user = getattr(request, 'user', None)
        language = getattr(request, 'LANGUAGE_CODE', None)
        if (user is not None and user.is_authenticated and language
                and language in dict(settings.LANGUAGES) and user.language != language
                and not request.path.startswith(EXEMPT_PREFIXES)):
            user.language = language
            user.save(update_fields=['language'])
