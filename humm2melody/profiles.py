"""User profiles.

Every threshold in this app was originally tuned by hand against one person's
voice, which is exactly the thing that should be measured per user instead.
A profile is where that lives: the dial settings someone has settled on, and
eventually what calibration learns about their range and habits.

Profiles are one JSON file each, so a profile can be copied, edited by hand or
deleted without touching anything else. Guest is not a file — it is the absence
of one, and nothing about a guest session is remembered.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .sessions import slugify

DEFAULT_PROFILE_DIR = Path("profiles")
GUEST_NAME = "Guest"


@dataclass
class Calibration:
    """What a calibration run learned about a voice. All optional until run."""

    range_low_midi: int | None = None
    range_high_midi: int | None = None
    tuning_offset_cents: float | None = None
    typical_drift_cents: float | None = None
    glide_fraction: float | None = None
    pitch_accuracy_cents: float | None = None
    transpose_semitones: int | None = None
    measured_at: str | None = None

    @property
    def is_empty(self) -> bool:
        return all(value is None for value in asdict(self).values())


@dataclass
class Profile:
    """One user's remembered settings."""

    name: str
    path: Path | None = None  # None means Guest: nothing is persisted
    created: datetime = field(default_factory=datetime.now)
    pitch_sensitivity: int = 5
    pause_sensitivity: int = 5
    mix: int = 5
    last_tab: str = "tab-record"
    calibration: Calibration = field(default_factory=Calibration)

    @property
    def is_guest(self) -> bool:
        return self.path is None

    @property
    def summary(self) -> str:
        if self.is_guest:
            return "nothing is saved"
        if self.calibration.is_empty:
            return f"created {self.created:%Y-%m-%d} · not calibrated"
        return f"created {self.created:%Y-%m-%d} · calibrated"


def guest() -> Profile:
    """The anonymous profile. Settings apply for the session and are forgotten."""
    return Profile(name=GUEST_NAME, path=None)


class ProfileStore:
    """Owns the profiles directory."""

    def __init__(self, root: Path | str = DEFAULT_PROFILE_DIR) -> None:
        self.root = Path(root).expanduser()

    def _path_for(self, name: str) -> Path:
        slug = slugify(name) or "profile"
        return self.root / f"{slug}.json"

    def create(self, name: str) -> Profile:
        """Create a profile. Raises ValueError on a blank or duplicate name."""
        name = name.strip()
        if not name:
            raise ValueError("a profile needs a name")
        if name.casefold() == GUEST_NAME.casefold():
            raise ValueError(f"{GUEST_NAME} is reserved")

        path = self._path_for(name)
        if path.exists():
            raise ValueError(f"a profile called {name!r} already exists")

        self.root.mkdir(parents=True, exist_ok=True)
        profile = Profile(name=name, path=path)
        self.save(profile)
        return profile

    def save(self, profile: Profile) -> None:
        """Persist a profile. Guests are silently skipped, by design."""
        if profile.is_guest or profile.path is None:
            return
        payload = {
            "version": 1,
            "name": profile.name,
            "created": profile.created.isoformat(timespec="seconds"),
            "dials": {
                "pitch": profile.pitch_sensitivity,
                "pause": profile.pause_sensitivity,
                "mix": profile.mix,
            },
            "last_tab": profile.last_tab,
            "calibration": asdict(profile.calibration),
        }
        profile.path.parent.mkdir(parents=True, exist_ok=True)
        with open(profile.path, "w") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")

    def load(self, path: Path) -> Profile | None:
        """Read one profile. Returns None if the file is not a valid profile."""
        try:
            with open(path) as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict) or not data.get("name"):
            return None

        try:
            created = datetime.fromisoformat(data["created"])
        except (KeyError, ValueError):
            created = datetime.fromtimestamp(path.stat().st_mtime)

        dials = data.get("dials") or {}
        known = {f for f in Calibration.__dataclass_fields__}
        raw = data.get("calibration") or {}

        return Profile(
            name=str(data["name"]),
            path=path,
            created=created,
            pitch_sensitivity=int(dials.get("pitch", 5)),
            pause_sensitivity=int(dials.get("pause", 5)),
            mix=int(dials.get("mix", 5)),
            last_tab=str(data.get("last_tab") or "tab-record"),
            calibration=Calibration(
                **{k: v for k, v in raw.items() if k in known}
            ),
        )

    def list(self) -> list[Profile]:
        """Every valid profile, alphabetically. Unreadable files are skipped."""
        if not self.root.is_dir():
            return []
        found = [
            profile
            for child in sorted(self.root.glob("*.json"))
            if (profile := self.load(child)) is not None
        ]
        found.sort(key=lambda p: p.name.casefold())
        return found

    def _owns(self, profile: Profile) -> bool:
        if profile.path is None:
            return False
        try:
            return profile.path.resolve().parent == self.root.resolve()
        except OSError:
            return False

    def delete(self, profile: Profile) -> None:
        """Remove a profile. Recordings it produced are left alone."""
        if profile.is_guest:
            raise ValueError("the guest profile is not stored")
        if not self._owns(profile):
            raise ValueError(f"{profile.path} is not inside {self.root}")
        profile.path.unlink(missing_ok=True)
