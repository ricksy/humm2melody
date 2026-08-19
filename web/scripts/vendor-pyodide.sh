#!/usr/bin/env bash
# Download the Pyodide runtime and the packages we import into
# web/public/pyodide/, so the app is self-contained.
#
# A PWA cannot depend on a CDN. The service worker can only cache what it
# fetches, an offline launch has no network at all, and a third party moving a
# URL would break an app someone has installed. Vendoring is what turns this
# from a web page into something distributable.
#
# The runtime comes from the GitHub release rather than the CDN: it ships as
# one `pyodide-core` archive, and the 9 MB wasm blob is unreliable over
# jsdelivr (curl 56 partway through, repeatably).
#
# Output is gitignored and regenerable. Run once, or after changing VERSION.
set -euo pipefail

VERSION="${PYODIDE_VERSION:-314.0.5}"
CORE="https://github.com/pyodide/pyodide/releases/download/${VERSION}/pyodide-core-${VERSION}.tar.bz2"
CDN="https://cdn.jsdelivr.net/pyodide/v${VERSION}/full"

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
out="$root/web/public/pyodide"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

mkdir -p "$out"

echo "Pyodide $VERSION"
curl -fL --retry 3 --progress-bar "$CORE" -o "$work/core.tar.bz2"
tar -xjf "$work/core.tar.bz2" -C "$work"

# Only what a browser needs. The archive also carries a CLI entry point, a
# native python binary and TypeScript definitions, none of which we serve.
for file in pyodide.mjs pyodide.asm.mjs pyodide.asm.wasm python_stdlib.zip pyodide-lock.json; do
  cp "$work/pyodide/$file" "$out/$file"
  printf '  %-22s %8s\n' "$file" "$(du -h "$out/$file" | cut -f1)"
done

# Packages, resolved through their declared dependencies. Pyodide ships 350+;
# we import two.
wheels=$(python3 - "$out/pyodide-lock.json" <<'PY'
import json, sys
lock = json.load(open(sys.argv[1]))["packages"]
seen, queue = set(), ["numpy", "micropip"]
while queue:
    name = queue.pop()
    if name in seen or name not in lock:
        continue
    seen.add(name)
    queue.extend(lock[name].get("depends", []))
print(" ".join(sorted(lock[n]["file_name"] for n in seen)))
PY
)

for wheel in $wheels; do
  curl -sfL --retry 3 "$CDN/$wheel" -o "$out/$wheel"
  printf '  %-22s %8s\n' "${wheel%%-*}" "$(du -h "$out/$wheel" | cut -f1)"
done

echo "  total                  $(du -sh "$out" | cut -f1)"
