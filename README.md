# humm2melody

Hum a melody into your microphone and get back the notes to play on a keyboard.

A terminal app: press **Start**, hum, press **Stop**. While you hum it shows the
note it is hearing in real time; when you stop it lays the melody out as a
piano-roll timeline plus a plain list of notes you can read off and play.

Press **p** and it plays the transcription back to you as tones, with a playhead
moving across the timeline — so you can tell straight away whether it heard you
correctly, before you go anywhere near a keyboard.

Every run is recorded to disk automatically, so you can go back and work out why
a transcription came out the way it did.

![humm2melody: humming a melody, transcribing it, and playing it back](docs/demo.gif)

> ### 🤖 This is a vibe-coded project
>
> Every line of this repository — the YIN pitch detector, the segmentation, the
> TUI, the tests, this README — was written by an LLM (Claude) from
> conversational prompts. I described what I wanted, pushed back on what came
> out, and it wrote the code. I did not hand-write the DSP.
>
> It works, and it is tested (193 tests, no microphone required). But treat it
> accordingly: it has had no expert review, the signal-processing choices were
> made by a model rather than by someone who does this for a living, and the
> only real-world validation is that it correctly transcribed some humming into
> a laptop microphone. Do not put it anywhere that matters without reading it
> yourself.

## Requirements

- macOS or Linux, Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- PortAudio (the C library behind microphone capture)

```bash
brew install portaudio          # macOS
sudo apt install libportaudio2  # Debian/Ubuntu
```

## Install

```bash
uv sync
```

## Run

```bash
uv run humm2melody
```

On the first run macOS will ask for microphone access **for your terminal app**
(Terminal, iTerm, VS Code…), not for Python itself. If you never see the prompt
or the level meter stays flat, enable it under
*System Settings → Privacy & Security → Microphone*.

### Keys

| Key | Action |
| --- | --- |
| `space` or the button | Start / stop recording |
| `p` | Play the detected melody back as tones |
| `enter` | Load the run highlighted in the sidebar |
| `r` | Rename that run |
| `d` | Delete that run (asks first) |
| `[` / `]` | Pitch sensitivity − / + — re-transcribes instantly |
| `<` / `>` | Pause sensitivity − / + |
| `m` | Cycle playback: tones / your hum / both |
| `c` | Clear the display (saved runs are untouched) |
| `q` | Quit |

Use `↑`/`↓` in the **Recordings** sidebar to pick a run.

### Choosing an input device

```bash
uv run humm2melody --list-devices
uv run humm2melody --device 2
```

## Saved runs

Every recording is written to `recordings/` automatically — including the ones
where nothing was detected, since a failed transcription is exactly what you
want to inspect later.

![Renaming, loading and deleting saved runs from the sidebar](docs/sessions.gif)

```
recordings/2026-08-19_14-32-05/
    hum.wav          the raw microphone input, 16-bit mono
    playback.wav     the tones the app plays back
    notes.json       detected notes, timings, tuning, plus run metadata
    pitch_track.csv  every analysis frame: time, freq, confidence, rms
```

`pitch_track.csv` is the one to reach for when a note comes out wrong: it is the
detector's frame-by-frame opinion *before* smoothing and segmentation discarded
anything, at roughly 43 rows per second. Plot `freq` against `time` and an
octave slip or a dropped note is usually obvious.

`playback.wav` is rendered when the run is saved rather than captured from the
speaker, so it is present even if you never pressed play. Rendering is
deterministic, so it is byte-for-byte the audio you would have heard.

Runs are named by timestamp. Renaming one keeps the timestamp prefix and appends
a slug (`2026-08-19_14-32-05__Chorus-idea`), so runs stay chronological and names
stay unique; clearing the label reverts to the bare timestamp.

```bash
uv run humm2melody --output ~/humming   # save somewhere else
uv run humm2melody --no-save            # do not record to disk at all
```

Deleting from the sidebar removes the whole run directory and asks for
confirmation first. The store refuses to touch anything outside its output
directory or any directory without a `notes.json`, so a stray path cannot turn
into a recursive delete of something you care about.

## Humming for best results

The detector wants a clear, sustained pitch, so:

- Hum on an open-ish sound (`mmm` or `ahh`) rather than whistling quietly.
- Hold each note for at least ~0.2 s. Anything under 90 ms is discarded as noise.
- Leave a small gap between repeated notes, otherwise two `E4`s in a row merge
  into one long `E4` — the detector hears pitch, not attacks.
- Sliding between notes is fine — the glide gate discards the slide and keeps
  the held pitch. But do *hold* each note; a phrase that never settles anywhere
  has no notes in it to find.
- Hum in a comfortable range. Detection covers 65–1200 Hz (C2–D6).

The tuning column tells you how far off you were. A consistent offset is normal
and harmless — but if it sits near ±50¢ you are on a semitone boundary, where
small wobbles flip notes between two neighbours and corrupt the intervals rather
than just the key. `analyze` reports this as the tuning offset.

## How it works

| Module | Job |
| --- | --- |
| `audio.py` | Capture the mic and run the analysis loop |
| `pitch.py` | Estimate the fundamental of one frame (YIN) |
| `segment.py` | Turn the frame-by-frame pitch track into note events |
| `playback.py` | Render the detected notes back to audible tones |
| `sessions.py` | Save, list, rename and delete runs on disk |
| `tui.py` | The Textual interface |

**1. Capture.** PortAudio delivers 512-sample blocks at 22.05 kHz. The audio
callback does nothing but copy each block onto a queue — anything slower there
causes dropouts. A worker thread owns a 2048-sample sliding window (~93 ms) that
advances one block (~23 ms) at a time, giving roughly 43 pitch estimates per
second.

**2. Pitch.** Each window goes through [YIN][yin]: build the squared-difference
function `d(τ)` via FFT, normalise it into the cumulative mean normalised
difference so it starts at 1 and dips at the period, then take the *first* dip
below an absolute threshold rather than the deepest one. That "first, not best"
rule is what stops the detector from locking onto a harmonic and reporting the
note an octave high. A parabolic fit around the dip gets the period to
sub-sample accuracy, and `1 − cmnd(τ)` falls out as a confidence value.

**3. Segmentation.** The raw track is too jittery to read directly — vibrato,
glides and the occasional slip all appear as pitch changes. So the track is
gated by confidence and level, converted to fractional MIDI numbers, run through
a NaN-aware 5-frame median filter (which removes single-frame octave errors),
and rounded to the nearest semitone.

Then the glide gate: singing is *legato*, so the voice slides between notes
rather than jumping. Snapping every frame of a slide invents a note for each
semitone it crosses — humming C-D-E in one breath transcribes as the chromatic
run `C4 C#4 D4 D#4 E4`. Frames where pitch is sliding faster than
`max_glide_rate` are therefore discarded, keeping only held pitch.

Getting that to work needed one non-obvious step. Vibrato has a *higher*
instantaneous slope than a glide (±40 cents at 5 Hz swings past 6 semitones/sec),
so measuring the slope directly splits steady notes in two. Measuring over a
longer window fixes vibrato but then eats discrete note changes as well. The
answer is to median-filter over a vibrato cycle first: a median removes
oscillation but *preserves edges*, so vibrato flattens while a real note change
stays a sharp step, and a short slope measured on top cleanly separates a
sustained slide from an instant jump. Equal-pitch runs become note events; a
dropout shorter than 70 ms does not split a note, and events shorter than 90 ms
are dropped.

**4. Display.** The timeline is drawn from the note list at whatever width the
terminal has, one row per semitone with white keys bright and black keys dimmed.

**5. Playback.** Each note is rendered as a fundamental plus two quiet harmonics
under an attack/decay/release envelope — a bare sine reads as a beep and blurs
together on repeated notes, whereas an audible attack makes each one distinct.
Notes are played at their **snapped** pitch, not the raw hummed frequency: the
point is to audition what you would actually play, so if the transcription is
wrong you hear it immediately.

Two design details worth knowing, because both were bugs before they were
decisions:

- **Smoothing corrects pitch, never voicing.** The median filter is re-masked
  with the original silences afterwards. Without that, it spreads a note into
  the surrounding silence, inflating every duration by roughly the filter width
  and welding repeated notes together across their gap.
- **Voicing is judged on a short slice, pitch on a long one.** The 93 ms window
  is needed to measure a low fundamental, but using it to detect silence smears
  note boundaries by its own length — a gap shorter than the window never looks
  fully silent. Energy is therefore measured over the ~23 ms at the window's
  centre, aligned with the frame's timestamp.

[yin]: http://audition.ens.fr/adc/pdf/2002_JASA_YIN.pdf

### Tuning the detector

The thresholds live in the signatures of `detect_pitch` and `segment_notes`:

| Parameter | Default | Raise it to… |
| --- | --- | --- |
| `threshold` | `0.15` | be stricter about what counts as pitched |
| `min_confidence` | `0.55` | drop more breathy/uncertain frames |
| `min_rms` | `0.006` | ignore more background noise |
| `min_duration` | `0.09` s | discard more short blips |
| `gap_tolerance` | `0.07` s | bridge longer dropouts within one note |
| `smoothing` | `5` frames | smooth harder (at the cost of fast passages) |
| `max_glide_rate` | `3.0` st/s | be stricter about what counts as *held* rather than sliding (`None` disables) |

## Tests

```bash
uv run pytest
```

The tests never touch a microphone or speaker: the detector is driven with
synthesised tones, and the TUI runs headless under Textual's `Pilot` with the
audio classes faked out. Every test app gets a `tmp_path` output directory, so
running the suite never writes into `recordings/`.

The strongest test is a round trip — render notes to audio with the playback
code, feed that back through the detector, and check the same notes come out.

## The two dials

Voices are not keyboards. An untrained voice slides between notes, overshoots
and settles, and returns to "the same" pitch a little flat or sharp each time —
so how big a pitch difference *should* count as a different note depends on who
is humming.

Two dials, both of which **re-transcribe the recording you already made**. No
second take: the frame-by-frame pitch track is kept, so only the segmentation is
redone. They work on saved runs too — load one from the sidebar and turn a dial.

```
Pitch       [ ]  [····●····]  5/9   balanced
Pauses      < >  [····●····]  5/9   balanced
```

**Pitch** (`[` `]`) is how finely to distinguish pitches. Low settings smooth
harder, require longer notes, and cluster nearby pitches so small wobbles read
as one note. High settings resolve smaller intervals at the cost of picking up
wobble.

**Pauses** (`<` `>`) is how eagerly to split notes in *time*. This answers a
different question, which is why it is a separate dial: two presses of the same
key are a single unbroken pitch, so no amount of pitch resolution separates
them. The only evidence of a second note is the **attack**.

Each dial rather than a pile of sliders, because within each concern the
parameters are not independent: a voice that wanders needs *both* heavier
smoothing and a willingness to treat nearby pitches as the same note, and most
combinations of five sliders are nonsense.

### Onsets: how repeated notes are separated

Silence is not required and often never happens — a piano note is still ringing
when the next one starts. So loudness is tracked in dB against the median of the
preceding few frames, and a sharp enough rise starts a new note even at constant
pitch. Measuring against the median rather than the minimum matters: a single
dropped frame is a detector artefact, not a pause, and would otherwise register
as a re-attack.

At pause level 1 this is off entirely and only real silence separates notes; at
7 or above, three strikes of one key separate correctly even with **no gap at
all** between them.

## Comparing against your voice

`m` cycles what `p` plays:

| Source | What you hear |
| --- | --- |
| **Tones only** | the transcription, as you would play it |
| **Your hum** | the original recording |
| **Hum + tones** | both together |

The overlay is the most direct check there is: if the tones sit inside the hum,
it heard you right; if they beat against it or wander off, it did not.

### Why clustering, not just merging

Pitches are clustered across the *whole* recording, not merely between
neighbours. If you hum low-high-low and your two lows land 45 cents apart either
side of a rounding boundary, they come out as two *different* notes — and
merging adjacent notes cannot fix it, because the two lows are not adjacent. The
high one is between them.

## Diagnosing a bad transcription

When a run comes out wrong, `analyze` re-runs detection over its saved
`hum.wav` and reports what the detector actually saw — before smoothing and
segmentation discarded the evidence.

```bash
uv run humm2melody analyze recordings/2026-08-19_14-32-05
uv run humm2melody analyze <run> --expect "C4 D4 E4"
```

```
── pitch ──────────────────────────────────────────────
  range             193.4 - 220.0 Hz (G3 - A3)
  median            195.9 Hz (G3)
  tuning offset     -5 cents
  gliding frames    24%
  octave jumps      0
  within-note wobble 18 cents sd
```

What the numbers mean:

| Reading | What it tells you |
| --- | --- |
| **tuning offset** | How far the whole performance sits off the A440 grid. Near ±50 means every note is a coin-flip between two semitones and vibrato decides — that corrupts intervals, not just the key. |
| **gliding frames** | Fraction of the time you were sliding rather than holding. High means the segmenter is snapping every semitone the slide passes through into its own note. |
| **octave jumps** | YIN flipping between f0 and 2·f0. |
| **within-note wobble** | Vibrato depth. Large values push notes over semitone boundaries. |
| **rms percentiles** | Whether you were loud enough to clear the silence gate. |

`--expect` scores the result, and distinguishes a *wrong* transcription from a
*transposed* one — humming in a comfortable key is a correct transcription of
what you actually sang, not an error:

```
  verdict:  intervals match, transposed by -5 semitones
```

`--sweep` searches detection parameters for the setting that best matches what
you meant, which is how you find out whether a failure is a tuning problem or a
fundamental one:

```bash
uv run humm2melody analyze <run> --sweep --expect "C4 D4 E4"
```

## Demo mode and the screen captures

`--demo` replays a synthetic hum through the real analysis pipeline instead of
opening the microphone. It is how the GIFs above are made, and it is handy for
trying the app on a machine with no working input device:

```bash
uv run humm2melody --demo
```

The captures are scripted with [VHS](https://github.com/charmbracelet/vhs), so
they can be regenerated rather than re-recorded by hand:

```bash
brew install vhs
vhs docs/demo.tape
vhs docs/sessions.tape
```

Because demo mode is deterministic and the tests assert the demo melody still
transcribes exactly, a regenerated capture cannot silently start showing a
broken app.

## Limitations

- **Monophonic only.** One voice at a time; it cannot transcribe chords.
- **No rhythm.** You get note start times and durations in seconds, not a
  quantised score with a time signature. Reading durations off the timeline is
  the current answer.
- **No key detection**, no transposition, no MIDI or MusicXML export yet.
- Playback is a plain synth tone, not a piano sample.
