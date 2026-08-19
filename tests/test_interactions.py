"""Two features used at once.

Each of these is a sequence a user would actually perform -- edit while the
playback is running, change the notation with a note selected, delete the run
that is on screen -- rather than one feature exercised on its own. They run
headless with the recorder and player faked out, as in test_app.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from humm2melody.profiles import ProfileStore, guest
from humm2melody.tui import MelodySequence, PianoKeys, PianoRoll
from textual.widgets import Button, ListView, Static

from tests.test_app import goto_calibrate, make_app, record_once


def hint(app) -> str:
    return str(app.query_one("#hint", Static).content)


# -- editing while the playback is running ---------------------------------


async def test_editing_does_not_stop_the_playback(tmp_path: Path):
    """Reaching for a wrong note while it plays should not kill the sound."""
    app = make_app(tmp_path)
    async with app.run_test(size=(150, 60)) as pilot:
        await record_once(pilot)
        await pilot.press("p")
        await pilot.pause()
        assert app.player.playing is True

        await pilot.press("e")
        await pilot.pause()
        assert app.editing is True
        assert app.player.playing is True


async def test_a_note_retuned_mid_playback_takes_effect(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(150, 60)) as pilot:
        await record_once(pilot)
        before = app.notes[0].midi
        await pilot.press("p")
        await pilot.press("e")
        await pilot.press("up")
        await pilot.pause()

        assert app.notes[0].midi == before + 1


async def test_deleting_every_note_mid_playback_does_not_crash_the_playhead(
    tmp_path: Path,
):
    """The tick walks the note list; emptying it under the tick must be safe."""
    app = make_app(tmp_path)
    async with app.run_test(size=(150, 60)) as pilot:
        await record_once(pilot)
        await pilot.press("p")
        await pilot.press("e")
        for _ in range(len(app.notes)):
            await pilot.press("delete")
        await pilot.pause()
        assert app.notes == []

        app.player.position = 0.5
        app._tick_playback()
        assert app.query_one("#piano", PianoKeys)._lit == set()
        assert app.is_running


async def test_the_playhead_lights_the_edited_pitch_not_the_old_one(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(150, 60)) as pilot:
        await record_once(pilot)
        await pilot.press("p")
        await pilot.press("e")
        await pilot.press("up")
        await pilot.pause()

        target = app.notes[0]
        app.player.position = (target.start + target.end) / 2
        app._tick_playback()
        assert app.query_one("#piano", PianoKeys)._lit == {target.midi}


async def test_adding_a_note_from_the_keyboard_while_playing(tmp_path: Path):
    """Clicking a key sounds it, which has to take the device from the melody."""
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        await pilot.press("p")
        await pilot.pause()
        piano = app.query_one("#piano", PianoKeys)
        before = len(app.notes)

        from tests.test_keyboard import white_click

        piano.on_click(white_click(piano, 2))
        await pilot.pause()

        assert len(app.notes) == before + 1
        assert [n.midi for n in app.player.played] == [app.notes[app.selected_note].midi]


# -- changing a setting mid-edit -------------------------------------------


async def test_changing_notation_keeps_the_selected_note_selected(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(150, 60)) as pilot:
        await record_once(pilot)
        await pilot.press("e")
        await pilot.press("right")
        await pilot.pause()
        assert app.selected_note == 1

        await pilot.press("n")
        await pilot.pause()
        assert app.selected_note == 1
        assert app.editing is True


async def test_changing_notation_mid_edit_respells_the_selection(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(150, 60)) as pilot:
        await record_once(pilot)
        await pilot.press("e")
        await pilot.pause()
        english = str(app.query_one("#sequence", MelodySequence).content)

        await pilot.press("n")
        await pilot.press("n")  # english -> german -> solfege
        await pilot.pause()
        solfege = str(app.query_one("#sequence", MelodySequence).content)

        assert "Do" in solfege
        assert solfege != english


async def test_changing_notation_does_not_move_a_single_note(tmp_path: Path):
    """Spelling is a view. Nothing about the transcription may follow it."""
    app = make_app(tmp_path)
    async with app.run_test(size=(150, 60)) as pilot:
        await record_once(pilot)
        await pilot.press("e")
        await pilot.press("up")
        await pilot.pause()
        edited = [(n.midi, n.start, n.end) for n in app.notes]

        for _ in range(4):
            await pilot.press("n")
        await pilot.pause()
        assert [(n.midi, n.start, n.end) for n in app.notes] == edited


async def test_the_editing_keys_survive_a_notation_change(tmp_path: Path):
    """Redrawing must leave the timeline focused, or the arrows go dead."""
    app = make_app(tmp_path)
    async with app.run_test(size=(150, 60)) as pilot:
        await record_once(pilot)
        await pilot.press("e")
        await pilot.press("n")
        await pilot.pause()

        before = app.notes[app.selected_note].midi
        await pilot.press("up")
        await pilot.pause()
        assert app.notes[app.selected_note].midi == before + 1


async def test_the_tempo_dial_still_works_while_editing(tmp_path: Path):
    """`<` and `>` are app keys; the editor must not swallow them."""
    app = make_app(tmp_path)
    async with app.run_test(size=(150, 60)) as pilot:
        await record_once(pilot)
        await pilot.press("e")
        await pilot.press("greater_than_sign")
        await pilot.pause()
        assert app.tempo == 6


async def test_changing_tempo_mid_edit_does_not_disturb_the_notes(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(150, 60)) as pilot:
        await record_once(pilot)
        await pilot.press("e")
        await pilot.press("up")
        await pilot.pause()
        edited = [n.midi for n in app.notes]

        await pilot.press("less_than_sign")
        await pilot.pause()
        assert [n.midi for n in app.notes] == edited
        assert app.selected_note == 0


async def test_the_new_tempo_reaches_a_playback_started_from_edit_mode(
    tmp_path: Path,
):
    app = make_app(tmp_path)
    async with app.run_test(size=(150, 60)) as pilot:
        await record_once(pilot)
        await pilot.press("e")
        await pilot.press("greater_than_sign")
        await pilot.press("greater_than_sign")
        await pilot.press("p")
        await pilot.pause()
        assert app.player.speed == pytest.approx(1.45)


async def test_the_voice_can_be_changed_while_editing(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(150, 60)) as pilot:
        await record_once(pilot)
        await pilot.press("e")
        await pilot.press("v")
        await pilot.press("p")
        await pilot.pause()
        assert app.player.voice == "rich"


# -- the run currently on screen -------------------------------------------


async def test_deleting_the_loaded_run_leaves_the_notes_on_screen(tmp_path: Path):
    """The transcription is still yours; only the copy on disk went away."""
    app = make_app(tmp_path)
    async with app.run_test(size=(150, 60)) as pilot:
        await record_once(pilot)
        names = [n.name for n in app.notes]

        await pilot.press("d")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        assert list(tmp_path.iterdir()) == []
        assert [n.name for n in app.notes] == names


async def test_editing_after_deleting_the_loaded_run_does_not_recreate_it(
    tmp_path: Path,
):
    """A write-back to a deleted run must fail quietly, not resurrect it."""
    app = make_app(tmp_path)
    async with app.run_test(size=(150, 60)) as pilot:
        await record_once(pilot)
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        await pilot.press("e")
        await pilot.press("up")
        await pilot.press("escape")
        await pilot.pause()
        await asyncio.sleep(0.6)
        await pilot.pause()

        assert list(tmp_path.iterdir()) == []
        assert app.sessions == []
        assert app.is_running


async def test_recording_again_after_deleting_the_loaded_run(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(150, 60)) as pilot:
        await record_once(pilot)
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        await record_once(pilot)
        assert len(app.sessions) == 1
        assert app.current_session is not None
        assert app.current_session.path.is_dir()


async def test_deleting_one_run_while_another_is_loaded(tmp_path: Path):
    """The deletion must follow the highlight, not whatever is on screen."""
    app = make_app(tmp_path)
    async with app.run_test(size=(150, 60)) as pilot:
        await record_once(pilot)
        await record_once(pilot)
        loaded = app.current_session.path

        app.query_one("#runs", ListView).index = 1  # the older run
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        assert loaded.is_dir()
        assert [s.path for s in app.sessions] == [loaded]


# -- calibrating, then using the app ---------------------------------------


async def calibrate_fully(pilot) -> None:
    """Run all three calibration steps, the way pressing space does."""
    from humm2melody.calibration import STEPS

    for _ in range(len(STEPS)):
        await pilot.press("space")
        await pilot.press("space")
    await pilot.pause()


async def back_to_recording(app, pilot) -> None:
    from textual.widgets import Tabs

    app.query_one(Tabs).focus()
    await pilot.press("left")
    await pilot.pause()
    assert app._active_tab() == "tab-record"


async def test_recording_works_immediately_after_a_calibration_run(tmp_path: Path):
    """Calibration leaves the recorder configured; the next hum must still work."""
    store = ProfileStore(tmp_path / "profiles")
    app = make_app(tmp_path, profile=store.create("Ahmed"))
    async with app.run_test(size=(150, 60)) as pilot:
        await goto_calibrate(app, pilot)
        await calibrate_fully(pilot)
        await back_to_recording(app, pilot)
        await record_once(pilot)

        assert [n.name for n in app.notes] == ["C4", "E4", "G4"]
        assert len(app.sessions) == 1


async def test_a_calibration_run_is_not_saved_as_a_recording(tmp_path: Path):
    """Calibration takes are not transcriptions; they must not fill the sidebar."""
    store = ProfileStore(tmp_path / "profiles")
    app = make_app(tmp_path, profile=store.create("Ahmed"))
    async with app.run_test(size=(150, 60)) as pilot:
        await goto_calibrate(app, pilot)
        await calibrate_fully(pilot)

        assert app.sessions == []
        assert list(tmp_path.glob("2*")) == []


async def test_a_hum_recorded_right_after_calibrating_uses_the_new_dials(
    tmp_path: Path,
):
    """What calibration chose has to reach the next recording, not just the file."""
    store = ProfileStore(tmp_path / "profiles")
    app = make_app(tmp_path, profile=store.create("Ahmed"))
    async with app.run_test(size=(150, 60)) as pilot:
        await goto_calibrate(app, pilot)
        await calibrate_fully(pilot)
        await pilot.press("y")  # keep it, though the faked take is not confident
        await pilot.pause()
        chosen = (app.cal_result.pitch_dial, app.cal_result.pause_dial)
        assert (app.sensitivity, app.pause_sensitivity) == chosen

        await back_to_recording(app, pilot)
        await record_once(pilot)

        assert (app.sensitivity, app.pause_sensitivity) == chosen
        assert store.load(app.profile.path).pitch_sensitivity == chosen[0]
        assert app.notes


# -- switching profile -----------------------------------------------------


async def test_switching_profile_reapplies_the_dials_to_the_transcription(
    tmp_path: Path,
):
    store = ProfileStore(tmp_path / "profiles")
    other = store.create("Bea")
    other.pitch_sensitivity = 9
    other.pause_sensitivity = 1
    store.save(other)

    app = make_app(tmp_path, profile=store.create("Ann"))
    async with app.run_test(size=(150, 60)) as pilot:
        await record_once(pilot)

        app._adopt_profile(store.load(other.path))
        await pilot.pause()
        assert app.sensitivity == 9
        assert app.pause_sensitivity == 1
        assert app.notes  # still showing a transcription, not blanked


async def test_switching_profile_stops_the_playback(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(150, 60)) as pilot:
        await record_once(pilot)
        await pilot.press("p")
        await pilot.pause()

        await pilot.press("u")
        await pilot.pause()
        assert app.player.playing is False
        await pilot.press("escape")


async def test_switching_to_guest_stops_remembering_settings(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles")
    named = store.create("Ann")
    app = make_app(tmp_path, profile=named)
    async with app.run_test(size=(150, 60)) as pilot:
        app._adopt_profile(guest())
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()

    assert store.load(named.path).voice == "pure"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "_apply_profile re-segments unconditionally, so adopting a profile "
        "whose dials are identical still throws hand edits away -- and clears "
        "the run's edited flag on disk, so they cannot be recovered by "
        "reloading either"
    ),
)
async def test_switching_to_an_identical_profile_keeps_hand_edits(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles")
    twin = store.create("Bea")  # same defaults as Ann
    app = make_app(tmp_path, profile=store.create("Ann"))
    async with app.run_test(size=(150, 60)) as pilot:
        await record_once(pilot)
        await pilot.press("e")
        await pilot.press("up")
        await pilot.press("escape")
        await pilot.pause()
        edited = [n.midi for n in app.notes]

        app._adopt_profile(store.load(twin.path))
        await pilot.pause()
        await asyncio.sleep(0.6)
        await pilot.pause()

        assert [n.midi for n in app.notes] == edited
        saved = json.loads((app.store.list()[0].manifest_path).read_text())
        assert [n["midi"] for n in saved["notes"]] == edited


# -- playing a run that transcribed to nothing -----------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "_stop_playback disables the play button on `not self.notes`, while "
        "_show_notes enables it whenever there is audio -- so a run that "
        "detected nothing can be auditioned once and then never again"
    ),
)
async def test_a_run_with_no_notes_can_be_played_more_than_once(tmp_path: Path):
    """Hearing a failed run back is exactly how you find out what went wrong."""
    from humm2melody.pitch import PitchFrame

    quiet = [PitchFrame(i * 0.02, 0.0, 0.0, 0.0) for i in range(60)]
    app = make_app(tmp_path, frames=quiet)
    async with app.run_test(size=(150, 60)) as pilot:
        await record_once(pilot)
        await pilot.press("m")  # play the hum, since there are no notes
        await pilot.press("p")
        await pilot.pause()
        await pilot.press("p")  # stop
        await pilot.pause()

        assert app.query_one("#play", Button).disabled is False


# -- clearing while other things are happening -----------------------------


async def test_clear_stops_the_playback(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(150, 60)) as pilot:
        await record_once(pilot)
        await pilot.press("p")
        await pilot.pause()

        await pilot.press("c")
        await pilot.pause()
        assert app.player.playing is False
        assert app.query_one("#roll", PianoRoll)._playhead is None


async def test_clear_leaves_edit_mode(tmp_path: Path):
    """Nothing is left to edit, so the arrows must go back to the run list."""
    app = make_app(tmp_path)
    async with app.run_test(size=(150, 60)) as pilot:
        await record_once(pilot)
        await pilot.press("e")
        await pilot.press("c")
        await pilot.pause()

        assert app.editing is False
        assert app.selected_note is None
        assert app.notes == []


async def test_undo_does_not_reach_across_a_clear(tmp_path: Path):
    """Undo after clearing must not resurrect notes from a different run."""
    app = make_app(tmp_path)
    async with app.run_test(size=(150, 60)) as pilot:
        await record_once(pilot)
        await pilot.press("e")
        await pilot.press("up")
        await pilot.press("c")
        await pilot.pause()

        await record_once(pilot)
        fresh = [n.midi for n in app.notes]
        await pilot.press("e")
        await pilot.press("z")
        await pilot.pause()

        assert [n.midi for n in app.notes] == fresh
        assert "Nothing to undo" in hint(app)
