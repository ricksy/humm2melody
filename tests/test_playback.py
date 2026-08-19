"""Playback rendering tests. Pure numpy — no output device required."""

from __future__ import annotations

import numpy as np
import pytest

from humm2melody.playback import TAIL, render
from humm2melody.segment import Note, segment_notes

from .test_segment import SR, analyse


def note(midi: int, start: float, end: float, freq: float | None = None) -> Note:
    from humm2melody.pitch import midi_to_hz

    return Note(
        midi=midi,
        start=start,
        end=end,
        freq=freq if freq is not None else midi_to_hz(midi),
        confidence=0.9,
    )


def test_empty_melody_renders_nothing():
    assert render([]).size == 0


def test_render_length_covers_melody_plus_tail():
    audio = render([note(60, 0.0, 0.5)], SR)
    assert audio.size / SR == pytest.approx(0.5 + TAIL, abs=0.02)


def test_render_respects_note_timing():
    """Silence before the note starts, sound during it."""
    audio = render([note(60, 0.5, 1.0)], SR)
    assert np.max(np.abs(audio[: int(0.45 * SR)])) < 1e-6
    assert np.max(np.abs(audio[int(0.6 * SR) : int(0.9 * SR)])) > 0.05


def test_gaps_between_notes_are_silent():
    audio = render([note(60, 0.0, 0.3), note(64, 0.6, 0.9)], SR)
    gap = audio[int(0.40 * SR) : int(0.55 * SR)]
    assert np.max(np.abs(gap)) < 1e-3


def test_output_never_clips():
    notes = [note(60 + i, i * 0.1, i * 0.1 + 0.5) for i in range(8)]
    assert np.max(np.abs(render(notes, SR))) <= 1.0


def test_notes_are_played_at_the_snapped_pitch_not_the_hummed_one():
    """A note hummed 40 cents flat must still play back as the note we printed."""
    from humm2melody.pitch import detect_pitch, midi_to_hz

    flat = midi_to_hz(69) * 2 ** (-0.4 / 12)
    audio = render([note(69, 0.0, 0.6, freq=flat)], SR)
    middle = audio[int(0.15 * SR) : int(0.15 * SR) + 2048]
    detected, _ = detect_pitch(middle, SR)
    assert detected == pytest.approx(440.0, rel=0.02)


def test_round_trip_render_then_detect():
    """Render notes to audio, run them back through the detector, get them back."""
    original = [
        note(60, 0.0, 0.4),
        note(62, 0.55, 0.95),
        note(64, 1.1, 1.5),
        note(67, 1.65, 2.15),
    ]
    detected = segment_notes(analyse(render(original, SR), SR))

    assert [n.name for n in detected] == [n.name for n in original]
    for got, want in zip(detected, original):
        assert got.start == pytest.approx(want.start, abs=0.08)
        assert got.duration == pytest.approx(want.duration, abs=0.12)


def test_round_trip_keeps_repeated_notes_separate():
    original = [note(67, 0.0, 0.35), note(67, 0.5, 0.85), note(67, 1.0, 1.35)]
    detected = segment_notes(analyse(render(original, SR), SR))
    assert [n.name for n in detected] == ["G4", "G4", "G4"]


# -- resampling and the hum/tone overlay -----------------------------------


def test_resample_is_a_no_op_at_the_same_rate():
    from humm2melody.playback import resample

    audio = np.sin(np.arange(1000) * 0.1).astype(np.float32)
    assert np.array_equal(resample(audio, SR, SR), audio)


def test_resample_changes_length_proportionally():
    from humm2melody.playback import resample

    audio = np.zeros(1000, dtype=np.float32)
    assert resample(audio, 22050, 44100).size == pytest.approx(2000, abs=2)
    assert resample(audio, 44100, 22050).size == pytest.approx(500, abs=2)


def test_resample_preserves_a_tone():
    """A resampled tone must still read as the same pitch."""
    from humm2melody.pitch import detect_pitch
    from humm2melody.playback import resample

    t = np.arange(22050) / 22050
    tone = np.sin(2 * np.pi * 220.0 * t).astype(np.float32)
    moved = resample(tone, 22050, 48000)
    detected, _ = detect_pitch(moved[8000:10048], 48000)
    assert detected == pytest.approx(220.0, rel=0.02)


def test_resample_of_nothing():
    from humm2melody.playback import resample

    assert resample(np.zeros(0, dtype=np.float32), 22050, 48000).size == 0


def test_overlay_contains_both_sources():
    from humm2melody.playback import mix_hum_with_tones

    hum = (0.3 * np.sin(np.arange(SR) * 0.05)).astype(np.float32)
    mixed = mix_hum_with_tones(hum, SR, [note(60, 0.0, 0.5)], SR)
    assert mixed.size >= hum.size
    assert np.max(np.abs(mixed)) > 0.1


def test_overlay_never_clips():
    from humm2melody.playback import mix_hum_with_tones

    hum = np.ones(SR, dtype=np.float32) * 0.9
    notes = [note(60 + i, i * 0.2, i * 0.2 + 0.3) for i in range(5)]
    assert np.max(np.abs(mix_hum_with_tones(hum, SR, notes, SR))) <= 1.0


def test_overlay_with_no_notes_is_just_the_hum():
    from humm2melody.playback import mix_hum_with_tones

    hum = (0.4 * np.sin(np.arange(SR) * 0.05)).astype(np.float32)
    mixed = mix_hum_with_tones(hum, SR, [], SR)
    assert np.max(np.abs(mixed)) == pytest.approx(0.4 * 0.85, abs=0.02)


def test_overlay_with_no_hum_is_just_the_tones():
    from humm2melody.playback import mix_hum_with_tones

    mixed = mix_hum_with_tones(
        np.zeros(0, dtype=np.float32), SR, [note(60, 0.0, 0.4)], SR
    )
    assert np.max(np.abs(mixed)) > 0.1


def test_player_starts_idle_and_stop_is_idempotent():
    from humm2melody.playback import Player

    player = Player()
    assert player.playing is False
    player.stop()
    player.stop()
    assert player.position == 0.0


def test_playing_nothing_is_a_no_op():
    """Must not open a device for an empty buffer."""
    from humm2melody.playback import Player

    player = Player()
    player.play_audio(np.zeros(0, dtype=np.float32), SR)
    assert player.playing is False
