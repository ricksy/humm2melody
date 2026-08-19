"""Recording every run to disk, for later analysis.

Each run gets its own timestamped directory holding everything needed to work
out *why* a transcription came out the way it did:

    recordings/2026-08-19_14-32-05/
        hum.wav          the raw microphone input
        playback.wav     the tones the app would play back
        notes.json       the manifest: detected notes plus run metadata
        pitch_track.csv  every analysis frame: time, freq, confidence, rms

The pitch track is the useful one when something goes wrong — it shows the
detector's frame-by-frame opinion before smoothing and segmentation threw
anything away.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from .pitch import PitchFrame
from .playback import SAMPLE_RATE as PLAYBACK_RATE
from .playback import render
from .segment import Note

MANIFEST = "notes.json"
PITCH_CSV = "pitch_track.csv"

HUM_AUDIO = "hum.flac"
"""The hum is stored losslessly: it is the master that re-analysis reads."""

PLAYBACK_AUDIO = "playback.mp3"
"""The tones are lossy: they are regenerable from notes.json at any time."""

LEGACY_HUM = "hum.wav"
LEGACY_PLAYBACK = "playback.wav"

# Kept so older code and tests keep working.
HUM_WAV = LEGACY_HUM
PLAYBACK_WAV = LEGACY_PLAYBACK

DIR_FORMAT = "%Y-%m-%d_%H-%M-%S"
LABEL_SEPARATOR = "__"
MAX_LABEL = 40

DEFAULT_OUTPUT_DIR = Path("recordings")


def slugify(label: str) -> str:
    """Reduce a user-supplied label to something safe for a directory name."""
    cleaned = re.sub(r"[^\w\s-]", "", label, flags=re.UNICODE).strip()
    cleaned = re.sub(r"[\s_]+", "-", cleaned).strip("-")
    return cleaned[:MAX_LABEL]


_FORMATS = {
    ".flac": ("FLAC", "PCM_16"),
    ".mp3": ("MP3", "MPEG_LAYER_III"),
    ".wav": ("WAV", "PCM_16"),
    ".ogg": ("OGG", "VORBIS"),
}


def write_audio(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    """Write mono float samples, picking the codec from the file extension."""
    import soundfile as sf

    audio = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    fmt, subtype = _FORMATS.get(Path(path).suffix.lower(), ("WAV", "PCM_16"))
    sf.write(str(path), audio, int(sample_rate), format=fmt, subtype=subtype)


def read_audio(path: Path) -> tuple[np.ndarray, int]:
    """Read any supported audio file into mono floats."""
    import soundfile as sf

    audio, sample_rate = sf.read(str(path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return np.asarray(audio, dtype=np.float32), int(sample_rate)


# Older names, kept so existing callers and .wav files keep working.
write_wav = write_audio
read_wav = read_audio


def read_pitch_track(path: Path) -> list[PitchFrame]:
    """Load a run's frame-by-frame pitch track back from its CSV.

    Re-segmenting a saved run needs the frames, not the notes: the notes are
    already the *result* of one particular set of thresholds.
    """
    frames: list[PitchFrame] = []
    try:
        with open(path) as handle:
            for row in csv.DictReader(handle):
                frames.append(
                    PitchFrame(
                        time=float(row["time"]),
                        freq=float(row["freq"]),
                        confidence=float(row["confidence"]),
                        rms=float(row["rms"]),
                    )
                )
    except (OSError, KeyError, ValueError):
        return []
    return frames


@dataclass
class Session:
    """One saved run."""

    path: Path
    timestamp: datetime
    label: str = ""
    notes: list[Note] = field(default_factory=list)
    duration: float = 0.0
    sample_rate: int = 0
    starred: bool = False
    profile: str = ""  # who recorded it; empty for guest

    @property
    def display_name(self) -> str:
        return self.label or self.timestamp.strftime("%Y-%m-%d %H:%M:%S")

    @property
    def summary(self) -> str:
        count = len(self.notes)
        return f"{count} note{'' if count == 1 else 's'} · {self.duration:.1f}s"

    def _audio_path(self, preferred: str, legacy: str) -> Path:
        """The stored audio, preferring the current format.

        Runs recorded before the switch to FLAC and MP3 still hold .wav files,
        and they stay readable rather than being migrated: the recordings are
        the user's data, and rewriting them to save disk is not a trade the
        app gets to make on their behalf.
        """
        current = self.path / preferred
        if current.is_file():
            return current
        older = self.path / legacy
        return older if older.is_file() else current

    @property
    def hum_path(self) -> Path:
        return self._audio_path(HUM_AUDIO, LEGACY_HUM)

    @property
    def playback_path(self) -> Path:
        return self._audio_path(PLAYBACK_AUDIO, LEGACY_PLAYBACK)

    @property
    def pitch_track_path(self) -> Path:
        return self.path / PITCH_CSV

    @property
    def manifest_path(self) -> Path:
        return self.path / MANIFEST


class SessionStore:
    """Owns the output directory and the runs inside it."""

    def __init__(self, root: Path | str = DEFAULT_OUTPUT_DIR) -> None:
        self.root = Path(root).expanduser()

    def _unique_dir(self, timestamp: datetime, label: str = "") -> Path:
        base = timestamp.strftime(DIR_FORMAT)
        slug = slugify(label)
        if slug:
            base = f"{base}{LABEL_SEPARATOR}{slug}"
        candidate = self.root / base
        counter = 2
        while candidate.exists():
            candidate = self.root / f"{base}-{counter}"
            counter += 1
        return candidate

    def save(
        self,
        *,
        audio: np.ndarray,
        sample_rate: int,
        frames: list[PitchFrame],
        notes: list[Note],
        timestamp: datetime | None = None,
        profile: str = "",
    ) -> Session:
        """Write one run to disk and return it.

        The playback audio is rendered here rather than captured, so a run has
        a complete record even if the user never pressed play — the rendering
        is deterministic, so it is the same audio they would have heard.
        """
        timestamp = timestamp or datetime.now()
        path = self._unique_dir(timestamp)
        path.mkdir(parents=True, exist_ok=True)

        duration = float(len(audio) / sample_rate) if sample_rate else 0.0

        write_audio(path / HUM_AUDIO, audio, sample_rate)
        write_audio(
            path / PLAYBACK_AUDIO, render(notes, PLAYBACK_RATE), PLAYBACK_RATE
        )

        with open(path / PITCH_CSV, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["time", "freq", "confidence", "rms"])
            for frame in frames:
                writer.writerow(
                    [
                        f"{frame.time:.4f}",
                        f"{frame.freq:.3f}",
                        f"{frame.confidence:.4f}",
                        f"{frame.rms:.6f}",
                    ]
                )

        session = Session(
            path=path,
            timestamp=timestamp,
            label="",
            profile=profile,
            notes=list(notes),
            duration=duration,
            sample_rate=sample_rate,
        )
        self._write_manifest(session)
        return session

    def _write_manifest(self, session: Session) -> None:
        payload = {
            "version": 1,
            "timestamp": session.timestamp.isoformat(timespec="seconds"),
            "label": session.label,
            "starred": session.starred,
            "profile": session.profile,
            "duration": round(session.duration, 4),
            "sample_rate": session.sample_rate,
            "playback_sample_rate": PLAYBACK_RATE,
            "files": {
                "hum": session.hum_path.name,
                "playback": session.playback_path.name,
                "pitch_track": PITCH_CSV,
            },
            "notes": [
                {
                    "index": i,
                    "midi": n.midi,
                    "name": n.name,
                    "start": round(n.start, 4),
                    "end": round(n.end, 4),
                    "duration": round(n.duration, 4),
                    "freq": round(n.freq, 3),
                    "cents_off": round(n.cents_off, 2),
                    "confidence": round(n.confidence, 4),
                }
                for i, n in enumerate(session.notes, start=1)
            ],
        }
        with open(session.manifest_path, "w") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")

    def load(self, path: Path) -> Session | None:
        """Read one run. Returns None if the directory is not a valid run."""
        manifest = path / MANIFEST
        if not manifest.is_file():
            return None
        try:
            with open(manifest) as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, OSError):
            return None

        try:
            timestamp = datetime.fromisoformat(data["timestamp"])
        except (KeyError, ValueError):
            timestamp = datetime.fromtimestamp(manifest.stat().st_mtime)

        notes = [
            Note(
                midi=int(n["midi"]),
                start=float(n["start"]),
                end=float(n["end"]),
                freq=float(n["freq"]),
                confidence=float(n.get("confidence", 0.0)),
            )
            for n in data.get("notes", [])
        ]

        return Session(
            path=path,
            timestamp=timestamp,
            label=str(data.get("label", "")),
            starred=bool(data.get("starred", False)),
            profile=str(data.get("profile", "")),
            notes=notes,
            duration=float(data.get("duration", 0.0)),
            sample_rate=int(data.get("sample_rate", 0)),
        )

    def list(self) -> list[Session]:
        """Every valid run, newest first. Unreadable directories are skipped."""
        if not self.root.is_dir():
            return []
        sessions = [
            session
            for child in self.root.iterdir()
            if child.is_dir() and (session := self.load(child)) is not None
        ]
        # Name breaks ties so runs recorded in the same second keep a stable,
        # predictable order rather than whatever the filesystem returns.
        sessions.sort(key=lambda s: (s.timestamp, s.path.name), reverse=True)
        return sessions

    def _owns(self, session: Session) -> bool:
        """Guard against touching anything outside the output directory."""
        try:
            resolved = session.path.resolve()
            root = self.root.resolve()
        except OSError:
            return False
        return resolved != root and root in resolved.parents

    def rename(self, session: Session, label: str) -> Session:
        """Relabel a run, moving its directory to match.

        The timestamp stays in the directory name so runs keep sorting
        chronologically and names stay unique; an empty label reverts to the
        bare timestamp.
        """
        if not self._owns(session):
            raise ValueError(f"{session.path} is not inside {self.root}")

        label = label.strip()
        target = self._unique_dir(session.timestamp, label)
        if target != session.path:
            session.path.rename(target)
            session.path = target
        session.label = label
        self._write_manifest(session)
        return session

    def update_notes(self, session: Session, notes: list[Note]) -> Session:
        """Rewrite a run's notes after they were edited by hand.

        The pitch track and the hum are left untouched: they are what was
        recorded, and an edit is a correction to the *reading* of it, not a
        claim about what was sung. Re-analysing later still starts from the
        original audio.
        """
        if not self._owns(session):
            raise ValueError(f"{session.path} is not inside {self.root}")
        session.notes = list(notes)
        self._write_manifest(session)
        write_audio(
            session.path / PLAYBACK_AUDIO, render(session.notes, PLAYBACK_RATE),
            PLAYBACK_RATE,
        )
        return session

    def set_starred(self, session: Session, starred: bool) -> Session:
        """Mark a run as a favourite, or clear the mark.

        Stored in the run's own manifest rather than a central index, so a run
        directory stays self-describing: copy it elsewhere and it is still
        starred, delete it and nothing dangles.
        """
        if not self._owns(session):
            raise ValueError(f"{session.path} is not inside {self.root}")
        session.starred = bool(starred)
        self._write_manifest(session)
        return session

    def delete(self, session: Session) -> None:
        """Remove a run and everything in it."""
        if not self._owns(session):
            raise ValueError(f"{session.path} is not inside {self.root}")
        if not session.manifest_path.is_file():
            raise ValueError(f"{session.path} does not look like a saved run")
        shutil.rmtree(session.path)
