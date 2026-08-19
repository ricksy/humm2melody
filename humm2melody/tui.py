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
    Tabs,
)

from .audio import AudioError, Recorder
from .calibration import STEPS as CALIBRATION_STEPS
from .calibration import GLOBAL_FMAX, GLOBAL_FMIN, calibrate, voice_bounds
from .pitch import NOTE_NAMES, hz_to_midi, midi_to_hz
from .naming import SCHEMES, get_scheme, next_scheme, spell
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

TAB_IDS = ("tab-record", "tab-calibrate", "tab-train")
DEFAULT_TAB = TAB_IDS[0]

MAX_ROLL_ROWS = 32
"""Cap the piano roll's pitch range so one stray octave can't blow up the view."""

ACCENT = "#7dd3fc"
ACCENT_SHARP = "#818cf8"
HIGHLIGHT = "#fbbf24"
SELECTED = "#f472b6"


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


class NotationRow(Static):
    """Which tradition note names are written in."""

    def show(self, key: str) -> None:
        scheme = get_scheme(key)
        text = Text(f"{'Notation':<11}", style="bold")
        text.append("n    ", style="dim")
        for item in SCHEMES:
            if item.key == scheme.key:
                text.append(f" {item.label} ", style=f"bold black on {HIGHLIGHT}")
            else:
                text.append(f" {item.label} ", style="grey42")
        text.append(f"   {scheme.note}", style="dim")
        self.update(text)


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
    """Notes laid out as pitch (rows) against time (columns).

    In edit mode this widget takes focus, so the editing keys belong to it
    rather than to the app. That is what lets `,` `.` `-` `=` mean nudge and
    resize while editing and keep meaning the pause and mix dials otherwise:
    a focused widget is offered keys before any app binding, so the two sets
    cannot collide.
    """

    can_focus = True

    BINDINGS = [
        ("left", "select(-1)", "Previous note"),
        ("right", "select(1)", "Next note"),
        ("up", "transpose(1)", "Higher"),
        ("down", "transpose(-1)", "Lower"),
        ("shift+up", "transpose(12)", "Octave up"),
        ("shift+down", "transpose(-12)", "Octave down"),
        ("comma", "shift(-1)", "Earlier"),
        ("full_stop", "shift(1)", "Later"),
        ("minus", "resize(-1)", "Shorter"),
        ("equals_sign", "resize(1)", "Longer"),
        ("i", "insert", "Insert"),
        ("delete", "remove", "Delete"),
        ("backspace", "remove", "Delete"),
        ("z", "undo", "Undo"),
        ("shift+z", "redo", "Redo"),
        ("escape", "done", "Done editing"),
    ]

    def action_select(self, delta: int) -> None:
        self.app.edit_select(delta)

    def action_transpose(self, delta: int) -> None:
        self.app.edit_transpose(delta)

    def action_shift(self, direction: int) -> None:
        self.app.edit_shift(direction)

    def action_resize(self, direction: int) -> None:
        self.app.edit_resize(direction)

    def action_insert(self) -> None:
        self.app.edit_insert()

    def action_remove(self) -> None:
        self.app.edit_remove()

    def action_undo(self) -> None:
        self.app.edit_undo()

    def action_redo(self) -> None:
        self.app.edit_redo()

    def action_done(self) -> None:
        self.app.action_edit_notes()

    def on_click(self, event) -> None:
        """Pick the note under the pointer."""
        index = self._note_at(event.x, event.y)
        if index is not None:
            self.app.edit_click(index)

    def _note_at(self, x: int, y: int) -> int | None:
        if self._geometry is None or not self._notes:
            return None
        lo, hi, label_w, width, span = self._geometry

        midi = hi - y
        if not (lo <= midi <= hi):
            return None

        column = x - (label_w + 1)
        if not (0 <= column < width):
            return None
        when = (column + 0.5) / width * span

        for index, note in enumerate(self._notes):
            if note.midi == midi and note.start <= when < note.end:
                return index
        return None

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._notes: list[Note] = []
        self._selected: int | None = None
        self._scheme: str = "english"
        self._playhead: float | None = None
        self._head_col: int | None = None
        # Geometry of the last draw, so a click can be mapped back to a note.
        self._geometry: tuple[int, int, int, int, float] | None = None

    def show(
        self,
        notes: list[Note],
        selected: int | None = None,
        scheme: str = "english",
    ) -> None:
        self._notes = notes
        self._selected = selected
        self._scheme = scheme
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

        lo0 = min(n.midi for n in notes)
        hi0 = max(n.midi for n in notes)
        label_w = max(5, max(len(spell(m, self._scheme)) for m in range(lo0, hi0 + 1)) + 1)
        width = max(20, self.size.width - label_w - 2)

        head_col = None
        if self._playhead is not None:
            head_col = min(width - 1, int(self._playhead / span * width))

        lo = min(n.midi for n in notes)
        hi = max(n.midi for n in notes)
        if hi - lo + 1 > MAX_ROLL_ROWS:
            hi = lo + MAX_ROLL_ROWS - 1

        self._geometry = (lo, hi, label_w, width, span)

        out = Text()
        for midi in range(hi, lo - 1, -1):
            style = "dim" if _is_black_key(midi) else "bold"
            out.append(f"{spell(midi, self._scheme):>{label_w - 1}} ", style=style)
            out.append("│", style="dim")

            cells: list[Note | None] = [None] * width
            chosen = [False] * width
            for index, n in enumerate(notes):
                if n.midi != midi:
                    continue
                start = int(n.start / span * width)
                end = max(start + 1, math.ceil(n.end / span * width))
                for c in range(start, min(end, width)):
                    cells[c] = n
                    chosen[c] = index == self._selected

            for col, cell in enumerate(cells):
                on_head = col == head_col
                if cell is None:
                    out.append("│" if on_head else "·",
                               style=HIGHLIGHT if on_head else "grey30")
                elif on_head:
                    out.append("█", style=HIGHLIGHT)
                elif chosen[col]:
                    out.append("█", style=f"bold {SELECTED}")
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
        self._selected: int | None = None
        self._scheme: str = "english"
        self._spans: list[tuple[int, int, int]] = []

    def on_click(self, event) -> None:
        for start, end, index in self._spans:
            if start <= event.x < end:
                self.app.edit_click(index)
                return

    def show(
        self,
        notes: list[Note],
        selected: int | None = None,
        scheme: str = "english",
    ) -> None:
        self._notes = notes
        self._selected = selected
        self._scheme = scheme
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
        self._spans = []
        for i, n in enumerate(self._notes):
            if i:
                gap = n.start - self._notes[i - 1].end
                text.append("  ·  " if gap > 0.25 else "  ", style="dim")
            column = len(text.plain)
            name = spell(n.midi, self._scheme)
            if i == self._active:
                text.append(f" {name} ", style=f"bold black on {HIGHLIGHT}")
            elif i == self._selected:
                text.append(f"[{name}]", style=f"bold {SELECTED}")
            else:
                text.append(name, style=f"bold {ACCENT}")
            self._spans.append((column, len(text.plain), i))
        self.update(text)


def _detail_table(
    notes: list[Note], selected: int | None = None, scheme: str = "english"
) -> Table:
    table = Table(expand=False, pad_edge=False, header_style="bold dim")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Note", style=f"bold {ACCENT}")
    table.add_column("Start", justify="right")
    table.add_column("Length", justify="right")
    table.add_column("Hz", justify="right", style="dim")
    table.add_column("Tuning", justify="right")

    for i, n in enumerate(notes, start=1):
        chosen = (i - 1) == selected
        cents = n.cents_off
        if abs(cents) < 12:
            tuning = Text("on pitch", style="green")
        else:
            tuning = Text(
                f"{'+' if cents > 0 else '−'}{abs(cents):.0f}¢", style="yellow"
            )
        marker = "▸" if chosen else str(i)
        name = Text(
            spell(n.midi, scheme),
            style=f"bold {SELECTED}" if chosen else f"bold {ACCENT}",
        )
        table.add_row(
            marker,
            name,
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


STEP_NUMERALS = ("①", "②", "③", "④", "⑤")


def _meter_bar(value: float, width: int = 14, filled: str = "█", empty: str = "░") -> str:
    """A proportional bar. Used for anything measured on a 0..1 scale."""
    take = int(round(max(0.0, min(1.0, value)) * width))
    return filled * take + empty * (width - take)


def _range_strip(low: int, high: int, width: int = 30) -> Text:
    """A voice's range drawn against the span the detector can hear."""
    lowest, highest = 36, 84  # C2 to C6, the useful singing span
    text = Text()
    for i in range(width):
        midi = lowest + (highest - lowest) * i / max(1, width - 1)
        if low <= midi <= high:
            text.append("█", style=ACCENT)
        else:
            text.append("─", style="grey30")
    return text


def _tuning_gauge(cents: float, width: int = 21) -> Text:
    """A tuner needle: flat on the left, sharp on the right, centre in tune."""
    position = int(round((max(-50.0, min(50.0, cents)) + 50) / 100 * (width - 1)))
    text = Text()
    for i in range(width):
        if i == position:
            style = "green" if abs(cents) < 12 else "yellow"
            text.append("●", style=f"bold {style}")
        elif i == width // 2:
            text.append("│", style="grey30")
        else:
            text.append("─", style="grey30")
    return text


class CalibrationPane(Vertical):
    """The Calibrating tab: three prompts, live feedback, then what was learned."""

    def compose(self) -> ComposeResult:
        yield Static(id="cal-title")
        yield Static(id="cal-steps")
        yield Static(id="cal-live")
        yield LevelMeter(id="cal-meter")
        with Horizontal(id="cal-buttons"):
            yield ActionButton("●  Start", variant="success", id="cal-record")
            yield ActionButton("♪  Hear the melody", id="cal-listen")
            yield ActionButton("✓  Keep it", variant="primary", id="cal-keep")
            yield ActionButton("↻  Start over", id="cal-reset")
        yield Static(id="calibrate-body")

    def show(
        self,
        *,
        step: int | None,
        recording: bool,
        takes: dict,
        result=None,
        live: str = "",
        level: float = 0.0,
        profile=None,
        saved: bool = False,
    ) -> None:
        from .calibration import STEPS, describe

        self._show_title()
        self._show_steps(STEPS, step, recording, takes)
        self._show_live(recording, live, level, step, STEPS)
        self._show_buttons(step, recording, result, saved)
        self._show_result(result, describe, profile, saved)

    # -- pieces ------------------------------------------------------------

    def _show_title(self) -> None:
        text = Text()
        text.append("♪  Teach the app your voice\n", style=f"bold {ACCENT}")
        text.append(
            "Three short takes. The dials are then set from what you actually "
            "sang,\ninstead of from defaults tuned for somebody else.",
            style="dim",
        )
        self.query_one("#cal-title", Static).update(text)

    def _show_steps(self, steps, step, recording, takes) -> None:
        text = Text()
        for index, item in enumerate(steps):
            done = item.key in takes
            active = step == index

            if done:
                marker, style = "✓", "green"
            elif active and recording:
                marker, style = "●", "#f87171"
            elif active:
                marker, style = "▸", f"bold {HIGHLIGHT}"
            else:
                marker, style = "·", "grey30"

            text.append(f"  {marker} ", style=style)
            text.append(f"{STEP_NUMERALS[index]} ", style=style)
            text.append(
                f"{item.title:<32}",
                style="bold" if (active or done) else "dim",
            )

            if done:
                text.append("♪ ", style=ACCENT)
                text.append(f"{takes[item.key]}", style="green")
            elif active and recording:
                text.append("recording…", style="#f87171")
            elif active:
                text.append(item.detail, style="dim")
            text.append("\n")
        self.query_one("#cal-steps", Static).update(text)

    def _show_live(self, recording, live, level, step, steps) -> None:
        note = self.query_one("#cal-live", Static)
        meter = self.query_one("#cal-meter", LevelMeter)
        if not recording:
            note.update(Text(""))
            meter.show(0.0)
            return

        text = Text("   ")
        text.append("● REC  ", style="bold #f87171")
        if live:
            text.append(f"♪ {live}", style=f"bold {ACCENT}")
        else:
            text.append("listening…", style="dim")
        note.update(text)
        meter.show(level)

    def _show_buttons(self, step, recording, result, saved) -> None:
        record = self.query_one("#cal-record", Button)
        if recording:
            record.label = "■  Done with this step"
            record.variant = "error"
        elif step is not None and step > 0:
            record.label = f"●  Record step {step + 1}"
            record.variant = "success"
        elif result is not None:
            record.label = "●  Calibrate again"
            record.variant = "success"
        else:
            record.label = "●  Start"
            record.variant = "success"

        self.query_one("#cal-listen", Button).disabled = recording

        # Say which state it is in. A greyed-out "Keep it" reads as a broken
        # control, when what it actually means is that there was nothing left
        # to do -- a confident calibration is adopted the moment it finishes.
        keep = self.query_one("#cal-keep", Button)
        keep.label = "✓  Saved" if saved else "✓  Keep it"
        keep.disabled = result is None or saved
        self.query_one("#cal-reset", Button).disabled = recording

    def _show_result(self, result, describe, profile, saved) -> None:
        body = self.query_one("#calibrate-body", Static)
        if result is None:
            body.update(
                Text("   press space, or the button, to begin", style="dim")
            )
            return

        c = result.calibration
        text = Text()
        text.append("  ── what we learned " + "─" * 34 + "\n", style="dim")

        if c.range_low_midi is not None and c.range_high_midi is not None:
            text.append("   ♪ Range       ", style="bold")
            text.append(_range_strip(c.range_low_midi, c.range_high_midi))
            text.append(
                f"  {_note_name(c.range_low_midi)}–{_note_name(c.range_high_midi)}"
                f"  ({c.range_high_midi - c.range_low_midi} semitones)\n"
            )

        if c.tuning_offset_cents is not None:
            text.append("   ◎ Tuning      ", style="bold")
            text.append(_tuning_gauge(c.tuning_offset_cents))
            flat_sharp = "♯" if c.tuning_offset_cents > 0 else "♭"
            text.append(
                f"          {flat_sharp}{abs(c.tuning_offset_cents):.0f}¢\n"
            )

        if c.typical_drift_cents is not None:
            steady = max(0.0, 1.0 - c.typical_drift_cents / 60.0)
            text.append("   ~ Steadiness  ", style="bold")
            text.append(_meter_bar(steady), style="green" if steady > 0.6 else "yellow")
            text.append(f"                  {c.typical_drift_cents:.0f}¢ drift\n")

        if c.glide_fraction is not None:
            text.append("   ↝ Style       ", style="bold")
            text.append(_meter_bar(c.glide_fraction), style=ACCENT_SHARP)
            text.append(f"                  {c.glide_fraction * 100:.0f}% sliding\n")

        if c.pitch_accuracy_cents is not None:
            good = max(0.0, 1.0 - c.pitch_accuracy_cents / 200.0)
            text.append("   ◈ Accuracy    ", style="bold")
            text.append(_meter_bar(good), style="green" if good > 0.6 else "yellow")
            text.append(
                f"                  {c.pitch_accuracy_cents:.0f}¢ from the melody\n"
            )

        if c.transpose_semitones is not None and c.transpose_semitones != 0:
            octaves, semis = divmod(abs(c.transpose_semitones), 12)
            where = "down" if c.transpose_semitones < 0 else "up"
            parts = []
            if octaves:
                parts.append(f"{octaves} octave{'s' if octaves > 1 else ''}")
            if semis:
                parts.append(f"{semis} semitone{'s' if semis > 1 else ''}")
            text.append("   ⇅ Register    ", style="bold")
            text.append(f"sung {' and '.join(parts)} {where}\n", style="dim")

        text.append("\n   ")
        text.append(result.message + "\n", style="green" if result.confident else "yellow")

        if profile is not None and profile.is_guest:
            text.append(
                "   Guest session — this applies now but is not saved.\n",
                style="dim",
            )
        if saved:
            text.append("\n   ✓ saved to your profile\n", style="green")
            text.append("   space  calibrate again\n", style="dim")
        else:
            text.append("\n   y  keep it anyway", style="bold")
            text.append("     — imperfect settings still beat none\n", style="dim")
            text.append("   space  try again\n", style="bold")
        body.update(text)


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


class DetailTable(Static):
    """The per-note table, with clickable rows."""

    HEADER_LINES = 3
    """Rich draws a top border, the header, then a separator above row one."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._count = 0

    def show(
        self, notes: list[Note], selected: int | None, scheme: str
    ) -> None:
        self._count = len(notes)
        self.update(_detail_table(notes, selected, scheme) if notes else Text(""))

    def on_click(self, event) -> None:
        row = event.y - self.HEADER_LINES
        if 0 <= row < self._count:
            self.app.edit_click(row)


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
    #notation { height: 1; margin: 0 2 0 2; }
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
    #train-body { height: auto; }

    #calibration { height: auto; padding: 1 2; }
    #cal-title { height: auto; margin-bottom: 1; }
    #cal-steps { height: auto; margin-bottom: 1; }
    #cal-live { height: 1; }
    #cal-meter { height: 1; margin-bottom: 1; }
    #cal-buttons { height: auto; margin-bottom: 1; }
    #cal-buttons Button { margin-right: 2; }
    #calibrate-body { height: auto; }
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
        ("l", "play_reference", "Hear melody"),
        ("y", "keep_calibration", "Keep calibration"),
        ("n", "cycle_notation", "Notation"),
        ("e", "edit_notes", "Edit notes"),
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
        # Calibration state: which step is next, what has been captured.
        self.cal_step: int | None = None
        self.cal_takes: dict[str, str] = {}
        self.cal_frames: dict[str, list[PitchFrame]] = {}
        self.cal_result = None
        self.cal_saved = False
        self.tuning_prior: float | None = None
        # Startup activates the first tab, which would otherwise be recorded
        # as "the tab you were last on" before the remembered one is restored.
        self._tab_ready = False
        self.notation = "english"
        self.editing = False
        self.selected_note: int | None = None
        self.current_session: Session | None = None
        self.undo_stack: list[list[Note]] = []
        self.redo_stack: list[list[Note]] = []
        self.audio = None
        self.audio_rate = 0
        self.sessions: list[Session] = []
        self._record_timer = None
        self._play_timer = None

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial=DEFAULT_TAB):
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
                yield NotationRow(id="notation")
                with Horizontal(id="main"):
                    with VerticalScroll(id="results"):
                        yield PianoRoll(id="roll")
                        yield MelodySequence(id="sequence")
                        yield DetailTable(id="detail")
                    with Vertical(id="sidebar"):
                        yield Static("Recordings", id="sidebar-title")
                        yield Static(id="sidebar-path")
                        yield ListView(id="runs")
                        yield Static(id="run-hint")

            with TabPane("Calibrating", id="tab-calibrate"):
                yield CalibrationPane(id="calibration")

            with TabPane("Training", id="tab-train"):
                yield Static(_placeholder_training(), id="train-body")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#readout", NoteReadout).idle("Ready.")
        self.query_one("#meter", LevelMeter).show(0.0)
        self.query_one("#sensitivity", SensitivityDial).show(self.sensitivity)
        self.query_one("#pause", PauseDial).show(self.pause_sensitivity)
        self.query_one("#mix", MixDial).show(self.mix)
        self.query_one("#notation", NotationRow).show(self.notation)
        self._apply_profile(self.profile)
        self._refresh_calibration()
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
        # Deferred, because during on_mount the Tabs widget has not built its
        # children yet and the assignment lands on nothing. TabbedContent's
        # own `initial` is ignored in this Textual version.
        self.call_after_refresh(self._restore_startup_tab)
        if self._ask_for_profile:
            self.action_switch_profile()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "toggle":
            self.action_toggle()
        elif event.button.id == "play":
            self.action_play()
        elif event.button.id == "compare":
            self.action_cycle_source()
        elif event.button.id == "cal-record":
            self._toggle_calibration()
        elif event.button.id == "cal-listen":
            self._play_reference()
        elif event.button.id == "cal-keep":
            self.action_keep_calibration()
        elif event.button.id == "cal-reset":
            self._reset_calibration()

    # -- recording ---------------------------------------------------------

    def _active_tab(self) -> str:
        tabs = self._find("TabbedContent", TabbedContent)
        return tabs.active if tabs is not None else "tab-record"

    def action_toggle(self) -> None:
        """Space means "go" on whichever tab is showing."""
        if self._active_tab() == "tab-calibrate":
            self._toggle_calibration()
            return
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
        self.notes = self._segment(frames)

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
            self.query_one("#detail", DetailTable).update(
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
        self.current_session = session
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
        self.current_session = session
        self.editing = False
        self.selected_note = None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.frames = read_pitch_track(session.pitch_track_path)
        self.audio, self.audio_rate = None, 0
        if session.hum_path.is_file():
            try:
                self.audio, self.audio_rate = read_wav(session.hum_path)
            except Exception:
                self.audio, self.audio_rate = None, 0
        if self.frames:
            self.notes = self._segment(self.frames)
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

    # -- editing -----------------------------------------------------------

    UNDO_DEPTH = 50
    NUDGE = 0.05
    """Seconds a note moves or grows per keypress."""

    MIN_DURATION = 0.05

    DEFAULT_NEW_DURATION = 0.35
    INSERT_GAP = 0.05

    def action_edit_notes(self) -> None:
        """Toggle note editing, which hands the arrow keys to the timeline."""
        if self._active_tab() != "tab-record":
            return
        # Allowed with nothing detected, so a transcription that came back
        # empty can still be built up by hand rather than only re-recorded.
        if not self.notes and self.audio is None and not self.frames:
            return

        self.editing = not self.editing
        roll = self._find("#roll", PianoRoll)
        if self.editing:
            if self.selected_note is None and self.notes:
                self.selected_note = 0
            if roll is not None:
                roll.focus()
            self._set_hint(
                "← → pick · ↑ ↓ pitch · , . move · - = length · "
                "i add · del remove · z undo · esc done"
            )
        else:
            runs = self._find("#runs", ListView)
            if runs is not None:
                runs.focus()
            self._set_hint("Done editing.")
        self._show_notes(self.notes)

    def edit_click(self, index: int) -> None:
        """Select a note that was clicked, entering edit mode if needed.

        Clicking is how most people will reach for this, so it should not
        require knowing about `e` first.
        """
        if not self.notes or not (0 <= index < len(self.notes)):
            return
        if self._active_tab() != "tab-record":
            return

        self.selected_note = index
        if not self.editing:
            self.editing = True
            self._set_hint(
                "← → pick · ↑ ↓ pitch · , . move · - = length · "
                "i add · del remove · z undo · esc done"
            )
        roll = self._find("#roll", PianoRoll)
        if roll is not None:
            roll.focus()  # so the arrows reach the editor, not the sidebar
        self._show_notes(self.notes)

    def edit_select(self, delta: int) -> None:
        if not self.editing or not self.notes:
            return
        current = self.selected_note or 0
        self.selected_note = max(0, min(len(self.notes) - 1, current + delta))
        self._show_notes(self.notes)

    def _push_undo(self) -> None:
        """Snapshot the notes before changing them.

        Cheap: Note is frozen, so a snapshot is a new list of the same objects
        rather than a copy of anything. Edits write straight through to the
        run, so without this a mistyped key would be permanent.
        """
        self.undo_stack.append(list(self.notes))
        del self.undo_stack[:-self.UNDO_DEPTH]
        self.redo_stack.clear()

    def _commit(self, notes: list[Note], keep: Note | None) -> None:
        """Adopt an edited note list, keeping `keep` selected.

        Sorted by start time, because moving a note past its neighbour would
        otherwise leave the sequence and the table reading out of order. The
        selection follows the note itself rather than its index, which the
        sort may well have changed.
        """
        notes = sorted(notes, key=lambda n: n.start)
        self.notes = notes
        if keep is None:
            self.selected_note = None if not notes else min(
                self.selected_note or 0, len(notes) - 1
            )
        else:
            self.selected_note = next(
                (i for i, n in enumerate(notes) if n is keep), None
            )
        self._show_notes(self.notes)
        self._save_edited_notes()

    def _replace_selected(self, **changes) -> None:
        """Rewrite the chosen note. Notes are frozen, so this makes a new one."""
        index = self.selected_note
        if index is None or not (0 <= index < len(self.notes)):
            return
        note = self.notes[index]
        fields = {
            "midi": note.midi,
            "start": note.start,
            "end": note.end,
            "freq": note.freq,
            "confidence": note.confidence,
            "pitch": note.pitch,
            "attack": note.attack,
        }
        fields.update(changes)
        self._push_undo()
        replacement = Note(**fields)
        notes = list(self.notes)
        notes[index] = replacement
        self._commit(notes, replacement)

    def _default_pitch(self) -> int:
        """A sensible pitch for a note being added from nothing."""
        if self.notes:
            index = self.selected_note or 0
            return self.notes[min(index, len(self.notes) - 1)].midi
        voiced = [f.freq for f in self.frames if f.voiced and f.confidence >= 0.55]
        if voiced:
            import numpy as np

            return int(round(hz_to_midi(float(np.median(voiced)))))
        return 60

    def edit_insert(self) -> None:
        """Add a note detection missed, after the selected one."""
        if not self.editing:
            return

        midi = self._default_pitch()
        if self.notes and self.selected_note is not None:
            after = self.notes[self.selected_note]
            start = after.end + self.INSERT_GAP
            length = after.duration
        else:
            start, length = 0.0, self.DEFAULT_NEW_DURATION

        added = Note(
            midi=midi,
            start=start,
            end=start + length,
            freq=midi_to_hz(midi),
            confidence=1.0,
            pitch=float(midi),
            attack=True,
        )
        self._push_undo()
        self._commit(self.notes + [added], added)
        self._set_hint(f"Added {spell(midi, self.notation)} — move it with , . ↑ ↓")

    def edit_remove(self) -> None:
        """Drop a note that should not be there."""
        if not self.editing or self.selected_note is None or not self.notes:
            return
        index = self.selected_note
        gone = self.notes[index]
        self._push_undo()
        remaining = [n for n in self.notes if n is not gone]
        self.selected_note = min(index, len(remaining) - 1) if remaining else None
        self._commit(remaining, None)
        self._set_hint(f"Removed {spell(gone.midi, self.notation)} — z to undo")

    def edit_undo(self) -> None:
        if not self.editing or not self.undo_stack:
            self._set_hint("Nothing to undo.")
            return
        self.redo_stack.append(list(self.notes))
        self._commit(self.undo_stack.pop(), None)
        self._set_hint("Undone.")

    def edit_redo(self) -> None:
        if not self.editing or not self.redo_stack:
            self._set_hint("Nothing to redo.")
            return
        self.undo_stack.append(list(self.notes))
        self._commit(self.redo_stack.pop(), None)
        self._set_hint("Redone.")

    def edit_transpose(self, semitones: int) -> None:
        if not self.editing:
            return
        index = self.selected_note
        if index is None:
            return
        note = self.notes[index]
        midi = max(0, min(127, note.midi + semitones))
        # Move the measured pitch with it, so the tuning column keeps reporting
        # the distance from the *hummed* pitch rather than becoming nonsense.
        self._replace_selected(
            midi=midi,
            pitch=(note.pitch + semitones) if note.pitch else float(midi),
            freq=midi_to_hz(midi + (note.cents_off / 100.0)),
        )
        self._set_hint(f"{spell(midi, self.notation)}")

    def edit_shift(self, direction: int) -> None:
        """Move a note earlier or later without changing its length."""
        if not self.editing:
            return
        index = self.selected_note
        if index is None:
            return
        note = self.notes[index]
        delta = self.NUDGE * direction
        start = max(0.0, note.start + delta)
        self._replace_selected(start=start, end=start + note.duration)

    def edit_resize(self, direction: int) -> None:
        """Lengthen or shorten a note, keeping its start where it is."""
        if not self.editing:
            return
        index = self.selected_note
        if index is None:
            return
        note = self.notes[index]
        end = max(note.start + self.MIN_DURATION, note.end + self.NUDGE * direction)
        self._replace_selected(end=end)

    def _save_edited_notes(self) -> None:
        """Write edits back to the run they came from, if there is one."""
        session = self.current_session
        if session is None:
            return
        try:
            self.store.update_notes(session, self.notes)
        except (OSError, ValueError):
            pass
        self.refresh_sessions(select=session.path)

    # -- calibration -------------------------------------------------------

    def _refresh_calibration(self) -> None:
        pane = self._find("#calibration", CalibrationPane)
        if pane is None:
            return
        live, level = "", 0.0
        if self.recorder.running:
            reading = self.recorder.latest()
            live, level = reading.note, reading.level
        pane.show(
            step=self.cal_step,
            recording=self.recorder.running and self.cal_step is not None,
            takes=self.cal_takes,
            result=self.cal_result,
            live=live,
            level=level,
            profile=self.profile,
            saved=self.cal_saved,
        )

    def _reset_calibration(self) -> None:
        self.cal_step = None
        self.cal_takes = {}
        self.cal_frames = {}
        self.cal_result = None
        self.cal_saved = False
        self._refresh_calibration()

    def _toggle_calibration(self) -> None:
        """One key drives the whole thing: start a step, or finish it."""
        if self.recorder.running:
            self._finish_calibration_step()
        else:
            self._start_calibration_step()

    def _start_calibration_step(self) -> None:
        if self.cal_step is None or self.cal_step >= len(CALIBRATION_STEPS):
            self._reset_calibration()
            self.cal_step = 0

        self._stop_playback()
        try:
            self.recorder.start()
        except AudioError as exc:
            self._set_hint(
                Text(f"Could not open the microphone: {exc}", style="bold red")
            )
            return
        self._record_timer = self.set_interval(1 / 10, self._refresh_calibration)
        self._refresh_calibration()

    def _finish_calibration_step(self) -> None:
        if self._record_timer is not None:
            self._record_timer.stop()
            self._record_timer = None

        frames = self.recorder.stop()
        step = CALIBRATION_STEPS[self.cal_step]
        self.cal_frames[step.key] = frames

        from .calibration import measure_note
        from .pitch import midi_to_name

        if step.key == "scale":
            self.cal_takes[step.key] = "captured"
        else:
            midi = measure_note(frames)
            self.cal_takes[step.key] = midi_to_name(midi) if midi else "not heard"

        self.cal_step += 1
        if self.cal_step >= len(CALIBRATION_STEPS):
            self._apply_calibration()
        self._refresh_calibration()

    def _apply_calibration(self) -> None:
        """Work out the settings, and adopt them only if they are trustworthy."""
        from datetime import datetime

        result = calibrate(
            self.cal_frames.get("low", []),
            self.cal_frames.get("high", []),
            self.cal_frames.get("scale", []),
            measured_at=datetime.now().isoformat(timespec="seconds"),
        )
        self.cal_result = result
        self.cal_step = None
        self.cal_saved = False

        if result.confident:
            self._keep_calibration()
        else:
            # Offer it rather than discarding it: the range, tuning and
            # steadiness were measured from the singing itself and hold
            # regardless, and settings that are merely imperfect still beat
            # having none.
            self._set_hint(Text(result.message, style="yellow"))

    def action_keep_calibration(self) -> None:
        """Adopt a calibration the app was not fully confident about."""
        if self._active_tab() != "tab-calibrate" or self.recorder.running:
            return
        if self.cal_result is None or self.cal_saved:
            return
        self._keep_calibration()

    def _keep_calibration(self) -> None:
        result = self.cal_result
        if result is None:
            return

        self.sensitivity = result.pitch_dial
        self.pause_sensitivity = result.pause_dial
        self.profile.calibration = result.calibration
        for selector, kind, value in (
            ("#sensitivity", SensitivityDial, self.sensitivity),
            ("#pause", PauseDial, self.pause_sensitivity),
        ):
            dial = self._find(selector, kind)
            if dial is not None:
                dial.show(value)
        self._remember_dials()
        self.cal_saved = True
        if self.frames:
            self._resegment()
        self._set_hint(result.message)
        self._refresh_calibration()

    def action_play_reference(self) -> None:
        """Play the reference tune. The key only applies on the Calibrating tab."""
        if self._active_tab() != "tab-calibrate":
            return
        self._play_reference()

    def _play_reference(self) -> None:
        """Play the tune the user is being asked to sing back.

        Separate from the action so the tab's own button can call it without
        the tab check, which is trivially satisfied there anyway.
        """
        from .calibration import reference_notes

        if self.recorder.running:
            # Playing now would be recorded through the microphone.
            self._set_hint(
                Text("Finish this step first, then press l.", style="yellow")
            )
            return
        try:
            self.player.play(reference_notes())
        except Exception as exc:
            self._set_hint(Text(f"Could not play audio: {exc}", style="bold red"))
            return
        self._set_hint("Playing the melody — sing it back when it finishes.")

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
        # Safe to switch directly here: this only runs from a user action,
        # long after mount, so there is nothing left to race with.
        self._restore_tab_now(profile)
        if profile.is_guest:
            self._set_hint("Continuing as guest — settings will not be saved.")
        else:
            self._set_hint(f"Settings loaded for “{profile.name}”.")

    def _apply_profile(self, profile: Profile) -> None:
        self.profile = profile
        self.sensitivity = profile.pitch_sensitivity
        self.pause_sensitivity = profile.pause_sensitivity
        self.mix = profile.mix
        self.notation = profile.notation
        self._apply_calibrated_detection(profile)
        self.sub_title = f"{profile.name} · hum a melody, get the keyboard notes"

        for selector, kind, value in (
            ("#sensitivity", SensitivityDial, self.sensitivity),
            ("#pause", PauseDial, self.pause_sensitivity),
            ("#mix", MixDial, self.mix),
            ("#notation", NotationRow, self.notation),
        ):
            dial = self._find(selector, kind)
            if dial is not None:
                dial.show(value)
        if self.frames:
            self._resegment()
        self._refresh_calibration()

    def _restore_startup_tab(self) -> None:
        """Open on the remembered tab, unless the user has already moved.

        The restore is deferred, so it can arrive after a fast user has
        switched tabs themselves. Only acting while still on the default tab
        means it can never drag them back.
        """
        content = self._find("TabbedContent", TabbedContent)
        if content is not None and content.active == DEFAULT_TAB:
            self._restore_tab_now(self.profile)
        self._tab_ready = True

    def _restore_tab_now(self, profile: Profile) -> None:
        """Switch to a profile's remembered tab, after startup.

        Set through the Tabs widget rather than TabbedContent.active, which
        reverts on the next refresh -- Tabs keys its tabs by a prefixed id and
        syncs back over the assignment.
        """
        tabs = self._find("Tabs", Tabs)
        content = self._find("TabbedContent", TabbedContent)
        if tabs is None or content is None:
            return
        wanted = profile.last_tab if profile.last_tab in TAB_IDS else DEFAULT_TAB
        if wanted != content.active:
            try:
                tabs.active = f"--content-tab-{wanted}"
            except Exception:
                pass  # a tab that no longer exists; stay where we are

    def on_tabbed_content_tab_activated(
        self, event: TabbedContent.TabActivated
    ) -> None:
        """Remember the tab, so the next session opens where this one left off."""
        if not self._tab_ready:
            return
        active = self._active_tab()
        if not active or self.profile.last_tab == active:
            return
        self.profile.last_tab = active
        if not self.profile.is_guest:
            try:
                self.profiles.save(self.profile)
            except OSError:
                pass

    def _apply_calibrated_detection(self, profile: Profile) -> None:
        """Feed what calibration measured into detection itself.

        Only two of the measurements are used, deliberately. The range narrows
        YIN's search, which is something the dials cannot do at all: they tune
        segmentation, which runs *after* pitch detection, so they can never
        undo an octave error. The tuning offset stands in when a run is too
        short to estimate its own. Drift and glide are left alone because the
        dial search already compensates for them, and applying both would
        correct for the same thing twice.
        """
        bounds = voice_bounds(profile.calibration)
        fmin, fmax = bounds if bounds else (GLOBAL_FMIN, GLOBAL_FMAX)
        for recorder in (self.recorder,):
            if hasattr(recorder, "fmin"):
                recorder.fmin, recorder.fmax = fmin, fmax
        self.tuning_prior = profile.calibration.tuning_offset_cents

    def _remember_dials(self) -> None:
        """Persist dial positions to the profile. Guests are not remembered."""
        if self.profile.is_guest:
            return
        self.profile.pitch_sensitivity = self.sensitivity
        self.profile.pause_sensitivity = self.pause_sensitivity
        self.profile.mix = self.mix
        self.profile.notation = self.notation
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
        if self._active_tab() == "tab-calibrate":
            if not self.recorder.running:
                self._reset_calibration()
            return
        if self.recorder.running:
            return
        self._stop_playback()
        self._clear_results()
        self.query_one("#readout", NoteReadout).idle("Ready.")
        self._set_hint("Press Start (or space) and hum your melody.")

    def _show_notes(self, notes: list[Note]) -> None:
        chosen = self.selected_note if self.editing else None
        self.query_one("#roll", PianoRoll).show(notes, chosen, self.notation)
        self.query_one("#sequence", MelodySequence).show(notes, chosen, self.notation)
        self.query_one("#play", Button).disabled = not (notes or self.audio is not None)
        self.query_one("#detail", DetailTable).show(notes, chosen, self.notation)

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

    def _segment(self, frames) -> list[Note]:
        return segment_with_sensitivity(
            frames,
            self.sensitivity,
            self.pause_sensitivity,
            tuning_prior=self.tuning_prior,
        )

    def _resegment(self) -> None:
        self.notes = self._segment(self.frames)
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

    def action_cycle_notation(self) -> None:
        """Switch how notes are spelled. Never changes what was detected."""
        self.notation = next_scheme(self.notation)
        row = self._find("#notation", NotationRow)
        if row is not None:
            row.show(self.notation)
        self.profile.notation = self.notation
        if not self.profile.is_guest:
            try:
                self.profiles.save(self.profile)
            except OSError:
                pass
        self._show_notes(self.notes)
        self._set_hint(f"Notes shown as {get_scheme(self.notation).label}.")

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
        self.editing = False
        self.selected_note = None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.current_session = None
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
