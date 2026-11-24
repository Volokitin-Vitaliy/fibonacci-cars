"""Photo files follow their database rows: copies are made on save, files removed on delete."""

from django.db import transaction

from . import images


def photo_saved(sender, instance, created, **kwargs):
    if created and instance.image and not instance.variants:
        transaction.on_commit(lambda: images.make_variants(instance))


def photo_deleted(sender, instance, **kwargs):
    if instance.image:
        name, widths = instance.image.name, list(instance.variants or [])
        transaction.on_commit(lambda: images.delete_files(name, widths))
