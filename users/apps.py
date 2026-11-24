from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'users'

    def ready(self):
        from django.db.models.signals import post_save

        from .models import CustomUser
        from .signals import sync_verified_email
        post_save.connect(sync_verified_email, sender=CustomUser, dispatch_uid='sync_verified_email')
