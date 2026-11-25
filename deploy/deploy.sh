#!/usr/bin/env bash
# Updates the site on the server to the latest master. Run by GitHub Actions after every
# merge (see .github/workflows/deploy.yml), or by hand: bash /opt/fibonacci/deploy/deploy.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/fibonacci}"
BACKUP_DIR="${BACKUP_DIR:-/opt/backups}"
cd "$APP_DIR"
DOMAIN="$(grep -E '^DOMAIN=' .env | cut -d= -f2-)"
PG_USER="$(grep -E '^POSTGRES_USER=' .env | cut -d= -f2-)"
PG_DB="$(grep -E '^POSTGRES_DB=' .env | cut -d= -f2-)"

echo "==> Current version: $(git rev-parse --short HEAD)"
git fetch --quiet origin master
NEW="$(git rev-parse --short origin/master)"

# A copy of the database before every update (the last 10 are kept).
mkdir -p "$BACKUP_DIR"
if docker compose ps --status running --services 2>/dev/null | grep -qx db; then
    echo "==> Backing up the database"
    docker compose exec -T db pg_dump -U "$PG_USER" "$PG_DB" | gzip > "$BACKUP_DIR/pre-deploy-$(date +%F-%H%M)-$NEW.sql.gz"
    ls -1t "$BACKUP_DIR"/pre-deploy-*.sql.gz | tail -n +11 | xargs -r rm --
fi

echo "==> Updating to $NEW"
git reset --hard --quiet origin/master
docker compose up -d --build --remove-orphans
docker compose restart nginx   # picks up nginx config changes
docker image prune -f >/dev/null

echo "==> Checking that the site answers"
for i in $(seq 1 30); do
    if curl -fsS -o /dev/null --max-time 10 --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/robots.txt"; then
        echo "==> Done: https://$DOMAIN is running version $NEW"
        exit 0
    fi
    sleep 5
done
echo "!! The site did not answer after the update. Logs:" >&2
docker compose logs --tail 80 web >&2
exit 1
