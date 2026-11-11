"""PR 2 (reliability): files and caches that request threads share stay whole.

Handlers now run in worker threads, so a reader can meet a writer mid-file and two
read-modify-writes can interleave. The saves go through a temp file + os.replace, and the
threat-intel cache's load -> merge -> save holds its lock.
"""

import asyncio
import json
import os
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from api import alerts as alerts_api
from api.addresses import threat_intel as address_threat_intel
from api.threats import handle_threat_intel
from services import alert_intelligence, threat_intel


def test_a_failed_write_leaves_the_old_file_whole(tmp_path):
    path = tmp_path / "alert_acks.json"
    alerts_api._save_acks({"a": {"acknowledged_by": "admin"}}, str(path))

    # The new content is written to the temp file, then the disk fails before the swap
    with patch("services.capture_config.os.fsync", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            alerts_api._save_acks({"b": {}}, str(path))

    assert json.loads(path.read_text()) == {"a": {"acknowledged_by": "admin"}}
    assert os.listdir(tmp_path) == ["alert_acks.json"]  # no temp file left behind


def test_a_failed_suppress_save_keeps_the_list(tmp_path, monkeypatch):
    monkeypatch.setattr(alert_intelligence, "_SUPPRESS_PATH", tmp_path / "s.json")
    alert_intelligence.suppress_rule(1)

    with patch("services.capture_config.os.fsync", side_effect=OSError("disk full")):
        alert_intelligence.suppress_rule(2)  # logged, not raised

    ids = [e["signature_id"] for e in alert_intelligence.load_suppress_list()["global"]]
    assert ids == [1]


def _intel_request() -> MagicMock:
    request = MagicMock()
    request.query = {}
    request.app = {"storage": MagicMock(), "excluded_ips": []}
    return request


def test_threat_intel_transactions_never_interleave(tmp_path, monkeypatch):
    """Load -> merge -> save runs whole, against another request and the drill-down."""
    monkeypatch.setattr(threat_intel, "_TI_CACHE_PATH", tmp_path / "ti.json")
    events: list[tuple[int, str]] = []

    def load(self):
        events.append((id(self), "load"))
        time.sleep(0.02)

    def merge(self, _seen):
        events.append((id(self), "merge"))
        time.sleep(0.05)
        events.append((id(self), "saved"))
        return 0

    monkeypatch.setattr(threat_intel.ThreatIntelService, "load_cache", load)
    # OLD CODE: monkeypatch.setattr(threat_intel.ThreatIntelService, "scan_suricata", MagicMock())
    # (NET-238: the scan returns (seen, complete))
    monkeypatch.setattr(
        threat_intel.ThreatIntelService,
        "scan_suricata",
        MagicMock(return_value=(set(), True)),
    )
    monkeypatch.setattr(threat_intel.ThreatIntelService, "merge_seen", merge)

    threads = [
        threading.Thread(
            target=lambda: asyncio.run(handle_threat_intel(_intel_request()))
        )
        for _ in range(2)
    ] + [
        threading.Thread(target=address_threat_intel, args=("203.0.113.9", None))
        for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(events) == 2 * 3 + 2
    for i, (owner, step) in enumerate(events):
        if step == "merge":
            # the same request loaded just before and saves just after: nobody in between
            assert events[i - 1] == (owner, "load")
            assert events[i + 1] == (owner, "saved")


def test_the_drill_down_never_waits_for_a_threat_intel_scan(tmp_path, monkeypatch):
    """PR 2 review: the scan (up to 30 s a page) ran under the lock the drill-down needs."""
    monkeypatch.setattr(threat_intel, "_TI_CACHE_PATH", tmp_path / "ti.json")
    scanning, release = threading.Event(), threading.Event()

    def scan(self, *_args, **_kwargs):
        scanning.set()
        release.wait(5)
        # OLD CODE: return set() (NET-238: the scan returns (seen, complete))
        return set(), True

    monkeypatch.setattr(threat_intel.ThreatIntelService, "scan_suricata", scan)
    refresh = threading.Thread(
        target=lambda: asyncio.run(handle_threat_intel(_intel_request()))
    )
    refresh.start()
    try:
        assert scanning.wait(5)
        drill_down = threading.Thread(
            target=address_threat_intel, args=("203.0.113.9", None)
        )
        drill_down.start()
        drill_down.join(1)
        assert not drill_down.is_alive(), "the drill-down waited for the scan"
    finally:
        release.set()
        refresh.join(5)
