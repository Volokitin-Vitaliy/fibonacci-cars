# FIBONACCI — exclusive car marketplace

Django marketplace for exclusive vehicles, in English and Russian.

- **Catalog**: All Vehicles and New Offers with two separate pickers that can be combined:
  **category** (engine type: combustion/petrol, diesel, hybrid, electric, gas) and
  **make**, plus accident history (no accidents / after an accident), seller and sorting by
  date or price — all as dropdowns; a vehicle page with gallery, gross/net price,
  details table, description and contacts.
- **Daily import** from hollmann.international (with their permission): make, model,
  prices, engine type, specification table, **photos** (copied and re-compressed, up to 20
  per car), **description** (sanitized HTML) and **dealer contacts** with portraits. Cars
  sold or removed on their site are hidden here and their photos deleted.
- **User accounts** (full name, email, country; or one click with Google / Apple) with a
  cabinet: add vehicles for sale with phone, WhatsApp and Telegram contacts, edit,
  deactivate/activate, delete, and a favorites list.
- **Moderation:** new and edited listings wait for an admin to approve them (admin list
  filter "moderation", actions "Approve/Reject selected"). Owners get an email either way.
- **Listings run for 30 days** from approval. Three days before the end the owner gets an
  email; when the month is over the listing is hidden immediately and stays inactive until
  the owner activates it again from the cabinet.
- **Paid listings via WayForPay** (or Stripe): 10 EUR when a listing is submitted and when
  it is reactivated; switched off by default.
- **Filters** by price (EUR, USD converted), year and mileage.
- **Favorites for guests:** kept in the session for 30 days after the last visit and moved
  to the account when the guest signs in.
- **Admin** on django-unfold: dashboard (listings to review, expiring soon, import status,
  new users, payments), sidebar with a moderation counter, coloured status labels.
- **Partnership page** (`/partnership/`) with the brand's links; edit them in
  `cars/partnership.py`.
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
| `python manage.py import_hollmann` | Updates vehicles from hollmann.international, downloads new photos, hides sold cars and deletes their photos. The first run takes ~45 min (≈600 MB of photos), later runs only fetch what changed. Options: `--no-media`, `--no-details`, `--limit 10` (test on a few cars), `--delay 1.0`. |
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
LISTING_PAYMENT_REQUIRED=False # True = a listing costs LISTING_PRICE_EUR
LISTING_PRICE_EUR=10.00
USD_TO_EUR_RATE=0.92           # for filtering/sorting prices across currencies
```

Lifecycle: created → (**awaiting payment** → paid, when payments are on) → **pending
review** → approved (the month starts) → reminder 3 days before the end → **inactive** →
owner activates again (pays again when payments are on). Editing an approved listing sends it
back to review; its remaining time is kept. Each period is stored as a `ListingPeriod`.

### Turning on WayForPay (10 EUR per listing)

1. In the WayForPay merchant cabinet open your store → **Store settings** and copy the
   **Merchant login** (merchantAccount) and **Merchant secret key**. The store's domain must
   be your site's domain.
2. Ask WayForPay support to enable **EUR** for the store if it is not enabled (by default
   stores usually accept UAH).
3. Put the keys in `.env` on the server (never in the code):

```ini
PAYMENT_PROVIDER=wayforpay
WAYFORPAY_MERCHANT_ACCOUNT=your_merchant_login
WAYFORPAY_SECRET_KEY=your_secret_key
WAYFORPAY_DOMAIN=domen.com
SITE_URL=https://domen.com
LISTING_PRICE_EUR=10.00
LISTING_PAYMENT_REQUIRED=True
```

The site sends WayForPay the result address itself
(`https://<domain>/payments/wayforpay/callback/`); it must be reachable from the internet
over HTTPS. Flow: the seller fills in the listing → pays on the WayForPay page → the
listing goes to moderation → on approval the paid 30 days start. Reactivating an expired
listing costs 10 EUR again and starts right away. Payments are in the admin under
**Payments**.

For a test run, WayForPay's public test store can be used:
`WAYFORPAY_MERCHANT_ACCOUNT=test_merch_n1`, `WAYFORPAY_SECRET_KEY=flk3409refn54t54t*FNJRET`
(test cards from the WayForPay documentation).

### Stripe (alternative)

Set `PAYMENT_PROVIDER=stripe`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` and create a webhook
to `https://<domain>/payments/stripe/webhook/` (events `checkout.session.completed`,
`checkout.session.async_payment_succeeded`, `checkout.session.expired`,
`checkout.session.async_payment_failed`).

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

Step-by-step server setup (VPS, domain, HTTPS, backups): **[deploy/README.md](deploy/README.md)**.
Template for the server's `.env`: [deploy/env.example](deploy/env.example).

Services: `db` (PostgreSQL 16), `web` (gunicorn), `scheduler` (daily jobs), `nginx` (HTTPS,
static and media files), `certbot` (certificate renewal).

## Tests

```bash
python manage.py test
```
