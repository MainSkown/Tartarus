#!/bin/sh
set -e

# A fresh database has no tables, so the first request to any DB-backed route would 500.
# Postgres is already healthy here (compose depends_on), so this runs once per start.
alembic upgrade head
exec "$@"
