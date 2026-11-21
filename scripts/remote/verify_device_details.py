"""NET-320 deploy check: the device details store and its backup section, end to end.

Runs inside a throwaway copy of the just-built daemon image (deploy-device-details.sh):
    docker run --rm -i --network none --entrypoint python3 <image id> -
        < verify_device_details.py
No mounts and no network, so nothing live is read or touched: NETTAP_DATA_DIR and every
backup path point into a fresh temp directory. Prints DEVICE-DETAILS-OK only after the
last check. Locally, from daemon/:
    PYTHONPATH=. python ../scripts/remote/verify_device_details.py
"""

import json
import os
import stat
import sys
import tempfile

sys.path.insert(0, "/opt/nettap/daemon")

TMP = tempfile.mkdtemp()
DATA = os.path.join(TMP, "data")  # not created: the first update must make it
os.environ["NETTAP_DATA_DIR"] = DATA
os.environ["OWNER_TZ_FILE"] = os.path.join(TMP, "owner-timezone.json")

from services import config_backup  # noqa: E402
from services.config_backup import ConfigBackup  # noqa: E402
from services.device_custom import StoreUnavailable  # noqa: E402
from services.device_details import (  # noqa: E402
    DETAILS_MAX_BYTES,
    TEXT_MAX,
    TOO_BIG,
    WATCH_FULL,
    WATCH_MAX,
    DeviceDetailsStore,
    encode,
)

MAC = "AA:BB:CC:DD:EE:FF"
FILE = "device_details.json"
NOTE = "x" * TEXT_MAX["notes"]


def fail(why: str) -> None:
    print("FAIL", why)
    sys.exit(1)


def mac(i: int) -> str:
    return f"02:00:00:00:{i // 256:02X}:{i % 256:02X}"


def refused(fn, *args) -> str | None:
    """The ValueError's message, or None when the call went through."""
    try:
        fn(*args)
    except ValueError as exc:
        return str(exc)
    return None


def check_update_and_reopen() -> DeviceDetailsStore:
    store = DeviceDetailsStore()
    if os.path.exists(DATA) or not store.healthy:
        fail("the data directory existed before the first update, or the store is off")
    snap = store.update(
        MAC, {"watch_after_min": 30, "group": "Kids", "notes": "  café  "}
    )
    want = {"watch_after_min": 30, "group": "Kids", "owner": None, "notes": "café"}
    if snap != want or store.get(MAC) != want:
        fail(f"update returned {snap}, get gives {store.get(MAC)}, expected {want}")
    if not os.path.isdir(DATA):
        fail("the first update didn't create the data directory")
    print(
        "   the first update created the directory and returned the committed snapshot"
    )
    if DeviceDetailsStore().get(MAC) != want:
        fail("a reopened store doesn't see the update")
    print("   a reopened store sees it")
    mode = stat.S_IMODE(os.stat(os.path.join(DATA, FILE)).st_mode)
    if mode != 0o600:
        fail(f"file mode is {oct(mode)}, expected 0o600")
    print("   the file is 0600")
    return store


def check_watch_budget(store: DeviceDetailsStore) -> None:
    for i in range(1, WATCH_MAX):  # MAC already holds one watch
        store.update(mac(i), {"watch_after_min": 15})
    reason = refused(store.update, mac(WATCH_MAX), {"watch_after_min": 15})
    if reason != WATCH_FULL:
        fail(
            f"watch {WATCH_MAX + 1} was not refused with the budget message: {reason!r}"
        )
    if refused(store.update, MAC, {"watch_after_min": 60}) is not None:
        fail(f"changing an existing watch at {WATCH_MAX} was refused")
    watched = sum(
        "watch_after_min" in e for e in DeviceDetailsStore().export().values()
    )
    if watched != WATCH_MAX or store.get(MAC)["watch_after_min"] != 60:
        fail(f"{watched} watches on disk after the budget checks, expected {WATCH_MAX}")
    print(f"   watch {WATCH_MAX + 1} refused, an existing watch changed at {WATCH_MAX}")


def check_size_budget() -> None:
    # fill with full notes, then find the one note length that ends one byte over
    full = {"notes": NOTE}
    per = len(encode({mac(0): full, mac(1): full})) - len(encode({mac(0): full}))
    count = (DETAILS_MAX_BYTES - len(encode({})) + 1) // per
    devices = {mac(i): full for i in range(count)}
    new = "02:FF:FF:FF:FF:FF"
    over = DETAILS_MAX_BYTES + 2 - len(encode({**devices, new: {"notes": "x"}}))
    if over < 2:  # too little room for even a one-character note: free some
        devices[mac(count - 1)] = {"notes": NOTE[:500]}
        over += 500
    if not 2 <= over <= TEXT_MAX["notes"]:
        fail(f"the size probe is off: a {over}-character note would be needed")
    root = os.path.join(TMP, "budget")
    path = os.path.join(root, FILE)
    store = DeviceDetailsStore(root=root)
    store.restore(devices)
    before = os.path.getsize(path)
    reason = refused(store.update, new, {"notes": "x" * over})
    if reason != TOO_BIG or os.path.getsize(path) != before:
        fail(f"one byte over {DETAILS_MAX_BYTES} wasn't refused cleanly: {reason!r}")
    if refused(store.update, new, {"notes": "x" * (over - 1)}) is not None:
        fail(f"exactly {DETAILS_MAX_BYTES} bytes was refused")
    if os.path.getsize(path) != DETAILS_MAX_BYTES:
        fail(f"the file is {os.path.getsize(path)} bytes, expected {DETAILS_MAX_BYTES}")
    print(f"   {DETAILS_MAX_BYTES} bytes accepted, one byte over refused")


def check_strict_mac(store: DeviceDetailsStore) -> None:
    kept = store.get(MAC)
    for bad in (MAC + ":00", MAC + ":", MAC + ":ZZ"):
        if refused(store.clear, bad) is None:
            fail(f"clear({bad!r}) was accepted")
        if store.get(MAC) != kept or DeviceDetailsStore().get(MAC) != kept:
            fail(f"clear({bad!r}) was refused but {MAC} changed")
    print(f"   clears for …:FF:00, …:FF: and …:FF:ZZ refused, {MAC} kept")


def check_backup_round_trip(store: DeviceDetailsStore) -> None:
    paths = {k: os.path.join(TMP, "backup", k) for k in config_backup._DEFAULT_PATHS}
    # the real download path: fit, then the shared preflight, then one encode (NET-344)
    # OLD CODE: exported = ConfigBackup(config_paths=paths, device_details=store).export_config()
    body, _left_out = ConfigBackup(config_paths=paths, device_details=store).export_file()
    exported = json.loads(bytes(body))
    section = exported["sections"].get("device_details")
    if section != store.export():
        fail("the export's device_details section doesn't match the store")
    root = os.path.join(TMP, "restored")
    second = DeviceDetailsStore(root=root)
    backup = {"metadata": exported["metadata"], "sections": {"device_details": section}}
    result = ConfigBackup(config_paths=paths, device_details=second).import_config(
        backup
    )
    if not result.get("success") or "device_details" not in result.get("applied", []):
        fail(f"the restore didn't apply: {result}")
    if DeviceDetailsStore(root=root).export() != section:
        fail("the restored store doesn't match the backup")
    print(
        f"   backup export -> restore into an empty store: {len(section)} devices match"
    )


def check_damaged_file() -> None:
    root = os.path.join(TMP, "damaged")
    os.makedirs(root)
    with open(os.path.join(root, FILE), "w") as fh:
        fh.write('{"version": 1, "devices": ')
    store = DeviceDetailsStore(root=root)
    if store.healthy:
        fail("a damaged file left the store healthy")
    try:
        store.export()
        fail("export() of a damaged store didn't raise")
    except StoreUnavailable:
        pass
    blank = {"group": None, "owner": None, "watch_after_min": None}
    if store.row_fields(MAC) != blank:
        fail(f"row_fields on a damaged store gave {store.row_fields(MAC)}")
    print("   a damaged file: unhealthy, export refused, rows read as nothing set")


def main() -> None:
    store = check_update_and_reopen()
    check_watch_budget(store)
    check_size_budget()
    check_strict_mac(store)
    check_backup_round_trip(store)
    check_damaged_file()
    print("DEVICE-DETAILS-OK")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # the deploy script passes only on DEVICE-DETAILS-OK
        fail(f"{type(exc).__name__}: {exc}")
