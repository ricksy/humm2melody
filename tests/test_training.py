"""Training logic. Driven by synthesised pitch tracks, no microphone."""

from __future__ import annotations

import pytest

from humm2melody.pitch import PitchFrame, midi_to_hz
from humm2melody.profiles import Calibration, Profile
from humm2melody.training import (
    HOLD_SECONDS,
    IN_TUNE_CENTS,
    Attempt,
    Session,
    build_exercises,
    cents_from,
    comfortable_centre,
)

STEP = 512 / 22050


def sing(attempt: Attempt, cents_off: float, seconds: float, quiet: bool = False):
    """Feed a steady pitch at a fixed distance from the target."""
    t = attempt._last_time or 0.0
    for _ in range(int(seconds / STEP)):
        t += STEP
        freq = midi_to_hz(attempt.target + cents_off / 100.0)
        attempt.feed(
            PitchFrame(t, 0.0 if quiet else freq, 0.0 if quiet else 0.95,
                       0.0 if quiet else 0.2)
        )
    return attempt


# -- exercises -------------------------------------------------------------


def test_there_are_three_exercises_in_order():
    keys = [e.key for e in build_exercises()]
    assert keys == ["hold", "match", "ladder"]


def test_the_ladder_is_a_major_scale():
    ladder = build_exercises()[2]
    intervals = [b - a for a, b in zip(ladder.targets, ladder.targets[1:])]
    assert intervals == [2, 2, 1, 2, 2, 2, 1]


def test_exercises_sit_in_a_calibrated_range():
    """Training outside someone's range only teaches them to fail."""
    profile = Profile(name="A", calibration=Calibration(range_low_midi=47,
                                                        range_high_midi=66))
    centre = comfortable_centre(profile)
    assert 47 <= centre <= 66
    for exercise in build_exercises(profile):
        for target in exercise.targets:
            assert 47 - 6 <= target <= 66 + 6


def test_an_uncalibrated_profile_falls_back_to_middle_c():
    assert comfortable_centre(None) == 60
    assert comfortable_centre(Profile(name="A")) == 60


def test_a_backwards_range_does_not_break_the_centre():
    profile = Profile(name="A", calibration=Calibration(range_low_midi=66,
                                                        range_high_midi=47))
    assert comfortable_centre(profile) == 60


# -- measuring one attempt -------------------------------------------------


def test_cents_from_is_signed():
    assert cents_from(60, midi_to_hz(60)) == pytest.approx(0.0, abs=0.01)
    assert cents_from(60, midi_to_hz(60.5)) == pytest.approx(50.0, abs=0.5)
    assert cents_from(60, midi_to_hz(59.5)) == pytest.approx(-50.0, abs=0.5)
    assert cents_from(60, 0.0) == 0.0


def test_a_steady_note_on_pitch_scores_full_marks():
    attempt = sing(Attempt(target=60), cents_off=0, seconds=2.0)
    assert attempt.held is True
    assert attempt.accuracy == pytest.approx(1.0)
    assert attempt.score >= 95
    assert attempt.stars == 3


def test_a_note_just_outside_tolerance_scores_nothing():
    attempt = sing(Attempt(target=60), cents_off=IN_TUNE_CENTS + 10, seconds=2.0)
    assert attempt.held is False
    assert attempt.accuracy == 0.0
    assert attempt.score == 0


def test_touching_the_note_scores_far_less_than_holding_it():
    """A voice sweeping past the target has not sung it."""
    passing = Attempt(target=60)
    sing(passing, cents_off=200, seconds=0.6)
    sing(passing, cents_off=0, seconds=0.25)      # a brief brush past
    sing(passing, cents_off=-200, seconds=0.6)

    holding = sing(Attempt(target=60), cents_off=0, seconds=1.5)
    assert passing.score < holding.score / 2


def test_silence_scores_zero_and_says_so():
    attempt = sing(Attempt(target=60), cents_off=0, seconds=1.5, quiet=True)
    assert attempt.voiced == 0
    assert attempt.score == 0
    assert "louder" in attempt.verdict


def test_the_verdict_names_the_direction():
    assert "Too high" in sing(Attempt(target=60), 150, 1.0).verdict
    assert "Too low" in sing(Attempt(target=60), -150, 1.0).verdict


def test_the_verdict_distinguishes_wandering_from_being_off():
    """Right pitch but unsteady needs different advice than wrong pitch."""
    wobbly = Attempt(target=60)
    for _ in range(6):
        sing(wobbly, cents_off=20, seconds=0.15)
        sing(wobbly, cents_off=-60, seconds=0.15)
    assert "wandered" in wobbly.verdict or "steady" in wobbly.verdict


def test_a_broken_hold_does_not_count():
    """The run resets when the pitch leaves the target."""
    attempt = Attempt(target=60)
    sing(attempt, 0, HOLD_SECONDS * 0.6)
    sing(attempt, 300, 0.2)
    sing(attempt, 0, HOLD_SECONDS * 0.6)
    assert attempt.held is False


def test_a_gap_in_the_voice_breaks_the_hold():
    attempt = Attempt(target=60)
    sing(attempt, 0, 0.6)
    sing(attempt, 0, 0.2, quiet=True)
    sing(attempt, 0, 0.6)
    assert attempt.held is False


def test_drift_measures_the_spread():
    attempt = Attempt(target=60)
    sing(attempt, 10, 0.5)
    sing(attempt, -20, 0.5)
    assert attempt.drift_cents == pytest.approx(30, abs=2)


# -- progress through an exercise ------------------------------------------


def test_a_session_walks_the_targets():
    session = Session(exercise=build_exercises()[2])
    first = session.target
    session.advance()
    assert session.target != first
    session.back()
    assert session.target == first


def test_a_session_finishes_at_the_end():
    exercise = build_exercises()[0]
    session = Session(exercise=exercise)
    assert session.finished is False
    session.advance()
    assert session.finished is True


def test_going_back_from_the_first_note_stays_put():
    session = Session(exercise=build_exercises()[2])
    session.back()
    assert session.index == 0


def test_retrying_keeps_the_better_score():
    """Practising again should never make your score worse."""
    session = Session(exercise=build_exercises()[2])
    session.record(sing(Attempt(target=session.target), 0, 2.0))
    good = session.scores[0]

    session.record(sing(Attempt(target=session.target), 400, 1.0))
    assert session.scores[0] == good


def test_the_average_covers_only_what_was_attempted():
    session = Session(exercise=build_exercises()[2])
    session.record(sing(Attempt(target=session.target), 0, 2.0))
    assert session.average == session.scores[0]


def test_an_attempt_with_no_voice_is_not_recorded():
    """Stopping without singing must not count as a failed attempt."""
    session = Session(exercise=build_exercises()[0])
    session.record(Attempt(target=60))
    assert session.scores == {}
