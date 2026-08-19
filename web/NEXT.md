# Where the web build stands

Written to be picked up cold, months later, by someone who has forgotten all
of it. Read `README.md` in this directory for how it works; this file is only
about what is done, what is not, and what to do first.

Decisions and the options that were rejected: `../docs/pwa.md`.

---

## Status: working, installable, offline

It is a real PWA. The unmodified Python detector runs in the browser through
Pyodide, and the app boots and transcribes with the network switched off.

Verified in Chrome, not merely believed:

- Pyodide boots — humm2melody on Python 3.14 in the browser
- synthetic audio pushed through a real worker transcribed to `C4 D4 E4 G4`
  with correct onsets
- the dev server was then **stopped**, the page reloaded, and a hum still
  transcribed to `C4 E4 G4` from cache alone

The performance question that the whole spike existed to answer is settled:

| | |
| --- | --- |
| analysis cost | ~0.08 ms per frame (CPython, measured) |
| budget at 43 fps | 23.2 ms per frame |
| margin | ~280× |

Even a tenfold wasm penalty leaves the live readout comfortable. This is no
longer a risk worth planning around.

---

## Getting back to a running app

```bash
./web/scripts/build-pwa.sh          # runtime + icons + wheel; idempotent
uv run web/scripts/serve.py         # http://127.0.0.1:8000/
uv run pytest web/tests             # 22 tests
```

The first command downloads 16 MB of Pyodide if `web/public/pyodide/` is
missing, which it will be on a fresh clone — all of `public/` is gitignored
because it is generated. Expect it to take a minute once.

After a change to `humm2melody/`, only `./web/scripts/build-wheel.sh` is
needed. **The browser holds a packaged copy of the Python**, so edits to the
source are invisible until you rebuild. This is the single most likely way to
waste an hour here.

---

## What exists

```
web/
  index.html  src/app.js  src/views.js  src/app.css   the UI
  src/pitch-worker.js  src/capture-worklet.js         audio + Pyodide plumbing
  py/bridge.py                                        the only new Python
  sw.js  manifest.webmanifest                         the PWA half
  scripts/                                            build, vendor, serve, publish
  tests/                                              22 tests, no browser needed
```

Feature parity with the Recording tab of the TUI: piano roll, playable
keyboard, melody sequence, detail table, four dials, notation switching
between English, German, Solfège and Sargam, click-to-select from any of the
three views, and the keyboard shortcuts from `tui.py`.

**Calibrating and Training are placeholders.**

---

## The rule that keeps this from rotting

> `web/` may import from `humm2melody/`. `humm2melody/` must never know
> `web/` exists.

`tests/test_portable.py` enforces it mechanically: every module the browser
loads must import with `sounddevice`, `soundfile`, `textual` and `rich`
blocked. It has already earned its place — `naming.py` appeared mid-session
and had to be added to its list.

If it fails, the fix is nearly always to move an import inside the function
that needs it, exactly as `audio.py`, `playback.py` and `sessions.py` do.

Two things are sent from Python rather than reimplemented in JS, for the same
reason: note spelling (`naming.spell`) and the tempo curve
(`playback.tempo_speed`). A JS copy of the latter was written and was wrong
within five minutes. Do not reintroduce either.

---

## What to do next, in order

**1. Persist recordings.** The largest gap by far. A reload loses the take;
there is no equivalent of `sessions.py`. Needs OPFS or IndexedDB, and a runs
list in the UI. Everything else on this list is smaller.

**2. Ask for persistent storage.** One line — `navigator.storage.persist()` —
and it matters as soon as item 1 lands, because 16 MB of cache plus recordings
is exactly what a browser reclaims under pressure. Do it with item 1, not
after.

**3. Test on iOS.** Untested, and it is the platform most likely to break:
Safari's `getUserMedia` inside an *installed* PWA has historically been the
weakest link anywhere, and there is no alternative engine to fall back on. Do
this before building anything that assumes the app works on a phone.

**4. Port calibration.** Roadmap item 0/1. `calibration.py` is already
numpy-only, so it crosses over unchanged; the work is the UI, and the profile
store, which is blocked on item 1.

**5. Fix seam-accurate resampling.** If a browser refuses a 22.05 kHz
`AudioContext` it returns the device rate and `bridge.py` resamples each block
independently, which is approximate at the joins. The status line says when
this is happening. No browser tested so far has refused.

---

## Things that will bite

- **A stale wheel.** See above. The footer shows the wheel filename and build
  time; check it before believing anything.
- **`deps=False` is load-bearing.** The wheel declares `sounddevice`,
  `soundfile` and `textual`; two are C bindings with no wasm build, and
  micropip would fail resolving them. `pitch-worker.js` installs with
  dependencies off, which is safe only because those imports are all lazy.
- **The first visit is the fragile one.** Pyodide downloads before the service
  worker controls anything, so the runtime never passes through its fetch
  handler. The app therefore asks the worker to cache it explicitly
  (`{type: "warm"}`). Two separate offline failures came from exactly this;
  if offline breaks again, suspect it first.
- **jsdelivr truncates the 9 MB wasm** repeatably (curl 56). The runtime comes
  from the GitHub release instead. Do not "simplify" this back to the CDN.
- **`publish.sh --delete` mirrors the target directory.** `PWA_PATH` must
  belong to this app alone.
- **`pwa.env` needs real values.** `./web/scripts/publish.sh --check`
  validates it without touching the network.

---

## Deploying, when you want to

```bash
cp web/scripts/pwa.env.example web/scripts/pwa.env
$EDITOR web/scripts/pwa.env        # PWA_HOST is likely BLOG_HOST from scripts/blog.env
./web/scripts/publish.sh --check
./web/scripts/publish.sh
```

The host must serve over **HTTPS** (required for both the microphone and
service workers) and must return **`application/wasm`** for `.wasm` — served
as `octet-stream`, Pyodide refuses to start, with an error that never mentions
MIME types. `publish.sh` checks the second and cannot check the first.
