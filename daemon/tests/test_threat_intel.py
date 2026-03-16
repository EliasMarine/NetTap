"""Tests for ThreatIntelService."""

import json
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

        alerts = [{
            "source_ip": "192.168.1.10",
            "destination_ip": "203.0.113.50",
            "severity": 3,
            "severity_label": "MEDIUM",
            "assessment": "Network scanning activity.",
        }]

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

        alerts = [{
            "source_ip": "192.168.1.10",
            "destination_ip": "8.8.8.8",
            "severity": 3,
            "severity_label": "MEDIUM",
            "assessment": "DNS query observed.",
        }]

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
