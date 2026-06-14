#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '[entrypoint] %s\n' "$*"
}

export PATH="/usr/lib/postgresql/18/bin:${PATH}"

APP_USER="${APP_USER:-kikoerumanager}"
APP_DB="${APP_DB:-kikoerumanager}"
APP_PASSWORD="${POSTGRES_PASSWORD:-${APP_PASSWORD:-kikoerumanager}}"
PGDATA="${PGDATA:-/app/postgres/data}"
PGHOST_DIR="${PGHOST_DIR:-/app/postgres/run}"
PGPORT="${PGPORT:-5432}"
PGLOG="${PGLOG:-/app/postgres/postgresql.log}"

mkdir -p "$PGDATA" "$PGHOST_DIR" /app/data /app/config /input /temp /library /existing /processed
chown -R postgres:postgres "$(dirname "$PGDATA")" "$PGHOST_DIR"
chmod 700 "$PGHOST_DIR"

run_as_postgres() {
  su -s /bin/bash postgres -c "$*"
}

init_postgres() {
  if [[ -s "$PGDATA/PG_VERSION" ]]; then
    return
  fi

  log "初始化内置 PostgreSQL 数据目录: $PGDATA"
  local pwfile
  pwfile="$(mktemp)"
  chmod 600 "$pwfile"
  printf '%s' "$APP_PASSWORD" > "$pwfile"
  chown postgres:postgres "$pwfile"
  run_as_postgres "initdb -D '$PGDATA' -U '$APP_USER' -A scram-sha-256 --pwfile='$pwfile' --encoding=UTF8 --locale=C"
  rm -f "$pwfile"

  cat >> "$PGDATA/postgresql.conf" <<EOF

listen_addresses = '127.0.0.1'
port = ${PGPORT}
unix_socket_directories = '${PGHOST_DIR}'
shared_preload_libraries = 'pg_stat_statements'
pg_stat_statements.track = all
pg_stat_statements.max = 10000
track_io_timing = on
shared_buffers = '256MB'
effective_cache_size = '1GB'
maintenance_work_mem = '128MB'
work_mem = '16MB'
max_wal_size = '1GB'
checkpoint_timeout = '15min'
checkpoint_completion_target = 0.9
random_page_cost = 1.1
effective_io_concurrency = 200
default_statistics_target = 200
log_min_duration_statement = 1000
EOF
}

start_postgres() {
  log "启动内置 PostgreSQL"
  run_as_postgres "pg_ctl -D '$PGDATA' -l '$PGLOG' -w start"
}

stop_postgres() {
  if [[ -s "$PGDATA/PG_VERSION" ]]; then
    run_as_postgres "pg_ctl -D '$PGDATA' -m fast -w stop" >/dev/null 2>&1 || true
  fi
}

ensure_database() {
  export PGPASSWORD="$APP_PASSWORD"
  until pg_isready -h 127.0.0.1 -p "$PGPORT" -U "$APP_USER" >/dev/null 2>&1; do
    sleep 1
  done

  psql -h 127.0.0.1 -p "$PGPORT" -U "$APP_USER" -d postgres -v ON_ERROR_STOP=1 \
    -v app_db="$APP_DB" -v app_user="$APP_USER" <<'SQL'
SELECT format('CREATE DATABASE %I OWNER %I', :'app_db', :'app_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'app_db')\gexec
SQL

  psql -h 127.0.0.1 -p "$PGPORT" -U "$APP_USER" -d "$APP_DB" -v ON_ERROR_STOP=1 <<SQL
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
SQL
  unset PGPASSWORD
}

if [[ -z "${DATABASE_URL:-}" ]]; then
  init_postgres
  start_postgres
  trap stop_postgres EXIT
  ensure_database
  export DATABASE_URL="postgresql+psycopg://${APP_USER}:${APP_PASSWORD}@127.0.0.1:${PGPORT}/${APP_DB}?sslmode=disable"
  log "使用内置 PostgreSQL: 127.0.0.1:${PGPORT}/${APP_DB}"
else
  log "检测到 DATABASE_URL，使用外部 PostgreSQL"
fi

exec "$@"
