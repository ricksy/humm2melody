"""Browser-side glue between WebAudio and the humm2melody core.

This is the counterpart of `Recorder._analyse` in `humm2melody/audio.py`. That
method owns a sliding window, feeds it to `analyse_frame` and publishes a live
reading; so does this, for exactly the same reason — the capture callback has
to stay cheap. Only the transport differs: a `queue.Queue` fed by PortAudio
there, `postMessage` fed by an AudioWorklet here.

Keep this file thin. Everything it does that is *musical* belongs in the core
package, where the desktop app and the tests can reach it too; what belongs
here is only the part that knows it is talking to a browser.

Nothing in here may import sounddevice, soundfile or textual — see
`tests/test_portable.py`.
"""

from __future__ import annotations

import json
import time

import numpy as np

from humm2melody.audio import FRAME_SIZE, HOP_SIZE, SAMPLE_RATE, meter_level
from humm2melody.naming import SCHEMES, spell
from humm2melody.pitch import analyse_frame, hz_to_note
from humm2melody.playback import (
    mix_hum_with_tones,
    render,
    resample,
    tempo_speed,
)
from humm2melody.segment import segment_with_sensitivity

VOICED_CONFIDENCE = 0.55
"""Matches `Recorder._analyse`, so the live readout agrees with the desktop."""


def schemes() -> str:
    """The notation traditions, for the notation row."""
    return json.dumps(
        [{"key": s.key, "label": s.label, "note": s.note} for s in SCHEMES]
    )


def spell_range(low: int, high: int) -> str:
    """Every spelling of every note in a range, for row and key labels.

    Sent once per transcription rather than per redraw: the browser switches
    notation without a round trip, and `naming.py` stays the only place that
    knows how a pitch is written.
    """
    return json.dumps(
        {
            s.key: {midi: spell(midi, s.key) for midi in range(int(low), int(high) + 1)}
            for s in SCHEMES
        }
    )


def tempo_table() -> str:
    """The nine playback speeds, so JS never reimplements `tempo_speed()`."""
    return json.dumps({level: tempo_speed(level) for level in range(1, 10)})


def _names(midi: int) -> dict:
    return {s.key: spell(midi, s.key) for s in SCHEMES}


def _as_float32(block) -> np.ndarray:
    """Coerce whatever Pyodide handed us into a flat float32 array.

    A JS `Float32Array` arrives as a memoryview, but a plain Array or a
    PyProxy are both possible depending on how the worker was written, and
    getting this wrong is a confusing failure a long way from its cause.
    """
    try:
        arr = np.asarray(memoryview(block), dtype=np.float32)
    except TypeError:
        to_py = getattr(block, "to_py", None)
        arr = np.asarray(to_py() if to_py else block, dtype=np.float32)
    return np.ascontiguousarray(arr.reshape(-1))


class LiveAnalyser:
    """Sliding-window analysis over blocks arriving from the audio thread."""

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        input_rate: int | None = None,
        frame_size: int = FRAME_SIZE,
        hop_size: int = HOP_SIZE,
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.input_rate = int(input_rate or sample_rate)
        self.frame_size = int(frame_size)
        self.hop_size = int(hop_size)

        self._buffer = np.zeros(self.frame_size, dtype=np.float32)
        self._filled = 0
        self._seen = 0
        self._raw: list[np.ndarray] = []
        self._frames: list = []

        # Spike instrumentation: the one number that decides whether Pyodide
        # is viable for the live readout at all (docs/pwa.md, option A).
        self._analysis_seconds = 0.0
        self._analysed = 0

    def reset(self) -> None:
        self.__init__(
            self.sample_rate, self.input_rate, self.frame_size, self.hop_size
        )

    def push(self, block) -> str | None:
        """Add one block of samples. Returns a JSON reading, or None if the
        window is not full yet.

        JSON rather than a dict because the return value crosses into
        JavaScript: a plain string has no proxy to destroy, and at ~43 readings
        a second the encoding cost is irrelevant next to the clarity.
        """
        samples = _as_float32(block)
        if self.input_rate != self.sample_rate:
            # Per-block resampling is approximate at the seams. Acceptable for
            # the spike; the real fix is to ask for a 22.05 kHz AudioContext.
            samples = resample(samples, self.input_rate, self.sample_rate)
        if samples.size == 0:
            return None

        self._raw.append(samples)

        # Slide the window left by one block and append. Same as audio.py.
        self._buffer = np.roll(self._buffer, -samples.size)
        self._buffer[-samples.size :] = samples
        self._filled = min(self._filled + samples.size, self.frame_size)
        self._seen += samples.size

        if self._filled < self.frame_size:
            return None

        started = time.perf_counter()
        # Timestamp the centre of the window, not its trailing edge.
        moment = max(0.0, (self._seen - self.frame_size / 2) / self.sample_rate)
        frame = analyse_frame(
            self._buffer,
            self.sample_rate,
            moment,
            energy_span=self.hop_size,
        )
        self._analysis_seconds += time.perf_counter() - started
        self._analysed += 1
        self._frames.append(frame)

        note, cents = "", 0.0
        if frame.voiced and frame.confidence >= VOICED_CONFIDENCE:
            _, note, cents = hz_to_note(frame.freq)

        return json.dumps(
            {
                "freq": frame.freq,
                "confidence": frame.confidence,
                "level": meter_level(frame.rms),
                "note": note,
                "cents": cents,
                "elapsed": self._seen / self.sample_rate,
                "analysed": self._analysed,
                "meanAnalysisMs": 1000.0 * self._analysis_seconds / self._analysed,
            }
        )

    def transcribe(self, level: int = 5, pause_level: int = 5) -> str:
        """Segment everything captured so far into notes."""
        notes = segment_with_sensitivity(
            self._frames, level=int(level), pause_level=int(pause_level)
        )
        return json.dumps(
            [
                {
                    "midi": n.midi,
                    "name": n.name,
                    "names": _names(n.midi),
                    "start": n.start,
                    "end": n.end,
                    "duration": n.duration,
                    "cents": n.cents_off,
                    # The measured mean, which is what the desktop detail
                    # table's Hz column shows; the snapped pitch is separate.
                    "freq": n.freq,
                    "idealFreq": n.ideal_freq,
                    "attack": n.attack,
                }
                for n in notes
            ]
        )

    def audio(self) -> np.ndarray:
        """Everything captured, at the analysis rate."""
        if not self._raw:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self._raw)

    def playback(self, rate: int = 44100, mix_level: int = 0):
        """Render the transcription to a buffer for WebAudio.

        `render()` and `mix_hum_with_tones()` are reused untouched — this is
        the payoff for synthesis having been kept separate from output.
        """
        notes = segment_with_sensitivity(self._frames)
        if mix_level > 0:
            # It takes the hum at its own rate and does the resampling and the
            # rendering itself, so hand the raw take straight over.
            out = mix_hum_with_tones(
                self.audio(),
                self.sample_rate,
                notes,
                int(rate),
                balance=int(mix_level),
            )
        else:
            out = render(notes, sample_rate=int(rate))
        return out.astype(np.float32, copy=False)


_analyser: LiveAnalyser | None = None


def start(input_rate: int) -> str:
    """Begin a take. Returns the rate the analysis actually runs at."""
    global _analyser
    _analyser = LiveAnalyser(input_rate=int(input_rate))
    return json.dumps(
        {
            "sampleRate": _analyser.sample_rate,
            "inputRate": _analyser.input_rate,
            "frameSize": _analyser.frame_size,
            "hopSize": _analyser.hop_size,
            "targetFps": _analyser.sample_rate / _analyser.hop_size,
            "resampling": _analyser.input_rate != _analyser.sample_rate,
        }
    )


def push(block) -> str | None:
    return _analyser.push(block) if _analyser else None


def transcribe(level: int = 5, pause_level: int = 5) -> str:
    return _analyser.transcribe(level, pause_level) if _analyser else "[]"


def playback(rate: int = 44100, mix_level: int = 0):
    return _analyser.playback(rate, mix_level) if _analyser else np.zeros(0, np.float32)
