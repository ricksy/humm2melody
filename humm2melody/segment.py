"""Turn a frame-by-frame pitch track into playable notes.

A raw pitch track is too jittery to read: vibrato, glides between notes and the
odd octave slip all show up as separate values. This module smooths the track,
snaps it to semitones and groups it into note events long enough to be worth
playing.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np

from .pitch import PitchFrame, hz_to_midi, midi_to_hz, midi_to_name


@dataclass(frozen=True)
class Note:
    """One detected note event."""

    midi: int
    start: float  # seconds
    end: float  # seconds
    freq: float  # mean measured frequency across the note
    confidence: float  # mean YIN confidence

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def name(self) -> str:
        return midi_to_name(self.midi)

    @property
    def cents_off(self) -> float:
        """How far the hummed pitch sat from the snapped note, in cents."""
        if self.freq <= 0:
            return 0.0
        return (hz_to_midi(self.freq) - self.midi) * 100.0

    @property
    def ideal_freq(self) -> float:
        return midi_to_hz(self.midi)


def _median_filter(values: np.ndarray, size: int) -> np.ndarray:
    """NaN-aware running median. NaN marks an unvoiced frame."""
    if size <= 1 or values.size == 0:
        return values
    half = size // 2
    padded = np.pad(values, half, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, size)
    with warnings.catch_warnings():
        # An all-NaN window is silence, and NaN is the answer we want there.
        warnings.simplefilter("ignore", RuntimeWarning)
        out = np.nanmedian(windows, axis=1)
    return out


VIBRATO_PERIOD = 0.23
"""Measurement window for glide rate: one cycle of slowish (~4.5 Hz) vibrato."""


def glide_mask(
    midis: np.ndarray,
    times: np.ndarray,
    max_rate: float,
    window: float = VIBRATO_PERIOD,
) -> np.ndarray:
    """Mark frames where pitch is sliding rather than being held.

    Sung melodies are legato: the voice slides between notes instead of
    jumping. Snapping every frame of that slide invents a note for each
    semitone it passes through, so humming C-D-E in one breath transcribes as
    a chromatic run.

    The rate is measured across a window of at least one vibrato cycle. That
    matters more than it looks: vibrato has a huge instantaneous slope --
    +/-40 cents at 5 Hz swings faster than 6 semitones/sec -- so a short
    window reads a perfectly steady note as a glide and splits it in two.
    Over a full cycle the wobble cancels and only real drift is left.
    """
    count = midis.size
    mask = np.zeros(count, dtype=bool)
    if count == 0:
        return mask

    step = float(np.median(np.diff(times))) if count > 1 else window
    if step <= 0:
        return mask

    # Median-filter over a vibrato cycle first. A median removes oscillation
    # but preserves edges, so vibrato flattens while a genuine note change
    # stays a sharp step -- which lets the slope below tell a slide (sustained)
    # apart from a jump (one step), instead of blanking a window around both.
    robust = _median_filter(midis, _odd(window / step))
    span = 2

    for i in range(count):
        lo, hi = max(0, i - span), min(count - 1, i + span)
        if np.isnan(robust[lo]) or np.isnan(robust[hi]):
            continue
        dt = times[hi] - times[lo]
        if dt <= 0:
            continue
        mask[i] = abs(robust[hi] - robust[lo]) / dt > max_rate
    return mask


def _odd(value: float) -> int:
    """Nearest odd integer >= 3, so a median window stays centred."""
    size = max(3, int(round(value)))
    return size if size % 2 else size + 1


def segment_notes(
    frames: list[PitchFrame],
    *,
    min_confidence: float = 0.55,
    min_rms: float = 0.006,
    min_duration: float = 0.09,
    gap_tolerance: float = 0.07,
    smoothing: int = 5,
    max_glide_rate: float | None = 3.0,
) -> list[Note]:
    """Group a pitch track into notes.

    ``min_confidence``/``min_rms`` gate out breath and room noise,
    ``smoothing`` is the median-filter width in frames (kills single-frame
    octave slips), ``min_duration`` drops notes too short to be intentional,
    and ``gap_tolerance`` lets a note survive a brief dropout without being
    split in two.

    ``max_glide_rate`` (semitones/second, None to disable) discards frames
    where the pitch is sliding rather than held, which is what stops a legato
    hum from transcribing as a chromatic run.
    """
    if not frames:
        return []

    times = np.array([f.time for f in frames])
    midis = np.full(len(frames), np.nan)
    for i, f in enumerate(frames):
        if f.voiced and f.confidence >= min_confidence and f.rms >= min_rms:
            midis[i] = hz_to_midi(f.freq)

    smoothed = _median_filter(midis, smoothing)
    # Smoothing corrects pitch values, never voicing: without this the filter
    # would spread a note into the surrounding silence, inflating durations and
    # welding repeated notes together across their gap.
    smoothed[np.isnan(midis)] = np.nan

    if max_glide_rate is not None:
        # Drop the slides, keep the held pitch on either side of them.
        smoothed[glide_mask(smoothed, times, max_glide_rate)] = np.nan

    snapped = np.where(np.isnan(smoothed), np.nan, np.round(smoothed))

    frame_step = float(np.median(np.diff(times))) if len(times) > 1 else 0.01

    notes: list[Note] = []
    run_start: int | None = None
    run_midi = 0

    def close_run(start_idx: int, end_idx: int, midi: int) -> None:
        """Emit a note for frames [start_idx, end_idx)."""
        members = [
            frames[i]
            for i in range(start_idx, end_idx)
            if not np.isnan(snapped[i]) and int(snapped[i]) == midi
        ]
        if not members:
            return
        start = times[start_idx]
        end = times[end_idx - 1] + frame_step
        if end - start < min_duration:
            return
        notes.append(
            Note(
                midi=midi,
                start=float(start),
                end=float(end),
                freq=float(np.mean([m.freq for m in members])),
                confidence=float(np.mean([m.confidence for m in members])),
            )
        )

    gap_frames = max(1, int(round(gap_tolerance / frame_step)))
    silence = 0

    for i, value in enumerate(snapped):
        if np.isnan(value):
            # Tolerate a short dropout; only end the run once it drags on.
            if run_start is not None:
                silence += 1
                if silence > gap_frames:
                    close_run(run_start, i - silence + 1, run_midi)
                    run_start = None
                    silence = 0
            continue

        midi = int(value)
        if run_start is None:
            run_start, run_midi, silence = i, midi, 0
        elif midi != run_midi:
            close_run(run_start, i - silence, run_midi)
            run_start, run_midi, silence = i, midi, 0
        else:
            silence = 0

    if run_start is not None:
        close_run(run_start, len(snapped) - silence, run_midi)

    return _merge_adjacent(notes, gap_tolerance)


def _merge_adjacent(notes: list[Note], gap_tolerance: float) -> list[Note]:
    """Join same-pitch notes separated only by a brief gap."""
    if not notes:
        return []
    merged = [notes[0]]
    for note in notes[1:]:
        prev = merged[-1]
        if note.midi == prev.midi and note.start - prev.end <= gap_tolerance:
            total = prev.duration + note.duration
            merged[-1] = Note(
                midi=prev.midi,
                start=prev.start,
                end=note.end,
                freq=(prev.freq * prev.duration + note.freq * note.duration) / total,
                confidence=(
                    prev.confidence * prev.duration + note.confidence * note.duration
                )
                / total,
            )
        else:
            merged.append(note)
    return merged
