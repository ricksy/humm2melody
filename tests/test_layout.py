"""The interface under stress: too many notes, too little terminal.

Nothing here is about whether the transcription is right -- it is about
whether the app can still be used once the melody is longer, wider or more
extreme than the screen it has to fit on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from humm2melody.pitch import PitchFrame, midi_to_hz
from humm2melody.segment import Note
from humm2melody.tui import (
    MAX_ROLL_ROWS,
    DetailTable,
    MelodySequence,
    PianoKeys,
    PianoRoll,
)

from tests.test_app import SR, make_app, record_once

SIZES = [(80, 24), (100, 30), (120, 40), (156, 50), (200, 60)]


def note(midi: int, start: float, length: float = 0.3) -> Note:
    return Note(
        midi=midi,
        start=start,
        end=start + length,
        freq=midi_to_hz(midi),
        confidence=0.9,
        pitch=float(midi),
    )


def many_notes(count: int) -> list[Note]:
    return [note(48 + (i * 5) % 36, i * 0.4) for i in range(count)]


def humming(count: int, midis=None) -> list[PitchFrame]:
    """A pitch track that segments into `count` notes."""
    frames: list[PitchFrame] = []
    step = 512 / SR
    t = 0.0
    for i in range(count):
        midi = (midis or [55, 60, 64, 67, 72])[i % len(midis or [0] * 5)]
        for _ in range(int(0.3 / step)):
            frames.append(PitchFrame(t, midi_to_hz(midi), 0.95, 0.2))
            t += step
        for _ in range(int(0.15 / step)):
            frames.append(PitchFrame(t, 0.0, 0.0, 0.0))
            t += step
    return frames


def fits(screen) -> bool:
    return (
        screen.virtual_size.height <= screen.region.height
        and screen.virtual_size.width <= screen.region.width
    )


# -- a very long transcription ---------------------------------------------


async def test_a_hundred_notes_still_fit_the_terminal(tmp_path: Path):
    app = make_app(tmp_path, frames=humming(100))
    async with app.run_test(size=(156, 50)) as pilot:
        await record_once(pilot)
        assert len(app.notes) > 80
        assert fits(app.screen)


async def test_a_hundred_notes_do_not_scroll_the_screen_sideways(tmp_path: Path):
    """A horizontal scrollbar on the whole app means something overflowed."""
    app = make_app(tmp_path, frames=humming(100))
    async with app.run_test(size=(120, 40)) as pilot:
        await record_once(pilot)
        assert app.screen.virtual_size.width <= app.screen.region.width


async def test_every_note_of_a_long_take_reaches_the_table(tmp_path: Path):
    """The pane scrolls; it must not silently stop listing them."""
    app = make_app(tmp_path, frames=humming(60))
    async with app.run_test(size=(156, 50)) as pilot:
        await record_once(pilot)
        table = app.query_one("#detail", DetailTable)
        assert table._count == len(app.notes)


async def test_a_long_take_can_still_be_edited_from_the_end(tmp_path: Path):
    """The selection has to survive scrolling past the visible rows."""
    app = make_app(tmp_path, frames=humming(60))
    async with app.run_test(size=(156, 50)) as pilot:
        await record_once(pilot)
        await pilot.press("e")
        for _ in range(len(app.notes) + 5):
            await pilot.press("right")
        await pilot.pause()

        assert app.selected_note == len(app.notes) - 1
        before = app.notes[-1].midi
        await pilot.press("up")
        await pilot.pause()
        assert app.notes[app.selected_note].midi == before + 1


# -- a very small terminal -------------------------------------------------


@pytest.mark.parametrize("size", SIZES)
async def test_the_app_lays_out_at_any_reasonable_size(tmp_path: Path, size):
    app = make_app(tmp_path)
    async with app.run_test(size=size) as pilot:
        await record_once(pilot)

        assert fits(app.screen)
        for selector in ("#roll", "#sequence", "#detail", "#piano", "#play"):
            assert app.query_one(selector).region.width > 0


@pytest.mark.parametrize("size", SIZES)
async def test_a_long_take_lays_out_at_any_reasonable_size(tmp_path: Path, size):
    app = make_app(tmp_path, frames=humming(60))
    async with app.run_test(size=size) as pilot:
        await record_once(pilot)
        assert fits(app.screen)


async def test_the_recording_button_is_reachable_on_a_short_terminal(tmp_path: Path):
    """Three stacked buttons need nine rows; on a short screen they scroll."""
    app = make_app(tmp_path, frames=humming(60))
    async with app.run_test(size=(100, 24)) as pilot:
        await record_once(pilot)
        results = app.query_one("#results")
        toggle = app.query_one("#toggle")
        results.scroll_to_widget(toggle, animate=False)
        await pilot.pause()

        assert toggle.region.height > 0


# -- melodies that span more than the timeline can show --------------------


async def test_the_timeline_caps_how_many_pitch_rows_it_draws(tmp_path: Path):
    """One stray octave must not turn the timeline into the whole screen."""
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        app.notes = [note(24, 0.0), note(60, 0.5), note(108, 1.0)]
        app._show_notes(app.notes)
        await pilot.pause()

        roll = app.query_one("#roll", PianoRoll)
        rows = [line for line in str(roll.content).splitlines() if "│" in line]
        assert 0 < len(rows) <= MAX_ROLL_ROWS


async def test_notes_the_timeline_cannot_show_are_still_listed(tmp_path: Path):
    """Capping the drawing must not amount to dropping notes."""
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        app.notes = [note(24, 0.0), note(60, 0.5), note(108, 1.0)]
        app._show_notes(app.notes)
        await pilot.pause()

        sequence = str(app.query_one("#sequence", MelodySequence).content)
        assert "C1" in sequence and "C8" in sequence
        assert app.query_one("#detail", DetailTable)._count == 3


async def test_the_keyboard_covers_what_the_timeline_had_to_cut(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        app.notes = [note(24, 0.0), note(108, 1.0)]
        app._show_notes(app.notes)
        await pilot.pause()

        piano = app.query_one("#piano", PianoKeys)
        assert piano._low <= 24 and piano._high >= 108


async def test_a_six_octave_melody_still_fits_the_screen(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await record_once(pilot)
        app.notes = [note(24 + i * 6, i * 0.4) for i in range(16)]
        app._show_notes(app.notes)
        await pilot.pause()

        assert fits(app.screen)


# -- notes at the ends of the MIDI range -----------------------------------


@pytest.mark.parametrize("midi", [0, 1, 126, 127])
async def test_a_note_at_the_edge_of_the_midi_range_draws(tmp_path: Path, midi: int):
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        app.notes = [note(midi, 0.0, 0.5)]
        app._show_notes(app.notes)
        await pilot.pause()

        assert str(app.query_one("#roll", PianoRoll).content)
        assert str(app.query_one("#sequence", MelodySequence).content)
        assert app.query_one("#detail", DetailTable)._count == 1
        assert fits(app.screen)


async def test_a_note_cannot_be_transposed_off_the_top_of_the_range(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        await pilot.press("e")
        for _ in range(8):
            await pilot.press("shift+up")
        await pilot.pause()

        assert app.notes[app.selected_note].midi == 127
        assert fits(app.screen)


async def test_a_note_cannot_be_transposed_off_the_bottom_of_the_range(
    tmp_path: Path,
):
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        await pilot.press("e")
        for _ in range(8):
            await pilot.press("shift+down")
        await pilot.pause()

        assert app.notes[app.selected_note].midi == 0
        assert fits(app.screen)


async def test_a_melody_pinned_to_the_top_of_the_range_still_plays(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        await pilot.press("e")
        for _ in range(8):
            await pilot.press("shift+up")
        await pilot.press("p")
        await pilot.pause()

        assert app.player.playing is True


# -- degenerate timings ----------------------------------------------------


async def test_a_zero_length_note_does_not_break_the_timeline(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        app.notes = [note(60, 0.0, 0.0)]
        app._show_notes(app.notes)
        await pilot.pause()

        assert app.is_running
        assert fits(app.screen)


async def test_a_zero_length_note_renders_no_audio_rather_than_crashing(
    tmp_path: Path,
):
    from humm2melody.playback import render

    assert render([note(60, 0.0, 0.0)], SR).size > 0


async def test_a_very_long_recording_gets_a_readable_time_axis(tmp_path: Path):
    """Twelve minutes is past the last tick spacing in the table."""
    from humm2melody.tui import _tick_step

    for span in (0.4, 12.0, 300.0, 800.0, 10_000.0):
        step = _tick_step(span)
        assert step > 0
        assert span / step <= 100  # still a countable number of ticks


async def test_an_hour_long_take_still_draws_its_timeline(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        app.notes = [note(60, 0.0, 1.0), note(64, 3500.0, 1.0)]
        app._show_notes(app.notes)
        await pilot.pause()

        assert "s" in str(app.query_one("#roll", PianoRoll).content)
        assert fits(app.screen)


# -- the longest spellings -------------------------------------------------


async def test_a_long_take_in_solfege_still_fits(tmp_path: Path):
    """Solfège and Sargam spell notes longer than English does."""
    app = make_app(tmp_path, frames=humming(60))
    async with app.run_test(size=(100, 30)) as pilot:
        await record_once(pilot)
        for _ in range(2):  # english -> german -> solfege
            await pilot.press("n")
        await pilot.pause()

        assert fits(app.screen)
        pane = app.query_one("#detail-pane")
        assert app.query_one("#detail").region.width <= pane.region.width
