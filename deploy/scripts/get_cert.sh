#!/usr/bin/env bash
# Получает сертификат Let's Encrypt и переключает nginx в режим https.
# Перед запуском: A-запись домена указывает на IP ВМ, сайт открывается по http.
# Запуск из корня проекта: bash deploy/scripts/get_cert.sh
set -euo pipefail
cd "$(dirname "$0")/../.."

DOMAIN=$(grep -E '^DOMAIN=' .env | cut -d= -f2-)
EMAIL=$(grep -E '^LETSENCRYPT_EMAIL=' .env | cut -d= -f2-)
[ -n "$DOMAIN" ] && [ -n "$EMAIL" ] || { echo "Заполните DOMAIN и LETSENCRYPT_EMAIL в .env"; exit 1; }

echo "==> Проверка, что домен смотрит на этот сервер"
MYIP=$(curl -fsS https://ifconfig.me || true)
DNSIP=$(getent ahostsv4 "$DOMAIN" | awk 'NR==1{print $1}' || true)
echo "IP сервера: ${MYIP:-?}   IP домена: ${DNSIP:-?}"
if [ -n "$MYIP" ] && [ "$MYIP" != "$DNSIP" ]; then
  echo "ВНИМАНИЕ: домен пока указывает не на этот сервер. Подождите обновления DNS или проверьте A-запись."
  read -r -p "Продолжить всё равно? [y/N] " ok; [ "${ok:-N}" = "y" ] || exit 1
fi

mkdir -p deploy/certbot/www deploy/certbot/conf
docker compose up -d web

echo "==> Запрос сертификата"
docker run --rm \
  -v "$PWD/deploy/certbot/conf:/etc/letsencrypt" \
  -v "$PWD/deploy/certbot/www:/var/www/certbot" \
  certbot/certbot certonly --webroot -w /var/www/certbot \
  -d "$DOMAIN" --email "$EMAIL" --agree-tos --no-eff-email --non-interactive

echo "==> Переключение nginx в режим https"
if grep -q '^NGINX_MODE=' .env; then sed -i 's/^NGINX_MODE=.*/NGINX_MODE=https/' .env; else echo 'NGINX_MODE=https' >> .env; fi
docker compose up -d --force-recreate web
sleep 2
curl -fsS -o /dev/null -w "https://$DOMAIN/api/health → %{http_code}\n" "https://$DOMAIN/api/health"
