# Outstanding work

Features discussed but not built, plus known limitations. Each entry says what
it is, why it matters, and what is already in place — the last part matters
most, because several of these are smaller than they look.

Written to be picked up cold: assume the reader has not seen the conversation
that produced them.

## Status at v0.15.0

| # | Item | State |
| --- | --- | --- |
| 0 | Calibrating and Training tabs | Calibrating **done in v0.7.0**, Training **done in v0.15.0** |
| 1 | Per-user vocal calibration | **done in v0.7.0**, wired into detection in v0.8.0 |
| 2 | Training mode | **Done in v0.15.0** — three exercises, live bar, scoring |
| 3 | Refresh the blog post | **Stale.** The post still describes v0.1 — **next** |
| 4 | Rhythm and quantisation | Not started — the hard half already exists |
| 5 | Compressed audio storage | **Done in v0.6.0** |
| 6 | Finish note editing | **Done in v0.10.0**, extended in v0.11.0 and v0.13.0 |
| 7 | MIDI / MusicXML export | Not started — small and self-contained |
| 8 | Key detection and transposition | Not started — the logic exists, unsurfaced |
| 9 | Smaller items | Mixed, see below |

Shipped since this file was first written: profiles and tabs (v0.5.0), FLAC and
MP3 storage (v0.6.0), calibration (v0.7.0), calibration feeding detection and
per-profile tab memory (v0.8.0), note editing and notation schemes (v0.9.0),
insert/delete/undo (v0.10.0), click-to-edit (v0.11.0), the piano keyboard and
tempo dial (v0.12.0), and a playable keyboard with richer playback voices
(v0.13.0).

Three items on this list are now covered by shipped work and are marked as such
below: item 6 is finished, item 9's "starred-first sorting" remains a deliberate
no, and item 9's "re-analyse from the CLI" is served by `analyze --sweep`.

**Recommended next:** item 3, the blog post, which is now fourteen versions out
of date and is the only item with an audience waiting for it.

---

## 0. Fill in the Calibrating and Training tabs — done

Calibrating shipped in v0.7.0 (item 1); Training in v0.15.0 (item 2). Both tabs
now hold real features, and neither depends on anything outstanding.

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

## 2. Training mode — done in v0.15.0

Three exercises in dependency order — hold one note, match a note you have just
heard, climb a major scale — with a target note, a tall live bar showing where
your voice is against it, and a score per note.

The design questions this entry used to pose, answered by what shipped:

- **What does it ask for?** A fixed target per exercise, pitched into the
  singer's calibrated range rather than at a fixed absolute pitch.
- **What counts as correct?** Within 35 cents, held for one second. Tighter
  than the 50 cents at which the app rounds to a note, because practising at a
  rounding boundary teaches nothing.
- **Which skill?** Steadiness first, then matching, then intervals. Steadiness
  is the one that most improves transcription, so it is the exercise you meet
  first.
- **How is progress shown?** Live cents and held time while singing, then a
  verdict, a score and stars; the best score per note is kept, so a retry can
  only help.

Not built, and deliberately: no cross-session progress history. Practice is not
stored in the profile and training runs are not written to `recordings/`.
Worth adding only if someone actually wants to watch a number climb over weeks.

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

## 6. Note editing — done in v0.10.0

Insert (`i`), delete (`del`), and undo/redo (`z` / `shift+z`, 50 deep) joined
the pitch and timing edits from v0.9.0. Editing also works from an empty
transcription, which is the case most worth building by hand.

Notes are re-sorted by start time after every edit and the selection follows
the note rather than its index, so nudging one past its neighbour cannot leave
the table out of order.

Notes are also clickable in all three views — the timeline, the sequence line
and the table — which enters edit mode without needing to know about `e`.

**Still open.** No multi-select, no copy or paste, no dragging a note with the
mouse, no way to edit a run without loading it first.

---

## 7. Export

No MIDI or MusicXML output. `notes.json` has everything required — MIDI number,
start, end, duration — so an export is a small, self-contained piece of work.
MIDI first; it is what would actually get used.

---

## 8. Key detection and transposition

The app reports absolute pitch. Someone humming "do re mi" in a comfortable key
gets a correct transcription that does not look like what they expected.
`analysis.compare()` already distinguishes a *transposed* result from a *wrong*
one, so the logic exists; it is not surfaced in the UI.

Would show: detected key, and an option to transpose to C or to a chosen key.

---

## 9. Smaller items

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
