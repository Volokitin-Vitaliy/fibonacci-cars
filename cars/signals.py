"""Photo files follow their database rows: copies are made on save, files removed on delete."""

from django.db import transaction

from . import images, translation


def photo_saved(sender, instance, created, **kwargs):
    if created and instance.image and not instance.variants:
        transaction.on_commit(lambda: images.make_variants(instance))


def photo_deleted(sender, instance, **kwargs):
    if instance.image:
        name, widths = instance.image.name, list(instance.variants or [])
        transaction.on_commit(lambda: images.delete_files(name, widths))


def car_saved(sender, instance, **kwargs):
    """A seller's description is translated as soon as it is saved; imported cars
    are translated in one go after the import (translate_listings)."""
    if instance.source == instance.Source.USER and translation.needs_translation(instance):
        translation.translate_in_background(instance.pk)
