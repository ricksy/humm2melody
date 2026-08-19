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


# -- overlay balance -------------------------------------------------------


def test_mix_gains_span_from_hum_to_tones():
    from humm2melody.playback import MIX_MAX, MIX_MIN, mix_gains

    low_hum, low_tone = mix_gains(MIX_MIN)
    high_hum, high_tone = mix_gains(MIX_MAX)
    assert low_hum > low_tone
    assert high_tone > high_hum


def test_mix_gains_are_monotonic():
    from humm2melody.playback import mix_gains

    hums = [mix_gains(n)[0] for n in range(1, 10)]
    tones = [mix_gains(n)[1] for n in range(1, 10)]
    assert hums == sorted(hums, reverse=True)
    assert tones == sorted(tones)


def test_both_sources_stay_audible_at_every_setting():
    """The ends are pulled in so neither source ever drops to nothing."""
    from humm2melody.playback import mix_gains

    for level in range(1, 10):
        hum, tone = mix_gains(level)
        assert hum > 0.05 and tone > 0.05


def test_mix_default_favours_the_voice():
    """A pure tone reads louder than a breathy hum at the same amplitude."""
    from humm2melody.playback import MIX_DEFAULT, mix_gains

    hum, tone = mix_gains(MIX_DEFAULT)
    assert hum > tone


def test_mix_gains_are_clamped():
    from humm2melody.playback import mix_gains

    assert mix_gains(-3) == mix_gains(1)
    assert mix_gains(99) == mix_gains(9)


def test_balance_changes_the_overlay():
    from humm2melody.playback import mix_hum_with_tones

    hum = (0.4 * np.sin(np.arange(SR) * 0.05)).astype(np.float32)
    notes = [note(60, 0.0, 0.5)]
    quiet = mix_hum_with_tones(hum, SR, notes, SR, balance=1)
    loud = mix_hum_with_tones(hum, SR, notes, SR, balance=9)
    assert not np.allclose(quiet, loud)


def test_overlay_never_clips_at_any_balance():
    from humm2melody.playback import mix_hum_with_tones

    hum = np.ones(SR, dtype=np.float32) * 0.9
    notes = [note(60 + i, i * 0.2, i * 0.2 + 0.3) for i in range(5)]
    for level in range(1, 10):
        mixed = mix_hum_with_tones(hum, SR, notes, SR, balance=level)
        assert np.max(np.abs(mixed)) <= 1.0


# -- voices ----------------------------------------------------------------


def test_pure_stacks_nothing():
    from humm2melody.playback import chord_offsets

    assert chord_offsets([note(60, 0, 0.4)], "pure") == {}


def test_rich_adds_the_fifth_and_octave():
    """Consonant against any root, so it cannot be wrong in any key."""
    from humm2melody.playback import chord_offsets

    assert chord_offsets([note(60, 0, 0.4)], "rich")[60] == (7, 12)


def test_chords_take_a_minor_third_from_a_minor_melody():
    from humm2melody.playback import chord_offsets

    melody = [note(60, 0, 0.3), note(63, 0.4, 0.7), note(67, 0.8, 1.1)]
    assert chord_offsets(melody, "chord")[60] == (3, 7)


def test_chords_take_a_major_third_from_a_major_melody():
    from humm2melody.playback import chord_offsets

    melody = [note(60, 0, 0.3), note(64, 0.4, 0.7), note(67, 0.8, 1.1)]
    assert chord_offsets(melody, "chord")[60] == (4, 7)


def test_chords_fall_back_to_major_when_the_melody_says_nothing():
    from humm2melody.playback import chord_offsets

    assert chord_offsets([note(60, 0, 0.4)], "chord")[60] == (4, 7)


def test_a_richer_voice_makes_a_fuller_sound():
    """More partials means more energy above the fundamental."""
    from humm2melody.playback import render

    melody = [note(60, 0.0, 0.6)]
    energy = {}
    for voice in ("pure", "rich", "chord"):
        audio = render(melody, SR, voice=voice)
        spectrum = np.abs(np.fft.rfft(audio[: 2**14]))
        freqs = np.fft.rfftfreq(2**14, 1 / SR)
        energy[voice] = spectrum[(freqs > 350) & (freqs < 900)].sum()
    assert energy["rich"] > energy["pure"]
    assert energy["chord"] > energy["pure"]


def test_every_voice_renders_and_stays_in_range():
    from humm2melody.playback import VOICES, render

    melody = [note(60 + i, i * 0.3, i * 0.3 + 0.25) for i in range(5)]
    for voice in VOICES:
        audio = render(melody, SR, voice=voice)
        assert audio.size > 0
        assert np.max(np.abs(audio)) <= 1.0


def test_the_voice_cycle_returns_to_the_start():
    from humm2melody.playback import VOICES, next_voice

    seen, voice = [], "pure"
    for _ in range(len(VOICES)):
        seen.append(voice)
        voice = next_voice(voice)
    assert seen == list(VOICES)
    assert voice == "pure"


def test_an_unknown_voice_is_survivable():
    from humm2melody.playback import next_voice, render

    assert next_voice("nonsense") == "pure"
    assert render([note(60, 0, 0.4)], SR, voice="nonsense").size > 0


# -- picking a chord out of the melody itself ------------------------------


def test_each_note_gets_the_third_its_own_pitch_class_asks_for():
    """A minor tune is not minor under every root: A minor makes C major."""
    from humm2melody.playback import chord_offsets

    melody = [note(69, 0, 0.3), note(72, 0.4, 0.7), note(76, 0.8, 1.1)]
    stacks = chord_offsets(melody, "chord")
    assert stacks[69] == (3, 7)  # A: C is its minor third
    assert stacks[72] == (4, 7)  # C: E is its major third


def test_an_ambiguous_melody_takes_the_major_third():
    """Both thirds sung against the same root: major is the safer guess."""
    from humm2melody.playback import chord_offsets

    melody = [note(60, 0, 0.3), note(63, 0.4, 0.7), note(64, 0.8, 1.1)]
    assert chord_offsets(melody, "chord")[60] == (4, 7)


def test_an_atonal_melody_still_produces_a_chord_for_every_note():
    """A chromatic run makes both thirds available to every root."""
    from humm2melody.playback import chord_offsets

    melody = [note(60 + i, i * 0.2, i * 0.2 + 0.15) for i in range(12)]
    stacks = chord_offsets(melody, "chord")
    assert len(stacks) == 12
    assert {offsets for offsets in stacks.values()} == {(4, 7)}


def test_a_single_note_melody_is_harmonised_major():
    """One note cannot say major or minor, and silence is not an option."""
    from humm2melody.playback import chord_offsets

    assert chord_offsets([note(65, 0, 0.5)], "chord") == {65: (4, 7)}


def test_the_third_is_taken_from_any_octave():
    """Pitch class, not interval: an E two octaves up still makes C major."""
    from humm2melody.playback import chord_offsets

    melody = [note(60, 0, 0.3), note(88, 0.4, 0.7)]  # C4 then E6
    assert chord_offsets(melody, "chord")[60] == (4, 7)


def test_the_same_note_in_two_octaves_gets_the_same_chord():
    from humm2melody.playback import chord_offsets

    melody = [note(60, 0, 0.3), note(63, 0.4, 0.7), note(72, 0.8, 1.1)]
    stacks = chord_offsets(melody, "chord")
    assert stacks[60] == stacks[72] == (3, 7)


def test_nothing_is_stacked_on_an_empty_melody():
    from humm2melody.playback import VOICES, chord_offsets

    for voice in VOICES:
        assert chord_offsets([], voice) == {}


def test_a_chord_voice_sounds_the_third_it_chose():
    """The chosen third has to reach the audio, not just the offsets table."""
    from humm2melody.pitch import midi_to_hz
    from humm2melody.playback import render

    minor = [note(60, 0, 0.6), note(63, 0.7, 1.2)]
    audio = render(minor, SR, voice="chord")[: 2**14]
    spectrum = np.abs(np.fft.rfft(audio))
    freqs = np.fft.rfftfreq(2**14, 1 / SR)

    def energy_at(hz: float) -> float:
        return spectrum[(freqs > hz * 0.98) & (freqs < hz * 1.02)].max()

    assert energy_at(midi_to_hz(63)) > energy_at(midi_to_hz(64)) * 3


def test_a_note_at_the_top_of_the_range_does_not_break_a_stacked_voice():
    """Stacking an octave on MIDI 127 asks for a partial past Nyquist."""
    from humm2melody.playback import render

    audio = render([note(127, 0.0, 0.3)], SR, voice="rich")
    assert audio.size > 0
    assert np.all(np.isfinite(audio))
    assert np.max(np.abs(audio)) <= 1.0


def test_a_note_at_the_bottom_of_the_range_still_renders():
    from humm2melody.playback import render

    audio = render([note(0, 0.0, 0.5)], SR, voice="chord")
    assert audio.size > 0
    assert np.all(np.isfinite(audio))


def test_the_voice_reaches_the_hum_overlay():
    """The overlay renders its own tones, so the setting has to be passed on."""
    from humm2melody.playback import mix_hum_with_tones

    hum = (0.2 * np.sin(np.arange(SR) * 0.05)).astype(np.float32)
    melody = [note(60, 0.0, 0.5)]
    plain = mix_hum_with_tones(hum, SR, melody, SR, voice="pure")
    stacked = mix_hum_with_tones(hum, SR, melody, SR, voice="rich")

    assert not np.allclose(plain, stacked)


# -- playing slower or faster ----------------------------------------------


def test_half_speed_takes_twice_as_long():
    from humm2melody.playback import render

    melody = [note(60, 0.0, 0.4), note(64, 0.5, 0.9)]
    normal = render(melody, SR).size - int(TAIL * SR)
    slow = render(melody, SR, speed=0.5).size - int(TAIL * SR)
    assert slow == pytest.approx(normal * 2, rel=0.02)


def test_slowing_a_melody_down_does_not_transpose_it():
    """The point of a tempo dial: half speed to learn it, same notes."""
    from humm2melody.playback import render

    melody = [note(60, 0.0, 0.4), note(64, 0.55, 0.95), note(67, 1.1, 1.5)]
    detected = segment_notes(analyse(render(melody, SR, speed=0.5), SR))
    assert [n.name for n in detected] == ["C4", "E4", "G4"]


def test_speeding_a_melody_up_does_not_transpose_it():
    from humm2melody.playback import render

    melody = [note(60, 0.0, 0.5), note(64, 0.7, 1.2), note(67, 1.4, 1.9)]
    detected = segment_notes(analyse(render(melody, SR, speed=1.7), SR))
    assert [n.name for n in detected] == ["C4", "E4", "G4"]


def test_tempo_levels_run_from_half_speed_to_double():
    from humm2melody.playback import TEMPO_DEFAULT, tempo_speed

    speeds = [tempo_speed(level) for level in range(1, 10)]
    assert speeds == sorted(speeds)
    assert speeds[0] == pytest.approx(0.5)
    assert speeds[-1] == pytest.approx(2.0)
    assert tempo_speed(TEMPO_DEFAULT) == pytest.approx(1.0)


def test_a_tempo_outside_the_dial_is_clamped():
    from humm2melody.playback import tempo_speed

    assert tempo_speed(-5) == tempo_speed(1)
    assert tempo_speed(99) == tempo_speed(9)


def test_speed_keeps_the_gaps_between_notes_silent():
    """Gaps have to scale with the notes, or the melody stops being the melody."""
    from humm2melody.playback import render

    melody = [note(60, 0.0, 0.4), note(64, 1.0, 1.4)]
    audio = render(melody, SR, speed=0.5)
    # The gap at 0.4-1.0s becomes 0.8-2.0s at half speed.
    quiet = audio[int(1.0 * SR) : int(1.8 * SR)]
    assert np.max(np.abs(quiet)) < 0.01
