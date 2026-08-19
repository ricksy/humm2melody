#!/usr/bin/env bash
# Push the post and its images to the blog, rebuild the site, commit.
#
#   scripts/publish-blog.sh --dry-run     show what would happen
#   scripts/publish-blog.sh --images      images only, no post text
#   scripts/publish-blog.sh               post text and images
#
# Two traps are encoded here rather than left to memory:
#
#   1. The server's working tree is usually dirty with unrelated in-progress
#      posts. `git add -A` there would commit somebody else's work, so only
#      our own paths are ever staged.
#   2. Plain `hugo` writes to public/, which is NOT what is served. The build
#      must target the served directory, so it always passes --destination.

set -euo pipefail
cd "$(dirname "$0")/.."

# Deployment details live in scripts/blog.env, which is gitignored. This
# repository is public, so host names and server paths do not belong in it.
ENV_FILE="${BLOG_ENV:-scripts/blog.env}"
if [ ! -f "$ENV_FILE" ]; then
    echo "missing $ENV_FILE -- copy scripts/blog.env.example and fill it in" >&2
    exit 1
fi
# shellcheck source=/dev/null
set -a; . "$ENV_FILE"; set +a

for var in BLOG_HOST BLOG_SITE BLOG_SERVED BLOG_SLUG BLOG_URL; do
    [ -n "${!var:-}" ] || { echo "$ENV_FILE is missing $var" >&2; exit 1; }
done

HOST="$BLOG_HOST"
SITE="$BLOG_SITE"
SERVED="$BLOG_SERVED"
SLUG="$BLOG_SLUG"
URL="$BLOG_URL"
POST="content/posts/$SLUG.md"
IMAGES="static/images/$SLUG"

DRY=0
IMAGES_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY=1 ;;
        --images)  IMAGES_ONLY=1 ;;
        *) echo "usage: $0 [--dry-run] [--images]" >&2; exit 2 ;;
    esac
done

run() {
    if [ "$DRY" = 1 ]; then
        printf '  would run: %s\n' "$*"
    else
        "$@"
    fi
}

echo "==> local files"
ls -lh docs/demo.gif docs/sessions.gif | awk '{printf "    %s  %s\n", $5, $9}'

echo "==> server state before"
ssh "$HOST" "cd $SITE && git status --short | head -20" || true

echo "==> uploading images"
run scp docs/demo.gif docs/sessions.gif "$HOST:$SITE/$IMAGES/"

if [ "$IMAGES_ONLY" = 0 ]; then
    if [ -f "docs/blog/$SLUG.md" ]; then
        echo "==> uploading post text from docs/blog/$SLUG.md"
        run scp "docs/blog/$SLUG.md" "$HOST:$SITE/$POST"
    else
        echo "==> no local docs/blog/$SLUG.md, leaving the post text alone"
        echo "    (fetch it first: scp $HOST:$SITE/$POST docs/blog/$SLUG.md)"
    fi
fi

echo "==> rebuilding to $SERVED"
run ssh "$HOST" "cd $SITE && hugo --destination $SERVED"

echo "==> committing only our own paths"
run ssh "$HOST" "cd $SITE && git add $POST $IMAGES && \
    git commit -m 'Update $SLUG post' && git push"

if [ "$DRY" = 1 ]; then
    echo "==> dry run, nothing was changed"
    exit 0
fi

echo "==> verifying"
fail=0
BASE="${URL%%/posts/*}"
for target in "$URL" \
              "$BASE/images/$SLUG/demo.gif" \
              "$BASE/images/$SLUG/sessions.gif"; do
    code=$(curl -s -o /dev/null -w '%{http_code}' "$target")
    printf '    %s  %s\n' "$code" "$target"
    [ "$code" = 200 ] || fail=1
done
[ "$fail" = 0 ] || { echo "!! something is not serving; check the paths" >&2; exit 1; }
echo "==> live: $URL"
