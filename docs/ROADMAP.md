# Outstanding work

Features discussed but not built, plus known limitations. Each entry says what
it is, why it matters, and what is already in place — the last part matters
most, because several of these are smaller than they look.

Written to be picked up cold: assume the reader has not seen the conversation
that produced them.

## Status at v0.8.0

| # | Item | State |
| --- | --- | --- |
| 0 | Calibrating and Training tabs | Calibrating **done**, Training still a placeholder |
| 1 | Per-user vocal calibration | **done**, and wired into detection in v0.8.0 |
| 2 | Training mode | not started — **next**, and now unblocked by calibration |
| 3 | Refresh the blog post | **stale** — the post still describes v0.1 |
| 4 | Rhythm and quantisation | not started — the hard half already exists |
| 5 | Compressed audio storage | **done in v0.6.0** |
| 6 | MIDI / MusicXML export | not started — small and self-contained |
| 7 | Key detection and transposition | not started — the logic exists, unsurfaced |
| 8 | Smaller items | mixed, see below |

Shipped since this file was written: profiles and tabs (v0.5.0), FLAC and MP3
storage (v0.6.0), calibration (v0.7.0), and a fix for the `analyze` command's
defaults having drifted out of sync with the app.

**Recommended next:** item 2, training mode. Calibration now supplies what it
was missing — a per-user notion of what "correct" means, and a reference melody
with scoring that already measures accuracy in cents.

---

## 0. Fill in the Calibrating and Training tabs

**Scaffolding is done.** Both tabs exist, each with a placeholder explaining
what it is for. Profiles exist and are chosen at startup, so there is somewhere
to put what calibration learns: `Profile.calibration` is defined and persisted,
with every field currently `None`. Runs record which profile made them.

What remains is the content, which is items 1 and 2.

---

## 1. Per-user vocal calibration — done in v0.7.0

Three prompts in the Calibrating tab: lowest comfortable note, highest, then a
familiar tune played back and sung in reply. The app then searches all 81 dial
combinations for the pair that best recovers the melody, and adopts it.

Two decisions worth keeping:

- **Everything is compared as intervals.** A voice that cannot reach the
  reference octave sings the tune transposed, and that is a correct
  performance, not an error. The transposition is measured and reported
  ("you sang it 1 octave down") rather than penalised.
- **It refuses rather than guesses.** If no dial setting recovers the melody,
  nothing is saved and it says so. A wrong calibration is worse than none, and
  the derived numbers are left as `None` rather than reported from a reading
  that was not trusted.

Recorded per profile: range, tuning offset, drift while holding, how much the
voice slides, accuracy against the melody in cents, and which register it was
sung in.

**Wired into detection in v0.8.0.** The measured range narrows YIN's search
window, which is the one thing the dials cannot do — they tune segmentation,
which runs after detection, so they can never undo an octave error. The tuning
offset stands in when a run is too short to estimate its own reliably.

Drift and style are recorded but deliberately not wired: the dial search
already compensates for them, and applying both would double-correct.

**Still open.** Whether the dials should show "your default" versus the global
one. What happens when a later recording disagrees with the stored profile.
Whether calibration should prompt to re-run when it goes stale.

**Worth doing:** calibration takes are not saved anywhere. When a calibration
failed in real use there was no artifact to analyse afterwards, and the cause
had to be reconstructed from a screenshot. Saving the three takes as an
ordinary run would make failures diagnosable with the tools that already
exist.

---

## 2. Training mode

**What.** Interactive real-time coaching: the app asks for a note, shows how
close you are, and tells you when you are holding it.

**Why.** The other half of the problem. Everything so far makes the app better
at understanding an imperfect voice; this makes the voice better.

**Now unblocked.** Calibration already supplies most of the missing pieces: a
reference melody with playback, scoring against it in cents, a per-user record
of accuracy and steadiness to set thresholds from, and a profile to store
progress in. Training is largely calibration with feedback attached and a
target you must hold.

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

## 5. Compressed audio storage — done in v0.6.0

The hum is stored as **FLAC** and the playback as **MP3**, which is the split
the reasoning pointed at: the hum is the analysis master and must stay
lossless, while the playback is regenerable from `notes.json` and so loses
nothing by being lossy.

Measured on a real 2.5 s run:

| File | Was | Now | Saving |
| --- | --- | --- | --- |
| hum | 108 KB (WAV) | 48 KB (FLAC) | 55% |
| playback | 246 KB (WAV) | 12 KB (MP3) | 95% |

Runs recorded before the switch keep their `.wav` files and are still read
without migration. Rewriting somebody's recordings to save disk is not a trade
the app gets to make on their behalf, so `Session.hum_path` simply prefers the
current format and falls back to the older one.

**Still open.** Exporting a run as a single shareable file.

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
