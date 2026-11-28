# FIBONACCI — exclusive car marketplace

Django marketplace for exclusive vehicles, in English and Russian.

- **Catalog**: All Vehicles and New Offers with two separate pickers that can be combined:
  **category** (engine type: combustion/petrol, diesel, hybrid, electric, gas) and
  **make**, plus accident history (no accidents / after an accident), **country** (only
  countries that have cars) and sorting by date or price — all as dropdowns; a vehicle page with gallery, gross/net price,
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
- **Search** in the header (or press `/`) and in the catalog: make, model or year, with
  instant results and photos; Russian spellings of popular makes work too («ламба», «мерс»).
- **Vehicle page:** fullscreen gallery (swipe, pinch / double-tap / wheel zoom, keyboard,
  swipe down or Back to close) and a "Similar vehicles" row (close price, same make first,
  then the same category).
- **Filters:** price from/to typed by hand in EUR or USD, and year from/to (suggested years
  1970 to today, or typed). Every listing has a country (Russia is not offered); imported
  Hollmann cars are set to Germany.
- **Favorites for guests:** kept in the session for 30 days after the last visit and moved
  to the account when the guest signs in.
- **Admin** on django-unfold: dashboard (listings to review, expiring soon, import status,
  new users, payments), sidebar with a moderation counter, coloured status labels.
- **Partnership page** (`/partnership/`) with the brand's links; edit them in
  `cars/partnership.py`.
- **Floating bottom menu** on every page: a full-width bar on phones, a pill on desktop.
- **Languages:** the site opens straight away: links keep their language (`/en/...`,
  `/ru/...`), the bare address follows the browser's language, and on the first visit a
  small offer to switch is shown if the browser prefers the other language. Pages have
  `hreflang` links, `/robots.txt` and `/sitemap.xml` cover both languages.
- **SEO and link previews:** schema.org data for search results (car with price and
  photos, breadcrumbs, organization, site search box); WhatsApp / Telegram / Facebook
  previews show the car photo, title and price.
- **Emails** are designed HTML (logo, car photo, button) with a plain-text version.

## Local development

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
printf "SECRET_KEY=change-me\nDEBUG=True\n" > .env
python manage.py migrate
python manage.py createsuperuser
python manage.py import_hollmann        # first import, takes a few minutes
python manage.py runserver
```

Without `POSTGRES_DB` in `.env` the project uses SQLite. Admin: http://localhost:8000/admin/

`DEBUG=True` is for your computer only: without it the site runs in production mode
(no debug pages, secure cookies) and will not serve photos over plain http.

## Front-end (CSS)

Styles are Tailwind CSS compiled into `assets/css/site.css`, which is committed, so the
server needs no Node.js. After changing classes in templates or `assets/src/site.css`:

```bash
npm install          # once
npm run build:css    # or: npm run watch:css while editing
```

Static files get a content hash in their names on `collectstatic`, so browsers cache them
for a year and still see every update.

## Photos

Seller photos are turned upright, stripped of EXIF/GPS, limited to 2000 px and saved under
random names. Every photo gets WebP copies (240, 480, 960, 1600 px) used for thumbnails,
cards, the vehicle page and the fullscreen viewer. `python manage.py process_photos` makes
missing copies (`--clean-uploads` also re-saves older seller photos without metadata,
`--all` remakes every copy). Photo files are deleted together with the photo.

## Daily jobs

| Command | What it does |
| --- | --- |
| `python manage.py import_hollmann` | Updates vehicles from hollmann.international, downloads new photos, hides sold cars and deletes their photos. The first run takes ~45 min (≈600 MB of photos), later runs only fetch what changed. Options: `--no-media`, `--no-details`, `--limit 10` (test on a few cars), `--delay 1.0`. |
| `python manage.py expire_listings` | Marks listings whose month is over as inactive. Visibility does not depend on it: expired listings are hidden at once. |
| `python manage.py send_expiry_reminders` | Emails owners whose listing expires within `LISTING_REMINDER_DAYS` (3). One email per listing period. |
| `python manage.py process_photos` | Makes WebP copies for photos that do not have them yet. |
| `python manage.py clearsessions` | Removes expired visitor sessions. |
| `python manage.py run_scheduler` | Runs all of the above every 24 hours in a loop (the `scheduler` service in docker-compose). |

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

## Security

- **Email confirmation:** accounts created with email and password stay inactive until the
  link in the confirmation email is clicked. Signing in with Google / Apple confirms the
  address; if someone had signed up with that address without confirming it, the Google /
  Apple owner gets the account and the earlier password stops working.
- **Brute-force protection** (django-axes): 5 wrong passwords for one email from one address
  lock logging in for 15 minutes, on the site and in the admin. Locked attempts are listed
  in the admin under **Axes → Access attempts**; delete a row there (or run
  `python manage.py axes_reset`) to unlock early. nginx also limits login and sign-up pages
  to 10 requests a minute per address.
- **Secret admin address:** set `ADMIN_URL=some-secret-path` in `.env`; the admin then lives
  at `https://<domain>/some-secret-path/` and `/admin/` returns 404.
- **Bot check** (Cloudflare Turnstile, free): add `TURNSTILE_SITE_KEY` and
  `TURNSTILE_SECRET_KEY` (Cloudflare dashboard → Turnstile → Add site) and sign-up and the
  new-listing form get an invisible "not a robot" check. Without keys it is off.
- **Content-Security-Policy:** browsers run only the site's own scripts (inline scripts
  carry a per-request nonce), so injected code would not run. `CSP_REPORT_ONLY=True` in
  `.env` switches it to report-only. The admin is not covered (it needs inline code).
- **Photo privacy:** location (GPS) and other metadata are removed from uploaded photos.
- **Email changes** take effect only after the new address is confirmed by a link.
- **Error reports:** set `SENTRY_DSN` (free plan at sentry.io) to be emailed about server
  errors; no personal data is sent.
- `DEBUG` is off unless `.env` says `DEBUG=True`.

## Moderation in Telegram

New and resubmitted listings come to a Telegram bot with photos, details and two buttons:
**✅ Approve** / **❌ Reject**. Rejecting asks for the reason (reply to the bot's message, or
send `-` for none). The decision works exactly like in the admin: the owner gets an email,
the reason shows as a moderator comment in their cabinet, and when they fix and resubmit the
listing, the bot shows the new version together with what you asked to fix. Approving
publishes it on the site. Decisions made in the admin also close the buttons in Telegram.

1. In Telegram open **@BotFather** → `/newbot` → copy the token.
2. On the server add to `.env` and restart (`docker compose up -d`):
   ```ini
   TELEGRAM_BOT_TOKEN=123456:ABC...
   ```
3. Connect the bot to the site: `docker compose exec web python manage.py telegram_webhook`
4. Send `/start` to your bot: it answers with your chat id. Add it to `.env` (several
   moderators: comma-separated) and restart:
   ```ini
   TELEGRAM_MODERATOR_CHAT_IDS=123456789
   ```

Only these chat ids can approve or reject.

## Cloudflare (protection)

The site is ready to run behind Cloudflare (DDoS protection, bot filtering, CDN):
nginx takes the visitor's real address from `CF-Connecting-IP` (trusted only from
Cloudflare's ranges), so the login rate limit, the admin lockout and analytics keep working;
analytics takes the country from `CF-IPCountry`.

1. Add the domain in Cloudflare (free plan), check that **all** DNS records were copied
   (mail records: MX, SPF, DKIM, DMARC, Brevo — keep them **DNS only**, grey cloud), and set the
   `@` and `www` A records to the server IP with the **orange cloud** (proxied).
2. Change the nameservers at the domain registrar to the two Cloudflare gives.
3. SSL/TLS → **Full (strict)** (the server keeps its Let's Encrypt certificate);
   Always Use HTTPS on. Security → Bots → Bot Fight Mode on. Keep **Rocket Loader off**
   and Cloudflare Web Analytics off (they conflict with the site's Content-Security-Policy).
4. When the site opens through Cloudflare, close the server's IP to everyone else:
   add `CLOUDFLARE_ONLY=yes` to `.env` and run `docker compose up -d nginx`. Direct requests to
   the IP then get no answer. To undo, set it to `no`.

Cloudflare's address ranges are in `deploy/nginx.conf.template` (from
https://www.cloudflare.com/ips; they change rarely).

## Site analytics

Admin → **Analytics** shows who visits the site, kept in our own database (no Google
Analytics, nothing for ad blockers to cut):

- **live**: how many people have the site open right now and on which pages;
- periods: now, last hour, today, yesterday, 7 / 30 days, any month, any year, any dates —
  each number compared with the same length of time before;
- visitors, new visitors, page views, vehicle views, contact clicks (call / WhatsApp /
  Telegram on vehicle pages), contact rate, saves to favorites; a chart over time;
- vehicles from the most viewed to the ones nobody opens (with contacts and favorites);
- sources (Google, Instagram, Telegram, utm_source…), countries, devices, browsers,
  systems, site language, pages; a table of every month of the year;
- filters: device, country, source, language, page type, new / returning, signed in, make.

Visitors are counted **without cookies**: a visitor is a hash of the IP address and the
browser, the IP itself is not stored. Bots and your own visits as staff are not counted.
Countries come from the free DB-IP Lite database, downloaded by the daily jobs
(`python manage.py update_geoip`). Data older than `ANALYTICS_RETENTION_DAYS` (800 days)
is deleted. Times are shown in `ADMIN_TIME_ZONE` (Europe/Berlin by default).

## Automatic translation of descriptions

A seller writes the description in Russian or English; the site shows it translated into the
other language automatically (with “Show original” under it). Imported Hollmann descriptions
are translated too. It uses the DeepL API: the free plan gives 500,000 characters a month,
and each description is translated only once (again only when it changes).

1. Create a free account at deepl.com → **DeepL API** → copy the key (it ends in `:fx`).
2. On the server add to `.env` and restart (`docker compose up -d`):
   ```ini
   DEEPL_API_KEY=...:fx
   ```
3. Translate the current catalog once (later it runs daily after the import, and new
   seller listings are translated right after saving):
   `docker compose exec web python manage.py translate_listings`

Without the key everything works as before: the original is shown in both languages.
A translation can be corrected by hand in the admin (vehicle → Automatic translation).

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
