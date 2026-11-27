#!/usr/bin/env bash
# Recria o banco da demo publica do zero: drop, create, migrations e seed.
# Roda como root (timer concession-demo-reset). Instalar em
# /opt/concession-demo/bin/reset-demo.sh. Runbook: docs/runbooks/public-demo.md
set -euo pipefail

base=/opt/concession-demo/current
env_file=/etc/concession-demo/demo.env
db=concession_demo
role=concession_demo

test -d "$base"
test -f "$env_file"

# A aplicacao volta a subir mesmo se o reset falhar no meio.
trap 'systemctl start concession-demo' EXIT
systemctl stop concession-demo

runuser -u postgres -- dropdb --if-exists "$db"
runuser -u postgres -- createdb --owner "$role" "$db"
# Extensoes exigem superusuario; a migration 001 usa IF NOT EXISTS.
runuser -u postgres -- psql --quiet --dbname "$db" \
  --command 'CREATE EXTENSION IF NOT EXISTS pgcrypto' \
  --command 'CREATE EXTENSION IF NOT EXISTS vector'

set -a
# shellcheck disable=SC1090
. "$env_file"
set +a

cd "$base"
/opt/concession-demo/bin/migrate-demo.sh
.venv/bin/python -m scripts.seed_demo_cases

echo "concession demo reset at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
