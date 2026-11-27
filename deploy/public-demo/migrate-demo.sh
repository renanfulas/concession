#!/usr/bin/env bash
# Aplica as migrations da demo publica a partir da pasta de uma release.
# Banco novo: a 007 so passa depois do backfill da 006 (mesma ordem da CI em
# .github/workflows/phase0-gates.yml). Banco que ja passou da 007: so apply.
# Uso: cd <release> && migrate-demo.sh   (com o demo.env ja carregado)
set -euo pipefail

python=.venv/bin/python
test -x "$python"

if "$python" -m scripts.migrate status | grep -q '^pending: 007_'; then
  "$python" -m scripts.migrate apply --target 006_conversations_messages.sql
  "$python" -m scripts.backfill_conversation_privacy --verify-contract-ready --quiet-period-seconds 0
fi
"$python" -m scripts.migrate apply
