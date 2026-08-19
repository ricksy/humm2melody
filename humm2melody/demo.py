"""A microphone stand-in that replays a synthetic hum in real time.

Used by `--demo` and by the documentation screen captures. It exists because
the app is hard to show off otherwise: a screenshot of a pitch detector with no
one humming into it is a screenshot of nothing.

`DemoRecorder` is a drop-in for `Recorder` and pushes its audio through exactly
the same sliding window and the same `analyse_frame` call, so what you see in a
capture is the real detector working — only the source of the samples differs.
"""

from __future__ import annotations

import threading
import time

import numpy as np

from .audio import FRAME_SIZE, HOP_SIZE, SAMPLE_RATE, LiveReading, meter_level
from .pitch import PitchFrame, analyse_frame, hz_to_note, midi_to_hz

DEMO_MELODY: list[tuple[int, float]] = [
    (60, 0.40),  # C4  — "Twinkle, twinkle, little star", which is handy
    (60, 0.40),  # C4    because the repeated notes show that the detector
    (67, 0.40),  # G4    separates them instead of merging them into one.
    (67, 0.40),  # G4
    (69, 0.40),  # A4
    (69, 0.40),  # A4
    (67, 0.75),  # G4
]

GAP = 0.13
"""Silence between notes. Long enough for repeated notes to stay separate."""

LEAD_IN = 0.35


def synth_hum(
    melody: list[tuple[int, float]] | None = None,
    sample_rate: int = SAMPLE_RATE,
    *,
    seed: int = 7,
    noise: float = 0.0015,
) -> np.ndarray:
    """Render a melody as something that behaves like an actual hum.

    A pure tone would be unrealistically easy to detect, so each note gets a
    small constant detune and a slow vibrato — enough that the tuning column
    has something to say, without pushing anything over a semitone boundary.
    The RNG is seeded so captures are reproducible.
    """
    melody = melody or DEMO_MELODY
    rng = np.random.default_rng(seed)
    parts: list[np.ndarray] = [np.zeros(int(LEAD_IN * sample_rate))]

    for midi, seconds in melody:
        length = int(seconds * sample_rate)
        t = np.arange(length) / sample_rate

        detune = rng.uniform(-0.18, 0.18)  # semitones, i.e. under 20 cents
        vibrato = 0.06 * np.sin(2 * np.pi * 5.2 * t) * np.minimum(1.0, t / 0.12)
        freq = midi_to_hz(midi + detune) * (2 ** (vibrato / 12))

        # Integrate frequency so the phase stays continuous under vibrato.
        phase = 2 * np.pi * np.cumsum(freq) / sample_rate
        wave = np.sin(phase) + 0.4 * np.sin(2 * phase) + 0.15 * np.sin(3 * phase)
        wave *= _envelope(length, sample_rate) * rng.uniform(0.34, 0.46)

        parts.append(wave)
        parts.append(np.zeros(int(GAP * sample_rate)))

    audio = np.concatenate(parts)
    audio += rng.normal(0.0, noise, audio.size)  # a quiet room, not a vacuum
    peak = np.max(np.abs(audio))
    if peak > 0.95:
        audio *= 0.95 / peak
    return audio.astype(np.float32)


def _envelope(length: int, sample_rate: int) -> np.ndarray:
    env = np.ones(length)
    attack = min(int(0.05 * sample_rate), length // 3)
    release = min(int(0.06 * sample_rate), length // 3)
    if attack:
        env[:attack] = np.linspace(0.0, 1.0, attack) ** 0.6
    if release:
        env[-release:] *= np.linspace(1.0, 0.0, release) ** 0.6
    return env


class DemoRecorder:
    """Replays synthetic audio at wall-clock speed, like a microphone would."""

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        frame_size: int = FRAME_SIZE,
        hop_size: int = HOP_SIZE,
        audio: np.ndarray | None = None,
        realtime: bool = True,
        fmin: float = 65.0,
        fmax: float = 1200.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.frame_size = frame_size
        self.hop_size = hop_size
        self.realtime = realtime
        self.fmin = fmin
        self.fmax = fmax
        self._source = synth_hum(sample_rate=sample_rate) if audio is None else audio

        self._frames: list[PitchFrame] = []
        self._raw: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._latest = LiveReading(0.0, 0.0, 0.0, "", 0.0, 0.0)
        self._running = False
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def running(self) -> bool:
        return self._running

    @property
    def overflows(self) -> int:
        return 0

    def start(self) -> None:
        if self._running:
            return
        with self._lock:
            self._frames = []
            self._raw = []
        self._latest = LiveReading(0.0, 0.0, 0.0, "", 0.0, 0.0)
        self._stop.clear()
        self._running = True
        self._worker = threading.Thread(target=self._replay, daemon=True)
        self._worker.start()

    def stop(self) -> list[PitchFrame]:
        if not self._running:
            return self.frames()
        self._running = False
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=2.0)
            self._worker = None
        return self.frames()

    def frames(self) -> list[PitchFrame]:
        with self._lock:
            return list(self._frames)

    def audio(self) -> np.ndarray:
        with self._lock:
            blocks = list(self._raw)
        if not blocks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(blocks)

    def latest(self) -> LiveReading:
        return self._latest

    def _replay(self) -> None:
        buffer = np.zeros(self.frame_size, dtype=np.float32)
        filled = 0
        samples_seen = 0
        cursor = 0
        started = time.monotonic()

        while not self._stop.is_set():
            block = self._source[cursor : cursor + self.hop_size]
            cursor += self.hop_size
            if block.size < self.hop_size:
                # Past the end of the melody, keep feeding a quiet room so the
                # display behaves like a real mic until the user hits stop.
                block = np.zeros(self.hop_size, dtype=np.float32)

            with self._lock:
                self._raw.append(np.asarray(block, dtype=np.float32))

            buffer = np.roll(buffer, -block.size)
            buffer[-block.size :] = block
            filled = min(filled + block.size, self.frame_size)
            samples_seen += block.size

            if filled >= self.frame_size:
                time_s = max(
                    0.0, (samples_seen - self.frame_size / 2) / self.sample_rate
                )
                frame = analyse_frame(
                    buffer,
                    self.sample_rate,
                    time_s,
                    energy_span=self.hop_size,
                    fmin=self.fmin,
                    fmax=self.fmax,
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

            if self.realtime:
                target = started + (samples_seen / self.sample_rate)
                self._stop.wait(max(0.0, target - time.monotonic()))
            elif cursor > self._source.size:
                break
