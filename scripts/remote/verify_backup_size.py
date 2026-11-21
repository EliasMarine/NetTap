"""NET-344 deploy check: a backup over the restore limit is trimmed, and restores, end to end.

Runs inside a throwaway copy of the just-built daemon image (deploy-backup-size.sh):
    docker run --rm -i --network none --entrypoint python3 <image id> - < verify_backup_size.py
No mounts and no network, so nothing live is read or touched: every path is in a fresh temp
directory. The box before: 32 full-size device pictures (the picture store's limit) with names,
set through the real DeviceCustomStore, and enough alert acknowledgements to push the backup
past the restore limit. The export path GET /api/backup/export runs (export_file: export_config,
fit and the export-time preflight) gives the exact bytes the owner would save; the preflight and import_config restore them into a second set of temp paths,
which must then hold the names, the pictures and exactly the newest acknowledgements, worked
out here without the daemon's code (plan §2.3 step 3). Prints BACKUP-SIZE-OK only after the
last check. Locally, from daemon/:
    PYTHONPATH=. python ../scripts/remote/verify_backup_size.py
"""

import base64
import json
import os
import random
import shutil
import sys
import tempfile
import time
import tracemalloc
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/opt/nettap/daemon")

TMP = tempfile.mkdtemp(prefix="backup-size-")
os.environ["OWNER_TZ_FILE"] = os.path.join(TMP, "owner-timezone.json")

from services import config_backup  # noqa: E402
from services.config_backup import RESTORE_LIMIT_BYTES, ConfigBackup  # noqa: E402
from services.device_custom import (  # noqa: E402
    PHOTO_MAX_BYTES,
    PHOTOS_MAX_TOTAL,
    DeviceCustomStore,
)
from services.notification_hub import NotificationHub  # noqa: E402

PICTURES = PHOTOS_MAX_TOTAL // PHOTO_MAX_BYTES  # 32 full-size pictures fill the store
ACKS = 70_000  # about 7 MB with the pictures' 11 MB: well past the limit
ODD = 100  # missing, unparsable, zone-less or non-string times: all count as oldest
# Ties share an instant written with different offsets, so string order isn't time order
OFFSETS = [timezone(timedelta(minutes=m)) for m in (0, 0, 330, -480, 60)]
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
RNG = random.Random(344)
ID_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def fail(why: str) -> None:
    print("FAIL", why)
    sys.exit(1)


def mac(i: int) -> str:
    return f"02:00:00:00:{i // 256:02X}:{i % 256:02X}"


def vm_rss() -> str:
    try:
        with open("/proc/self/status") as fh:
            return next(
                " ".join(ln.split()[1:]) for ln in fh if ln.startswith("VmRSS:")
            )
    except (OSError, StopIteration):
        return "n/a (no /proc)"


def box(name: str) -> tuple[str, dict[str, str]]:
    """A data directory and every ConfigBackup path inside it."""
    root = os.path.join(TMP, name)
    os.makedirs(root)
    return root, {
        k: os.path.join(root, k + ".json") for k in config_backup._DEFAULT_PATHS
    }


def stamp(i: int) -> object:
    """acknowledged_at for entry i: groups of three share an instant, each with its own offset."""
    if i >= ACKS:
        return ("2026-12-31T23:59:59", "not a time", None, 1_700_000_000)[i % 4]
    instant = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(
        seconds=7 * (i // 3), microseconds=(i // 3) % 4 * 125_000
    )
    text = instant.astimezone(OFFSETS[i % len(OFFSETS)]).isoformat()
    return text.replace("+00:00", "Z") if i % 5 == 0 else text


def make_acks() -> dict[str, dict]:
    entries = []
    for i in range(ACKS + ODD):
        alert_id = "".join(RNG.choices(ID_CHARS, k=20))
        entry = {"acknowledged_by": "Élodie 🛡" if i % 7 == 0 else "admin"}
        if stamp(i) is not None:
            entry["acknowledged_at"] = stamp(i)
        entries.append((alert_id, entry))
    RNG.shuffle(entries)  # the file's order is no help to the fitter
    acks = dict(entries)
    if len(acks) != ACKS + ODD:
        fail("two acknowledgement IDs collided; change the seed")
    return acks


def newest_first(item: tuple[str, dict]) -> tuple:
    """Newest UTC instant first; a missing, unparsable or zone-less time counts as oldest;
    equal instants by alert ID ascending (plan §2.3 step 3). Never compares time strings."""
    alert_id, entry = item
    try:
        when = datetime.fromisoformat(entry["acknowledged_at"])
    except (KeyError, TypeError, ValueError):
        when = None
    if when is None or when.tzinfo is None:
        return (1, 0, alert_id)
    return (0, -((when - EPOCH) // timedelta(microseconds=1)), alert_id)


def build_before(root: str, paths: dict[str, str]) -> tuple[DeviceCustomStore, dict]:
    store = DeviceCustomStore(root=root)
    for i in range(PICTURES):
        data = b"\x89PNG\r\n\x1a\n" + RNG.randbytes(PHOTO_MAX_BYTES - 8)
        store.set_photo(
            mac(i), "data:image/png;base64," + base64.b64encode(data).decode()
        )
        store.set_name(mac(i), f"Café screen {i} 📺")
    acks = make_acks()
    with open(paths["alert_acks"], "w", encoding="utf-8") as fh:
        json.dump(acks, fh, ensure_ascii=False)
    print(
        f"   before: {PICTURES} pictures of {PHOTO_MAX_BYTES:,} bytes, {PICTURES} names, "
        f"{len(acks):,} acknowledgements"
    )
    return store, acks


def export(store: DeviceCustomStore, paths: dict[str, str]) -> tuple[bytearray, int]:
    """The exact bytes the owner would save, as handle_export gets them, with peak memory."""
    rss = vm_rss()
    tracemalloc.start()
    started = time.monotonic()
    body, left_out = ConfigBackup(config_paths=paths, device_custom=store).export_file()
    seconds = time.monotonic() - started
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    print(
        f"   export: {len(body):,} bytes ({RESTORE_LIMIT_BYTES - len(body):,} under the limit), "
        f"acknowledgements_left_out {left_out:,}, {seconds:.1f} s"
    )
    print(f"   peak traced memory (export_file): {peak / 2**20:.1f} MiB")
    print(f"   VmRSS before the export: {rss}, after: {vm_rss()}")
    return body, left_out


def check_export(body: bytearray, left_out: int, acks: dict) -> dict:
    """The parsed backup; fails unless it fits and keeps exactly the newest acknowledgements."""
    # fit hands back a bytearray, which saves a 16 MiB bytes copy
    if not isinstance(body, (bytes, bytearray)) or len(body) >= RESTORE_LIMIT_BYTES:
        fail(
            f"the export is {type(body).__name__} of {len(body):,}, not bytes under the limit"
        )
    if left_out <= 0:
        fail("nothing was left out: the fixture didn't push the backup past the limit")
    data = json.loads(body)
    meta_left = data["metadata"].get("acknowledgements_left_out")
    if meta_left != left_out:
        fail(f"metadata says {meta_left!r} left out, export_file says {left_out}")
    kept = dict(sorted(acks.items(), key=newest_first)[: len(acks) - left_out])
    if data["sections"]["alert_acknowledgements"] != kept:
        fail("the exported acknowledgements aren't exactly the newest set")
    print(f"   the export keeps exactly the {len(kept):,} newest acknowledgements")
    return data


def restore(data: dict, left_out: int) -> tuple[str, dict[str, str]]:
    """The preflight, then import_config, into a second box."""
    root, paths = box("after")
    with open(paths["notification_config"], "w") as fh:
        json.dump(
            {"channels": {}, "rules": {}}, fh
        )  # never seeded from the environment
    open(paths["env_file"], "w").close()
    hub = NotificationHub(
        config_path=paths["notification_config"], env_file=paths["env_file"]
    )
    dest = ConfigBackup(
        config_paths=paths,
        device_custom=DeviceCustomStore(root=root),
        notification_hub=hub,
    )
    validation = dest.validate_import(data)
    if not validation.get("is_valid"):
        fail(f"the preflight refused the export: {validation.get('errors')}")
    if not any(
        f"{left_out:,}" in w or str(left_out) in w for w in validation["warnings"]
    ):
        fail(f"no warning names the {left_out:,} left out: {validation['warnings']}")
    started = time.monotonic()
    result = dest.import_config(data)
    missing = {"device_aliases", "device_pictures", "alert_acknowledgements"} - set(
        result.get("applied", [])
    )
    if not result.get("success") or result.get("errors") or missing:
        fail(f"the import didn't apply cleanly (missing {sorted(missing)}): {result}")
    print(
        f"   preflight passed, import applied {len(result['applied'])} sections in "
        f"{time.monotonic() - started:.1f} s"
    )
    return root, paths


def check_after(
    root: str, paths: dict[str, str], store: DeviceCustomStore, kept: dict
) -> None:
    with open(paths["alert_acks"], encoding="utf-8") as fh:
        if json.load(fh) != kept:
            fail("the restored acknowledgements aren't exactly the kept set")
    if DeviceCustomStore(root=root).export() != store.export():
        fail("the restored names and pictures differ from the box's")
    print(
        f"   after: {len(kept):,} acknowledgements, {PICTURES} names and pictures, as exported"
    )


def main() -> None:
    root, paths = box("before")
    store, acks = build_before(root, paths)
    body, left_out = export(store, paths)
    data = check_export(body, left_out, acks)
    after_root, after_paths = restore(data, left_out)
    check_after(
        after_root, after_paths, store, data["sections"]["alert_acknowledgements"]
    )
    print(f"   VmRSS after the restore: {vm_rss()}")
    print("BACKUP-SIZE-OK")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # the deploy script passes only on BACKUP-SIZE-OK
        fail(f"{type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
