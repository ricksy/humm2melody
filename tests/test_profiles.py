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


# -- profiles the app did not write ----------------------------------------


def write_profile(root: Path, name: str, payload) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.json"
    path.write_text(json.dumps(payload))
    return path


def test_a_profile_from_a_future_version_still_loads(tmp_path: Path):
    """Settings this version does not know about must not lose the ones it does."""
    path = write_profile(
        tmp_path,
        "ahmed",
        {
            "version": 99,
            "name": "Ahmed",
            "created": "2026-08-19T10:00:00",
            "dials": {"pitch": 7, "pause": 3, "mix": 2, "tempo": 8, "swing": 4},
            "voice": "chord",
            "notation": "sargam",
            "theme": "midnight",
            "calibration": {"range_low_midi": 48, "vibrato_hz": 5.5},
        },
    )
    profile = ProfileStore(tmp_path).load(path)

    assert profile is not None
    assert profile.name == "Ahmed"
    assert profile.pitch_sensitivity == 7
    assert profile.tempo == 8
    assert profile.voice == "chord"
    assert profile.notation == "sargam"
    assert profile.calibration.range_low_midi == 48


def test_a_future_profile_is_not_rewritten_just_by_being_read(tmp_path: Path):
    """Reading someone's profile must not quietly drop what it did not parse."""
    path = write_profile(
        tmp_path, "ahmed", {"version": 99, "name": "Ahmed", "theme": "midnight"}
    )
    before = path.read_text()
    ProfileStore(tmp_path).list()

    assert path.read_text() == before


def test_a_profile_that_is_a_json_list_is_skipped(tmp_path: Path):
    write_profile(tmp_path, "odd", ["not", "a", "profile"])
    assert ProfileStore(tmp_path).list() == []


def test_a_profile_with_no_name_is_skipped(tmp_path: Path):
    write_profile(tmp_path, "nameless", {"dials": {"pitch": 3}})
    assert ProfileStore(tmp_path).list() == []


def test_a_profile_with_an_empty_name_is_skipped(tmp_path: Path):
    write_profile(tmp_path, "blank", {"name": ""})
    assert ProfileStore(tmp_path).list() == []


def test_a_profile_with_no_created_date_falls_back_to_the_file(tmp_path: Path):
    path = write_profile(tmp_path, "ahmed", {"name": "Ahmed"})
    profile = ProfileStore(tmp_path).load(path)

    assert profile is not None
    assert profile.created.year >= 2020


def test_a_profile_with_an_unreadable_created_date_still_loads(tmp_path: Path):
    path = write_profile(tmp_path, "ahmed", {"name": "Ahmed", "created": "never"})
    assert ProfileStore(tmp_path).load(path) is not None


def test_a_profile_naming_a_tab_that_no_longer_exists_still_loads(tmp_path: Path):
    path = write_profile(
        tmp_path, "ahmed", {"name": "Ahmed", "last_tab": "tab-that-went-away"}
    )
    profile = ProfileStore(tmp_path).load(path)

    assert profile is not None
    assert profile.last_tab == "tab-that-went-away"  # the app decides what to do


def test_a_profile_with_a_null_voice_falls_back_to_pure(tmp_path: Path):
    path = write_profile(tmp_path, "ahmed", {"name": "Ahmed", "voice": None})
    assert ProfileStore(tmp_path).load(path).voice == "pure"


def test_one_unreadable_profile_does_not_hide_the_others(tmp_path: Path):
    store = ProfileStore(tmp_path)
    store.create("Ahmed")
    (tmp_path / "broken.json").write_text("{ not json")

    assert [p.name for p in store.list()] == ["Ahmed"]


def test_a_profile_store_pointed_at_a_file_lists_nothing(tmp_path: Path):
    blocked = tmp_path / "profiles"
    blocked.write_text("in the way")
    assert ProfileStore(blocked).list() == []


def test_saving_into_a_path_that_is_a_file_raises_an_os_error(tmp_path: Path):
    """The app catches OSError when remembering dials; nothing else."""
    blocked = tmp_path / "profiles"
    blocked.write_text("in the way")
    store = ProfileStore(blocked)

    with pytest.raises(OSError):
        store.create("Ahmed")


def test_deleting_a_profile_whose_file_is_already_gone_is_quiet(tmp_path: Path):
    store = ProfileStore(tmp_path)
    profile = store.create("Ahmed")
    profile.path.unlink()

    store.delete(profile)  # must not raise
    assert store.list() == []


def test_two_names_that_slug_the_same_way_are_rejected_as_duplicates(tmp_path: Path):
    """One file per profile means the slug has to be the identity."""
    store = ProfileStore(tmp_path)
    store.create("Ahmed S")

    with pytest.raises(ValueError):
        store.create("Ahmed_S")  # spaces and underscores both become "-"


def test_a_name_with_nothing_safe_in_it_still_gets_a_file(tmp_path: Path):
    store = ProfileStore(tmp_path)
    profile = store.create("!!!")

    assert profile.path.is_file()
    assert [p.name for p in store.list()] == ["!!!"]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "ProfileStore.load calls int() on the stored dials without guarding, "
        "so a hand-edited profile with a non-numeric dial raises ValueError "
        "out of list() -- and the chooser cannot open at all"
    ),
)
@pytest.mark.parametrize("dial", ["high", None, [5]])
def test_a_profile_with_a_nonsense_dial_is_skipped(tmp_path: Path, dial):
    store = ProfileStore(tmp_path)
    store.create("Ahmed")
    write_profile(tmp_path, "broken", {"name": "Broken", "dials": {"pitch": dial}})

    assert [p.name for p in store.list()] == ["Ahmed"]
