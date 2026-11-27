from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CarsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'cars'
    verbose_name = _('Vehicles')

    def ready(self):
        from django.contrib.auth.signals import user_logged_in

        from django.db.models.signals import post_delete, post_save

        from .favorites import merge_guest_favorites
        from .models import Car, CarPhoto
        from .signals import car_saved, photo_deleted, photo_saved
        user_logged_in.connect(merge_guest_favorites, dispatch_uid='merge_guest_favorites')
        post_save.connect(photo_saved, sender=CarPhoto, dispatch_uid='photo_saved')
        post_delete.connect(photo_deleted, sender=CarPhoto, dispatch_uid='photo_deleted')
        post_save.connect(car_saved, sender=Car, dispatch_uid='car_saved')
