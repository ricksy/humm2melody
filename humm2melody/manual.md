# humm2melody user manual

Hum a melody into your microphone and get back the notes to play on a keyboard.

This manual is the same text you can read in the app's **Manual** tab and on
GitHub.

---

## Get started

1. Start the app: `uv run humm2melody`
2. Choose a profile, or press `g` to continue as a guest.
3. Press `space`, hum a few notes, then press `space` again.
4. Read the notes off the timeline, the `Play this:` line, or the table.
5. Press `p` to hear the transcription played back.

macOS asks for microphone access for your **terminal**, not for Python. If the
level meter never moves, allow it in *System Settings > Privacy & Security >
Microphone*.

The app needs a terminal at least **120 columns** wide. Around 60 rows
shows everything at once; below that the timeline, the note table and the
recordings list scroll inside themselves.

---

## The tabs

| Tab | What it is for |
| --- | --- |
| **Recording** | Hum, transcribe, edit, and play back. |
| **Calibrating** | Teach the app your voice, once. |
| **Training** | Practise hitting a note and holding it. |
| **Manual** | This text. |

Press `u` to switch profile. The app reopens on the tab you used last.

Press `q` to quit. If the keys panel is open, `q` and `esc` close it first.

---

## Record and play back

| Key | Action |
| --- | --- |
| `space` | Start or stop recording |
| `p` | Play back |
| `m` | Choose what plays: tones, your hum, or both |
| `v` | Choose how it sounds: pure, rich, or chords |
| `<` `>` | Play slower or faster |
| `-` `=` | Balance the hum against the tones |

**Compare against your voice.** Press `m` until it reads *Hum + tones*, then
`p`. If the tones sit inside your hum, the app heard you correctly. If they
beat against it, it did not.

**Play it slower to learn it.** `<` slows playback to half speed. Each note is
regenerated rather than resampled, so slowing it down does not change the
pitch.

---

## Tune the transcription

Two dials change how your recording is read. Both re-read the recording you
already made, so you never have to hum again.

| Dial | Keys | What it decides |
| --- | --- | --- |
| **Pitch** | `[` `]` | How small a pitch difference counts as a different note |
| **Pauses** | `,` `.` | How eagerly to split notes apart in time |

Turn **Pitch** down when your voice wanders and one note is read as several.
Turn it up when two notes you meant to be different are read as one.

Turn **Pauses** up when repeated notes run together. This is a separate dial
because pitch cannot solve it: two presses of the same key are one unbroken
pitch, and the only evidence of a second note is the fresh attack.

---

## Calibrate the app to your voice

The **Calibrating** tab learns your voice once, so the dials start where they
suit you instead of at a setting tuned for somebody else.

Three short takes, all driven by `space`:

1. Your lowest comfortable note.
2. Your highest comfortable note.
3. A familiar tune. Press `l` to hear it, then sing it back.

Sing the tune at whatever pitch suits you. The app compares **intervals**, so
singing it an octave down is a correct performance, not a mistake, and it says
so.

Being a note or two off is fine. That is what calibration measures, and it
comes back as an accuracy figure rather than a failure. If the app is unsure it
adopts nothing and offers **Keep it** (`y`), because settings that are merely
imperfect still beat none.

Calibration records your range, how far off concert pitch you sit, how much you
drift while holding a note, how much you slide between notes, and how
accurately you sang the tune. Your range narrows the detector's search, which
is the one thing that prevents an octave error.

---

## Train your voice

The **Training** tab is for the other half of the problem. The app can only
transcribe what you actually sang; if every hummed note lands on the same
pitch, no amount of dial-turning will find a melody that is not in the
recording.

One target note at a time. Press `l` to hear it, `space` to sing it, `space`
again to stop.

`l` holds the note rather than previewing it. The tone keeps sounding while you
sing, so you can match it as you go instead of from memory, and it retunes as
you move through the exercise. Press `l` again, or leave the tab, to stop it.
**Use headphones**: through speakers the microphone hears the tone as well as
your voice, and scores it as though you had sung it. A tall bar shows where your voice is: the green band is the
note, above the band means sharp, below means flat. The tip moves while you
sing, so you can correct yourself mid-note rather than read a verdict
afterwards.

| Key | Action |
| --- | --- |
| `l` | Hold the target note, or stop holding it |
| `space` | Start and stop singing |
| `f` | Next note |
| `b` | Back a note |
| `x` | Change exercise |

Three exercises, in order, because each one needs the one before it:

| Exercise | Skill |
| --- | --- |
| **Hold one note** | Keep a single pitch steady. Nothing else is measurable without it. |
| **Match the note** | Sing back a pitch you have just heard. This is the skill most people are missing. |
| **Climb the ladder** | Move a known distance between pitches, which is what a melody is. |

Exercises are pitched into your calibrated range, so calibrate first if you
have not. Without a calibration they sit around middle C, which suits nobody
in particular.

The bar is damped on purpose: the reading is median-filtered over about 120 ms,
so one bad frame cannot throw the tip. If the bar looks calmer than your voice
feels, that is why.

When you are further off than the scale shows, it zooms out — 150 cents either
side, then 300, 700 or 1500 — and back in once you have settled. The readout
names the note you are actually singing as well as the distance to the target,
so an octave error reads as `F2` rather than as `-1200¢`.

### How the score works

On the note counts as within 35 cents, tighter than the 50 cents at which the
app would round to that note: sitting on a rounding boundary is not the same
as singing the note.

The score weights **holding** the pitch for a second above merely touching it,
because a voice that crosses the right pitch on its way past has not sung the
note. Three stars means you held it. Retrying can only improve your score for
a note, and stopping without making a sound does not count as an attempt.

Nothing from the Training tab is saved to `recordings/` — it is practice, not
a take.

---

## Fix a note by hand

Click any note, in the timeline, the `Play this:` line, or the table. Or press
`e`.

| Key | Action |
| --- | --- |
| `left` `right` | Choose a note |
| `up` `down` | A semitone higher or lower |
| `shift+up` `shift+down` | An octave |
| `,` `.` | Move it earlier or later |
| `-` `=` | Make it shorter or longer |
| `i` | Insert a note the app missed |
| `del` or `backspace` | Remove one that should not be there |
| `z` / `shift+z` | Undo / redo |
| `esc` | Finish editing |

Editing works even when nothing was detected, which is the transcription most
worth building by hand.

Your recording is never changed. An edit corrects the **reading**, not the
performance, so you can always turn the dials again and start from the original
audio.

---

## Compose on the keyboard

The keyboard below the timeline is playable. Click a key and that note is
added, sounded, and selected, so you can build a tune entirely by clicking and
correct it with the editing keys. Press `z` to undo a wrong key.

Black keys respond in the upper part of the keyboard, where they are drawn.
Below that, the white key underneath takes the click.

---

## Note names

Press `n` to change how notes are spelled.

| Scheme | Spelling |
| --- | --- |
| **English** | C D E F G A B |
| **German** | C D E F G A **H**, and **B** means B flat |
| **Solfège** | Do Re Mi Fa Sol La Si |
| **Sargam** | Sa Re Ga Ma Pa Dha Ni |

German is worth knowing about: **H is what English calls B, and B is what
English calls B flat.** Reading a German name with English habits puts you a
semitone out.

Changing the scheme never changes what was detected. Pitch is stored as a
number; only the spelling changes.

---

## Saved runs

Every recording is saved automatically to `recordings/`, including the ones
where nothing was detected. A failed transcription is the one you most want to
look at later.

| Key | Action |
| --- | --- |
| `enter` | Load the highlighted run |
| `s` | Star it as a favourite |
| `r` | Rename it |
| `d` | Delete it |
| `c` | Clear the display, leaving saved runs alone |

Each run holds the raw audio, the tones the app plays back, the detected notes,
and a frame-by-frame pitch track. Loading a run brings back its audio and pitch
track, so you can turn the dials on an old recording.

---

## Hum for the best results

- Hum on an open sound, `mmm` or `ahh`, rather than whistling quietly.
- Hold each note for at least a fifth of a second.
- Leave a small gap between repeated notes. The detector hears pitch, and a gap
  or a fresh attack is what separates two notes of the same pitch.
- Sliding between notes is fine. The app discards the slide and keeps the held
  pitch, but do settle on each note.
- Hum in a comfortable range. Calibrating narrows the search to your voice.

---

## When it goes wrong

Diagnose a saved run from the command line:

```
uv run humm2melody analyze recordings/<run>
uv run humm2melody analyze recordings/<run> --expect "C4 D4 E4"
uv run humm2melody analyze recordings/<run> --sweep --expect "C4 D4 E4"
```

The report shows what the detector saw before smoothing discarded anything:

| Reading | What it tells you |
| --- | --- |
| **Tuning offset** | How far off concert pitch you sat. Near 50 cents means every note is a coin flip between two semitones. |
| **Gliding frames** | How much of the time you were sliding rather than holding. |
| **Octave jumps** | The detector flipping between a pitch and its octave. |
| **Within-note wobble** | How much your pitch moved while holding a note. |
| **Level** | Whether you were loud enough to clear the silence gate. |

`--expect` also tells a *wrong* transcription apart from a *transposed* one.

`analyze` reads the run at the same settings the app uses. To try others,
give it dial levels or override a single threshold:

```
uv run humm2melody analyze <run> --sensitivity 8 --pause 3
uv run humm2melody analyze <run> --min-duration 0.05 --smoothing 3
```

| Option | Overrides |
| --- | --- |
| `--sensitivity` `--pause` | The two dials, 1 to 9 |
| `--min-confidence` | How sure the detector must be to call a frame pitched |
| `--min-rms` | How loud a frame must be to count as sound rather than silence |
| `--min-duration` | The shortest run of frames that becomes a note |
| `--gap-tolerance` | How long a dropout a note survives without splitting |
| `--smoothing` | The median filter width, in frames |
| `--max-glide-rate` | Semitones per second above which pitch counts as sliding |

---

## Command line

```
uv run humm2melody                      # start the app
uv run humm2melody --guest              # skip the profile chooser
uv run humm2melody --profile Ahmed      # use a profile directly
uv run humm2melody --profiles DIR       # keep profiles elsewhere
uv run humm2melody --output DIR         # keep recordings elsewhere
uv run humm2melody --no-save            # do not record runs to disk
uv run humm2melody --demo               # replay a synthetic hum, no microphone
uv run humm2melody --list-devices       # list microphones
uv run humm2melody --device 2           # choose one
uv run humm2melody analyze <run>        # diagnose a saved run
```

---

## Limits

- **One voice at a time.** The app cannot transcribe chords you hum.
- **No rhythm.** You get note times in seconds, not a score with a time
  signature.
- **The Training tab is not built.**
