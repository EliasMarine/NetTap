"""Tests for ThreatIntelService."""

import json
from unittest.mock import MagicMock

import pytest

from services.threat_intel import ThreatIntelService


class TestThreatIntelLookup:
    """Tests for IP lookup against loaded feeds."""

    def test_lookup_ip_hit(self):
        """add indicator, lookup returns match."""
        svc = ThreatIntelService()
        svc.add_indicators("abuse_ch_feodo", ["198.51.100.5"])
        hits = svc.lookup_ip("198.51.100.5")
        assert len(hits) == 1
        assert hits[0]["feed"] == "abuse_ch_feodo"
        assert hits[0]["indicator"] == "198.51.100.5"
        assert hits[0]["label"] == "Abuse.ch Feodo (Banking Trojans/C2)"

    def test_lookup_ip_miss(self):
        """lookup unknown IP returns empty."""
        svc = ThreatIntelService()
        svc.add_indicators("abuse_ch_feodo", ["198.51.100.5"])
        hits = svc.lookup_ip("192.168.1.1")
        assert hits == []

    def test_populate_and_lookup(self):
        """add_indicators + lookup roundtrip across multiple feeds."""
        svc = ThreatIntelService()
        svc.add_indicators("et_compromised", ["10.0.0.1", "10.0.0.2"])
        svc.add_indicators("dshield_block", ["10.0.0.2", "10.0.0.3"])

        # IP in both feeds returns two hits
        hits = svc.lookup_ip("10.0.0.2")
        assert len(hits) == 2
        feeds = {h["feed"] for h in hits}
        assert feeds == {"et_compromised", "dshield_block"}

        # IP in one feed returns one hit
        hits = svc.lookup_ip("10.0.0.1")
        assert len(hits) == 1
        assert hits[0]["feed"] == "et_compromised"

        # IP in no feed returns empty
        assert svc.lookup_ip("10.0.0.99") == []


class TestEnrichAlerts:
    """Tests for alert enrichment with TI data."""

    def test_enrich_alerts_boosts_severity(self):
        """alert with dst in feed gets severity bumped."""
        svc = ThreatIntelService()
        svc.add_indicators("abuse_ch_feodo", ["203.0.113.50"])

        alerts = [
            {
                "source_ip": "192.168.1.10",
                "destination_ip": "203.0.113.50",
                "severity": 3,
                "severity_label": "MEDIUM",
                "assessment": "Network scanning activity.",
            }
        ]

        enriched = svc.enrich_alerts(alerts)
        assert len(enriched) == 1
        alert = enriched[0]
        assert alert["ti_matched"] is True
        assert alert["severity"] == 2  # bumped from 3 to 2
        assert alert["severity_label"] == "HIGH"
        assert "confirmed malicious infrastructure" in alert["assessment"]

    def test_enrich_alerts_no_match(self):
        """alert with clean IPs stays unchanged."""
        svc = ThreatIntelService()
        svc.add_indicators("abuse_ch_feodo", ["203.0.113.50"])

        alerts = [
            {
                "source_ip": "192.168.1.10",
                "destination_ip": "8.8.8.8",
                "severity": 3,
                "severity_label": "MEDIUM",
                "assessment": "DNS query observed.",
            }
        ]

        enriched = svc.enrich_alerts(alerts)
        assert len(enriched) == 1
        alert = enriched[0]
        assert alert["ti_matched"] is False
        assert alert["severity"] == 3  # unchanged
        assert alert["severity_label"] == "MEDIUM"
        assert "confirmed malicious" not in alert["assessment"]


class TestCachePersistence:
    """Tests for save/load cache roundtrip."""

    def test_save_and_load_cache(self, tmp_path, monkeypatch):
        """save to disk, reload, verify data persists."""
        cache_path = tmp_path / "nettap-threat-intel.json"
        monkeypatch.setattr("services.threat_intel._TI_CACHE_PATH", cache_path)

        # Save
        svc1 = ThreatIntelService()
        svc1.add_indicators("et_compromised", ["10.0.0.1", "10.0.0.2"])
        svc1.add_indicators("dshield_block", ["172.16.0.1"])
        svc1.save_cache()

        assert cache_path.exists()
        raw = json.loads(cache_path.read_text())
        assert "ip_feeds" in raw
        assert "updated_at" in raw

        # Load into a fresh instance
        svc2 = ThreatIntelService()
        svc2.load_cache()
        assert svc2._loaded is True

        # Verify data roundtripped
        hits = svc2.lookup_ip("10.0.0.1")
        assert len(hits) == 1
        assert hits[0]["feed"] == "et_compromised"

        hits = svc2.lookup_ip("172.16.0.1")
        assert len(hits) == 1
        assert hits[0]["feed"] == "dshield_block"

        # Non-existent IP still misses
        assert svc2.lookup_ip("99.99.99.99") == []


class _AlertIndex:
    """Alert counts per destination IP, answered the way OpenSearch does: a terms list keeps
    its top `size` IPs, a composite pages every IP."""

    def __init__(self, counts: dict[str, int]):
        self.counts = counts

    def search(self, index: str, body: dict) -> dict:
        ((name, agg),) = body["aggs"].items()
        if "composite" in agg:
            if "after" in agg["composite"]:
                return {"aggregations": {name: {"buckets": []}}}
            buckets = [
                {"key": {"ip": ip}, "doc_count": n}
                for ip, n in sorted(self.counts.items())
            ]
            return {
                "aggregations": {
                    name: {"buckets": buckets, "after_key": buckets[-1]["key"]}
                }
            }
        top = sorted(self.counts.items(), key=lambda kv: kv[1], reverse=True)[
            : agg["terms"]["size"]
        ]
        return {
            "aggregations": {
                name: {"buckets": [{"key": ip, "doc_count": n} for ip, n in top]}
            }
        }


class TestPopulateFromSuricata:
    """#96: indicators come from every alerted IP, and only unknown ones count as new."""

    def test_every_alerted_ip_becomes_an_indicator(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "services.threat_intel._TI_CACHE_PATH", tmp_path / "ti.json"
        )
        counts = {f"198.51.{i // 250}.{i % 250}": 10 for i in range(500)}
        index = _AlertIndex({**counts, "203.0.113.9": 1})
        svc = ThreatIntelService()

        assert svc.populate_from_suricata(index, "now-1d", "now") == 501
        assert svc.lookup_ip("203.0.113.9")  # the 501st, least-alerted IP

    def test_new_indicators_counts_only_unknown_ips(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "services.threat_intel._TI_CACHE_PATH", tmp_path / "ti.json"
        )
        index = _AlertIndex({"203.0.113.1": 5, "203.0.113.2": 3})
        svc = ThreatIntelService()
        svc.add_indicators("et_compromised", ["203.0.113.1"])

        assert svc.populate_from_suricata(index, "now-1d", "now") == 1
        assert svc.populate_from_suricata(index, "now-1d", "now") == 0

    def test_failed_alert_scan_raises(self, tmp_path, monkeypatch):
        """#96: 0 new indicators read as "nothing new" when the alerts were never read."""
        monkeypatch.setattr(
            "services.threat_intel._TI_CACHE_PATH", tmp_path / "ti.json"
        )
        client = MagicMock()
        client.search.side_effect = Exception("Connection refused")

        with pytest.raises(Exception, match="Connection refused"):
            ThreatIntelService().populate_from_suricata(client, "now-1d", "now")


@pytest.mark.asyncio
async def test_intel_endpoint_answers_500_when_the_alert_scan_fails(
    tmp_path, monkeypatch
):
    """#96: GET /api/threats/intel must not report 0 new indicators for a scan that never ran."""
    from aiohttp import web
    from aiohttp.test_utils import make_mocked_request

    from api.threats import handle_threat_intel

    monkeypatch.setattr("services.threat_intel._TI_CACHE_PATH", tmp_path / "ti.json")
    storage = MagicMock()
    storage._client.search.side_effect = Exception("Connection refused")
    app = web.Application()
    app["storage"] = storage

    resp = await handle_threat_intel(
        make_mocked_request("GET", "/api/threats/intel", app=app)
    )
    assert resp.status == 500
    assert "error" in json.loads(resp.text)
