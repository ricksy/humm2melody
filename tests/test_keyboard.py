"""The on-screen piano keyboard.

These read the keyboard back out of what it actually drew rather than out of
its geometry variables: the drawn base line ("┴──┴──┴") says where each key
starts and ends, so a click can be aimed the way a user aims one -- at the
middle of a key they can see -- and the hit map is checked against the picture
instead of against the code that produced it.

Everything here runs headless with audio faked out, as in test_app.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from humm2melody.naming import spell
from humm2melody.pitch import midi_to_hz
from humm2melody.segment import Note
from humm2melody.tui import HIGHLIGHT, WHITE_STEPS, PianoKeys

from tests.test_app import _Click, make_app, record_once

BLACK_STEPS = (1, 3, 6, 8, 10)


def note(midi: int, start: float = 0.0, length: float = 0.4) -> Note:
    return Note(
        midi=midi,
        start=start,
        end=start + length,
        freq=midi_to_hz(midi),
        confidence=1.0,
        pitch=float(midi),
    )


def drawn(piano: PianoKeys) -> list[str]:
    """The keyboard as rows of characters, exactly as it was written out."""
    return str(piano.content).splitlines()


def key_spans(piano: PianoKeys) -> list[tuple[int, int]]:
    """First and last *body* column of every white key, read off the base line.

    The base line is the one place the drawing says out loud where one key
    ends and the next begins, so the spans come from there rather than from
    the widget's own idea of its key width.
    """
    base = drawn(piano)[-1]
    edges = [i for i, glyph in enumerate(base) if glyph == "┴"]
    return [(left + 1, right - 1) for left, right in zip(edges, edges[1:])]


def white_click(piano: PianoKeys, index: int) -> _Click:
    """A click in the middle of the nth drawn white key, below the black keys."""
    left, right = key_spans(piano)[index]
    return _Click((left + right) // 2 + 1, piano.BLACK_ROWS + 2)


def black_columns(piano: PianoKeys) -> list[int]:
    """Every column of the top row that has a black key drawn in it."""
    return [i for i, glyph in enumerate(drawn(piano)[0]) if glyph == "█"]


def body_row(piano: PianoKeys) -> int:
    """A white-key row that never carries a label, so it is blank or lit."""
    return piano.BLACK_ROWS + 1


# -- what gets drawn -------------------------------------------------------


async def test_the_keyboard_draws_one_key_per_white_note(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)
        assert len(key_spans(piano)) == len(piano._white_keys())


async def test_an_empty_melody_shows_the_octave_from_middle_c(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        piano = app.query_one("#piano", PianoKeys)
        piano.set_range([])
        assert piano._low <= 60 and piano._high >= 71
        assert 60 in piano._white_keys()


async def test_the_keyboard_covers_a_melody_spanning_many_octaves(tmp_path: Path):
    """Five octaves is beyond what widening reaches, so the range must follow."""
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        piano = app.query_one("#piano", PianoKeys)
        piano.set_range([note(36), note(96)])

        assert piano._low <= 36
        assert piano._high >= 96
        assert 36 in piano._white_keys() and 96 in piano._white_keys()


async def test_a_note_at_the_bottom_of_the_midi_range_is_drawn(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        piano = app.query_one("#piano", PianoKeys)
        piano.set_range([note(0)])

        assert piano._low == 0
        assert min(piano._white_keys()) == 0
        assert key_spans(piano)  # it drew something rather than giving up


async def test_the_keys_stay_slim_and_the_range_widens_instead(tmp_path: Path):
    """A wide terminal should buy more octaves, not fatter keys."""
    narrow = make_app(tmp_path / "narrow")
    async with narrow.run_test(size=(100, 40)) as pilot:
        await record_once(pilot)
        small = narrow.query_one("#piano", PianoKeys)
        small_keys = len(small._white_keys())
        small_width = max(right - left + 2 for left, right in key_spans(small))

    wide = make_app(tmp_path / "wide")
    async with wide.run_test(size=(200, 40)) as pilot:
        await record_once(pilot)
        big = wide.query_one("#piano", PianoKeys)
        big_keys = len(big._white_keys())
        big_width = max(right - left + 2 for left, right in key_spans(big))

    assert big_keys > small_keys
    assert big_width <= PianoKeys.MAX_KEY_WIDTH
    assert small_width >= PianoKeys.MIN_KEY_WIDTH


@pytest.mark.parametrize("width", [96, 120, 156, 200])
async def test_the_keyboard_fits_the_width_it_was_given(tmp_path: Path, width: int):
    """Drawn wider than the widget, the rows wrap and the keyboard doubles up."""
    app = make_app(tmp_path)
    async with app.run_test(size=(width, 45)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)
        assert max(len(line) for line in drawn(piano)) <= piano.size.width
        assert piano.size.height == PianoKeys.BLACK_ROWS + PianoKeys.WHITE_ROWS + 1


# -- aiming a click at a key you can see -----------------------------------


@pytest.mark.parametrize("size", [(100, 40), (120, 45), (156, 60), (200, 50)])
async def test_every_white_key_is_hit_where_it_is_drawn(tmp_path: Path, size):
    """Click the middle of each key in turn; each must answer for itself.

    The key width is clamped at both ends, so it is not simply the widget
    width divided by the number of keys -- aiming with that formula lands on
    the wrong key at most terminal sizes.
    """
    app = make_app(tmp_path)
    async with app.run_test(size=size) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)
        whites = piano._white_keys()

        hit = [
            piano.key_at(*(click.x, click.y))
            for click in (white_click(piano, i) for i in range(len(whites)))
        ]
        assert hit == whites


async def test_every_black_key_hit_is_a_sharp(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)

        hits = {piano.key_at(column + 1, 1) for column in black_columns(piano)}
        assert hits
        assert all(midi is not None and midi % 12 in BLACK_STEPS for midi in hits)


async def test_a_black_key_sits_between_the_whites_it_divides(tmp_path: Path):
    """A sharp drawn to the left of its own white key would be a semitone lie."""
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)
        spans = key_spans(piano)
        whites = piano._white_keys()

        for column in black_columns(piano):
            sharp = piano.key_at(column + 1, 1)
            left = max(i for i, (a, _) in enumerate(spans) if a <= column)
            assert whites[left] < sharp < whites[left + 1]


async def test_the_gap_between_two_keys_still_reaches_a_key(tmp_path: Path):
    """Every column of the keyboard is clickable; none is dead space."""
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)
        columns = range(len(drawn(piano)[-1]))

        for row in (1, piano.BLACK_ROWS + 2):
            assert all(piano.key_at(c + 1, row) is not None for c in columns)


async def test_clicking_below_the_last_row_reaches_nothing(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)
        rows = PianoKeys.BLACK_ROWS + PianoKeys.WHITE_ROWS
        assert piano.key_at(5, rows + 1) is None


async def test_a_click_past_the_last_key_reaches_nothing(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)
        beyond = len(drawn(piano)[-1]) + 2
        assert piano.key_at(beyond, piano.BLACK_ROWS + 2) is None


@pytest.mark.parametrize("size", [(100, 40), (156, 60)])
async def test_the_note_added_is_the_key_that_was_clicked(tmp_path: Path, size):
    app = make_app(tmp_path)
    async with app.run_test(size=size) as pilot:
        await record_once(pilot)
        await pilot.press("c")  # start from nothing
        await pilot.pause()
        piano = app.query_one("#piano", PianoKeys)

        wanted = piano._white_keys()[4]
        piano.on_click(white_click(piano, 4))
        await pilot.pause()

        assert [n.midi for n in app.notes] == [wanted]


# -- lighting --------------------------------------------------------------


async def test_a_lit_white_key_is_filled_in(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)
        left, right = key_spans(piano)[3]
        row = body_row(piano)
        assert drawn(piano)[row][left:right + 1].strip() == ""

        piano.light({piano._white_keys()[3]})
        assert drawn(piano)[row][left:right + 1] == "█" * (right - left + 1)


async def test_lighting_one_key_leaves_its_neighbours_blank(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)
        piano.light({piano._white_keys()[3]})

        row = drawn(piano)[body_row(piano)]
        for index in (2, 4):
            left, right = key_spans(piano)[index]
            assert row[left:right + 1].strip() == ""


async def test_every_sounding_note_lights_at_once(tmp_path: Path):
    """Two notes overlapping in time are two keys held down together."""
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)
        pair = piano._white_keys()[2:4]
        piano.light(set(pair))

        row = drawn(piano)[body_row(piano)]
        lit = [
            index
            for index, (left, right) in enumerate(key_spans(piano))
            if "█" in row[left:right + 1]
        ]
        assert [piano._white_keys()[i] for i in lit] == pair


async def test_a_lit_black_key_is_highlighted(tmp_path: Path):
    """Black keys are already solid, so only their colour can say "sounding"."""
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)
        sharp = piano.key_at(black_columns(piano)[0] + 1, 1)

        assert not any(HIGHLIGHT in str(s.style) for s in piano.content.spans)
        piano.light({sharp})
        assert any(HIGHLIGHT in str(s.style) for s in piano.content.spans)


async def test_lighting_a_key_off_the_keyboard_changes_nothing(tmp_path: Path):
    """A note outside the drawn range must not smear the drawing."""
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)
        before = drawn(piano)

        piano.light({piano._high + 24})
        assert drawn(piano) == before


async def test_the_keyboard_goes_dark_between_notes(tmp_path: Path):
    """A gap in the melody must clear the last key, not leave it stuck on."""
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)

        await pilot.press("p")
        gap = app.notes[0].end + (app.notes[1].start - app.notes[0].end) / 2
        app.player.position = gap
        app._tick_playback()

        assert piano._lit == set()
        assert "█" not in drawn(piano)[body_row(piano)]


# -- how the keys are labelled ---------------------------------------------


def labels(piano: PianoKeys) -> list[str]:
    row = drawn(piano)[PianoKeys.BLACK_ROWS + PianoKeys.WHITE_ROWS - 2]
    return [row[left:right + 1].strip() for left, right in key_spans(piano)]


@pytest.mark.parametrize("scheme", ["english", "german", "solfege", "sargam"])
async def test_a_key_is_never_labelled_with_another_note_s_name(
    tmp_path: Path, scheme: str
):
    """A shortened label may drop the octave; it may not become a different note."""
    app = make_app(tmp_path)
    async with app.run_test(size=(120, 45)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)
        piano.set_range(app.notes, scheme)

        for midi, label in zip(piano._white_keys(), labels(piano)):
            assert label
            assert spell(midi, scheme).startswith(label)


async def test_the_labels_change_with_the_notation(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)

        piano.set_range(app.notes, "english")
        english = labels(piano)
        piano.set_range(app.notes, "solfege")
        assert labels(piano) != english
        assert labels(piano)[0].startswith("Do")


async def test_only_white_keys_carry_a_label(tmp_path: Path):
    """A name printed under a black key would read as belonging to it."""
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)
        row = drawn(piano)[PianoKeys.BLACK_ROWS + PianoKeys.WHITE_ROWS - 2]
        base = drawn(piano)[-1]

        edges = [i for i, glyph in enumerate(base) if glyph == "┴"]
        assert all(row[i] == "│" for i in edges)


# -- known defects ---------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "refresh_keys only ever widens the range: on_resize never recomputes it "
        "from the melody, so shrinking the terminal leaves a keyboard drawn far "
        "wider than the widget, and it wraps to double height"
    ),
)
async def test_shrinking_the_terminal_reflows_the_keyboard(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(180, 50)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)

        await pilot.resize_terminal(90, 40)
        await pilot.pause()
        await pilot.pause()

        assert max(len(line) for line in drawn(piano)) <= piano.size.width
        assert piano.size.height == PianoKeys.BLACK_ROWS + PianoKeys.WHITE_ROWS + 1


@pytest.mark.xfail(
    strict=True,
    reason=(
        "set_range rounds the top of the range up to a whole octave without "
        "clamping to 127, so a melody in the top octave draws keys for MIDI "
        "128-131; clicking one adds a note above the MIDI range"
    ),
)
async def test_the_keyboard_never_draws_a_key_above_midi_127(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(80, 30)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)
        piano.set_range([note(127)])

        assert max(piano._white_keys()) <= 127
        assert all(
            key <= 127 for key in piano._owner + piano._black if key is not None
        )


def test_white_and_black_steps_together_cover_the_octave():
    """Guards the constants the drawing and the hit map are both built on."""
    assert sorted(WHITE_STEPS + BLACK_STEPS) == list(range(12))
