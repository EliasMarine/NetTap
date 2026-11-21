"""GET /api/devices/watched and the job's capture-health reader (NET-331, plan §2.6)."""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, make_mocked_request

from api import devices_watched as dw
from services import watched_devices as wd
from services.capture_manager import CaptureHealth
from services.pipeline_health import NETWORK_INDEX
from tests.watched_rig import D, MAC_D, MAC_E, ROUTER, Rig, at, iso


class _Base(AioHTTPTestCase):
    async def get_application(self):
        self._dir = tempfile.TemporaryDirectory()
        self._tmp = Path(self._dir.name)
        self.rig = Rig(self._tmp)
        app = web.Application()
        # the device list's dynamic route is registered first in create_app
        app.router.add_get("/api/devices/{ip}", lambda r: web.json_response({}))
        dw.register_watched_devices_routes(app, self.rig.watcher)
        return app

    async def tearDownAsync(self):
        self._dir.cleanup()

    async def get(self) -> tuple[int, dict]:
        resp = await self.client.get("/api/devices/watched")
        return resp.status, await resp.json()


class TestList(_Base):
    async def test_rows_merge_the_watches_with_the_job_state(self):
        rig = self.rig
        rig.names[MAC_D] = "Kitchen plug"
        rig.bring_down()
        rig.watch(MAC_E, 60)  # added since the last run
        status, body = await self.get()
        assert status == 200
        assert body["check"]["success_at"] == iso(at("12:35"))
        assert body["check"]["scope"] == "mirror|enp1s0"
        assert body["devices"] == [
            {
                "mac": MAC_D,
                "name": "Kitchen plug",
                "after_min": 15,
                "state": "down",
                "seen_at": iso(
                    at("12:02")
                ),  # the incident's: the last confirmed sighting
                "since": iso(at("12:35")),
            },
            {
                "mac": MAC_E,
                "name": None,
                "after_min": 60,
                "state": "unknown",
                "seen_at": None,
                "since": None,
            },
        ]

    async def test_an_up_device_shows_its_latest_sighting(self):
        self.rig.bring_up()
        self.rig.conn(D, ROUTER, at("12:06"), at("12:08"))
        self.rig.check(at("12:10"))
        (row,) = (await self.get())[1]["devices"]
        assert (row["state"], row["seen_at"], row["since"]) == (
            "up",
            iso(at("12:08")),
            iso(at("12:05")),
        )

    async def test_no_watches_is_an_empty_list(self):
        status, body = await self.get()
        assert status == 200 and body == {"check": wd.EMPTY_CHECK, "devices": []}

    async def test_an_unreadable_state_file_is_check_error_with_devices_unknown(self):
        self.rig.watch()
        self.rig.path.write_text("{broken")
        status, body = await self.get()
        assert status == 200
        assert body["check"]["error"] == wd.UNREADABLE
        assert [(r["mac"], r["state"]) for r in body["devices"]] == [(MAC_D, "unknown")]
        assert self.rig.path.read_text() == "{broken"

    async def test_a_damaged_details_store_is_a_fixed_503(self):
        (self._tmp / "device_details.json").write_text("{broken")
        self.rig.details = type(self.rig.details)(str(self._tmp))
        self.rig.watcher._details = self.rig.details
        status, body = await self.get()
        assert status == 503 and body == {"error": dw.STORE_UNREADABLE}


# --- the capture-health reader ----------------------------------------------------


def _health(mode: str = "mirror") -> CaptureHealth:
    return CaptureHealth(
        mode=mode,
        status="normal",
        capture_interface="enp1s0",
        link_up=True,
        promisc_enabled=True,
    )


class _Manager:
    def __init__(self, health: CaptureHealth, delay: float = 0.0) -> None:
        self.health, self.delay = health, delay
        self.loop = None
        self.cancelled = False

    async def get_health(self) -> CaptureHealth:
        self.loop = asyncio.get_running_loop()
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return self.health


class TestCaptureHealthReader(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        app["capture_manager"] = _Manager(_health())
        self.read = dw.capture_health_reader(app)
        return app

    async def test_it_asks_the_current_manager_on_the_app_loop(self):
        got = await asyncio.to_thread(self.read)
        assert got["mode"] == "mirror" and got["link_up"] is True
        assert self.app["capture_manager"].loop is asyncio.get_running_loop()
        # setup replaces the manager: the next call asks the new one
        self.app["capture_manager"] = _Manager(_health("dhcp_gateway"))
        assert (await asyncio.to_thread(self.read))["mode"] == "dhcp_gateway"

    async def test_a_slow_manager_times_out_and_is_cancelled(self):
        slow = _Manager(_health(), delay=30)
        self.app["capture_manager"] = slow
        with patch.object(dw, "HEALTH_TIMEOUT_S", 0.05):
            with pytest.raises(TimeoutError):
                await asyncio.to_thread(self.read)
        await asyncio.sleep(0.01)  # the loop runs the cancellation
        assert slow.cancelled


def test_before_start_up_the_reader_raises():
    app = web.Application()
    app["capture_manager"] = _Manager(_health())
    with pytest.raises(RuntimeError):
        dw.capture_health_reader(app)()


# --- create_app wiring ----------------------------------------------------------


def _real_app(tmp_path) -> web.Application:
    """The daemon's own app from create_app, with every route in its real order."""
    from api.server import create_app
    from storage.manager import RetentionConfig, StorageManager

    client = MagicMock(**{"search.return_value": {}})
    with patch.object(StorageManager, "_create_client", return_value=client):
        storage = StorageManager(RetentionConfig(), "http://localhost:9200")
    config = tmp_path / "notifications.json"
    config.write_text(json.dumps({"channels": {}, "rules": {}}))
    env = {
        "DAEMON_TOKEN_FILE": str(tmp_path / "auth" / "token"),
        "EXCLUDED_IPS_FILE": str(tmp_path / "excluded_ips.json"),
        "NOTIFICATION_CONFIG": str(config),
        "NETTAP_DATA_DIR": str(tmp_path),
    }
    with patch.dict(os.environ, env):
        return create_app(storage, MagicMock(), "http://localhost:9200")


def test_create_app_registers_the_job(tmp_path):
    app = _real_app(tmp_path)
    (job,) = [r for r in app["scheduler"].view() if r["name"] == "watched-devices"]
    assert (job["label"], job["every_s"]) == ("Watched devices", 300)
    assert app["scheduler"]._jobs["watched-devices"].deadline_s == 60
    assert app["watched_devices"]._index == NETWORK_INDEX


def test_the_real_router_sends_watched_to_its_handler_not_the_ip_route(tmp_path):
    from api import devices

    app = _real_app(tmp_path)
    paths = [r.canonical for r in app.router.resources()]
    # the case that matters: the device list's {ip} route is registered first
    assert paths.index("/api/devices/{ip}") < paths.index("/api/devices/watched")

    async def handler_for(path: str):
        request = make_mocked_request("GET", path, app=app)
        return (await app.router.resolve(request)).handler

    assert asyncio.run(handler_for("/api/devices/watched")) is dw.handle_watched
    assert (
        asyncio.run(handler_for("/api/devices/10.0.0.5"))
        is devices.handle_device_detail
    )
