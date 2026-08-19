"""Demo-mode tests.

The demo recorder backs `--demo` and the documentation captures, so if the
melody stops detecting cleanly the screen captures would quietly start showing
a broken app.
"""

from __future__ import annotations

import numpy as np
import pytest

from humm2melody.audio import METER_FLOOR_DB, meter_level
from humm2melody.demo import DEMO_MELODY, DemoRecorder, synth_hum
from humm2melody.pitch import midi_to_name
from humm2melody.segment import segment_notes

SR = 22050


def drain(recorder: DemoRecorder) -> list:
    """Run a non-realtime recorder to completion and return its frames."""
    recorder.start()
    recorder._worker.join(timeout=30)
    recorder._running = False
    return recorder.frames()


# -- the meter -------------------------------------------------------------


def test_meter_is_empty_at_silence():
    assert meter_level(0.0) == 0.0
    assert meter_level(1e-12) == 0.0


def test_meter_is_full_at_full_scale():
    assert meter_level(1.0) == pytest.approx(1.0)


def test_meter_floor_reads_empty():
    assert meter_level(10 ** (METER_FLOOR_DB / 20)) == pytest.approx(0.0, abs=1e-9)


def test_meter_is_monotonic():
    levels = [meter_level(r) for r in (0.001, 0.01, 0.05, 0.2, 0.5, 1.0)]
    assert levels == sorted(levels)


def test_meter_spreads_normal_humming_across_the_bar():
    """The whole point: quiet-but-audible humming must not sit pinned at 0 or 1."""
    for rms in (0.02, 0.05, 0.15):
        assert 0.05 < meter_level(rms) < 0.95


def test_meter_clamps_above_full_scale():
    assert meter_level(4.0) == 1.0


# -- the synthetic hum -----------------------------------------------------


def test_synth_hum_is_audible_and_unclipped():
    audio = synth_hum()
    assert audio.dtype == np.float32
    assert 0.1 < np.max(np.abs(audio)) <= 1.0


def test_synth_hum_is_deterministic():
    """Captures must be reproducible, so the same seed gives the same audio."""
    assert np.array_equal(synth_hum(seed=7), synth_hum(seed=7))
    assert not np.array_equal(synth_hum(seed=7), synth_hum(seed=8))


def test_synth_hum_starts_quiet():
    """A lead-in of near-silence, so the capture does not open mid-note."""
    audio = synth_hum()
    assert np.max(np.abs(audio[: int(0.25 * SR)])) < 0.05


# -- detection -------------------------------------------------------------


def test_demo_melody_detects_exactly():
    """The capture is only worth publishing if the demo transcribes correctly."""
    notes = segment_notes(drain(DemoRecorder(realtime=False)))
    expected = [midi_to_name(midi) for midi, _ in DEMO_MELODY]
    assert [n.name for n in notes] == expected


def test_demo_repeated_notes_stay_separate():
    """C4 C4 and G4 G4 must not merge — that is what the demo exists to show."""
    notes = segment_notes(drain(DemoRecorder(realtime=False)))
    assert [n.name for n in notes[:4]] == ["C4", "C4", "G4", "G4"]
    assert notes[0].end < notes[1].start


def test_demo_detection_is_confident_and_close_to_pitch():
    notes = segment_notes(drain(DemoRecorder(realtime=False)))
    for note in notes:
        assert note.confidence > 0.8
        assert abs(note.cents_off) < 35


# -- the Recorder interface ------------------------------------------------


def test_demo_recorder_matches_the_recorder_interface():
    from humm2melody.audio import Recorder

    for name in ("start", "stop", "frames", "audio", "latest"):
        assert callable(getattr(DemoRecorder, name))
    for name in ("running", "overflows"):
        assert hasattr(DemoRecorder, name)
    # Same constructor keywords the app relies on.
    assert DemoRecorder().sample_rate == Recorder().sample_rate


def test_demo_recorder_reports_captured_audio():
    recorder = DemoRecorder(realtime=False)
    drain(recorder)
    assert recorder.audio().size > SR  # more than a second of it


def test_demo_recorder_starts_and_stops_clean():
    recorder = DemoRecorder(realtime=False)
    assert recorder.running is False
    recorder.start()
    assert recorder.running is True
    recorder.stop()
    assert recorder.running is False


def test_stopping_a_stopped_recorder_is_harmless():
    recorder = DemoRecorder(realtime=False)
    assert recorder.stop() == []


def test_restarting_clears_the_previous_take():
    recorder = DemoRecorder(realtime=False)
    first = len(drain(recorder))
    recorder.start()
    recorder.stop()
    assert first > 0
    assert len(recorder.frames()) < first  # a fresh, much shorter take
