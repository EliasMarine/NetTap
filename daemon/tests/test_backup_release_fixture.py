"""F2 x NET-344 release fixture: a full box still downloads a backup that restores (F2 plan,
"Rebase requirements"; NET-344 plan §5).

32 full-size pictures, 46,000 acknowledgements with mixed offsets (as the NET-344 verifier
builds them) and 480 devices with 1,000-character notes. The plan sized 46,000 against the old
pretty-printed download; as exact bytes it fits whole, so 70,000 (the verifier's count) runs too,
to make the trim happen. The expected left-out count comes from encoding candidate files, never
from fit's arithmetic, and the newest set from a sort of its own. Slow (seconds): it builds and
encodes about 16 MB several times.
"""

import base64
import json
import random
from datetime import datetime, timedelta, timezone

import pytest

from services import config_backup
from services.config_backup import LEFT_OUT, RESTORE_LIMIT_BYTES, ConfigBackup
from services.device_custom import PHOTO_MAX_BYTES, PHOTOS_MAX_TOTAL, DeviceCustomStore
from services.device_details import DeviceDetailsStore
from services.notification_hub import NotificationHub

ACKS = "alert_acknowledgements"
PICTURES = PHOTOS_MAX_TOTAL // PHOTO_MAX_BYTES  # 32 full-size pictures fill the store
ODD = 40  # missing, unparsable, zone-less or non-string times: all count as oldest
NOTED = 480
# equal instants written with different offsets, so string order isn't time order
OFFSETS = [timezone(timedelta(minutes=m)) for m in (0, 0, 330, -480, 60)]
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
ID_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def _mac(i: int) -> str:
    return f"02:00:00:00:{i // 256:02X}:{i % 256:02X}"


def _box(root) -> tuple[ConfigBackup, DeviceCustomStore, DeviceDetailsStore, dict]:
    root.mkdir()
    paths = {k: str(root / f"{k}.json") for k in config_backup._DEFAULT_PATHS}
    (root / "notification_config.json").write_text('{"channels": {}, "rules": {}}')
    (root / "env_file.json").write_text("")
    hub = NotificationHub(
        config_path=paths["notification_config"], env_file=paths["env_file"]
    )
    custom, details = DeviceCustomStore(str(root)), DeviceDetailsStore(str(root))
    backup = ConfigBackup(paths, custom, hub, details)
    return backup, custom, details, paths


def _stamp(i: int, count: int):
    """Groups of three share an instant, each written with its own offset; ODD ones last."""
    if i >= count - ODD:
        return ("2026-12-31T23:59:59", "not a time", None, 1_700_000_000)[i % 4]
    instant = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(
        seconds=7 * (i // 3), microseconds=(i // 3) % 4 * 125_000
    )
    text = instant.astimezone(OFFSETS[i % len(OFFSETS)]).isoformat()
    return text.replace("+00:00", "Z") if i % 5 == 0 else text


def _acks(rng: random.Random, count: int) -> dict:
    entries = []
    for i in range(count):
        entry = {"acknowledged_by": "Élodie 🛡" if i % 7 == 0 else "admin"}
        if _stamp(i, count) is not None:
            entry["acknowledged_at"] = _stamp(i, count)
        entries.append(("".join(rng.choices(ID_CHARS, k=20)), entry))
    rng.shuffle(entries)  # the file's order is no help to the fitter
    acks = dict(entries)
    assert len(acks) == count, "two IDs collided; change the seed"
    return acks


def _fill(custom, details, paths, rng: random.Random, count: int) -> dict:
    for i in range(PICTURES):
        png = b"\x89PNG\r\n\x1a\n" + rng.randbytes(PHOTO_MAX_BYTES - 8)
        custom.set_photo(
            _mac(i), "data:image/png;base64," + base64.b64encode(png).decode()
        )
        custom.set_name(_mac(i), f"Café screen {i} 📺")
    for i in range(NOTED):
        note = f"Note {i} 📝 " + "".join(rng.choices(ID_CHARS + " ", k=1000))
        details.update(
            _mac(i), {"group": "Living room", "owner": "Sam", "notes": note[:1000]}
        )
    acks = _acks(rng, count)
    with open(paths["alert_acks"], "w", encoding="utf-8") as fh:
        json.dump(acks, fh, ensure_ascii=False)
    return acks


def _newest_first(item: tuple[str, dict]) -> tuple:
    """Newest UTC instant first; no usable zoned time counts as oldest; ties by ID ascending."""
    alert_id, entry = item
    try:
        when = datetime.fromisoformat(entry["acknowledged_at"])
    except (KeyError, TypeError, ValueError):
        when = None
    if when is None or when.tzinfo is None:
        return (1, 0, alert_id)
    return (0, -((when - EPOCH) // timedelta(microseconds=1)), alert_id)


def _size(data: dict, newest: list[str], acks: dict, kept: int) -> int:
    """The file with the `kept` newest acknowledgements, encoded as JSON itself encodes it."""
    meta = {k: v for k, v in data["metadata"].items() if k != LEFT_OUT}
    if kept < len(newest):
        meta[LEFT_OUT] = len(newest) - kept
    doc = {
        **data,
        "metadata": meta,
        "sections": {**data["sections"], ACKS: {k: acks[k] for k in newest[:kept]}},
    }
    return len(json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode())


def _expected_kept(data: dict, newest: list[str], acks: dict) -> int:
    """The most acknowledgements a file under the limit holds (sizes grow with each one kept)."""
    if _size(data, newest, acks, len(newest)) < RESTORE_LIMIT_BYTES:
        return len(newest)
    low, high = 0, len(newest) - 1  # low fits (asserted below), high + 1 doesn't
    assert _size(data, newest, acks, 0) < RESTORE_LIMIT_BYTES
    while low < high:
        mid = (low + high + 1) // 2
        if _size(data, newest, acks, mid) < RESTORE_LIMIT_BYTES:
            low = mid
        else:
            high = mid - 1
    return low


@pytest.mark.parametrize("count,trims", [(46_000, False), (70_000, True)])
def test_a_full_box_downloads_a_backup_that_restores(tmp_path, count, trims):
    rng = random.Random(320)
    backup, custom, details, paths = _box(tmp_path / "before")
    acks = _fill(custom, details, paths, rng, count)

    body, left_out = backup.export_file()

    # what the export answers with a 200: bytes under the limit
    assert isinstance(body, bytearray) and len(body) < RESTORE_LIMIT_BYTES
    data = json.loads(body)
    newest = [k for k, _ in sorted(acks.items(), key=_newest_first)]
    kept = _expected_kept(data, newest, acks)
    assert left_out == len(acks) - kept
    assert (left_out > 0) == trims
    assert data["metadata"].get(LEFT_OUT, 0) == left_out
    assert set(data["sections"][ACKS]) == set(newest[:kept])
    print(
        f"release fixture: {len(body):,} bytes, {left_out:,} of {len(acks):,} "
        f"acknowledgements left out"
    )

    dest, dest_custom, dest_details, dest_paths = _box(tmp_path / "after")
    validation = dest.validate_import(data)
    assert validation["is_valid"], validation["errors"]
    result = dest.import_config(data, validation)
    assert result["success"] and not result["errors"], result
    assert {"device_aliases", "device_pictures", "device_details", ACKS} <= set(
        result["applied"]
    )
    assert DeviceCustomStore(str(tmp_path / "after")).export() == custom.export()
    assert DeviceDetailsStore(str(tmp_path / "after")).export() == details.export()
    with open(dest_paths["alert_acks"], encoding="utf-8") as fh:
        assert json.load(fh) == data["sections"][ACKS]
