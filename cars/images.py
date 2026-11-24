"""Photo processing: clean uploads, and smaller WebP copies for fast pages.

* Uploaded photos are turned upright, stripped of all metadata (EXIF, including the GPS
  position where the photo was taken), limited to MAX_SIDE pixels and saved as JPEG
  under a random name.
* Every photo gets WebP copies in VARIANT_WIDTHS (only those smaller than the photo) so
  cards and thumbnails download a few dozen kilobytes instead of the full picture.
"""

import logging
import posixpath
import uuid
from io import BytesIO

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

MAX_SIDE = 2000
JPEG_QUALITY = 86
VARIANT_WIDTHS = (480, 960, 1600)
WEBP_QUALITY = 80


def _rgb(image):
    if image.mode in ('P', 'RGBA', 'LA'):
        image = image.convert('RGBA')
        background = Image.new('RGB', image.size, (17, 17, 17))
        background.paste(image, mask=image.split()[-1])
        return background
    return image.convert('RGB')


def clean_upload(uploaded):
    """A cleaned JPEG copy of an uploaded image, ready for ImageField.save()."""
    uploaded.seek(0)
    image = Image.open(uploaded)
    image = ImageOps.exif_transpose(image)  # phones store rotation in EXIF
    image = _rgb(image)
    image.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    out = BytesIO()
    # A fresh image object carries no EXIF/GPS/ICC metadata unless passed explicitly.
    image.save(out, 'JPEG', quality=JPEG_QUALITY, optimize=True, progressive=True)
    return ContentFile(out.getvalue(), name=f'{uuid.uuid4().hex}.jpg')


def variant_path(name, width):
    folder, filename = posixpath.split(name)
    stem = posixpath.splitext(filename)[0]
    return posixpath.join(folder, 'v', f'{stem}-{width}.webp')


def make_variants(photo):
    """Create the WebP copies for a CarPhoto and remember which widths exist."""
    try:
        with photo.image.open('rb') as f:
            image = _rgb(Image.open(f))
            image.load()
    except (OSError, ValueError) as exc:
        logger.warning('Cannot make variants for photo %s: %s', photo.pk, exc)
        return []
    widths = []
    for width in VARIANT_WIDTHS:
        if width >= image.width:
            break
        copy = image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)
        out = BytesIO()
        copy.save(out, 'WEBP', quality=WEBP_QUALITY, method=5)
        path = variant_path(photo.image.name, width)
        if default_storage.exists(path):
            default_storage.delete(path)
        default_storage.save(path, ContentFile(out.getvalue()))
        widths.append(width)
    # The full-size picture as WebP too: smaller than the JPEG at the same quality.
    out = BytesIO()
    image.save(out, 'WEBP', quality=WEBP_QUALITY + 4, method=5)
    path = variant_path(photo.image.name, image.width)
    if default_storage.exists(path):
        default_storage.delete(path)
    default_storage.save(path, ContentFile(out.getvalue()))
    widths.append(image.width)
    type(photo).objects.filter(pk=photo.pk).update(variants=widths)
    photo.variants = widths
    return widths


def delete_files(name, widths):
    for path in [name] + [variant_path(name, w) for w in widths or []]:
        try:
            if path and default_storage.exists(path):
                default_storage.delete(path)
        except OSError:
            logger.warning('Could not delete %s', path)
