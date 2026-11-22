from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from cars import views as car_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('i18n/', include('django.conf.urls.i18n')),
    path('choose-language/', car_views.choose_language, name='choose_language'),
]

urlpatterns += i18n_patterns(
    path('users/', include('users.urls', namespace='users')),
    path('', include('cars.urls', namespace='cars')),
)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL,
                          document_root=settings.MEDIA_ROOT)
