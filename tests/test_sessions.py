"""Session store tests: saving, loading, renaming and deleting runs."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from humm2melody.pitch import PitchFrame, midi_to_hz
from humm2melody.segment import Note
from humm2melody.sessions import (
    HUM_WAV,
    MANIFEST,
    PITCH_CSV,
    PLAYBACK_WAV,
    Session,
    SessionStore,
    read_wav,
    slugify,
    write_wav,
)

SR = 22050


def sample_notes() -> list[Note]:
    return [
        Note(midi=60, start=0.0, end=0.4, freq=261.6, confidence=0.93),
        Note(midi=64, start=0.5, end=0.9, freq=329.6, confidence=0.91),
    ]


def sample_frames(count: int = 20) -> list[PitchFrame]:
    step = 512 / SR
    return [
        PitchFrame(i * step, midi_to_hz(60), 0.9, 0.2) for i in range(count)
    ]


def sample_audio(seconds: float = 1.0) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (0.4 * np.sin(2 * np.pi * 261.6 * t)).astype(np.float32)


def save_one(store: SessionStore, when: datetime | None = None) -> Session:
    return store.save(
        audio=sample_audio(),
        sample_rate=SR,
        frames=sample_frames(),
        notes=sample_notes(),
        timestamp=when,
    )


# -- wav helpers -----------------------------------------------------------


def test_wav_round_trip(tmp_path: Path):
    original = sample_audio(0.25)
    write_wav(tmp_path / "a.wav", original, SR)
    restored, rate = read_wav(tmp_path / "a.wav")

    assert rate == SR
    assert restored.size == original.size
    assert np.max(np.abs(restored - original)) < 1e-3  # 16-bit quantisation


def test_wav_clips_instead_of_wrapping(tmp_path: Path):
    """Out-of-range samples must clamp, not wrap around to the opposite sign."""
    loud = np.array([2.0, -2.0, 0.0], dtype=np.float32)
    write_wav(tmp_path / "loud.wav", loud, SR)
    restored, _ = read_wav(tmp_path / "loud.wav")

    assert restored[0] > 0.99
    assert restored[1] < -0.99


# -- slugs -----------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("My Melody", "My-Melody"),
        ("  spaced  out  ", "spaced-out"),
        ("../../etc/passwd", "etcpasswd"),
        ("weird/\\:*?chars", "weirdchars"),
        ("", ""),
        ("...", ""),
    ],
)
def test_slugify(raw, expected):
    assert slugify(raw) == expected


def test_slugify_is_length_capped():
    assert len(slugify("x" * 200)) <= 40


# -- saving ----------------------------------------------------------------


def test_save_writes_every_artifact(tmp_path: Path):
    store = SessionStore(tmp_path)
    session = save_one(store)

    for name in (HUM_WAV, PLAYBACK_WAV, PITCH_CSV, MANIFEST):
        assert (session.path / name).is_file(), f"{name} missing"


def test_saved_hum_matches_the_captured_audio(tmp_path: Path):
    store = SessionStore(tmp_path)
    audio = sample_audio(0.5)
    session = store.save(
        audio=audio, sample_rate=SR, frames=sample_frames(), notes=sample_notes()
    )

    restored, rate = read_wav(session.hum_path)
    assert rate == SR
    assert restored.size == audio.size
    assert np.max(np.abs(restored - audio)) < 1e-3


def test_saved_playback_is_audible(tmp_path: Path):
    store = SessionStore(tmp_path)
    session = save_one(store)
    restored, _ = read_wav(session.playback_path)
    assert np.max(np.abs(restored)) > 0.1


def test_manifest_contents(tmp_path: Path):
    store = SessionStore(tmp_path)
    session = save_one(store)

    data = json.loads(session.manifest_path.read_text())
    assert data["sample_rate"] == SR
    assert [n["name"] for n in data["notes"]] == ["C4", "E4"]
    assert data["notes"][0]["start"] == pytest.approx(0.0)
    assert data["duration"] == pytest.approx(1.0, abs=0.01)


def test_pitch_track_has_a_row_per_frame(tmp_path: Path):
    store = SessionStore(tmp_path)
    frames = sample_frames(37)
    session = store.save(
        audio=sample_audio(), sample_rate=SR, frames=frames, notes=sample_notes()
    )

    with open(session.pitch_track_path) as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 37
    assert set(rows[0]) == {"time", "freq", "confidence", "rms"}
    assert float(rows[0]["freq"]) == pytest.approx(midi_to_hz(60), abs=0.01)


def test_directory_is_named_by_timestamp(tmp_path: Path):
    store = SessionStore(tmp_path)
    session = save_one(store, when=datetime(2026, 8, 19, 14, 32, 5))
    assert session.path.name == "2026-08-19_14-32-05"


def test_runs_in_the_same_second_do_not_collide(tmp_path: Path):
    store = SessionStore(tmp_path)
    when = datetime(2026, 8, 19, 14, 32, 5)
    first = save_one(store, when=when)
    second = save_one(store, when=when)

    assert first.path != second.path
    assert second.path.exists()


def test_save_creates_the_output_directory(tmp_path: Path):
    store = SessionStore(tmp_path / "nested" / "recordings")
    session = save_one(store)
    assert session.path.is_dir()


def test_a_run_with_no_notes_is_still_saved(tmp_path: Path):
    """Failed transcriptions are exactly what you want to analyse later."""
    store = SessionStore(tmp_path)
    session = store.save(
        audio=sample_audio(), sample_rate=SR, frames=sample_frames(), notes=[]
    )
    assert session.hum_path.is_file()
    assert session.notes == []


# -- loading ---------------------------------------------------------------


def test_round_trip_through_disk(tmp_path: Path):
    store = SessionStore(tmp_path)
    saved = save_one(store)
    loaded = store.load(saved.path)

    assert loaded is not None
    assert [n.name for n in loaded.notes] == ["C4", "E4"]
    assert loaded.notes[0].start == pytest.approx(0.0)
    assert loaded.notes[1].end == pytest.approx(0.9)
    assert loaded.duration == pytest.approx(saved.duration)


def test_list_is_newest_first(tmp_path: Path):
    store = SessionStore(tmp_path)
    save_one(store, when=datetime(2026, 8, 19, 10, 0, 0))
    save_one(store, when=datetime(2026, 8, 19, 12, 0, 0))
    save_one(store, when=datetime(2026, 8, 19, 11, 0, 0))

    hours = [s.timestamp.hour for s in store.list()]
    assert hours == [12, 11, 10]


def test_list_on_missing_directory_is_empty(tmp_path: Path):
    assert SessionStore(tmp_path / "nope").list() == []


def test_unrelated_directories_are_ignored(tmp_path: Path):
    store = SessionStore(tmp_path)
    save_one(store)
    (tmp_path / "not-a-run").mkdir()

    assert len(store.list()) == 1


def test_corrupt_manifest_is_skipped_not_fatal(tmp_path: Path):
    store = SessionStore(tmp_path)
    save_one(store)
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / MANIFEST).write_text("{not json")

    assert len(store.list()) == 1


# -- renaming --------------------------------------------------------------


def test_rename_moves_the_directory_and_keeps_the_timestamp(tmp_path: Path):
    store = SessionStore(tmp_path)
    session = save_one(store, when=datetime(2026, 8, 19, 14, 32, 5))
    old_path = session.path

    store.rename(session, "Chorus idea")

    assert not old_path.exists()
    assert session.path.name == "2026-08-19_14-32-05__Chorus-idea"
    assert session.label == "Chorus idea"


def test_rename_keeps_the_files(tmp_path: Path):
    store = SessionStore(tmp_path)
    session = save_one(store)
    store.rename(session, "kept")

    for name in (HUM_WAV, PLAYBACK_WAV, PITCH_CSV, MANIFEST):
        assert (session.path / name).is_file()


def test_rename_survives_a_reload(tmp_path: Path):
    store = SessionStore(tmp_path)
    session = save_one(store)
    store.rename(session, "Verse two")

    loaded = store.list()[0]
    assert loaded.label == "Verse two"
    assert loaded.display_name == "Verse two"


def test_empty_label_reverts_to_the_timestamp(tmp_path: Path):
    store = SessionStore(tmp_path)
    session = save_one(store, when=datetime(2026, 8, 19, 14, 32, 5))
    store.rename(session, "temporary")
    store.rename(session, "")

    assert session.path.name == "2026-08-19_14-32-05"
    assert session.label == ""


def test_rename_cannot_escape_the_output_directory(tmp_path: Path):
    store = SessionStore(tmp_path)
    session = save_one(store)
    store.rename(session, "../../escaped")

    assert session.path.parent == tmp_path


def test_rename_rejects_a_session_from_outside_the_store(tmp_path: Path):
    store = SessionStore(tmp_path / "mine")
    store.root.mkdir(parents=True)
    outsider = Session(path=tmp_path / "elsewhere", timestamp=datetime.now())

    with pytest.raises(ValueError):
        store.rename(outsider, "nope")


# -- deleting --------------------------------------------------------------


def test_delete_removes_the_run(tmp_path: Path):
    store = SessionStore(tmp_path)
    session = save_one(store)
    store.delete(session)

    assert not session.path.exists()
    assert store.list() == []


def test_delete_leaves_other_runs_alone(tmp_path: Path):
    store = SessionStore(tmp_path)
    first = save_one(store, when=datetime(2026, 8, 19, 10, 0, 0))
    second = save_one(store, when=datetime(2026, 8, 19, 11, 0, 0))

    store.delete(first)

    assert second.path.exists()
    assert len(store.list()) == 1


def test_delete_refuses_a_directory_outside_the_store(tmp_path: Path):
    store = SessionStore(tmp_path / "mine")
    store.root.mkdir(parents=True)
    precious = tmp_path / "precious"
    precious.mkdir()
    (precious / "keep.txt").write_text("do not delete me")

    with pytest.raises(ValueError):
        store.delete(Session(path=precious, timestamp=datetime.now()))

    assert (precious / "keep.txt").exists()


def test_delete_refuses_the_store_root_itself(tmp_path: Path):
    store = SessionStore(tmp_path)
    save_one(store)

    with pytest.raises(ValueError):
        store.delete(Session(path=tmp_path, timestamp=datetime.now()))

    assert tmp_path.exists()


def test_delete_refuses_a_directory_that_is_not_a_run(tmp_path: Path):
    store = SessionStore(tmp_path)
    stray = tmp_path / "stray"
    stray.mkdir()
    (stray / "important.txt").write_text("not a run")

    with pytest.raises(ValueError):
        store.delete(Session(path=stray, timestamp=datetime.now()))

    assert (stray / "important.txt").exists()
