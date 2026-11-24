"""Links on the Partnership page (mirrors linktr.ee/fibonacci.iox).
Edit this list to change the page."""

from django.utils.translation import gettext_lazy as _

EMAIL = 'fibonacci.iox@gmail.com'
FOLLOWERS = '110K+'

LINKS = [
    # (title, url, icon, primary)
    (_('Partnership'), 'https://t.me/fibonaccicars', 'handshake', True),
    ('TikTok', 'https://www.tiktok.com/@fibonacci_io', 'tiktok', False),
    ('Instagram', 'https://www.instagram.com/fibonacci_io', 'instagram', False),
    ('YouTube', 'https://www.youtube.com/channel/UCJC4YI6kj6oSz-YfJMguiVw', 'youtube', False),
    ('Facebook', 'https://www.facebook.com/people/Fibonacci/61585279025965', 'facebook', False),
    ('Telegram', 'https://t.me/fibonacci_io', 'telegram', False),
]
