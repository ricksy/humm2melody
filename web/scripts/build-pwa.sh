#!/usr/bin/env bash
# Everything needed to serve or deploy the app: runtime, wheel, icons.
#
# Only the wheel changes often; the other two steps notice they are already
# done and cost nothing.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../.." && pwd)"

if [ ! -f "$root/web/public/pyodide/pyodide.asm.wasm" ]; then
  "$here/vendor-pyodide.sh"
else
  echo "  pyodide                already vendored ($(du -sh "$root/web/public/pyodide" | cut -f1))"
fi

if [ ! -f "$root/web/public/icons/icon-512.png" ]; then
  uv run "$here/make-icons.py"
else
  echo "  icons                  already generated"
fi

"$here/build-wheel.sh"

# The service worker cannot discover these: it is not running when the app
# first fetches them, and the numpy/micropip filenames carry versions. So the
# build writes down exactly what it produced, and the worker warms the cache
# from that list once the app is up.
python3 - "$root/web" <<'PY'
import json, sys
from pathlib import Path

web = Path(sys.argv[1])
files = ["./public/" + p.name for p in sorted((web / "public" / "pyodide").iterdir())
         if p.suffix in {".mjs", ".wasm", ".zip", ".json", ".whl"}]
files = [f.replace("./public/", "./public/pyodide/") for f in files]
files += ["./public/" + p.name for p in sorted(web.glob("public/*.whl"))]

out = web / "public" / "precache.json"
out.write_text(json.dumps({"files": files}, indent=2) + "\n")
print(f"  precache.json          {len(files)} runtime files")
PY

echo "  total to serve         $(du -sh "$root/web" | cut -f1)"
