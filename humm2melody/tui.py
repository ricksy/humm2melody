"""The Textual interface: record, see the melody, hear it back, keep every run."""

from __future__ import annotations

import math
from pathlib import Path

from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
    TabbedContent,
    TabPane,
)

from .audio import AudioError, Recorder
from .pitch import NOTE_NAMES
from .playback import MIX_DEFAULT, MIX_MAX, MIX_MIN, Player, mix_hum_with_tones
from .profiles import DEFAULT_PROFILE_DIR, Profile, ProfileStore, guest
from .pitch import PitchFrame
from .segment import (
    PAUSE_DEFAULT,
    PAUSE_MAX,
    PAUSE_MIN,
    SENSITIVITY_DEFAULT,
    SENSITIVITY_MAX,
    SENSITIVITY_MIN,
    Note,
    segment_with_sensitivity,
)
from .sessions import (
    DEFAULT_OUTPUT_DIR,
    Session,
    SessionStore,
    read_pitch_track,
    read_wav,
)

MAX_ROLL_ROWS = 32
"""Cap the piano roll's pitch range so one stray octave can't blow up the view."""

ACCENT = "#7dd3fc"
ACCENT_SHARP = "#818cf8"
HIGHLIGHT = "#fbbf24"


def _is_black_key(midi: int) -> bool:
    return "#" in NOTE_NAMES[midi % 12]


def _note_name(midi: int) -> str:
    return NOTE_NAMES[midi % 12] + str(midi // 12 - 1)


class ActionButton(Button):
    """A button that never takes focus.

    Buttons activate on space when focused, which would otherwise shadow the
    app-level space binding and make the key mean different things depending
    on what was clicked last.
    """

    can_focus = False


class Dial(Static):
    """A labelled 1-9 dial with a caption describing the current setting."""

    def render_dial(
        self, label: str, keys: str, level: int, captions: tuple[str, str, str]
    ) -> None:
        low, mid, high = captions
        text = Text(f"{label:<11}", style="bold")
        text.append(f"{keys}  ", style="dim")
        text.append("[", style="dim")
        for step in range(SENSITIVITY_MIN, SENSITIVITY_MAX + 1):
            text.append(
                "●" if step == level else "·",
                style=f"bold {HIGHLIGHT}" if step == level else "grey30",
            )
        text.append("]", style="dim")
        text.append(f"  {level}/{SENSITIVITY_MAX}   ", style="bold")
        text.append(low if level < 5 else (mid if level == 5 else high), style="dim")
        self.update(text)


class SensitivityDial(Dial):
    """How finely to distinguish pitches."""

    def show(self, level: int) -> None:
        self.render_dial(
            "Pitch",
            "[ ]",
            level,
            (
                "forgiving — small wobbles read as one note",
                "balanced",
                "literal — small differences become separate notes",
            ),
        )


class PauseDial(Dial):
    """How eagerly to split notes in time."""

    def show(self, level: int) -> None:
        self.render_dial(
            "Pauses",
            "< >",
            level,
            (
                "only real silence separates notes",
                "balanced",
                "a fresh attack alone starts a new note",
            ),
        )


class MixDial(Dial):
    """Balance between your recording and the tones, for the overlay."""

    def show(self, level: int) -> None:
        self.render_dial(
            "Mix",
            "- +",
            level,
            (
                "mostly your hum, tones underneath",
                "balanced — favours your voice",
                "mostly tones, hum underneath",
            ),
        )


class LevelMeter(Static):
    """Input level as a block-character bar."""

    def show(self, level: float) -> None:
        width = max(10, self.size.width - 2)
        filled = int(round(min(1.0, max(0.0, level)) * width))
        bar = Text()
        for i in range(width):
            if i >= filled:
                bar.append("─", style="dim")
            elif i < width * 0.7:
                bar.append("█", style="green")
            elif i < width * 0.9:
                bar.append("█", style="yellow")
            else:
                bar.append("█", style="red")
        self.update(bar)


class NoteReadout(Static):
    """The current note, its tuning offset, and the raw frequency."""

    def show(self, note: str, cents: float, freq: float, elapsed: float) -> None:
        text = Text()
        if not note:
            text.append("  ——  ", style="bold dim")
            text.append("   listening…", style="dim")
        else:
            text.append(f"  {note:<4}", style=f"bold {ACCENT}")
            direction = "♯" if cents > 0 else "♭"
            if abs(cents) < 12:
                text.append("  in tune", style="green")
            else:
                text.append(f"  {direction}{abs(cents):.0f}¢", style="yellow")
            text.append(f"   {freq:6.1f} Hz", style="dim")
        text.append(f"   ·   {elapsed:5.1f}s", style="dim")
        self.update(text)

    def idle(self, message: str) -> None:
        self.update(Text(f"  {message}", style="dim"))


class PianoRoll(Static):
    """Notes laid out as pitch (rows) against time (columns)."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._notes: list[Note] = []
        self._playhead: float | None = None
        self._head_col: int | None = None

    def show(self, notes: list[Note]) -> None:
        self._notes = notes
        self._playhead = None
        self._head_col = None
        self.refresh_roll()

    def set_playhead(self, position: float | None) -> None:
        """Move the playhead, redrawing only when it changes column.

        The playhead ticks far faster than it crosses character cells, and a
        redraw rebuilds every row. Skipping the no-op redraws keeps the UI from
        competing with the audio callback for the interpreter.
        """
        self._playhead = position
        col = self._playhead_column()
        if col == self._head_col:
            return
        self._head_col = col
        self.refresh_roll()

    def _playhead_column(self) -> int | None:
        if self._playhead is None or not self._notes:
            return None
        span = max(n.end for n in self._notes)
        if span <= 0:
            return None
        width = max(20, self.size.width - 6)
        return min(width - 1, int(self._playhead / span * width))

    def on_resize(self) -> None:
        self.refresh_roll()

    def refresh_roll(self) -> None:
        notes = self._notes
        if not notes:
            self.update(Text(""))
            return

        span = max(n.end for n in notes)
        if span <= 0:
            self.update(Text(""))
            return

        label_w = 5
        width = max(20, self.size.width - label_w - 2)

        head_col = None
        if self._playhead is not None:
            head_col = min(width - 1, int(self._playhead / span * width))

        lo = min(n.midi for n in notes)
        hi = max(n.midi for n in notes)
        if hi - lo + 1 > MAX_ROLL_ROWS:
            hi = lo + MAX_ROLL_ROWS - 1

        out = Text()
        for midi in range(hi, lo - 1, -1):
            style = "dim" if _is_black_key(midi) else "bold"
            out.append(f"{_note_name(midi):>{label_w - 1}} ", style=style)
            out.append("│", style="dim")

            cells: list[Note | None] = [None] * width
            for n in notes:
                if n.midi != midi:
                    continue
                start = int(n.start / span * width)
                end = max(start + 1, math.ceil(n.end / span * width))
                for c in range(start, min(end, width)):
                    cells[c] = n

            for col, cell in enumerate(cells):
                on_head = col == head_col
                if cell is None:
                    out.append("│" if on_head else "·",
                               style=HIGHLIGHT if on_head else "grey30")
                elif on_head:
                    out.append("█", style=HIGHLIGHT)
                else:
                    out.append(
                        "█", style=ACCENT_SHARP if _is_black_key(midi) else ACCENT
                    )
            out.append("\n")

        # Time axis.
        out.append(" " * (label_w - 1) + " └", style="dim")
        out.append("─" * width + "\n", style="dim")

        step = _tick_step(span)
        axis = [" "] * width
        t = 0.0
        while t <= span:
            col = int(t / span * width)
            label = f"{t:g}s"
            if col + len(label) <= width:
                axis[col : col + len(label)] = list(label)
            t += step
        out.append(" " * (label_w + 1), style="dim")
        out.append("".join(axis), style="dim")
        self.update(out)


def _tick_step(span: float) -> float:
    """Pick a readable spacing for the time axis."""
    for step in (0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0):
        if span / step <= 12:
            return step
    return 120.0


class MelodySequence(Static):
    """The playable note sequence, with the sounding note highlighted."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._notes: list[Note] = []
        self._active: int | None = None

    def show(self, notes: list[Note]) -> None:
        self._notes = notes
        self._active = None
        self._redraw()

    def set_active(self, index: int | None) -> None:
        if index != self._active:
            self._active = index
            self._redraw()

    def _redraw(self) -> None:
        if not self._notes:
            self.update(Text(""))
            return
        text = Text("Play this:  ", style="bold")
        for i, n in enumerate(self._notes):
            if i:
                gap = n.start - self._notes[i - 1].end
                text.append("  ·  " if gap > 0.25 else "  ", style="dim")
            if i == self._active:
                text.append(f" {n.name} ", style=f"bold black on {HIGHLIGHT}")
            else:
                text.append(n.name, style=f"bold {ACCENT}")
        self.update(text)


def _detail_table(notes: list[Note]) -> Table:
    table = Table(expand=False, pad_edge=False, header_style="bold dim")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Note", style=f"bold {ACCENT}")
    table.add_column("Start", justify="right")
    table.add_column("Length", justify="right")
    table.add_column("Hz", justify="right", style="dim")
    table.add_column("Tuning", justify="right")

    for i, n in enumerate(notes, start=1):
        cents = n.cents_off
        if abs(cents) < 12:
            tuning = Text("on pitch", style="green")
        else:
            tuning = Text(
                f"{'+' if cents > 0 else '−'}{abs(cents):.0f}¢", style="yellow"
            )
        table.add_row(
            str(i),
            n.name,
            f"{n.start:.2f}s",
            f"{n.duration:.2f}s",
            f"{n.freq:.1f}",
            tuning,
        )
    return table


DIALOG_CSS = """
    NameScreen, ConfirmScreen, ProfileScreen { align: center middle; }
    #dialog {
        width: 60;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #dialog Label { margin-bottom: 1; }
    #dialog Input { margin-bottom: 1; }
    #dialog Horizontal { height: auto; align: right middle; }
    #dialog Button { margin-left: 2; }
"""


class NameScreen(ModalScreen[str | None]):
    """Ask for a name. Used for both run labels and profile names."""

    CSS = DIALOG_CSS
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        title: str,
        value: str = "",
        placeholder: str = "",
        confirm_label: str = "Save",
    ) -> None:
        super().__init__()
        self.title_text = title
        self.value = value
        self.placeholder = placeholder
        self.confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.title_text)
            yield Input(value=self.value, placeholder=self.placeholder, id="label")
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button(self.confirm_label, variant="primary", id="ok")

    def on_mount(self) -> None:
        self.query_one("#label", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            self.dismiss(self.query_one("#label", Input).value)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmScreen(ModalScreen[bool]):
    """Confirm a destructive action.

    `y`/`n` are bound so the dialog is reachable from the keyboard. Neither the
    dialog nor the confirm button takes focus on open, so a stray Enter cannot
    delete anything — confirming is always deliberate.
    """

    CSS = DIALOG_CSS
    BINDINGS = [
        ("y", "confirm", "Yes"),
        ("n", "cancel", "No"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, message: str, confirm_label: str = "Delete") -> None:
        super().__init__()
        self.message = message
        self.confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.message)
            yield Label(Text("y  confirm      n  cancel", style="dim"))
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button(self.confirm_label, variant="error", id="ok")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "ok")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


def _placeholder_calibrating() -> Text:
    text = Text()
    text.append("\n  Calibrating\n\n", style="bold")
    text.append(
        "  Not built yet. The plan is to learn your voice once and set the\n"
        "  dials from that, instead of from thresholds hand-tuned against\n"
        "  somebody else.\n\n",
        style="dim",
    )
    text.append("  It would measure:\n\n", style="dim")
    for line in (
        "your comfortable range, low and high",
        "how far you usually sit off concert pitch",
        "how much your pitch drifts while holding a note",
        "how much you slide between notes",
        "how cleanly you separate repeated notes",
    ):
        text.append(f"    · {line}\n", style="dim")
    text.append(
        "\n  Most of these are already computed by the analyze command; what\n"
        "  is missing is capturing a known scale and saving the result to\n"
        "  your profile. See docs/ROADMAP.md.\n",
        style="dim",
    )
    return text


def _placeholder_training() -> Text:
    text = Text()
    text.append("\n  Training\n\n", style="bold")
    text.append(
        "  Not built yet. The plan is the other half of the problem: rather\n"
        "  than making the app better at understanding an imperfect voice,\n"
        "  help the voice get steadier.\n\n",
        style="dim",
    )
    text.append(
        "  The live readout already produces pitch, note and cents about 43\n"
        "  times a second, so the machinery exists. What it needs is a target\n"
        "  to compare against and a way to score you.\n\n",
        style="dim",
    )
    text.append(
        "  First exercise, once built: show a target note, play it, and ask\n"
        "  you to match and hold it inside a band for a second.\n",
        style="dim",
    )
    return text


class ProfileScreen(ModalScreen[Profile]):
    """Asks who is humming, before anything else happens."""

    CSS = DIALOG_CSS + """
    ProfileScreen #dialog { width: 68; }
    ProfileScreen ListView {
        height: auto;
        min-height: 3;
        max-height: 12;
        background: transparent;
        border: none;
    }
    ProfileScreen #profile-hint { color: $text-muted; margin: 1 0; }
    """
    BINDINGS = [
        ("g", "use_guest", "Guest"),
        ("n", "new_profile", "New"),
        ("d", "delete_profile", "Delete"),
        ("escape", "use_guest", "Guest"),
    ]

    def __init__(self, store: ProfileStore) -> None:
        super().__init__()
        self.store = store
        self.profiles: list[Profile] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(Text("Who is humming?", style="bold"))
            yield ListView(id="profiles")
            yield Static(id="profile-hint")
            with Horizontal():
                yield Button("Continue as guest", id="guest")
                yield Button("New profile", variant="primary", id="new")

    def on_mount(self) -> None:
        self.refresh_profiles()
        self.query_one("#profiles", ListView).focus()

    def _show_hint(self) -> None:
        """Only advertise the keys that currently do something."""
        if self.profiles:
            hint = "enter  use profile      n  new      d  delete      g  guest"
        else:
            hint = "No profiles yet.      n  new profile      g  continue as guest"
        self.query_one("#profile-hint", Static).update(Text(hint, style="dim"))

    def refresh_profiles(self, select: str | None = None) -> None:
        self.profiles = self.store.list()
        listing = self.query_one("#profiles", ListView)
        listing.clear()
        for profile in self.profiles:
            label = Text(profile.name, style="bold")
            label.append(f"\n{profile.summary}", style="dim")
            listing.append(ListItem(Label(label)))
        if self.profiles:
            index = 0
            if select is not None:
                index = next(
                    (i for i, p in enumerate(self.profiles) if p.name == select), 0
                )
            listing.index = index
        self._show_hint()

    @property
    def selected(self) -> Profile | None:
        listing = self.query_one("#profiles", ListView)
        if listing.index is None or not (0 <= listing.index < len(self.profiles)):
            return None
        return self.profiles[listing.index]

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if self.selected is not None:
            self.dismiss(self.selected)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "guest":
            self.action_use_guest()
        elif event.button.id == "new":
            self.action_new_profile()

    def action_use_guest(self) -> None:
        self.dismiss(guest())

    def action_new_profile(self) -> None:
        def create(name: str | None) -> None:
            if not name:
                return
            try:
                profile = self.store.create(name)
            except (OSError, ValueError) as exc:
                self.query_one("#profile-hint", Static).update(
                    Text(str(exc), style="bold red")
                )
                return
            self.dismiss(profile)

        self.app.push_screen(NameScreen("New profile", ""), create)

    def action_delete_profile(self) -> None:
        profile = self.selected
        if profile is None:
            return

        def apply(confirmed: bool | None) -> None:
            if not confirmed:
                return
            try:
                self.store.delete(profile)
            except (OSError, ValueError) as exc:
                self.query_one("#profile-hint", Static).update(
                    Text(str(exc), style="bold red")
                )
                return
            self.refresh_profiles()

        self.app.push_screen(
            ConfirmScreen(
                f"Delete the profile “{profile.name}”?\n"
                "Recordings it produced are kept."
            ),
            apply,
        )


class Humm2MelodyApp(App):
    """Hum a melody, get the notes to play."""

    TITLE = "humm2melody"
    SUB_TITLE = "hum a melody, get the keyboard notes"

    CSS = """
    Screen { layout: vertical; }

    #live {
        height: auto;
        border: round $primary 50%;
        padding: 1 2;
        margin: 1 2 0 2;
    }
    #live.recording { border: round #f87171; }

    NoteReadout { height: 1; }
    LevelMeter { height: 1; margin-top: 1; }
    #hint { height: 1; margin-top: 1; color: $text-muted; }

    #controls {
        height: auto;
        align: center middle;
        margin: 1 2 0 2;
    }
    #toggle { min-width: 24; margin-right: 2; }
    #play { min-width: 22; }
    #sensitivity { height: 1; margin: 1 2 0 2; }
    #pause { height: 1; margin: 0 2 0 2; }
    #mix { height: 1; margin: 0 2 0 2; }
    #compare { min-width: 26; margin-left: 2; }

    #main { height: 1fr; margin: 1 2; }
    #results { width: 1fr; }
    #roll { height: auto; margin-bottom: 1; }
    #sequence { height: auto; margin-bottom: 1; }
    #detail { height: auto; }

    #sidebar {
        width: 34;
        border-left: solid $primary 30%;
        padding: 0 1;
    }
    TabPane { padding: 0 1; }
    #calibrate-body, #train-body { height: auto; }
    #sidebar-title { height: 1; text-style: bold; }
    #sidebar-path { height: auto; margin-bottom: 1; }
    #runs { height: 1fr; background: transparent; border: none; }
    #runs > ListItem { height: auto; padding: 0 1; }
    #run-hint { height: auto; color: $text-muted; }
    """

    BINDINGS = [
        ("space", "toggle", "Start / Stop"),
        ("p", "play", "Play back"),
        ("s", "star_run", "Star run"),
        ("u", "switch_profile", "Profile"),
        ("r", "rename_run", "Rename run"),
        ("d", "delete_run", "Delete run"),
        ("left_square_bracket", "less_sensitive", "Pitch −"),
        ("right_square_bracket", "more_sensitive", "Pitch +"),
        ("comma", "fewer_pauses", "Pauses −"),
        ("full_stop", "more_pauses", "Pauses +"),
        ("m", "cycle_source", "Compare"),
        ("minus", "less_tones", "More hum"),
        ("equals_sign", "more_tones", "More tones"),
        ("c", "clear", "Clear"),
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        device: int | str | None = None,
        output_dir: Path | str = DEFAULT_OUTPUT_DIR,
        save: bool = True,
        demo: bool = False,
        profile_dir: Path | str = DEFAULT_PROFILE_DIR,
        profile: Profile | None = None,
    ) -> None:
        super().__init__()
        self.profiles = ProfileStore(profile_dir)
        # None means "ask on startup"; a profile means use it and do not ask.
        self.profile = profile or guest()
        self._ask_for_profile = profile is None
        if demo:
            from .demo import DemoRecorder

            self.recorder = DemoRecorder()
        else:
            self.recorder = Recorder(device=device)
        self.player = Player()
        self.store = SessionStore(output_dir)
        self.saving = save
        self.notes: list[Note] = []
        self.frames: list[PitchFrame] = []
        self.sensitivity = SENSITIVITY_DEFAULT
        self.pause_sensitivity = PAUSE_DEFAULT
        self.source = "tones"
        self.mix = MIX_DEFAULT
        self.audio = None
        self.audio_rate = 0
        self.sessions: list[Session] = []
        self._record_timer = None
        self._play_timer = None

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="tab-record"):
            with TabPane("Recording", id="tab-record"):
                with Vertical(id="live"):
                    yield NoteReadout(id="readout")
                    yield LevelMeter(id="meter")
                    yield Static(
                        "Press Start (or space) and hum your melody.", id="hint"
                    )
                with Horizontal(id="controls"):
                    yield ActionButton(
                        "▶  Start humming", variant="success", id="toggle"
                    )
                    yield ActionButton(
                        "♪  Play back", variant="primary", id="play", disabled=True
                    )
                    yield ActionButton("◑  Tones only", id="compare")
                yield SensitivityDial(id="sensitivity")
                yield PauseDial(id="pause")
                yield MixDial(id="mix")
                with Horizontal(id="main"):
                    with VerticalScroll(id="results"):
                        yield PianoRoll(id="roll")
                        yield MelodySequence(id="sequence")
                        yield Static(id="detail")
                    with Vertical(id="sidebar"):
                        yield Static("Recordings", id="sidebar-title")
                        yield Static(id="sidebar-path")
                        yield ListView(id="runs")
                        yield Static(id="run-hint")

            with TabPane("Calibrating", id="tab-calibrate"):
                yield Static(_placeholder_calibrating(), id="calibrate-body")

            with TabPane("Training", id="tab-train"):
                yield Static(_placeholder_training(), id="train-body")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#readout", NoteReadout).idle("Ready.")
        self.query_one("#meter", LevelMeter).show(0.0)
        self.query_one("#sensitivity", SensitivityDial).show(self.sensitivity)
        self.query_one("#pause", PauseDial).show(self.pause_sensitivity)
        self.query_one("#mix", MixDial).show(self.mix)
        self._apply_profile(self.profile)
        self.query_one("#compare", Button).label = self._source_label()
        # One key per line: the sidebar is too narrow for a single run-on line,
        # which wraps mid-word.
        self.query_one("#run-hint", Static).update(
            Text(
                "enter  load\ns      star\nr      rename\nd      delete",
                style="dim",
            )
        )
        self.query_one("#sidebar-path", Static).update(
            Text(
                f"{self.store.root}/" if self.saving else "saving disabled",
                style="dim",
            )
        )
        self.refresh_sessions()
        # The results pane is scrollable and so grabs focus first, which would
        # leave the sidebar's enter/up/down keys dead. ListView only binds
        # those three, so focusing it does not shadow any app-level key.
        self.query_one("#runs", ListView).focus()
        if self._ask_for_profile:
            self.action_switch_profile()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "toggle":
            self.action_toggle()
        elif event.button.id == "play":
            self.action_play()
        elif event.button.id == "compare":
            self.action_cycle_source()

    # -- recording ---------------------------------------------------------

    def action_toggle(self) -> None:
        if self.recorder.running:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        self._stop_playback()
        try:
            self.recorder.start()
        except AudioError as exc:
            self._set_hint(
                Text(f"Could not open the microphone: {exc}", style="bold red")
            )
            return

        self._clear_results()
        button = self.query_one("#toggle", Button)
        button.label = "■  Stop"
        button.variant = "error"
        self.query_one("#play", Button).disabled = True
        self.query_one("#live").add_class("recording")
        self._set_hint(
            Text("Recording — hum steadily, one note at a time.", style="#f87171")
        )
        self._record_timer = self.set_interval(1 / 20, self._tick_recording)

    def _tick_recording(self) -> None:
        reading = self.recorder.latest()
        self.query_one("#readout", NoteReadout).show(
            reading.note, reading.cents, reading.freq, reading.elapsed
        )
        self.query_one("#meter", LevelMeter).show(reading.level)

    def _stop_recording(self) -> None:
        if self._record_timer is not None:
            self._record_timer.stop()
            self._record_timer = None

        frames = self.recorder.stop()
        audio = self.recorder.audio()
        self.frames = frames
        self.audio = audio if len(audio) else None
        self.audio_rate = self.recorder.sample_rate
        self.notes = segment_with_sensitivity(
            frames, self.sensitivity, self.pause_sensitivity
        )

        button = self.query_one("#toggle", Button)
        button.label = "▶  Start humming"
        button.variant = "success"
        self.query_one("#live").remove_class("recording")

        duration = frames[-1].time if frames else 0.0
        self.query_one("#readout", NoteReadout).idle(
            f"Stopped — {len(self.notes)} notes over {duration:.1f}s."
        )
        self.query_one("#meter", LevelMeter).show(0.0)
        self._show_notes(self.notes)

        saved = self._save_run(audio, frames)
        if self.notes:
            # Keep this on one line: the hint row is a single line and clips.
            lead = f"Saved as {saved.path.name} · " if saved else ""
            self._set_hint(f"{lead}p to play it back · space to hum again")
        else:
            self.query_one("#detail", Static).update(
                Text(
                    "No notes detected. Try humming louder, closer to the mic, "
                    "and hold each note a little longer.",
                    style="yellow",
                )
            )
            self._set_hint("Press space to try again.")

    def _save_run(self, audio, frames) -> Session | None:
        """Persist the run. A save failure must not lose the transcription."""
        if not self.saving or len(audio) == 0:
            return None
        try:
            session = self.store.save(
                audio=audio,
                sample_rate=self.recorder.sample_rate,
                frames=frames,
                notes=self.notes,
                profile="" if self.profile.is_guest else self.profile.name,
            )
        except OSError as exc:
            self._set_hint(Text(f"Could not save this run: {exc}", style="bold red"))
            return None
        self.refresh_sessions(select=session.path)
        return session

    # -- playback ----------------------------------------------------------

    def action_play(self) -> None:
        if self.recorder.running:
            return
        if not self.notes and self.audio is None:
            return
        if self.player.playing:
            self._stop_playback()
            return

        try:
            if self.source == "tones" or self.audio is None:
                self.player.play(self.notes)
            elif self.source == "hum":
                self.player.play_audio(self.audio, self.audio_rate)
            else:
                rate = self.player.sample_rate or self.audio_rate
                self.player.play_audio(
                    mix_hum_with_tones(
                        self.audio,
                        self.audio_rate,
                        self.notes,
                        rate,
                        balance=self.mix,
                    ),
                    rate,
                )
        except Exception as exc:
            self._set_hint(Text(f"Could not play audio: {exc}", style="bold red"))
            return

        button = self.query_one("#play", Button)
        button.label = "■  Stop playback"
        button.variant = "warning"
        self._set_hint("Playing back — does it match what you hummed?")
        self._play_timer = self.set_interval(1 / 30, self._tick_playback)

    def _tick_playback(self) -> None:
        if not self.player.playing:
            self._stop_playback()
            return

        position = self.player.position
        roll = self._find("#roll", PianoRoll)
        if roll is None:  # the tree is being torn down; nothing left to draw
            return
        roll.set_playhead(position)

        active = None
        for i, note in enumerate(self.notes):
            if note.start <= position < note.end:
                active = i
                break
        sequence = self._find("#sequence", MelodySequence)
        if sequence is not None:
            sequence.set_active(active)

    def _stop_playback(self) -> None:
        if self._play_timer is not None:
            self._play_timer.stop()
            self._play_timer = None
        self.player.stop()

        button = self._find("#play", Button)
        if button is not None:
            button.label = "♪  Play back"
            button.variant = "primary"
            button.disabled = not self.notes
        roll = self._find("#roll", PianoRoll)
        if roll is not None:
            roll.set_playhead(None)
        sequence = self._find("#sequence", MelodySequence)
        if sequence is not None:
            sequence.set_active(None)

    # -- saved runs --------------------------------------------------------

    def refresh_sessions(self, select: Path | None = None) -> None:
        """Reload the run list from disk, optionally highlighting one."""
        self.sessions = self.store.list()
        runs = self._find("#runs", ListView)
        if runs is None:
            return

        runs.clear()
        for session in self.sessions:
            label = Text()
            if session.starred:
                label.append("★ ", style=HIGHLIGHT)
            label.append(session.display_name, style="bold")
            label.append(f"\n{session.summary}", style="dim")
            runs.append(ListItem(Label(label)))

        if self.sessions:
            index = 0
            if select is not None:
                index = next(
                    (i for i, s in enumerate(self.sessions) if s.path == select), 0
                )
            runs.index = index

    @property
    def selected_session(self) -> Session | None:
        runs = self._find("#runs", ListView)
        if runs is None or runs.index is None:
            return None
        if 0 <= runs.index < len(self.sessions):
            return self.sessions[runs.index]
        return None

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.load_selected_session()

    def load_selected_session(self) -> None:
        """Bring a saved run back onto the timeline so it can be replayed."""
        session = self.selected_session
        if session is None:
            return
        self._stop_playback()
        self.frames = read_pitch_track(session.pitch_track_path)
        self.audio, self.audio_rate = None, 0
        if session.hum_path.is_file():
            try:
                self.audio, self.audio_rate = read_wav(session.hum_path)
            except Exception:
                self.audio, self.audio_rate = None, 0
        if self.frames:
            self.notes = segment_with_sensitivity(
                self.frames, self.sensitivity, self.pause_sensitivity
            )
        else:
            self.notes = list(session.notes)
        self._show_notes(self.notes)
        self.query_one("#readout", NoteReadout).idle(
            f"Loaded “{session.display_name}” — {session.summary}."
        )
        if self.notes:
            self._set_hint(f"Loaded {session.path.name} · p to play it back")
        else:
            self._set_hint(f"Loaded {session.path.name} · this run has no notes")

    # -- profiles ----------------------------------------------------------

    def action_switch_profile(self) -> None:
        """Ask who is humming, and adopt their saved settings."""
        if self.recorder.running:
            return
        self._stop_playback()
        self.push_screen(ProfileScreen(self.profiles), self._adopt_profile)

    def _adopt_profile(self, profile: Profile | None) -> None:
        if profile is None:
            return
        self._apply_profile(profile)
        if profile.is_guest:
            self._set_hint("Continuing as guest — settings will not be saved.")
        else:
            self._set_hint(f"Settings loaded for “{profile.name}”.")

    def _apply_profile(self, profile: Profile) -> None:
        self.profile = profile
        self.sensitivity = profile.pitch_sensitivity
        self.pause_sensitivity = profile.pause_sensitivity
        self.mix = profile.mix
        self.sub_title = f"{profile.name} · hum a melody, get the keyboard notes"

        for selector, kind, value in (
            ("#sensitivity", SensitivityDial, self.sensitivity),
            ("#pause", PauseDial, self.pause_sensitivity),
            ("#mix", MixDial, self.mix),
        ):
            dial = self._find(selector, kind)
            if dial is not None:
                dial.show(value)
        if self.frames:
            self._resegment()

    def _remember_dials(self) -> None:
        """Persist dial positions to the profile. Guests are not remembered."""
        if self.profile.is_guest:
            return
        self.profile.pitch_sensitivity = self.sensitivity
        self.profile.pause_sensitivity = self.pause_sensitivity
        self.profile.mix = self.mix
        try:
            self.profiles.save(self.profile)
        except OSError:
            pass

    def action_star_run(self) -> None:
        """Toggle the favourite mark on the highlighted run."""
        session = self.selected_session
        if session is None or self.recorder.running:
            return
        try:
            self.store.set_starred(session, not session.starred)
        except (OSError, ValueError) as exc:
            self._set_hint(Text(f"Could not star: {exc}", style="bold red"))
            return
        self.refresh_sessions(select=session.path)
        state = "Starred" if session.starred else "Unstarred"
        self._set_hint(f"{state} “{session.display_name}”.")

    def action_rename_run(self) -> None:
        session = self.selected_session
        if session is None or self.recorder.running:
            return

        def apply(label: str | None) -> None:
            if label is None:
                return
            try:
                self.store.rename(session, label)
            except (OSError, ValueError) as exc:
                self._set_hint(Text(f"Could not rename: {exc}", style="bold red"))
                return
            self.refresh_sessions(select=session.path)
            self._set_hint(f"Renamed to “{session.display_name}”.")

        self.push_screen(
            NameScreen(
                f"Rename “{session.display_name}”",
                session.label,
                "leave empty to go back to the timestamp",
                confirm_label="Rename",
            ),
            apply,
        )

    def action_delete_run(self) -> None:
        session = self.selected_session
        if session is None or self.recorder.running:
            return

        def apply(confirmed: bool | None) -> None:
            if not confirmed:
                return
            try:
                self.store.delete(session)
            except (OSError, ValueError) as exc:
                self._set_hint(Text(f"Could not delete: {exc}", style="bold red"))
                return
            self.refresh_sessions()
            self._set_hint(f"Deleted “{session.display_name}”.")

        warning = "\nThis run is starred." if session.starred else ""
        self.push_screen(
            ConfirmScreen(
                f"Delete “{session.display_name}” and its recordings?\n"
                f"This cannot be undone.{warning}"
            ),
            apply,
        )

    # -- misc --------------------------------------------------------------

    def action_clear(self) -> None:
        """Clear the display. Saved runs on disk are left alone."""
        if self.recorder.running:
            return
        self._stop_playback()
        self._clear_results()
        self.query_one("#readout", NoteReadout).idle("Ready.")
        self._set_hint("Press Start (or space) and hum your melody.")

    def _show_notes(self, notes: list[Note]) -> None:
        self.query_one("#roll", PianoRoll).show(notes)
        self.query_one("#sequence", MelodySequence).show(notes)
        self.query_one("#play", Button).disabled = not (notes or self.audio is not None)
        self.query_one("#detail", Static).update(
            _detail_table(notes) if notes else Text("")
        )

    def action_less_sensitive(self) -> None:
        self._set_dials(self.sensitivity - 1, self.pause_sensitivity)

    def action_more_sensitive(self) -> None:
        self._set_dials(self.sensitivity + 1, self.pause_sensitivity)

    def action_fewer_pauses(self) -> None:
        self._set_dials(self.sensitivity, self.pause_sensitivity - 1)

    def action_more_pauses(self) -> None:
        self._set_dials(self.sensitivity, self.pause_sensitivity + 1)

    def _set_dials(self, pitch: int, pause: int) -> None:
        """Move the dials and re-segment, without needing a new recording."""
        pitch = max(SENSITIVITY_MIN, min(SENSITIVITY_MAX, pitch))
        pause = max(PAUSE_MIN, min(PAUSE_MAX, pause))
        if (pitch, pause) == (self.sensitivity, self.pause_sensitivity):
            return
        self.sensitivity, self.pause_sensitivity = pitch, pause
        self._remember_dials()

        dial = self._find("#sensitivity", SensitivityDial)
        if dial is not None:
            dial.show(pitch)
        pause_dial = self._find("#pause", PauseDial)
        if pause_dial is not None:
            pause_dial.show(pause)

        if self.recorder.running or not self.frames:
            return
        self._stop_playback()
        self._resegment()
        self._set_hint(
            f"Pitch {pitch}/{SENSITIVITY_MAX} · pauses {pause}/{PAUSE_MAX} · "
            f"{len(self.notes)} notes"
        )

    def _resegment(self) -> None:
        self.notes = segment_with_sensitivity(
            self.frames, self.sensitivity, self.pause_sensitivity
        )
        self._show_notes(self.notes)

    # -- comparison --------------------------------------------------------

    SOURCES = ("tones", "hum", "both")

    def _source_label(self) -> str:
        return {
            "tones": "◑  Tones only",
            "hum": "◑  Your hum",
            "both": "◑  Hum + tones",
        }[self.source]

    def action_less_tones(self) -> None:
        self._set_mix(self.mix - 1)

    def action_more_tones(self) -> None:
        self._set_mix(self.mix + 1)

    def _set_mix(self, level: int) -> None:
        """Change the overlay balance. Takes effect on the next play."""
        level = max(MIX_MIN, min(MIX_MAX, level))
        if level == self.mix:
            return
        self.mix = level
        self._remember_dials()
        dial = self._find("#mix", MixDial)
        if dial is not None:
            dial.show(level)
        if self.source == "both":
            self._set_hint(f"Mix {level}/{MIX_MAX} — press p to hear it.")

    def action_cycle_source(self) -> None:
        """Cycle what `p` plays: the transcription, your recording, or both."""
        if self.recorder.running:
            return
        self._stop_playback()
        self.source = self.SOURCES[
            (self.SOURCES.index(self.source) + 1) % len(self.SOURCES)
        ]
        button = self._find("#compare", Button)
        if button is not None:
            button.label = self._source_label()
        if self.source == "both":
            self._set_hint("Plays your hum with the tones on top — do they agree?")
        elif self.source == "hum":
            self._set_hint("Plays your original recording back.")
        else:
            self._set_hint("Plays the transcribed notes as tones.")

    def _clear_results(self) -> None:
        self.notes = []
        self.frames = []
        self.audio = None
        self.audio_rate = 0
        self._show_notes([])

    def _set_hint(self, message) -> None:
        hint = self._find("#hint", Static)
        if hint is not None:
            hint.update(message)

    def _find(self, selector: str, kind):
        """query_one that tolerates a missing widget.

        Timer callbacks can fire after the widget tree has started coming
        down, so updates must not explode during shutdown.
        """
        try:
            return self.query_one(selector, kind)
        except NoMatches:
            return None

    def on_unmount(self) -> None:
        for timer in (self._record_timer, self._play_timer):
            if timer is not None:
                timer.stop()
        self._record_timer = self._play_timer = None
        if self.recorder.running:
            self.recorder.stop()
        self.player.stop()


def run(
    device: int | str | None = None,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    save: bool = True,
    demo: bool = False,
    profile_dir: Path | str = DEFAULT_PROFILE_DIR,
    profile: Profile | None = None,
) -> None:
    Humm2MelodyApp(
        device=device,
        output_dir=output_dir,
        save=save,
        demo=demo,
        profile_dir=profile_dir,
        profile=profile,
    ).run()
