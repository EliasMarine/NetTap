"""NET-344 over HTTP: every downloadable backup restores (plan §5 "HTTP", "fit" memory, "Preflight").

The real backup routes on an app built as api/server.py builds it (client_max_size =
MAX_REQUEST_BYTES, safe_error_middleware), served by the daemon's own runner, which doesn't cancel
a handler when its client goes away. Files live in a temp dir.
"""

import asyncio
import base64
import json
import os
import subprocess
import sys
import threading
import time
import zoneinfo
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import api.backup as backup_api
import services.backup_checks as checks
import services.config_backup as cb
from api.backup import register_backup_routes
from api.error_replies import safe_error_middleware
from api.server import MAX_REQUEST_BYTES
from services import device_custom
from services.config_backup import LEFT_OUT, RESTORE_LIMIT_BYTES, ConfigBackup
from services.device_custom import DeviceCustomStore
from services.notification_hub import NotificationHub
from tests.test_backup_fit import ack_file_32mib

LIMIT = RESTORE_LIMIT_BYTES
ZONE = "Pacific/Kiritimati"  # UTC+14: the file's date is the owner's, not the server's
EMPTY = b'{"metadata":{"schema_version":2},"sections":{}}'


class _DaemonServer(TestServer):
    """web.AppRunner(app) with aiohttp's defaults, as the daemon runs: a handler keeps going
    when its client leaves (TestServer cancels it)."""

    async def _make_runner(self, **kwargs):
        kwargs.pop("handler_cancellation", None)
        return web.AppRunner(self.app, **kwargs)


async def _health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


class Box:
    """One NetTap's backup routes and files."""

    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.paths = {
            k: str(root / f"{k}.json")
            for k in (
                "notification_config",
                "excluded_ips",
                "bandwidth_cap",
                "retention_config",
                "home_location",
                "alert_acks",
                "suppressions",
            )
        }
        self.paths["capture_config"] = str(root / "capture-mode.conf")
        self.paths["env_file"] = str(root / ".env")
        self.store = DeviceCustomStore(str(root / "appdata"))
        self.hub = NotificationHub(
            config_path=self.paths["notification_config"],
            env_file=self.paths["env_file"],
        )
        self.backup = ConfigBackup(
            config_paths=self.paths, device_custom=self.store, notification_hub=self.hub
        )
        self.client: TestClient | None = None

    def write(self, key: str, data) -> None:
        Path(self.paths[key]).write_text(json.dumps(data))

    def read(self, key: str):
        return json.loads(Path(self.paths[key]).read_text())

    async def start(self) -> TestClient:
        app = web.Application(
            middlewares=[safe_error_middleware], client_max_size=MAX_REQUEST_BYTES
        )
        app["excluded_ips_file"] = self.paths["excluded_ips"]
        app["excluded_ips"] = []
        register_backup_routes(app, self.backup)
        app.router.add_get("/api/health", _health)
        self.client = TestClient(_DaemonServer(app))
        await self.client.start_server()
        return self.client


@pytest.fixture(autouse=True)
def owner_zone(tmp_path, monkeypatch):
    path = tmp_path / "owner-timezone.json"
    path.write_text(json.dumps({"tz": ZONE}))
    monkeypatch.setenv("OWNER_TZ_FILE", str(path))


@pytest_asyncio.fixture
async def boxes(tmp_path):
    made: list[Box] = []

    async def make(name: str = "a") -> Box:
        box = Box(tmp_path / name)
        await box.start()
        made.append(box)
        return box

    yield make
    for box in made:
        await box.client.close()


def _png(seed: int, size: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + os.urandom(size - 9) + bytes([seed % 256])


def _ack_set(n: int) -> dict:
    """n acknowledgements a second apart, a0 the oldest, in mixed ASCII and emoji."""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return {
        f"id{i:07d}": {
            "acknowledged_at": (start + timedelta(seconds=i)).isoformat(),
            "acknowledged_by": "admin" if i % 3 else "管理者 😀",
        }
        for i in range(n)
    }


def _padded(body: bytes, size: int) -> bytes:
    """A JSON document padded with trailing whitespace to exactly `size` bytes."""
    assert len(body) <= size
    return body + b" " * (size - len(body))


async def _post(client: TestClient, path: str, body: bytes):
    resp = await client.post(
        path, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        return resp.status, await resp.json()
    except Exception:
        return resp.status, await resp.text()


# ---------------------------------------------------------------------------- the download


@pytest.mark.asyncio
async def test_the_download_is_compact_json_with_its_headers(boxes):
    box = await boxes()
    box.store.set_name("AA:BB:CC:DD:EE:01", "Kid's tablet 📱")
    resp = await box.client.get("/api/backup/export")
    body = await resp.read()
    assert resp.status == 200
    assert resp.headers["Content-Type"].startswith("application/json")
    today = datetime.now(zoneinfo.ZoneInfo(ZONE)).date().isoformat()
    assert resp.headers["Content-Disposition"] == (
        f'attachment; filename="nettap-config-{today}.json"'
    )
    assert resp.headers["Cache-Control"] == "no-store"
    doc = json.loads(body.decode("utf-8"))
    assert body == cb.encode(doc)  # the one encoding, byte for byte
    assert LEFT_OUT not in doc["metadata"]
    assert "Kid's tablet 📱".encode() in body


@pytest.mark.asyncio
async def test_a_trimmed_backup_restores_into_another_box(boxes):
    """The before-and-after fixture: pictures, names and more acknowledgements than fit. The
    bytes go back as downloaded; the destination gets the names, the pictures and exactly the
    newest acknowledgements."""
    source, dest = await boxes("source"), await boxes("dest")
    for i in range(6):
        mac = f"AA:BB:CC:DD:EE:{i:02X}"
        source.store.set_name(mac, f"Device {i} 😀")
        source.store.set_photo(mac, base64.b64encode(_png(i, 250 * 1024)).decode())
    acks = _ack_set(200_000)
    source.write("alert_acks", acks)

    resp = await source.client.get("/api/backup/export")
    body = await resp.read()
    assert resp.status == 200 and len(body) < LIMIT
    left = json.loads(body)["metadata"][LEFT_OUT]
    assert 0 < left < len(acks)

    status, validation = await _post(dest.client, "/api/backup/validate", body)
    assert status == 200 and validation["is_valid"], validation
    kept = len(acks) - left
    assert (
        f"This backup leaves out {left:,} alert acknowledgements. Restoring replaces this "
        f"NetTap's acknowledgements with the {kept:,} it carries."
    ) in validation["warnings"]

    status, result = await _post(dest.client, "/api/backup/import", body)
    assert status == 200, result
    assert {"device_aliases", "device_pictures", "alert_acknowledgements"} <= set(
        result["applied"]
    )
    assert dest.store.names() == source.store.names()
    for i in range(6):
        mac = f"AA:BB:CC:DD:EE:{i:02X}"
        assert dest.store.photo(mac)[0] == source.store.photo(mac)[0]
    newest = sorted(acks, key=lambda k: acks[k]["acknowledged_at"])[left:]
    assert set(dest.read("alert_acks")) == set(newest)


# ---------------------------------------------------------------------------- the cutoff


@pytest.mark.asyncio
async def test_limit_minus_one_restores_and_over_the_limit_is_a_plain_413(boxes):
    """aiohttp <=3.13 refuses a body >= the limit, 3.14 one > it, so LIMIT + 1 is the plain 413
    on both and LIMIT - 1 (the most fit ever answers) restores on both."""
    box = await boxes()
    under, over = _padded(EMPTY, LIMIT - 1), _padded(EMPTY, LIMIT + 1)
    status, validation = await _post(box.client, "/api/backup/validate", under)
    assert status == 200 and validation["is_valid"], validation
    status, result = await _post(box.client, "/api/backup/import", under)
    assert status == 200 and result["applied"] == [], result
    for path in ("/api/backup/validate", "/api/backup/import"):
        status, reply = await _post(box.client, path, over)
        assert status == 413, path
        assert reply == {"error": "This file is over the 16 MB restore limit."}
    status, _ = await _post(box.client, "/api/backup/validate", b'{"metadata": ')
    assert status == 400


@pytest.mark.asyncio
async def test_a_near_limit_file_with_1e_05_posted_as_raw_bytes_restores(boxes):
    """Rollback: old Settings re-stringified 1e-05 as 0.00001, two bytes more; the saved bytes
    posted directly still restore."""
    box = await boxes()
    doc = (
        b'{"metadata":{"schema_version":2},'
        b'"sections":{"alert_acknowledgements":{"a1":{"score":1e-05}}}}'
    )
    body = _padded(doc, LIMIT - 1)
    status, validation = await _post(box.client, "/api/backup/validate", body)
    assert status == 200 and validation["is_valid"], validation
    status, result = await _post(box.client, "/api/backup/import", body)
    assert status == 200 and result["applied"] == ["alert_acknowledgements"], result
    assert box.read("alert_acks") == {"a1": {"score": 1e-05}}


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/backup/validate", "/api/backup/import"])
@pytest.mark.parametrize(
    "number,section",
    [
        ("NaN", '"alert_acknowledgements":{"a1":{"score":NaN}}'),
        ("Infinity", '"alert_suppressions":{"global":[{"signature_id":Infinity}]}'),
        ("-Infinity", '"notification_rules":{"r1":{"min":-Infinity}}'),
    ],
)
async def test_nan_and_infinity_are_refused_as_invalid_json(
    boxes, path, number, section
):
    """L1: Python's json takes them; once written, every export was a 422 and the Alerts page
    got NaN. They are not JSON, so the body is the plain 400 and nothing is written."""
    box = await boxes()
    body = '{"metadata":{"schema_version":2},"sections":{' + section + "}}"
    status, reply = await _post(box.client, path, body.encode())
    assert (status, reply) == (400, {"error": "Invalid JSON body"}), number
    for key in ("alert_acks", "suppressions", "notification_config"):
        assert (
            not Path(box.paths[key]).exists()
            or number not in Path(box.paths[key]).read_text()
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [-1, "3", True, 1.5, None])
async def test_a_malformed_left_out_count_is_a_validation_error_not_a_500(boxes, value):
    box = await boxes()
    doc = {
        "metadata": {"schema_version": 2, LEFT_OUT: value},
        "sections": {"alert_acknowledgements": {}},
    }
    status, validation = await _post(
        box.client, "/api/backup/validate", json.dumps(doc).encode()
    )
    assert status == 200 and validation["is_valid"] is False, validation
    status, _ = await _post(box.client, "/api/backup/import", json.dumps(doc).encode())
    assert status == 400


@pytest.mark.asyncio
async def test_an_invalid_section_beside_a_valid_cap_writes_nothing(boxes):
    box = await boxes()
    box.write("bandwidth_cap", {"monthly_cap_bytes": 1000})
    doc = {
        "metadata": {"schema_version": 2},
        "sections": {
            "bandwidth_cap": {"monthly_cap_bytes": 5000},
            "excluded_ips": ["10.0.0.0/8"],
        },
    }
    status, result = await _post(
        box.client, "/api/backup/import", json.dumps(doc).encode()
    )
    assert status == 400 and result["applied"] == [], result
    assert box.read("bandwidth_cap") == {"monthly_cap_bytes": 1000}


# ---------------------------------------------------------------------------- refusals


@pytest.mark.asyncio
async def test_a_legacy_range_is_a_422_until_the_owner_removes_it(boxes):
    box = await boxes()
    box.write("excluded_ips", ["192.0.2.1", "10.0.0.0/8"])
    before = Path(box.paths["excluded_ips"]).read_text()
    resp = await box.client.get("/api/backup/export")
    reply = await resp.json()
    assert resp.status == 422
    assert reply == {
        "error": "Excluded IPs: 10.0.0.0/8 is a range. NetTap no longer keeps ranges, so it "
        "can't restore this one. Remove it in Settings › Network, then export again. Live "
        "Connections and Top Destinations stop hiding that range once it's removed.",
        "code": "legacy_excluded_ips",
    }
    assert Path(box.paths["excluded_ips"]).read_text() == before
    box.write("excluded_ips", ["192.0.2.1"])
    assert (await box.client.get("/api/backup/export")).status == 200


# Settings saved any text before 7c1f7a99 (2026-10-29): the owner's own entries, not junk
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entry", ["192.168.1.050", "300.1.1.1", "printer.local", "fe80::1%eth0"]
)
async def test_old_text_that_isnt_one_ip_is_legacy_until_removed(boxes, entry):
    box = await boxes()
    box.write("excluded_ips", ["192.0.2.1", entry])
    resp = await box.client.get("/api/backup/export")
    assert resp.status == 422
    assert await resp.json() == {
        "error": f"Excluded IPs: {entry} isn't a single IP address. Remove it in "
        "Settings › Network, then export again.",
        "code": "legacy_excluded_ips",
    }
    box.write("excluded_ips", ["192.0.2.1"])
    assert (await box.client.get("/api/backup/export")).status == 200


@pytest.mark.asyncio
async def test_a_range_and_several_old_entries_are_named_together(boxes):
    box = await boxes()
    box.write("excluded_ips", ["10.0.0.0/8", "printer.local", "nas.local", "300.1.1.1"])
    reply = await (await box.client.get("/api/backup/export")).json()
    assert reply["code"] == "legacy_excluded_ips"
    assert "Excluded IPs: 10.0.0.0/8 is a range." in reply["error"]
    assert (
        "Excluded IPs: printer.local and 2 more aren't single IP addresses. Remove them "
        "in Settings › Network, then export again."
    ) in reply["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stored", [["192.0.2.1", 5], ["printer.local", None], {"a": 1}]
)
async def test_excluded_ips_no_api_wrote_are_invalid_section(boxes, stored):
    """Something that isn't text, or a file that isn't a list, never came from Settings."""
    box = await boxes()
    box.write("excluded_ips", stored)
    resp = await box.client.get("/api/backup/export")
    assert resp.status == 422
    assert (await resp.json())["code"] == "invalid_section"


@pytest.mark.asyncio
async def test_more_than_10000_excluded_ips_is_a_422_until_the_owner_saves_10000(boxes):
    box = await boxes()
    ips = [f"10.0.{i >> 8}.{i & 255}" for i in range(10_001)]
    box.write("excluded_ips", ips)
    resp = await box.client.get("/api/backup/export")
    reply = await resp.json()
    assert resp.status == 422 and reply["code"] == "legacy_excluded_ips"
    assert (
        "there are 10,001" in reply["error"]
        and "Remove 1 in Settings" in reply["error"]
    )
    box.write("excluded_ips", ips[:10_000])
    assert (await box.client.get("/api/backup/export")).status == 200


@pytest.mark.asyncio
async def test_anything_else_is_invalid_section_and_the_log_names_entry_and_file(
    boxes, caplog
):
    box = await boxes()
    box.write("excluded_ips", ["10.0.0.0/8"])
    box.write("suppressions", {"global": [{"signature_id": 1}, {"signature_id": "x"}]})
    resp = await box.client.get("/api/backup/export")
    reply = await resp.json()
    assert resp.status == 422 and reply["code"] == "invalid_section"
    assert reply["error"].startswith(
        "No backup was made: excluded IPs, alert suppressions"
    )
    logged = caplog.text
    assert box.paths["suppressions"] in logged and "global[1]" in logged
    assert box.paths["excluded_ips"] in logged and "'10.0.0.0/8'" in logged


@pytest.mark.asyncio
async def test_suppressions_with_very_long_reasons_are_a_413_naming_net_346(
    boxes, caplog
):
    box = await boxes()
    box.write(
        "suppressions",
        {"global": [{"signature_id": i, "reason": "r" * 6_000_000} for i in range(3)]},
    )
    resp = await box.client.get("/api/backup/export")
    reply = await resp.json()
    assert resp.status == 413
    assert set(reply) == {"error", "code"} and reply["code"] == "backup_too_large"
    assert reply["error"].startswith("This backup would be 18.0 MB, over the 16 MB")
    assert "The largest part is alert suppressions (18.0 MB)" in reply["error"]
    assert "NetTap can't remove suppressions yet (NET-346)." in reply["error"]
    assert "section sizes" in caplog.text and "'excluded_ips'" in caplog.text


@pytest.mark.asyncio
async def test_a_stored_numeric_reason_exports_as_text_and_validates(boxes):
    box = await boxes()
    box.write(
        "suppressions",
        {
            "global": [
                {"signature_id": 1, "reason": 5},
                {"signature_id": 2, "reason": None},
            ]
        },
    )
    resp = await box.client.get("/api/backup/export")
    body = await resp.read()
    assert resp.status == 200
    reasons = [
        e["reason"]
        for e in json.loads(body)["sections"]["alert_suppressions"]["global"]
    ]
    assert reasons == ["5", ""]
    status, validation = await _post(box.client, "/api/backup/validate", body)
    assert status == 200 and validation["is_valid"], validation


# ---------------------------------------------------------------------------- one at a time


async def _until(predicate, seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        await asyncio.sleep(0.005)


@pytest.mark.asyncio
async def test_two_exports_of_a_32_mib_file_one_builds_and_none_waits(
    boxes, monkeypatch
):
    """The build is held until the 503s are checked, so the order is fixed, not timed."""
    box = await boxes()
    box.write("alert_acks", ack_file_32mib())
    building, release = threading.Event(), threading.Event()
    builds = []
    real = ConfigBackup.export_config

    def held(self):
        builds.append(self)
        building.set()
        assert release.wait(30), "the build was never released"
        return real(self)

    monkeypatch.setattr(ConfigBackup, "export_config", held)
    state = box.client.app[backup_api.EXPORT_STATE]

    first = asyncio.create_task(box.client.get("/api/backup/export"))
    try:
        await _until(building.is_set)
        second = await box.client.get("/api/backup/export")
        assert second.status == 503
        assert second.headers["Retry-After"] == "30"
        assert await second.json() == {
            "error": "A backup is already being made. Try again in a moment."
        }
    finally:
        release.set()
    resp = await first
    body = await resp.read()
    assert resp.status == 200 and len(body) < LIMIT
    assert json.loads(body)["metadata"][LEFT_OUT] > 0
    assert len(builds) == 1 and not state["busy"]

    # a client that leaves mid-build: its build finishes, and no later build follows from it
    building.clear()
    release.clear()
    gone = asyncio.create_task(box.client.get("/api/backup/export"))
    try:
        await _until(building.is_set)
        gone.cancel()
        assert (await box.client.get("/api/backup/export")).status == 503
    finally:
        release.set()
    await _until(
        lambda: not state["busy"], seconds=120
    )  # a hang guard, not a time limit
    assert len(builds) == 2


# A fresh interpreter, so its peak RSS is this export's alone (ru_maxrss: KiB on Linux, bytes on macOS)
_PEAK = """
import resource, sys
from services.config_backup import ConfigBackup
scale = 1 if sys.platform == "darwin" else 1024
backup = ConfigBackup(config_paths={"alert_acks": sys.argv[1]})
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * scale
body, left = backup.export_file()
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * scale
assert left > 0 and len(body) < 16 * 1024 * 1024
print(f"{before / 2**20:.0f} MiB before, {after / 2**20:.0f} MiB peak")
"""


def test_the_whole_export_path_peak_is_reported(tmp_path):
    """From the file read to the bytes, in its own process: reported (plan §5 memory)."""
    path = tmp_path / "acks.json"
    path.write_text(json.dumps(ack_file_32mib()))
    env = {**os.environ, "EXCLUDED_IPS_FILE": str(tmp_path / "no-excluded-ips.json")}
    done = subprocess.run(
        [sys.executable, "-c", _PEAK, str(path)],
        cwd=Path(__file__).resolve().parents[1],  # daemon/, as the suite runs
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    print(f"export_file of 32 MiB acknowledgements: {done.stdout.strip()}")


# ---------------------------------------------------------------------------- off the loop


@pytest.mark.asyncio
async def test_health_answers_during_a_populated_near_limit_validation(
    boxes, monkeypatch
):
    """32 photos (the 8 MiB cap), 10,000 excluded IPs and acknowledgements up to the limit."""
    box = await boxes()
    per = device_custom.PHOTOS_MAX_TOTAL // 32
    sections = {
        "device_aliases": {f"AA:BB:CC:DD:EE:{i:02X}": f"Camera {i}" for i in range(32)},
        "device_pictures": {
            f"AA:BB:CC:DD:EE:{i:02X}": {
                "image": "data:image/png;base64,"
                + base64.b64encode(_png(i, per)).decode()
            }
            for i in range(32)
        },
        "excluded_ips": [f"2001:db8::{i:x}" for i in range(10_000)],
        "alert_acknowledgements": _ack_set(40_000),
    }
    doc = cb.encode({"metadata": {"schema_version": 2}, "sections": sections})
    assert LIMIT - 5_000_000 < len(doc) < LIMIT
    body = _padded(doc, LIMIT - 1)

    entered, release = threading.Event(), threading.Event()
    real = checks.restore_problems

    def slow(*args):
        entered.set()
        # release is set only after /api/health answers, which needs the loop free
        assert release.wait(10), "validation blocked the loop"
        return real(*args)

    monkeypatch.setattr(checks, "restore_problems", slow)
    validating = asyncio.create_task(_post(box.client, "/api/backup/validate", body))
    try:
        await _until(entered.is_set)
        health = await box.client.get("/api/health")
        assert health.status == 200
    finally:
        release.set()
    status, validation = await validating
    assert status == 200 and validation["is_valid"], validation


@pytest.mark.asyncio
async def test_a_valid_cap_then_a_failed_capture_restart_reports_both(boxes):
    """An operational failure after the preflight is reported as it happened, not undone."""
    box = await boxes()
    Path(box.paths["capture_config"]).write_text(
        "[capture]\nmode = mirror\ninterface = eth1\nmanagement = eth0\n"
    )
    box.write("bandwidth_cap", {"monthly_cap_bytes": 1000})
    restart = web.json_response(
        {"status": "ok", "capture_restart": {"errors": ["docker restart failed"]}}
    )
    doc = {
        "metadata": {"schema_version": 2},
        "sections": {
            "bandwidth_cap": {"monthly_cap_bytes": 5000},
            "capture_mode_config": {
                "capture_mode": "mirror",
                "capture_interface": "eth2",
                "management_interface": "eth0",
            },
        },
    }
    with (
        patch.dict(os.environ, {"CAPTURE_CONFIG_PATH": box.paths["capture_config"]}),
        patch("api.backup._apply_configuration", return_value=restart),
    ):
        resp = await box.client.post("/api/backup/import?apply_capture=1", json=doc)
        result = await resp.json()
    assert resp.status == 400
    assert result["applied"] == ["bandwidth_cap"]
    assert any("didn't restart" in e for e in result["errors"])
    assert box.read("bandwidth_cap") == {"monthly_cap_bytes": 5000}
