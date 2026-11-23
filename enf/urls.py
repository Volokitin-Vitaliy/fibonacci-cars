from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.conf.urls.static import static
from django.contrib import admin
from django.templatetags.static import static as static_url
from django.urls import include, path
from django.views.generic import RedirectView

from django.contrib.sitemaps.views import sitemap

from cars import views as car_views
from cars.sitemaps import sitemaps

urlpatterns = [
    path('admin/', admin.site.urls),
    path('i18n/', include('django.conf.urls.i18n')),
    path('choose-language/', car_views.choose_language, name='choose_language'),
    path('payments/stripe/webhook/', car_views.stripe_webhook, name='stripe_webhook'),
    path('robots.txt', car_views.robots_txt, name='robots_txt'),
    path('favicon.ico', RedirectView.as_view(url=static_url('favicon.ico'), permanent=True)),
    path('accounts/', include('allauth.urls')),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps},
         name='django.contrib.sitemaps.views.sitemap'),
]

urlpatterns += i18n_patterns(
    path('users/', include('users.urls', namespace='users')),
    path('', include('cars.urls', namespace='cars')),
)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL,
                          document_root=settings.MEDIA_ROOT)
