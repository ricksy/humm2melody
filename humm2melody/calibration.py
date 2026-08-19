"""Learning a voice, so the dials do not have to be guessed.

Every threshold in `segment.py` started as a constant tuned by hand against one
person's recordings. This measures them instead, per user.

The approach: ask for something whose *structure* is known — a low note, a high
note, then a familiar tune played back and sung in reply — and search for the
dial settings that recover it. That reuses the segmentation the app already
runs rather than inventing a second, untested set of heuristics, and it fails
honestly: if no setting recovers the melody, the take was not good enough and
nothing is saved.

Everything is compared as *intervals*. A voice that cannot reach the reference
octave will sing the tune transposed, and that is a correct performance rather
than an error — so the transposition is measured and reported, not penalised.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .analysis import diagnose_frames
from .pitch import PitchFrame, hz_to_midi, midi_to_hz, midi_to_name
from .profiles import Calibration
from .demo import DEMO_MELODY, GAP, LEAD_IN
from .segment import (
    PAUSE_MAX,
    PAUSE_MIN,
    SENSITIVITY_MAX,
    SENSITIVITY_MIN,
    Note,
    segment_with_sensitivity,
    tuning_offset_semitones,
)

REFERENCE_MELODY = DEMO_MELODY
"""The opening of Twinkle Twinkle Little Star, reused from demo mode.

Asking someone to sing back a tune they already know is far easier than asking
for a scale: no solfege, no guessing what "eight notes going up" means, and the
repeated notes and the leap up to the fifth exercise the two things the dials
actually control.
"""

REFERENCE_MIDIS = [midi for midi, _ in REFERENCE_MELODY]
SCALE_LENGTH = len(REFERENCE_MIDIS)

MAX_ACCURACY_CENTS = 150.0
"""How far off the melody a reply can be and still count as that melody.

Deliberately generous. Singing a note or two off is the thing calibration
*measures*, not a reason to refuse: demanding an exact interval match meant a
real voice essentially never calibrated. Beyond about a semitone and a half of
average error, though, it was a different tune and pairing it note-for-note
with the reference would produce meaningless numbers.
"""


def reference_notes() -> list[Note]:
    """The reference melody as playable notes."""
    notes: list[Note] = []
    start = LEAD_IN
    for midi, seconds in REFERENCE_MELODY:
        notes.append(
            Note(
                midi=midi,
                start=start,
                end=start + seconds,
                freq=midi_to_hz(midi),
                confidence=1.0,
                pitch=float(midi),
            )
        )
        start += seconds + GAP
    return notes


@dataclass(frozen=True)
class Step:
    """One thing to sing."""

    key: str
    title: str
    detail: str


STEPS: tuple[Step, ...] = (
    Step("low", "Your lowest comfortable note", "hum it and hold for ~2 seconds"),
    Step("high", "Your highest comfortable note", "hum it and hold for ~2 seconds"),
    Step(
        "scale",
        "Sing the melody back",
        "press l to hear it, then sing it back at whatever pitch suits you",
    ),
)


@dataclass
class Result:
    """What calibration concluded."""

    calibration: Calibration
    pitch_dial: int
    pause_dial: int
    detected: list[str]
    confident: bool
    message: str
    structure_ok: bool = False
    """Whether one note per reference note was heard.

    Separate from `confident`, because they gate different things. Without the
    right count there is nothing to pair up and the dial suggestion is a guess.
    With the right count but a poorly pitched reply, the dials are still sound
    -- the structure was recovered -- and only the accuracy figure is a
    judgement on the singing rather than on the app.
    """

    @property
    def range_semitones(self) -> int:
        low = self.calibration.range_low_midi
        high = self.calibration.range_high_midi
        if low is None or high is None:
            return 0
        return max(0, high - low)


def voiced_midis(
    frames: list[PitchFrame],
    *,
    min_confidence: float = 0.55,
    min_rms: float = 0.006,
) -> np.ndarray:
    """The pitches actually sung, as fractional MIDI numbers."""
    values = [
        hz_to_midi(f.freq)
        for f in frames
        if f.voiced and f.confidence >= min_confidence and f.rms >= min_rms
    ]
    return np.array(values, dtype=float)


def measure_note(frames: list[PitchFrame]) -> int | None:
    """The pitch of a single held note, as a MIDI number.

    The median, not the mean: the start of a note is usually an overshoot
    settling into place, and a mean would drag the answer towards it.
    """
    midis = voiced_midis(frames)
    if midis.size < 3:
        return None
    return int(round(float(np.median(midis))))


def compare_to_reference(
    pitches: list[float], reference: list[int]
) -> tuple[float, int]:
    """(mean absolute error in cents, transposition in semitones).

    The best-fitting transposition is removed first, so the error measures how
    accurately the *shape* was sung rather than which octave it was sung in.
    """
    if not pitches or len(pitches) != len(reference):
        return 0.0, 0
    offsets = [p - r for p, r in zip(pitches, reference)]
    offset = float(np.median(offsets))
    errors = [abs(o - offset) for o in offsets]
    return float(np.mean(errors)) * 100.0, int(round(offset))


def suggest_dials(
    frames: list[PitchFrame], reference: list[int] | None = None
) -> tuple[int, int, list[str], list[float], bool]:
    """Search dial settings for the pair that best recovers the reference tune.

    Returns ``(pitch, pause, names, continuous_pitches, confident)``. Ties are
    broken towards the middle of each dial, because a setting that only works
    at an extreme is one bad take away from being wrong.
    """
    reference = reference or REFERENCE_MIDIS
    best: tuple[tuple, int, int, list[str], list[float]] | None = None

    for pitch in range(SENSITIVITY_MIN, SENSITIVITY_MAX + 1):
        for pause in range(PAUSE_MIN, PAUSE_MAX + 1):
            notes = segment_with_sensitivity(frames, pitch, pause)
            names = [n.name for n in notes]
            pitches = [n.pitch or float(n.midi) for n in notes]

            # Getting the count right comes first: without one note per
            # reference note there is nothing to compare. After that, prefer
            # the setting whose pitches land closest to the tune -- a
            # continuous measure, so near-misses rank above wild ones instead
            # of all being equally "wrong".
            count_error = abs(len(notes) - len(reference))
            accuracy, _ = compare_to_reference(pitches, reference)
            distance_from_middle = abs(pitch - 5) + abs(pause - 5)
            score = (count_error, round(accuracy), distance_from_middle)

            if best is None or score < best[0]:
                best = (score, pitch, pause, names, pitches)

    assert best is not None
    (count_error, accuracy, _), pitch, pause, names, pitches = best
    confident = count_error == 0 and accuracy <= MAX_ACCURACY_CENTS
    return pitch, pause, names, pitches, confident


def calibrate(
    low_frames: list[PitchFrame],
    high_frames: list[PitchFrame],
    scale_frames: list[PitchFrame],
    *,
    measured_at: str | None = None,
) -> Result:
    """Turn three recordings into a profile's settings."""
    low = measure_note(low_frames)
    high = measure_note(high_frames)
    if low is not None and high is not None and low > high:
        low, high = high, low  # sung in the wrong order; harmless to fix

    pitch, pause, detected, pitches, confident = suggest_dials(scale_frames)

    # Measure accuracy with clustering and merging switched off. Those exist to
    # make a transcription readable by pulling nearby pitches together, which
    # is exactly what would launder the error we are trying to report: at a low
    # pitch dial a semitone mistake gets quietly absorbed into its neighbour.
    honest = segment_with_sensitivity(
        scale_frames, pitch, pause, cluster_tolerance=0.0, merge_within=0.0
    )
    honest_pitches = [n.pitch or float(n.midi) for n in honest]
    if len(honest_pitches) != len(REFERENCE_MIDIS):
        honest_pitches = pitches
    accuracy, transpose = compare_to_reference(honest_pitches, REFERENCE_MIDIS)

    report = diagnose_frames(scale_frames)
    midis = voiced_midis(scale_frames)
    tuning = tuning_offset_semitones(midis) * 100.0 if midis.size else 0.0

    structure_ok = len(detected) == SCALE_LENGTH

    # Range, tuning, steadiness and style are measured from the singing itself
    # and do not depend on the melody being matched, so they are always
    # trustworthy. Accuracy and register are comparisons against the reference
    # and mean nothing without one note per reference note to pair up.
    calibration = Calibration(
        range_low_midi=low,
        range_high_midi=high,
        tuning_offset_cents=round(tuning, 1),
        typical_drift_cents=round(report.note_cents_spread, 1),
        glide_fraction=round(report.glide_fraction, 3),
        pitch_accuracy_cents=round(accuracy, 1) if structure_ok else None,
        transpose_semitones=transpose if structure_ok else None,
        measured_at=measured_at,
    )

    if not structure_ok:
        message = (
            f"Heard {len(detected)} notes, but the melody has {SCALE_LENGTH}, "
            "so the dial settings are only a guess. Try again holding each "
            "note longer with a clear gap, or save what was measured anyway."
        )
    elif not confident:
        message = (
            f"The reply was about {accuracy:.0f} cents off the melody, so the "
            "accuracy figure says more about the singing than the app. The "
            "dial settings are still sound — the right number of notes came "
            "through."
        )
    elif low is None or high is None:
        message = "Could not hear the range notes, but the rest was measured."
    else:
        message = (
            f"Range {midi_to_name(low)}–{midi_to_name(high)}, "
            f"dials set to pitch {pitch} and pauses {pause}."
        )

    return Result(
        calibration=calibration,
        pitch_dial=pitch,
        pause_dial=pause,
        detected=detected,
        confident=confident,
        message=message,
        structure_ok=structure_ok,
    )


RANGE_MARGIN_SEMITONES = 7
"""Headroom either side of a measured range, before it constrains detection.

A fifth. Calibration measures a *comfortable* range, not a limit, and a note
sung outside the bounds is not detected at all — so the cost of being too tight
is silence, while the cost of being too loose is only that some octave errors
survive. The asymmetry argues for generosity.
"""

GLOBAL_FMIN = 65.0
GLOBAL_FMAX = 1200.0

MIN_TRUSTED_RANGE_SEMITONES = 5
"""How wide a measured range must be before it is allowed to narrow detection.

Anyone can sing more than a fourth. A range narrower than this means the two
range takes did not capture two different notes — the same note sung twice, or
one of them missed — and constraining the detector around a bad measurement
would make notes vanish rather than merely mis-snap.
"""


def voice_bounds(
    calibration: Calibration, margin: int = RANGE_MARGIN_SEMITONES
) -> tuple[float, float] | None:
    """Detection bounds implied by a measured range, or None if uncalibrated.

    Narrowing the search is the one thing a measured range can do that the
    dials cannot: the dials tune *segmentation*, which runs after pitch
    detection, so they cannot undo an octave error. YIN can only report a
    subharmonic or harmonic that falls inside its search window, so a window
    that stops short of one simply cannot produce it.
    """
    low, high = calibration.range_low_midi, calibration.range_high_midi
    if low is None or high is None:
        return None
    if low > high:
        low, high = high, low

    if high - low < MIN_TRUSTED_RANGE_SEMITONES:
        return None

    fmin = max(GLOBAL_FMIN, midi_to_hz(low - margin))
    fmax = min(GLOBAL_FMAX, midi_to_hz(high + margin))
    return float(fmin), float(fmax)


def describe(calibration: Calibration) -> list[tuple[str, str]]:
    """Human-readable rows for the calibration panel."""
    rows: list[tuple[str, str]] = []

    low, high = calibration.range_low_midi, calibration.range_high_midi
    if low is not None and high is not None:
        rows.append(
            (
                "Range",
                f"{midi_to_name(low)} – {midi_to_name(high)}"
                f"   ({high - low} semitones)",
            )
        )

    cents = calibration.tuning_offset_cents
    if cents is not None:
        if abs(cents) < 10:
            rows.append(("Tuning", "sits on concert pitch"))
        else:
            direction = "sharp" if cents > 0 else "flat"
            rows.append(("Tuning", f"{abs(cents):.0f} cents {direction}"))

    drift = calibration.typical_drift_cents
    if drift is not None:
        steadiness = "very steady" if drift < 15 else (
            "steady" if drift < 30 else "wanders while holding"
        )
        rows.append(("Steadiness", f"{drift:.0f} cents drift — {steadiness}"))

    glide = calibration.glide_fraction
    if glide is not None:
        style = "you slide between notes" if glide > 0.35 else "you step cleanly"
        rows.append(("Style", f"{glide * 100:.0f}% sliding — {style}"))

    accuracy = calibration.pitch_accuracy_cents
    if accuracy is not None:
        grade = "excellent" if accuracy < 20 else (
            "good" if accuracy < 40 else "some notes off"
        )
        rows.append(("Accuracy", f"{accuracy:.0f} cents from the melody — {grade}"))

    transpose = calibration.transpose_semitones
    if transpose is not None:
        if transpose == 0:
            where = "you sang it in the original key"
        else:
            direction = "up" if transpose > 0 else "down"
            octaves, semis = divmod(abs(transpose), 12)
            parts = []
            if octaves:
                parts.append(f"{octaves} octave{'s' if octaves > 1 else ''}")
            if semis:
                parts.append(f"{semis} semitone{'s' if semis > 1 else ''}")
            where = f"you sang it {' and '.join(parts)} {direction}"
        rows.append(("Register", where))

    return rows
