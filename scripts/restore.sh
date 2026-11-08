#!/bin/sh
set -e

FILE="$1"
DB_PATH="${DB_PATH:-/app/data/portals.db}"

if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then
    echo "Укажите файл бэкапа: sh scripts/restore.sh backups/portals-YYYYmmdd-HHMMSS.db"
    exit 1
fi

echo "Остановите backend и worker перед восстановлением: docker compose stop backend worker"

docker compose cp "$FILE" "backend:/app/data/restore.tmp"
docker compose exec -T backend python - <<PY
import os
import sqlite3

db = "$DB_PATH"
for suffix in ("", "-wal", "-shm"):
    try:
        os.remove(db + suffix)
    except FileNotFoundError:
        pass

src = sqlite3.connect("/app/data/restore.tmp")
dst = sqlite3.connect(db)
src.backup(dst)
dst.close()
src.close()
os.remove("/app/data/restore.tmp")
PY

echo "Восстановление завершено из $FILE"
