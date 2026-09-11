#!/bin/bash
# Cell supervisor: Postgres on the volume, then the daemon as `hatch`.
# Exit status follows the daemon, so an idle exit (0) stops the machine and a
# crash (non-zero) lets the machine's restart policy bring it back.
set -euo pipefail

: "${SUPERAPP_CELL_USER:?SUPERAPP_CELL_USER is required in a cell}"
: "${SUPERAPP_CELL_TOKEN:?SUPERAPP_CELL_TOKEN is required in a cell}"
PGDATA="${PGDATA:-/data/pg}"
HOME_ROOT="${SUPERAPP_HOME_ROOT:-/data/users}"
export DATABASE_URL="${DATABASE_URL:-postgresql://superapp@127.0.0.1:5432/superapp}"
export SUPERAPP_INTERNAL_URL="http://127.0.0.1:${SUPERAPP_PORT:-18792}"
export SUPERAPP_INTERNAL_TOKEN="${SUPERAPP_INTERNAL_TOKEN:-$(head -c 24 /dev/urandom | base64 | tr -d '/+=')}"

# Egress policy hook (Muse's Sentinel). When the gateway hands the cell a proxy
# and a CA, every HTTP client in the cell (daemon, CLIs, Chromium) goes through it.
if [ -n "${SUPERAPP_EGRESS_PROXY:-}" ]; then
    export HTTP_PROXY="$SUPERAPP_EGRESS_PROXY" HTTPS_PROXY="$SUPERAPP_EGRESS_PROXY" \
           http_proxy="$SUPERAPP_EGRESS_PROXY" https_proxy="$SUPERAPP_EGRESS_PROXY" \
           NO_PROXY="localhost,127.0.0.1,::1" no_proxy="localhost,127.0.0.1,::1"
    if [ -n "${SUPERAPP_EGRESS_CA:-}" ]; then
        export SSL_CERT_FILE="$SUPERAPP_EGRESS_CA" REQUESTS_CA_BUNDLE="$SUPERAPP_EGRESS_CA" NODE_EXTRA_CA_CERTS="$SUPERAPP_EGRESS_CA"
    fi
fi

mkdir -p /data /run/postgresql "$HOME_ROOT"
chown postgres:postgres /run/postgresql
chown hatch:hatch "$HOME_ROOT"

if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo "cell: initialising Postgres at $PGDATA"
    mkdir -p "$PGDATA" && chown postgres:postgres "$PGDATA" && chmod 700 "$PGDATA"
    gosu postgres initdb -D "$PGDATA" --auth-local=trust --auth-host=trust -U superapp >/dev/null
    cat >> "$PGDATA/postgresql.conf" <<CONF
listen_addresses = '127.0.0.1'
unix_socket_directories = '/run/postgresql'
shared_buffers = 64MB
max_connections = 40
CONF
fi

gosu postgres pg_ctl -D "$PGDATA" -l "$PGDATA/postgres.log" -w -t 60 start >/dev/null
stop_pg() { gosu postgres pg_ctl -D "$PGDATA" -m fast -w stop >/dev/null 2>&1 || true; }
trap 'stop_pg' EXIT
gosu postgres psql -U superapp -d postgres -tAc "select 1 from pg_database where datname='superapp'" | grep -q 1 \
    || gosu postgres createdb -U superapp superapp

echo "cell: user=$SUPERAPP_CELL_USER idle_exit=${SUPERAPP_IDLE_EXIT_SECS:-0}s"
set +e
gosu hatch env HOME=/home/hatch SUPERAPP_LOG_LEVEL="${SUPERAPP_LOG_LEVEL:-warning}" ./.venv/bin/python -m superapp.serve &
daemon=$!
term() { kill -TERM "$daemon" 2>/dev/null; }
trap 'term' TERM INT
wait "$daemon"; code=$?
echo "cell: daemon exited with $code"
exit $code
