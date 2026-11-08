#!/bin/sh
set -e

mkdir -p data
alembic upgrade head

if [ "$1" = "worker" ]; then
    exec python -m app.worker.main
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${UVICORN_WORKERS:-1}"
