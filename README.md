# FIBONACCI — exclusive car marketplace

Django marketplace for exclusive vehicles, in English and Russian.

- **Catalog** with the structure of hollmann.international: All Vehicles, New Offers,
  collections (Customized, Armoured, Oldtimer, Electric) and manufacturers, sorting by
  name / date / price, and a vehicle page with gallery, gross/net price, details table,
  description and contacts.
- **Daily import** from hollmann.international: make, model, prices, collections and the
  specification table, with a link to the original offer. Photos, descriptions and staff
  contacts are not copied.
- **User accounts** (email, phone, country, full name) with a cabinet: add vehicles for
  sale, edit, deactivate/activate, delete, and a favorites list.
- **Listings run for 30 days.** When the month is over the listing is hidden immediately
  and stays inactive until the owner activates it again from the cabinet. Activation is
  free for now; paid activation (5 EUR / month) is prepared but not implemented.
- **Language choice first:** on the first visit to any page the visitor chooses English or
  Russian, then the site continues to the requested page (`/en/...`, `/ru/...`).

## Local development

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
echo "SECRET_KEY=change-me" > .env
python manage.py migrate
python manage.py createsuperuser
python manage.py import_hollmann        # first import, takes a few minutes
python manage.py runserver
```

Without `POSTGRES_DB` in `.env` the project uses SQLite. Admin: http://localhost:8000/admin/

## Daily jobs

| Command | What it does |
| --- | --- |
| `python manage.py import_hollmann` | Updates vehicles from hollmann.international. Vehicles no longer listed there are hidden. Options: `--no-details` (listing pages only), `--delay 1.0`. |
| `python manage.py expire_listings` | Marks listings whose month is over as inactive. Visibility does not depend on it: expired listings are hidden at once. |
| `python manage.py run_scheduler` | Runs both commands every 24 hours in a loop (the `scheduler` service in docker-compose). |

Instead of the scheduler you can use cron:

```cron
15 3 * * * cd /app && python manage.py expire_listings && python manage.py import_hollmann
```

Every import is recorded in the admin under **Import runs**, with errors if any.

## Listing lifecycle and future payments

Settings in `enf/settings.py` (override with environment variables):

```ini
LISTING_DURATION_DAYS=30
LISTING_PRICE_EUR=5.00
LISTING_PAYMENT_REQUIRED=False
```

Each activation creates a `ListingPeriod` record (start, end, amount, method). To add paid
activation, implement the payment in `cars.views.car_activate` (the
`LISTING_PAYMENT_REQUIRED` branch) and call `car.activate(paid_amount=..., method='stripe')`
after a successful payment.

## Translations

Russian strings live in `locale/ru/LC_MESSAGES/django.po`; the compiled `django.mo` is
committed. After changing texts:

```bash
python manage.py makemessages -l ru
# edit locale/ru/LC_MESSAGES/django.po
python manage.py compilemessages
```

## Docker / production

Fill `.env`:

```ini
SECRET_KEY=...
DEBUG=False
POSTGRES_DB=enfdb
POSTGRES_USER=enfdb
POSTGRES_PASSWORD=enfdb
POSTGRES_HOST=db
POSTGRES_PORT=5432
```

```bash
docker-compose up --build -d
docker-compose exec web python manage.py collectstatic --no-input
docker-compose exec web python manage.py createsuperuser
```

Services: `db` (PostgreSQL), `web` (gunicorn), `scheduler` (daily jobs), `nginx`.

## Tests

```bash
python manage.py test
```
