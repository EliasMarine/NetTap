"""NET-211 #3: Go Live reads the bridge ports the wizard saved, never a guess."""

import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from api.capture import register_capture_routes
from services.capture_config import saved_bridge_ports
from services.capture_manager import CaptureMode

BRIDGE_FILE = """[capture]
mode = bridge
interface = br0
management =

[bridge]
wan_interface = enp2s0
lan_interface = enp3s0
"""


@pytest.fixture
def conf(tmp_path, monkeypatch):
    path = tmp_path / "capture-mode.conf"
    monkeypatch.setenv("CAPTURE_CONFIG_PATH", str(path))
    return path


def test_ports_of_a_saved_bridge_config(conf):
    conf.write_text(BRIDGE_FILE)
    assert saved_bridge_ports() == ("enp2s0", "enp3s0")


@pytest.mark.parametrize(
    "text",
    [
        None,  # no file
        "",  # empty file
        "[capture]\nmode = bridge\n",  # no [bridge]
        BRIDGE_FILE.replace("wan_interface = enp2s0\n", ""),
        BRIDGE_FILE.replace("lan_interface = enp3s0\n", ""),
        BRIDGE_FILE.replace("= enp2s0", "="),  # empty name
        BRIDGE_FILE.replace("enp2s0", "eth0;rm -rf"),  # not an interface name
        # save_capture_config writes [bridge] defaults in every mode
        BRIDGE_FILE.replace("mode = bridge", "mode = mirror"),
        "not an ini file\n",  # unparsable
    ],
)
def test_no_ports_unless_the_wizard_saved_a_bridge(conf, text):
    if text is not None:
        conf.write_text(text)
    assert saved_bridge_ports() is None


class _Manager:
    def __init__(self, mode: CaptureMode, interface: str):
        self.mode = mode
        self._interface = interface

    def get_capture_interface(self) -> str:
        return self._interface


def _mode_reply(manager: _Manager) -> dict:
    async def run() -> dict:
        app = web.Application()
        app["capture_manager"] = manager
        register_capture_routes(app)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/capture/mode")
            assert resp.status == 200
            return await resp.json()

    return asyncio.run(run())


def test_bridge_mode_reply_carries_the_saved_ports(conf):
    conf.write_text(BRIDGE_FILE)
    body = _mode_reply(_Manager(CaptureMode.BRIDGE, "br0"))
    assert body == {
        "mode": "bridge",
        "interface": "br0",
        "wan_interface": "enp2s0",
        "lan_interface": "enp3s0",
    }


def test_bridge_mode_without_saved_ports_has_no_port_keys(conf):
    conf.write_text("")
    body = _mode_reply(_Manager(CaptureMode.BRIDGE, "br0"))
    assert body == {"mode": "bridge", "interface": "br0"}


def test_mirror_mode_reply_has_no_bridge_ports(conf):
    conf.write_text(BRIDGE_FILE.replace("mode = bridge", "mode = mirror"))
    body = _mode_reply(_Manager(CaptureMode.MIRROR, "enp4s0"))
    assert body == {"mode": "mirror", "interface": "enp4s0"}
