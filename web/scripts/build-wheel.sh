#!/usr/bin/env bash
# Build the humm2melody wheel into web/public/ for Pyodide to install.
#
# The wheel is py3-none-any, so micropip can install it directly; numpy comes
# from Pyodide's own bundle. Rebuild after any change to humm2melody/ — the
# browser holds a copy, and a stale one is a confusing way to lose an hour.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
out="$root/web/public"

rm -f "$out"/*.whl
uv build --wheel -o "$out" >/dev/null
wheel="$(basename "$(ls -t "$out"/*.whl | head -1)")"

printf '{"wheel": "%s", "built": "%s"}\n' \
  "$wheel" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$out/wheel.json"

echo "built $wheel"
