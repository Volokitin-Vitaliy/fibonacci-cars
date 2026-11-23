"""
Django settings for the FIBONACCI car marketplace.
"""

from pathlib import Path
import os

from django.utils.translation import gettext_lazy as _
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in ('1', 'true', 'yes', 'on')


SECRET_KEY = os.getenv('SECRET_KEY')

DEBUG = env_bool('DEBUG', True)

ALLOWED_HOSTS = ['127.0.0.1', 'localhost', 'domen.com', 'www.domen.com']

CSRF_TRUSTED_ORIGINS = [
    'http://127.0.0.1:8000',
    'http://localhost:8000',
    'https://domen.com',
    'https://www.domen.com',
]

# Secure cookies only work over HTTPS; keep them on in production and off
# for local development over plain http.
CSRF_COOKIE_SECURE = env_bool('SECURE_COOKIES', not DEBUG)
SESSION_COOKIE_SECURE = env_bool('SECURE_COOKIES', not DEBUG)
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'


INSTALLED_APPS = [
    'unfold',
    'unfold.contrib.filters',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'django.contrib.sitemaps',

    'django_countries',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'allauth.socialaccount.providers.apple',

    'users',
    'cars',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'cars.middleware.LanguageChoiceMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
]

ROOT_URLCONF = 'enf.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.template.context_processors.i18n',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',

                'cars.context_processors.navigation',
            ],
        },
    },
]

WSGI_APPLICATION = 'enf.wsgi.application'


# Database: PostgreSQL when configured (Docker / production), SQLite otherwise.
if os.getenv('POSTGRES_DB'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('POSTGRES_DB'),
            'USER': os.getenv('POSTGRES_USER'),
            'PASSWORD': os.getenv('POSTGRES_PASSWORD'),
            'HOST': os.getenv('POSTGRES_HOST', 'db'),
            'PORT': os.getenv('POSTGRES_PORT', '5432'),
            'ATOMIC_REQUESTS': True,
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

AUTH_USER_MODEL = 'users.CustomUser'
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]
LOGIN_URL = 'users:login'
LOGIN_REDIRECT_URL = 'cars:my_cars'
LOGOUT_REDIRECT_URL = 'cars:home'


# Internationalization: English and Russian. Every visitor chooses a
# language first (see cars.middleware.LanguageChoiceMiddleware).
LANGUAGE_CODE = 'en'
LANGUAGES = [
    ('en', _('English')),
    ('ru', _('Russian')),
]
LOCALE_PATHS = [BASE_DIR / 'locale']
LANGUAGE_COOKIE_AGE = 60 * 60 * 24 * 365

TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'assets']
STATIC_ROOT = os.path.join(BASE_DIR, 'static')

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

SESSION_COOKIE_AGE = 60 * 60 * 24 * 30  # 30 days
SESSION_SAVE_EVERY_REQUEST = True


# Listings created by users from their cabinet.
LISTING_DURATION_DAYS = int(os.getenv('LISTING_DURATION_DAYS', 30))
LISTING_PRICE_EUR = os.getenv('LISTING_PRICE_EUR', '5.00')
# When True, (re)activating a listing requires a payment. Payment itself is
# not implemented yet, so this stays False and activation is free.
LISTING_PAYMENT_REQUIRED = env_bool('LISTING_PAYMENT_REQUIRED', False)
LISTING_MAX_PHOTOS = 10
# New and edited user listings wait for an admin to approve them.
LISTING_MODERATION = env_bool('LISTING_MODERATION', True)
# Owners get an email this many days before their listing expires.
LISTING_REMINDER_DAYS = int(os.getenv('LISTING_REMINDER_DAYS', 3))
# Used to compare and filter prices given in USD and EUR.
USD_TO_EUR_RATE = float(os.getenv('USD_TO_EUR_RATE', 0.92))


# Email. Without EMAIL_HOST, emails are printed to the console.
SITE_URL = os.getenv('SITE_URL', 'http://localhost:8000').rstrip('/')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'FIBONACCI <no-reply@localhost>')
EMAIL_HOST = os.getenv('EMAIL_HOST', '')
if EMAIL_HOST:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
    EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
    EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
    EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', True)
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
# Who is told about listings waiting for review (comma-separated emails).
MODERATION_EMAILS = [e.strip() for e in os.getenv('MODERATION_EMAILS', '').split(',') if e.strip()]


# Daily import from hollmann.international (see cars/importers/hollmann.py).
HOLLMANN_BASE_URL = 'https://hollmann.international'
HOLLMANN_REQUEST_DELAY = float(os.getenv('HOLLMANN_REQUEST_DELAY', 1.0))


STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')


# Sign in with Google / Apple (django-allauth). A button appears on the
# login and sign-up pages once the provider's keys are set.
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_LOGIN_METHODS = {'email'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'password1*', 'password2*']
ACCOUNT_EMAIL_VERIFICATION = 'none'
ACCOUNT_ADAPTER = 'users.adapters.AccountAdapter'
SOCIALACCOUNT_ADAPTER = 'users.adapters.SocialAccountAdapter'
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_LOGIN_ON_GET = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
SOCIALACCOUNT_STORE_TOKENS = False

SOCIALACCOUNT_PROVIDERS = {}
if os.getenv('GOOGLE_CLIENT_ID') and os.getenv('GOOGLE_CLIENT_SECRET'):
    SOCIALACCOUNT_PROVIDERS['google'] = {
        'APP': {'client_id': os.getenv('GOOGLE_CLIENT_ID'),
                'secret': os.getenv('GOOGLE_CLIENT_SECRET')},
        'SCOPE': ['profile', 'email'],
        'EMAIL_AUTHENTICATION': True,
    }
if os.getenv('APPLE_SERVICE_ID') and os.getenv('APPLE_TEAM_ID') and os.getenv('APPLE_KEY_ID'):
    SOCIALACCOUNT_PROVIDERS['apple'] = {
        'APP': {
            'client_id': os.getenv('APPLE_SERVICE_ID'),
            'secret': os.getenv('APPLE_KEY_ID'),
            'key': os.getenv('APPLE_TEAM_ID'),
            # Contents of the .p8 key file; newlines may be written as \n in .env.
            'settings': {'certificate_key': os.getenv('APPLE_PRIVATE_KEY', '').replace('\\n', '\n')},
        },
        'EMAIL_AUTHENTICATION': True,
    }


# Admin theme (django-unfold): dark-ready, with a dashboard and a sidebar.
from django.templatetags.static import static  # noqa: E402
from django.urls import reverse_lazy  # noqa: E402

UNFOLD = {
    'SITE_TITLE': 'FIBONACCI',
    'SITE_HEADER': 'FIBONACCI',
    'SITE_SUBHEADER': _('Admin panel'),
    'SITE_URL': '/',
    'SITE_ICON': lambda request: static('img/logo-96.png'),
    'SITE_SYMBOL': 'directions_car',
    'SITE_FAVICONS': [
        {'rel': 'icon', 'sizes': '32x32', 'type': 'image/png',
         'href': lambda request: static('img/favicon-32.png')},
    ],
    'SHOW_HISTORY': True,
    'SHOW_VIEW_ON_SITE': True,
    'DASHBOARD_CALLBACK': 'cars.dashboard.dashboard_callback',
    'COLORS': {
        'base': {
            '50': '250, 250, 250', '100': '245, 245, 245', '200': '229, 229, 229',
            '300': '212, 212, 212', '400': '163, 163, 163', '500': '115, 115, 115',
            '600': '82, 82, 82', '700': '64, 64, 64', '800': '38, 38, 38',
            '900': '23, 23, 23', '950': '10, 10, 10',
        },
        'primary': {  # the blue glow of the logo
            '50': '239, 246, 255', '100': '219, 234, 254', '200': '191, 219, 254',
            '300': '147, 197, 253', '400': '96, 165, 250', '500': '59, 130, 246',
            '600': '37, 99, 235', '700': '29, 78, 216', '800': '30, 64, 175',
            '900': '30, 58, 138', '950': '23, 37, 84',
        },
    },
    'SIDEBAR': {
        'show_search': True,
        'show_all_applications': False,
        'navigation': [
            {
                'title': _('Overview'),
                'items': [
                    {'title': _('Dashboard'), 'icon': 'space_dashboard',
                     'link': reverse_lazy('admin:index')},
                    {'title': _('Open the site'), 'icon': 'open_in_new', 'link': '/'},
                ],
            },
            {
                'title': _('Listings'),
                'items': [
                    {'title': _('Moderation'), 'icon': 'fact_check',
                     'link': lambda request: str(reverse_lazy('admin:cars_car_changelist')) + '?moderation=pending',
                     'badge': 'cars.dashboard.pending_badge'},
                    {'title': _('All vehicles'), 'icon': 'directions_car',
                     'link': reverse_lazy('admin:cars_car_changelist')},
                    {'title': _('Makes'), 'icon': 'sell',
                     'link': reverse_lazy('admin:cars_make_changelist')},
                ],
            },
            {
                'title': _('People'),
                'items': [
                    {'title': _('Users'), 'icon': 'group',
                     'link': reverse_lazy('admin:users_customuser_changelist')},
                    {'title': _('Favorites'), 'icon': 'favorite',
                     'link': reverse_lazy('admin:cars_favorite_changelist')},
                    {'title': _('Google / Apple accounts'), 'icon': 'key',
                     'link': reverse_lazy('admin:socialaccount_socialaccount_changelist')},
                ],
            },
            {
                'title': _('Money'),
                'items': [
                    {'title': _('Payments'), 'icon': 'payments',
                     'link': reverse_lazy('admin:cars_payment_changelist')},
                ],
            },
            {
                'title': _('System'),
                'collapsible': True,
                'items': [
                    {'title': _('Hollmann import'), 'icon': 'sync',
                     'link': reverse_lazy('admin:cars_importrun_changelist')},
                    {'title': _('Groups'), 'icon': 'admin_panel_settings',
                     'link': reverse_lazy('admin:auth_group_changelist')},
                ],
            },
        ],
    },
}
