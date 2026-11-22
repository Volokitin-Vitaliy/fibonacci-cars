from django.db import migrations
from django.utils.text import slugify

CATEGORIES = [
    # (hollmann id, slug, English, Russian)
    (1, 'customized', 'Customized', 'Тюнинг'),
    (2, 'armoured', 'Armoured', 'Бронированные'),
    (3, 'oldtimer', 'Oldtimer', 'Олдтаймеры'),
    (4, 'electric', 'Electric', 'Электромобили'),
]

# Manufacturers listed on hollmann.international, plus common makes so private
# sellers can list everyday cars too. The daily import adds any new ones.
MAKES = [
    'Aston Martin', 'Audi', 'BMW', 'Bentley', 'Brabus', 'Bugatti', 'Dembell', 'Dodge',
    'Ducati', 'Ferrari', 'Ford', 'Franken Autodesign', 'Hymer', 'KTM', 'Lamborghini',
    'Land Rover', 'Lexus', 'Mansory', 'Maybach', 'McLaren', 'Mercedes-Benz', 'Nissan',
    'Novitec', 'Porsche', 'Rolls-Royce', 'Techart', 'Tijhof', 'Toyota', 'Trasco',
    'Volkswagen',
    'Alfa Romeo', 'Cadillac', 'Chevrolet', 'Citroën', 'Cupra', 'Fiat', 'Genesis', 'GMC',
    'Honda', 'Hyundai', 'Infiniti', 'Jaguar', 'Jeep', 'Kia', 'Lincoln', 'Lotus',
    'Maserati', 'Mazda', 'MINI', 'Mitsubishi', 'Opel', 'Peugeot', 'Polestar', 'RAM',
    'Renault', 'SEAT', 'Škoda', 'Subaru', 'Suzuki', 'Tesla', 'Volvo',
]


def seed(apps, schema_editor):
    Category = apps.get_model('cars', 'Category')
    Make = apps.get_model('cars', 'Make')
    for position, (hid, slug, en, ru) in enumerate(CATEGORIES):
        Category.objects.update_or_create(
            slug=slug, defaults={'hollmann_id': hid, 'name_en': en, 'name_ru': ru,
                                 'position': position})
    for name in MAKES:
        Make.objects.get_or_create(name=name, defaults={'slug': slugify(name)})


class Migration(migrations.Migration):

    dependencies = [
        ('cars', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
