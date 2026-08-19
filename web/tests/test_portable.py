"""The browser-portable core must not depend on the desktop's audio stack.

The web build (see `docs/pwa.md`) loads `humm2melody` into Pyodide, where
`sounddevice` and `soundfile` cannot exist — both are bindings to C libraries
with no WebAssembly build — and `textual` is meaningless without a terminal.

Today the core is clean, but only by habit: `sounddevice` and `soundfile` are
each imported lazily inside the one function that needs them. This test turns
that habit into a rule, so that a stray top-level import breaks a test here
rather than the web build weeks later.

If this fails, the fix is almost always to move the import inside the function
that uses it, exactly as `audio.py`, `playback.py` and `sessions.py` do.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

PORTABLE = [
    "humm2melody.pitch",
    # Not the Recorder — the web build has its own capture. But the sample
    # rate, window sizes and `meter_level` are shared with it, and web/py
    # imports them rather than duplicating constants that would then drift.
    "humm2melody.audio",
    "humm2melody.segment",
    "humm2melody.analysis",
    "humm2melody.calibration",
    "humm2melody.profiles",
    "humm2melody.naming",
    "humm2melody.demo",
]
"""Modules the browser loads. Anything added here must stay numpy-only."""

FORBIDDEN = ["sounddevice", "soundfile", "textual", "rich"]
"""Absent in Pyodide, or useless there."""

# Run in a subprocess: the modules under test are already imported by the rest
# of the suite, so blocking an import in-process would prove nothing.
PROGRAM = """
import sys


class Blocked:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in {forbidden!r}:
            raise ImportError(f"{{name}} is not available in the browser")
        return None


sys.meta_path.insert(0, Blocked())

import importlib

for module in {modules!r}:
    importlib.import_module(module)

# `render()` and the mixing helpers are reused verbatim by the web build to
# produce a buffer for WebAudio, so they have to import without a sound device.
from humm2melody.playback import mix_hum_with_tones, render, resample

print("ok")
"""


def test_core_imports_without_the_desktop_audio_stack() -> None:
    result = subprocess.run(
        [sys.executable, "-c", PROGRAM.format(forbidden=FORBIDDEN, modules=PORTABLE)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "A browser-portable module now imports something Pyodide cannot "
        f"provide:\n\n{result.stderr}"
    )
    assert result.stdout.strip() == "ok"


@pytest.mark.parametrize("module", PORTABLE)
def test_portable_modules_declare_no_desktop_imports(module: str) -> None:
    """A cheaper, per-module version that names the offender directly."""
    import ast
    import importlib.util

    spec = importlib.util.find_spec(module)
    assert spec is not None and spec.origin is not None
    tree = ast.parse(open(spec.origin).read())

    found: set[str] = set()
    for node in ast.walk(tree):
        # Only top-level imports matter; a lazy import inside a function is the
        # documented way to reach the desktop audio stack.
        if isinstance(node, (ast.Import, ast.ImportFrom)) and node.col_offset == 0:
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            found |= {n.split(".")[0] for n in names} & set(FORBIDDEN)

    assert not found, f"{module} imports {sorted(found)} at module level"
