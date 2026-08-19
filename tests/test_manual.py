"""The user manual, and the tab that shows it."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from humm2melody.tui import MANUAL_PATH, _manual_text


def manual() -> str:
    return MANUAL_PATH.read_text(encoding="utf-8")


def test_the_manual_ships_beside_the_package():
    """One file, read both in the app and on GitHub."""
    assert MANUAL_PATH.is_file()
    assert MANUAL_PATH.parent.name == "humm2melody"


def test_the_manual_loads():
    text = _manual_text()
    assert text.startswith("# humm2melody user manual")
    assert len(text) > 2000


def test_a_missing_manual_does_not_crash_the_app(monkeypatch, tmp_path):
    """The tab must still render if the file is somehow absent."""
    monkeypatch.setattr("humm2melody.tui.MANUAL_PATH", tmp_path / "gone.md")
    text = _manual_text()
    assert "unavailable" in text.lower()


def test_the_manual_covers_every_binding():
    """A manual that omits a key is worse than one that is short."""
    from humm2melody.tui import Humm2MelodyApp, PianoRoll

    pretty = {
        "left_square_bracket": "`[`",
        "right_square_bracket": "`]`",
        "less_than_sign": "`<`",
        "greater_than_sign": "`>`",
        "comma": "`,`",
        "full_stop": "`.`",
        "minus": "`-`",
        "equals_sign": "`=`",
        "space": "`space`",
        "escape": "`esc`",
        "delete": "`del`",
        "backspace": "`backspace`",
        "shift+z": "`shift+z`",
        "shift+up": "`shift+up`",
        "shift+down": "`shift+down`",
    }
    text = manual()
    missing = []
    for binding in list(Humm2MelodyApp.BINDINGS) + list(PianoRoll.BINDINGS):
        key = binding[0] if isinstance(binding, tuple) else binding.key
        token = pretty.get(key, f"`{key}`")
        if token not in text:
            missing.append(key)
    assert not missing, f"undocumented keys: {missing}"


def test_the_manual_covers_every_command_line_flag():
    from humm2melody import __main__

    source = Path(__main__.__file__).read_text()
    flags = set(re.findall(r'"(--[a-z-]+)"', source))
    text = manual()
    missing = [f for f in flags if f not in text and f != "--help"]
    assert not missing, f"undocumented flags: {missing}"


def test_the_manual_warns_about_german_notation():
    """The one spelling difference that silently puts you a semitone out."""
    text = manual()
    assert "H is what English calls B" in text


def test_the_manual_says_edits_leave_the_recording_alone():
    assert "corrects the **reading**" in manual()


@pytest.mark.parametrize(
    "heading",
    [
        "## Get started",
        "## The tabs",
        "## Record and play back",
        "## Tune the transcription",
        "## Calibrate the app to your voice",
        "## Fix a note by hand",
        "## Compose on the keyboard",
        "## Note names",
        "## Saved runs",
        "## When it goes wrong",
        "## Command line",
        "## Limits",
    ],
)
def test_the_manual_has_its_sections(heading):
    assert heading in manual()
