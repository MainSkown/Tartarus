#!/usr/bin/env bash
# Runs once, on an empty pg-data volume. The primary database comes from POSTGRES_DB.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v cape_user="${CAPE_DB_USER:?CAPE_DB_USER is required}" \
    -v cape_password="${CAPE_DB_PASSWORD:?CAPE_DB_PASSWORD is required}" \
    -v cape_db="${CAPE_DB_NAME:?CAPE_DB_NAME is required}" <<'SQL'
CREATE ROLE :"cape_user" WITH LOGIN PASSWORD :'cape_password';
CREATE DATABASE :"cape_db" OWNER :"cape_user";
SQL
