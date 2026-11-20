"""F2 (NET-320): the device details store, its limits, its file and its failure modes."""

import json
import os
import stat
import threading
from unittest import mock

import pytest

from services import device_details as dd
from services.device_custom import DeviceCustomStore, StoreUnavailable
from services.device_details import (
    DETAILS_MAX_BYTES,
    DEVICES_MAX,
    WATCH_MAX,
    DeviceDetailsStore,
    encode,
    problems,
    strict_mac,
)

MAC = "AA:BB:CC:DD:EE:FF"


def mac_n(i: int) -> str:
    return ":".join(
        f"{b:02X}" for b in (0x02, 0, 0, (i >> 16) & 255, (i >> 8) & 255, i & 255)
    )


@pytest.fixture
def root(tmp_path):
    return str(tmp_path / "data")


@pytest.fixture
def store(root):
    return DeviceDetailsStore(root)


def path_of(root):
    return os.path.join(root, "device_details.json")


# ---------------------------------------------------------------------------
# Fields and limits
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "limit"), [("group", 32), ("owner", 64), ("notes", 1000)]
)
def test_text_limits_at_the_boundary(store, key, limit):
    assert store.update(MAC, {key: "x" * limit})[key] == "x" * limit
    with pytest.raises(ValueError, match=f"at most {limit:,} characters"):
        store.update(MAC, {key: "y" * (limit + 1)})
    assert store.get(MAC)[key] == "x" * limit


@pytest.mark.parametrize("minutes", [15, 30, 60, 240, 1440])
def test_each_watch_choice_is_allowed(store, minutes):
    assert store.update(MAC, {"watch_after_min": minutes})["watch_after_min"] == minutes


@pytest.mark.parametrize("bad", [0, 45, True, False, "30", 30.0, -15])
def test_other_watch_values_are_refused(store, bad):
    with pytest.raises(ValueError, match="Pick 15, 30, 60, 240 or 1440"):
        store.update(MAC, {"watch_after_min": bad})


@pytest.mark.parametrize(
    "bad",
    [
        "\n",
        "a\nb",
        "a\rb",
        "\x00",
        "tab\there",
        "‮evil",  # bidi override (Cf)
        "​zero width",  # Cf
        "line sep",  # Zl
        "para sep",  # Zp
        "lone \ud800 surrogate",  # Cs
    ],
)
@pytest.mark.parametrize("key", ["group", "owner", "notes"])
def test_controls_and_separators_are_refused_before_trimming(store, key, bad):
    store.update(MAC, {key: "kept"})
    with pytest.raises(ValueError, match="line breaks, control or formatting"):
        store.update(MAC, {key: bad})
    # "\n" alone is refused, never read as "clear"
    assert store.get(MAC)[key] == "kept"


def test_text_is_nfc_normalised_and_trimmed(store):
    got = store.update(MAC, {"owner": "  Café  "})
    assert got["owner"] == "Café"


def test_a_four_byte_character_is_allowed_and_costs_four_bytes(store, root):
    store.update(MAC, {"notes": "\U0001f600"})
    with open(path_of(root), "rb") as fh:
        raw = fh.read()
    assert "\U0001f600".encode() in raw
    assert len(raw) == len(encode({MAC: {"notes": "\U0001f600"}}))


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_empty_or_null_clears_and_the_last_field_removes_the_entry(store, empty):
    store.update(MAC, {"group": "Kids", "owner": "Sam"})
    assert store.update(MAC, {"group": empty})["group"] is None
    assert store.update(MAC, {"owner": empty}) == dd.EMPTY
    assert store.export() == {}


@pytest.mark.parametrize(
    "bad", [{}, {"name": "x"}, {"group": "a", "extra": 1}, [], "x", None]
)
def test_empty_or_unknown_bodies_are_refused(store, bad):
    with pytest.raises(ValueError):
        store.update(MAC, bad)
    assert store.export() == {}


def test_a_bad_field_changes_nothing(store):
    store.update(MAC, {"group": "Kids"})
    with pytest.raises(ValueError):
        store.update(MAC, {"group": "Adults", "watch_after_min": 7})
    assert store.get(MAC)["group"] == "Kids"


def test_a_no_op_writes_nothing(store, root):
    store.update(MAC, {"group": "Kids"})
    before = os.stat(path_of(root)).st_mtime_ns
    with mock.patch.object(dd, "write_file_atomic") as write:
        store.update(MAC, {"group": " Kids "})
        store.update(MAC, {"owner": None})
        store.clear("02:00:00:00:00:01")
    write.assert_not_called()
    assert os.stat(path_of(root)).st_mtime_ns == before


def test_devices_max(store):
    store._devices = {mac_n(i): {"group": "g"} for i in range(DEVICES_MAX)}
    with pytest.raises(ValueError, match="limited to 2,000 devices"):
        store.update(MAC, {"group": "g"})
    # an existing device can still change
    assert store.update(mac_n(0), {"group": "h"})["group"] == "h"


def test_the_watch_budget(store):
    for i in range(WATCH_MAX):
        store.update(mac_n(i), {"watch_after_min": 30})
    with pytest.raises(ValueError, match=f"At most {WATCH_MAX} devices can be watched"):
        store.update(MAC, {"watch_after_min": 30})
    # changing an existing watch, and a group-only device, are fine at 50
    assert store.update(mac_n(0), {"watch_after_min": 60})["watch_after_min"] == 60
    assert store.update(MAC, {"group": "Kids"})["group"] == "Kids"


def _filled_to(target: int) -> tuple[dict, str]:
    """(devices, last MAC): an encoded file of exactly `target` bytes, the last device's notes as filler."""
    # 900-character notes keep each device under ~950 bytes, so the filler always fits in 1..997
    devices = {mac_n(i): {"notes": "x" * 900} for i in range(DEVICES_MAX - 1)}
    last = mac_n(DEVICES_MAX)

    def overhead() -> int:
        return len(encode({**devices, last: {"notes": ""}})) - len(encode(devices))

    while len(encode(devices)) + overhead() + 1 > target:
        devices.pop(next(iter(devices)))
    devices[last] = {"notes": "a" * (target - len(encode(devices)) - overhead())}
    assert len(encode(devices)) == target
    assert len(devices[last]["notes"]) <= 997
    return devices, last


def test_the_byte_budget_at_its_boundary_on_update_and_restore(store, root):
    devices, last = _filled_to(DETAILS_MAX_BYTES - 1)
    store.restore(devices)
    notes = devices[last]["notes"]
    # one more byte fits exactly; the next is refused
    store.update(last, {"notes": notes + "a"})
    assert os.path.getsize(path_of(root)) == DETAILS_MAX_BYTES
    with pytest.raises(ValueError, match="Device details are full"):
        store.update(last, {"notes": notes + "aa"})
    # a boundary-size file reopens healthy and exports
    again = DeviceDetailsStore(root)
    assert again.healthy
    assert len(again.export()) == len(devices)
    over = {**devices, last: {"notes": notes + "aa"}}
    assert any("full" in r for r in problems(over))
    with pytest.raises(ValueError, match="full"):
        DeviceDetailsStore(str(root) + "-2").restore(over)


# ---------------------------------------------------------------------------
# MACs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw", ["aa:bb:cc:dd:ee:ff", "AA-BB-CC-DD-EE-FF", "aA:Bb:cC:dD:eE:fF"]
)
def test_strict_mac_accepts_six_pairs(raw):
    assert strict_mac(raw) == MAC


@pytest.mark.parametrize(
    "raw",
    [
        "AA:BB:CC:DD:EE:FF:00",
        "AA:BB:CC:DD:EE:FF:",
        "AA:BB:CC:DD:EE:FF:ZZ",
        "AA:BB-CC:DD:EE:FF",
        "AABBCCDDEEFF",
        "AA:BB:CC:DD:EE:FF\n",
        " AA:BB:CC:DD:EE:FF",
        "AA:BB:CC:DD:EE",
        None,
        12,
    ],
)
def test_strict_mac_refuses_everything_else_and_never_touches_the_device(store, raw):
    store.update(MAC, {"group": "Kids"})
    with pytest.raises(ValueError, match="Not a valid MAC"):
        strict_mac(raw)
    with pytest.raises(ValueError):
        store.clear(raw)
    with pytest.raises(ValueError):
        store.update(raw, {"group": "x"})
    assert store.get(MAC)["group"] == "Kids"
    assert store.get(raw) == dd.EMPTY


@pytest.mark.parametrize(
    "key", ["aa:bb:cc:dd:ee:ff", "AA-BB-CC-DD-EE-FF", "AA:BB:CC:DD:EE:FF:00", 7]
)
def test_backup_keys_must_be_canonical(key):
    assert problems({key: {"group": "Kids"}})
    # two spellings of one device can never collapse onto it
    assert problems({MAC: {"group": "a"}, "aa:bb:cc:dd:ee:ff": {"group": "b"}})


# ---------------------------------------------------------------------------
# The file
# ---------------------------------------------------------------------------


def test_first_update_creates_the_directory_and_reopens(root):
    assert not os.path.exists(root)
    DeviceDetailsStore(root).update(MAC, {"notes": "first"})
    assert DeviceDetailsStore(root).get(MAC)["notes"] == "first"


def test_first_restore_creates_the_directory_and_reopens(root):
    DeviceDetailsStore(root).restore({MAC: {"group": "Kids"}})
    assert DeviceDetailsStore(root).get(MAC)["group"] == "Kids"


def test_the_file_is_mode_0600_after_update_and_restore(store, root):
    store.update(MAC, {"owner": "Sam"})
    assert stat.S_IMODE(os.stat(path_of(root)).st_mode) == 0o600
    os.chmod(path_of(root), 0o644)
    store.restore({MAC: {"owner": "Alex"}})
    assert stat.S_IMODE(os.stat(path_of(root)).st_mode) == 0o600


def test_a_write_failure_leaves_memory_and_file_as_they_were(store, root):
    store.update(MAC, {"group": "Kids"})
    with open(path_of(root), "rb") as fh:
        before = fh.read()
    with mock.patch.object(dd, "write_file_atomic", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            store.update(MAC, {"group": "Adults"})
    assert store.get(MAC)["group"] == "Kids"
    with open(path_of(root), "rb") as fh:
        assert fh.read() == before


def test_concurrent_updates_keep_both_fields(store):
    def put(key, value):
        for _ in range(50):
            store.update(MAC, {key: value})

    threads = [
        threading.Thread(target=put, args=("group", "Kids")),
        threading.Thread(target=put, args=("owner", "Sam")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert DeviceDetailsStore(store._root).get(MAC) == {
        **dd.EMPTY,
        "group": "Kids",
        "owner": "Sam",
    }


# ---------------------------------------------------------------------------
# A damaged file
# ---------------------------------------------------------------------------


def _write(root, text_or_bytes):
    os.makedirs(root, exist_ok=True)
    mode = "wb" if isinstance(text_or_bytes, bytes) else "w"
    with open(path_of(root), mode) as fh:
        fh.write(text_or_bytes)


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        b"\xff\xfe not utf-8",
        json.dumps({"version": 2, "devices": {}}),
        json.dumps({"version": 1, "devices": {MAC: {"group": " padded "}}}),
        json.dumps({"version": 1, "devices": {MAC: {}}}),
        json.dumps({"version": 1, "devices": {"aa:bb:cc:dd:ee:ff": {"group": "x"}}}),
        json.dumps({"version": 1, "devices": {MAC: {"watch_after_min": True}}}),
        "[" * 100_000 + "]" * 100_000,  # RecursionError
    ],
)
def test_a_damaged_file_latches_the_store_off(root, content, caplog):
    _write(root, content)
    store = DeviceDetailsStore(root)
    assert not store.healthy
    assert "Device details file is unreadable" in caplog.text
    assert store.get(MAC) == dd.EMPTY
    assert store.row_fields(MAC) == {
        "watch_after_min": None,
        "group": None,
        "owner": None,
    }
    with pytest.raises(StoreUnavailable):
        store.update(MAC, {"group": "x"})
    with pytest.raises(StoreUnavailable):
        store.clear(MAC)
    with pytest.raises(StoreUnavailable):
        store.export()
    with pytest.raises(StoreUnavailable):
        store.restore({})


def test_an_over_long_file_is_damaged_not_empty(root):
    _write(root, b" " * (DETAILS_MAX_BYTES + 1))
    assert not DeviceDetailsStore(root).healthy


def test_a_directory_in_place_of_the_file_is_damaged(root):
    os.makedirs(path_of(root))
    assert not DeviceDetailsStore(root).healthy


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_an_unreadable_file_is_damaged(root):
    _write(root, encode({}))
    os.chmod(path_of(root), 0)
    try:
        assert not DeviceDetailsStore(root).healthy
    finally:
        os.chmod(path_of(root), 0o600)


def test_a_missing_file_is_an_empty_healthy_store(store):
    assert store.healthy
    assert store.export() == {}


# ---------------------------------------------------------------------------
# Next to the names store (rollback safety)
# ---------------------------------------------------------------------------


def test_names_load_and_serve_beside_a_details_file(root):
    DeviceDetailsStore(root).update(MAC, {"group": "Kids"})
    custom = DeviceCustomStore(root)
    custom.set_name(MAC, "Sam's phone")
    again = DeviceCustomStore(root)
    assert again.healthy
    assert again.name_for(MAC) == "Sam's phone"
    assert os.path.exists(path_of(root))


def test_names_serve_on_a_cold_start_beside_a_damaged_details_file(root):
    DeviceCustomStore(root).set_name(MAC, "Sam's phone")
    _write(root, "{damaged")
    details = DeviceDetailsStore(root)
    custom = DeviceCustomStore(root)
    assert not details.healthy
    assert custom.healthy
    assert custom.name_for(MAC) == "Sam's phone"


# ---------------------------------------------------------------------------
# Backup functions
# ---------------------------------------------------------------------------


def test_export_and_restore_round_trip(store, tmp_path):
    store.update(
        MAC, {"group": "Kids", "watch_after_min": 30, "notes": "café \U0001f600"}
    )
    other = DeviceDetailsStore(str(tmp_path / "other"))
    other.update("02:00:00:00:00:01", {"owner": "gone after restore"})
    other.restore(store.export())
    assert other.export() == store.export()


def test_problems_stops_at_five_reasons():
    bad = {mac_n(i): {"group": "\n"} for i in range(20)}
    assert len(problems(bad)) == 5


@pytest.mark.parametrize("bad", [[], "x", None, 5])
def test_problems_needs_an_object(bad):
    assert problems(bad) == ["Device details must be an object keyed by MAC address."]


def test_restore_refuses_a_bad_section_and_writes_nothing(store):
    store.update(MAC, {"group": "Kids"})
    with pytest.raises(ValueError):
        store.restore({MAC: {"group": "x" * 33}})
    with pytest.raises(ValueError, match="watched"):
        store.restore({mac_n(i): {"watch_after_min": 30} for i in range(WATCH_MAX + 1)})
    assert store.get(MAC)["group"] == "Kids"
