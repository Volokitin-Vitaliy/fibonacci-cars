import re

from django.conf import settings
from django.utils import translation

EXEMPT_PREFIXES = ('/' + settings.ADMIN_URL, '/static/', '/media/', '/i18n/', '/choose-language/',
                   '/payments/', '/telegram/', '/accounts/', '/favicon.ico', '/robots.txt', '/sitemap.xml')

# Search engines and link previews get the page as it is, without language offers.
BOT_RE = re.compile(
    r'bot|crawl|spider|slurp|yandex|bingpreview|facebookexternalhit|embedly|'
    r'whatsapp|telegram|skype|vkshare|pinterest|lighthouse|headlesschrome-seo',
    re.IGNORECASE)


def is_bot(request):
    return bool(BOT_RE.search(request.headers.get('User-Agent', '')))


class LanguageChoiceMiddleware:
    """The site opens straight away in the visitor's language: links to /en/ or /ru/
    keep their language, and the bare address (/) follows the browser's language
    (LocaleMiddleware). On the first visit the language is remembered in the language
    cookie, and if the browser prefers the other language a small offer to switch is
    shown (request.suggest_language)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        first_visit = (request.method == 'GET'
                       and settings.LANGUAGE_COOKIE_NAME not in request.COOKIES
                       and not request.path.startswith(EXEMPT_PREFIXES)
                       and not is_bot(request))
        if first_visit:
            preferred = translation.get_language_from_request(request)  # browser language
            from_path = translation.get_language_from_path(request.path_info)
            if from_path and preferred != from_path:
                request.suggest_language = preferred
        response = self.get_response(request)
        if first_visit and response.status_code == 200 and getattr(request, 'LANGUAGE_CODE', None):
            response.set_cookie(settings.LANGUAGE_COOKIE_NAME, request.LANGUAGE_CODE,
                                max_age=60 * 60 * 24 * 365, samesite='Lax',
                                secure=settings.SESSION_COOKIE_SECURE)
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
