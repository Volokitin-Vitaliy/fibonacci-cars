from django.db import migrations


def no_accidents(apps, schema_editor):
    """Hollmann sells accident-free cars: mark the imported ones (the importer does it from now on)."""
    apps.get_model('cars', 'Car').objects.filter(source='hollmann').update(accident=False)


class Migration(migrations.Migration):
    dependencies = [('cars', '0015_description_translation')]
    operations = [migrations.RunPython(no_accidents, migrations.RunPython.noop)]
