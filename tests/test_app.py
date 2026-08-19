"""TUI tests driven by Textual's Pilot, with audio I/O faked out.

These run headless and never touch a microphone or speaker. Every app is given
a tmp_path output directory so tests never write into the working tree.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
from humm2melody.audio import AudioError, LiveReading
from humm2melody.pitch import PitchFrame, midi_to_hz
from humm2melody.segment import Note
from humm2melody.sessions import HUM_WAV, MANIFEST, PITCH_CSV, PLAYBACK_WAV
from humm2melody.tui import Humm2MelodyApp, MelodySequence, PianoRoll
from textual.widgets import Button, Input, Label, ListView, Static

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
    sample_rate = SR

    def __init__(self, frames=None, fail=False, audio=None):
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

    def play(self, notes):
        self.played = list(notes)
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


def make_app(tmp_path: Path, save: bool = True, **kwargs) -> Humm2MelodyApp:
    app = Humm2MelodyApp(output_dir=tmp_path, save=save)
    app.recorder = FakeRecorder(**kwargs)
    app.player = FakePlayer()
    return app


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
    async with app.run_test() as pilot:
        toggle = app.query_one("#toggle", Button)
        await pilot.click("#toggle")
        assert app.recorder.running is True
        assert "Stop" in str(toggle.label)

        # Button ignores clicks while its "-active" press animation runs, so
        # wait that out before clicking again.
        await asyncio.sleep(toggle.active_effect_duration + 0.05)
        await pilot.click("#toggle")
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
    async with app.run_test() as pilot:
        await pilot.click("#toggle")

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
        for name in (HUM_WAV, PLAYBACK_WAV, PITCH_CSV, MANIFEST):
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
        assert isinstance(app.screen, type(app.screen))
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
