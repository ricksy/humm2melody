"""Profile store tests."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from humm2melody.profiles import (
    GUEST_NAME,
    Calibration,
    Profile,
    ProfileStore,
    guest,
)


def test_guest_is_not_persisted(tmp_path: Path):
    store = ProfileStore(tmp_path)
    person = guest()
    assert person.is_guest is True
    store.save(person)
    assert list(tmp_path.glob("*.json")) == []


def test_guest_summary_says_nothing_is_saved():
    assert "nothing is saved" in guest().summary


def test_create_writes_a_file(tmp_path: Path):
    store = ProfileStore(tmp_path)
    profile = store.create("Ahmed")
    assert profile.path.is_file()
    assert profile.is_guest is False


def test_create_makes_the_directory(tmp_path: Path):
    store = ProfileStore(tmp_path / "nested" / "profiles")
    assert store.create("Ahmed").path.is_file()


def test_created_profile_has_default_dials(tmp_path: Path):
    profile = ProfileStore(tmp_path).create("Ahmed")
    assert (profile.pitch_sensitivity, profile.pause_sensitivity, profile.mix) == (
        5,
        5,
        5,
    )


def test_names_with_spaces_and_punctuation_are_usable(tmp_path: Path):
    store = ProfileStore(tmp_path)
    profile = store.create("Ahmed's Voice!")
    assert profile.path.is_file()
    assert store.list()[0].name == "Ahmed's Voice!"  # display name is preserved


def test_duplicate_names_are_rejected(tmp_path: Path):
    store = ProfileStore(tmp_path)
    store.create("Ahmed")
    with pytest.raises(ValueError):
        store.create("Ahmed")


def test_blank_names_are_rejected(tmp_path: Path):
    store = ProfileStore(tmp_path)
    for bad in ("", "   ", "\t"):
        with pytest.raises(ValueError):
            store.create(bad)


def test_guest_name_is_reserved(tmp_path: Path):
    store = ProfileStore(tmp_path)
    with pytest.raises(ValueError):
        store.create(GUEST_NAME)
    with pytest.raises(ValueError):
        store.create("guest")


def test_dials_survive_a_reload(tmp_path: Path):
    store = ProfileStore(tmp_path)
    profile = store.create("Ahmed")
    profile.pitch_sensitivity = 8
    profile.pause_sensitivity = 7
    profile.mix = 3
    store.save(profile)

    reloaded = store.list()[0]
    assert (
        reloaded.pitch_sensitivity,
        reloaded.pause_sensitivity,
        reloaded.mix,
    ) == (8, 7, 3)


def test_calibration_survives_a_reload(tmp_path: Path):
    store = ProfileStore(tmp_path)
    profile = store.create("Ahmed")
    profile.calibration = Calibration(
        range_low_midi=45, range_high_midi=64, tuning_offset_cents=12.0
    )
    store.save(profile)

    reloaded = store.list()[0]
    assert reloaded.calibration.range_low_midi == 45
    assert reloaded.calibration.range_high_midi == 64
    assert reloaded.calibration.tuning_offset_cents == pytest.approx(12.0)


def test_a_new_profile_is_not_calibrated(tmp_path: Path):
    profile = ProfileStore(tmp_path).create("Ahmed")
    assert profile.calibration.is_empty is True
    assert "not calibrated" in profile.summary


def test_a_calibrated_profile_says_so(tmp_path: Path):
    store = ProfileStore(tmp_path)
    profile = store.create("Ahmed")
    profile.calibration = Calibration(range_low_midi=45)
    assert profile.calibration.is_empty is False
    assert "calibrated" in profile.summary


def test_list_is_alphabetical_and_case_insensitive(tmp_path: Path):
    store = ProfileStore(tmp_path)
    for name in ("zoe", "Ahmed", "mia"):
        store.create(name)
    assert [p.name for p in store.list()] == ["Ahmed", "mia", "zoe"]


def test_list_of_a_missing_directory_is_empty(tmp_path: Path):
    assert ProfileStore(tmp_path / "nope").list() == []


def test_corrupt_profile_is_skipped_not_fatal(tmp_path: Path):
    store = ProfileStore(tmp_path)
    store.create("Ahmed")
    (tmp_path / "broken.json").write_text("{not json")
    (tmp_path / "empty.json").write_text("{}")

    assert [p.name for p in store.list()] == ["Ahmed"]


def test_unknown_calibration_fields_are_ignored(tmp_path: Path):
    """A profile written by a newer version must not crash an older one."""
    store = ProfileStore(tmp_path)
    profile = store.create("Ahmed")
    data = json.loads(profile.path.read_text())
    data["calibration"]["something_new"] = 42
    profile.path.write_text(json.dumps(data))

    assert store.list()[0].name == "Ahmed"


def test_delete_removes_the_file(tmp_path: Path):
    store = ProfileStore(tmp_path)
    profile = store.create("Ahmed")
    store.delete(profile)
    assert not profile.path.exists()
    assert store.list() == []


def test_delete_leaves_other_profiles_alone(tmp_path: Path):
    store = ProfileStore(tmp_path)
    first = store.create("Ahmed")
    store.create("Mia")
    store.delete(first)
    assert [p.name for p in store.list()] == ["Mia"]


def test_deleting_guest_is_refused(tmp_path: Path):
    with pytest.raises(ValueError):
        ProfileStore(tmp_path).delete(guest())


def test_delete_refuses_a_file_outside_the_store(tmp_path: Path):
    store = ProfileStore(tmp_path / "mine")
    store.root.mkdir(parents=True)
    outsider = tmp_path / "precious.json"
    outsider.write_text('{"name": "elsewhere"}')

    with pytest.raises(ValueError):
        store.delete(Profile(name="elsewhere", path=outsider))
    assert outsider.exists()


def test_deleting_a_profile_does_not_touch_recordings(tmp_path: Path):
    """Profiles and recordings are independent; losing one must not lose the other."""
    store = ProfileStore(tmp_path / "profiles")
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    (recordings / "keep.txt").write_text("a run")

    store.delete(store.create("Ahmed"))
    assert (recordings / "keep.txt").exists()
