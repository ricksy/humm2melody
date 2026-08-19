"""Segmentation tests, including a full synth-audio -> notes run."""

from __future__ import annotations

import numpy as np
import pytest

from humm2melody.audio import FRAME_SIZE, HOP_SIZE
from humm2melody.pitch import PitchFrame, analyse_signal, midi_to_hz
from humm2melody.segment import segment_notes, segment_with_sensitivity

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


# -- glide gating ----------------------------------------------------------


def legato(targets, hold=0.45, slide=0.12, vibrato=0.18, sr=SR):
    """A sung phrase: hold a pitch, slide to the next, hold again.

    This is what humming actually looks like, as opposed to the step-shaped
    tracks the other tests use. The default slide of 120ms matches how quickly
    a voice actually moves between notes; a much slower portamento is genuinely
    ambiguous, since it is barely faster than a note settling into pitch.
    """
    midi = []
    for i, m in enumerate(targets):
        midi.append(np.full(int(hold * sr), float(m)))
        if i + 1 < len(targets):
            midi.append(np.linspace(m, targets[i + 1], int(slide * sr)))
    midi = np.concatenate(midi)
    t = np.arange(midi.size) / sr
    midi = midi + vibrato * np.sin(2 * np.pi * 5.0 * t)
    phase = 2 * np.pi * np.cumsum(midi_to_hz(midi)) / sr
    wave = 0.4 * (np.sin(phase) + 0.3 * np.sin(2 * phase) + 0.1 * np.sin(3 * phase))
    return wave.astype(np.float32)


def test_legato_hum_never_invents_a_chromatic_run():
    """The original failure: sliding C to E transcribed as every semitone between.

    Two independent mechanisms now prevent it, so check both configurations.
    Without glide gating the region is still one note, because its pitch comes
    from the median of the whole held region rather than from rounding each
    frame; with gating the slide is discarded and the held notes survive.
    """
    audio = analyse(legato([60, 62, 64]))

    ungated = [n.name for n in segment_notes(audio, max_glide_rate=None)]
    assert "C#4" not in ungated and "D#4" not in ungated

    gated = [n.name for n in segment_notes(audio)]
    assert gated == ["C4", "D4", "E4"]


def test_legato_hum_is_transcribed_correctly_with_gating():
    notes = segment_notes(analyse(legato([60, 62, 64])))
    assert [n.name for n in notes] == ["C4", "D4", "E4"]


def test_longer_legato_phrase():
    notes = segment_notes(analyse(legato([60, 62, 64, 65, 67])))
    assert [n.name for n in notes] == ["C4", "D4", "E4", "F4", "G4"]


def test_legato_descending_phrase():
    notes = segment_notes(analyse(legato([67, 65, 64, 62, 60])))
    assert [n.name for n in notes] == ["G4", "F4", "E4", "D4", "C4"]


def test_gating_keeps_deep_vibrato_as_one_note():
    """Vibrato swings faster than a glide; only the median window saves it."""
    notes = segment_notes(analyse(legato([69], hold=0.9, vibrato=0.4)))
    assert [n.name for n in notes] == ["A4"]


def test_gating_does_not_eat_back_to_back_discrete_notes():
    """A step is one event, not a window: adjacent notes must survive."""
    notes = segment_notes(
        track([(261.6, 0.3), (293.7, 0.3), (329.6, 0.3), (349.2, 0.3)])
    )
    assert [n.name for n in notes] == ["C4", "D4", "E4", "F4"]


def test_gating_leaves_well_separated_notes_alone():
    spec: list[tuple[int | None, float]] = []
    for midi in (60, 64, 67):
        spec.append((midi, 0.35))
        spec.append((None, 0.15))
    assert [n.name for n in segment_notes(analyse(synth(spec)))] == ["C4", "E4", "G4"]


def test_a_pure_slide_with_no_held_pitch_yields_little():
    """If nothing is ever held, there are no notes to report."""
    sr = SR
    seconds = 1.6
    t = np.arange(int(seconds * sr)) / sr
    phase = 2 * np.pi * np.cumsum(midi_to_hz(60 + 7 * t / seconds)) / sr
    audio = (0.45 * np.sin(phase)).astype(np.float32)
    assert len(segment_notes(analyse(audio))) <= 2


def test_a_very_slow_portamento_may_merge_into_one_note():
    """A documented limitation, not an accident.

    A one-semitone slide stretched over 180ms moves at about 5.6 semitones/sec,
    which is close to the rate at which a voice settles onto a note it slightly
    overshot. The detector cannot tell those apart from rate alone, so a slide
    that lazy may be absorbed into its neighbour.
    """
    notes = segment_notes(analyse(legato([65, 64], hold=0.5, slide=0.30)))
    assert len(notes) <= 2


def test_even_smoothing_window_does_not_crash():
    """An even median window cannot be centred; it must be coerced, not crash."""
    frames = track([(440.0, 0.5)])
    for size in (2, 4, 6, 8):
        assert [n.name for n in segment_notes(frames, smoothing=size)] == ["A4"]


# -- sensitivity -----------------------------------------------------------


def test_sensitivity_anchors_are_defined():
    from humm2melody.segment import sensitivity_settings

    for level in range(1, 10):
        settings = sensitivity_settings(level)
        assert settings["smoothing"] >= 3
        assert settings["min_duration"] > 0


def test_sensitivity_is_monotonic():
    """Lower levels must be uniformly more forgiving, not a jumble."""
    from humm2melody.segment import sensitivity_settings

    levels = [sensitivity_settings(x) for x in range(1, 10)]
    assert [s["smoothing"] for s in levels] == sorted(
        (s["smoothing"] for s in levels), reverse=True
    )
    assert [s["min_duration"] for s in levels] == sorted(
        (s["min_duration"] for s in levels), reverse=True
    )
    assert [s["cluster_tolerance"] for s in levels] == sorted(
        (s["cluster_tolerance"] for s in levels), reverse=True
    )


def test_sensitivity_is_clamped():
    from humm2melody.segment import sensitivity_settings

    assert sensitivity_settings(-5) == sensitivity_settings(1)
    assert sensitivity_settings(99) == sensitivity_settings(9)


def test_every_sensitivity_level_runs():
    from humm2melody.segment import segment_with_sensitivity

    frames = analyse(legato([60, 62, 64]))
    for level in range(1, 10):
        assert isinstance(segment_with_sensitivity(frames, level), list)


def test_low_sensitivity_unifies_a_wandering_voice():
    """Two attempts at one pitch, landing either side of the rounding line."""
    frames = analyse(legato([60.45, 64.0, 59.6], hold=0.5))
    low = segment_with_sensitivity(frames, 1)
    assert len(low) == 3
    assert low[0].name == low[2].name  # the two outer notes agree


def test_clustering_leaves_genuine_intervals_alone():
    frames = analyse(legato([60, 64, 67], hold=0.5))
    notes = segment_with_sensitivity(frames, 1)
    assert len({n.name for n in notes}) == 3


# -- onsets and the pause dial ---------------------------------------------


def struck(count=3, note=0.35, gap=0.05, midi=64, decay=6.0, sr=SR):
    """Repeated same-pitch notes that decay but never reach silence."""
    out = []
    for _ in range(count):
        t = np.arange(int(note * sr)) / sr
        env = np.exp(-decay * t)
        phase = 2 * np.pi * midi_to_hz(midi) * t
        out.append(0.5 * env * (np.sin(phase) + 0.35 * np.sin(2 * phase)))
        if gap > 0:
            out.append(np.zeros(int(gap * sr)))
    return np.concatenate(out).astype(np.float32)


def test_repeated_notes_need_onsets_not_pitch():
    """Three strikes of one key are a single unbroken pitch."""
    frames = analyse(struck(gap=0.0))
    assert len(segment_with_sensitivity(frames, 5, pause_level=1)) == 1
    assert len(segment_with_sensitivity(frames, 5, pause_level=5)) == 3


def test_repeated_notes_split_across_short_gaps():
    for gap in (0.0, 0.02, 0.05, 0.08, 0.15):
        frames = analyse(struck(gap=gap))
        notes = segment_with_sensitivity(frames, 5, pause_level=7)
        assert len(notes) == 3, f"gap={gap}"
        assert {n.name for n in notes} == {"E4"}


def test_pause_dial_is_monotonic():
    from humm2melody.segment import pause_settings

    levels = [pause_settings(x) for x in range(1, 10)]
    gaps = [s["gap_tolerance"] for s in levels]
    assert gaps == sorted(gaps, reverse=True)


def test_lowest_pause_level_disables_onset_splitting():
    from humm2melody.segment import pause_settings

    assert pause_settings(1)["onset_rise_db"] is None


def test_onset_mask_ignores_a_single_dropped_frame():
    """A one-frame dropout is a detector artefact, not a re-attack."""
    from humm2melody.segment import onset_mask

    rms = np.full(30, 0.2)
    rms[15] = 0.0
    assert not onset_mask(rms, 6.0).any()


def test_onset_mask_finds_a_real_re_attack():
    from humm2melody.segment import onset_mask

    rms = np.concatenate([np.full(10, 0.30), np.full(10, 0.02), np.full(10, 0.30)])
    assert onset_mask(rms, 6.0).any()


def test_onset_mask_is_off_when_disabled():
    from humm2melody.segment import onset_mask

    rms = np.concatenate([np.full(10, 0.3), np.full(10, 0.01), np.full(10, 0.3)])
    assert not onset_mask(rms, None).any()


def test_onsets_do_not_shatter_one_sustained_note():
    frames = analyse(legato([69], hold=1.0, vibrato=0.3))
    assert len(segment_with_sensitivity(frames, 5, pause_level=9)) <= 2


def test_a_separate_attack_survives_pitch_clustering():
    """Clustering rewrites notes; it must not drop the attack that split them."""
    frames = analyse(struck(gap=0.02))
    notes = segment_with_sensitivity(frames, 1, pause_level=7)
    assert len(notes) == 3
