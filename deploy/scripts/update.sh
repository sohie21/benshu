#!/usr/bin/env bash
# Обновление после изменений кода: бэкап → пересборка → проверка.
set -euo pipefail
cd "$(dirname "$0")/../.."
bash deploy/scripts/backup.sh || echo "Бэкап пропущен (сервис ещё не запущен?)"
if [ -d .git ]; then git pull --ff-only; fi
docker compose up -d --build
sleep 3
docker compose ps
docker compose exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/health').read().decode())"
