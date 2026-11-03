"""System health reports the machine's uptime, not the daemon's (dashboard accuracy #9)."""

from unittest.mock import mock_open, patch

from api.server import _host_uptime_seconds


def test_host_uptime_reads_proc_uptime():
    with patch("builtins.open", mock_open(read_data="6455.38 25000.10\n")):
        assert _host_uptime_seconds() == 6455.38


def test_host_uptime_none_when_unreadable():
    with patch("builtins.open", side_effect=OSError("no /proc")):
        assert _host_uptime_seconds() is None
