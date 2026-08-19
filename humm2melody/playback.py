"""Play the detected melody back as simple tones.

This is the app's correctness check: hearing the snapped notes played back at
the timing they were detected tells you immediately whether the transcription
matches what you hummed, without having to find a keyboard first.

Playback uses each note's *snapped* pitch, not the raw hummed frequency — the
point is to audition what you would actually play.
"""

from __future__ import annotations

import math
import threading

import numpy as np

from .pitch import midi_to_hz
from .segment import Note

SAMPLE_RATE = 44100
"""Output rate. Higher than capture: harmonics up here are worth resolving."""

TAIL = 0.35  # seconds of silence after the last note, so the release can ring


def render(
    notes: list[Note],
    sample_rate: int = SAMPLE_RATE,
    *,
    amplitude: float = 0.32,
    speed: float = 1.0,
    voice: str = "pure",
) -> np.ndarray:
    """Render notes into a mono waveform, preserving their original timing.

    ``speed`` scales time only. Pitch is regenerated from each note rather
    than resampled, so playing at half speed lowers nothing -- which is the
    point of being able to slow a melody down to learn it.
    """
    if not notes:
        return np.zeros(0, dtype=np.float32)

    if speed != 1.0:
        notes = [
            Note(
                midi=n.midi, start=n.start / speed, end=n.end / speed,
                freq=n.freq, confidence=n.confidence, pitch=n.pitch,
                attack=n.attack,
            )
            for n in notes
        ]

    total = max(n.end for n in notes) + TAIL
    buffer = np.zeros(int(total * sample_rate) + 1, dtype=np.float32)

    stacks = chord_offsets(notes, voice)
    for note in notes:
        wave = _voice(note.ideal_freq, note.duration, sample_rate) * amplitude
        for offset in stacks.get(note.midi, ()):
            # Quieter than the melody, so the tune stays the thing you hear.
            wave = wave + _voice(
                midi_to_hz(note.midi + offset), note.duration, sample_rate
            ) * (amplitude * 0.45)
        start = int(note.start * sample_rate)
        end = min(start + wave.size, buffer.size)
        buffer[start:end] += wave[: end - start]

    peak = float(np.max(np.abs(buffer))) if buffer.size else 0.0
    if peak > 1.0:
        buffer /= peak
    return buffer


def _voice(freq: float, duration: float, sample_rate: int) -> np.ndarray:
    """One note: a few harmonics under an envelope.

    A bare sine reads as a beep and blurs together on repeated notes; the decay
    and the quiet upper harmonics make each attack audible.
    """
    length = max(1, int(duration * sample_rate))
    t = np.arange(length) / sample_rate

    wave = (
        np.sin(2 * np.pi * freq * t)
        + 0.34 * np.sin(2 * np.pi * 2 * freq * t)
        + 0.12 * np.sin(2 * np.pi * 3 * freq * t)
    )
    return (wave * _envelope(length, sample_rate)).astype(np.float32)


DRONE_SECONDS = 2.0
"""Roughly how long one turn of a looping reference tone lasts."""


def drone(
    midi: int, sample_rate: int = SAMPLE_RATE, *, amplitude: float = 0.16
) -> np.ndarray:
    """A reference tone built to be looped without a click at the seam.

    The length is rounded to a whole number of cycles, so the last sample runs
    into the first with the phase intact. Anything else gives a discontinuity
    once per turn, and a click every two seconds is worse than no reference at
    all.

    Quieter and plainer than `_voice`: this plays *while* you sing, so it has
    to sit under your own voice rather than compete with it, and it has no
    envelope because a drone has no attack to hear.
    """
    freq = midi_to_hz(midi)
    cycles = max(1, round(DRONE_SECONDS * freq))
    length = max(1, int(round(cycles * sample_rate / freq)))
    t = np.arange(length) / sample_rate

    # Sine plus a quiet octave: enough body to hear against a voice, without
    # the harmonics that would make it hard to sing over.
    wave = np.sin(2 * np.pi * freq * t) + 0.18 * np.sin(2 * np.pi * 2 * freq * t)
    return (wave * amplitude).astype(np.float32)


def _envelope(length: int, sample_rate: int) -> np.ndarray:
    """Attack / decay / sustain / release, clamped to fit short notes."""
    env = np.ones(length, dtype=np.float64)

    attack = min(int(0.012 * sample_rate), length // 4)
    release = min(int(0.05 * sample_rate), length // 3)
    decay = min(int(0.09 * sample_rate), max(0, length - attack - release))

    if attack:
        env[:attack] = np.linspace(0.0, 1.0, attack)
    if decay:
        env[attack : attack + decay] = np.linspace(1.0, 0.75, decay)
        env[attack + decay :] = 0.75
    if release:
        env[-release:] *= np.linspace(1.0, 0.0, release)
    return env


def resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Linear resample. Good enough for auditioning a hum against its notes."""
    if src_rate == dst_rate or audio.size == 0:
        return np.asarray(audio, dtype=np.float32)
    count = int(round(audio.size * dst_rate / src_rate))
    source = np.linspace(0.0, 1.0, audio.size, endpoint=False)
    target = np.linspace(0.0, 1.0, count, endpoint=False)
    return np.interp(target, source, audio).astype(np.float32)


VOICES = ("pure", "rich", "chord")
VOICE_LABELS = {
    "pure": "Pure",
    "rich": "Rich",
    "chord": "Chords",
}
VOICE_NOTES = {
    "pure": "one tone per note",
    "rich": "with its octave and fifth — always consonant",
    "chord": "a triad from the melody's own notes",
}


def next_voice(voice: str) -> str:
    return VOICES[(VOICES.index(voice) + 1) % len(VOICES)] if voice in VOICES else VOICES[0]


def chord_offsets(notes: list[Note], voice: str) -> dict[int, tuple[int, ...]]:
    """What to stack on each note, in semitones above it.

    "Rich" adds the fifth and the octave, which are consonant against any
    root and so cannot be wrong. "Chords" adds a third as well, and picks
    major or minor by looking at which one the melody actually uses -- a
    third borrowed from the tune itself belongs with it, where a fixed major
    third would fight a minor melody.
    """
    if voice == "pure" or not notes:
        return {}
    if voice == "rich":
        return {n.midi: (7, 12) for n in notes}

    present = {n.midi % 12 for n in notes}
    stacks: dict[int, tuple[int, ...]] = {}
    for note in notes:
        root = note.midi % 12
        major = (root + 4) % 12 in present
        minor = (root + 3) % 12 in present
        if minor and not major:
            third = 3
        elif major and not minor:
            third = 4
        else:
            # Neither or both are in the tune; major is the safer default.
            third = 4
        stacks[note.midi] = (third, 7)
    return stacks


TEMPO_MIN = 1
TEMPO_MAX = 9
TEMPO_DEFAULT = 5

TEMPO_SPEEDS = (0.50, 0.62, 0.75, 0.87, 1.00, 1.20, 1.45, 1.70, 2.00)
"""Playback speeds for tempo levels 1..9. Level 5 is the recorded tempo."""


def tempo_speed(level: int) -> float:
    level = max(TEMPO_MIN, min(TEMPO_MAX, int(level)))
    return TEMPO_SPEEDS[level - TEMPO_MIN]


MIX_MIN = 1
MIX_MAX = 9
MIX_DEFAULT = 5


def mix_gains(level: int) -> tuple[float, float]:
    """(hum_gain, tone_gain) for a balance level from 1 to 9.

    An equal-power crossfade, but deliberately not centred on equal *gain*: a
    pure tone is perceptually far louder than a breathy hum at the same
    amplitude, so the midpoint favours the voice. The ends are pulled in
    slightly so both sources stay audible across the whole range.
    """
    level = max(MIX_MIN, min(MIX_MAX, int(level)))
    position = 0.1 + 0.8 * (level - MIX_MIN) / (MIX_MAX - MIX_MIN)
    angle = position * math.pi / 2
    return 0.95 * math.cos(angle), 0.55 * math.sin(angle)


def mix_hum_with_tones(
    hum: np.ndarray,
    hum_rate: int,
    notes: list[Note],
    rate: int,
    *,
    balance: int | None = None,
    hum_gain: float = 0.85,
    tone_gain: float = 0.45,
    voice: str = "pure",
) -> np.ndarray:
    """Your recording and the transcription playing together.

    The single most direct check of a transcription: if the tones sit inside
    the hum, it heard you right; if they beat against it or wander off, it did
    not. The tones sit under the hum so the hum stays recognisable.
    """
    if balance is not None:
        hum_gain, tone_gain = mix_gains(balance)

    # Not named `voice`: that is the timbre setting, and the two would collide.
    singing = resample(hum, hum_rate, rate) * hum_gain
    # render() already applies its own amplitude, so scale relative to that.
    tones = render(notes, rate, voice=voice) * (tone_gain / 0.32 if notes else 1.0)

    length = max(singing.size, tones.size)
    out = np.zeros(length, dtype=np.float32)
    out[: singing.size] += singing
    out[: tones.size] += tones

    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > 1.0:
        out /= peak
    return out


def device_sample_rate(fallback: int = SAMPLE_RATE) -> int:
    """The default output device's native rate.

    Rendering at the device's own rate avoids handing the OS a stream it has to
    resample on the fly, which is a common source of audible artefacts — a Mac
    running its speakers at 48 kHz has to resample every 44.1 kHz buffer.
    """
    try:
        import sounddevice as sd

        info = sd.query_devices(sd.default.device[1])
        rate = int(round(float(info["default_samplerate"])))
    except Exception:
        return fallback
    return rate if 8000 <= rate <= 192000 else fallback


BLOCK = 1024
"""Frames handed to PortAudio per write. ~21 ms at 48 kHz."""

LEAD_IN = 0.05
"""Silence before the audio, so the ring buffer is never caught empty."""


class Player:
    """Non-blocking playback with a position readout for the playhead.

    Audio is pushed with blocking writes from a worker thread rather than
    pulled by a Python callback. That difference is audible: a callback has to
    acquire the GIL to run, so whenever the UI thread is busy rendering, the
    callback misses its deadline and the device is handed nothing -- one click
    per buffer period. With blocking writes the device is fed from PortAudio's
    own ring buffer by C code that never needs the GIL, and `write()` releases
    the GIL while it waits, so a stalled UI costs latency instead of clicks.
    """

    def __init__(self, sample_rate: int | None = None) -> None:
        # None means "match the output device", resolved when play() is called.
        self._requested_rate = sample_rate
        self.sample_rate = sample_rate or SAMPLE_RATE
        self._stream = None
        self._buffer = np.zeros(0, dtype=np.float32)
        self._cursor = 0
        self._latency_frames = 0
        self._worker: threading.Thread | None = None
        self._halt = threading.Event()
        # Bumped per playback. A worker from a previous take must not write
        # the cursor of the current one after it has been superseded.
        self._generation = 0
        self.looping = False
        self._lock = threading.Lock()
        self._closed: set = set()

    @property
    def playing(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    @property
    def position(self) -> float:
        """Seconds of audio actually audible, for drawing the playhead.

        The writer runs ahead of the speaker by whatever PortAudio has
        buffered, so that much is subtracted or the playhead leads the sound.
        """
        played = self._cursor - self._latency_frames
        return max(0.0, played / self.sample_rate)

    def play(
        self, notes: list[Note], speed: float = 1.0, voice: str = "pure"
    ) -> None:
        """Start playing the transcription. Restarts cleanly if already playing."""
        rate = self._requested_rate or device_sample_rate()
        self.speed = speed
        self.voice = voice
        self.play_audio(render(notes, rate, speed=speed, voice=voice), rate)

    def play_audio(
        self, buffer: np.ndarray, rate: int | None = None, loop: bool = False
    ) -> None:
        """Start playing an arbitrary mono buffer.

        With `loop`, it plays until something stops it, wrapping straight back
        to the first sample -- so the buffer had better end where it began.
        """
        import sounddevice as sd

        self.stop()
        self.sample_rate = rate or self._requested_rate or device_sample_rate()
        buffer = np.asarray(buffer, dtype=np.float32)
        if buffer.size == 0:
            return

        # No lead-in silence on a loop: it would be a gap once per turn.
        lead = np.zeros(
            0 if loop else int(LEAD_IN * self.sample_rate), dtype=np.float32
        )
        self.looping = loop
        self._buffer = np.concatenate([lead, buffer])
        self._cursor = 0
        self._halt.clear()

        try:
            stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=BLOCK,
                latency="high",
                callback=None,  # blocking write mode
            )
            stream.start()
        except Exception:
            self._stream = None
            raise

        self._stream = stream
        self._latency_frames = int(float(stream.latency) * self.sample_rate)
        self._generation += 1
        self._worker = threading.Thread(
            target=self._pump, args=(stream, self._generation), daemon=True
        )
        self._worker.start()

    def _pump(self, stream, generation: int) -> None:
        """Feed the device until the buffer runs out or playback is stopped."""
        try:
            while not self._halt.is_set():
                if generation != self._generation:
                    return  # superseded; the newer take owns the state now
                start = self._cursor
                if start >= self._buffer.size:
                    if not self.looping:
                        break
                    start = 0  # phase-continuous by construction
                chunk = self._buffer[start : start + BLOCK]
                if chunk.size < BLOCK:
                    chunk = np.concatenate(
                        [chunk, np.zeros(BLOCK - chunk.size, dtype=np.float32)]
                    )
                # Releases the GIL while it waits for room in the ring buffer.
                stream.write(chunk)
                if generation == self._generation:
                    self._cursor = start + BLOCK
        except Exception:
            pass
        finally:
            # Reaching the end on its own: close here, since stop() never ran.
            if generation == self._generation and not self._halt.is_set():
                self._shut(stream, drain=True)
                if self._stream is stream:
                    self._stream = None

    def _shut(self, stream, drain: bool) -> None:
        """Close a stream exactly once, from whichever thread finished with it."""
        with self._lock:
            if stream is None or stream in self._closed:
                return
            self._closed.add(stream)
        try:
            if drain:
                stream.stop()  # let what is already buffered finish
            else:
                stream.abort()  # and unblock a worker waiting inside write()
            stream.close()
        except Exception:
            pass

    def stop(self) -> None:
        """Stop playback and release the device.

        The stream is closed only after its worker has exited. Closing it from
        here while the worker was still inside `write()` was a genuine crash:
        rapid start/stop -- clicking several piano keys quickly, each of which
        previews a note -- could take the whole process down, and a Textual app
        that dies without unwinding leaves the terminal in mouse-reporting mode.
        """
        self._halt.set()
        self._generation += 1  # orphan any worker still running
        stream = self._stream
        worker = self._worker
        self._stream = None
        self._worker = None

        if stream is not None:
            try:
                stream.abort()  # unblocks a pending write so the worker returns
            except Exception:
                pass
        if worker is not None and worker.is_alive():
            worker.join(timeout=2.0)
            if worker.is_alive():
                # Never close underneath a live worker; leaking one stream is
                # survivable, a use-after-free is not.
                self._cursor = 0
                return
        self._shut(stream, drain=False)
        self._cursor = 0
