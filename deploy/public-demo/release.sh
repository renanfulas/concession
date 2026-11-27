#!/usr/bin/env bash
# Instala uma release da demo publica e troca o link "current" de forma atomica.
# Uso (root, na VPS): release.sh /tmp/concession-<id>.tar.gz <AAAAMMDD-HHMMSS>
# O tarball vem de `git archive --format=tar.gz HEAD` no repositorio.
# Runbook: docs/runbooks/public-demo.md
set -euo pipefail

archive="$1"
release_id="$2"
[[ "$release_id" =~ ^[0-9]{8}-[0-9]{6}$ ]] || { echo "release id must be AAAAMMDD-HHMMSS" >&2; exit 2; }

base=/opt/concession-demo
release="$base/releases/$release_id"
env_file=/etc/concession-demo/demo.env

test -f "$archive"
test -f "$env_file"
test ! -e "$release"

mkdir -p "$release"
tar -xzf "$archive" -C "$release" --no-same-owner
test -f "$release/pyproject.toml"

python3.11 -m venv "$release/.venv"
"$release/.venv/bin/pip" install --quiet --upgrade pip
"$release/.venv/bin/pip" install --quiet "$release"

chown -R root:root "$release"
chmod -R go-w "$release"

set -a
# shellcheck disable=SC1090
. "$env_file"
set +a
(cd "$release" && "$(dirname "$(readlink -f "$0")")/migrate-demo.sh")

previous=""
if [[ -L "$base/current" ]]; then
  previous="$(readlink -f "$base/current")"
fi
ln -sfn "$release" "$base/current-next"
mv -Tf "$base/current-next" "$base/current"
systemctl restart concession-demo

for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS http://127.0.0.1:8095/health >/dev/null; then
    printf 'DEPLOYED_RELEASE=%s\nPREVIOUS_RELEASE=%s\n' "$release" "${previous:-none}"
    exit 0
  fi
  sleep 1
done

echo "health check failed; rolling back to ${previous:-nothing}" >&2
if [[ -n "$previous" ]]; then
  ln -sfn "$previous" "$base/current-next"
  mv -Tf "$base/current-next" "$base/current"
  systemctl restart concession-demo
fi
exit 4
