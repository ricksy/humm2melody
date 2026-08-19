"""Note-naming tests."""

from __future__ import annotations

import pytest

from humm2melody.naming import (
    DEFAULT_SCHEME,
    SCHEMES,
    get_scheme,
    next_scheme,
    spell,
)
from humm2melody.pitch import midi_to_name


def test_english_matches_the_internal_spelling():
    """English is canonical; the rest are presentation."""
    for midi in range(36, 85):
        assert spell(midi, "english") == midi_to_name(midi)


def test_german_uses_h_for_english_b():
    """The trap: H is B, and B is B flat. A semitone apart."""
    assert spell(71, "german") == "H4"      # English B4
    assert spell(70, "german") == "B4"      # English A#4 / B flat
    assert spell(71, "english") == "B4"


def test_german_spells_sharps_with_is():
    assert spell(61, "german") == "Cis4"
    assert spell(66, "german") == "Fis4"


def test_solfege_is_fixed_do():
    assert spell(60, "solfege") == "Do4"
    assert spell(62, "solfege") == "Re4"
    assert spell(64, "solfege") == "Mi4"
    assert spell(71, "solfege") == "Si4"


def test_sargam_marks_komal_in_lower_case():
    assert spell(60, "sargam") == "Sa4"
    assert spell(62, "sargam") == "Re4"
    assert spell(61, "sargam") == "re4"  # komal re


@pytest.mark.parametrize("scheme", [s.key for s in SCHEMES])
def test_every_scheme_spells_every_pitch_class(scheme):
    spellings = {spell(60 + step, scheme) for step in range(12)}
    assert len(spellings) == 12


@pytest.mark.parametrize("scheme", [s.key for s in SCHEMES])
def test_every_scheme_carries_the_octave(scheme):
    assert spell(60, scheme) != spell(72, scheme)


def test_an_unknown_scheme_falls_back_to_english():
    """A profile from a future version must not break the display."""
    assert spell(60, "klingon") == "C4"
    assert spell(60, None) == "C4"
    assert get_scheme("klingon").key == "english"


def test_the_cycle_visits_every_scheme_and_returns():
    seen, key = [], DEFAULT_SCHEME
    for _ in range(len(SCHEMES)):
        seen.append(key)
        key = next_scheme(key)
    assert seen == [s.key for s in SCHEMES]
    assert key == DEFAULT_SCHEME


def test_cycling_from_an_unknown_scheme_is_safe():
    assert next_scheme("nonsense") in {s.key for s in SCHEMES}


def test_every_scheme_describes_itself():
    for scheme in SCHEMES:
        assert scheme.label and scheme.note
