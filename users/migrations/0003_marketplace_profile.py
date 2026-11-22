import django_countries.fields
from django.db import migrations, models


def clean_countries(apps, schema_editor):
    """Free-text countries from the old shop do not fit two-letter codes."""
    CustomUser = apps.get_model('users', 'CustomUser')
    CustomUser.objects.filter(country__isnull=True).update(country='')
    for user in CustomUser.objects.exclude(country=''):
        if len(user.country) != 2:
            user.country = ''
            user.save(update_fields=['country'])
        else:
            user.country = user.country.upper()
            user.save(update_fields=['country'])


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0002_alter_customuser_managers_and_more'),
    ]

    operations = [
        migrations.RunPython(clean_countries, migrations.RunPython.noop),
        migrations.RemoveField(model_name='customuser', name='address1'),
        migrations.RemoveField(model_name='customuser', name='address2'),
        migrations.RemoveField(model_name='customuser', name='city'),
        migrations.RemoveField(model_name='customuser', name='company'),
        migrations.RemoveField(model_name='customuser', name='postal_code'),
        migrations.RemoveField(model_name='customuser', name='province'),
        migrations.AddField(
            model_name='customuser',
            name='middle_name',
            field=models.CharField(blank=True, max_length=50, verbose_name='middle name'),
        ),
        migrations.AlterField(
            model_name='customuser',
            name='country',
            field=django_countries.fields.CountryField(blank=True, default='', max_length=2, verbose_name='country'),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='customuser',
            name='phone',
            field=models.CharField(blank=True, max_length=30, null=True, unique=True, verbose_name='phone'),
        ),
        migrations.AlterField(
            model_name='customuser',
            name='email',
            field=models.EmailField(max_length=254, unique=True, verbose_name='email'),
        ),
        migrations.AlterField(
            model_name='customuser',
            name='first_name',
            field=models.CharField(max_length=50, verbose_name='first name'),
        ),
        migrations.AlterField(
            model_name='customuser',
            name='last_name',
            field=models.CharField(max_length=50, verbose_name='last name'),
        ),
    ]
