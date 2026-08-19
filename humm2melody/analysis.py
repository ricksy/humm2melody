"""Offline diagnostics for a saved run.

Detection failures are hard to reason about from the transcription alone: by
the time you see notes, smoothing and segmentation have already thrown away the
evidence. This re-runs the pipeline over a saved `hum.wav` and reports what the
detector actually saw, so a bad result can be attributed to a cause rather than
guessed at.

    uv run humm2melody analyze recordings/2026-08-19_14-32-05
    uv run humm2melody analyze <run> --expect "C4 D4 E4"
    uv run humm2melody analyze <run> --sweep --expect "C4 D4 E4"
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np

from .pitch import PitchFrame, analyse_signal, hz_to_midi, midi_to_name
from .segment import Note, segment_notes
from .sessions import read_wav

GLIDE_SEMITONES_PER_SEC = 2.0
"""Above this rate of pitch change, a frame is sliding rather than held."""


@dataclass
class Diagnosis:
    """What the detector saw, and what looks wrong with it."""

    duration: float = 0.0
    sample_rate: int = 0
    frame_count: int = 0
    voiced_count: int = 0

    rms_percentiles: dict[int, float] = field(default_factory=dict)
    confidence_percentiles: dict[int, float] = field(default_factory=dict)

    f0_low: float = 0.0
    f0_high: float = 0.0
    f0_median: float = 0.0

    tuning_offset_cents: float = 0.0
    glide_fraction: float = 0.0
    octave_jumps: int = 0
    note_cents_spread: float = 0.0

    notes: list[Note] = field(default_factory=list)

    @property
    def voiced_fraction(self) -> float:
        return self.voiced_count / self.frame_count if self.frame_count else 0.0

    @property
    def sequence(self) -> list[str]:
        return [n.name for n in self.notes]


def _percentiles(values: np.ndarray, points=(5, 50, 95)) -> dict[int, float]:
    if values.size == 0:
        return {p: 0.0 for p in points}
    return {p: float(np.percentile(values, p)) for p in points}


def tuning_offset_cents(midis: np.ndarray) -> float:
    """Estimate how far the whole performance sits off the equal-tempered grid.

    Humans do not hum in A440. A singer sitting a consistent 40 cents sharp is
    still perfectly musical, but if that offset lands near 50 cents then every
    note is a coin-flip between two semitones and vibrato decides the outcome —
    which wrecks the intervals, not just the key.

    Averaged as angles on a circle, because the deviation wraps: +49 and -49
    cents are 2 cents apart, not 98.
    """
    if midis.size == 0:
        return 0.0
    angles = 2 * np.pi * (midis % 1.0)
    mean = np.arctan2(np.sin(angles).mean(), np.cos(angles).mean())
    cents = (mean / (2 * np.pi)) * 100.0
    return float((cents + 50.0) % 100.0 - 50.0)


def diagnose(
    audio: np.ndarray,
    sample_rate: int,
    *,
    min_confidence: float = 0.55,
    min_rms: float = 0.006,
    **segment_kwargs,
) -> Diagnosis:
    """Re-run detection over a recording and measure what happened."""
    frames = analyse_signal(audio, sample_rate)
    return diagnose_frames(
        frames,
        audio_seconds=len(audio) / sample_rate if sample_rate else 0.0,
        sample_rate=sample_rate,
        min_confidence=min_confidence,
        min_rms=min_rms,
        **segment_kwargs,
    )


def diagnose_frames(
    frames: list[PitchFrame],
    *,
    audio_seconds: float = 0.0,
    sample_rate: int = 0,
    min_confidence: float = 0.55,
    min_rms: float = 0.006,
    **segment_kwargs,
) -> Diagnosis:
    report = Diagnosis(
        duration=audio_seconds,
        sample_rate=sample_rate,
        frame_count=len(frames),
    )
    if not frames:
        return report

    report.rms_percentiles = _percentiles(np.array([f.rms for f in frames]))
    report.confidence_percentiles = _percentiles(
        np.array([f.confidence for f in frames])
    )

    voiced = [
        f
        for f in frames
        if f.voiced and f.confidence >= min_confidence and f.rms >= min_rms
    ]
    report.voiced_count = len(voiced)

    if voiced:
        freqs = np.array([f.freq for f in voiced])
        report.f0_low = float(freqs.min())
        report.f0_high = float(freqs.max())
        report.f0_median = float(np.median(freqs))

        midis = np.array([hz_to_midi(f) for f in freqs])
        times = np.array([f.time for f in voiced])
        report.tuning_offset_cents = tuning_offset_cents(midis)

        # Rate of pitch change, but only across frames that are genuinely
        # adjacent — a gap in voicing is not a glide.
        if midis.size > 1:
            dt = np.diff(times)
            dm = np.abs(np.diff(midis))
            contiguous = dt < 0.05
            if contiguous.any():
                rate = dm[contiguous] / np.maximum(dt[contiguous], 1e-6)
                report.glide_fraction = float(np.mean(rate > GLIDE_SEMITONES_PER_SEC))
                report.octave_jumps = int(
                    np.sum((dm[contiguous] > 11.0) & (dm[contiguous] < 13.0))
                )

    report.notes = segment_notes(
        frames,
        min_confidence=min_confidence,
        min_rms=min_rms,
        **segment_kwargs,
    )

    spreads = []
    for note in report.notes:
        inside = [
            hz_to_midi(f.freq)
            for f in voiced
            if note.start <= f.time < note.end and f.freq > 0
        ]
        if len(inside) > 1:
            spreads.append(float(np.std(inside)) * 100.0)
    report.note_cents_spread = float(np.mean(spreads)) if spreads else 0.0

    return report


def parse_expected(text: str) -> list[str]:
    """Parse "C4 D4 E4" or "C4,D4,E4" into a note-name list."""
    return [part for part in text.replace(",", " ").split() if part]


def compare(detected: list[str], expected: list[str]) -> tuple[int, str]:
    """Score a transcription against what was intended.

    Returns (edit_distance, verdict). Intervals are checked separately from
    absolute pitch, because a hum transposed into a comfortable key is a
    correct transcription of what was actually sung.
    """
    distance = _levenshtein(detected, expected)
    if detected == expected:
        return 0, "exact match"

    if len(detected) == len(expected) and len(detected) > 1:
        got = _intervals(detected)
        want = _intervals(expected)
        if got == want:
            shift = _midi(detected[0]) - _midi(expected[0])
            return distance, (
                f"intervals match, transposed by {shift:+d} semitones "
                "(the melody is right, just in a different key)"
            )
    return distance, f"{distance} edit(s) from expected"


def _intervals(names: list[str]) -> list[int]:
    midis = [_midi(n) for n in names]
    return [b - a for a, b in zip(midis, midis[1:])]


def _midi(name: str) -> int:
    from .pitch import NOTE_NAMES

    for length in (2, 1):
        pitch, octave = name[:length], name[length:]
        if pitch in NOTE_NAMES and octave.lstrip("-").isdigit():
            return NOTE_NAMES.index(pitch) + (int(octave) + 1) * 12
    raise ValueError(f"not a note name: {name!r}")


def _levenshtein(a: list[str], b: list[str]) -> int:
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, start=1):
        current = [i]
        for j, y in enumerate(b, start=1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y))
            )
        previous = current
    return previous[-1]


SWEEP_GRID = {
    "min_confidence": (0.45, 0.55, 0.65),
    "min_rms": (0.002, 0.006, 0.012),
    "min_duration": (0.06, 0.09, 0.14),
    "smoothing": (3, 5, 9),
    "gap_tolerance": (0.05, 0.07, 0.12),
    "max_glide_rate": (None, 2.0, 3.0, 5.0),
}


def sweep(
    audio: np.ndarray,
    sample_rate: int,
    expected: list[str],
    grid: dict | None = None,
) -> list[tuple[int, dict, list[str]]]:
    """Try many parameter combinations, ranked by closeness to `expected`.

    The frames are computed once and reused: only segmentation depends on these
    parameters, so re-running YIN for every combination would be wasted work.
    """
    grid = grid or SWEEP_GRID
    frames = analyse_signal(audio, sample_rate)

    keys = list(grid)
    results = []
    for combo in itertools.product(*(grid[k] for k in keys)):
        params = dict(zip(keys, combo))
        notes = segment_notes(frames, **params)
        names = [n.name for n in notes]
        results.append((_levenshtein(names, expected), params, names))

    results.sort(key=lambda r: (r[0], len(r[2])))
    return results


def format_report(report: Diagnosis, expected: list[str] | None = None) -> str:
    """Render a diagnosis as a plain-text report."""
    out: list[str] = []
    add = out.append

    add("── recording ──────────────────────────────────────────")
    add(f"  duration          {report.duration:.2f}s at {report.sample_rate} Hz")
    add(f"  analysis frames   {report.frame_count}")
    add(
        f"  voiced            {report.voiced_count} "
        f"({report.voiced_fraction * 100:.0f}%)"
    )

    add("")
    add("── level and confidence ───────────────────────────────")
    rms = report.rms_percentiles
    add(
        f"  rms   p5 {rms.get(5, 0):.4f}   median {rms.get(50, 0):.4f}   "
        f"p95 {rms.get(95, 0):.4f}"
    )
    conf = report.confidence_percentiles
    add(
        f"  conf  p5 {conf.get(5, 0):.2f}     median {conf.get(50, 0):.2f}     "
        f"p95 {conf.get(95, 0):.2f}"
    )
    if rms.get(95, 0) < 0.01:
        add("  ! very quiet: hum closer to the mic, or lower min_rms")

    if report.voiced_count:
        add("")
        add("── pitch ──────────────────────────────────────────────")
        add(
            f"  range             {report.f0_low:.1f} - {report.f0_high:.1f} Hz "
            f"({midi_to_name(round(hz_to_midi(report.f0_low)))} - "
            f"{midi_to_name(round(hz_to_midi(report.f0_high)))})"
        )
        add(
            f"  median            {report.f0_median:.1f} Hz "
            f"({midi_to_name(round(hz_to_midi(report.f0_median)))})"
        )
        add(f"  tuning offset     {report.tuning_offset_cents:+.0f} cents")
        if abs(report.tuning_offset_cents) > 35:
            add("  ! sitting near a semitone boundary: small wobble will flip")
            add("    notes between two semitones. Worth correcting globally.")
        add(f"  gliding frames    {report.glide_fraction * 100:.0f}%")
        if report.glide_fraction > 0.35:
            add("  ! mostly sliding rather than holding: the segmenter snaps")
            add("    every semitone a glide passes through into its own note.")
        add(f"  octave jumps      {report.octave_jumps}")
        if report.octave_jumps > 2:
            add("  ! octave instability: YIN is switching between f0 and 2*f0.")
        add(f"  within-note wobble {report.note_cents_spread:.0f} cents sd")

    add("")
    add("── transcription ──────────────────────────────────────")
    add(f"  {len(report.notes)} notes: {' '.join(report.sequence) or '(none)'}")
    if expected:
        distance, verdict = compare(report.sequence, expected)
        add(f"  expected:  {' '.join(expected)}")
        add(f"  verdict:   {verdict}")

    return "\n".join(out)


def load_run(path) -> tuple[np.ndarray, int]:
    """Load a run directory's hum.wav, or a bare .wav file."""
    from pathlib import Path

    path = Path(path)
    wav = path if path.suffix == ".wav" else path / "hum.wav"
    if not wav.is_file():
        raise FileNotFoundError(f"no hum.wav in {path}")
    return read_wav(wav)
