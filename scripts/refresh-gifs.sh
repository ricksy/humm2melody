#!/usr/bin/env bash
# Regenerate the documentation GIFs and build a contact sheet to check them.
#
#   scripts/refresh-gifs.sh            both GIFs
#   scripts/refresh-gifs.sh demo       just one
#
# The contact sheet is the point. A capture can record a perfectly broken UI
# and the file size will look fine, so past runs have shipped a pegged level
# meter and a mid-word text wrap. Always look at the sheet before committing.

set -euo pipefail
cd "$(dirname "$0")/.."

for tool in vhs ffmpeg uv; do
    command -v "$tool" >/dev/null || { echo "missing: $tool" >&2; exit 1; }
done

WHICH="${1:-all}"
OUT="${TMPDIR:-/tmp}/h2m-gif-check"
mkdir -p "$OUT"

echo "==> tests first: a broken app records a broken GIF"
uv run pytest -q | tail -1

# The tapes write runs and profiles into /tmp; clear them so each capture
# starts from the same state and the sidebar is not full of old takes.
rm -rf /tmp/h2m-demo /tmp/h2m-sessions /tmp/h2m-profiles

record() {
    local name="$1"
    echo "==> recording $name"
    vhs "docs/$name.tape"

    local gif="docs/$name.gif"
    local size duration
    size=$(du -h "$gif" | cut -f1)
    duration=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$gif")
    printf '    %s  %s  %.1fs\n' "$gif" "$size" "$duration"

    # Six evenly spaced frames tiled into one image, so the whole capture can
    # be judged at a glance instead of guessing at timestamps. The first fifth
    # is skipped: the tape spends it typing the command, and empty terminal
    # tells you nothing about whether the UI rendered.
    local frames start step
    frames=$(ffprobe -v error -count_frames -select_streams v:0 \
        -show_entries stream=nb_read_frames -of csv=p=0 "$gif")
    start=$(( frames / 5 ))
    step=$(( (frames - start) / 6 ))
    [ "$step" -lt 1 ] && step=1

    ffmpeg -v error -i "$gif" \
        -vf "select='gte(n\,${start})*not(mod(n-${start}\,${step}))',scale=560:-1,tile=2x3" \
        -frames:v 1 "$OUT/$name-sheet.png" -y
    echo "    contact sheet: $OUT/$name-sheet.png"
}

case "$WHICH" in
    demo)     record demo ;;
    sessions) record sessions ;;
    all)      record demo; record sessions ;;
    *) echo "usage: $0 [demo|sessions|all]" >&2; exit 2 ;;
esac

cat <<'NOTE'

==> now LOOK at the contact sheets before committing
    check: a note in the live readout, bars in the timeline, rows in the
    detail table, the three dials aligned, runs listed in the sidebar,
    and no text clipped by the sidebar edge.

    keep each GIF under ~1 MB; if a tape grew, lower `Set Framerate`.
NOTE
