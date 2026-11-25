from django.db import migrations
from django.utils.text import slugify


SLUGS = {'ГАЗ': 'gaz', 'ВАЗ': 'vaz'}  # URLs use Latin letters only


def add_makes(apps, schema_editor):
    from cars.makes_data import MAKES, normalize
    Make = apps.get_model('cars', 'Make')
    existing = {normalize(m.name) for m in Make.objects.all()}
    for name in MAKES:
        if normalize(name) in existing:  # 'Citroën' already there covers 'Citroen'
            continue
        existing.add(normalize(name))
        base = SLUGS.get(name) or slugify(name) or 'make'
        slug, n = base, 2
        while Make.objects.filter(slug=slug).exists():
            slug, n = f'{base}-{n}', n + 1
        Make.objects.create(name=name, slug=slug)


class Migration(migrations.Migration):
    dependencies = [('cars', '0010_photo_variants')]
    operations = [migrations.RunPython(add_makes, migrations.RunPython.noop)]
