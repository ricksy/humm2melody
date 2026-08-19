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
    pitch: float = 0.0  # continuous MIDI value before snapping, 0 if unknown

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


def _odd(value: float) -> int:
    """Nearest odd integer >= 3, so a median window stays centred."""
    size = max(3, int(round(value)))
    return size if size % 2 else size + 1


def _median_filter(values: np.ndarray, size: int) -> np.ndarray:
    """NaN-aware running median. NaN marks an unvoiced frame."""
    if size <= 1 or values.size == 0:
        return values
    # An even window cannot be centred: the symmetric padding below would
    # return one sample more than it was given.
    size = _odd(size)
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


def tuning_offset_semitones(midis: np.ndarray) -> float:
    """How far a performance sits off the equal-tempered grid, in semitones.

    Nobody hums in A440. A voice sitting a consistent 40 cents sharp is still
    musical, but rounding is done at the half-semitone line, so a performance
    parked near that line has every note decided by whichever way a small
    wobble happened to lean -- two renditions of the *same* pitch can land a
    semitone apart. Estimating the offset and shifting the grid to match is
    what a chromatic tuner does when it calibrates.

    Averaged as angles on a circle, because deviation wraps: +49 and -49 cents
    are 2 cents apart, not 98.
    """
    values = midis[~np.isnan(midis)]
    if values.size == 0:
        return 0.0
    angles = 2 * np.pi * (values % 1.0)
    mean = np.arctan2(np.sin(angles).mean(), np.cos(angles).mean())
    offset = mean / (2 * np.pi)
    return float((offset + 0.5) % 1.0 - 0.5)


def segment_notes(
    frames: list[PitchFrame],
    *,
    min_confidence: float = 0.55,
    min_rms: float = 0.006,
    min_duration: float = 0.09,
    gap_tolerance: float = 0.07,
    smoothing: int = 5,
    max_glide_rate: float | None = 5.0,
    tuning: str | float | None = "auto",
    max_step: float = 0.8,
    merge_within: float = 0.0,
    cluster_tolerance: float = 0.0,
) -> list[Note]:
    """Group a pitch track into notes.

    ``min_confidence``/``min_rms`` gate out breath and room noise,
    ``smoothing`` is the median-filter width in frames (kills single-frame
    octave slips), ``min_duration`` drops notes too short to be intentional,
    and ``gap_tolerance`` lets a note survive a brief dropout without being
    split in two.

    ``max_glide_rate`` (semitones/second, None to disable) discards frames
    where the pitch is sliding rather than held, which stops a legato hum from
    transcribing as a chromatic run.

    ``tuning`` shifts the semitone grid: ``"auto"`` estimates the offset from
    the recording, a number sets it in cents, ``None`` pins it to A440.

    A note is decided from the *median* of a whole held region rather than by
    rounding each frame and grouping equal values. Voices drift: holding one
    note while sliding a semitone across a rounding boundary used to split it
    into two different notes, which is a property of the arithmetic and not of
    the singing. ``max_step`` still splits a region where the pitch genuinely
    jumps between adjacent frames.
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

    if tuning == "auto":
        offset = tuning_offset_semitones(smoothed)
    elif tuning is None:
        offset = 0.0
    else:
        offset = float(tuning) / 100.0

    frame_step = float(np.median(np.diff(times))) if len(times) > 1 else 0.01
    gap_frames = max(1, int(round(gap_tolerance / frame_step)))

    notes: list[Note] = []

    def emit(start_idx: int, end_idx: int) -> None:
        """Emit one note for the held region [start_idx, end_idx)."""
        values = smoothed[start_idx:end_idx]
        values = values[~np.isnan(values)]
        if values.size == 0:
            return
        start = float(times[start_idx])
        end = float(times[end_idx - 1] + frame_step)
        if end - start < min_duration:
            return

        pitch = float(np.median(values)) - offset
        members = [
            frames[i]
            for i in range(start_idx, end_idx)
            if not np.isnan(smoothed[i]) and frames[i].freq > 0
        ]
        if not members:
            return
        notes.append(
            Note(
                midi=int(round(pitch)),
                pitch=pitch,
                start=start,
                end=end,
                freq=float(np.mean([m.freq for m in members])),
                confidence=float(np.mean([m.confidence for m in members])),
            )
        )

    run_start: int | None = None
    last_valid: int | None = None
    silence = 0

    for i, value in enumerate(smoothed):
        if np.isnan(value):
            if run_start is not None:
                silence += 1
                if silence > gap_frames:
                    emit(run_start, last_valid + 1)
                    run_start = None
                    silence = 0
            continue

        if run_start is None:
            run_start, last_valid, silence = i, i, 0
            continue

        # A genuine jump ends the region even when nothing was gliding, which
        # keeps back-to-back notes apart if glide gating is switched off.
        if abs(value - smoothed[last_valid]) > max_step:
            emit(run_start, last_valid + 1)
            run_start = i
        last_valid, silence = i, 0

    if run_start is not None and last_valid is not None:
        emit(run_start, last_valid + 1)

    notes = _cluster_pitches(notes, cluster_tolerance)
    return _merge_adjacent(notes, gap_tolerance, merge_within)


def _cluster_pitches(notes: list[Note], tolerance: float) -> list[Note]:
    """Collapse pitches that are close together anywhere in the recording.

    An unsteady voice returns to "the same" note a little flat or sharp each
    time. If those renditions straddle a rounding boundary they come out as
    different notes -- a low-high-low phrase reads as three *different*
    pitches. Clustering the whole recording fixes that, where merging only
    adjacent notes cannot: the two lows are not adjacent, the high is between
    them.

    Membership is tested against the running cluster median rather than the
    previous member, so a slow drift cannot chain far-apart pitches together.
    """
    if tolerance <= 0 or len(notes) < 2:
        return notes

    order = sorted(range(len(notes)), key=lambda i: notes[i].pitch)
    clusters: list[list[int]] = []
    for index in order:
        pitch = notes[index].pitch
        if clusters:
            current = [notes[i].pitch for i in clusters[-1]]
            if abs(pitch - float(np.median(current))) <= tolerance:
                clusters[-1].append(index)
                continue
        clusters.append([index])

    resolved = list(notes)
    for cluster in clusters:
        centre = float(np.median([notes[i].pitch for i in cluster]))
        midi = int(round(centre))
        for i in cluster:
            resolved[i] = Note(
                midi=midi,
                pitch=centre,
                start=notes[i].start,
                end=notes[i].end,
                freq=notes[i].freq,
                confidence=notes[i].confidence,
            )
    return resolved


def _merge_adjacent(
    notes: list[Note], gap_tolerance: float, merge_within: float = 0.0
) -> list[Note]:
    """Join notes separated only by a brief gap.

    Same-pitch neighbours always merge. ``merge_within`` additionally merges
    neighbours whose pitches are within that many semitones, which is how a low
    sensitivity setting stops an unsteady voice from reading as a melody: the
    combined pitch is re-snapped from the duration-weighted average.
    """
    if not notes:
        return []
    merged = [notes[0]]
    for note in notes[1:]:
        prev = merged[-1]
        close = note.midi == prev.midi or (
            merge_within > 0 and abs(note.midi - prev.midi) <= merge_within
        )
        if close and note.start - prev.end <= gap_tolerance:
            total = prev.duration + note.duration
            blended = (
                prev.freq * prev.duration + note.freq * note.duration
            ) / total
            merged[-1] = Note(
                midi=prev.midi if note.midi == prev.midi else round(hz_to_midi(blended)),
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


SENSITIVITY_MIN = 1
SENSITIVITY_MAX = 9
SENSITIVITY_DEFAULT = 5

_ANCHORS: dict[int, dict[str, float]] = {
    # Forgiving: an unsteady voice reads as few, long, confident notes.
    SENSITIVITY_MIN: {
        "smoothing": 9,
        "min_duration": 0.20,
        "gap_tolerance": 0.12,
        "max_glide_rate": 3.0,
        "merge_within": 1.2,
        "cluster_tolerance": 1.0,
    },
    # The tuned defaults.
    SENSITIVITY_DEFAULT: {
        "smoothing": 5,
        "min_duration": 0.09,
        "gap_tolerance": 0.07,
        "max_glide_rate": 5.0,
        "merge_within": 0.0,
        "cluster_tolerance": 0.35,
    },
    # Literal: every deliberate move is a note, at the cost of picking up wobble.
    SENSITIVITY_MAX: {
        "smoothing": 3,
        "min_duration": 0.05,
        "gap_tolerance": 0.04,
        "max_glide_rate": 9.0,
        "merge_within": 0.0,
        "cluster_tolerance": 0.0,
    },
}


def sensitivity_settings(level: int) -> dict:
    """Segmentation parameters for a sensitivity level from 1 to 9.

    One control, because the parameters are not independent: a voice that
    wanders needs *both* heavier smoothing and a willingness to treat nearby
    pitches as the same note, and exposing five sliders would mostly offer
    combinations that make no sense. Level 5 is the tuned default; lower is
    more forgiving of an unsteady voice, higher resolves smaller intervals.
    """
    level = max(SENSITIVITY_MIN, min(SENSITIVITY_MAX, int(level)))
    if level in _ANCHORS:
        settings = dict(_ANCHORS[level])
    else:
        lo_key = SENSITIVITY_MIN if level < SENSITIVITY_DEFAULT else SENSITIVITY_DEFAULT
        hi_key = SENSITIVITY_DEFAULT if level < SENSITIVITY_DEFAULT else SENSITIVITY_MAX
        lo, hi = _ANCHORS[lo_key], _ANCHORS[hi_key]
        weight = (level - lo_key) / (hi_key - lo_key)
        settings = {
            key: lo[key] + (hi[key] - lo[key]) * weight for key in lo
        }
    settings["smoothing"] = int(round(settings["smoothing"]))
    return settings


def segment_with_sensitivity(
    frames: list[PitchFrame], level: int = SENSITIVITY_DEFAULT, **overrides
) -> list[Note]:
    """Segment a pitch track at the given sensitivity level."""
    settings = sensitivity_settings(level)
    settings.update(overrides)
    return segment_notes(frames, **settings)
