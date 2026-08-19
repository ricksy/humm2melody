"""humm2melody — hum a melody, get the notes to play on a keyboard."""

from .pitch import PitchFrame, detect_pitch, hz_to_note, midi_to_name
from .segment import Note, segment_notes

__version__ = "0.8.0"

__all__ = [
    "Note",
    "PitchFrame",
    "detect_pitch",
    "hz_to_note",
    "midi_to_name",
    "segment_notes",
]
