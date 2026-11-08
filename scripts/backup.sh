#!/bin/sh
set -e

BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
DB_PATH="${DB_PATH:-/app/data/portals.db}"

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
FILE="portals-$STAMP.db"

docker compose exec -T backend python - <<PY
import sqlite3

src = sqlite3.connect("$DB_PATH")
dst = sqlite3.connect("/app/data/backup.tmp")
src.backup(dst)
dst.close()
src.close()
PY
docker compose cp "backend:/app/data/backup.tmp" "$BACKUP_DIR/$FILE"
docker compose exec -T backend rm -f /app/data/backup.tmp

find "$BACKUP_DIR" -name 'portals-*.db' -mtime "+$RETENTION_DAYS" -delete

echo "Бэкап сохранён: $BACKUP_DIR/$FILE"
