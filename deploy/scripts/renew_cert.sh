#!/usr/bin/env bash
# Продление сертификата (запускается по cron). Без изменений, если продлевать рано.
set -euo pipefail
cd "$(dirname "$0")/../.."
docker run --rm \
  -v "$PWD/deploy/certbot/conf:/etc/letsencrypt" \
  -v "$PWD/deploy/certbot/www:/var/www/certbot" \
  certbot/certbot renew --webroot -w /var/www/certbot -q
docker compose exec -T web nginx -s reload
