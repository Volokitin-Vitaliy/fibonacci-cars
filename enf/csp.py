"""Content-Security-Policy: the browser runs only our own scripts.

Every page gets a random nonce; inline <script nonce="{{ CSP_NONCE }}"> blocks carry it,
so an injected script (for example through a listing text) would not run. The admin is
left out: django-unfold relies on inline code and it is only reachable by staff.
"""

import secrets

from django.conf import settings

THIRD_PARTY = {
    'script': ['https://challenges.cloudflare.com'],               # Turnstile bot check
    'style': ['https://fonts.googleapis.com'],
    'font': ['https://fonts.gstatic.com'],
    'frame': ['https://challenges.cloudflare.com'],
    'connect': ['https://challenges.cloudflare.com'],
    # Forms that leave the site: payments and Google / Apple sign-in.
    'form': ['https://secure.wayforpay.com', 'https://checkout.stripe.com',
             'https://accounts.google.com', 'https://appleid.apple.com'],
}


def policy(nonce):
    parts = [
        "default-src 'self'",
        f"script-src 'self' 'nonce-{nonce}' " + ' '.join(THIRD_PARTY['script']),
        # style="" attributes are used in templates; styles cannot run code.
        "style-src 'self' 'unsafe-inline' " + ' '.join(THIRD_PARTY['style']),
        "font-src 'self' " + ' '.join(THIRD_PARTY['font']),
        "img-src 'self' data: blob:",
        "connect-src 'self' " + ' '.join(THIRD_PARTY['connect']),
        'frame-src ' + ' '.join(THIRD_PARTY['frame']),
        "form-action 'self' " + ' '.join(THIRD_PARTY['form']),
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "object-src 'none'",
    ]
    if not settings.DEBUG:
        parts.append('upgrade-insecure-requests')
    return '; '.join(parts)


class ContentSecurityPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.csp_nonce = secrets.token_urlsafe(18)
        response = self.get_response(request)
        if (settings.CSP_ENABLED
                and response.get('Content-Type', '').startswith('text/html')
                and not request.path.startswith('/' + settings.ADMIN_URL)):
            header = 'Content-Security-Policy-Report-Only' if settings.CSP_REPORT_ONLY else 'Content-Security-Policy'
            response.setdefault(header, policy(request.csp_nonce))
        return response


def nonce(request):
    """Template context: {{ CSP_NONCE }}."""
    return {'CSP_NONCE': getattr(request, 'csp_nonce', '')}
