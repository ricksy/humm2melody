"""Microphone capture and the real-time analysis loop.

The PortAudio callback must stay cheap, so it does nothing but hand blocks to a
queue. A worker thread owns the sliding window and the YIN calls, which keeps
pitch detection off both the audio thread and the UI thread.
"""

from __future__ import annotations

import math
import queue
import threading
from dataclasses import dataclass

import numpy as np

from .pitch import PitchFrame, analyse_frame, hz_to_note

SAMPLE_RATE = 22050
"""Plenty for a hummed fundamental, and half the YIN work of 44.1 kHz."""

FRAME_SIZE = 2048  # ~93 ms analysis window
HOP_SIZE = 512  # ~23 ms between estimates


@dataclass(frozen=True)
class LiveReading:
    """The most recent estimate, for the live display."""

    freq: float
    confidence: float
    level: float  # 0..1, for the meter
    note: str  # "" when unvoiced
    cents: float
    elapsed: float


METER_FLOOR_DB = -48.0
"""Level that reads as an empty meter."""


def meter_level(rms: float) -> float:
    """Map an RMS amplitude onto a 0..1 meter position, on a dB scale.

    A linear meter is useless for audio: quiet humming sits in the bottom few
    percent of the bar while anything loud pins it to full. On a dB scale
    -48 dBFS reads empty and 0 dBFS reads full, which spreads normal humming
    across the middle of the bar where it can actually be seen to move.
    """
    if rms <= 1e-9:
        return 0.0
    db = 20.0 * math.log10(rms)
    return min(1.0, max(0.0, (db - METER_FLOOR_DB) / -METER_FLOOR_DB))


class AudioError(RuntimeError):
    """Raised when the microphone cannot be opened."""


class Recorder:
    """Captures the microphone and produces a pitch track."""

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        frame_size: int = FRAME_SIZE,
        hop_size: int = HOP_SIZE,
        device: int | str | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.frame_size = frame_size
        self.hop_size = hop_size
        self.device = device

        self._frames: list[PitchFrame] = []
        self._raw: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._queue: queue.Queue[np.ndarray | None] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._stream = None
        self._latest = LiveReading(0.0, 0.0, 0.0, "", 0.0, 0.0)
        self._running = False
        self._overflows = 0

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        """Open the mic and begin analysing. Raises AudioError on failure."""
        if self._running:
            return

        import sounddevice as sd

        with self._lock:
            self._frames = []
            self._raw = []
        self._queue = queue.Queue()
        self._latest = LiveReading(0.0, 0.0, 0.0, "", 0.0, 0.0)
        self._overflows = 0

        def callback(indata, _frames_count, _time_info, status) -> None:
            if status.input_overflow:
                self._overflows += 1
            # Copy: PortAudio reuses the buffer once the callback returns.
            self._queue.put(indata[:, 0].astype(np.float32, copy=True))

        try:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                blocksize=self.hop_size,
                channels=1,
                dtype="float32",
                device=self.device,
                callback=callback,
            )
            self._stream.start()
        except Exception as exc:  # sounddevice raises a grab-bag of types
            self._stream = None
            raise AudioError(str(exc)) from exc

        self._running = True
        self._worker = threading.Thread(target=self._analyse, daemon=True)
        self._worker.start()

    def stop(self) -> list[PitchFrame]:
        """Stop capture and return the full pitch track."""
        if not self._running:
            return self.frames()

        self._running = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        self._queue.put(None)  # sentinel: let the worker drain and exit
        if self._worker is not None:
            self._worker.join(timeout=2.0)
            self._worker = None

        return self.frames()

    def frames(self) -> list[PitchFrame]:
        with self._lock:
            return list(self._frames)

    def audio(self) -> np.ndarray:
        """Everything the microphone captured, for saving alongside the notes."""
        with self._lock:
            blocks = list(self._raw)
        if not blocks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(blocks)

    def latest(self) -> LiveReading:
        return self._latest

    @property
    def overflows(self) -> int:
        """Dropped-block count; a nonzero value means the machine fell behind."""
        return self._overflows

    def _analyse(self) -> None:
        buffer = np.zeros(self.frame_size, dtype=np.float32)
        filled = 0
        samples_seen = 0

        while True:
            block = self._queue.get()
            if block is None:
                break

            with self._lock:
                self._raw.append(block)

            # Slide the window left by one hop and append the new block.
            buffer = np.roll(buffer, -block.size)
            buffer[-block.size :] = block
            filled = min(filled + block.size, self.frame_size)
            samples_seen += block.size

            if filled < self.frame_size:
                continue

            # Timestamp the centre of the window, not its trailing edge.
            time = max(0.0, (samples_seen - self.frame_size / 2) / self.sample_rate)
            frame = analyse_frame(
                buffer, self.sample_rate, time, energy_span=self.hop_size
            )
            with self._lock:
                self._frames.append(frame)

            note, cents = "", 0.0
            if frame.voiced and frame.confidence >= 0.55:
                _, note, cents = hz_to_note(frame.freq)

            self._latest = LiveReading(
                freq=frame.freq,
                confidence=frame.confidence,
                level=meter_level(frame.rms),
                note=note,
                cents=cents,
                elapsed=samples_seen / self.sample_rate,
            )


def list_input_devices() -> list[tuple[int, str]]:
    """Available input devices as (index, name)."""
    import sounddevice as sd

    devices = []
    for index, info in enumerate(sd.query_devices()):
        if info["max_input_channels"] > 0:
            devices.append((index, info["name"]))
    return devices
