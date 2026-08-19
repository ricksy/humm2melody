"""TUI tests driven by Textual's Pilot, with audio I/O faked out.

These run headless and never touch a microphone or speaker. Every app is given
a tmp_path output directory so tests never write into the working tree.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest
from humm2melody.audio import AudioError, LiveReading
from humm2melody.pitch import PitchFrame, midi_to_hz
from humm2melody.profiles import Profile, ProfileStore, guest
from humm2melody.segment import Note
from humm2melody.sessions import HUM_AUDIO, MANIFEST, PITCH_CSV, PLAYBACK_AUDIO
from humm2melody.tui import (
    ConfirmScreen,
    Humm2MelodyApp,
    MelodySequence,
    NameScreen,
    PianoRoll,
    ProfileScreen,
)
from textual.widgets import (
    Button,
    Input,
    Label,
    ListView,
    Static,
    TabbedContent,
    TabPane,
)

SR = 22050


def canned_frames() -> list[PitchFrame]:
    """A clean C4-E4-G4 pitch track."""
    frames: list[PitchFrame] = []
    step = 512 / SR
    t = 0.0
    for midi in (60, 64, 67):
        for _ in range(int(0.4 / step)):
            frames.append(PitchFrame(t, midi_to_hz(midi), 0.95, 0.2))
            t += step
        for _ in range(int(0.15 / step)):
            frames.append(PitchFrame(t, 0.0, 0.0, 0.0))
            t += step
    return frames


class FakeRecorder:
    """Stands in for Recorder, and mirrors the attributes the app sets on it."""

    sample_rate = SR

    def __init__(self, frames=None, fail=False, audio=None):
        self.fmin = 65.0
        self.fmax = 1200.0
        self._frames = frames if frames is not None else canned_frames()
        self._fail = fail
        self._audio = (
            audio if audio is not None else np.zeros(int(1.6 * SR), dtype=np.float32)
        )
        self.running = False

    def start(self):
        if self._fail:
            raise AudioError("no such device")
        self.running = True

    def stop(self):
        self.running = False
        return self._frames

    def audio(self):
        return self._audio

    def latest(self):
        return LiveReading(261.6, 0.9, 0.5, "C4", 3.0, 1.2)


class FakePlayer:
    def __init__(self):
        self.playing = False
        self.position = 0.0
        self.played: list[Note] | None = None
        self.buffer = None
        self.sample_rate = SR
        self.speed = 1.0
        self.voice = "pure"

    def play(self, notes, speed=1.0, voice="pure"):
        self.played = list(notes)
        self.speed = speed
        self.voice = voice
        self.playing = True
        self.position = 0.0

    def play_audio(self, buffer, rate=None):
        self.buffer = buffer
        self.sample_rate = rate or SR
        self.playing = True
        self.position = 0.0

    def stop(self):
        self.playing = False
        self.position = 0.0


def make_app(tmp_path: Path, save: bool = True, profile=None, **kwargs):
    """An app that skips the profile chooser, so key presses reach the UI."""
    app = Humm2MelodyApp(
        output_dir=tmp_path,
        save=save,
        profile_dir=tmp_path / "profiles",
        profile=profile or guest(),
    )
    app.recorder = FakeRecorder(**kwargs)
    app.player = FakePlayer()
    return app


class _Click:
    """The couple of fields a widget's on_click actually reads."""

    def __init__(self, x: int, y: int) -> None:
        self.x, self.y = x, y


async def click_button(app, pilot, selector: str) -> None:
    """Click a button, scrolling it into view first.

    The controls sit inside the scrolling results pane, so on a short screen
    they can be below the fold -- which a real user also has to scroll to.
    """
    button = app.query_one(selector)
    app.query_one("#results").scroll_to_widget(button, animate=False)
    await pilot.pause()
    await pilot.click(button)
    await pilot.pause()


async def record_once(pilot) -> None:
    """Start and stop a recording, letting the UI settle."""
    await pilot.press("space")
    await pilot.press("space")
    await pilot.pause()


# -- basic wiring ----------------------------------------------------------


async def test_starts_empty_with_playback_disabled(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test():
        assert app.query_one("#play", Button).disabled is True
        assert app.notes == []


async def test_button_toggles_label_while_recording(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(120, 70)) as pilot:
        toggle = app.query_one("#toggle", Button)
        await click_button(app, pilot, "#toggle")
        assert app.recorder.running is True
        assert "Stop" in str(toggle.label)

        # Button ignores clicks while its "-active" press animation runs, so
        # wait that out before clicking again.
        await asyncio.sleep(toggle.active_effect_duration + 0.05)
        await click_button(app, pilot, "#toggle")
        assert app.recorder.running is False
        assert "Start" in str(toggle.label)


async def test_recording_produces_notes_and_enables_playback(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)

        assert [n.name for n in app.notes] == ["C4", "E4", "G4"]
        assert app.query_one("#play", Button).disabled is False


async def test_timeline_and_sequence_render_after_stopping(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)

        roll = str(app.query_one("#roll", PianoRoll).content)
        assert "C4" in roll and "G4" in roll
        assert "█" in roll

        sequence = str(app.query_one("#sequence", MelodySequence).content)
        assert "C4" in sequence and "E4" in sequence and "G4" in sequence


async def test_microphone_failure_is_reported_not_raised(tmp_path: Path):
    app = make_app(tmp_path, fail=True)
    async with app.run_test(size=(120, 70)) as pilot:
        await click_button(app, pilot, "#toggle")

        hint = str(app.query_one("#hint", Static).content)
        assert "microphone" in hint.lower()
        assert "Start" in str(app.query_one("#toggle", Button).label)


async def test_silence_reports_no_notes_without_crashing(tmp_path: Path):
    quiet = [PitchFrame(i * 0.02, 0.0, 0.0, 0.0) for i in range(60)]
    app = make_app(tmp_path, frames=quiet)
    async with app.run_test() as pilot:
        await record_once(pilot)

        assert app.notes == []
        detail = str(app.query_one("#detail", Static).content)
        assert "No notes detected" in detail
        # Playback stays available: with nothing transcribed, hearing the
        # recording back is exactly how you work out what went wrong.
        assert app.query_one("#play", Button).disabled is False


# -- playback --------------------------------------------------------------


async def test_playback_plays_the_detected_notes(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("p")

        assert app.player.playing is True
        assert [n.name for n in app.player.played] == ["C4", "E4", "G4"]
        assert "Stop" in str(app.query_one("#play", Button).label)


async def test_playback_toggles_off(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("p")
        await pilot.press("p")

        assert app.player.playing is False
        assert "Play" in str(app.query_one("#play", Button).label)


async def test_playhead_tracks_position_during_playback(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("p")

        # Drop the playhead inside the second note and tick the UI by hand.
        app.player.position = app.notes[1].start + 0.05
        app._tick_playback()
        sequence = str(app.query_one("#sequence", MelodySequence).content)
        assert "E4" in sequence


async def test_recording_stops_playback(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("p")
        assert app.player.playing is True

        await pilot.press("space")  # start recording again
        assert app.player.playing is False
        assert app.query_one("#play", Button).disabled is True


# -- saving ----------------------------------------------------------------


async def test_every_run_is_saved_by_default(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)

        runs = list(tmp_path.iterdir())
        assert len(runs) == 1
        for name in (HUM_AUDIO, PLAYBACK_AUDIO, PITCH_CSV, MANIFEST):
            assert (runs[0] / name).is_file()


async def test_saved_run_appears_in_the_sidebar(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)

        assert len(app.sessions) == 1
        assert len(app.query_one("#runs", ListView).children) == 1
        assert app.selected_session is not None


async def test_repeated_runs_accumulate(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await record_once(pilot)
        await record_once(pilot)

        assert len(app.sessions) == 3
        assert len({s.path for s in app.sessions}) == 3


async def test_no_save_flag_writes_nothing(tmp_path: Path):
    app = make_app(tmp_path, save=False)
    async with app.run_test() as pilot:
        await record_once(pilot)

        assert list(tmp_path.iterdir()) == []
        assert app.sessions == []
        # The transcription still works, it just is not persisted.
        assert [n.name for n in app.notes] == ["C4", "E4", "G4"]


async def test_a_run_with_no_notes_is_still_saved(tmp_path: Path):
    quiet = [PitchFrame(i * 0.02, 0.0, 0.0, 0.0) for i in range(60)]
    app = make_app(tmp_path, frames=quiet)
    async with app.run_test() as pilot:
        await record_once(pilot)

        assert len(list(tmp_path.iterdir())) == 1


async def test_clear_does_not_delete_saved_runs(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("c")
        await pilot.pause()

        assert app.notes == []
        assert len(list(tmp_path.iterdir())) == 1
        assert len(app.sessions) == 1


# -- loading, renaming, deleting -------------------------------------------


async def test_loading_a_run_restores_its_notes(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("c")  # wipe the display
        await pilot.pause()
        assert app.notes == []

        app.load_selected_session()
        await pilot.pause()

        assert [n.name for n in app.notes] == ["C4", "E4", "G4"]
        assert app.query_one("#play", Button).disabled is False


async def test_the_run_list_holds_focus_so_its_keys_work(tmp_path: Path):
    """Buttons are non-focusable, so the sidebar should get focus by default."""
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        assert app.focused is app.query_one("#runs", ListView)


async def test_enter_loads_the_highlighted_run(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("c")
        await pilot.pause()
        assert app.notes == []

        await pilot.press("enter")
        await pilot.pause()

        assert [n.name for n in app.notes] == ["C4", "E4", "G4"]


async def test_arrow_keys_move_between_runs(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await record_once(pilot)

        newest = app.selected_session
        await pilot.press("down")
        await pilot.pause()

        assert app.selected_session is not None
        assert app.selected_session.path != newest.path


async def test_rename_updates_the_sidebar_and_disk(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)

        await pilot.press("r")
        await pilot.pause()
        app.screen.query_one("#label", Input).value = "Chorus idea"
        await pilot.press("enter")
        await pilot.pause()

        assert app.sessions[0].label == "Chorus idea"
        assert "Chorus-idea" in app.sessions[0].path.name
        assert app.sessions[0].path.is_dir()


async def test_rename_can_be_cancelled(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        original = app.sessions[0].path

        await pilot.press("r")
        await pilot.pause()
        app.screen.query_one("#label", Input).value = "discarded"
        await pilot.press("escape")
        await pilot.pause()

        assert app.sessions[0].path == original
        assert app.sessions[0].label == ""


async def test_delete_removes_the_run_after_confirmation(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        assert len(list(tmp_path.iterdir())) == 1

        await pilot.press("d")
        await pilot.pause()
        await pilot.click("#ok")
        await pilot.pause()

        assert list(tmp_path.iterdir()) == []
        assert app.sessions == []
        assert len(app.query_one("#runs", ListView).children) == 0


async def test_delete_can_be_confirmed_from_the_keyboard(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)

        await pilot.press("d")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        assert list(tmp_path.iterdir()) == []
        assert app.sessions == []


async def test_delete_can_be_declined_from_the_keyboard(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)

        await pilot.press("d")
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()

        assert len(list(tmp_path.iterdir())) == 1
        assert len(app.sessions) == 1


async def test_enter_alone_does_not_confirm_a_delete(tmp_path: Path):
    """A destructive dialog must not be dismissable by a stray Enter."""
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)

        await pilot.press("d")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert len(list(tmp_path.iterdir())) == 1


async def test_delete_is_cancellable(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)

        await pilot.press("d")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert len(list(tmp_path.iterdir())) == 1
        assert len(app.sessions) == 1


async def test_delete_only_removes_the_selected_run(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await record_once(pilot)
        assert len(app.sessions) == 2
        survivor = app.sessions[1].path

        app.query_one("#runs", ListView).index = 0
        await pilot.press("d")
        await pilot.pause()
        await pilot.click("#ok")
        await pilot.pause()

        assert len(app.sessions) == 1
        assert survivor.exists()


async def test_rename_and_delete_do_nothing_without_a_selection(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        assert app.selected_session is None
        await pilot.press("r")
        await pilot.press("d")
        await pilot.pause()
        # No modal should have opened, and nothing should have blown up.
        assert app.screen_stack == [app.screen_stack[0]]
        assert not app.query(ConfirmScreen) and not app.query(NameScreen)
        assert app.sessions == []


# -- sensitivity dial ------------------------------------------------------


async def test_sensitivity_starts_balanced(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test():
        assert app.sensitivity == 5
        assert app.pause_sensitivity == 5
        assert "Pitch" in str(app.query_one("#sensitivity", Static).content)
        assert "Pauses" in str(app.query_one("#pause", Static).content)


async def test_brackets_move_the_dial(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("right_square_bracket")
        assert app.sensitivity == 6
        await pilot.press("left_square_bracket")
        await pilot.press("left_square_bracket")
        assert app.sensitivity == 4


async def test_dial_clamps_at_both_ends(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        for _ in range(12):
            await pilot.press("left_square_bracket")
        assert app.sensitivity == 1
        for _ in range(20):
            await pilot.press("right_square_bracket")
        assert app.sensitivity == 9


async def test_changing_sensitivity_resegments_without_rerecording(tmp_path: Path):
    """The whole point: adjust after the fact, no second take."""
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        assert app.frames  # the pitch track is kept for re-segmentation

        before = list(app.notes)
        await pilot.press("left_square_bracket")
        await pilot.pause()
        assert app.notes  # still a transcription, recomputed
        assert app.recorder.running is False  # nothing was re-recorded
        assert len(before) > 0


async def test_sensitivity_does_nothing_without_a_recording(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("left_square_bracket")
        await pilot.pause()
        assert app.notes == []


async def test_loading_a_run_restores_its_pitch_track(tmp_path: Path):
    """A saved run must stay adjustable, not just replayable."""
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("c")
        await pilot.pause()
        assert app.frames == []

        app.load_selected_session()
        await pilot.pause()
        assert len(app.frames) > 0
        assert [n.name for n in app.notes] == ["C4", "E4", "G4"]


async def test_clear_resets_the_pitch_track(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("c")
        await pilot.pause()
        assert app.frames == []


# -- pause dial and comparison playback ------------------------------------


async def test_comma_and_period_move_the_pause_dial(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("full_stop")
        assert app.pause_sensitivity == 6
        await pilot.press("comma")
        await pilot.press("comma")
        assert app.pause_sensitivity == 4


async def test_pause_dial_clamps(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        for _ in range(12):
            await pilot.press("comma")
        assert app.pause_sensitivity == 1
        for _ in range(20):
            await pilot.press("full_stop")
        assert app.pause_sensitivity == 9


async def test_the_two_dials_are_independent(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("comma")
        assert app.sensitivity == 5 and app.pause_sensitivity == 4
        await pilot.press("right_square_bracket")
        assert app.sensitivity == 6 and app.pause_sensitivity == 4


async def test_compare_button_cycles_the_source(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        assert app.source == "tones"
        await pilot.press("m")
        assert app.source == "hum"
        await pilot.press("m")
        assert app.source == "both"
        await pilot.press("m")
        assert app.source == "tones"


async def test_compare_button_label_follows_the_source(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        assert "Tones" in str(app.query_one("#compare", Button).label)
        await pilot.press("m")
        assert "hum" in str(app.query_one("#compare", Button).label).lower()


async def test_playing_the_hum_uses_the_recording_not_the_notes(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("m")  # -> hum
        await pilot.press("p")
        assert app.player.playing is True
        assert app.player.played is None  # notes were not what got played
        assert app.player.buffer is not None


async def test_overlay_mixes_hum_and_tones(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("m")
        await pilot.press("m")  # -> both
        await pilot.press("p")
        assert app.player.playing is True
        assert app.player.buffer is not None
        assert app.player.buffer.size > 0


async def test_recording_keeps_the_audio_for_comparison(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        assert app.audio is not None
        assert app.audio_rate == SR


async def test_loading_a_run_restores_its_audio(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("c")
        await pilot.pause()
        assert app.audio is None

        app.load_selected_session()
        await pilot.pause()
        assert app.audio is not None
        assert app.audio_rate == SR


# -- starring --------------------------------------------------------------


async def test_s_stars_the_highlighted_run(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        assert app.selected_session.starred is False

        await pilot.press("s")
        await pilot.pause()
        assert app.sessions[0].starred is True


async def test_s_toggles_the_star_off_again(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("s")
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()
        assert app.sessions[0].starred is False


async def test_a_starred_run_is_marked_in_the_sidebar(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("s")
        await pilot.pause()

        runs = app.query_one("#runs", ListView)
        rendered = " ".join(str(item.query_one(Label).content) for item in runs.children)
        assert "★" in rendered


async def test_starring_does_nothing_without_a_selection(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("s")
        await pilot.pause()
        assert app.sessions == []


async def test_deleting_a_starred_run_warns_that_it_is_starred(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("s")
        await pilot.pause()

        await pilot.press("d")
        await pilot.pause()
        dialog = " ".join(str(w.content) for w in app.screen.query(Label))
        assert "starred" in dialog.lower()
        await pilot.press("n")


# -- overlay mix dial ------------------------------------------------------


async def test_mix_dial_starts_balanced(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test():
        assert app.mix == 5
        assert "Mix" in str(app.query_one("#mix", Static).content)


async def test_minus_and_equals_move_the_mix(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("equals_sign")
        assert app.mix == 6
        await pilot.press("minus")
        await pilot.press("minus")
        assert app.mix == 4


async def test_mix_dial_clamps(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        for _ in range(12):
            await pilot.press("minus")
        assert app.mix == 1
        for _ in range(20):
            await pilot.press("equals_sign")
        assert app.mix == 9


async def test_mix_does_not_disturb_the_other_dials(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("minus")
        assert app.sensitivity == 5
        assert app.pause_sensitivity == 5
        assert app.mix == 4


async def test_overlay_uses_the_chosen_balance(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("m")
        await pilot.press("m")  # -> both
        await pilot.press("minus")
        await pilot.press("p")
        quiet = app.player.buffer.copy()

        app.player.stop()
        for _ in range(6):
            await pilot.press("equals_sign")
        await pilot.press("p")
        loud = app.player.buffer

        assert quiet is not None and loud is not None
        assert not np.allclose(quiet[: min(quiet.size, loud.size)],
                               loud[: min(quiet.size, loud.size)])


# -- tabs ------------------------------------------------------------------


async def test_the_ui_lives_in_four_tabs(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test():
        panes = [p.id for p in app.query(TabPane)]
        assert panes == ["tab-record", "tab-calibrate", "tab-train", "tab-manual"]


async def test_recording_is_the_active_tab_on_startup(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test():
        assert app.query_one(TabbedContent).active == "tab-record"


async def test_the_recording_tab_holds_the_existing_ui(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        pane = app.query_one("#tab-record", TabPane)
        for selector in ("#roll", "#sequence", "#runs", "#sensitivity", "#toggle"):
            assert pane.query(selector)


async def test_the_other_tabs_explain_themselves(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test():
        calibrate = str(app.query_one("#cal-title", Static).content)
        train = str(app.query_one("#train-body", Static).content)
        assert "Teach the app your voice" in calibrate
        assert "Training" in train and "Not built yet" in train


# -- profiles --------------------------------------------------------------


async def test_the_chooser_opens_when_no_profile_is_given(tmp_path: Path):
    app = Humm2MelodyApp(
        output_dir=tmp_path, save=False, profile_dir=tmp_path / "profiles"
    )
    app.recorder = FakeRecorder()
    app.player = FakePlayer()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ProfileScreen)


async def test_guest_can_be_chosen_from_the_chooser(tmp_path: Path):
    app = Humm2MelodyApp(
        output_dir=tmp_path, save=False, profile_dir=tmp_path / "profiles"
    )
    app.recorder = FakeRecorder()
    app.player = FakePlayer()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("g")
        await pilot.pause()
        assert not isinstance(app.screen, ProfileScreen)
        assert app.profile.is_guest is True


async def test_a_profile_supplies_its_dial_settings(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles")
    profile = store.create("Ahmed")
    profile.pitch_sensitivity, profile.pause_sensitivity, profile.mix = 8, 3, 7
    store.save(profile)

    app = make_app(tmp_path, profile=profile)
    async with app.run_test():
        assert app.sensitivity == 8
        assert app.pause_sensitivity == 3
        assert app.mix == 7


async def test_dial_changes_are_remembered_for_a_profile(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles")
    profile = store.create("Ahmed")

    app = make_app(tmp_path, profile=profile)
    async with app.run_test() as pilot:
        await pilot.press("right_square_bracket")
        await pilot.press("comma")
        await pilot.press("minus")
        await pilot.pause()

    reloaded = store.list()[0]
    assert reloaded.pitch_sensitivity == 6
    assert reloaded.pause_sensitivity == 4
    assert reloaded.mix == 4


async def test_guest_settings_are_not_remembered(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert app.sensitivity == 6
    assert not (tmp_path / "profiles").exists() or list(
        (tmp_path / "profiles").glob("*.json")
    ) == []


async def test_the_profile_name_shows_in_the_subtitle(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles")
    app = make_app(tmp_path, profile=store.create("Ahmed"))
    async with app.run_test():
        assert "Ahmed" in app.sub_title


async def test_u_reopens_the_chooser(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("u")
        await pilot.pause()
        assert isinstance(app.screen, ProfileScreen)
        await pilot.press("escape")


async def test_a_run_records_which_profile_made_it(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles")
    app = make_app(tmp_path, profile=store.create("Ahmed"))
    async with app.run_test() as pilot:
        await record_once(pilot)
        assert app.sessions[0].profile == "Ahmed"


async def test_a_guest_run_records_no_profile(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        assert app.sessions[0].profile == ""


async def test_the_chooser_says_so_when_there_are_no_profiles(tmp_path: Path):
    app = Humm2MelodyApp(
        output_dir=tmp_path, save=False, profile_dir=tmp_path / "profiles"
    )
    app.recorder = FakeRecorder()
    app.player = FakePlayer()
    async with app.run_test() as pilot:
        await pilot.pause()
        hint = str(app.screen.query_one("#profile-hint", Static).content)
        assert "No profiles yet" in hint
        assert "delete" not in hint  # nothing to delete, so do not offer it
        await pilot.press("g")


async def test_the_chooser_offers_every_action_once_a_profile_exists(tmp_path: Path):
    ProfileStore(tmp_path / "profiles").create("Ahmed")
    app = Humm2MelodyApp(
        output_dir=tmp_path, save=False, profile_dir=tmp_path / "profiles"
    )
    app.recorder = FakeRecorder()
    app.player = FakePlayer()
    async with app.run_test() as pilot:
        await pilot.pause()
        hint = str(app.screen.query_one("#profile-hint", Static).content)
        assert "use profile" in hint and "delete" in hint
        await pilot.press("g")


async def test_a_profile_can_be_selected_from_the_chooser(tmp_path: Path):
    ProfileStore(tmp_path / "profiles").create("Ahmed")
    app = Humm2MelodyApp(
        output_dir=tmp_path, save=False, profile_dir=tmp_path / "profiles"
    )
    app.recorder = FakeRecorder()
    app.player = FakePlayer()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.profile.name == "Ahmed"
        assert app.profile.is_guest is False


# -- calibration -----------------------------------------------------------


async def goto_calibrate(app, pilot):
    """Switch tabs the way a user does.

    Assigning TabbedContent.active directly does not stick: the underlying
    Tabs widget uses prefixed ids and reverts the change on the next refresh.
    Driving the tab bar exercises the real path anyway, including that keys
    still reach the app while the tab bar holds focus.
    """
    from textual.widgets import Tabs

    # Let startup settle first. The remembered-tab restore is deferred by one
    # refresh, and switching inside that window is not something a real user
    # can do -- the app deliberately ignores tab changes until it has settled,
    # so that the restore cannot drag them back.
    await pilot.pause()

    app.query_one(Tabs).focus()
    await pilot.press("right")
    await pilot.pause()
    assert app._active_tab() == "tab-calibrate"


async def test_calibration_starts_idle(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_calibrate(app, pilot)
        body = str(app.query_one("#calibrate-body", Static).content)
        assert "to begin" in body
        assert app.cal_step is None


async def test_space_drives_calibration_on_that_tab(tmp_path: Path):
    """Space means 'go' on whichever tab is showing, not always record."""
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_calibrate(app, pilot)
        await pilot.press("space")
        assert app.recorder.running is True
        assert app.cal_step == 0
        assert app.notes == []  # the recording tab was not touched

        await pilot.press("space")
        assert app.recorder.running is False
        assert app.cal_step == 1
        assert "low" in app.cal_frames


async def test_a_full_calibration_run_reaches_a_result(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_calibrate(app, pilot)
        for _ in range(3):
            await pilot.press("space")
            await pilot.press("space")
        await pilot.pause()

        assert app.cal_result is not None
        assert set(app.cal_frames) == {"low", "high", "scale"}


async def test_an_unconfident_take_is_offered_not_discarded(tmp_path: Path):
    """The fake recorder returns C4-E4-G4, which is not the melody.

    Nothing is adopted automatically, but the result is kept on screen with
    the option to take it: imperfect settings still beat none.
    """
    store = ProfileStore(tmp_path / "profiles")
    app = make_app(tmp_path, profile=store.create("Ahmed"))
    async with app.run_test() as pilot:
        before = (app.sensitivity, app.pause_sensitivity)
        await goto_calibrate(app, pilot)
        for _ in range(3):
            await pilot.press("space")
            await pilot.press("space")
        await pilot.pause()

        assert app.cal_result.confident is False
        assert app.cal_saved is False
        assert (app.sensitivity, app.pause_sensitivity) == before
        assert app.profile.calibration.is_empty is True

        body = str(app.query_one("#calibrate-body", Static).content)
        assert "keep it anyway" in body
        assert "try again" in body


async def test_y_keeps_an_unconfident_calibration(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles")
    app = make_app(tmp_path, profile=store.create("Ahmed"))
    async with app.run_test() as pilot:
        await goto_calibrate(app, pilot)
        for _ in range(3):
            await pilot.press("space")
            await pilot.press("space")
        await pilot.pause()

        await pilot.press("y")
        await pilot.pause()

        assert app.cal_saved is True
        assert app.profile.calibration.is_empty is False
        assert store.list()[0].calibration.is_empty is False


async def test_keeping_is_only_offered_once(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles")
    app = make_app(tmp_path, profile=store.create("Ahmed"))
    async with app.run_test() as pilot:
        await goto_calibrate(app, pilot)
        for _ in range(3):
            await pilot.press("space")
            await pilot.press("space")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        body = str(app.query_one("#calibrate-body", Static).content)
        assert "saved to your profile" in body
        assert "keep it anyway" not in body


async def test_y_does_nothing_without_a_result(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_calibrate(app, pilot)
        await pilot.press("y")
        await pilot.pause()
        assert app.cal_saved is False


async def test_measurements_are_kept_even_from_a_poor_take(tmp_path: Path):
    """Range and tuning do not depend on the melody being matched."""
    store = ProfileStore(tmp_path / "profiles")
    app = make_app(tmp_path, profile=store.create("Ahmed"))
    async with app.run_test() as pilot:
        await goto_calibrate(app, pilot)
        for _ in range(3):
            await pilot.press("space")
            await pilot.press("space")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        saved = store.list()[0].calibration
        assert saved.tuning_offset_cents is not None
        assert saved.typical_drift_cents is not None


async def test_c_resets_calibration(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_calibrate(app, pilot)
        await pilot.press("space")
        await pilot.press("space")
        assert app.cal_frames

        await pilot.press("c")
        await pilot.pause()
        assert app.cal_step is None
        assert app.cal_frames == {}


async def test_l_plays_the_reference_melody(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_calibrate(app, pilot)
        await pilot.press("l")
        await pilot.pause()

        assert app.player.playing is True
        assert [n.name for n in app.player.played] == [
            "C4", "C4", "G4", "G4", "A4", "A4", "G4"
        ]


async def test_the_reference_is_not_played_into_the_microphone(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_calibrate(app, pilot)
        await pilot.press("space")  # recording
        await pilot.press("l")
        await pilot.pause()

        assert app.player.playing is False
        assert "Finish this step" in str(app.query_one("#hint", Static).content)


async def test_l_does_nothing_on_the_recording_tab(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("l")
        await pilot.pause()
        assert app.player.playing is False


async def test_space_still_records_on_the_recording_tab(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        assert [n.name for n in app.notes] == ["C4", "E4", "G4"]
        assert app.cal_step is None


# -- calibrated settings reaching the detector -----------------------------


async def test_a_calibrated_profile_narrows_detection(tmp_path: Path):
    from humm2melody.profiles import Calibration

    store = ProfileStore(tmp_path / "profiles")
    profile = store.create("Ahmed")
    profile.calibration = Calibration(range_low_midi=47, range_high_midi=66)
    store.save(profile)

    app = make_app(tmp_path, profile=profile)
    async with app.run_test():
        assert app.recorder.fmin > 65.0
        assert app.recorder.fmax < 1200.0


async def test_an_uncalibrated_profile_leaves_detection_wide(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles")
    app = make_app(tmp_path, profile=store.create("Ahmed"))
    async with app.run_test():
        assert app.recorder.fmin == 65.0
        assert app.recorder.fmax == 1200.0


async def test_a_calibrated_tuning_offset_is_carried_as_a_prior(tmp_path: Path):
    from humm2melody.profiles import Calibration

    store = ProfileStore(tmp_path / "profiles")
    profile = store.create("Ahmed")
    profile.calibration = Calibration(tuning_offset_cents=31.0)
    store.save(profile)

    app = make_app(tmp_path, profile=profile)
    async with app.run_test():
        assert app.tuning_prior == 31.0


async def test_switching_to_an_uncalibrated_profile_widens_again(tmp_path: Path):
    """Adopting a profile must not leave the previous voice's bounds behind."""
    from humm2melody.profiles import Calibration, guest

    store = ProfileStore(tmp_path / "profiles")
    calibrated = store.create("Ahmed")
    calibrated.calibration = Calibration(range_low_midi=47, range_high_midi=66)

    app = make_app(tmp_path, profile=calibrated)
    async with app.run_test() as pilot:
        assert app.recorder.fmin > 65.0
        app._apply_profile(guest())
        await pilot.pause()
        assert app.recorder.fmin == 65.0
        assert app.tuning_prior is None


# -- remembering the tab ---------------------------------------------------


async def test_the_active_tab_is_remembered(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles")
    app = make_app(tmp_path, profile=store.create("Ahmed"))
    async with app.run_test() as pilot:
        await goto_calibrate(app, pilot)

    assert store.list()[0].last_tab == "tab-calibrate"


async def test_the_remembered_tab_is_reopened(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles")
    profile = store.create("Ahmed")
    profile.last_tab = "tab-calibrate"
    store.save(profile)

    app = make_app(tmp_path, profile=store.list()[0])
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._active_tab() == "tab-calibrate"


async def test_a_new_profile_opens_on_recording(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles")
    app = make_app(tmp_path, profile=store.create("Ahmed"))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._active_tab() == "tab-record"


async def test_a_guest_does_not_persist_the_tab(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_calibrate(app, pilot)
        assert app.profile.last_tab == "tab-calibrate"  # for this session only
    assert not list((tmp_path / "profiles").glob("*.json"))


async def test_an_unknown_remembered_tab_falls_back(tmp_path: Path):
    """A profile from a future version must not break startup."""
    store = ProfileStore(tmp_path / "profiles")
    profile = store.create("Ahmed")
    profile.last_tab = "tab-that-does-not-exist"
    store.save(profile)

    app = make_app(tmp_path, profile=store.list()[0])
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._active_tab() == "tab-record"


async def test_a_confident_calibration_is_adopted_immediately(tmp_path: Path):
    """And the keep button says so, rather than just going grey."""
    from humm2melody.calibration import REFERENCE_MIDIS
    from tests.test_segment import analyse, legato
    import numpy as np

    def sung():
        parts = []
        for midi in REFERENCE_MIDIS:
            parts.append(legato([midi], hold=0.42, vibrato=0.18))
            parts.append(np.zeros(int(0.16 * SR), dtype=np.float32))
        return np.concatenate(parts).astype(np.float32)

    takes = [
        analyse(legato([47], hold=2.0)),
        analyse(legato([66], hold=2.0)),
        analyse(sung()),
    ]

    class Sequenced(FakeRecorder):
        def __init__(self):
            super().__init__()
            self.index = 0

        def stop(self):
            self.running = False
            frames = takes[min(self.index, 2)]
            self.index += 1
            return frames

    store = ProfileStore(tmp_path / "profiles")
    app = make_app(tmp_path, profile=store.create("Ahmed"))
    app.recorder = Sequenced()
    async with app.run_test() as pilot:
        await goto_calibrate(app, pilot)
        for _ in range(3):
            await pilot.press("space")
            await pilot.press("space")
        await pilot.pause()

        assert app.cal_result.confident is True
        assert app.cal_saved is True
        keep = app.query_one("#cal-keep", Button)
        assert keep.disabled is True
        assert "Saved" in str(keep.label)
        assert store.list()[0].calibration.is_empty is False


async def test_the_keep_button_is_offered_when_not_confident(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles")
    app = make_app(tmp_path, profile=store.create("Ahmed"))
    async with app.run_test() as pilot:
        await goto_calibrate(app, pilot)
        for _ in range(3):
            await pilot.press("space")
            await pilot.press("space")
        await pilot.pause()

        keep = app.query_one("#cal-keep", Button)
        assert app.cal_saved is False
        assert keep.disabled is False
        assert "Keep it" in str(keep.label)


# -- notation --------------------------------------------------------------


async def test_notation_starts_english(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test():
        assert app.notation == "english"
        assert "English" in str(app.query_one("#notation", Static).content)


async def test_n_cycles_notation_and_redraws(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        assert "C4" in str(app.query_one("#sequence", MelodySequence).content)

        await pilot.press("n")
        await pilot.pause()
        assert app.notation == "german"

        for _ in range(2):
            await pilot.press("n")
        await pilot.pause()
        assert app.notation == "sargam"
        assert "Sa4" in str(app.query_one("#sequence", MelodySequence).content)


async def test_notation_does_not_change_the_notes(tmp_path: Path):
    """Spelling is presentation; the detection must be untouched."""
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        before = [(n.midi, n.start, n.end) for n in app.notes]
        for _ in range(3):
            await pilot.press("n")
        await pilot.pause()
        assert [(n.midi, n.start, n.end) for n in app.notes] == before


async def test_notation_is_remembered_per_profile(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles")
    app = make_app(tmp_path, profile=store.create("Ahmed"))
    async with app.run_test() as pilot:
        await pilot.press("n")
        await pilot.pause()
    assert store.list()[0].notation == "german"


# -- editing ---------------------------------------------------------------


async def test_e_enters_edit_mode_and_selects_a_note(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("e")
        await pilot.pause()
        assert app.editing is True
        assert app.selected_note == 0


async def test_editing_needs_notes(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("e")
        await pilot.pause()
        assert app.editing is False


async def test_arrows_move_the_selection(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("e")
        await pilot.press("right")
        await pilot.pause()
        assert app.selected_note == 1
        await pilot.press("left")
        await pilot.press("left")
        await pilot.pause()
        assert app.selected_note == 0  # clamped, not wrapped


async def test_up_and_down_change_the_pitch(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        before = app.notes[0].midi
        await pilot.press("e")
        await pilot.press("up")
        await pilot.pause()
        assert app.notes[0].midi == before + 1
        await pilot.press("down")
        await pilot.press("down")
        await pilot.pause()
        assert app.notes[0].midi == before - 1


async def test_shift_arrows_move_by_an_octave(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        before = app.notes[0].midi
        await pilot.press("e")
        await pilot.press("shift+up")
        await pilot.pause()
        assert app.notes[0].midi == before + 12


async def test_a_transposed_note_keeps_its_tuning_reading(tmp_path: Path):
    """Editing corrects the reading; it must not invent a wild cents figure."""
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        before = app.notes[0].cents_off
        await pilot.press("e")
        await pilot.press("up")
        await pilot.pause()
        assert app.notes[0].cents_off == pytest.approx(before, abs=1.0)


async def test_comma_and_period_move_a_note_in_time(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        note = app.notes[0]
        start, length = note.start, note.duration
        await pilot.press("e")
        await pilot.press("full_stop")
        await pilot.pause()
        assert app.notes[0].start == pytest.approx(start + app.NUDGE)
        assert app.notes[0].duration == pytest.approx(length)


async def test_a_note_cannot_be_moved_before_zero(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("e")
        for _ in range(30):
            await pilot.press("comma")
        await pilot.pause()
        assert app.notes[0].start >= 0.0


async def test_minus_and_equals_change_the_length(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        length = app.notes[0].duration
        await pilot.press("e")
        await pilot.press("equals_sign")
        await pilot.pause()
        assert app.notes[0].duration == pytest.approx(length + app.NUDGE)


async def test_a_note_cannot_be_shortened_to_nothing(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("e")
        for _ in range(40):
            await pilot.press("minus")
        await pilot.pause()
        assert app.notes[0].duration >= app.MIN_DURATION


async def test_the_dials_still_work_outside_edit_mode(tmp_path: Path):
    """The edit keys are the dials' keys; only focus keeps them apart."""
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("full_stop")
        await pilot.pause()
        assert app.pause_sensitivity == 6

        await pilot.press("e")
        await pilot.press("full_stop")
        await pilot.pause()
        assert app.pause_sensitivity == 6  # unchanged: the roll took the key


async def test_escape_leaves_edit_mode(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("e")
        await pilot.press("escape")
        await pilot.pause()
        assert app.editing is False


async def test_edits_are_written_back_to_the_run(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("e")
        await pilot.press("up")
        await pilot.press("escape")  # writing back is deferred until you stop
        await pilot.pause()

        reloaded = app.store.list()[0]
        assert reloaded.notes[0].midi == app.notes[0].midi


async def test_editing_leaves_the_recording_alone(tmp_path: Path):
    """An edit corrects the reading, not the audio it was read from."""
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        run = app.current_session.path
        before = (run / PITCH_CSV).read_bytes()

        await pilot.press("e")
        await pilot.press("up")
        await pilot.pause()

        assert (run / PITCH_CSV).read_bytes() == before


# -- insert, delete, undo --------------------------------------------------


async def test_i_inserts_a_note_after_the_selection(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        before = len(app.notes)
        await pilot.press("e")
        await pilot.press("i")
        await pilot.pause()

        assert len(app.notes) == before + 1
        added = app.notes[app.selected_note]
        assert added.start > app.notes[0].start


async def test_an_inserted_note_takes_the_selected_pitch(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("e")
        pitch = app.notes[0].midi
        await pilot.press("i")
        await pilot.pause()
        assert app.notes[app.selected_note].midi == pitch


async def test_an_inserted_note_can_be_moved_and_retuned(tmp_path: Path):
    """Insert is only useful if the new note is then editable like any other."""
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("e")
        await pilot.press("i")
        await pilot.pause()
        pitch = app.notes[app.selected_note].midi

        await pilot.press("up")
        await pilot.press("full_stop")
        await pilot.pause()
        assert app.notes[app.selected_note].midi == pitch + 1


async def test_notes_stay_in_time_order_after_editing(tmp_path: Path):
    """Moving a note past its neighbour must not leave the table out of order."""
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("e")
        for _ in range(30):
            await pilot.press("full_stop")
        await pilot.pause()

        starts = [n.start for n in app.notes]
        assert starts == sorted(starts)


async def test_the_selection_follows_a_note_that_moved(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("e")
        await pilot.press("up")
        await pilot.pause()
        moved = app.notes[app.selected_note].midi

        for _ in range(30):
            await pilot.press("full_stop")
        await pilot.pause()
        assert app.notes[app.selected_note].midi == moved


async def test_delete_removes_the_selected_note(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        before = [n.name for n in app.notes]
        await pilot.press("e")
        await pilot.press("right")
        await pilot.press("delete")
        await pilot.pause()

        assert len(app.notes) == len(before) - 1
        assert before[1] not in [n.name for n in app.notes]


async def test_backspace_deletes_too(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        before = len(app.notes)
        await pilot.press("e")
        await pilot.press("backspace")
        await pilot.pause()
        assert len(app.notes) == before - 1


async def test_deleting_everything_is_survivable(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("e")
        for _ in range(6):
            await pilot.press("delete")
        await pilot.pause()
        assert app.notes == []
        assert app.selected_note is None


async def test_undo_restores_a_deleted_note(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        before = [n.name for n in app.notes]
        await pilot.press("e")
        await pilot.press("delete")
        await pilot.press("z")
        await pilot.pause()
        assert [n.name for n in app.notes] == before


async def test_undo_reverses_a_pitch_change(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        before = app.notes[0].midi
        await pilot.press("e")
        await pilot.press("up")
        await pilot.press("up")
        await pilot.press("z")
        await pilot.pause()
        assert app.notes[0].midi == before + 1


async def test_undo_walks_back_through_several_edits(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        before = [(n.midi, n.start) for n in app.notes]
        await pilot.press("e")
        await pilot.press("up")
        await pilot.press("i")
        await pilot.press("delete")
        for _ in range(3):
            await pilot.press("z")
        await pilot.pause()
        assert [(n.midi, n.start) for n in app.notes] == before


async def test_redo_reapplies_an_undone_edit(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("e")
        await pilot.press("up")
        raised = app.notes[0].midi
        await pilot.press("z")
        await pilot.press("shift+z")
        await pilot.pause()
        assert app.notes[0].midi == raised


async def test_a_new_edit_clears_the_redo_history(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("e")
        await pilot.press("up")
        await pilot.press("z")
        await pilot.press("down")
        await pilot.press("shift+z")
        await pilot.pause()
        assert app.redo_stack == []


async def test_undo_with_nothing_to_undo_says_so(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("e")
        await pilot.press("z")
        await pilot.pause()
        assert "Nothing to undo" in str(app.query_one("#hint", Static).content)


async def test_a_new_recording_starts_a_fresh_history(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("e")
        await pilot.press("up")
        await pilot.pause()
        assert app.undo_stack

        await record_once(pilot)
        assert app.undo_stack == []


async def test_editing_works_when_nothing_was_detected(tmp_path: Path):
    """The empty transcription is exactly the one worth building by hand."""
    quiet = [PitchFrame(i * 0.02, 0.0, 0.0, 0.0) for i in range(60)]
    app = make_app(tmp_path, frames=quiet)
    async with app.run_test() as pilot:
        await record_once(pilot)
        assert app.notes == []

        await pilot.press("e")
        assert app.editing is True
        await pilot.press("i")
        await pilot.pause()

        assert len(app.notes) == 1
        assert app.notes[0].start == 0.0


async def test_insert_and_delete_reach_the_saved_run(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await record_once(pilot)
        await pilot.press("e")
        await pilot.press("i")
        app._flush_edits()
        await pilot.pause()
        assert len(app.store.list()[0].notes) == len(app.notes)

        await pilot.press("delete")
        app._flush_edits()
        await pilot.pause()
        assert len(app.store.list()[0].notes) == len(app.notes)


# -- clicking a note -------------------------------------------------------


async def test_clicking_the_sequence_selects_that_note(tmp_path: Path):
    from humm2melody.tui import MelodySequence

    app = make_app(tmp_path)
    async with app.run_test(size=(110, 70)) as pilot:
        await record_once(pilot)
        sequence = app.query_one("#sequence", MelodySequence)
        start, end, index = sequence._spans[1]

        await pilot.click(sequence, offset=(start, 0))
        await pilot.pause()
        assert app.selected_note == index
        assert app.editing is True


async def test_clicking_the_sequence_enters_edit_mode(tmp_path: Path):
    """Clicking should not require knowing about `e` first."""
    from humm2melody.tui import MelodySequence

    app = make_app(tmp_path)
    async with app.run_test(size=(110, 70)) as pilot:
        await record_once(pilot)
        assert app.editing is False

        sequence = app.query_one("#sequence", MelodySequence)
        await pilot.click(sequence, offset=(sequence._spans[0][0], 0))
        await pilot.pause()
        assert app.editing is True


async def test_a_clicked_note_can_then_be_edited(tmp_path: Path):
    from humm2melody.tui import MelodySequence

    app = make_app(tmp_path)
    async with app.run_test(size=(110, 70)) as pilot:
        await record_once(pilot)
        sequence = app.query_one("#sequence", MelodySequence)
        await pilot.click(sequence, offset=(sequence._spans[2][0], 0))
        await pilot.pause()

        before = app.notes[2].midi
        await pilot.press("up")
        await pilot.pause()
        assert app.notes[2].midi == before + 1


async def test_a_clicked_note_can_be_deleted(tmp_path: Path):
    from humm2melody.tui import MelodySequence

    app = make_app(tmp_path)
    async with app.run_test(size=(110, 70)) as pilot:
        await record_once(pilot)
        gone = app.notes[1].name
        sequence = app.query_one("#sequence", MelodySequence)
        await pilot.click(sequence, offset=(sequence._spans[1][0], 0))
        await pilot.press("delete")
        await pilot.pause()

        assert len(app.notes) == 2
        assert gone not in [n.name for n in app.notes]


async def test_clicking_the_table_selects_that_row(tmp_path: Path):
    from humm2melody.tui import DetailTable

    app = make_app(tmp_path)
    async with app.run_test(size=(110, 70)) as pilot:
        await record_once(pilot)
        table = app.query_one("#detail", DetailTable)

        await pilot.click(table, offset=(4, DetailTable.HEADER_LINES + 1))
        await pilot.pause()
        assert app.selected_note == 1


async def test_clicking_the_table_header_selects_nothing(tmp_path: Path):
    from humm2melody.tui import DetailTable

    app = make_app(tmp_path)
    async with app.run_test(size=(110, 70)) as pilot:
        await record_once(pilot)
        table = app.query_one("#detail", DetailTable)

        await pilot.click(table, offset=(4, 0))
        await pilot.pause()
        assert app.editing is False


async def test_clicking_the_timeline_selects_that_note(tmp_path: Path):
    from humm2melody.tui import PianoRoll

    app = make_app(tmp_path)
    async with app.run_test(size=(110, 70)) as pilot:
        await record_once(pilot)
        roll = app.query_one("#roll", PianoRoll)
        lo, hi, label_w, width, span = roll._geometry

        target = app.notes[1]
        mid = (target.start + target.end) / 2
        x = label_w + 1 + int(mid / span * width)
        y = hi - target.midi

        await pilot.click(roll, offset=(x, y))
        await pilot.pause()
        assert app.selected_note == 1


async def test_clicking_empty_timeline_selects_nothing(tmp_path: Path):
    from humm2melody.tui import PianoRoll

    app = make_app(tmp_path)
    async with app.run_test(size=(110, 70)) as pilot:
        await record_once(pilot)
        roll = app.query_one("#roll", PianoRoll)
        lo, hi, label_w, width, span = roll._geometry

        # A row with no note on it at all.
        empty = next(m for m in range(lo, hi + 1) if all(n.midi != m for n in app.notes))
        await pilot.click(roll, offset=(label_w + 2, hi - empty))
        await pilot.pause()
        assert app.editing is False


async def test_clicking_the_row_labels_selects_nothing(tmp_path: Path):
    from humm2melody.tui import PianoRoll

    app = make_app(tmp_path)
    async with app.run_test(size=(110, 70)) as pilot:
        await record_once(pilot)
        roll = app.query_one("#roll", PianoRoll)
        await pilot.click(roll, offset=(0, 0))
        await pilot.pause()
        assert app.editing is False


async def test_all_three_views_agree_on_the_selection(tmp_path: Path):
    """Clicking one view should highlight the note in the other two."""
    from humm2melody.tui import DetailTable, MelodySequence

    app = make_app(tmp_path)
    async with app.run_test(size=(110, 70)) as pilot:
        await record_once(pilot)
        table = app.query_one("#detail", DetailTable)
        await pilot.click(table, offset=(4, DetailTable.HEADER_LINES + 2))
        await pilot.pause()

        assert app.selected_note == 2
        sequence = str(app.query_one("#sequence", MelodySequence).content)
        assert f"[{app.notes[2].name}]" in sequence
        # The table holds a Rich Table, so check its cells rather than its text.
        markers = list(table.content.columns[0]._cells)
        assert markers == ["1", "2", "▸"]


async def test_editing_does_not_rebuild_the_sidebar_per_keystroke(tmp_path: Path):
    """Holding an arrow key used to queue more widget work than Textual could drain."""
    app = make_app(tmp_path)
    async with app.run_test(size=(110, 70)) as pilot:
        await record_once(pilot)
        await pilot.press("e")

        rebuilds = 0
        original = app.refresh_sessions

        def counting(*args, **kwargs):
            nonlocal rebuilds
            rebuilds += 1
            return original(*args, **kwargs)

        app.refresh_sessions = counting
        for _ in range(15):
            await pilot.press("up")
        await pilot.pause()

        assert app.notes[app.selected_note].midi > 0
        assert rebuilds == 0  # deferred, not once per key


async def test_pending_edits_are_written_when_editing_ends(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(110, 70)) as pilot:
        await record_once(pilot)
        await pilot.press("e")
        await pilot.press("up")
        await pilot.press("escape")
        await pilot.pause()

        assert app.store.list()[0].notes[0].midi == app.notes[0].midi


async def test_pending_edits_survive_loading_another_run(tmp_path: Path):
    """Switching away must not silently drop what was just edited."""
    app = make_app(tmp_path)
    async with app.run_test(size=(110, 70)) as pilot:
        await record_once(pilot)
        edited = app.current_session.path
        await pilot.press("e")
        await pilot.press("up")
        expected = app.notes[0].midi

        app.load_selected_session()
        await pilot.pause()

        saved = next(r for r in app.store.list() if r.path == edited)
        assert saved.notes[0].midi == expected


# -- the piano keyboard ----------------------------------------------------


async def test_the_keyboard_covers_the_melody_in_whole_octaves(tmp_path: Path):
    from humm2melody.tui import PianoKeys

    app = make_app(tmp_path)
    async with app.run_test(size=(120, 70)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)
        assert piano._low % 12 == 0
        assert piano._high % 12 == 11
        assert piano._low <= min(n.midi for n in app.notes)
        assert piano._high >= max(n.midi for n in app.notes)


async def test_the_keyboard_draws_white_and_black_keys(tmp_path: Path):
    from humm2melody.tui import PianoKeys

    app = make_app(tmp_path)
    async with app.run_test(size=(120, 70)) as pilot:
        await record_once(pilot)
        drawn = str(app.query_one("#piano", PianoKeys).content)
        assert "│" in drawn      # white key separators
        assert "█" in drawn      # black keys
        assert "C4" in drawn     # keys are named inside


async def test_the_keyboard_lights_the_sounding_notes(tmp_path: Path):
    from humm2melody.tui import PianoKeys

    app = make_app(tmp_path)
    async with app.run_test(size=(120, 70)) as pilot:
        await record_once(pilot)
        await pilot.press("p")

        target = app.notes[1]
        app.player.position = (target.start + target.end) / 2
        app._tick_playback()
        assert app.query_one("#piano", PianoKeys)._lit == {target.midi}


async def test_the_keyboard_clears_when_playback_stops(tmp_path: Path):
    from humm2melody.tui import PianoKeys

    app = make_app(tmp_path)
    async with app.run_test(size=(120, 70)) as pilot:
        await record_once(pilot)
        await pilot.press("p")
        app.player.position = app.notes[0].start + 0.01
        app._tick_playback()
        assert app.query_one("#piano", PianoKeys)._lit

        await pilot.press("p")
        await pilot.pause()
        assert app.query_one("#piano", PianoKeys)._lit == set()


async def test_the_keyboard_shows_the_note_being_edited(tmp_path: Path):
    from humm2melody.tui import PianoKeys

    app = make_app(tmp_path)
    async with app.run_test(size=(120, 70)) as pilot:
        await record_once(pilot)
        await pilot.press("e")
        await pilot.press("right")
        await pilot.pause()
        assert app.query_one("#piano", PianoKeys)._lit == {app.notes[1].midi}


async def test_the_keyboard_follows_the_notation_scheme(tmp_path: Path):
    from humm2melody.tui import PianoKeys

    app = make_app(tmp_path)
    async with app.run_test(size=(120, 70)) as pilot:
        await record_once(pilot)
        await pilot.press("n")
        await pilot.press("n")  # solfège
        await pilot.pause()
        # Narrow keys drop the octave number rather than overflow the key.
        assert "Do" in str(app.query_one("#piano", PianoKeys).content)


async def test_the_keyboard_is_as_wide_as_the_timeline(tmp_path: Path):
    from humm2melody.tui import PianoKeys, PianoRoll

    app = make_app(tmp_path)
    async with app.run_test(size=(120, 70)) as pilot:
        await record_once(pilot)
        roll = app.query_one("#roll", PianoRoll)
        piano = app.query_one("#piano", PianoKeys)
        assert piano.region.width == roll.region.width


async def test_the_keyboard_keys_are_tall_and_outlined(tmp_path: Path):
    from humm2melody.tui import PianoKeys

    app = make_app(tmp_path)
    async with app.run_test(size=(120, 70)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)
        lines = str(piano.content).splitlines()
        assert len(lines) >= PianoKeys.BLACK_ROWS + PianoKeys.WHITE_ROWS
        assert all("│" in line for line in lines[: PianoKeys.BLACK_ROWS])
        assert "┴" in lines[PianoKeys.BLACK_ROWS + PianoKeys.WHITE_ROWS]


# -- the second footer and the keys panel ----------------------------------


async def test_the_live_panel_is_a_footer_on_every_tab(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(120, 70)) as pilot:
        await pilot.pause()
        live = app.query_one("#live")
        footer_top = app.query_one("#live").region.y
        assert footer_top > app.query_one(TabbedContent).region.y

        await goto_calibrate(app, pilot)
        assert live.display  # still visible away from the Recording tab


async def test_escape_closes_the_keys_panel(tmp_path: Path):
    from textual.widgets import HelpPanel

    app = make_app(tmp_path)
    async with app.run_test(size=(120, 70)) as pilot:
        await pilot.pause()
        app.action_show_help_panel()
        await pilot.pause()
        assert app.screen.query(HelpPanel)

        await pilot.press("escape")
        await pilot.pause()
        assert not app.screen.query(HelpPanel)


async def test_q_closes_the_keys_panel_before_quitting(tmp_path: Path):
    from textual.widgets import HelpPanel

    app = make_app(tmp_path)
    async with app.run_test(size=(120, 70)) as pilot:
        await pilot.pause()
        app.action_show_help_panel()
        await pilot.pause()

        await pilot.press("q")
        await pilot.pause()
        assert not app.screen.query(HelpPanel)
        assert app.is_running  # closed the panel, did not quit


async def test_the_playhead_sweeps_the_whole_timeline_at_any_tempo(tmp_path: Path):
    """Position is in played seconds; the timeline is in the notes' seconds."""
    app = make_app(tmp_path)
    async with app.run_test(size=(120, 70)) as pilot:
        await record_once(pilot)
        span = max(n.end for n in app.notes)

        for _ in range(4):  # tempo 5 -> 9, i.e. 2x
            await pilot.press("greater_than_sign")
        await pilot.press("p")
        await pilot.pause()

        # Playing 2x means the audio ends at half the score duration.
        app.player.position = span / 2
        app._tick_playback()
        roll = app.query_one("#roll", PianoRoll)
        assert roll._playhead == pytest.approx(span, abs=0.01)


async def test_tempo_reaches_the_player(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(120, 70)) as pilot:
        await record_once(pilot)
        for _ in range(4):
            await pilot.press("less_than_sign")
        await pilot.press("p")
        await pilot.pause()
        assert app.player.speed == pytest.approx(0.50)


async def test_the_notes_lit_follow_the_tempo(tmp_path: Path):
    from humm2melody.tui import PianoKeys

    app = make_app(tmp_path)
    async with app.run_test(size=(120, 70)) as pilot:
        await record_once(pilot)
        for _ in range(4):
            await pilot.press("greater_than_sign")
        await pilot.press("p")

        target = app.notes[1]
        app.player.position = ((target.start + target.end) / 2) / 2.0
        app._tick_playback()
        assert app.query_one("#piano", PianoKeys)._lit == {target.midi}


# -- composing on the keyboard ---------------------------------------------


def _key_width(piano) -> int:
    return (piano.size.width - 2) // len(piano._white_keys())


def _white_hit(piano, index: int) -> tuple[int, int]:
    """A point inside the body of the nth white key."""
    width = _key_width(piano)
    return (index * width + width // 2 + 1, piano.BLACK_ROWS + 2)


def _black_hit(piano, white_index: int) -> tuple[int, int]:
    """A point on the black key sitting to the right of the nth white key."""
    return ((white_index + 1) * _key_width(piano) + 1, 1)


def _hit_for(piano, midi: int) -> tuple[int, int]:
    """Where to click for a given pitch, in the layout as it stands now.

    Recomputed per click, because adding a note can widen the keyboard's
    range and shift every key along.
    """
    return _white_hit(piano, piano._white_keys().index(midi))


async def test_clicking_a_white_key_adds_that_note(tmp_path: Path):
    from humm2melody.tui import PianoKeys

    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)
        before = len(app.notes)

        wanted = piano._white_keys()[2]
        piano.on_click(_Click(*_white_hit(piano, 2)))
        await pilot.pause()

        assert len(app.notes) == before + 1
        assert app.notes[app.selected_note].midi == wanted


async def test_clicking_a_black_key_adds_a_sharp(tmp_path: Path):
    from humm2melody.tui import PianoKeys

    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)

        wanted = piano._white_keys()[0] + 1  # the C sharp
        piano.on_click(_Click(*_black_hit(piano, 0)))
        await pilot.pause()
        assert app.notes[app.selected_note].midi == wanted


async def test_the_lower_half_of_a_black_key_hits_the_white_one(tmp_path: Path):
    """Like a real keyboard: below the black keys, the white key takes it."""
    from humm2melody.tui import PianoKeys

    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)
        x, _ = _black_hit(piano, 0)
        below = piano.key_at(x, piano.BLACK_ROWS + 2)
        assert below in (piano._white_keys()[0], piano._white_keys()[1])
        assert below % 12 in (0, 2)  # a white key, not the sharp above it


async def test_composing_a_phrase_by_clicking(tmp_path: Path):
    from humm2melody.tui import PianoKeys

    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        await pilot.press("c")  # start from an empty transcription
        await pilot.pause()
        piano = app.query_one("#piano", PianoKeys)

        wanted = [piano._white_keys()[i] for i in (0, 1, 2)]
        for midi in wanted:
            piano.on_click(_Click(*_hit_for(piano, midi)))
            await pilot.pause()

        assert [n.midi for n in app.notes] == wanted
        starts = [n.start for n in app.notes]
        assert starts == sorted(starts)  # laid out in the order they were played


async def test_clicking_a_key_starts_editing(tmp_path: Path):
    from humm2melody.tui import PianoKeys

    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        assert app.editing is False
        piano = app.query_one("#piano", PianoKeys)
        piano.on_click(_Click(*_white_hit(piano, 1)))
        await pilot.pause()
        assert app.editing is True


async def test_a_clicked_key_is_sounded(tmp_path: Path):
    from humm2melody.tui import PianoKeys

    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)
        wanted = piano._white_keys()[3]
        piano.on_click(_Click(*_white_hit(piano, 3)))
        await pilot.pause()

        assert app.player.playing is True
        assert [n.midi for n in app.player.played] == [wanted]


async def test_a_clicked_note_can_be_undone(tmp_path: Path):
    from humm2melody.tui import PianoKeys

    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        before = [n.midi for n in app.notes]
        piano = app.query_one("#piano", PianoKeys)
        piano.on_click(_Click(*_white_hit(piano, 2)))
        await pilot.pause()

        await pilot.press("z")
        await pilot.pause()
        assert [n.midi for n in app.notes] == before


async def test_clicking_outside_the_keys_adds_nothing(tmp_path: Path):
    from humm2melody.tui import PianoKeys

    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        piano = app.query_one("#piano", PianoKeys)
        before = len(app.notes)
        piano.on_click(_Click(0, 0))            # the border
        piano.on_click(_Click(2, 99))           # below the keys
        await pilot.pause()
        assert len(app.notes) == before


async def test_v_cycles_the_voice_and_reaches_playback(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 60)) as pilot:
        await record_once(pilot)
        assert app.voice == "pure"

        await pilot.press("v")
        await pilot.pause()
        assert app.voice == "rich"

        await pilot.press("p")
        await pilot.pause()
        assert app.player.voice == "rich"


async def test_the_voice_is_remembered_per_profile(tmp_path: Path):
    store = ProfileStore(tmp_path / "profiles")
    app = make_app(tmp_path, profile=store.create("Ahmed"))
    async with app.run_test(size=(156, 60)) as pilot:
        await pilot.press("v")
        await pilot.press("v")
        await pilot.pause()
    assert store.list()[0].voice == "chord"


# -- fitting the terminal --------------------------------------------------


def long_take(count: int = 30) -> list[PitchFrame]:
    """A transcription with far more notes than fit on screen."""
    frames: list[PitchFrame] = []
    step = 512 / SR
    t = 0.0
    for i in range(count):
        for _ in range(int(0.25 / step)):
            frames.append(PitchFrame(t, midi_to_hz(55 + i % 14), 0.95, 0.2))
            t += step
        for _ in range(int(0.15 / step)):
            frames.append(PitchFrame(t, 0.0, 0.0, 0.0))
            t += step
    return frames


async def test_a_long_transcription_does_not_grow_the_app(tmp_path: Path):
    """The window should match the terminal however many notes there are."""
    app = make_app(tmp_path, frames=long_take())
    async with app.run_test(size=(156, 50)) as pilot:
        await record_once(pilot)
        assert len(app.notes) > 20
        screen = app.screen
        assert screen.virtual_size.height <= screen.region.height


async def test_a_long_table_scrolls_inside_itself(tmp_path: Path):
    app = make_app(tmp_path, frames=long_take())
    async with app.run_test(size=(156, 50)) as pilot:
        await record_once(pilot)
        pane = app.query_one("#detail-pane")
        assert pane.virtual_size.height > pane.region.height
        assert pane.show_vertical_scrollbar


async def test_a_short_transcription_still_fits(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 50)) as pilot:
        await record_once(pilot)
        screen = app.screen
        assert screen.virtual_size.height <= screen.region.height


async def test_the_app_fits_a_short_terminal(tmp_path: Path):
    app = make_app(tmp_path, frames=long_take())
    async with app.run_test(size=(120, 30)) as pilot:
        await record_once(pilot)
        screen = app.screen
        assert screen.virtual_size.height <= screen.region.height


async def test_the_table_pane_is_wide_enough_for_the_table(tmp_path: Path):
    """A scroll container cannot size itself to its content; `auto` collapses it."""
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 50)) as pilot:
        await record_once(pilot)
        pane = app.query_one("#detail-pane")
        table = app.query_one("#detail")
        assert table.region.width >= 30           # not squashed to a sliver
        assert pane.region.width >= table.region.width


async def test_the_table_stays_readable_in_every_notation(tmp_path: Path):
    """Solfège and Sargam spell notes longer than English does."""
    app = make_app(tmp_path)
    async with app.run_test(size=(156, 50)) as pilot:
        await record_once(pilot)
        pane = app.query_one("#detail-pane")
        for _ in range(4):
            await pilot.press("n")
            await pilot.pause()
            assert app.query_one("#detail").region.width <= pane.region.width
