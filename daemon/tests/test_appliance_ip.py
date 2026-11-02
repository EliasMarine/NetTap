"""#79: NetTap's own address is left out of the figures; the .env.example placeholder is not.

On the G11, MGMT_IP held the shipped placeholder 192.168.1.100, which was excluded (and saved
into the owner's list), while the box's real address 192.168.1.199 was counted everywhere.
"""

import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from services.excluded_ips import detect_appliance_ip

HOST_ADDRS = [
    {"ifname": "lo", "addr_info": [{"local": "127.0.0.1"}]},
    {"ifname": "eno1", "addr_info": [{"local": "192.168.1.199"}]},
]


def _fake_ip(argv, **_kw):
    """`ip -j -4 addr show [iface]` on a host whose management NIC eno1 is 192.168.1.199."""
    iface = argv[5] if len(argv) > 5 else None
    addrs = [a for a in HOST_ADDRS if iface in (None, a["ifname"])]
    return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(addrs), stderr="")


def _detect(env, fallback=""):
    with patch.dict(os.environ, env, clear=False), patch("subprocess.run", side_effect=_fake_ip):
        return detect_appliance_ip(fallback)


class TestDetectApplianceIp(unittest.TestCase):
    def test_placeholder_mgmt_ip_is_ignored_for_the_real_address(self):
        env = {"MGMT_IP": "192.168.1.100", "MGMT_INTERFACE": ""}
        self.assertEqual(_detect(env, fallback="eno1"), "192.168.1.199")

    def test_mgmt_ip_this_host_holds_is_used(self):
        self.assertEqual(_detect({"MGMT_IP": "192.168.1.199", "MGMT_INTERFACE": ""}), "192.168.1.199")

    def test_mgmt_interface_beats_the_capture_config(self):
        env = {"MGMT_IP": "", "MGMT_INTERFACE": "eno1"}
        self.assertEqual(_detect(env, fallback="nope0"), "192.168.1.199")

    def test_nothing_configured_finds_nothing(self):
        self.assertIsNone(_detect({"MGMT_IP": "", "MGMT_INTERFACE": ""}))

    def test_mgmt_ip_is_trusted_when_addresses_cannot_be_listed(self):
        env = {"MGMT_IP": "10.1.2.3", "MGMT_INTERFACE": ""}
        with patch.dict(os.environ, env), patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertEqual(detect_appliance_ip(), "10.1.2.3")


class TestApplianceIpNotSaved(unittest.TestCase):
    def test_detected_ip_is_excluded_but_not_written_into_the_owners_list(self):
        from api.server import create_app
        from storage.manager import RetentionConfig, StorageManager

        with tempfile.TemporaryDirectory() as tmp:
            saved = os.path.join(tmp, "excluded_ips.json")
            with open(saved, "w") as f:
                json.dump(["10.0.0.5"], f)
            # An empty reply, not a MagicMock: LAN detection pages until a reply has no after_key (#96)
            client = MagicMock(**{"search.return_value": {}})
            with patch.object(StorageManager, "_create_client", return_value=client):
                storage = StorageManager(RetentionConfig(), "http://localhost:9200")
            env = {"DAEMON_TOKEN_FILE": os.path.join(tmp, "auth", "token"), "EXCLUDED_IPS_FILE": saved}
            with (
                patch.dict(os.environ, env),
                patch("api.server.detect_appliance_ip", return_value="192.168.1.199"),
            ):
                app = create_app(storage, MagicMock(), "http://localhost:9200")
            with open(saved) as f:
                on_disk = json.load(f)

        self.assertEqual(app["excluded_ips"], ["10.0.0.5", "192.168.1.199"])
        self.assertEqual(on_disk, ["10.0.0.5"])
