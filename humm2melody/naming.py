"""How a pitch is spelled.

The same note has different names in different traditions, and the differences
are not merely cosmetic. German is the trap: **H** is what English calls B, and
**B** is what English calls B flat. Reading a German name with English habits
gets you a semitone wrong, silently.

Pitch is always stored as a MIDI number. This module only decides how to write
it down, so switching scheme can never change what was detected or what gets
played.
"""

from __future__ import annotations

from dataclasses import dataclass

SHARP = "♯"


@dataclass(frozen=True)
class Scheme:
    """One way of spelling the twelve pitch classes."""

    key: str
    label: str
    names: tuple[str, ...]
    note: str = ""
    show_octave: bool = True

    def spell(self, midi: int) -> str:
        name = self.names[midi % 12]
        if not self.show_octave:
            return name
        return f"{name}{midi // 12 - 1}"


ENGLISH = Scheme(
    key="english",
    label="English",
    names=("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"),
    note="C D E F G A B",
)

GERMAN = Scheme(
    key="german",
    label="German",
    # H is English B; B is English B flat. The one genuinely confusing scheme.
    names=(
        "C", "Cis", "D", "Dis", "E", "F", "Fis", "G", "Gis", "A", "B", "H",
    ),
    note="C D E F G A H  (B is B♭)",
)

SOLFEGE = Scheme(
    key="solfege",
    label="Solfège",
    names=(
        "Do", f"Do{SHARP}", "Re", f"Re{SHARP}", "Mi", "Fa",
        f"Fa{SHARP}", "Sol", f"Sol{SHARP}", "La", f"La{SHARP}", "Si",
    ),
    note="Do Re Mi Fa Sol La Si  (fixed do)",
)

SARGAM = Scheme(
    key="sargam",
    label="Sargam",
    names=(
        "Sa", "re", "Re", "ga", "Ga", "Ma", "ma", "Pa", "dha", "Dha", "ni", "Ni",
    ),
    note="Sa Re Ga Ma Pa Dha Ni  (lower case = komal)",
)

SCHEMES: tuple[Scheme, ...] = (ENGLISH, GERMAN, SOLFEGE, SARGAM)
DEFAULT_SCHEME = ENGLISH.key

_BY_KEY = {scheme.key: scheme for scheme in SCHEMES}


def get_scheme(key: str | None) -> Scheme:
    """Look up a scheme, falling back to English for anything unrecognised."""
    return _BY_KEY.get(key or "", ENGLISH)


def spell(midi: int, scheme: str | Scheme | None = None) -> str:
    """Write a MIDI number the way the chosen tradition would."""
    if not isinstance(scheme, Scheme):
        scheme = get_scheme(scheme)
    return scheme.spell(midi)


def next_scheme(key: str | None) -> str:
    """The next scheme in the cycle."""
    current = get_scheme(key)
    index = SCHEMES.index(current)
    return SCHEMES[(index + 1) % len(SCHEMES)].key
