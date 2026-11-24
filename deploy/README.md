# Deploying FIBONACCI

A single VPS with Docker runs everything: PostgreSQL, the site (gunicorn), the daily
scheduler (Hollmann import, reminders), nginx with HTTPS and automatic certificate renewal.

Recommended: **Hetzner Cloud CX22** (2 vCPU, 4 GB RAM, 40 GB SSD, ~€4.5/month), location
Falkenstein/Nuremberg, image **Ubuntu 24.04**. Any VPS with 2 GB+ RAM and 20 GB+ disk works.

## 1. Domain → server

At your domain registrar create two DNS records pointing to the server's IPv4 address:

| Type | Name  | Value          |
|------|-------|----------------|
| A    | `@`   | `SERVER_IP`    |
| A    | `www` | `SERVER_IP`    |

Wait until `ping your-domain.com` shows the server IP (usually 5–30 minutes).

## 2. Prepare the server

```bash
ssh root@SERVER_IP
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
git clone https://github.com/Volokitin-Vitaliy/fibonacci-cars.git /opt/fibonacci
cd /opt/fibonacci
```

## 3. Configure

```bash
cp deploy/env.example .env
nano .env        # fill in DOMAIN, SITE_URL, SECRET_KEY, passwords, keys
```

## 4. HTTPS certificate (once)

Port 80 must be free, so run this before starting the site:

```bash
docker run --rm -p 80:80 -v /etc/letsencrypt:/etc/letsencrypt certbot/certbot \
  certonly --standalone -d your-domain.com -d www.your-domain.com \
  --email you@example.com --agree-tos --no-eff-email
```

Renewal is automatic afterwards (the `certbot` service checks twice a day,
nginx reloads every 6 hours).

## 5. Start

```bash
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
docker compose exec scheduler python manage.py import_hollmann   # first import, ~45 min
```

The site is at `https://your-domain.com`, the admin at `https://your-domain.com/<ADMIN_URL>/`
(the secret address from `.env`).

## Updating to a new version

```bash
cd /opt/fibonacci
git pull
docker compose up -d --build
```

Migrations and static files run automatically on start.

**Once after updating to the version with photo sizes** (makes the small WebP copies
and removes location data from photos sellers uploaded earlier, ~10 minutes):

```bash
docker compose exec scheduler python manage.py process_photos --clean-uploads
```

Later photos get their copies automatically; the daily jobs also catch any that were missed.

## Backups

Database dump every night at 04:30, kept for 14 days:

```bash
mkdir -p /opt/backups
crontab -e
# add:
30 4 * * * docker compose -f /opt/fibonacci/docker-compose.yml exec -T db pg_dump -U fibonacci fibonacci | gzip > /opt/backups/db-$(date +\%F).sql.gz && find /opt/backups -name 'db-*.sql.gz' -mtime +14 -delete
```

Photos live in the Docker volume `fibonacci_media`; Hollmann photos are re-downloaded by the
import, user photos should be backed up too (e.g. Hetzner's automatic server backups, +20%).

## Useful commands

```bash
docker compose ps                     # what is running
docker compose logs -f web            # site logs
docker compose logs -f scheduler      # daily import logs
docker compose restart web            # restart the site after changing .env
```
