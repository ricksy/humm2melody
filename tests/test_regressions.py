"""Regressions found by review, each reproducing the reported failure."""

from __future__ import annotations

from pathlib import Path

import pytest

from humm2melody.segment import Note, _merge_adjacent


# -- C1: hand edits were discarded on reload, then overwritten on disk ------


async def test_a_hand_edit_survives_reloading_the_run(tmp_path: Path):
    """Reload used to re-segment, silently undoing the edit.

    Worse, the next flush then wrote the re-segmented notes over it, so the
    edit was destroyed on disk as well as lost from the screen.
    """
    from tests.test_app import make_app

    app = make_app(tmp_path)
    async with app.run_test(size=(150, 60)) as pilot:
        await pilot.press("space")
        await pilot.press("space")
        await pilot.pause()
        original = [n.midi for n in app.notes]

        await pilot.press("e")
        await pilot.press("up")
        await pilot.press("escape")
        await pilot.pause()
        edited = [n.midi for n in app.notes]
        assert edited != original

        app.load_selected_session()
        await pilot.pause()
        assert [n.midi for n in app.notes] == edited

        # A further edit must not write the re-segmented notes back over it.
        await pilot.press("e")
        await pilot.press("up")
        await pilot.press("escape")
        await pilot.pause()
        assert app.store.list()[0].notes[0].midi == app.notes[0].midi


async def test_turning_a_dial_deliberately_re_reads_the_recording(tmp_path: Path):
    """The other half: a dial change *is* a request to read the audio again."""
    from tests.test_app import make_app

    app = make_app(tmp_path)
    async with app.run_test(size=(150, 60)) as pilot:
        await pilot.press("space")
        await pilot.press("space")
        await pilot.pause()

        await pilot.press("e")
        await pilot.press("up")
        await pilot.press("escape")
        await pilot.pause()
        assert app.store.list()[0].edited is True

        await pilot.press("]")
        await pilot.pause()
        assert app.store.list()[0].edited is False


# -- P1: the playhead guard compared a width it had not drawn with ----------


async def test_the_playhead_guard_uses_the_drawn_width(tmp_path: Path):
    """It redrew on ticks that had not moved, and skipped ticks that had."""
    from humm2melody.tui import PianoRoll
    from tests.test_app import make_app

    app = make_app(tmp_path)
    async with app.run_test(size=(150, 60)) as pilot:
        await pilot.press("space")
        await pilot.press("space")
        await pilot.pause()

        roll = app.query_one("#roll", PianoRoll)
        _, _, _, drawn_width, span = roll._geometry

        redraws = 0
        original = roll.refresh_roll

        def counting():
            nonlocal redraws
            redraws += 1
            return original()

        roll.refresh_roll = counting

        # Two positions inside the same character cell must not redraw twice.
        cell = span / drawn_width
        roll.set_playhead(cell * 0.2)
        first = redraws
        roll.set_playhead(cell * 0.6)
        assert redraws == first, "redrew without changing column"

        roll.set_playhead(cell * 1.5)
        assert redraws > first, "skipped a real column change"


# -- C2: merging dropped the continuous pitch and the attack ---------------


def make(midi: int, start: float, end: float, pitch: float, attack: bool) -> Note:
    from humm2melody.pitch import midi_to_hz

    return Note(
        midi=midi,
        start=start,
        end=end,
        freq=midi_to_hz(pitch),
        confidence=0.9,
        pitch=pitch,
        attack=attack,
    )


def test_merging_keeps_the_measured_pitch():
    """A merged note used to report as exactly in tune, whatever was sung.

    calibration reads `n.pitch or float(n.midi)`, so losing it made the
    accuracy figure optimistic and pushed the dial search towards settings
    that merged more -- laundering the very error it was measuring.
    """
    merged = _merge_adjacent(
        [make(60, 0.0, 0.4, 60.42, True), make(60, 0.42, 0.8, 60.38, False)],
        gap_tolerance=0.07,
    )
    assert len(merged) == 1
    assert merged[0].pitch == pytest.approx(60.40, abs=0.02)
    assert merged[0].cents_off != 0.0


def test_merging_keeps_the_first_notes_attack():
    merged = _merge_adjacent(
        [make(60, 0.0, 0.4, 60.0, True), make(60, 0.42, 0.8, 60.0, False)],
        gap_tolerance=0.07,
    )
    assert merged[0].attack is True


def test_merging_falls_back_to_the_measured_frequency():
    """Older notes carry no continuous pitch; the frequency still tells us."""
    from humm2melody.pitch import midi_to_hz

    bare = [
        Note(midi=60, start=0.0, end=0.4, freq=midi_to_hz(60.3), confidence=0.9),
        Note(midi=60, start=0.42, end=0.8, freq=midi_to_hz(60.1), confidence=0.9),
    ]
    merged = _merge_adjacent(bare, gap_tolerance=0.07)
    assert merged[0].pitch == pytest.approx(60.2, abs=0.05)


def test_notes_that_do_not_merge_are_untouched():
    notes = [make(60, 0.0, 0.4, 60.4, True), make(64, 1.0, 1.4, 64.2, True)]
    assert _merge_adjacent(notes, gap_tolerance=0.07) == notes


# -- the timeline used to push the layout apart on a wide melody -----------


def wide_range_take():
    """A melody spanning nearly four octaves, so the roll wants many rows."""
    from humm2melody.pitch import PitchFrame, midi_to_hz

    frames, step, t = [], 512 / 22050, 0.0
    for midi in (36, 84, 40, 79, 45):
        for _ in range(int(0.3 / step)):
            frames.append(PitchFrame(t, midi_to_hz(midi), 0.95, 0.2))
            t += step
        for _ in range(int(0.2 / step)):
            frames.append(PitchFrame(t, 0.0, 0.0, 0.0))
            t += step
    return frames


async def test_a_wide_melody_does_not_push_the_layout_apart(tmp_path: Path):
    """The roll grows a row per semitone; it used to shove the rest off screen."""
    from tests.test_app import make_app

    app = make_app(tmp_path, frames=wide_range_take())
    async with app.run_test(size=(150, 60)) as pilot:
        await pilot.press("space")
        await pilot.press("space")
        await pilot.pause()

        pane = app.query_one("#roll-pane")
        results = app.query_one("#results").region
        last_button = app.query_one("#compare").region

        assert pane.virtual_size.height > pane.region.height, "should scroll"
        assert last_button.y + last_button.height <= results.y + results.height
