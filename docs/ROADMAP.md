# Outstanding work

Features discussed but not built, plus known limitations. Ordered roughly by
value. Each entry says what it is, why it matters, and what is already in place
— the last part matters most, because several of these are smaller than they
look.

Written to be picked up cold: assume the reader has not seen the conversation
that produced them.

---

## 0. Fill in the Calibrating and Training tabs

Both tabs exist and are placeholders. The app now has profiles, so there is
somewhere to put what calibration learns — `Profile.calibration` is defined and
persisted, with every field currently `None`. Items 1 and 2 are the content for
those two tabs.

---

## 1. Per-user vocal calibration

**What.** Ask the user to sing a short scale, learn their voice, and set the
dials' defaults from that instead of from global constants.

**Why it is the most valuable item here.** Every threshold in `segment.py` was
tuned by hand against one person's recordings. That is exactly the thing that
should be measured per user rather than guessed once. It is also the honest
version of a calibration already done crudely: the pitch dial was recentred
because one user kept pushing it to 8–9.

**What it would learn.**

| Measurement | Sets |
| --- | --- |
| Comfortable range (lowest/highest reliable note) | `fmin`/`fmax`, warn when out of range |
| Typical within-note drift | pitch dial default, `max_step` |
| Typical tuning offset | whether to trust `tuning="auto"` per run |
| How much they slide between notes | `max_glide_rate` default |
| How cleanly they separate repeats | pause dial default |
| Typical loudness | `min_rms` |

**Already in place.** `analysis.py` computes nearly all of these already —
`tuning_offset_semitones`, `glide_fraction`, `note_cents_spread`, `f0_low`,
`f0_high`, rms percentiles. `sweep()` already searches parameters against an
expected answer. A calibration run is largely: capture a known scale, run the
existing diagnosis, persist the result.

**Already answered.** Profiles exist: `profiles/<name>.json`, chosen at startup,
holding dial positions and an empty `Calibration` waiting to be filled. Runs
record which profile made them.

**Still open.** Whether dials should show "your default" versus the global one.
What happens when a new recording disagrees with the stored profile. Whether
calibration should re-run automatically when it goes stale.

---

## 2. Training mode

**What.** Interactive real-time coaching: the app asks for a note, shows how
close you are, and tells you when you are holding it.

**Why.** The other half of the problem. Everything so far makes the app better
at understanding an imperfect voice; this makes the voice better. It also feeds
item 1 — a training session is a calibration session with feedback attached.

**Already in place.** More than it seems. The live readout already produces
pitch, note name and cents deviation at ~43 frames/sec, and `NoteReadout`
already renders in-tune/sharp/flat. The missing parts are a target to compare
against, a scoring rule, and a lesson structure.

**Design questions — these are the real work, not the code.**

- What does it ask for? A fixed scale, intervals, or notes from a melody you
  just hummed (most motivating, arguably).
- What counts as correct? Within N cents, held for M milliseconds. Both should
  probably come from the user's profile rather than being fixed.
- How is progress shown — a streak, a per-note accuracy history, a target you
  must hold inside a moving band?
- Does it drill *pitch accuracy*, *interval accuracy*, or *steadiness*? These
  are different skills and the third is what most improves transcription.

**Suggestion.** Start with one exercise: show a target note, play it, ask the
user to match and hold it for one second, show a live band they must stay
inside. That alone is useful and exercises every piece the fuller version
needs.

---

## 3. Refresh the blog post

The post at <https://mufradat.com/posts/humm2melody/> describes v0.1 and is now
substantially out of date. It predates:

- the glide gate (legato humming no longer transcribes as a chromatic run)
- segment-then-snap and automatic tuning correction
- both sensitivity dials and the mix dial
- comparison playback
- the crackling fix
- starring runs

The crackling diagnosis is the best story in the project and is missing
entirely: a phone recording of the speakers showed artefact bursts 64 ms apart
against a 65 ms output buffer, which identified buffer underrun caused by
pulling audio through a Python callback that has to acquire the GIL.

Follow `docs/MAINTENANCE.md` §5. Note the trap recorded there: never
`git add -A` on the server.

---

## 4. Rhythm and quantisation

Note timings are reported in seconds. There is no tempo estimate, no bar lines,
no note values. Reading durations off the timeline is the current answer.

Would need: onset times (already available — `Note.attack` marks detected
attacks), a tempo estimate from inter-onset intervals, then snapping durations
to a grid. The onset detection added for the pause dial is the hard half and it
already exists.

---

## 5. Compressed audio storage

**Asked for:** save audio as MP3 instead of WAV.

**Recommendation: yes for sharing, no for the stored master — and FLAC, not
MP3, if the goal is disk space.** The reasoning, since it is not obvious:

`hum.wav` is not just a recording, it is the analysis master. It exists so a
run can be re-analysed later at different thresholds, and `analyze` and the
dials both depend on that. MP3 is lossy in exactly the places that matter here:

- it smears transients, and transients are now load-bearing — onset detection
  is what separates repeated notes for the pause dial
- it alters low-frequency phase, and a low hum sits at 100–200 Hz where the
  encoder has least headroom
- re-analysis would then be measuring the encoder as much as the voice

Three options, in order of preference:

| Option | Size | Analysis | Cost |
| --- | --- | --- | --- |
| **FLAC master** | ~50–60% of WAV | lossless, identical results | needs `soundfile`/libsndfile |
| **WAV master + MP3 export** | unchanged on disk | untouched | an encoder for the export only |
| **MP3 master** | ~10% of WAV | degraded, subtly | cheapest disk, worst fidelity |

For context on the actual numbers: `hum.wav` is mono 16-bit at 22.05 kHz, about
44 KB per second — roughly 2.6 MB per minute of humming. Twenty-five runs so
far come to a few tens of megabytes. This is a real but not urgent problem.

**Suggested shape.** Keep a lossless master (switch it to FLAC if size matters),
and add an explicit "export this run as MP3" action for sharing, where lossy is
exactly right. `playback.wav` is a different case — it is regenerable from
`notes.json`, so it could be dropped entirely rather than compressed.

---

## 6. Export

No MIDI or MusicXML output. `notes.json` has everything required — MIDI number,
start, end, duration — so an export is a small, self-contained piece of work.
MIDI first; it is what would actually get used.

---

## 7. Key detection and transposition

The app reports absolute pitch. Someone humming "do re mi" in a comfortable key
gets a correct transcription that does not look like what they expected.
`analysis.compare()` already distinguishes a *transposed* result from a *wrong*
one, so the logic exists; it is not surfaced in the UI.

Would show: detected key, and an option to transpose to C or to a chosen key.

---

## 8. Smaller items

- **Starred-first sorting, or a favourites filter.** Deliberately not done: the
  list stays newest-first so a fresh recording never appears below older
  favourites. Easy now that the flag is persisted.
- **Re-analysing a saved run at different thresholds from the CLI.** Mostly
  done — `humm2melody analyze <run> --sweep` exists. Not exposed in the TUI
  beyond the dials.
- **The piano roll cannot show a gap narrower than one character cell**, so
  repeated notes can look joined even when they are correctly separate. The
  detail table is authoritative.
- **Polyphony.** Out of scope. YIN is monophonic by construction; chords would
  need a different detector entirely.

---

## Open questions for the user

- **Is the hum+tones overlay still worse than tones-only?** The crackling fix
  removed buffer underruns (verified acoustically: clicky frames 12–19% → 0%),
  but the overlay was reported as *disproportionately* worse, and that gap was
  never fully explained. If it persists, record another phone memo — the
  diagnostic loop in `analysis.py` plus the HF-burst method works.
- **Does the recalibrated pitch dial sit right now?** It was recentred so that
  the old level 8 is the new level 5. If the dial is still being pushed to the
  end, it needs shifting again — or, better, item 1.
