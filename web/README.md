# humm2melody on the web

A spike, not a product. It runs the **unmodified** Python detector in the
browser via Pyodide, to answer the one question that decides whether the whole
approach is viable: **does the live readout hold ~43 frames/sec in wasm?**

Background and the options that were weighed: `docs/pwa.md`.

## Run it

```bash
./web/scripts/build-pwa.sh          # runtime + icons + wheel
uv run web/scripts/serve.py         # http://127.0.0.1:8000/
```

`build-pwa.sh` is idempotent — the 16 MB Pyodide download and the icons happen
once, the wheel is rebuilt every time. After a change to `humm2melody/` you
only need `./web/scripts/build-wheel.sh`.

Localhost is deliberate — `getUserMedia` needs a secure context, and localhost
is the only origin exempt from HTTPS.

## Test it

```bash
uv run pytest web/tests
```

These are **not** in the default `pytest` run: `testpaths = ["tests"]` in
`pyproject.toml` keeps the main suite untouched, so the test count quoted in
the README stays correct. Adding `"web/tests"` to that list is a one-line
change whenever the web build is worth gating the main suite on.

## How it fits together

```
AudioWorklet (audio thread)   regroups 128-sample quanta into 512-sample hops
        │ postMessage
        ▼
main thread (app.js)          UI only; no analysis
        │ postMessage
        ▼
Worker (pitch-worker.js)      Pyodide + numpy + the humm2melody wheel
        │
        ▼
bridge.py                     sliding window → analyse_frame → JSON reading
```

That is the same three-way split the desktop app uses — cheap audio callback,
a worker doing YIN, a UI thread that only draws — with `postMessage` where
`queue.Queue` sits in `humm2melody/audio.py`. The shapes were already right;
only the transport changed.

## What it shows

The Recording tab mirrors the TUI, widget for widget and colour for colour:

| Terminal (`tui.py`) | Browser (`views.js`) |
| --- | --- |
| `NoteReadout` | live note, cents, Hz, elapsed |
| `LevelMeter` | same green/yellow/red zones |
| `MelodySequence` | "Play this:" row, clickable |
| `PianoKeys` | a drawn keyboard that lights up |
| `PianoRoll` | SVG roll with playhead and time axis |
| `DetailTable` | the authoritative per-note table |
| `SensitivityDial` etc. | four dials, same captions and `1-9` levels |
| `NotationRow` | English / German / Solfège / Sargam |

Two things are better here than in the terminal, both because there is no
character cell to round to: the roll can show a gap narrower than one cell
(the limitation listed in the roadmap), and the keyboard is drawn rather than
approximated with block glyphs.

Keys follow `tui.py` where they still make sense: `[` `]` pitch, `<` `>`
pauses, `-` `=` mix, `n` notation, `r` record, `s` stop, `p` play.

Calibrating and Training are placeholders, as they were in the TUI until
recently. Calibration is the next thing worth porting — `calibration.py` is
already numpy-only, so it crosses over unchanged.

## What is reused, unchanged

`pitch.py`, `segment.py`, `analysis.py`, `calibration.py`, `naming.py` and
`profiles.py` are installed from the wheel and called directly. Note spelling
comes from `naming.spell()` and the playback speeds from
`playback.tempo_speed()` — both are sent to the browser rather than
reimplemented there, so a new notation scheme or a retuned tempo curve appears
in both front ends at once. `render()` and
`mix_hum_with_tones()` produce the playback buffer that WebAudio plays. The
dials call the same `sensitivity_settings()` and `pause_settings()`, so a
level here means what it means in the TUI.

`bridge.py` is the only new Python, and it is deliberately thin: a sliding
window and JSON encoding. **Anything musical belongs in the core package**,
where the desktop app and the real test suite can reach it.

## The one rule

> `web/` may import from `humm2melody/`. `humm2melody/` must never know
> `web/` exists.

`web/tests/test_portable.py` enforces it: the modules the browser loads must
import with `sounddevice`, `soundfile`, `textual` and `rich` blocked. If it
fails, move the offending import inside the function that needs it, the way
`audio.py`, `playback.py` and `sessions.py` already do.

Add any new browser-loaded module to its `PORTABLE` list.

## It is a PWA

Installable, and it runs with no network at all. Verified by stopping the
server and reloading: Pyodide boots from cache and a synthetic hum still
transcribes.

**Vendored, not CDN.** `vendor-pyodide.sh` downloads the runtime into
`public/pyodide/`. An installed app cannot depend on a third party keeping a
URL alive, and a service worker can only cache what it is allowed to fetch.
The runtime comes from the GitHub release rather than jsdelivr, which
truncates the 9 MB wasm blob repeatably (curl 56).

**What it costs.**

| | |
| --- | --- |
| `pyodide.asm.wasm` | 9.2 MB |
| `python_stdlib.zip` | 2.4 MB |
| numpy | 3.0 MB |
| `pyodide.asm.mjs` | 1.2 MB |
| micropip, lock, loader | 0.3 MB |
| humm2melody wheel | 80 KB |
| app shell | ~60 KB |
| **total** | **~16 MB, once** |

Compression matters: serve with gzip or brotli and the wasm drops
substantially over the wire.

**Two caches, on purpose.** `h2m-shell-<build>` holds the app — kilobytes,
changes constantly, wiped on every deploy. `h2m-runtime-v1` holds Pyodide,
numpy and the wheel — 16 MB, changes rarely, survives an app deploy. One cache
for both would mean re-downloading 16 MB whenever a colour changed.

**The warm-up.** On a first visit Pyodide is already downloading before the
service worker controls anything, so those 16 MB never pass through its fetch
handler. The app therefore asks the worker to fetch them explicitly once it is
up (`{type: "warm"}` → `public/precache.json`, written by the build). Without
it, install-then-go-offline fails, and it fails on exactly the visit where a
user decided to install.

**Versioning without churn.** The worker is registered as `sw.js?v=<build
stamp>`, taken from `wheel.json`. The browser compares script bytes to decide
a worker is new, so a version baked into `sw.js` would have to be rewritten by
the build — a modified file in git on every deploy. A query string avoids that
entirely.

## Deploying it

```bash
cp web/scripts/pwa.env.example web/scripts/pwa.env   # first time only
$EDITOR web/scripts/pwa.env                          # ← real values, not the examples
./web/scripts/publish.sh --check                     # validates config, no network
./web/scripts/publish.sh --dry-run                   # connects, shows what would change
./web/scripts/publish.sh
```

`PWA_HOST` is very likely the same machine as `BLOG_HOST` in `scripts/blog.env`
— the one already serving the site. `--check` exists because the alternative
way to discover an unedited `pwa.env` is a 75-second SSH timeout against
`example.com`.

`pwa.env` is gitignored, following `docs/MAINTENANCE.md` §5 — this repository
is public and deployment targets are infrastructure.

The host must get three things right, and `publish.sh` checks the third:

1. **HTTPS.** Both `getUserMedia` and service workers require a secure
   context. There is no way around this off localhost.
2. **Compression** on `.wasm`, `.js` and `.zip`.
3. **`application/wasm`** for `.wasm`. Serve it as `octet-stream` and Pyodide
   refuses to start — with an error that does not mention MIME types.

Worth setting, though not checked: `Cache-Control: immutable` with a long
max-age on `public/pyodide/`, and `no-cache` on `sw.js` and `wheel.json` so a
deploy is picked up.

## Known gaps

- **Nothing is persisted.** A reload loses the take. Storage is the next real
  piece of work — OPFS or IndexedDB in place of `sessions.py`.
- **Resampling at block seams.** If the browser refuses a 22.05 kHz
  `AudioContext` it hands back the device rate and `bridge.py` resamples each
  block independently, which is approximate at the joins. The status line says
  when this is happening. Fine for a spike; fix before it matters.
- **No build tooling, on purpose.** Plain ES modules, no `node_modules`. Add
  Vite when the UI outgrows one file, not before.
- **The install button is Chromium-only.** It hangs off
  `beforeinstallprompt`, which Safari does not implement — there, installing
  is Share → Add to Home Screen, and the button stays hidden. Firefox on
  desktop does not install PWAs at all.
- **Storage is evictable.** 16 MB of cache can be reclaimed under pressure.
  `navigator.storage.persist()` is not requested yet; it should be, before
  anything depends on the app working offline.
- **Untested on iOS.** Safari's `getUserMedia` inside an installed PWA is the
  weakest link on any platform and there is no fallback engine. Test on real
  hardware before building anything on top of this.
