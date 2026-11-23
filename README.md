# FIBONACCI — exclusive car marketplace

Django marketplace for exclusive vehicles, in English and Russian.

- **Catalog**: All Vehicles and New Offers with two separate pickers that can be combined:
  **category** (engine type: combustion/petrol, diesel, hybrid, electric, gas) and
  **make**; sorting by date or price; a vehicle page with gallery, gross/net price,
  details table, description and contacts.
- **Daily import** from hollmann.international: make, model, prices, engine type and the
  specification table, with a link to the original offer. Photos, descriptions and staff
  contacts are not copied.
- **User accounts** (full name, email, country; or one click with Google / Apple) with a
  cabinet: add vehicles for sale with phone, WhatsApp and Telegram contacts, edit,
  deactivate/activate, delete, and a favorites list.
- **Moderation:** new and edited listings wait for an admin to approve them (admin list
  filter "moderation", actions "Approve/Reject selected"). Owners get an email either way.
- **Listings run for 30 days** from approval. Three days before the end the owner gets an
  email; when the month is over the listing is hidden immediately and stays inactive until
  the owner activates it again from the cabinet.
- **Paid activation via Stripe** (5 EUR per month), switched off by default.
- **Filters** by price (EUR, USD converted), year and mileage.
- **Favorites for guests:** kept in the session for 30 days after the last visit and moved
  to the account when the guest signs in.
- **Admin** on django-unfold: dashboard (listings to review, expiring soon, import status,
  new users, payments), sidebar with a moderation counter, coloured status labels.
- **Floating bottom menu** on every page: a full-width bar on phones, a pill on desktop.
- **Language choice first:** on the first visit to any page the visitor chooses English or
  Russian, then the site continues to the requested page (`/en/...`, `/ru/...`).
  Search engines skip the picker; pages have `hreflang` links, `/robots.txt` and
  `/sitemap.xml` cover both languages.

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
| `python manage.py send_expiry_reminders` | Emails owners whose listing expires within `LISTING_REMINDER_DAYS` (3). One email per listing period. |
| `python manage.py run_scheduler` | Runs all three commands every 24 hours in a loop (the `scheduler` service in docker-compose). |

Instead of the scheduler you can use cron:

```cron
15 3 * * * cd /app && python manage.py expire_listings && python manage.py send_expiry_reminders && python manage.py import_hollmann
```

Every import is recorded in the admin under **Import runs**, with errors if any.

## Listings, moderation and payments

```ini
LISTING_DURATION_DAYS=30
LISTING_REMINDER_DAYS=3
LISTING_MODERATION=True        # new/edited listings need approval
LISTING_PAYMENT_REQUIRED=False # True = activation costs LISTING_PRICE_EUR via Stripe
LISTING_PRICE_EUR=5.00
USD_TO_EUR_RATE=0.92           # for filtering/sorting prices across currencies
```

Lifecycle: created → **pending review** → approved (first month starts, or the owner pays
first when payments are on) → reminder 3 days before the end → **inactive** → owner
activates again (pays again when payments are on). Editing an approved listing sends it
back to review; its remaining time is kept. Each period is stored as a `ListingPeriod`.

### Turning on Stripe payments

1. In the Stripe dashboard create a webhook endpoint
   `https://<your-domain>/payments/stripe/webhook/` with the events
   `checkout.session.completed`, `checkout.session.async_payment_succeeded`,
   `checkout.session.expired`, `checkout.session.async_payment_failed`.
2. Put the keys in `.env` and switch payments on:

```ini
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
LISTING_PAYMENT_REQUIRED=True
```

The owner presses "Activate for €5", pays on Stripe Checkout and the listing becomes active
for 30 days. Payments are listed in the admin under **Payments**. For local testing use test
keys and `stripe listen --forward-to localhost:8000/payments/stripe/webhook/`.

## Email

Without `EMAIL_HOST` emails are printed to the console. For real sending:

```ini
SITE_URL=https://domen.com          # used for links in emails
DEFAULT_FROM_EMAIL=FIBONACCI <no-reply@domen.com>
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=...
EMAIL_HOST_PASSWORD=...
EMAIL_USE_TLS=True
MODERATION_EMAILS=admin@domen.com    # told about listings waiting for review
```

Emails to owners are sent in the language they last used on the site.

## Sign in with Google and Apple

The buttons appear on the login and sign-up pages as soon as the keys are in `.env`.
Accounts with the same email are linked automatically.

**Google** — [Google Cloud Console](https://console.cloud.google.com/apis/credentials):
create an *OAuth client ID* of type *Web application* and add the redirect URI
`https://<your-domain>/accounts/google/login/callback/`
(for local testing also `http://127.0.0.1:8000/accounts/google/login/callback/`).

```ini
GOOGLE_CLIENT_ID=....apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=...
```

**Apple** — needs a paid Apple Developer account. In *Certificates, Identifiers & Profiles*
create an App ID with *Sign in with Apple*, a *Services ID* (this is the client id) with the
domain and return URL `https://<your-domain>/accounts/apple/login/callback/`, and a *Key*
with *Sign in with Apple* (download the `.p8` file). Apple does not allow `localhost`, so it
only works on the real domain over HTTPS.

```ini
APPLE_SERVICE_ID=com.example.web
APPLE_TEAM_ID=ABCDE12345
APPLE_KEY_ID=XYZ987WVU6
APPLE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
```

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
