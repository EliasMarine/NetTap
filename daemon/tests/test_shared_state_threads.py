"""PR 2 (reliability): files and caches that request threads share stay whole.

Handlers now run in worker threads, so a reader can meet a writer mid-file and two
read-modify-writes can interleave. The saves go through a temp file + os.replace and each
read-modify-write holds its module's lock.
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


def test_suppress_writes_from_many_threads_all_land(tmp_path, monkeypatch):
    monkeypatch.setattr(alert_intelligence, "_SUPPRESS_PATH", tmp_path / "s.json")
    threads = [
        threading.Thread(target=alert_intelligence.suppress_rule, args=(sig,))
        for sig in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ids = {e["signature_id"] for e in alert_intelligence.load_suppress_list()["global"]}
    assert ids == set(range(20))


def test_threat_intel_transactions_never_interleave(tmp_path, monkeypatch):
    """Load -> populate -> save runs whole, against another request and the drill-down."""
    monkeypatch.setattr(threat_intel, "_TI_CACHE_PATH", tmp_path / "ti.json")
    events: list[tuple[int, str]] = []

    def load(self):
        events.append((id(self), "load"))
        time.sleep(0.02)

    def populate(self, *_args, **_kwargs):
        events.append((id(self), "populate"))
        time.sleep(0.05)
        events.append((id(self), "saved"))
        self.seen_in_window = set()
        return 0

    monkeypatch.setattr(threat_intel.ThreatIntelService, "load_cache", load)
    monkeypatch.setattr(
        threat_intel.ThreatIntelService, "populate_from_suricata", populate
    )
    request = MagicMock()
    request.query = {}
    request.app = {"storage": MagicMock(), "excluded_ips": []}

    threads = [
        threading.Thread(target=lambda: asyncio.run(handle_threat_intel(request)))
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
        if step == "populate":
            # the same request loaded just before and saves just after: nobody in between
            assert events[i - 1] == (owner, "load")
            assert events[i + 1] == (owner, "saved")
