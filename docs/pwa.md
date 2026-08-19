# Getting humm2melody onto the web

Options for making the app usable from a browser, with what each one costs and
what it would reuse. Written to be picked up cold: assume the reader has not
seen the conversation that produced it.

The whole question turns on one constraint. **The microphone is on the user's
device.** Anything that runs the capture somewhere else is not a version of
this app, it is a version of this app pointed at the wrong room. Every option
below is therefore judged first on where the audio is captured, and only then
on where it is analysed.

---

## What the code base already gives you

This matters more than the options do, so it goes first. The package is
unusually well placed for this, mostly by accident of how the audio layer was
kept cheap.

| Module | Lines | Third-party deps | Crosses to the browser? |
| --- | --- | --- | --- |
| `pitch.py` | 206 | numpy | **yes, unchanged** |
| `segment.py` | 521 | numpy | **yes, unchanged** |
| `analysis.py` | 343 | numpy | **yes, unchanged** |
| `demo.py` | 209 | numpy | yes, unchanged |
| `profiles.py` | 176 | *none* | yes, but storage swaps out |
| `sessions.py` | 336 | numpy | logic yes, filesystem no |
| `playback.py` | 296 | numpy, sounddevice | `render()` yes, `Player` no |
| `audio.py` | 217 | numpy, sounddevice | no — capture is rewritten |
| `tui.py` | 1331 | rich, textual | **no — rewritten entirely** |

Four things are worth calling out because they are each worth days of work
that has already been done:

**1. The DSP core is numpy and nothing else.** 1070 lines of pitch detection,
segmentation and diagnosis with no scipy, no librosa, no numba. YIN is
hand-written against `np.fft.rfft`/`irfft`, `cumsum` and `argmin`. Had this
leaned on librosa or numba, options A and B below would both be far harder —
numba in particular has no browser story at all.

**2. `sounddevice` is imported lazily, in three places only.** `audio.py:94`,
`playback.py:157` and `playback.py:217`. The DSP core imports and runs cleanly
on a machine with no PortAudio at all, which is exactly the condition inside a
browser. Nothing needs untangling first.

**3. Synthesis is already separate from output.** `playback.render()` takes
notes and returns a mono numpy buffer; `Player` is the only part that opens a
device. On the web, `render()` is reused verbatim and its buffer is handed to
a WebAudio `AudioBuffer`. Same for `mix_hum_with_tones()` and `resample()`.

**4. There are 46 saved runs and 2733 lines of tests.** Every run in
`recordings/` holds `hum.wav` alongside the `pitch_track.csv` and `notes.json`
the current code produced from it. That is a frame-level golden corpus for
free — any reimplementation can be checked against it numerically rather than
by ear. This single-handedly decides how risky option B is.

---

## Ruled out: serving the TUI (`textual-serve` / `textual-web`)

Recorded here so it does not get re-proposed.

Both work the same way: the app runs as a terminal process on a server and
`xterm.js` in the browser acts as a screen and keyboard over a websocket. It is
three lines of code, and for most Textual apps it is the right answer.

It is wrong for this one. `sounddevice` binds PortAudio in the process that
calls it, which under a relay is the **server**. The result is an app that
faithfully records the server's microphone and shows it to a user in another
country. There is no configuration that fixes this; the browser is a terminal
emulator in that design and terminals do not carry audio.

Two secondary points, both moot given the above:

- Textualize wound up as a company in mid-2025. `textual-serve` is still
  maintained (1.1.3, Nov 2025), but `textual-web` — the hosted public-URL
  relay — has not shipped since 0.8.0 in Aug 2024 and still describes itself
  as beta.
- Even with audio solved, one OS process per visitor is a poor fit for an app
  whose sessions are minutes long and whose users are many.

---

## Option A — run the existing Python in the browser (Pyodide)

> **Built.** This is what `web/` implements, and it is now an installable,
> fully offline PWA. The performance risk below did not materialise: analysis
> costs a fraction of the 23 ms hop budget. See `web/README.md`.


**What.** Ship CPython compiled to WebAssembly, load `humm2melody` into it,
capture audio in JavaScript and pass the samples in.

**How it maps onto this code.** Better than it sounds. numpy is one of the
packages Pyodide ships, and numpy is the only thing the DSP core needs. The
capture path becomes:

```
getUserMedia → AudioWorklet (audio thread, 128-sample quanta)
             → postMessage → Web Worker running Pyodide
             → analyse_frame() / analyse_signal()
             → postMessage → main thread → UI
```

`analyse_signal()` already exists for exactly this shape of work and already
guarantees offline analysis sees what the live path saw. `segment_with_sensitivity()`,
`pause_settings()`, `sensitivity_settings()` and the whole of `analysis.py`
come along untouched, which means the dials keep behaving identically.

**What survives:** the entire DSP core, the dial calibration, `render()`,
`profiles.py` (pure stdlib), the semantics of `sessions.py`.
**What is rewritten:** the UI, capture, output, and storage.

**Architectural constraints worth knowing before committing:**

- An `AudioWorklet` runs on the audio thread and **cannot** host Pyodide. The
  worklet must stay a dumb forwarder — which is precisely what the PortAudio
  callback in `audio.py` already is, so the design carries over.
- Pyodide wants a **module-type worker**; classic `importScripts()` workers are
  not supported.
- Worker vs main thread is a real trade-off, not a default. Crossing the
  boundary costs a copy each way, and there are reports of main-thread Pyodide
  massively outperforming a worker when the payload is chatty. Our payload is
  a 2048-sample float32 window ~43 times a second, which is small, and
  transferables avoid the copy. Still: **measure both before choosing.**

**Costs.** First load pulls the Pyodide runtime plus numpy — on the order of
ten megabytes, which needs measuring rather than assuming. A service worker
caches it once, so this is a first-visit cost, not a per-visit one. That is
also the strongest argument for making this a PWA specifically rather than a
plain web page.

**Risk.** Live-readout latency. YIN over a 2048-sample window is a 4096-point
FFT and some cumulative sums — trivially cheap, and wasm numpy is compiled, not
interpreted, so 43 frames/sec should be comfortable. It is nonetheless the one
thing that could sink this option, so it is what the spike should test first.

**Verdict: the recommended path.** It keeps one implementation of the
algorithm. Given that every threshold in `segment.py` was hand-tuned against
real recordings, and that per-user calibration (roadmap item 1) is about to
make that tuning richer still, a second implementation is a liability the
project should not take on unless forced.

---

## Option B — port the DSP to TypeScript

**What.** Reimplement `pitch.py` and `segment.py` in TypeScript, run natively
in the browser, no Python anywhere.

**How it maps onto this code.** ~1070 lines to port, of which the genuinely
fiddly parts are the FFT-based difference function, the cumulative mean
normalisation, the median filter, and the glide/onset masks. There is no FFT
in the browser's standard library that fits — `AnalyserNode` gives magnitudes
only, not the complex spectrum `_difference_function()` needs — so that is
either a small library or forty lines of hand-written radix-2.

**What makes it far less risky than it sounds.** The golden corpus. Every
`recordings/*/pitch_track.csv` is a frame-by-frame record of what the Python
detector concluded, and `notes.json` is what it segmented. A port can be
driven to agreement numerically, frame by frame, across 46 real recordings
including the awkward ones the thresholds were tuned against. That converts
"did I port it right?" from a judgement call into a test suite.

**Costs.** Startup is instant and the bundle is small — tens of kilobytes
against Pyodide's tens of megabytes. Offline is trivial. It is by a distance
the best *product*.

The cost is permanent, not one-off: **two implementations of the same
algorithm, forever.** Every threshold change, every calibration feature, every
fix to the glide gate has to land twice and be re-verified twice. Roadmap items
1 and 2 both push directly on this code. That is the reason this is not the
recommendation despite producing the better artefact.

**Verdict: the right destination, the wrong starting point.** Reasonable as a
second pass once the web UI has proven itself and the DSP has stopped moving —
and if it happens, the Python stays as the reference implementation that the
corpus tests define.

---

## Option C — capture in the browser, analyse on a server

**What.** The browser records with `MediaRecorder`, uploads the audio, an HTTP
service runs the existing unmodified Python, and returns `notes.json`.

**How it maps onto this code.** Most cleanly of the three. `analyse_signal()`
→ `segment_with_sensitivity()` → `render()` is already the offline pipeline
that `humm2melody analyze` drives; wrapping it in an endpoint is close to
mechanical. `sessions.py` keeps working, because the server has a real
filesystem.

**What it gives up, and this is the whole argument:**

- **The live readout.** Pitch, note name and cents at ~43 frames/sec is the
  app's most distinctive feature and it cannot survive a round trip. You either
  lose it, or stream over a websocket and inherit exactly the latency and
  connection problems the crackling fix was about, or implement it separately
  in JS — at which point you are doing option B anyway, for the hardest part.
- **Offline.** There is no PWA here in any meaningful sense.
- **Privacy.** Recordings of the user's voice leave their device and land on
  someone's disk. For a toy that people hum into, this is a real objection and
  it invites obligations — retention, deletion, a policy — that a local app
  simply does not have.
- **Running cost.** Someone pays for CPU, storage and uptime forever.

**Verdict: only as a deliberate hybrid.** If option A's live readout turns out
too slow in wasm, the sensible fallback is a cheap approximate meter in JS for
the live view with the authoritative pass server-side. Choosing C outright,
though, trades away the app's identity to save work that option A largely
avoids anyway.

---

## What gets rewritten no matter which option wins

Worth budgeting honestly, because it is the same work in all three and it is
larger than the analysis question everyone focuses on.

| Concern | Today | On the web |
| --- | --- | --- |
| **UI** | `tui.py`, 1331 lines of Textual | rewritten from scratch — Textual does not cross over |
| **Capture** | `Recorder` + PortAudio callback | `getUserMedia` + `AudioWorklet` |
| **Output** | `Player` + `OutputStream` | `AudioBuffer` + `AudioBufferSourceNode` |
| **Storage** | `recordings/<timestamp>/` on disk | OPFS or IndexedDB |
| **Profiles** | `profiles/<name>.json` | same JSON, different store |

`tui.py` is the single biggest line item and none of it survives. That said,
the *layout* survives: tabs, the dials, the piano roll, the detail table and
the run list are all designed already, and redesigning is not required — only
reimplementing. The piano roll in particular gets strictly better, since the
one-character-cell limitation noted in the roadmap disappears on a canvas.

---

## PWA specifics

Things that will bite, collected in one place:

- **Secure context.** `getUserMedia` requires HTTPS. `localhost` is exempt for
  development; nothing else is.
- **Permission is per-origin and revocable.** The app needs a real state for
  "mic denied", which the desktop version never had to handle — `AudioError`
  is the closest existing analogue.
- **Autoplay policy.** Audio output must be initiated by a user gesture. The
  first playback needs a click, and the `AudioContext` should be created or
  resumed inside that handler.
- **Storage is evictable.** IndexedDB and OPFS can be cleared under pressure.
  Call `navigator.storage.persist()`, and treat eviction as possible rather
  than as a bug — recordings accumulate at roughly 2.6 MB per minute of
  humming today, so this is not hypothetical. Roadmap item 5 (FLAC instead of
  WAV) becomes considerably more attractive here than it is on desktop.
- **iOS is the platform to test first, not last.** Safari's handling of
  `getUserMedia` inside an installed standalone PWA has historically been the
  weakest link, and iOS has no alternative engine to fall back to. Verify on a
  real device early; do not assume desktop Chrome behaviour generalises.
- **Service worker.** Under option A this is what makes the download tolerable
  — cache the Pyodide runtime and numpy on first visit and the second visit is
  fast and offline.

---

## Suggested staging

1. **Spike the one thing that could sink it.** A page that loads Pyodide plus
   numpy in a worker, feeds it 2048-sample windows from an `AudioWorklet`, and
   reports achieved frames/sec against the 43 the desktop app manages. Nothing
   else. If this holds, option A is settled and everything after it is ordinary
   work.
2. **Offline first, live second.** Get record → `analyse_signal` →
   `segment_with_sensitivity` → notes → `render()` → playback working on a
   fixed recording. This exercises the whole DSP path with no timing pressure.
3. **Verify against the corpus.** Run the browser build over the existing 46
   recordings and diff against their stored `pitch_track.csv` and `notes.json`.
   Under option A this should match to the bit; anything that does not is a
   porting bug in the plumbing, not in the DSP.
4. **Then the live readout, then the UI, then storage, then the PWA shell.**

---

## Open questions

- **Who is this for?** A PWA that anyone can open is a different product from a
  local tool with a browser UI. If it is only ever the two of us, a local
  server bound to `localhost` with a browser front end skips most of this
  document, including all of the storage and iOS problems.
- **Does the web version replace the TUI or sit beside it?** Beside it means
  `tui.py` keeps being maintained and the DSP core must stay free of anything
  browser-specific — which it currently is, and which is worth protecting
  deliberately rather than by luck.
- **Does per-user calibration (roadmap items 0–2) land before or after this?**
  It touches the DSP and the profile schema hard. Landing it first means
  porting a moving target; landing it after means the web version ships without
  the feature the roadmap ranks highest.
