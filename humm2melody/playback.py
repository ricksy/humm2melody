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

from .segment import Note

SAMPLE_RATE = 44100
"""Output rate. Higher than capture: harmonics up here are worth resolving."""

TAIL = 0.35  # seconds of silence after the last note, so the release can ring


def render(
    notes: list[Note],
    sample_rate: int = SAMPLE_RATE,
    *,
    amplitude: float = 0.32,
) -> np.ndarray:
    """Render notes into a mono waveform, preserving their original timing."""
    if not notes:
        return np.zeros(0, dtype=np.float32)

    total = max(n.end for n in notes) + TAIL
    buffer = np.zeros(int(total * sample_rate) + 1, dtype=np.float32)

    for note in notes:
        wave = _voice(note.ideal_freq, note.duration, sample_rate) * amplitude
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
) -> np.ndarray:
    """Your recording and the transcription playing together.

    The single most direct check of a transcription: if the tones sit inside
    the hum, it heard you right; if they beat against it or wander off, it did
    not. The tones sit under the hum so the hum stays recognisable.
    """
    if balance is not None:
        hum_gain, tone_gain = mix_gains(balance)

    voice = resample(hum, hum_rate, rate) * hum_gain
    # render() already applies its own amplitude, so scale relative to that.
    tones = render(notes, rate) * (tone_gain / 0.32 if notes else 1.0)

    length = max(voice.size, tones.size)
    out = np.zeros(length, dtype=np.float32)
    out[: voice.size] += voice
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

    def play(self, notes: list[Note]) -> None:
        """Start playing the transcription. Restarts cleanly if already playing."""
        rate = self._requested_rate or device_sample_rate()
        self.play_audio(render(notes, rate), rate)

    def play_audio(self, buffer: np.ndarray, rate: int | None = None) -> None:
        """Start playing an arbitrary mono buffer."""
        import sounddevice as sd

        self.stop()
        self.sample_rate = rate or self._requested_rate or device_sample_rate()
        buffer = np.asarray(buffer, dtype=np.float32)
        if buffer.size == 0:
            return

        lead = np.zeros(int(LEAD_IN * self.sample_rate), dtype=np.float32)
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
        self._worker = threading.Thread(target=self._pump, daemon=True)
        self._worker.start()

    def _pump(self) -> None:
        """Feed the device until the buffer runs out or playback is stopped."""
        stream = self._stream
        try:
            while not self._halt.is_set() and stream is not None:
                start = self._cursor
                if start >= self._buffer.size:
                    break
                chunk = self._buffer[start : start + BLOCK]
                if chunk.size < BLOCK:
                    chunk = np.concatenate(
                        [chunk, np.zeros(BLOCK - chunk.size, dtype=np.float32)]
                    )
                # Releases the GIL while it waits for room in the ring buffer.
                stream.write(chunk)
                self._cursor = start + BLOCK
        except Exception:
            pass
        finally:
            self._close(stream)

    def _close(self, stream) -> None:
        if stream is None:
            return
        try:
            if not self._halt.is_set():
                stream.stop()  # let what is already buffered finish
            stream.close()
        except Exception:
            pass
        if self._stream is stream:
            self._stream = None

    def stop(self) -> None:
        self._halt.set()
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.abort()
                stream.close()
            except Exception:
                pass
        worker = self._worker
        self._worker = None
        if worker is not None and worker.is_alive():
            worker.join(timeout=1.0)
        self._cursor = 0
