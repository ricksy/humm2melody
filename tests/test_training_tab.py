"""Training tab tests: the loop from target note to score, driven by Pilot.

The recorder is faked, so a "sung" note here is a canned pitch track. That is
enough to prove the wiring: the target reaches the display, the frames reach
the scorer, and the score reaches the display again.
"""

from __future__ import annotations

from pathlib import Path

from humm2melody.pitch import PitchFrame, midi_to_hz
from humm2melody.profiles import Calibration, ProfileStore
from humm2melody.training import build_exercises
from humm2melody.tui import PitchBar
from textual.widgets import Static, Tabs

from tests.test_app import FakeRecorder, make_app

SR = 22050


def sung(midi: float, seconds: float = 1.6, *, start: float = 0.0):
    """A steady held note, the way a well-behaved singer would arrive."""
    step = 512 / SR
    freq = midi_to_hz(midi)
    return [
        PitchFrame(start + i * step, freq, 0.95, 0.2)
        for i in range(int(seconds / step))
    ]


async def goto_train(app, pilot) -> None:
    await pilot.pause()
    app.query_one(Tabs).focus()
    await pilot.press("right", "right")
    await pilot.pause()
    assert app._active_tab() == "tab-train"


def head(app) -> str:
    return str(app.query_one("#train-head", Static).content)


def foot(app) -> str:
    return str(app.query_one("#train-foot", Static).content)


def hint(app) -> str:
    return str(app.query_one("#hint", Static).content)


# -- what the tab shows before you sing ------------------------------------


async def test_the_tab_names_the_note_to_sing(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        assert "Sing" in head(app)
        assert "C4" in head(app)  # the uncalibrated default centre


async def test_it_tells_you_how_to_start(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        assert "hear the note" in foot(app)


async def test_the_bar_shows_the_green_band_before_you_sing(tmp_path: Path):
    """The target range is visible up front, not only once you are singing."""
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        assert "░" in str(app.query_one("#train-bar", PitchBar).content)


async def test_exercises_follow_the_calibrated_range(tmp_path: Path):
    """A low voice must not be asked to sing middle C all session."""
    store = ProfileStore(tmp_path / "profiles")
    profile = store.create("Low")
    profile.calibration = Calibration(range_low_midi=40, range_high_midi=52)
    store.save(profile)

    app = make_app(tmp_path, profile=profile)
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        assert app.training.target < 60


async def test_the_notation_choice_reaches_the_target(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        app.notation = "solfege"
        app._refresh_training()
        await pilot.pause()
        assert "Do4" in head(app)


# -- singing ---------------------------------------------------------------


async def test_space_starts_listening(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        await pilot.press("space")
        await pilot.pause()
        assert app.recorder.running is True
        assert "stop" in foot(app)


async def test_singing_the_target_scores_well(tmp_path: Path):
    app = make_app(tmp_path)
    app.recorder = FakeRecorder(frames=sung(60))
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        await pilot.press("space")
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()

        assert app.training.scores[0] > 80
        assert "score" in foot(app)


async def test_singing_the_wrong_note_scores_badly(tmp_path: Path):
    app = make_app(tmp_path)
    app.recorder = FakeRecorder(frames=sung(64))  # a major third too high
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        await pilot.press("space")
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()

        assert app.training.scores[0] == 0
        assert "too high" in foot(app).lower()


async def test_a_finished_attempt_reports_which_way_you_were_off(tmp_path: Path):
    app = make_app(tmp_path)
    app.recorder = FakeRecorder(frames=sung(59.0))  # a semitone flat
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        await pilot.press("space")
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        assert "too low" in foot(app).lower()


async def test_stars_appear_once_you_have_sung(tmp_path: Path):
    app = make_app(tmp_path)
    app.recorder = FakeRecorder(frames=sung(60))
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        await pilot.press("space")
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        assert "★" in head(app)


async def test_silence_is_not_scored(tmp_path: Path):
    """Stopping without singing must not put a zero on the board."""
    app = make_app(tmp_path)
    app.recorder = FakeRecorder(frames=[PitchFrame(0.1, 0.0, 0.0, 0.0)])
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        await pilot.press("space")
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        assert app.training.scores == {}


# -- moving through the exercise -------------------------------------------


async def test_f_moves_to_the_next_note(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        await pilot.press("x")  # the hold exercise has only one note
        await pilot.pause()
        first = app.training.target
        await pilot.press("f")
        await pilot.pause()
        assert app.training.target != first


async def test_b_goes_back(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        await pilot.press("x")
        await pilot.pause()
        first = app.training.target
        await pilot.press("f")
        await pilot.press("b")
        await pilot.pause()
        assert app.training.target == first


async def test_back_from_the_first_note_stays_put(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        await pilot.press("b")
        await pilot.pause()
        assert app.training.index == 0


async def test_x_changes_exercise(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        titles = {head(app).split("\n")[0]}
        for _ in range(len(build_exercises()) - 1):
            await pilot.press("x")
            await pilot.pause()
            titles.add(head(app).split("\n")[0])
        assert len(titles) == len(build_exercises())


async def test_changing_exercise_starts_the_score_over(tmp_path: Path):
    app = make_app(tmp_path)
    app.recorder = FakeRecorder(frames=sung(60))
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        await pilot.press("space")
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        await pilot.press("x")
        await pilot.pause()
        assert app.training.scores == {}


async def test_the_average_appears_after_a_score(tmp_path: Path):
    app = make_app(tmp_path)
    app.recorder = FakeRecorder(frames=sung(60))
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        await pilot.press("space")
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        assert "average" in head(app)


async def test_moving_on_while_singing_is_refused(tmp_path: Path):
    """Changing the target mid-note would score you against the wrong one."""
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        await pilot.press("x")
        await pilot.pause()
        target = app.training.target
        await pilot.press("space")
        await pilot.press("f")
        await pilot.pause()
        assert app.training.target == target


# -- hearing the note ------------------------------------------------------


def dominant_midi(buffer, rate=SR) -> float:
    """The pitch of a rendered buffer, read back off its spectrum."""
    import numpy as np
    from humm2melody.pitch import hz_to_midi

    spectrum = np.abs(np.fft.rfft(buffer * np.hanning(buffer.size)))
    peak = np.fft.rfftfreq(buffer.size, 1 / rate)[int(np.argmax(spectrum))]
    return hz_to_midi(peak)


async def test_l_holds_the_target_note(tmp_path: Path):
    """It is a drone, not a preview: you sing against it."""
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        await pilot.press("l")
        await pilot.pause()
        assert app.player.looping is True
        assert round(dominant_midi(app.player.buffer)) == app.training.target
        assert "stop the tone" in foot(app)


async def test_l_again_stops_the_tone(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        await pilot.press("l")
        await pilot.press("l")
        await pilot.pause()
        assert app.player.playing is False
        assert app.drone_midi is None
        assert "hear the note" in foot(app)


async def test_the_tone_keeps_playing_while_you_sing(tmp_path: Path):
    """The whole point: hum against a held reference instead of from memory."""
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        await pilot.press("l")
        await pilot.press("space")
        await pilot.pause()
        assert app.recorder.running is True
        assert app.player.playing is True
        assert app.drone_midi == app.training.target


async def test_the_tone_follows_the_target(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        await pilot.press("x")  # an exercise with more than one note
        await pilot.press("l")
        await pilot.pause()
        await pilot.press("f")
        await pilot.pause()
        assert app.drone_midi == app.training.target
        assert round(dominant_midi(app.player.buffer)) == app.training.target


async def test_leaving_the_tab_silences_the_tone(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        await pilot.press("l")
        await pilot.pause()
        await pilot.press("left")
        await pilot.pause()
        assert app.drone_midi is None
        assert app.player.playing is False


async def test_the_tone_warns_about_speakers(tmp_path: Path):
    """With no headphones the microphone hears the tone and scores it as you."""
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        await pilot.press("l")
        await pilot.pause()
        assert "headphones" in hint(app).lower()


# -- the training keys stay on the training tab ----------------------------


async def test_f_does_nothing_on_the_recording_tab(tmp_path: Path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        before = app.training.index
        await pilot.press("f")
        await pilot.pause()
        assert app.training.index == before


async def test_space_on_the_training_tab_does_not_save_a_run(tmp_path: Path):
    """Training is practice, not a take; nothing lands in the output folder."""
    app = make_app(tmp_path, frames=sung(60))
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        await pilot.press("space")
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        assert list(tmp_path.glob("2*")) == []


# -- damping the live reading ----------------------------------------------


async def test_the_bar_ignores_a_single_wild_frame(tmp_path: Path):
    """One octave-flipped frame must not throw the tip across the screen."""
    frames = sung(60, 0.6)
    frames[8] = PitchFrame(frames[8].time, midi_to_hz(72), 0.95, 0.2)
    app = make_app(tmp_path)
    app.recorder = FakeRecorder(frames=frames)
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        await pilot.press("space")
        await pilot.pause()
        assert abs(app.attempt.eased) < 50


async def test_a_wild_frame_does_not_cost_you_the_score(tmp_path: Path):
    frames = sung(60, 1.6)
    frames[20] = PitchFrame(frames[20].time, midi_to_hz(72), 0.95, 0.2)
    app = make_app(tmp_path)
    app.recorder = FakeRecorder(frames=frames)
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        await pilot.press("space")
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        assert app.training.scores[0] > 80


async def test_the_detector_searches_the_whole_voice_not_just_the_target(
    tmp_path: Path,
):
    """A window around the target would trap a singer who is outside it.

    Narrowing the search rules out the octave, which is tempting. But a voice
    outside the window cannot be reported at all -- only mis-reported at the
    nearest edge, which reads as "always too low" or "always too high" and
    gives the singer nothing to correct. Being far off is the condition this
    tab exists to treat, so the search has to reach that far.
    """
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        before = (app.recorder.fmin, app.recorder.fmax)
        await pilot.press("space")
        await pilot.pause()
        assert (app.recorder.fmin, app.recorder.fmax) == before
        assert app.recorder.fmin < midi_to_hz(app.training.target - 12)
        assert app.recorder.fmax > midi_to_hz(app.training.target + 12)


async def test_leaving_the_tab_mid_note_ends_the_attempt(tmp_path: Path):
    """Otherwise the mic stays open with the detector aimed at nothing."""
    app = make_app(tmp_path, frames=sung(60))
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        await pilot.press("space")
        await pilot.pause()
        await pilot.press("left")
        await pilot.pause()
        assert app.recorder.running is False


async def test_each_attempt_starts_on_the_close_up_scale(tmp_path: Path):
    """Last go being an octave out must not leave the next one zoomed out."""
    app = make_app(tmp_path)
    app.recorder = FakeRecorder(frames=sung(72))  # an octave high
    async with app.run_test() as pilot:
        await goto_train(app, pilot)
        await pilot.press("space")
        await pilot.pause()
        assert app.query_one("#train-bar", PitchBar).span > 150.0
        await pilot.press("space")
        await pilot.pause()

        app.recorder = FakeRecorder(frames=sung(60))
        await pilot.press("space")
        await pilot.pause()
        assert app.query_one("#train-bar", PitchBar).span == 150.0


# -- the bar ---------------------------------------------------------------


class _Capture(PitchBar):
    """A bar that renders into a string instead of onto a screen."""

    lines: list[str] = []

    def update(self, text):
        self.lines = str(text).split("\n")


def bar_rows(cents, tolerance=35.0, width=20):
    """Render a bar off-screen and hand back its lines."""
    bar = _Capture()
    bar.show(cents, tolerance, width)
    return [line for line in bar.lines if line.strip()]


def test_the_band_is_several_rows_tall():
    """A hairline band is unreadable while you are singing at it."""
    green = [row for row in bar_rows(None) if "░" in row]
    assert len(green) >= 3


def test_the_tip_sits_above_the_band_when_sharp():
    rows = bar_rows(90)
    tip = next(i for i, row in enumerate(rows) if "█" in row)
    band = next(i for i, row in enumerate(rows) if "░" in row)
    assert tip < band  # rows run sharp at the top


def test_the_tip_sits_below_the_band_when_flat():
    rows = bar_rows(-90)
    tip = next(i for i, row in enumerate(rows) if "█" in row)
    band = next(i for i, row in enumerate(rows) if "░" in row)
    assert tip > band


def test_the_tip_is_inside_the_band_when_in_tune():
    rows = bar_rows(10)
    assert "◄" in next(row for row in rows if "█" in row)
    assert all("░" in row or "█" in row for row in rows if "◄" in row)


def test_the_scale_zooms_out_to_keep_the_tip_visible():
    """A pinned tip says "too high" and nothing else -- no gradient to follow."""
    rows = bar_rows(1200)
    tip = next(i for i, row in enumerate(rows) if "█" in row)
    assert "+1200" in rows[tip]
    assert 0 < tip < len(rows) - 1  # on the scale, not jammed against an edge


def test_the_scale_zooms_back_in_when_the_voice_settles():
    bar = _Capture()
    bar.show(1200, 35.0, 20, 15)
    wide = bar.span
    for _ in range(20):
        bar.show(10, 35.0, 20, 15)
    assert bar.span < wide
    assert bar.span == 150.0


def test_the_scale_does_not_flap_between_two_zooms():
    """Hovering on a boundary must not make the whole bar jump every frame."""
    bar = _Capture()
    bar.show(290, 35.0, 20, 15)  # settle on whatever scale that needs
    spans = []
    for cents in (290, 160, 290, 160, 290, 160):
        bar.show(cents, 35.0, 20, 15)
        spans.append(bar.span)
    assert len(set(spans)) == 1


def test_further_out_than_the_widest_scale_still_shows_which_way():
    up = next(row for row in bar_rows(2400) if "█" in row)
    down = next(row for row in bar_rows(-2400) if "█" in row)
    assert "▲" in up and "+2400" in up
    assert "▼" in down and "-2400" in down


def test_the_bar_is_quiet_until_you_sing():
    assert not any("█" in row for row in bar_rows(None))


def test_the_bar_takes_the_width_it_is_given():
    assert bar_rows(None, width=48)[0].count("·") == 48
