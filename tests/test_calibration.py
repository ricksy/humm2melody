"""Calibration tests, driven by synthesised voices."""

from __future__ import annotations

import numpy as np
import pytest

from humm2melody.calibration import (
    SCALE_LENGTH,
    STEPS,
    calibrate,
    describe,
    measure_note,
    suggest_dials,
    voiced_midis,
)
from humm2melody.pitch import PitchFrame, midi_to_hz, midi_to_name
from humm2melody.profiles import Calibration

from humm2melody.calibration import REFERENCE_MIDIS, compare_to_reference, reference_notes

from .test_segment import SR, analyse, legato


def held(midi: float, seconds: float = 2.0, vibrato: float = 0.15) -> np.ndarray:
    return legato([midi], hold=seconds, vibrato=vibrato)


def sung_back(
    transpose: float = 0.0, errors=None, hold=0.45, vibrato=0.18, sr=SR
) -> np.ndarray:
    """The reference melody sung back, optionally transposed or misjudged.

    `errors` adds a per-note offset in semitones, for simulating someone who
    gets the shape wrong rather than merely singing in a different key.
    """
    offsets = errors or [0.0] * len(REFERENCE_MIDIS)
    parts = []
    for midi, error in zip(REFERENCE_MIDIS, offsets):
        parts.append(
            legato([midi + transpose + error], hold=hold, vibrato=vibrato, sr=sr)
        )
        parts.append(np.zeros(int(0.18 * sr), dtype=np.float32))
    return np.concatenate(parts).astype(np.float32)


# -- steps -----------------------------------------------------------------


def test_there_are_three_steps():
    assert len(STEPS) == 3
    assert [s.key for s in STEPS] == ["low", "high", "scale"]


def test_the_reference_is_the_familiar_demo_tune():
    assert len(REFERENCE_MIDIS) == SCALE_LENGTH
    assert [n.midi for n in reference_notes()] == REFERENCE_MIDIS


def test_the_reference_is_playable():
    notes = reference_notes()
    assert notes[0].start > 0  # a lead-in, so playback does not clip its own start
    for a, b in zip(notes, notes[1:]):
        assert a.end < b.start  # gaps, so repeated notes stay separable


def test_every_step_explains_itself():
    for step in STEPS:
        assert step.title and step.detail


# -- measuring a single note -----------------------------------------------


@pytest.mark.parametrize("midi", [45, 52, 60, 67])
def test_a_held_note_is_measured(midi):
    assert measure_note(analyse(held(midi))) == midi


def test_a_note_that_settles_is_measured_from_the_median():
    """Voices overshoot then settle; the answer should be where it settled."""
    audio = np.concatenate([held(62, 0.25), held(60, 1.6)])
    assert measure_note(analyse(audio)) == 60


def test_silence_measures_nothing():
    frames = [PitchFrame(i * 0.02, 0.0, 0.0, 0.0) for i in range(60)]
    assert measure_note(frames) is None


def test_too_little_signal_measures_nothing():
    assert measure_note([]) is None


def test_voiced_midis_ignores_gated_frames():
    frames = [
        PitchFrame(0.0, midi_to_hz(60), 0.95, 0.2),
        PitchFrame(0.02, midi_to_hz(60), 0.10, 0.2),  # unconfident
        PitchFrame(0.04, midi_to_hz(60), 0.95, 0.0001),  # too quiet
    ]
    assert voiced_midis(frames).size == 1


# -- choosing the dials ----------------------------------------------------


def test_a_clean_reply_is_recovered_confidently():
    pitch, pause, names, _, confident = suggest_dials(analyse(sung_back()))
    assert confident is True
    assert names == [midi_to_name(m) for m in REFERENCE_MIDIS]
    assert 1 <= pitch <= 9 and 1 <= pause <= 9


def test_the_chosen_dials_actually_reproduce_the_melody():
    """The suggestion has to work when applied, not merely score well."""
    from humm2melody.segment import segment_with_sensitivity

    frames = analyse(sung_back())
    pitch, pause, _, _, _ = suggest_dials(frames)
    notes = segment_with_sensitivity(frames, pitch, pause)
    assert [n.name for n in notes] == [midi_to_name(m) for m in REFERENCE_MIDIS]


def test_a_transposed_reply_is_still_correct():
    """Singing it in a comfortable key is a correct performance."""
    _, _, _, _, confident = suggest_dials(analyse(sung_back(transpose=-5)))
    assert confident is True


def test_an_octave_down_reply_is_still_correct():
    _, _, _, _, confident = suggest_dials(analyse(sung_back(transpose=-12)))
    assert confident is True


def test_a_wrong_shape_is_not_confident():
    """Right number of notes, wrong intervals: that is a real mistake."""
    wrong = [0, 0, -3, -3, 0, 0, 0]
    _, _, _, _, confident = suggest_dials(analyse(sung_back(errors=wrong)))
    assert confident is False


def test_ties_are_broken_towards_the_middle():
    """A setting that only works at an extreme is fragile."""
    pitch, pause, _, _, confident = suggest_dials(analyse(sung_back()))
    assert confident
    assert abs(pitch - 5) <= 3 and abs(pause - 5) <= 3


def test_a_shorter_reply_still_calibrates():
    frames = analyse(sung_back(hold=0.35))
    _, _, names, _, confident = suggest_dials(frames)
    assert confident and len(names) == SCALE_LENGTH


def test_nonsense_is_not_confident():
    """One long note is not the melody, and calibration must say so."""
    _, _, _, _, confident = suggest_dials(analyse(held(60, 3.0)))
    assert confident is False


def test_silence_is_not_confident():
    frames = [PitchFrame(i * 0.02, 0.0, 0.0, 0.0) for i in range(200)]
    assert suggest_dials(frames)[4] is False


# -- the whole run ---------------------------------------------------------


def full_run(low=48, high=67, **kwargs):
    return calibrate(
        analyse(held(low)),
        analyse(held(high)),
        analyse(sung_back(**kwargs)),
        measured_at="2026-08-19T18:00:00",
    )


def test_calibration_measures_the_range():
    result = full_run(low=48, high=67)
    assert result.calibration.range_low_midi == 48
    assert result.calibration.range_high_midi == 67
    assert result.range_semitones == 19


def test_range_notes_sung_in_the_wrong_order_are_corrected():
    """Singing high first should not produce a negative range."""
    result = calibrate(
        analyse(held(67)), analyse(held(48)), analyse(sung_back())
    )
    assert result.calibration.range_low_midi == 48
    assert result.calibration.range_high_midi == 67


def test_calibration_reports_tuning_offset():
    result = full_run()
    assert result.calibration.tuning_offset_cents is not None
    assert abs(result.calibration.tuning_offset_cents) < 50


def test_a_sharp_singer_is_detected():
    result = calibrate(
        analyse(held(48)), analyse(held(67)), analyse(sung_back(transpose=0.35))
    )
    assert result.calibration.tuning_offset_cents == pytest.approx(35, abs=15)


def test_accuracy_is_measured_against_the_melody():
    result = full_run()
    assert result.calibration.pitch_accuracy_cents is not None
    assert result.calibration.pitch_accuracy_cents < 40


def test_the_register_someone_sang_in_is_recorded():
    result = calibrate(
        analyse(held(40)), analyse(held(60)), analyse(sung_back(transpose=-12))
    )
    assert result.confident is True
    assert result.calibration.transpose_semitones == -12


def test_accuracy_is_not_claimed_when_the_take_was_bad():
    """Never report a number derived from a reading we do not trust."""
    result = calibrate(
        analyse(held(48)), analyse(held(67)), analyse(held(60, 3.0))
    )
    assert result.calibration.pitch_accuracy_cents is None
    assert result.calibration.transpose_semitones is None


def test_compare_to_reference_removes_the_transposition():
    pitches = [m - 5.0 for m in REFERENCE_MIDIS]
    error, transpose = compare_to_reference(pitches, REFERENCE_MIDIS)
    assert error == pytest.approx(0.0, abs=1e-6)
    assert transpose == -5


def test_compare_to_reference_measures_real_error():
    pitches = [float(m) for m in REFERENCE_MIDIS]
    pitches[2] += 0.5
    error, _ = compare_to_reference(pitches, REFERENCE_MIDIS)
    assert error > 5


def test_compare_to_reference_of_a_mismatched_length():
    assert compare_to_reference([60.0], REFERENCE_MIDIS) == (0.0, 0)


def test_calibration_records_drift_and_style():
    result = full_run()
    assert result.calibration.typical_drift_cents is not None
    assert result.calibration.glide_fraction is not None


def test_calibration_stores_when_it_was_measured():
    assert full_run().calibration.measured_at == "2026-08-19T18:00:00"


def test_a_good_run_is_confident_and_explains_itself():
    result = full_run()
    assert result.confident is True
    assert "Range" in result.message
    assert "dials" in result.message


def test_a_bad_scale_is_refused_rather_than_guessed():
    """Saving a wrong calibration is worse than saving none."""
    result = calibrate(
        analyse(held(48)), analyse(held(67)), analyse(held(60, 3.0))
    )
    assert result.confident is False
    assert "try again" in result.message.lower()


def test_missing_range_notes_are_refused():
    quiet = [PitchFrame(i * 0.02, 0.0, 0.0, 0.0) for i in range(120)]
    result = calibrate(quiet, quiet, analyse(sung_back()))
    assert result.confident is False


# -- the summary rows ------------------------------------------------------


def test_describe_covers_every_measurement():
    rows = dict(describe(full_run().calibration))
    assert set(rows) == {
        "Range",
        "Tuning",
        "Steadiness",
        "Style",
        "Accuracy",
        "Register",
    }


def test_describe_names_the_register():
    from humm2melody.profiles import Calibration as C

    assert "original key" in dict(describe(C(transpose_semitones=0)))["Register"]
    assert "1 octave" in dict(describe(C(transpose_semitones=-12)))["Register"]
    assert "down" in dict(describe(C(transpose_semitones=-5)))["Register"]


def test_describe_of_nothing_is_empty():
    assert describe(Calibration()) == []


def test_describe_calls_a_centred_voice_on_pitch():
    rows = dict(describe(Calibration(tuning_offset_cents=3.0)))
    assert "concert pitch" in rows["Tuning"]


def test_describe_names_the_direction_of_a_detuned_voice():
    assert "sharp" in dict(describe(Calibration(tuning_offset_cents=40.0)))["Tuning"]
    assert "flat" in dict(describe(Calibration(tuning_offset_cents=-40.0)))["Tuning"]


def test_describe_grades_steadiness():
    assert "very steady" in dict(describe(Calibration(typical_drift_cents=8)))[
        "Steadiness"
    ]
    assert "wanders" in dict(describe(Calibration(typical_drift_cents=45)))[
        "Steadiness"
    ]
