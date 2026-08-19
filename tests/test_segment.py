"""Segmentation tests, including a full synth-audio -> notes run."""

from __future__ import annotations

import numpy as np
import pytest

from humm2melody.audio import FRAME_SIZE, HOP_SIZE
from humm2melody.pitch import PitchFrame, analyse_signal, midi_to_hz
from humm2melody.segment import segment_notes

SR = 22050
STEP = HOP_SIZE / SR  # seconds between analysis frames


def track(spec: list[tuple[float | None, float]]) -> list[PitchFrame]:
    """Build a pitch track from (freq_or_None, seconds) pairs."""
    frames: list[PitchFrame] = []
    t = 0.0
    for freq, seconds in spec:
        for _ in range(int(round(seconds / STEP))):
            if freq is None:
                frames.append(PitchFrame(t, 0.0, 0.0, 0.0))
            else:
                frames.append(PitchFrame(t, freq, 0.95, 0.2))
            t += STEP
    return frames


def synth(
    spec: list[tuple[int | None, float]], sr: int = SR, detune: float = 0.0
) -> np.ndarray:
    """Render (midi_or_None, seconds) pairs into a voice-like waveform.

    `detune` shifts every note by that many semitones, for simulating a
    performance that sits off the equal-tempered grid.
    """
    parts = []
    for midi, seconds in spec:
        t = np.arange(int(seconds * sr)) / sr
        if midi is None:
            parts.append(np.zeros_like(t))
            continue
        freq = midi_to_hz(midi + detune)
        wave = sum(np.sin(2 * np.pi * freq * h * t) / h for h in (1, 2, 3, 4))
        wave = wave / np.max(np.abs(wave)) * 0.5
        # Short fades so note edges don't click.
        fade = min(int(0.005 * sr), len(wave) // 2)
        if fade:
            wave[:fade] *= np.linspace(0, 1, fade)
            wave[-fade:] *= np.linspace(1, 0, fade)
        parts.append(wave)
    return np.concatenate(parts).astype(np.float32)


def analyse(audio: np.ndarray, sr: int = SR) -> list[PitchFrame]:
    """The same sliding-window loop the recorder uses, without the microphone."""
    return analyse_signal(audio, sr, frame_size=FRAME_SIZE, hop_size=HOP_SIZE)


def test_empty_input():
    assert segment_notes([]) == []


def test_single_sustained_note():
    notes = segment_notes(track([(440.0, 0.5)]))
    assert [n.name for n in notes] == ["A4"]
    assert notes[0].duration == pytest.approx(0.5, abs=0.05)


def test_sequence_of_notes():
    notes = segment_notes(
        track([(261.6, 0.3), (293.7, 0.3), (329.6, 0.3), (349.2, 0.3)])
    )
    assert [n.name for n in notes] == ["C4", "D4", "E4", "F4"]


def test_notes_are_ordered_and_do_not_overlap():
    notes = segment_notes(track([(261.6, 0.3), (329.6, 0.3), (392.0, 0.3)]))
    for a, b in zip(notes, notes[1:]):
        assert a.end <= b.start + 1e-9


def test_silence_separates_repeated_pitches():
    notes = segment_notes(track([(440.0, 0.3), (None, 0.3), (440.0, 0.3)]))
    assert [n.name for n in notes] == ["A4", "A4"]


def test_brief_dropout_does_not_split_a_note():
    notes = segment_notes(track([(440.0, 0.3), (None, 0.03), (440.0, 0.3)]))
    assert [n.name for n in notes] == ["A4"]


def test_short_blips_are_discarded():
    notes = segment_notes(track([(440.0, 0.3), (880.0, 0.02), (440.0, 0.3)]))
    assert [n.name for n in notes] == ["A4"]


def test_single_frame_octave_slip_is_smoothed_away():
    """One bad frame in the middle of a note must not become a note."""
    spec = [(440.0, 0.3), (880.0, STEP), (440.0, 0.3)]
    assert [n.name for n in segment_notes(track(spec))] == ["A4"]


def test_low_confidence_frames_are_ignored():
    frames = [PitchFrame(i * STEP, 440.0, 0.2, 0.2) for i in range(30)]
    assert segment_notes(frames) == []


def test_quiet_frames_are_ignored():
    frames = [PitchFrame(i * STEP, 440.0, 0.95, 0.0001) for i in range(30)]
    assert segment_notes(frames) == []


def test_vibrato_stays_one_note():
    """±40 cents of wobble should snap to a single semitone."""
    frames = []
    for i in range(int(0.6 / STEP)):
        wobble = 440.0 * 2 ** (0.4 * np.sin(2 * np.pi * 5 * i * STEP) / 12)
        frames.append(PitchFrame(i * STEP, wobble, 0.95, 0.2))
    assert [n.name for n in segment_notes(frames)] == ["A4"]


def test_cents_off_is_reported():
    notes = segment_notes(track([(450.0, 0.4)]))  # ~39 cents sharp of A4
    assert notes[0].name == "A4"
    assert 30 < notes[0].cents_off < 45


def test_end_to_end_melody_from_synthesised_audio():
    """The real path: waveform -> YIN -> segmentation -> notes."""
    melody = [60, 62, 64, 65, 67]  # C4 D4 E4 F4 G4
    spec: list[tuple[int | None, float]] = [(None, 0.1)]
    for midi in melody:
        spec.append((midi, 0.35))
        spec.append((None, 0.12))

    notes = segment_notes(analyse(synth(spec)))
    assert [n.name for n in notes] == ["C4", "D4", "E4", "F4", "G4"]
    for note in notes:
        assert note.duration == pytest.approx(0.35, abs=0.1)
        assert abs(note.cents_off) < 20

    starts = [n.start for n in notes]
    assert starts == sorted(starts)


def test_end_to_end_repeated_note_with_gap():
    spec: list[tuple[int | None, float]] = [
        (67, 0.3),
        (None, 0.15),
        (67, 0.3),
        (None, 0.15),
        (64, 0.3),
    ]
    notes = segment_notes(analyse(synth(spec)))
    assert [n.name for n in notes] == ["G4", "G4", "E4"]
