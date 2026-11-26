from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.conf.urls.static import static
from django.contrib import admin
from django.templatetags.static import static as static_url
from django.shortcuts import redirect
from django.urls import include, path, reverse
from django.views.generic import RedirectView

from django.contrib.sitemaps.views import sitemap

from cars import views as car_views
from cars.sitemaps import sitemaps

def admin_login(request):
    # Signing in at /admin/login/ directly should open the admin, not the
    # site cabinet (LOGIN_REDIRECT_URL); the login form posts to its own URL.
    if 'next' not in request.GET:
        return redirect(f"{request.path}?next={reverse('admin:index')}")
    return admin.site.login(request)


urlpatterns = [
    path(f'{settings.ADMIN_URL}login/', admin_login),
    path(settings.ADMIN_URL, admin.site.urls),
    path('i18n/setlang/', car_views.set_language, name='set_language'),
    path('i18n/', include('django.conf.urls.i18n')),
    path('choose-language/', car_views.choose_language, name='choose_language'),
    path('telegram/webhook/', car_views.telegram_webhook, name='telegram_webhook'),
    path('payments/stripe/webhook/', car_views.stripe_webhook, name='stripe_webhook'),
    path('payments/wayforpay/callback/', car_views.wayforpay_callback, name='wayforpay_callback'),
    path('payments/wayforpay/return/', car_views.wayforpay_return, name='wayforpay_return'),
    path('payments/wayforpay/done/', car_views.wayforpay_done, name='wayforpay_done'),
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
