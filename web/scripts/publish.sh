#!/usr/bin/env bash
# Build and upload the PWA.
#
# Deliberately dumb: it builds, mirrors a directory, then checks the result is
# actually reachable. Configuration lives in pwa.env, which is gitignored —
# same reasoning as docs/MAINTENANCE.md §5, this repository is public.
#
#   cp web/scripts/pwa.env.example web/scripts/pwa.env   # first time
#   ./web/scripts/publish.sh --check     # validate config, no network
#   ./web/scripts/publish.sh --dry-run   # connect, show what would change
#   ./web/scripts/publish.sh
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../.." && pwd)"

die() { echo "error: $*" >&2; exit 1; }

[ -f "$here/pwa.env" ] || die "missing $here/pwa.env — copy pwa.env.example and fill it in"
# shellcheck disable=SC1091
source "$here/pwa.env"

for var in PWA_HOST PWA_PATH PWA_URL; do
  [ -n "${!var:-}" ] || die "$var is not set in pwa.env"
done

# Copying the example without editing it is the obvious first mistake, and
# without this check it surfaces as a 75-second SSH timeout against a domain
# reserved by the IETF for exactly this kind of accident.
case "$PWA_HOST$PWA_PATH$PWA_URL" in
  *example.com*|*your-ssh-host-alias*|*/path/to/*)
    die "pwa.env still holds the example values — edit it with your real host.
       PWA_HOST is probably the same as BLOG_HOST in scripts/blog.env." ;;
esac

case "$PWA_URL" in
  https://*) ;;
  *) die "PWA_URL must be https — getUserMedia and service workers both
       require a secure context, so the app cannot work over plain HTTP." ;;
esac

mode="${1:-}"
[ "$mode" = "--check" ] && {
  echo "pwa.env looks usable:"
  printf '  %-10s %s\n' host "$PWA_HOST" path "$PWA_PATH" url "$PWA_URL"
  exit 0
}

"$here/build-pwa.sh"

dry=""
[ "$mode" = "--dry-run" ] && dry="--dry-run"

# --delete so a renamed wheel does not leave its predecessor behind; the
# excludes are development-only files that should never be served.
# ConnectTimeout so an unreachable host fails in seconds, not minutes.
rsync -az --delete $dry \
  -e "ssh -o ConnectTimeout=10" \
  --exclude 'tests/' --exclude 'scripts/' --exclude '__pycache__/' \
  --exclude '.gitignore' --exclude 'README.md' \
  "$root/web/" "$PWA_HOST:$PWA_PATH/" \
  || die "rsync failed — check PWA_HOST is reachable over ssh and PWA_PATH exists"

[ -n "$dry" ] && { echo "dry run — nothing uploaded"; exit 0; }

echo "checking $PWA_URL"
fail=0
for path in "" "manifest.webmanifest" "sw.js" "public/wheel.json" \
            "public/pyodide/pyodide.asm.wasm"; do
  code=$(curl -s -m 20 -o /dev/null -w '%{http_code}' "${PWA_URL%/}/$path")
  printf '  %-40s %s\n' "${path:-/}" "$code"
  [ "$code" = "200" ] || fail=1
done

# An installed app that cannot load its own runtime is the failure mode worth
# catching, and it looks fine from the home page alone.
type=$(curl -s -m 20 -o /dev/null -w '%{content_type}' \
  "${PWA_URL%/}/public/pyodide/pyodide.asm.wasm")
printf '  %-40s %s\n' "wasm content-type" "$type"
case "$type" in
  application/wasm*) ;;
  *) echo "  ⚠ must be application/wasm or Pyodide will not start"; fail=1 ;;
esac

exit $fail
