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
import wave
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from .pitch import PitchFrame
from .playback import SAMPLE_RATE as PLAYBACK_RATE
from .playback import render
from .segment import Note

MANIFEST = "notes.json"
HUM_WAV = "hum.wav"
PLAYBACK_WAV = "playback.wav"
PITCH_CSV = "pitch_track.csv"

DIR_FORMAT = "%Y-%m-%d_%H-%M-%S"
LABEL_SEPARATOR = "__"
MAX_LABEL = 40

DEFAULT_OUTPUT_DIR = Path("recordings")


def slugify(label: str) -> str:
    """Reduce a user-supplied label to something safe for a directory name."""
    cleaned = re.sub(r"[^\w\s-]", "", label, flags=re.UNICODE).strip()
    cleaned = re.sub(r"[\s_]+", "-", cleaned).strip("-")
    return cleaned[:MAX_LABEL]


def write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    """Write mono float samples as 16-bit PCM."""
    clipped = np.clip(np.asarray(samples, dtype=np.float64), -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """Read a mono 16-bit PCM file back into floats."""
    with wave.open(str(path), "rb") as handle:
        sample_rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32767.0, sample_rate


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

    @property
    def hum_path(self) -> Path:
        return self.path / HUM_WAV

    @property
    def playback_path(self) -> Path:
        return self.path / PLAYBACK_WAV

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

        write_wav(path / HUM_WAV, audio, sample_rate)
        write_wav(path / PLAYBACK_WAV, render(notes, PLAYBACK_RATE), PLAYBACK_RATE)

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
                "hum": HUM_WAV,
                "playback": PLAYBACK_WAV,
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
