# humm2melody

Hum a melody into your microphone and get back the notes to play on a keyboard.

humm2melody is a terminal app. You press **Start**, hum, and press **Stop**.
While you hum, it shows the note it is hearing in real time. When you stop, it
lays the melody out four ways at once: a piano-roll timeline, a playable note
sequence, a piano keyboard, and a table giving each note's timing and tuning.

Press `p` and it plays the transcription back as tones, with a playhead crossing
the timeline. You find out whether it heard you correctly before you go anywhere
near a keyboard.

Every run is written to disk, including the ones where nothing was detected — a
failed transcription is exactly the one you want to inspect later.

![humm2melody: humming a melody, transcribing it, and playing it back](docs/demo.gif)

> ### 🤖 This is a vibe-coded project
>
> An LLM (Claude) wrote every line of this repository from conversational
> prompts: the pitch detector, the segmentation, the TUI, the tests, and this
> README. I described what I wanted, pushed back on what came out, and it wrote
> the code. I did not hand-write the signal processing.
>
> It works, and it has 460 tests that need no microphone. Treat it accordingly:
> no expert has reviewed it, a model made the signal-processing choices rather
> than someone who does this for a living, and the only real-world validation is
> that it transcribed some humming into a laptop microphone correctly. Read it
> yourself before you put it anywhere that matters.

## User manual

[**humm2melody user manual**](humm2melody/manual.md) covers every feature in
task order. The same text is in the app's **Manual** tab, so there is one
manual rather than one per place you read it.

## Requirements

- macOS or Linux, Python 3.11 or later
- [uv](https://docs.astral.sh/uv/)
- PortAudio, the C library behind microphone capture

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

On the first run, macOS asks for microphone access **for your terminal app**
(Terminal, iTerm, VS Code, and so on), not for Python itself. If you never see
the prompt, or the level meter stays flat, turn access on under *System Settings
> Privacy & Security > Microphone*.

### Choose an input device

```bash
uv run humm2melody --list-devices
uv run humm2melody --device 2
uv run humm2melody --device "MacBook Pro Microphone"
```

`--device` takes either the index printed by `--list-devices` or the device
name. Without it, the app uses your system input.

## What you see

The app opens by asking who is humming, then shows three tabs.

| Tab | What you do there |
| --- | --- |
| **Recording** | Hum, read the transcription, play it back, edit it, and manage saved runs. |
| **Calibrating** | Teach the app your voice once, and let it set the dials from what you sang. |
| **Training** | Placeholder. The plan is to help your voice get steadier. See `docs/ROADMAP.md`. |

The Recording tab stacks six control rows above the results: the **Pitch**,
**Pauses**, **Mix** and **Tempo** dials, then the **Voice** and **Notation**
rows. Below them sit the timeline, the `Play this:` sequence, the keyboard, and
the note table with its buttons. The **Recordings** sidebar on the right lists
every saved run.

A live footer runs along the bottom of every tab. It shows the note being heard,
how far off pitch it is, its frequency in hertz, elapsed time, an input level
meter, and a one-line hint about what to do next.

## Key reference

These keys work on any tab unless the table says otherwise.

| Key | Action |
| --- | --- |
| `space` | Start or stop. On the Recording tab it records; on the Calibrating tab it starts or finishes a calibration step. |
| `p` | Play back |
| `m` | Cycle what `p` plays: tones only, your hum, or both |
| `v` | Cycle the playback voice: pure, rich, chords |
| `n` | Cycle note names: English, German, Solfège, Sargam |
| `[` `]` | Pitch dial, down and up |
| `,` `.` | Pauses dial, down and up |
| `<` `>` | Tempo, slower and faster |
| `-` `=` | Mix: more hum, more tones |
| `e` | Edit the notes (Recording tab) |
| `c` | Clear the display. On the Calibrating tab, start the calibration over. |
| `u` | Switch profile |
| `q` | Quit |
| `ctrl+p` | Open the command palette, which is where Textual's built-in **Keys** panel lives |
| `escape` | Close the Keys panel |

`q` closes the Keys panel if it is open and quits otherwise, because the panel
has no other way out.

**In the Recordings sidebar:**

| Key | Action |
| --- | --- |
| `↑` `↓` | Pick a run |
| `enter` | Load it onto the timeline |
| `s` | Star or unstar it |
| `r` | Rename it |
| `d` | Delete it, after a confirmation |

**On the Calibrating tab:**

| Key | Action |
| --- | --- |
| `space` | Start the next step, or finish the one recording |
| `l` | Play the reference melody |
| `y` | Keep a calibration the app was not confident about |
| `c` | Start over |

**In the profile chooser:**

| Key | Action |
| --- | --- |
| `↑` `↓` | Pick a profile |
| `enter` | Use it |
| `n` | Create a new profile |
| `d` | Delete the highlighted profile, after a confirmation |
| `g` or `escape` | Continue as guest |

**In a confirmation dialog:** `y` confirms and `n` or `escape` cancels. Nothing
in the dialog takes focus when it opens, so a stray Enter cannot delete
anything. Confirming is always deliberate.

**In a name dialog** (rename a run, create a profile): `enter` saves and
`escape` cancels.

Editing keys are listed under [Fix a note by hand](#fix-a-note-by-hand).

### Click instead

Every surface that shows a note responds to the mouse, so you never have to
find `e` first.

| Click this | And it |
| --- | --- |
| A bar in the timeline | Selects that note and enters edit mode |
| A name in the `Play this:` line | Selects that note and enters edit mode |
| A row in the note table | Selects that note and enters edit mode |
| A piano key | Adds that note to the melody, sounds it, and selects it |
| A run in the sidebar | Loads it |
| **Start humming** / **Stop** | Same as `space` |
| **Play back** / **Stop playback** | Same as `p` |
| **Tones only** / **Your hum** / **Hum + tones** | Same as `m` |

The Calibrating tab has its own four buttons — **Start**, **Hear the melody**,
**Keep it** and **Start over** — which mirror `space`, `l`, `y` and `c`. None of
the buttons take keyboard focus, so pressing space always means "go" rather than
re-triggering whichever button you clicked last.

## Profiles

Pick an existing profile at startup, create one, or continue as **Guest**. A
guest session works fully but remembers nothing.

A profile stores the positions of all four dials, your chosen voice and
notation, the tab you were last on, and what calibration learned about your
voice. Each profile is a single JSON file under `profiles/`, so you can copy,
hand-edit, or delete one without touching anything else. Deleting a profile
keeps the runs it produced. `Guest` is a reserved name.

Press `u` to switch profile at any time.

```bash
uv run humm2melody --guest              # skip the chooser, save nothing
uv run humm2melody --profile Ahmed      # use a profile directly
uv run humm2melody --profiles ~/voices  # keep profiles somewhere else
```

`--profile` matches names without regard to case, and the app exits with an
error if no profile matches.

## Calibrate the app to your voice

Every threshold in this app started out hand-tuned against one person's voice,
which is precisely the thing that should be measured per user instead.
Calibration measures it.

Open the **Calibrating** tab and press `space`. There are three short takes:

1. Your lowest comfortable note. Hum it and hold it for about two seconds.
2. Your highest comfortable note. Same again.
3. The reference melody. Press `l` to hear it, then sing it back at whatever
   pitch suits you.

The app then searches all 81 combinations of the two detection dials for the
pair that best recovers the melody, and adopts that pair.

What it learns is saved to your profile:

| Measurement | What it is |
| --- | --- |
| Range | The lowest and highest notes you sang, in semitones. A **semitone** is one piano key, black or white. |
| Tuning offset | How far your singing sits from the standard A440 grid, in **cents**. A cent is one hundredth of a semitone, so 50 cents is exactly halfway between two keys. |
| Steadiness | How much your pitch drifts while you hold one note, in cents. |
| Style | The fraction of the time you were sliding between notes rather than holding one. |
| Accuracy | How far your reply sat from the reference melody, in cents. |
| Register | How far up or down you transposed the melody. |

The pane shows live feedback while you sing — a record indicator, the note it is
hearing, and an input meter — and afterwards draws what it learned: your range
against the singable span, a tuner needle for the tuning offset, and bars for
steadiness, style and accuracy.

**Everything is compared as intervals.** If you sing the tune an octave down
because that is where your voice sits, that is a correct performance. The app
reports it ("you sang it 1 octave down") rather than counting it against you.

Being off is fine. That is the thing being *measured*, and it comes back as an
accuracy figure rather than a failure.

A confident calibration is adopted the moment it finishes. The **Saved** button
is showing you state, not a control you missed. When the reply does not match
well, the app adopts nothing but leaves the result on screen with a choice:
press `y` to keep it, or `space` to try again. Range, tuning and steadiness are
measured from the singing itself and hold regardless of whether the melody
matched, so there is usually something worth keeping — imperfect settings still
beat none. Only accuracy and register need the melody to line up, and the app
withholds them when it cannot compute them.

Calibrating as a guest works, and applies for the session, but nothing is saved.

### What calibration changes

Two of the measurements change how the app listens. The rest are recorded and
deliberately unused.

| Measurement | Effect |
| --- | --- |
| **Range** | Narrows the pitch detector's search to your voice plus a fifth either side |
| **Tuning offset** | Stands in when a run is too short to estimate its own |
| Steadiness, style, accuracy, register | Recorded only |

Narrowing the search is the one thing a measured range can do that the dials
cannot. The dials tune *segmentation*, which runs after pitch detection, so they
can never undo an octave error. The detector can only report a harmonic or
subharmonic that falls inside its search window, and a window that stops short
of one cannot produce it at all. For a B2–F♯4 voice the window narrows from
65–1200 Hz to 82–554 Hz, about 42% of the original.

Steadiness and style are **not** wired in, on purpose: the dial search already
compensates for them, and applying both would correct for the same thing twice.

A range narrower than a fourth is ignored as a failed measurement rather than
trusted. Nobody's range is one note, and constraining detection around a bad
reading would make notes vanish.

## Tune the transcription with the dials

Voices are not keyboards. An untrained voice slides between notes, overshoots
and settles, and returns to "the same" pitch a little flat or sharp each time.
How big a pitch difference *should* count as a different note therefore depends
on who is humming.

Two dials answer that, and both **re-transcribe the recording you already
made**. You do not need a second take: the app keeps the frame-by-frame pitch
track and redoes only the segmentation. They work on saved runs too — load one
from the sidebar and turn a dial.

```
Pitch       [ ]  [····●····]  5/9   balanced
Pauses      < >  [····●····]  5/9   balanced
```

**Pitch** (`[` and `]`) sets how finely to distinguish pitches. Low settings
smooth harder, require longer notes, and cluster nearby pitches so that small
wobbles read as one note. High settings resolve smaller intervals, at the cost
of picking up wobble.

**Pauses** (`,` and `.`) sets how eagerly to split notes in *time*. This is a
separate dial because it answers a different question: two presses of the same
key are a single unbroken pitch, so no amount of pitch resolution separates
them. The only evidence of a second note is the **attack** — the moment the
sound gets suddenly louder again.

> The Pauses row currently prints `< >` as its key hint. That hint is wrong;
> the keys that move the Pauses dial are `,` and `.`, and `<` and `>` change
> the tempo.

One dial per concern, rather than a pile of sliders, because within each concern
the parameters are not independent. A voice that wanders needs *both* heavier
smoothing and a willingness to treat nearby pitches as the same note, and most
combinations of five separate sliders are nonsense.

### How repeated notes get separated

An **onset** is the start of a fresh note. Silence between notes is not required
and often never happens: a piano note is still ringing when the next one starts.
So the app tracks loudness in decibels against the median of the preceding few
frames, and a sharp enough rise starts a new note even when the pitch has not
changed.

Measuring against the median rather than the minimum matters. A single dropped
frame is a detector artefact, not a pause, and would otherwise register as a
re-attack.

At Pauses level 1 onset detection is off entirely and only real silence
separates notes. At level 7 and above, three strikes of one key separate
correctly with **no gap at all** between them.

### Why clustering, not only merging

The app clusters pitches across the *whole* recording, not merely between
neighbours. Suppose you hum low-high-low and your two lows land 45 cents apart,
either side of a rounding boundary. They come out as two *different* notes, and
merging adjacent notes cannot fix it, because the two lows are not adjacent —
the high one is between them.

## Compare the transcription against your voice

Press `m` to cycle what `p` plays.

| Source | What you hear |
| --- | --- |
| **Tones only** | The transcription, as you would play it |
| **Your hum** | The original recording |
| **Hum + tones** | Both together |

The overlay is the most direct check there is. If the tones sit inside the hum,
the app heard you right. If they beat against it or wander off, it did not.

Press `-` and `=` to set the balance.

```
Mix         - +  [····●····]  5/9   balanced
```

The mix is an equal-power crossfade, but it is deliberately not centred on equal
*gain*. A pure tone sounds much louder than a breathy hum at the same amplitude,
so the midpoint favours your voice. Both ends are pulled in slightly so that
neither source ever drops to nothing.

## Choose how the playback sounds

Press `v` to switch the voice.

| Voice | What plays |
| --- | --- |
| **Pure** | One tone per note |
| **Rich** | Its octave and fifth as well, which are consonant against any root |
| **Chords** | A triad, with the third taken from the melody itself |

The chord voice picks major or minor by looking at which third the melody
actually uses, rather than assuming major. A third borrowed from the tune
belongs with it, where a fixed major third would fight a minor melody.

## Play it slower

Press `<` and `>` to set the playback tempo, from half speed to double.

```
Tempo       < >  [····●····]  5/9   as recorded
```

Pitch is regenerated from each note rather than resampled, so slowing a melody
down to learn it does not transpose it.

Tempo applies to the tones only. Speeding up your own recording would need
time-stretching, and resampling it would shift the very pitches you are
checking.

## The keyboard

Under the timeline is a piano keyboard spanning the same width. It lights up as
the melody plays and shows the note you are editing. A piano roll tells you the
shape of a tune; the keyboard tells you where your hands go, which is the point
of the app. Key names are printed inside the keys, in whichever notation you
have chosen.

The keyboard widens in whole octaves to fill the terminal rather than fattening
a handful of keys, so a wide window shows more range instead of bigger keys.

### Compose on it

Click a key and the app adds that note to the melody, plays it so you can hear
it, and selects it so the usual editing keys apply. You can build a tune
entirely by clicking, with `z` to undo a wrong key.

Black keys are only hit in the upper rows where they are drawn. Below that the
white key underneath takes the click, as on a real keyboard.

## Note names

Press `n` to cycle how notes are spelled. Pitch is always stored as a MIDI
number, so switching schemes can never change what was detected or what gets
played — only how it is written down. The choice is remembered per profile.

| Scheme | Spelling |
| --- | --- |
| **English** | C D E F G A B |
| **German** | C D E F G A **H**, and **B** means B♭ |
| **Solfège** | Do Re Mi Fa Sol La Si (fixed do) |
| **Sargam** | Sa Re Ga Ma Pa Dha Ni, with lower case for komal |

German is the one worth knowing about: **H is what English calls B, and B is
what English calls B♭.** Read a German name with English habits and you are a
semitone out, silently.

In Sargam, a *komal* note is the flattened form of a degree — komal Re is one
semitone below Re. The app writes komal notes in lower case (`re`, `ga`, `dha`,
`ni`) and shows `ma` for tivra Ma, the sharpened fourth.

## Fix a note by hand

Detection gets things wrong. **Click any note** — in the timeline, in the
`Play this:` line, or in the table — to select it and start editing. Or press
`e`.

| Key | Effect |
| --- | --- |
| `←` `→` | Pick a note |
| `↑` `↓` | A semitone higher or lower |
| `shift+↑` `shift+↓` | An octave higher or lower |
| `,` `.` | Move it earlier or later, in 0.05 s steps |
| `-` `=` | Make it shorter or longer, in 0.05 s steps |
| `i` | Insert a note that detection missed |
| `del` or `⌫` | Remove one that should not be there |
| `z` / `shift+z` | Undo / redo |
| `esc` | Finish editing |

Those are the same keys as the Pauses and Mix dials, which works because the
timeline takes focus while you edit. A focused widget is offered keys before any
app-level binding, so the two sets cannot collide.

The selected note is highlighted in the timeline, the sequence and the table at
once, whichever of the three you picked it in.

Editing works even when **nothing** was detected. That is the transcription most
worth building by hand, so `e` then `i` starts one from scratch, taking a
sensible pitch from the recording rather than guessing.

The app keeps notes in time order as you move them, so nudging one past its
neighbour cannot leave the table reading out of sequence. The selection follows
the note itself rather than its position.

Every edit is undoable, 50 deep. Edits write through to the run, so without undo
a mistyped key would be permanent.

Writing back is deferred until you pause, and forced when you finish. Saving
re-encodes the run's playback and rebuilds a sidebar row per saved run, which is
far too much work to do on every keystroke once you have a few dozen recordings.

**The recording is never touched.** `hum.flac` and `pitch_track.csv` stay
exactly as captured — an edit corrects the *reading*, not the performance — so
re-analysing later still starts from the original audio.

## Saved runs

Every recording goes into `recordings/` automatically, including the ones where
nothing was detected.

![Renaming, loading and deleting saved runs from the sidebar](docs/sessions.gif)

```
recordings/2026-08-19_14-32-05/
    hum.flac         the raw microphone input, lossless
    playback.mp3     the tones the app plays back
    notes.json       detected notes, timings, tuning, plus run metadata
    pitch_track.csv  every analysis frame: time, freq, confidence, rms
```

The two audio formats are chosen for different reasons. The hum is the
**analysis master** — `analyze` and both detection dials re-read it — so it
stays lossless, and FLAC is about 45% the size of WAV with identical results.
The playback is regenerable from `notes.json` at any time, so lossy compression
costs nothing and MP3 is about 5% of the WAV. On a 2.5-second run that is 354 KB
down to 60 KB.

Runs recorded before the switch keep their `.wav` files and are read without
migration. Rewriting somebody's recordings to save disk is not a trade the app
gets to make on their behalf.

`pitch_track.csv` is the file to reach for when a note comes out wrong. It is
the detector's frame-by-frame opinion *before* smoothing and segmentation
discarded anything, at roughly 43 rows per second. Plot `freq` against `time`
and an octave slip or a dropped note is usually obvious.

`playback.mp3` is rendered when the run is saved rather than captured from the
speaker, so it is there even if you never pressed play. Rendering is
deterministic, so it is byte-for-byte the audio you would have heard.

Press `s` to star a run. Starred runs show a ★ in the sidebar, and deleting one
says so in the confirmation. The mark lives in that run's own `notes.json`
rather than in a central index, so a run directory stays self-describing: copy
it somewhere else and it is still starred; delete it and nothing dangles.

Runs are named by timestamp. Renaming one keeps the timestamp prefix and appends
a slug (`2026-08-19_14-32-05__Chorus-idea`), so runs stay chronological and
names stay unique. Clear the label to revert to the bare timestamp.

Deleting from the sidebar removes the whole run directory, after a confirmation.
The store refuses to touch anything outside its output directory, or any
directory without a `notes.json`, so a stray path cannot turn into a recursive
delete of something you care about.

```bash
uv run humm2melody --output ~/humming   # save somewhere else
uv run humm2melody --no-save            # do not record to disk at all
```

The sidebar shows the output directory, or `saving disabled` when you pass
`--no-save`.

## Hum for the best results

The detector wants a clear, sustained pitch, so:

- Hum on an open-ish sound (`mmm` or `ahh`) rather than whistling quietly.
- Hold each note for at least about 0.2 s. At the default Pitch setting,
  anything under 90 ms is discarded as noise; the dial moves that threshold
  between 35 ms and 200 ms.
- Sliding between notes is fine. The glide gate discards the slide and keeps the
  held pitch. But do *hold* each note: a phrase that never settles anywhere has
  no notes in it to find.
- Repeated notes work without a gap at Pauses level 5 and above, because a fresh
  attack is enough to separate them. Below that, leave a small gap, or two `E4`s
  in a row merge into one long `E4`.
- Hum in a comfortable range. Detection covers 65–1200 Hz, which is C2 to D6.

The **Tuning** column tells you how far off you were, in cents. The app calls
anything inside 12 cents "on pitch". A consistent offset is normal and harmless,
but if it sits near ±50 cents you are on a semitone boundary, where small
wobbles flip notes between two neighbours and corrupt the intervals rather than
only the key. `analyze` reports this as the tuning offset.

The timeline draws at most 32 semitone rows, so one stray octave cannot blow up
the view. When a run spans more than that, the top is cut off and the note table
is authoritative.

## Diagnose a bad transcription

When a run comes out wrong, `analyze` re-runs detection over its saved hum and
reports what the detector actually saw, before smoothing and segmentation
discarded the evidence.

```bash
uv run humm2melody analyze recordings/2026-08-19_14-32-05
uv run humm2melody analyze recordings/2026-08-19_14-32-05/hum.flac
uv run humm2melody analyze <run> --expect "C4 D4 E4"
```

The argument is a run directory or a bare audio file. Given a directory,
`analyze` reads `hum.flac`, falling back to `hum.wav` for older runs.

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
| **tuning offset** | How far the whole performance sits off the A440 grid. Near ±50 cents, every note is a coin-flip between two semitones and vibrato decides. That corrupts intervals, not only the key. |
| **gliding frames** | The fraction of the time you were sliding rather than holding. High means the segmenter is snapping every semitone the slide passes through into its own note. |
| **octave jumps** | The detector flipping between f0 and 2·f0. |
| **within-note wobble** | Vibrato depth, as a standard deviation in cents. Large values push notes over semitone boundaries. |
| **rms percentiles** | Whether you were loud enough to clear the silence gate. |

`analyze` also prints a warning line under any reading that looks like the
cause: very quiet input, a tuning offset past 35 cents, more than 35% gliding
frames, or more than two octave jumps.

### Score the result against what you meant

`--expect` compares the transcription with the notes you actually hummed, and
distinguishes a *wrong* transcription from a *transposed* one. Humming in a
comfortable key is a correct transcription of what you sang, not an error:

```
  verdict:  intervals match, transposed by -5 semitones
```

`--sweep` searches detection parameters for the setting that best matches what
you meant, which is how you find out whether a failure is a tuning problem or a
fundamental one. It needs `--expect`, and prints the ten best settings by edit
distance:

```bash
uv run humm2melody analyze <run> --sweep --expect "C4 D4 E4"
```

### Analyze at other settings

By default `analyze` runs at Pitch 5 and Pauses 5, so a diagnosis reproduces
what the app does. Move either dial to reproduce a different reading:

| Flag | Default | Effect |
| --- | --- | --- |
| `--sensitivity` | `5` | The Pitch dial level to analyse at, 1 to 9 |
| `--pause` | `5` | The Pauses dial level to analyse at, 1 to 9 |

Six more flags override one dial-derived value each, for pinning down which
threshold is responsible: `--min-confidence`, `--min-rms`, `--min-duration`,
`--smoothing`, `--gap-tolerance`, and `--max-glide-rate`. See
[Tune the detector](#tune-the-detector) for what each one does.

## Demo mode and the screen captures

`--demo` replays a synthetic hum through the real analysis pipeline instead of
opening the microphone. It is how the GIFs above are made, and it is useful for
trying the app on a machine with no working input device:

```bash
uv run humm2melody --demo
```

The demo melody is the opening of "Twinkle, twinkle, little star", chosen
because its repeated notes show that the detector separates them instead of
merging them into one.

The captures are scripted with [VHS](https://github.com/charmbracelet/vhs), so
they can be regenerated rather than re-recorded by hand:

```bash
./scripts/refresh-gifs.sh
```

Because demo mode is deterministic and the tests assert that the demo melody
still transcribes exactly, a regenerated capture cannot silently start showing a
broken app. See `docs/MAINTENANCE.md` for the full procedure.

## How it works

| Module | Job |
| --- | --- |
| `audio.py` | Capture the microphone and run the analysis loop |
| `pitch.py` | Estimate the fundamental of one frame (YIN) |
| `segment.py` | Turn the frame-by-frame pitch track into note events |
| `playback.py` | Render the detected notes back to audible tones |
| `naming.py` | Spell a MIDI number in each notation scheme |
| `sessions.py` | Save, list, rename and delete runs on disk |
| `profiles.py` | Load and store per-user settings |
| `calibration.py` | Measure a voice and derive dial settings from it |
| `analysis.py` | Offline diagnostics for the `analyze` command |
| `demo.py` | A microphone stand-in that replays a synthetic hum |
| `tui.py` | The Textual interface |

**1. Capture.** PortAudio delivers 512-sample blocks at 22.05 kHz. The audio
callback does nothing but copy each block onto a queue, because anything slower
there causes dropouts. A worker thread owns a 2048-sample sliding window (about
93 ms) that advances one block (about 23 ms) at a time, giving roughly 43 pitch
estimates per second.

**2. Pitch.** Each window goes through [YIN][yin], a standard algorithm for
finding the fundamental frequency of a monophonic sound. Humming is monophonic
and lives roughly between 65 and 1200 Hz, so YIN suits it: it is cheap enough to
run in real time and far more robust against octave errors than plain
autocorrelation.

YIN builds the squared-difference function `d(τ)` by FFT, normalises it into the
cumulative mean normalised difference so that it starts at 1 and dips at the
period, then takes the *first* dip below an absolute threshold rather than the
deepest one. That "first, not best" rule is what stops the detector from locking
onto a harmonic and reporting the note an octave high. A parabolic fit around
the dip gets the period to sub-sample accuracy, and `1 − cmnd(τ)` falls out as a
confidence value.

**3. Segmentation.** The raw track is too jittery to read directly: vibrato — the
small, fast pitch oscillation a singer adds to a held note — plus glides and the
occasional detector slip all appear as pitch changes. So the app gates the track
by confidence and level, converts it to fractional MIDI numbers, runs it through
a NaN-aware 5-frame median filter that removes single-frame octave errors, and
rounds it to the nearest semitone.

Then comes the glide gate. Singing is **legato**: the voice slides continuously
between notes instead of jumping. Snapping every frame of a slide invents a note
for each semitone it crosses, so humming C-D-E in one breath transcribes as the
chromatic run `C4 C♯4 D4 D♯4 E4`. The app therefore discards frames where pitch
is sliding faster than `max_glide_rate`, keeping only held pitch.

Getting that to work needed one non-obvious step. Vibrato has a *higher*
instantaneous slope than a glide — ±40 cents at 5 Hz swings past 6 semitones per
second — so measuring the slope directly splits steady notes in two. Measuring
over a longer window fixes vibrato but then eats discrete note changes as well.
The answer is to median-filter over a vibrato cycle first: a median removes
oscillation but *preserves edges*, so vibrato flattens while a real note change
stays a sharp step, and a short slope measured on top cleanly separates a
sustained slide from an instant jump.

Runs of equal pitch then become note events. A dropout shorter than 70 ms does
not split a note, and events shorter than 90 ms are dropped.

**4. Display.** The app draws the timeline from the note list at whatever width
the terminal has, one row per semitone, with white keys bright and black keys
dimmed.

**5. Playback.** Audio is *pushed* to the device with blocking writes from a
worker thread, not *pulled* by a Python callback. The difference is audible. A
callback has to acquire the GIL to run, so whenever the UI thread is busy
rendering the terminal, the callback misses its deadline and the device is
handed nothing, producing exactly one click per buffer period.

That was diagnosed from a phone recording of the speakers: the artefact bursts
were spaced 64 ms apart, matching the 65 ms output buffer almost exactly, and
the rendered file itself had *zero* energy above 4 kHz. With blocking writes,
PortAudio's own ring buffer feeds the device from C code that never needs the
GIL, and `write()` releases the GIL while it waits, so a stalled UI costs latency
rather than clicks.

Each note is rendered as a fundamental plus two quiet harmonics under an
attack/decay/release envelope. A bare sine reads as a beep and blurs together on
repeated notes, whereas an audible attack makes each one distinct.

Notes play at their **snapped** pitch, not the raw hummed frequency. The point
is to audition what you would actually play, so if the transcription is wrong
you hear it immediately.

Two details are worth knowing, because both were bugs before they were
decisions:

- **Smoothing corrects pitch, never voicing.** The app re-masks the median
  filter's output with the original silences afterwards. Without that, smoothing
  spreads a note into the surrounding silence, inflating every duration by
  roughly the filter width and welding repeated notes together across their gap.
- **Voicing is judged on a short slice, pitch on a long one.** The 93 ms window
  is needed to measure a low fundamental, but using it to detect silence smears
  note boundaries by its own length: a gap shorter than the window never looks
  fully silent. Energy is therefore measured over the roughly 23 ms at the
  window's centre, aligned with the frame's timestamp.

[yin]: http://audition.ens.fr/adc/pdf/2002_JASA_YIN.pdf

### Tune the detector

The thresholds live in the signatures of `detect_pitch` and `segment_notes`. The
dials set them for you; these are the values underneath, and the ones the
`analyze` override flags reach.

| Parameter | Default | Raise it to… |
| --- | --- | --- |
| `threshold` | `0.15` | Be stricter about what counts as pitched |
| `min_confidence` | `0.55` | Drop more breathy or uncertain frames |
| `min_rms` | `0.006` | Ignore more background noise |
| `min_duration` | `0.09` s | Discard more short blips |
| `gap_tolerance` | `0.07` s | Bridge longer dropouts within one note |
| `smoothing` | `5` frames | Smooth harder, at the cost of fast passages |
| `max_glide_rate` | `5.0` st/s | Be stricter about what counts as *held* rather than sliding (`None` disables the gate) |

## Tests

```bash
uv run pytest
```

460 tests, and none of them touch a microphone or a speaker. The detector is
driven with synthesised tones, and the TUI runs headless under Textual's `Pilot`
with the audio classes faked out. Every test app gets a `tmp_path` output
directory, so running the suite never writes into `recordings/`.

The strongest test is a round trip: render notes to audio with the playback
code, feed that back through the detector, and check that the same notes come
out.

## Limits

- **Monophonic only.** One voice at a time. It cannot transcribe chords.
- **No rhythm.** You get note start times and durations in seconds, not a
  quantised score with a time signature. Reading durations off the timeline is
  the current answer.
- **No key detection**, no transposition, and no MIDI or MusicXML export yet.
- Playback is a plain synth tone, not a piano sample.
- The Training tab is a placeholder.

`docs/ROADMAP.md` lists the outstanding work, with what already exists for each.
Several of the items are smaller than they look.
