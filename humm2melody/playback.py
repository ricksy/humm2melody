"""Play the detected melody back as simple tones.

This is the app's correctness check: hearing the snapped notes played back at
the timing they were detected tells you immediately whether the transcription
matches what you hummed, without having to find a keyboard first.

Playback uses each note's *snapped* pitch, not the raw hummed frequency — the
point is to audition what you would actually play.
"""

from __future__ import annotations

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


class Player:
    """Non-blocking playback with a position readout for the playhead."""

    def __init__(self, sample_rate: int | None = None) -> None:
        # None means "match the output device", resolved when play() is called.
        self._requested_rate = sample_rate
        self.sample_rate = sample_rate or SAMPLE_RATE
        self._stream = None
        self._buffer = np.zeros(0, dtype=np.float32)
        self._cursor = 0
        self._lock = threading.Lock()

    @property
    def playing(self) -> bool:
        return self._stream is not None

    @property
    def position(self) -> float:
        """Seconds into the melody, for drawing the playhead."""
        return self._cursor / self.sample_rate

    def play(self, notes: list[Note]) -> None:
        """Start playing. Restarts cleanly if already playing."""
        import sounddevice as sd

        self.stop()
        self.sample_rate = self._requested_rate or device_sample_rate()
        buffer = render(notes, self.sample_rate)
        if buffer.size == 0:
            return

        self._buffer = buffer
        self._cursor = 0

        def callback(outdata, frames, _time_info, _status) -> None:
            # No lock here: a Python lock in the audio callback risks stalling
            # it behind the UI thread. A plain int read/write is atomic enough,
            # and the only reader is the playhead, where a stale frame is
            # invisible.
            start = self._cursor
            chunk = self._buffer[start : start + frames]
            self._cursor = start + chunk.size

            outdata[: chunk.size, 0] = chunk
            if chunk.size < frames:
                outdata[chunk.size :, 0] = 0.0
                raise sd.CallbackStop

        self._stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            latency="high",  # prefer a safe buffer over low latency
            callback=callback,
            finished_callback=self._on_finished,
        )
        self._stream.start()

    def _on_finished(self) -> None:
        self._stream = None

    def stop(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        with self._lock:
            self._cursor = 0
