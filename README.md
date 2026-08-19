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
> It works, and it is tested (458 tests, no microphone required). But treat it
> accordingly: it has had no expert review, the signal-processing choices were
> made by a model rather than by someone who does this for a living, and the
> only real-world validation is that it correctly transcribed some humming into
> a laptop microphone. Do not put it anywhere that matters without reading it
> yourself.

## Profiles and tabs

The app opens by asking who is humming. Pick an existing profile, create one,
or continue as **Guest** — a guest session works fully but remembers nothing.

A profile stores the dial positions you have settled on, and is where
calibration will record what it learns about your voice. Each profile is a
single JSON file under `profiles/`, so one can be copied, edited by hand or
deleted without touching anything else. Deleting a profile keeps its
recordings. Press `u` to switch profile at any time. The app also reopens on whichever tab
you were last using, remembered per profile.

```bash
uv run humm2melody --guest              # skip the chooser
uv run humm2melody --profile Ahmed      # use a profile directly
uv run humm2melody --profiles ~/voices  # keep profiles somewhere else
```

The interface has three tabs:

| Tab | What it does |
| --- | --- |
| **Recording** | everything described below — hum, transcribe, play back, keep runs |
| **Calibrating** | learn your voice once, and set the dials from it |
| **Training** | placeholder: help your voice get steadier |

### Calibrating

Three short recordings, driven entirely by `space`:

1. your lowest comfortable note
2. your highest comfortable note
3. a familiar tune — press `l` to hear it, then sing it back

The app then searches every dial combination for the pair that best recovers
the melody, and adopts it. What it learns is saved to your profile: range,
tuning offset, how much you drift while holding a note, how much you slide
between notes, your accuracy against the melody in cents, and which register
you naturally sang in.

Everything is compared as **intervals**. If you sing the tune an octave down
because that is where your voice sits, that is a correct performance — it is
reported ("you sang it 1 octave down"), not counted against you.

Being off is fine — that is the thing being *measured*, and it comes back as an
accuracy figure rather than a failure.

When the reply does not match well, nothing is adopted automatically, but the
result stays on screen with a choice: `y` keeps it, `space` tries again. Range,
tuning and steadiness are measured from the singing itself and hold regardless
of whether the melody was matched, so there is usually something worth keeping —
imperfect settings still beat none. Only accuracy and register need the melody
to line up, and they are withheld when they cannot be computed.

The pane shows live feedback while you sing — a record indicator, the note it
is hearing, an input meter — and afterwards draws what it learned: your range
against the singable span, a tuner needle for your tuning offset, and bars for
steadiness, style and accuracy. Buttons mirror every key, so none of it has to
be memorised.

A confident calibration is adopted the moment it finishes — the **Saved** button
is showing state, not a control you missed. When the app is unsure it adopts
nothing and offers **Keep it** instead.

### What calibration feeds back into detection

Two of the measurements change how the app listens; the rest are recorded but
deliberately unused.

| Measurement | Effect |
| --- | --- |
| **Range** | narrows YIN's search to your voice plus a fifth either side |
| **Tuning offset** | stands in when a run is too short to estimate its own |
| Drift, style, accuracy, register | recorded only — see below |

Narrowing the search is the one thing a measured range can do that the dials
cannot. The dials tune *segmentation*, which runs after pitch detection, so
they can never undo an octave error; YIN can only report a harmonic or
subharmonic that falls inside its search window, and a window that stops short
of one simply cannot produce it. For a B2–F#4 voice the window narrows from
65–1200 Hz to 82–554 Hz, about 42% of the original.

Drift and style are **not** wired in on purpose: the dial search already
compensates for them, and applying both would correct for the same thing twice.
A range narrower than a fourth is ignored as a failed measurement rather than
trusted — nobody's range is one note, and constraining detection around a bad
reading would make notes vanish.

The Training tab is still a placeholder. See `docs/ROADMAP.md`.

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
| `s` | Star that run as a favourite |
| `y` | Keep a calibration the app was unsure about |
| `r` | Rename that run |
| `d` | Delete that run (asks first) |
| `[` / `]` | Pitch sensitivity − / + — re-transcribes instantly |
| `<` / `>` | Pause sensitivity − / + |
| `m` | Cycle playback: tones / your hum / both |
| `n` | Cycle note naming |
| `e` | Edit the detected notes |
| `-` / `=` | Overlay mix: more hum / more tones |
| `c` | Clear the display (saved runs are untouched) |
| `u` | Switch profile |
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
    hum.flac         the raw microphone input, lossless
    playback.mp3     the tones the app plays back
    notes.json       detected notes, timings, tuning, plus run metadata
    pitch_track.csv  every analysis frame: time, freq, confidence, rms
```

The two formats are chosen for different reasons. The hum is the **analysis
master** — `analyze` and both dials re-read it — so it stays lossless; FLAC is
about 45% the size of WAV with identical results. The playback is regenerable
from `notes.json` at any time, so lossy costs nothing and MP3 is about 5% of
the WAV. On a 2.5 s run that is 354 KB down to 60 KB.

Runs recorded before the switch keep their `.wav` files and are read without
migration.

`pitch_track.csv` is the one to reach for when a note comes out wrong: it is the
detector's frame-by-frame opinion *before* smoothing and segmentation discarded
anything, at roughly 43 rows per second. Plot `freq` against `time` and an
octave slip or a dropped note is usually obvious.

`playback.mp3` is rendered when the run is saved rather than captured from the
speaker, so it is present even if you never pressed play. Rendering is
deterministic, so it is byte-for-byte the audio you would have heard.

Press `s` to star a run. Starred runs show a ★ in the sidebar, and deleting one
says so in the confirmation. The mark lives in that run's own `notes.json`
rather than in a central index, so a run directory stays self-describing: copy
it somewhere else and it is still starred, delete it and nothing dangles.

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

**5. Playback.** Audio is *pushed* to the device with blocking writes from a
worker thread, not *pulled* by a Python callback. That difference is audible.
A callback has to acquire the GIL to run, so whenever the UI thread is busy
rendering the terminal, the callback misses its deadline and the device is
handed nothing — producing exactly one click per buffer period. That was
diagnosed from a phone recording of the speakers: the artefact bursts were
spaced 64 ms apart, matching the 65 ms output buffer almost exactly, and the
rendered file itself had *zero* energy above 4 kHz. With blocking writes the
device is fed from PortAudio's own ring buffer by C code that never needs the
GIL, and `write()` releases the GIL while it waits, so a stalled UI costs
latency rather than clicks.

Each note is rendered as a fundamental plus two quiet harmonics
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

`-` and `=` set the balance:

```
Mix         - +  [····●····]  5/9   balanced
```

It is an equal-power crossfade, but deliberately not centred on equal *gain*: a
pure tone is perceptually much louder than a breathy hum at the same amplitude,
so the midpoint favours your voice. Both ends are pulled in slightly so neither
source ever drops to nothing.

## The keyboard

Under the timeline is a piano keyboard spanning the same width, which lights up
as the melody plays and shows the note you are editing. A piano roll tells you
the shape of a tune; this tells you where your hands go, which is the point of
the app. Keys are named inside, in whichever notation you have chosen.

### Composing on it

The keys are clickable. Click one and that note is added to the melody, played
so you can hear it, and selected so the usual editing keys apply — so a tune can
be built entirely by clicking, with `z` to undo a wrong key.

Black keys are only hit in the upper rows where they are drawn; below that the
white key underneath takes the click, as on a real keyboard.

## How full it sounds

`v` switches the voice:

| Voice | What plays |
| --- | --- |
| **Pure** | one tone per note |
| **Rich** | its octave and fifth as well — consonant against any root |
| **Chords** | a triad, with the third taken from the melody itself |

The chord voice picks major or minor by looking at which third the melody
actually uses, rather than assuming major. A third borrowed from the tune
belongs with it; a fixed major third fights a minor melody.

## Playing it slower

`<` and `>` set playback tempo, from half speed to double. Pitch is regenerated
from each note rather than resampled, so slowing a melody down to learn it does
not transpose it.

Tempo applies to the tones only. Speeding up your own recording would need
time-stretching, and simply resampling it would shift the very pitches you are
checking.

## What is not built yet

`docs/ROADMAP.md` lists the outstanding work — per-user vocal calibration,
training mode, rhythm and quantisation, MIDI export, key detection — with what
already exists for each. Several are smaller than they look.

### Why clustering, not just merging

Pitches are clustered across the *whole* recording, not merely between
neighbours. If you hum low-high-low and your two lows land 45 cents apart either
side of a rounding boundary, they come out as two *different* notes — and
merging adjacent notes cannot fix it, because the two lows are not adjacent. The
high one is between them.

## Note naming

`n` cycles how notes are spelled. Pitch is always stored as a MIDI number, so
switching can never change what was detected or what gets played — only how it
is written down.

| Scheme | Spelling |
| --- | --- |
| **English** | C D E F G A B |
| **German** | C D E F G A **H** — and **B** means B♭ |
| **Solfège** | Do Re Mi Fa Sol La Si (fixed do) |
| **Sargam** | Sa Re Ga Ma Pa Dha Ni (lower case = komal) |

German is the one worth knowing about: **H is what English calls B, and B is
what English calls B♭.** Reading a German name with English habits puts you a
semitone out, silently. The choice is remembered per profile.

## Fixing a note by hand

Detection gets things wrong. **Click any note** — in the timeline, in the
`Play this:` line, or in the table — to pick it and start editing. Or press `e`.

| Key | Effect |
| --- | --- |
| `←` `→` | pick a note |
| `↑` `↓` | a semitone higher or lower |
| `shift+↑` `shift+↓` | an octave |
| `,` `.` | move it earlier or later |
| `-` `=` | make it shorter or longer |
| `i` | insert a note detection missed |
| `del` `⌫` | remove one that should not be there |
| `z` / `shift+z` | undo / redo |
| `esc` | done |

The selected note is highlighted in the timeline, the sequence and the table at
once, whichever of the three you picked it in.

The table scrolls inside itself, so a long transcription never pushes the app
past the bottom of the terminal — the window always matches the screen. Edits are written straight back to the run, and its playback is
re-rendered to match.

Editing works even when **nothing** was detected — that is the transcription
most worth building by hand, so `e` then `i` starts one from scratch, taking a
sensible pitch from the recording rather than guessing.

Notes are kept in time order as you move them, so nudging one past its
neighbour cannot leave the table reading out of sequence, and the selection
follows the note itself rather than its position.

Every edit is undoable (50 deep). Since edits write through to the run, without
undo a mistyped key would be permanent.

Writing back is deferred until you pause, and forced when you finish. Saving
re-encodes the run's playback and rebuilds a sidebar row per saved run, which
is far too much to do on every keystroke once you have a few dozen recordings.

Those are the same keys as the pause and mix dials, which works because the
timeline takes focus while editing: a focused widget is offered keys before any
app-level binding, so the two sets cannot collide.

**The recording is never touched.** `hum.flac` and `pitch_track.csv` stay
exactly as captured — an edit corrects the *reading*, not the performance — so
re-analysing later still starts from the original audio.

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
