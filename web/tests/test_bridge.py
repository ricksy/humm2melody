"""The browser bridge, exercised without a browser.

`bridge.py` is deliberately pure Python and numpy, which means it runs under
desktop CPython exactly as it runs under Pyodide. That is worth a great deal:
the whole analysis path can be tested here, in the ordinary test suite, and a
browser is only needed for the parts that are genuinely browser-shaped —
getUserMedia, the worklet, and message passing.

If a transcription is wrong, it is wrong here first.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

import bridge
from humm2melody.pitch import midi_to_hz
from humm2melody.playback import render
from humm2melody.segment import Note

HOP = 512
RATE = 22050


def melody(pitches: list[int], length: float = 0.45, gap: float = 0.05) -> np.ndarray:
    """Render a known sequence at the analysis rate."""
    notes, at = [], 0.0
    for midi in pitches:
        notes.append(
            Note(midi=midi, start=at, end=at + length,
                 freq=midi_to_hz(midi), confidence=0.95)
        )
        at += length + gap
    return render(notes, sample_rate=RATE)


def feed(audio: np.ndarray) -> list[dict]:
    """Push audio through in hops, as the worklet does."""
    readings = []
    for start in range(0, len(audio) - HOP, HOP):
        out = bridge.push(audio[start : start + HOP])
        if out:
            readings.append(json.loads(out))
    return readings


@pytest.fixture(autouse=True)
def fresh() -> None:
    bridge.start(RATE)


def test_start_reports_the_analysis_configuration() -> None:
    config = json.loads(bridge.start(RATE))
    assert config["sampleRate"] == RATE
    assert config["hopSize"] == HOP
    assert config["resampling"] is False
    assert config["targetFps"] == pytest.approx(43.07, abs=0.01)


def test_no_reading_until_the_window_is_full() -> None:
    # 2048-sample window, 512-sample hops: nothing until the fourth block.
    audio = melody([60])
    assert bridge.push(audio[:HOP]) is None
    assert bridge.push(audio[HOP : 2 * HOP]) is None
    assert bridge.push(audio[2 * HOP : 3 * HOP]) is None
    assert bridge.push(audio[3 * HOP : 4 * HOP]) is not None


def test_recovers_a_known_melody() -> None:
    feed(melody([60, 62, 64, 60]))
    notes = json.loads(bridge.transcribe())
    assert [n["name"] for n in notes] == ["C4", "D4", "E4", "C4"]


def test_repeated_notes_stay_separate() -> None:
    # The case the pause dial exists for: same pitch twice, not one long note.
    feed(melody([67, 67], length=0.4, gap=0.12))
    notes = json.loads(bridge.transcribe())
    assert [n["name"] for n in notes] == ["G4", "G4"]


def test_readings_carry_a_live_note_name() -> None:
    readings = feed(melody([69]))  # A4, 440 Hz
    voiced = [r for r in readings if r["note"]]
    assert voiced, "a pure 440 Hz tone should read as voiced"
    assert voiced[len(voiced) // 2]["note"] == "A4"
    assert abs(voiced[len(voiced) // 2]["freq"] - 440.0) < 2.0


def test_readings_report_their_own_cost() -> None:
    """The spike's whole question: how much of the 23.2 ms hop do we use?"""
    readings = feed(melody([60, 64]))
    assert readings[-1]["analysed"] == len(readings)
    budget_ms = 1000.0 * HOP / RATE
    assert readings[-1]["meanAnalysisMs"] < budget_ms, (
        "analysis is slower than real time even on CPython; Pyodide will be worse"
    )


def test_resampling_path_still_transcribes() -> None:
    """Browsers may refuse a 22.05 kHz AudioContext and hand back 48 kHz."""
    bridge.start(48000)
    notes_44 = render(
        [Note(midi=60, start=0.0, end=0.5, freq=midi_to_hz(60), confidence=0.95),
         Note(midi=64, start=0.6, end=1.1, freq=midi_to_hz(64), confidence=0.95)],
        sample_rate=48000,
    )
    feed(notes_44)
    notes = json.loads(bridge.transcribe())
    assert [n["name"] for n in notes] == ["C4", "E4"]


def test_playback_renders_a_buffer_for_webaudio() -> None:
    feed(melody([60, 62]))
    buffer = bridge.playback(rate=44100)
    assert buffer.dtype == np.float32
    assert buffer.size > 44100  # at least a second of audio
    assert np.max(np.abs(buffer)) <= 1.0


def test_playback_can_mix_the_original_hum() -> None:
    feed(melody([60]))
    tones = bridge.playback(rate=44100, mix_level=0)
    mixed = bridge.playback(rate=44100, mix_level=5)
    assert mixed.size == tones.size
    assert not np.array_equal(tones, mixed)


# --- what the views need, all of it sourced from the core package ----------


def test_schemes_match_the_core_naming_module() -> None:
    from humm2melody.naming import SCHEMES

    out = json.loads(bridge.schemes())
    assert [s["key"] for s in out] == [s.key for s in SCHEMES]
    assert [s["label"] for s in out] == [s.label for s in SCHEMES]


def test_spell_range_covers_every_pitch_in_every_scheme() -> None:
    from humm2melody.naming import SCHEMES, spell

    out = json.loads(bridge.spell_range(60, 72))
    assert set(out) == {s.key for s in SCHEMES}
    # JSON object keys are strings; the views index with them as such.
    assert out["english"]["60"] == "C4"
    assert out["solfege"]["60"] == "Do4"
    for scheme in SCHEMES:
        for midi in range(60, 73):
            assert out[scheme.key][str(midi)] == spell(midi, scheme.key)


def test_tempo_table_matches_playback() -> None:
    """The browser must not carry its own copy of the tempo curve."""
    from humm2melody.playback import tempo_speed

    table = json.loads(bridge.tempo_table())
    assert {int(k) for k in table} == set(range(1, 10))
    for level in range(1, 10):
        assert table[str(level)] == pytest.approx(tempo_speed(level))
    assert table["5"] == 1.0


def test_notes_carry_every_spelling_and_the_measured_frequency() -> None:
    feed(melody([69]))  # A4
    note = json.loads(bridge.transcribe())[0]
    assert note["names"]["english"] == "A4"
    assert note["names"]["sargam"] == "Dha4"
    # `freq` is the measured mean (what the detail table shows); `idealFreq`
    # is the snapped pitch. They are close for a pure tone but not identical.
    assert abs(note["freq"] - 440.0) < 3.0
    assert note["idealFreq"] == pytest.approx(440.0)
