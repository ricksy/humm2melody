"""Ear and voice training.

The app can only transcribe what you actually sang. When every hummed note
lands on the same pitch, no amount of detection tuning helps -- the recording
genuinely does not contain the melody. This is the other half of the problem:
making the voice do what you meant.

Three skills, in order, because each depends on the one before:

1. **Hold** a single pitch steadily. Without this nothing else is measurable.
2. **Match** a pitch you have just heard. This is the skill most people lack.
3. **Move** a known distance between two pitches, which is what a melody is.

Scoring rewards *holding* inside the target, not touching it. A voice that
crosses the right pitch on its way past has not sung the note.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .pitch import PitchFrame, hz_to_midi
from .profiles import Profile

IN_TUNE_CENTS = 35.0
"""How close counts as on the note while training.

Tighter than the 50 cents at which the app would snap to this note: hitting
the edge of a rounding boundary is not the same as singing the note, and
training at the boundary teaches nothing.
"""

HOLD_SECONDS = 1.0
"""How long the pitch must stay in tune for the note to count as sung."""

MIN_CONFIDENCE = 0.55
MIN_RMS = 0.006

MAJOR_STEPS = (0, 2, 4, 5, 7, 9, 11, 12)
"""A major scale: do re mi fa sol la ti do."""

SMOOTHING_FRAMES = 5
"""How many frames the live reading is de-spiked over (about 120 ms).

A *median*, not an average. One bad frame -- an octave flip, a breath, a
consonant -- moves a median not at all but drags a mean a fifth of the way
there. The same reason `segment.py` filters the pitch track before deciding
where notes are.
"""

EASE = 0.35
"""How fast the displayed tip catches up with the de-spiked reading.

Purely cosmetic: it makes the bar glide rather than step. Scoring never sees
it, so a prettier bar cannot flatter your singing.
"""

def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


@dataclass(frozen=True)
class Exercise:
    """A sequence of target pitches to sing, in order."""

    key: str
    title: str
    detail: str
    targets: tuple[int, ...]

    def __len__(self) -> int:
        return len(self.targets)


def comfortable_centre(profile: Profile | None) -> int:
    """The middle of a calibrated range, or middle C when nothing is known.

    Training outside someone's range guarantees failure and teaches them only
    that they are bad at it.
    """
    if profile is not None:
        low = profile.calibration.range_low_midi
        high = profile.calibration.range_high_midi
        if low is not None and high is not None and high > low:
            return (low + high) // 2
    return 60


def build_exercises(profile: Profile | None = None) -> tuple[Exercise, ...]:
    """The three exercises, pitched into this singer's range."""
    centre = comfortable_centre(profile)
    root = centre - 4  # so the scale sits around the middle, not above it

    return (
        Exercise(
            key="hold",
            title="Hold one note",
            detail="Sing the note and keep it steady",
            targets=(centre,),
        ),
        Exercise(
            key="match",
            title="Match the note",
            detail="Listen, then sing the same pitch back",
            targets=(centre, centre + 3, centre - 2, centre + 5, centre - 4),
        ),
        Exercise(
            key="ladder",
            title="Climb the ladder",
            detail="do re mi fa sol la ti do",
            targets=tuple(root + step for step in MAJOR_STEPS),
        ),
    )


def cents_from(target: int, freq: float) -> float:
    """How far a frequency sits from a target note, in cents."""
    if freq <= 0:
        return 0.0
    return (hz_to_midi(freq) - target) * 100.0


@dataclass
class Attempt:
    """One go at one target note, scored as it happens."""

    target: int
    tolerance: float = IN_TUNE_CENTS
    hold_needed: float = HOLD_SECONDS

    voiced: int = 0
    in_tune: int = 0
    best_hold: float = 0.0
    cents: float | None = None
    """The current de-spiked reading, or None before anything was heard."""
    eased: float | None = None
    """The same reading, softened for display only."""

    _run: float = 0.0
    _last_time: float | None = None
    _recent: list[float] = field(default_factory=list)
    history: list[float] = field(default_factory=list)

    def feed(self, frame: PitchFrame) -> None:
        """Take one analysis frame and update the score.

        The frame is de-spiked before it counts. What is scored is therefore
        what the bar showed, which is the point: a green bar followed by a
        zero would teach the singer to distrust the display.
        """
        step = 0.0
        if self._last_time is not None:
            step = max(0.0, frame.time - self._last_time)
        self._last_time = frame.time

        usable = (
            frame.voiced
            and frame.confidence >= MIN_CONFIDENCE
            and frame.rms >= MIN_RMS
        )
        if not usable:
            self._run = 0.0
            self._recent.clear()
            self.cents = None
            self.eased = None
            return

        self._recent.append(cents_from(self.target, frame.freq))
        del self._recent[:-SMOOTHING_FRAMES]

        self.voiced += 1
        offset = _median(self._recent)
        self.cents = offset
        self.eased = (
            offset if self.eased is None else self.eased + (offset - self.eased) * EASE
        )
        self.history.append(offset)

        if abs(offset) <= self.tolerance:
            self.in_tune += 1
            self._run += step
            self.best_hold = max(self.best_hold, self._run)
        else:
            self._run = 0.0

    @property
    def accuracy(self) -> float:
        """Fraction of the sung time that was on the note."""
        return self.in_tune / self.voiced if self.voiced else 0.0

    @property
    def held(self) -> bool:
        return self.best_hold >= self.hold_needed

    @property
    def drift_cents(self) -> float:
        """How far the pitch wandered while singing, ignoring direction."""
        if not self.history:
            return 0.0
        return max(self.history) - min(self.history)

    @property
    def score(self) -> int:
        """0 to 100. Holding is worth more than passing through.

        Accuracy alone would reward a voice that swept across the target, so
        most of the score comes from sustaining it.
        """
        if not self.voiced:
            return 0
        hold = min(1.0, self.best_hold / self.hold_needed) if self.hold_needed else 0.0
        return int(round(100 * (0.35 * self.accuracy + 0.65 * hold)))

    @property
    def stars(self) -> int:
        score = self.score
        if score >= 90:
            return 3
        if score >= 70:
            return 2
        if score >= 45:
            return 1
        return 0

    @property
    def median_cents(self) -> float:
        """Where the voice actually sat, ignoring the excursions."""
        return _median(self.history) if self.history else 0.0

    @property
    def sung_midi(self) -> int:
        """The note that was actually sung, as opposed to the one asked for."""
        return round(self.target + self.median_cents / 100)

    @property
    def verdict(self) -> str:
        if not self.voiced:
            return "Nothing heard — sing a little louder."
        if self.held:
            return "Held it. That is the note."
        median = self.median_cents
        if abs(median) <= self.tolerance:
            return "Right pitch, but it wandered. Try to hold it steady."
        return "Too high — come down." if median > 0 else "Too low — come up."


@dataclass
class Session:
    """Progress through one exercise."""

    exercise: Exercise
    index: int = 0
    scores: dict[int, int] = field(default_factory=dict)

    @property
    def target(self) -> int:
        return self.exercise.targets[min(self.index, len(self.exercise) - 1)]

    @property
    def finished(self) -> bool:
        return self.index >= len(self.exercise)

    def record(self, attempt: Attempt) -> None:
        """Keep the best score for this position, so retrying can only help.

        An attempt with no voice in it is not a bad attempt, it is a
        non-attempt: stopping to cough must not put a zero on the board.
        """
        if not attempt.voiced:
            return
        best = self.scores.get(self.index, 0)
        self.scores[self.index] = max(best, attempt.score)

    def advance(self) -> None:
        self.index = min(self.index + 1, len(self.exercise))

    def back(self) -> None:
        self.index = max(self.index - 1, 0)

    @property
    def total(self) -> int:
        return sum(self.scores.values())

    @property
    def average(self) -> int:
        return int(round(self.total / len(self.scores))) if self.scores else 0
