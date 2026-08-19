"""Tests for the offline diagnosis tooling.

This is the tool used to decide *why* a transcription went wrong, so it has to
be trustworthy: a diagnostic that lies is worse than none.
"""

from __future__ import annotations

import numpy as np
import pytest

from humm2melody.analysis import (
    Diagnosis,
    compare,
    diagnose,
    format_report,
    load_run,
    parse_expected,
    sweep,
    tuning_offset_cents,
)
from humm2melody.pitch import hz_to_midi, midi_to_hz

from .test_segment import SR, synth

# -- tuning offset ---------------------------------------------------------


def test_tuning_offset_is_zero_when_on_the_grid():
    midis = np.array([60.0, 62.0, 64.0, 67.0])
    assert tuning_offset_cents(midis) == pytest.approx(0.0, abs=0.5)


def test_tuning_offset_detects_a_consistent_sharpness():
    midis = np.array([60.3, 62.3, 64.3, 67.3])
    assert tuning_offset_cents(midis) == pytest.approx(30.0, abs=1.0)


def test_tuning_offset_detects_a_consistent_flatness():
    midis = np.array([60.0, 62.0, 64.0, 67.0]) - 0.25
    assert tuning_offset_cents(midis) == pytest.approx(-25.0, abs=1.0)


def test_tuning_offset_wraps_correctly():
    """+49 and -49 cents are 2 cents apart, not 98 — a plain mean gets this wrong."""
    midis = np.array([60.49, 61.51, 62.49, 63.51])
    offset = tuning_offset_cents(midis)
    assert abs(offset) > 45  # near the boundary, either sign
    plain_mean = np.mean(((midis + 0.5) % 1 - 0.5)) * 100
    assert abs(plain_mean) < 5  # the naive answer would say "in tune"


def test_tuning_offset_of_nothing_is_zero():
    assert tuning_offset_cents(np.array([])) == 0.0


# -- comparing transcriptions ----------------------------------------------


def test_compare_exact_match():
    distance, verdict = compare(["C4", "D4"], ["C4", "D4"])
    assert distance == 0
    assert "exact" in verdict


def test_compare_spots_a_transposition():
    """Humming in a comfortable key is a correct transcription, not an error."""
    distance, verdict = compare(["G3", "A3", "B3"], ["C4", "D4", "E4"])
    assert "intervals match" in verdict
    assert "-5 semitones" in verdict


def test_compare_reports_edits_for_a_wrong_melody():
    distance, verdict = compare(["C4", "E4", "G4"], ["C4", "D4", "E4"])
    assert distance > 0
    assert "intervals match" not in verdict


def test_compare_handles_missing_and_extra_notes():
    assert compare(["C4"], ["C4", "D4", "E4"])[0] == 2
    assert compare(["C4", "D4", "E4", "F4"], ["C4", "D4", "E4"])[0] == 1


def test_parse_expected_accepts_spaces_and_commas():
    assert parse_expected("C4 D4 E4") == ["C4", "D4", "E4"]
    assert parse_expected("C4,D4,E4") == ["C4", "D4", "E4"]
    assert parse_expected("  C#4  Db5 ") == ["C#4", "Db5"]


# -- diagnosis -------------------------------------------------------------


def clean_melody() -> np.ndarray:
    spec = [(None, 0.1)]
    for midi in (60, 62, 64):
        spec.append((midi, 0.4))
        spec.append((None, 0.15))
    return synth(spec)


def test_diagnose_transcribes_and_measures():
    report = diagnose(clean_melody(), SR)
    assert report.sequence == ["C4", "D4", "E4"]
    assert report.frame_count > 0
    assert 0.0 < report.voiced_fraction < 1.0
    assert report.duration == pytest.approx(1.75, abs=0.1)


def test_diagnose_reports_the_pitch_range():
    report = diagnose(clean_melody(), SR)
    assert report.f0_low == pytest.approx(midi_to_hz(60), rel=0.03)
    assert report.f0_high == pytest.approx(midi_to_hz(64), rel=0.03)


def test_diagnose_finds_no_octave_jumps_in_a_clean_melody():
    assert diagnose(clean_melody(), SR).octave_jumps == 0


def test_diagnose_flags_a_detuned_performance():
    """Everything sung 40 cents sharp should be reported, not silently rounded."""
    spec = [(None, 0.1)]
    for midi in (60, 62, 64):
        spec.append((midi, 0.4))
        spec.append((None, 0.15))
    audio = synth(spec, detune=0.40)
    report = diagnose(audio, SR)
    assert report.tuning_offset_cents == pytest.approx(40, abs=12)


def test_diagnose_flags_a_glide():
    """A continuous slide should show a high gliding fraction."""
    seconds = 1.5
    t = np.arange(int(seconds * SR)) / SR
    midi = 60 + 7 * (t / seconds)  # slide a fifth, continuously
    freq = midi_to_hz(midi)
    phase = 2 * np.pi * np.cumsum(freq) / SR
    audio = (0.5 * np.sin(phase)).astype(np.float32)

    report = diagnose(audio, SR)
    assert report.glide_fraction > 0.5


def test_diagnose_of_silence_does_not_crash():
    report = diagnose(np.zeros(SR, dtype=np.float32), SR)
    assert report.notes == []
    assert report.voiced_count == 0


def test_diagnose_of_empty_audio_does_not_crash():
    report = diagnose(np.zeros(0, dtype=np.float32), SR)
    assert report.frame_count == 0
    assert report.sequence == []


def test_quiet_recording_is_flagged_in_the_report():
    quiet = clean_melody() * 0.004
    text = format_report(diagnose(quiet, SR, min_rms=0.0))
    assert "very quiet" in text


# -- report rendering ------------------------------------------------------


def test_report_is_readable_text():
    text = format_report(diagnose(clean_melody(), SR))
    for heading in ("recording", "level and confidence", "pitch", "transcription"):
        assert heading in text
    assert "C4 D4 E4" in text


def test_report_includes_the_verdict_when_expected_is_given():
    text = format_report(diagnose(clean_melody(), SR), ["C4", "D4", "E4"])
    assert "exact match" in text


def test_report_of_an_empty_diagnosis():
    assert "0 notes" in format_report(Diagnosis())


# -- parameter sweep -------------------------------------------------------


def test_sweep_finds_a_perfect_setting_for_a_clean_melody():
    results = sweep(clean_melody(), SR, ["C4", "D4", "E4"])
    assert results[0][0] == 0
    assert results[0][2] == ["C4", "D4", "E4"]


def test_sweep_is_ranked_best_first():
    results = sweep(clean_melody(), SR, ["C4", "D4", "E4"])
    assert [r[0] for r in results] == sorted(r[0] for r in results)


def test_sweep_returns_the_parameters_that_were_used():
    _, params, _ = sweep(clean_melody(), SR, ["C4", "D4", "E4"])[0]
    assert set(params) == {
        "min_confidence",
        "min_rms",
        "min_duration",
        "smoothing",
        "gap_tolerance",
    }


# -- loading ---------------------------------------------------------------


def test_load_run_reads_a_run_directory(tmp_path):
    from humm2melody.sessions import write_wav

    (tmp_path / "hum.wav").write_bytes(b"")
    write_wav(tmp_path / "hum.wav", clean_melody(), SR)
    audio, rate = load_run(tmp_path)
    assert rate == SR
    assert audio.size > 0


def test_load_run_reads_a_bare_wav(tmp_path):
    from humm2melody.sessions import write_wav

    write_wav(tmp_path / "x.wav", clean_melody(), SR)
    audio, rate = load_run(tmp_path / "x.wav")
    assert rate == SR


def test_load_run_errors_clearly_when_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_run(tmp_path)
