#!/usr/bin/env bash
# Консистентная копия SQLite (через sqlite backup API, без остановки сервиса).
# Хранит 14 последних копий в ./backups. Запуск по cron — см. инструкцию.
set -euo pipefail
cd "$(dirname "$0")/../.."
mkdir -p backups
STAMP=$(date +%F_%H%M)
docker compose exec -T api python -c "import sqlite3; s=sqlite3.connect('/data/benshu.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d); d.close(); s.close()"
docker compose cp api:/data/backup.db "backups/benshu-$STAMP.db"
ls -1t backups/benshu-*.db | tail -n +15 | xargs -r rm --
echo "Бэкап: backups/benshu-$STAMP.db"
