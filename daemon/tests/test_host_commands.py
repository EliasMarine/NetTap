"""Host network commands run directly, never through nsenter.

Ubuntu's docker-default AppArmor profile denies nsenter's ptrace read of PID 1,
so every ``nsenter -t 1 -n`` call failed on the G11 trial box (2026-11-01).
The daemon container uses network_mode: host, so the commands run as-is.
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.bridge_health import BridgeHealthMonitor  # noqa: E402
from services.bridge_manager import BridgeManager  # noqa: E402
from services.dhcp_gateway_host import HostNetOps  # noqa: E402
from services.mirror_manager import MirrorManager  # noqa: E402

HELPERS = [
    MirrorManager(interface="enp4s0"),
    BridgeManager(),
    BridgeHealthMonitor(),
    HostNetOps(),
]


class TestHostCommandsRunDirectly(unittest.TestCase):
    def test_no_helper_wraps_commands_in_nsenter(self):
        for helper in HELPERS:
            with self.subTest(helper=type(helper).__name__):
                proc = AsyncMock()
                proc.communicate = AsyncMock(return_value=(b"out", b""))
                proc.returncode = 0
                with patch("asyncio.create_subprocess_exec", return_value=proc) as ex:
                    result = asyncio.run(
                        helper._run_nsenter("ip", "link", "set", "enp4s0", "up")
                    )
                self.assertEqual(
                    ex.call_args.args, ("ip", "link", "set", "enp4s0", "up")
                )
                self.assertEqual(result, (0, "out", ""))

    def test_missing_binary_names_the_command(self):
        for helper in HELPERS:
            with self.subTest(helper=type(helper).__name__):
                with patch(
                    "asyncio.create_subprocess_exec", side_effect=FileNotFoundError
                ):
                    rc, _, err = asyncio.run(helper._run_nsenter("ethtool", "-K"))
                self.assertEqual((rc, err), (1, "ethtool not found"))


if __name__ == "__main__":
    unittest.main()
