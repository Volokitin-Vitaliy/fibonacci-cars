from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CarsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'cars'
    verbose_name = _('Vehicles')

    def ready(self):
        from django.contrib.auth.signals import user_logged_in

        from .favorites import merge_guest_favorites
        user_logged_in.connect(merge_guest_favorites, dispatch_uid='merge_guest_favorites')
