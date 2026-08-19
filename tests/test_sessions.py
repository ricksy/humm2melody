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
    HUM_AUDIO,
    LEGACY_HUM,
    LEGACY_PLAYBACK,
    MANIFEST,
    PITCH_CSV,
    PLAYBACK_AUDIO,
    Session,
    SessionStore,
    read_audio,
    read_wav,
    slugify,
    write_audio,
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

    for name in (HUM_AUDIO, PLAYBACK_AUDIO, PITCH_CSV, MANIFEST):
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

    for name in (HUM_AUDIO, PLAYBACK_AUDIO, PITCH_CSV, MANIFEST):
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


# -- starring --------------------------------------------------------------


def test_runs_start_unstarred(tmp_path: Path):
    store = SessionStore(tmp_path)
    assert save_one(store).starred is False


def test_star_survives_a_reload(tmp_path: Path):
    """The mark lives in the run's own manifest, not in memory."""
    store = SessionStore(tmp_path)
    session = save_one(store)
    store.set_starred(session, True)

    assert store.list()[0].starred is True


def test_star_can_be_cleared(tmp_path: Path):
    store = SessionStore(tmp_path)
    session = save_one(store)
    store.set_starred(session, True)
    store.set_starred(session, False)

    assert store.list()[0].starred is False


def test_star_survives_a_rename(tmp_path: Path):
    store = SessionStore(tmp_path)
    session = save_one(store)
    store.set_starred(session, True)
    store.rename(session, "Reference take")

    reloaded = store.list()[0]
    assert reloaded.starred is True
    assert reloaded.label == "Reference take"


def test_star_is_written_into_the_manifest(tmp_path: Path):
    store = SessionStore(tmp_path)
    session = save_one(store)
    store.set_starred(session, True)

    assert json.loads(session.manifest_path.read_text())["starred"] is True


def test_starring_only_affects_the_chosen_run(tmp_path: Path):
    store = SessionStore(tmp_path)
    first = save_one(store, when=datetime(2026, 8, 19, 10, 0, 0))
    save_one(store, when=datetime(2026, 8, 19, 11, 0, 0))
    store.set_starred(first, True)

    assert [s.starred for s in store.list()] == [False, True]


def test_a_run_from_an_older_manifest_loads_unstarred(tmp_path: Path):
    """Manifests written before starring existed must still load."""
    store = SessionStore(tmp_path)
    session = save_one(store)
    data = json.loads(session.manifest_path.read_text())
    del data["starred"]
    session.manifest_path.write_text(json.dumps(data))

    assert store.list()[0].starred is False


def test_starring_rejects_a_run_outside_the_store(tmp_path: Path):
    store = SessionStore(tmp_path / "mine")
    store.root.mkdir(parents=True)
    outsider = Session(path=tmp_path / "elsewhere", timestamp=datetime.now())

    with pytest.raises(ValueError):
        store.set_starred(outsider, True)


# -- audio formats ---------------------------------------------------------


def test_hum_is_stored_losslessly_as_flac(tmp_path: Path):
    """The hum is the analysis master, so it must survive a round trip intact."""
    store = SessionStore(tmp_path)
    audio = sample_audio(0.5)
    session = store.save(
        audio=audio, sample_rate=SR, frames=sample_frames(), notes=sample_notes()
    )

    assert session.hum_path.name == HUM_AUDIO
    restored, rate = read_audio(session.hum_path)
    assert rate == SR
    assert restored.size == audio.size
    assert np.max(np.abs(restored - audio)) < 1e-3


def test_playback_is_stored_as_mp3(tmp_path: Path):
    store = SessionStore(tmp_path)
    session = save_one(store)

    assert session.playback_path.name == PLAYBACK_AUDIO
    restored, _ = read_audio(session.playback_path)
    assert np.max(np.abs(restored)) > 0.1


def test_flac_is_much_smaller_than_wav(tmp_path: Path):
    audio = sample_audio(2.0)
    write_audio(tmp_path / "a.wav", audio, SR)
    write_audio(tmp_path / "a.flac", audio, SR)
    assert (tmp_path / "a.flac").stat().st_size < (tmp_path / "a.wav").stat().st_size


def test_the_manifest_records_the_real_filenames(tmp_path: Path):
    store = SessionStore(tmp_path)
    session = save_one(store)
    files = json.loads(session.manifest_path.read_text())["files"]
    assert files["hum"] == HUM_AUDIO
    assert files["playback"] == PLAYBACK_AUDIO


def test_a_legacy_wav_run_is_still_readable(tmp_path: Path):
    """Runs recorded before the format switch must keep working, unmigrated."""
    store = SessionStore(tmp_path)
    session = save_one(store)
    audio = sample_audio(0.4)

    # Rewrite it the old way.
    session.hum_path.unlink()
    session.playback_path.unlink()
    write_audio(session.path / LEGACY_HUM, audio, SR)
    write_audio(session.path / LEGACY_PLAYBACK, audio, SR)

    reloaded = store.list()[0]
    assert reloaded.hum_path.name == LEGACY_HUM
    assert reloaded.playback_path.name == LEGACY_PLAYBACK
    assert read_audio(reloaded.hum_path)[0].size == audio.size


def test_a_run_with_both_formats_prefers_the_current_one(tmp_path: Path):
    store = SessionStore(tmp_path)
    session = save_one(store)
    write_audio(session.path / LEGACY_HUM, sample_audio(0.2), SR)

    assert store.list()[0].hum_path.name == HUM_AUDIO


def test_write_audio_picks_the_format_from_the_extension(tmp_path: Path):
    import soundfile as sf

    audio = sample_audio(0.3)
    for name, expected in (("x.flac", "FLAC"), ("x.wav", "WAV"), ("x.mp3", "MP3")):
        write_audio(tmp_path / name, audio, SR)
        assert sf.info(str(tmp_path / name)).format == expected


def test_audio_round_trip_clips_instead_of_wrapping(tmp_path: Path):
    loud = np.array([2.0, -2.0, 0.0], dtype=np.float32)
    write_audio(tmp_path / "loud.flac", loud, SR)
    restored, _ = read_audio(tmp_path / "loud.flac")
    assert restored[0] > 0.99
    assert restored[1] < -0.99


# -- damaged runs ----------------------------------------------------------


def write_manifest(root: Path, name: str, payload) -> Path:
    run = root / name
    run.mkdir(parents=True)
    (run / MANIFEST).write_text(json.dumps(payload))
    return run


def test_a_directory_without_a_manifest_is_not_a_run(tmp_path: Path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "scribble.txt").write_text("not a run")
    assert SessionStore(tmp_path).load(tmp_path / "notes") is None


def test_a_manifest_that_is_a_directory_is_not_a_run(tmp_path: Path):
    (tmp_path / "run" / MANIFEST).mkdir(parents=True)
    assert SessionStore(tmp_path).load(tmp_path / "run") is None


def test_a_truncated_manifest_is_skipped(tmp_path: Path):
    """Interrupted mid-write, the JSON stops in the middle of a note."""
    run = tmp_path / "run"
    run.mkdir()
    (run / MANIFEST).write_text('{"timestamp": "2026-08-19T14:32:05", "notes": [{"mi')
    store = SessionStore(tmp_path)

    assert store.load(run) is None
    assert store.list() == []


def test_a_run_whose_timestamp_is_nonsense_falls_back_to_the_file_time(
    tmp_path: Path,
):
    run = write_manifest(tmp_path, "run", {"timestamp": "not a date", "notes": []})
    session = SessionStore(tmp_path).load(run)

    assert session is not None
    assert session.timestamp.year >= 2020


def test_a_run_with_no_timestamp_still_loads(tmp_path: Path):
    run = write_manifest(tmp_path, "run", {"label": "no clock", "notes": []})
    session = SessionStore(tmp_path).load(run)

    assert session is not None
    assert session.label == "no clock"


def test_one_damaged_run_does_not_hide_the_healthy_ones(tmp_path: Path):
    store = SessionStore(tmp_path)
    good = save_one(store, when=datetime(2026, 8, 19, 10, 0, 0))
    broken = tmp_path / "2026-08-19_11-00-00"
    broken.mkdir()
    (broken / MANIFEST).write_text("{oh no")

    assert [s.path for s in store.list()] == [good.path]


def test_a_pitch_track_that_is_missing_reads_as_no_frames(tmp_path: Path):
    from humm2melody.sessions import read_pitch_track

    assert read_pitch_track(tmp_path / "nothing.csv") == []


def test_a_pitch_track_with_the_wrong_columns_reads_as_no_frames(tmp_path: Path):
    """Better no frames than frames invented from the wrong columns."""
    from humm2melody.sessions import read_pitch_track

    path = tmp_path / PITCH_CSV
    path.write_text("t,hz\n0.0,440.0\n")
    assert read_pitch_track(path) == []


def test_a_pitch_track_with_a_corrupt_row_reads_as_no_frames(tmp_path: Path):
    from humm2melody.sessions import read_pitch_track

    path = tmp_path / PITCH_CSV
    path.write_text("time,freq,confidence,rms\n0.0,440.0,0.9,0.1\n0.02,oops,0.9,0.1\n")
    assert read_pitch_track(path) == []


def test_a_pitch_track_with_only_a_header_reads_as_no_frames(tmp_path: Path):
    from humm2melody.sessions import read_pitch_track

    path = tmp_path / PITCH_CSV
    path.write_text("time,freq,confidence,rms\n")
    assert read_pitch_track(path) == []


def test_a_run_whose_audio_was_removed_still_lists(tmp_path: Path):
    """The manifest is the run; the audio going missing must not hide it."""
    store = SessionStore(tmp_path)
    session = save_one(store)
    (session.path / HUM_AUDIO).unlink()

    assert len(store.list()) == 1
    assert not session.hum_path.is_file()


def test_reading_a_file_that_is_not_audio_raises(tmp_path: Path):
    """The app guards this call; the guard has to have something to catch."""
    path = tmp_path / "hum.flac"
    path.write_text("not audio at all")
    with pytest.raises(Exception):
        read_audio(path)


def test_saving_into_a_path_that_is_a_file_raises_an_os_error(tmp_path: Path):
    """The app catches OSError around save; anything else would escape it."""
    blocked = tmp_path / "runs"
    blocked.write_text("in the way")
    store = SessionStore(blocked)

    with pytest.raises(OSError):
        save_one(store)


def test_updating_a_run_that_was_deleted_raises_an_os_error(tmp_path: Path):
    import shutil

    store = SessionStore(tmp_path)
    session = save_one(store)
    shutil.rmtree(session.path)

    with pytest.raises(OSError):
        store.update_notes(session, sample_notes())


def test_two_runs_renamed_to_the_same_label_both_survive(tmp_path: Path):
    store = SessionStore(tmp_path)
    first = save_one(store, when=datetime(2026, 8, 19, 10, 0, 0))
    second = save_one(store, when=datetime(2026, 8, 19, 10, 0, 0))
    store.rename(first, "Take")
    store.rename(second, "Take")

    assert first.path != second.path
    assert first.path.is_dir() and second.path.is_dir()
    assert len(store.list()) == 2


def test_a_label_that_reduces_to_nothing_leaves_no_slug_behind(tmp_path: Path):
    """"!!!" is a name on screen, but there is nothing safe to put in a path."""
    from humm2melody.sessions import LABEL_SEPARATOR

    store = SessionStore(tmp_path)
    session = save_one(store, when=datetime(2026, 8, 19, 14, 32, 5))
    store.rename(session, "!!!???")

    assert LABEL_SEPARATOR not in session.path.name
    assert session.path.is_dir()
    assert store.list()[0].display_name == "!!!???"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "_unique_dir treats the run's own directory as a collision, so "
        "renaming a run to the label it already has moves it to a '-2' "
        "suffix rather than leaving it alone"
    ),
)
def test_renaming_a_run_to_its_own_label_leaves_it_where_it_is(tmp_path: Path):
    store = SessionStore(tmp_path)
    session = save_one(store, when=datetime(2026, 8, 19, 14, 32, 5))
    store.rename(session, "Chorus")
    settled = session.path

    store.rename(session, "Chorus")
    assert session.path == settled


def test_a_run_saved_with_no_audio_reports_no_duration(tmp_path: Path):
    store = SessionStore(tmp_path)
    session = store.save(
        audio=np.zeros(0, dtype=np.float32),
        sample_rate=SR,
        frames=[],
        notes=[],
    )
    assert session.duration == 0.0
    assert store.list()[0].duration == 0.0


@pytest.mark.xfail(
    strict=True,
    reason=(
        "SessionStore.load indexes the manifest without checking it is an "
        "object, so a file holding a JSON list, string or null raises "
        "TypeError -- and it escapes list(), so one damaged run makes every "
        "saved run unreachable"
    ),
)
@pytest.mark.parametrize("payload", [[], "hello", None, 7])
def test_a_manifest_that_is_not_an_object_is_skipped(tmp_path: Path, payload):
    run = write_manifest(tmp_path, "run", payload)
    store = SessionStore(tmp_path)

    assert store.load(run) is None
    assert store.list() == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "a note entry missing a field raises KeyError out of load(), and a "
        "field of the wrong type raises ValueError; both escape list() and "
        "take the whole run sidebar with them"
    ),
)
@pytest.mark.parametrize(
    "payload",
    [
        {"timestamp": "2026-08-19T14:32:05", "notes": [{"start": 0.0}]},
        {"timestamp": "2026-08-19T14:32:05", "duration": "long", "notes": []},
        {"timestamp": "2026-08-19T14:32:05", "notes": [{"midi": None}]},
    ],
)
def test_a_partially_written_manifest_is_skipped(tmp_path: Path, payload):
    run = write_manifest(tmp_path, "run", payload)
    store = SessionStore(tmp_path)

    assert store.load(run) is None
    assert store.list() == []
