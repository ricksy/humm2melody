"""Pitch detection and note-conversion tests. No microphone required."""

from __future__ import annotations

import math

import numpy as np
import pytest

from humm2melody.pitch import (
    detect_pitch,
    hz_to_midi,
    hz_to_note,
    midi_to_hz,
    midi_to_name,
    rms,
)

SR = 22050


def tone(freq: float, seconds: float = 0.1, harmonics: int = 1, sr: int = SR):
    """A tone with optional harmonics, roughly voice-shaped."""
    t = np.arange(int(seconds * sr)) / sr
    wave = np.zeros_like(t)
    for h in range(1, harmonics + 1):
        wave += np.sin(2 * np.pi * freq * h * t) / h
    return (wave / np.max(np.abs(wave))).astype(np.float32)


@pytest.mark.parametrize("freq", [82.4, 130.8, 220.0, 261.6, 440.0, 587.3, 880.0])
def test_detects_pure_tones(freq):
    detected, confidence = detect_pitch(tone(freq, 0.15), SR)
    assert detected == pytest.approx(freq, rel=0.01)
    assert confidence > 0.8


@pytest.mark.parametrize("freq", [110.0, 196.0, 329.6, 523.3])
def test_detects_harmonic_rich_tones(freq):
    """A hum is far from a sine; the first-dip rule must not pick a harmonic."""
    detected, confidence = detect_pitch(tone(freq, 0.15, harmonics=6), SR)
    assert detected == pytest.approx(freq, rel=0.01)
    assert confidence > 0.7


def test_missing_fundamental_still_reads_as_the_fundamental():
    """Harmonics 2..5 only — the perceived pitch is still the absent f0."""
    t = np.arange(int(0.15 * SR)) / SR
    wave = sum(np.sin(2 * np.pi * 200.0 * h * t) for h in (2, 3, 4, 5))
    detected, _ = detect_pitch((wave / np.max(np.abs(wave))).astype(np.float32), SR)
    assert detected == pytest.approx(200.0, rel=0.02)


def test_silence_and_noise_are_not_confidently_pitched():
    silence = np.zeros(2048, dtype=np.float32)
    freq, confidence = detect_pitch(silence, SR)
    assert freq == 0.0 or confidence < 0.5

    rng = np.random.default_rng(0)
    noise = rng.standard_normal(2048).astype(np.float32)
    _, confidence = detect_pitch(noise, SR)
    assert confidence < 0.6


@pytest.mark.parametrize("freq", [2500.0, 1800.0, 40.0, 25.0])
def test_never_reports_outside_its_declared_range(freq):
    """Out-of-range input may alias onto a sub/harmonic, but the reported value
    always stays inside [fmin, fmax] — never the true out-of-range pitch."""
    detected, _ = detect_pitch(tone(freq, 0.2), SR)
    assert detected == 0.0 or 65.0 <= detected <= 1200.0
    assert detected != pytest.approx(freq, rel=0.01)


def test_dc_offset_does_not_break_detection():
    signal = tone(220.0, 0.15) + 0.5
    detected, _ = detect_pitch(signal, SR)
    assert detected == pytest.approx(220.0, rel=0.01)


def test_frequency_resolution_is_sub_semitone():
    """Parabolic interpolation should land well inside a semitone."""
    for freq in (277.2, 415.3, 466.2):
        detected, _ = detect_pitch(tone(freq, 0.15), SR)
        cents = abs(1200 * math.log2(detected / freq))
        assert cents < 15


def test_midi_conversions_round_trip():
    for midi in range(36, 85):
        assert hz_to_midi(midi_to_hz(midi)) == pytest.approx(midi, abs=1e-9)


def test_note_naming():
    assert midi_to_name(60) == "C4"
    assert midi_to_name(69) == "A4"
    assert midi_to_name(61) == "C#4"
    assert midi_to_name(21) == "A0"


def test_hz_to_note_reports_cents():
    midi, name, cents = hz_to_note(440.0)
    assert (midi, name) == (69, "A4")
    assert cents == pytest.approx(0.0, abs=0.01)

    _, name, cents = hz_to_note(450.0)  # ~39 cents sharp of A4
    assert name == "A4"
    assert 30 < cents < 45

    # Just past the midpoint it belongs to the next semitone down, not A4.
    _, name, cents = hz_to_note(453.0)
    assert name == "A#4"
    assert -50 < cents < -40


def test_rms():
    assert rms(np.zeros(100)) == 0.0
    assert rms(np.ones(100)) == pytest.approx(1.0)
    assert rms(np.array([])) == 0.0
