"""Recording visits: who (anonymous hash), what page, from where, on what device."""

import hashlib
import logging
import os
import re
from urllib.parse import urlsplit

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

BOTS = re.compile(
    r'bot|crawl|spider|slurp|scrap|preview|facebookexternalhit|embedly|whatsapp/|vkshare|'
    r'headless|phantom|lighthouse|pagespeed|gtmetrix|pingdom|uptime|monitor|python|curl|wget|'
    r'httpclient|okhttp|java/|go-http|axios|node-fetch|postman|insomnia|scan|check|validator|feed',
    re.I)

# Referring sites grouped into named sources; anything else is shown by its domain.
SOURCES = [
    ('Google', r'(^|\.)google\.'), ('Yandex', r'(^|\.)yandex\.|(^|\.)ya\.ru$'), ('Bing', r'(^|\.)bing\.com$'),
    ('DuckDuckGo', r'duckduckgo\.com$'), ('Threads', r'(^|\.)threads\.(net|com)$'), ('Instagram', r'instagram\.com$'),
    ('Facebook', r'(^|\.)facebook\.com$|(^|\.)fb\.(com|me)$'), ('Telegram', r'(^|\.)t\.me$|telegram\.'),
    ('YouTube', r'youtube\.com$|youtu\.be$'), ('TikTok', r'tiktok\.com$'),
    ('WhatsApp', r'whatsapp\.com$|wa\.me$'), ('X / Twitter', r'(^|\.)(t\.co|twitter\.com|x\.com)$'),
    ('LinkedIn', r'linkedin\.com$|lnkd\.in$'), ('VK', r'(^|\.)vk\.(com|ru)$'),
    ('Hollmann', r'hollmann'), ('ChatGPT', r'chatgpt\.com$|openai\.com$'),
]

PAGE_KINDS = {
    'cars:home': 'home', 'cars:list': 'catalog', 'cars:new': 'catalog', 'cars:fuel': 'catalog',
    'cars:make': 'catalog', 'cars:detail': 'car', 'cars:my_cars': 'sell', 'cars:add': 'sell',
    'cars:edit': 'sell', 'cars:favorites': 'account', 'users:login': 'account',
    'users:register': 'account', 'users:account': 'account',
}


def client_ip(request):
    return (request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR') or '').strip()


def visitor_id(request):
    """The same person (IP + browser) gets the same id; it cannot be turned back into an IP."""
    raw = f'{settings.SECRET_KEY}|{client_ip(request)}|{request.META.get("HTTP_USER_AGENT", "")}'
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def is_bot(request):
    ua = request.META.get('HTTP_USER_AGENT', '')
    return not ua or bool(BOTS.search(ua))


def parse_agent(ua):
    """(device, browser, os) from the User-Agent, without extra libraries."""
    if re.search(r'iPad|Tablet|PlayBook|Silk|(Android(?!.*Mobile))', ua):
        device = 'tablet'
    elif re.search(r'Mobi|iPhone|iPod|Android|Windows Phone', ua):
        device = 'mobile'
    else:
        device = 'desktop'
    for name, pattern in (('Edge', r'Edg/'), ('Opera', r'OPR/|Opera'), ('Samsung', r'SamsungBrowser'),
                          ('Yandex', r'YaBrowser'), ('Firefox', r'Firefox|FxiOS'), ('Chrome', r'Chrome|CriOS'),
                          ('Safari', r'Safari')):
        if re.search(pattern, ua):
            browser = name
            break
    else:
        browser = 'Other'
    for name, pattern in (('iOS', r'iPhone|iPad|iPod'), ('Android', r'Android'), ('Windows', r'Windows'),
                          ('macOS', r'Mac OS X|Macintosh'), ('Linux', r'Linux|X11')):
        if re.search(pattern, ua):
            os_name = name
            break
    else:
        os_name = 'Other'
    return device, browser, os_name


# In-app browsers sign their User-Agent: a visitor who opened a link inside the app,
# where no referrer is sent, is still counted for that app.
APP_BROWSERS = [
    ('Threads', r'Barcelona'), ('Instagram', r'Instagram'), ('Facebook', r'FBAN|FBAV|FB_IAB|FBIOS|\[FB'), ('TikTok', r'musical_ly|BytedanceWebview|TikTok|trill_'),
    ('YouTube', r'com\.google\.ios\.youtube|YouTube'), ('Telegram', r'Telegram'), ('LinkedIn', r'LinkedInApp'),
    ('Snapchat', r'Snapchat'), ('X / Twitter', r'Twitter'), ('VK', r'VKAndroidApp|com\.vk\.'),
]
# utm_source spellings that mean the same source as the referrer names above.
UTM_ALIASES = {
    'threads': 'Threads', 'instagram': 'Instagram', 'insta': 'Instagram', 'ig': 'Instagram', 'facebook': 'Facebook', 'fb': 'Facebook',
    'tiktok': 'TikTok', 'tt': 'TikTok', 'youtube': 'YouTube', 'yt': 'YouTube', 'telegram': 'Telegram',
    'tg': 'Telegram', 'whatsapp': 'WhatsApp', 'wa': 'WhatsApp', 'google': 'Google', 'yandex': 'Yandex',
    'twitter': 'X / Twitter', 'x': 'X / Twitter', 'linkedin': 'LinkedIn', 'vk': 'VK',
}


def source_of(request):
    """(source, referrer domain): utm_source wins, then the referring site, then the app whose
    in-app browser opened the link. Links from inside the site are not a source."""
    utm = request.GET.get('utm_source', '').strip()[:40]
    ref = request.META.get('HTTP_REFERER', '')
    host = (urlsplit(ref).hostname or '').lower().removeprefix('www.')[:100]
    own = (request.get_host().split(':')[0] or '').lower().removeprefix('www.')
    internal = host == own or host in ('localhost', '127.0.0.1')
    if internal:
        host = ''
    if utm:
        return UTM_ALIASES.get(utm.lower(), utm), host
    if host:
        for name, pattern in SOURCES:
            if re.search(pattern, host):
                return name, host
        return host[:40], host
    if not internal and not ref:
        ua = request.META.get('HTTP_USER_AGENT', '')
        for name, pattern in APP_BROWSERS:
            if re.search(pattern, ua):
                return name, ''
    return '', ''


# --- Country from the IP (DB-IP Lite database, updated monthly by update_geoip) ---

_reader = {'path': None, 'mtime': None, 'db': None}


def geoip_path():
    return os.path.join(settings.MEDIA_ROOT, 'geoip', 'dbip-country-lite.mmdb')


def country_of(ip):
    path = geoip_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return ''
    try:
        if _reader['mtime'] != mtime:
            import maxminddb
            _reader.update(path=path, mtime=mtime, db=maxminddb.open_database(path))
        found = _reader['db'].get(ip) if ip else None
    except Exception:
        logger.exception('GeoIP lookup failed')
        return ''
    return ((found or {}).get('country') or {}).get('iso_code', '')[:2]


def country_for(request):
    """Behind Cloudflare its CF-IPCountry header tells the country; otherwise the IP database."""
    code = request.META.get('HTTP_CF_IPCOUNTRY', '').upper()
    if len(code) == 2 and code.isalpha() and code not in ('XX', 'T1'):
        return code
    return country_of(client_ip(request))


def should_track(request, response):
    if request.method != 'GET' or response.status_code != 200 or settings.ANALYTICS_DISABLED:
        return False
    if 'text/html' not in response.get('Content-Type', ''):
        return False
    if request.headers.get('Sec-Purpose', '').startswith('prefetch') or request.headers.get('Purpose') == 'prefetch':
        return False
    if request.path.startswith('/' + settings.ADMIN_URL) or is_bot(request):
        return False
    return should_count_user(request)


def should_count_user(request):
    """Staff (you and moderators) are not counted, so your own visits do not inflate the numbers."""
    if settings.ANALYTICS_DISABLED:
        return False
    user = getattr(request, 'user', None)
    return not (settings.ANALYTICS_EXCLUDE_STAFF and user is not None and user.is_staff)


def record_pageview(request):
    from .models import PageView
    match = getattr(request, 'resolver_match', None)
    name = match.view_name if match else ''
    kind = PAGE_KINDS.get(name, 'other')
    car_id = match.kwargs.get('pk') if kind == 'car' else None
    visitor = visitor_id(request)
    device, browser, os_name = parse_agent(request.META.get('HTTP_USER_AGENT', ''))
    source, referrer = source_of(request)
    user = getattr(request, 'user', None)
    PageView.objects.create(
        created_at=timezone.now(), visitor=visitor,
        is_new=not PageView.objects.filter(visitor=visitor).exists(),
        is_member=bool(user and user.is_authenticated), path=request.path[:300], kind=kind,
        car_id=car_id, lang=(getattr(request, 'LANGUAGE_CODE', '') or '')[:2], device=device,
        browser=browser, os=os_name, country=country_for(request), source=source, referrer=referrer)


def record_event(request, kind, car_id=None):
    from .models import Event
    if is_bot(request) or not should_count_user(request):
        return
    try:
        Event.objects.create(created_at=timezone.now(), visitor=visitor_id(request), kind=kind, car_id=car_id,
                             device=parse_agent(request.META.get('HTTP_USER_AGENT', ''))[0],
                             country=country_for(request))
    except Exception:
        logger.exception('Analytics: event not recorded')
