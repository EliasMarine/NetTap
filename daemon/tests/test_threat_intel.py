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


# OLD CODE START — NET-228: enrich_alerts is retired (no caller; it called a list hit confirmed)
# class TestEnrichAlerts:
#     """Tests for alert enrichment with TI data."""
#
#     def test_enrich_alerts_boosts_severity(self):
#         """alert with dst in feed gets severity bumped."""
#         svc = ThreatIntelService()
#         svc.add_indicators("abuse_ch_feodo", ["203.0.113.50"])
#
#         alerts = [
#             {
#                 "source_ip": "192.168.1.10",
#                 "destination_ip": "203.0.113.50",
#                 "severity": 3,
#                 "severity_label": "MEDIUM",
#                 "assessment": "Network scanning activity.",
#             }
#         ]
#
#         enriched = svc.enrich_alerts(alerts)
#         assert len(enriched) == 1
#         alert = enriched[0]
#         assert alert["ti_matched"] is True
#         assert alert["severity"] == 2  # bumped from 3 to 2
#         assert alert["severity_label"] == "HIGH"
#         assert "confirmed malicious infrastructure" in alert["assessment"]
#
#     def test_enrich_alerts_no_match(self):
#         """alert with clean IPs stays unchanged."""
#         svc = ThreatIntelService()
#         svc.add_indicators("abuse_ch_feodo", ["203.0.113.50"])
#
#         alerts = [
#             {
#                 "source_ip": "192.168.1.10",
#                 "destination_ip": "8.8.8.8",
#                 "severity": 3,
#                 "severity_label": "MEDIUM",
#                 "assessment": "DNS query observed.",
#             }
#         ]
#
#         enriched = svc.enrich_alerts(alerts)
#         assert len(enriched) == 1
#         alert = enriched[0]
#         assert alert["ti_matched"] is False
#         assert alert["severity"] == 3  # unchanged
#         assert alert["severity_label"] == "MEDIUM"
#         assert "confirmed malicious" not in alert["assessment"]
# OLD CODE END


def test_the_feed_nettap_fills_is_named_for_its_rules():
    """NET-228: it holds addresses Suricata's blocklist rules named, not ET's Compromised list."""
    from services.threat_intel import TI_FEEDS

    assert TI_FEEDS["et_compromised"]["label"] == "Suricata blocklist rules"
    assert not hasattr(ThreatIntelService, "enrich_alerts")


class TestCachePersistence:
    """Tests for save/load cache roundtrip."""

    def test_save_and_load_cache(self, tmp_path, monkeypatch):
        """save to disk, reload, verify data persists."""
        cache_path = tmp_path / "nettap-threat-intel.json"
        monkeypatch.setattr("services.threat_intel._TI_CACHE_PATH", cache_path)

        # Save
        # OLD CODE START — I7: private addresses are never indicators now, and load drops them
        # svc1 = ThreatIntelService()
        # svc1.add_indicators("et_compromised", ["10.0.0.1", "10.0.0.2"])
        # svc1.add_indicators("dshield_block", ["172.16.0.1"])
        # svc1.save_cache()
        # OLD CODE END
        svc1 = ThreatIntelService()
        svc1.add_indicators("et_compromised", ["45.33.32.1", "45.33.32.2"])
        svc1.add_indicators("dshield_block", ["185.220.101.1"])
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
        hits = svc2.lookup_ip("45.33.32.1")
        assert len(hits) == 1
        assert hits[0]["feed"] == "et_compromised"

        hits = svc2.lookup_ip("185.220.101.1")
        assert len(hits) == 1
        assert hits[0]["feed"] == "dshield_block"

        # Non-existent IP still misses
        assert svc2.lookup_ip("99.99.99.99") == []


_LAN = "192.168.1.10"


class _AlertIndex:
    """Alert counts per listed IP (each alert from it to a LAN device) or per (source,
    destination) pair, answered the way OpenSearch does: a terms list keeps its top `size`
    IPs, a composite pages every key."""

    def __init__(self, counts: dict):
        self.counts = counts
        self.pairs = {
            (k if isinstance(k, tuple) else (k, _LAN)): n for k, n in counts.items()
        }

    def search(self, index: str, body: dict) -> dict:
        ((name, agg),) = body["aggs"].items()
        if "composite" in agg:
            if "after" in agg["composite"]:
                return {"aggregations": {name: {"buckets": []}}}
            names = [next(iter(src)) for src in agg["composite"]["sources"]]
            if names == ["src", "dst"]:  # I7: both endpoints of every alert
                buckets = [
                    {"key": {"src": src, "dst": dst}, "doc_count": n}
                    for (src, dst), n in sorted(self.pairs.items())
                ]
                return {
                    "aggregations": {
                        name: {"buckets": buckets, "after_key": buckets[-1]["key"]}
                    }
                }
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
        # OLD CODE START — I7: documentation ranges (203.0.113.0/24) aren't internet addresses
        # counts = {f"198.51.{i // 250}.{i % 250}": 10 for i in range(500)}
        # index = _AlertIndex({**counts, "203.0.113.9": 1})
        # svc = ThreatIntelService()
        #
        # assert svc.populate_from_suricata(index, "now-1d", "now") == 501
        # assert svc.lookup_ip("203.0.113.9")  # the 501st, least-alerted IP
        # OLD CODE END
        counts = {f"45.33.{i // 250}.{i % 250}": 10 for i in range(500)}
        index = _AlertIndex({**counts, "185.220.101.9": 1})
        svc = ThreatIntelService()

        assert svc.populate_from_suricata(index, "now-1d", "now") == 501
        assert svc.lookup_ip("185.220.101.9")  # the 501st, least-alerted IP

    def test_new_indicators_counts_only_unknown_ips(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "services.threat_intel._TI_CACHE_PATH", tmp_path / "ti.json"
        )
        # OLD CODE START — I7: documentation ranges aren't internet addresses
        # index = _AlertIndex({"203.0.113.1": 5, "203.0.113.2": 3})
        # svc = ThreatIntelService()
        # svc.add_indicators("et_compromised", ["203.0.113.1"])
        # OLD CODE END
        index = _AlertIndex({"185.220.101.1": 5, "185.220.101.2": 3})
        svc = ThreatIntelService()
        svc.add_indicators("et_compromised", ["185.220.101.1"])

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


# ---------------------------------------------------------------------------
# I7 (accuracy audit 2026-11-06): indicator integrity
# ---------------------------------------------------------------------------


class TestIndicatorIntegrity:
    """Inbound rules (listed host -> this network) taught the old code the network's own
    addresses, and an alert to one then read "confirmed malicious infrastructure"."""

    def test_learns_the_internet_endpoint_never_a_lan_one(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "services.threat_intel._TI_CACHE_PATH", tmp_path / "ti.json"
        )
        index = _AlertIndex(
            {
                ("185.220.101.9", _LAN): 4,  # inbound: the listed host is the source
                ("192.168.1.20", "45.33.32.156"): 2,  # outbound: the destination
            }
        )
        svc = ThreatIntelService()

        assert svc.populate_from_suricata(index, "now-1d", "now") == 2
        assert svc.lookup_ip("185.220.101.9") and svc.lookup_ip("45.33.32.156")
        assert svc.lookup_ip(_LAN) == [] and svc.lookup_ip("192.168.1.20") == []

    def test_ambiguous_alerts_teach_nothing(self, tmp_path, monkeypatch):
        """Two internet endpoints (an inbound alert to this network's public address) or
        none: the listed host can't be told apart, so neither side is learned."""
        monkeypatch.setattr(
            "services.threat_intel._TI_CACHE_PATH", tmp_path / "ti.json"
        )
        index = _AlertIndex(
            {("185.220.101.9", "81.2.69.142"): 3, ("192.168.1.5", "10.0.0.1"): 1}
        )
        svc = ThreatIntelService()

        assert svc.populate_from_suricata(index, "now-1d", "now") == 0
        assert svc.lookup_ip("81.2.69.142") == []
        assert svc.seen_in_window == set()

    def test_a_poisoned_cache_is_cleaned_and_confirms_nothing(
        self, tmp_path, monkeypatch
    ):
        cache = tmp_path / "ti.json"
        monkeypatch.setattr("services.threat_intel._TI_CACHE_PATH", cache)
        # what the old code wrote: no version, the LAN address learned from an inbound rule
        cache.write_text(
            json.dumps({"ip_feeds": {"et_compromised": [_LAN, "81.2.69.142"]}})
        )
        svc = ThreatIntelService()
        svc.load_cache()

        assert svc.lookup_ip(_LAN) == []
        assert svc.lookup_ip("81.2.69.142") == []  # can't tell it from an own address
        # OLD CODE START — NET-228: enrich_alerts is retired
        # alert = {
        #     "source_ip": "185.220.101.9",
        #     "destination_ip": _LAN,
        #     "severity": 3,
        #     "severity_label": "MEDIUM",
        #     "assessment": "",
        # }
        # (enriched,) = svc.enrich_alerts([alert])
        # assert enriched["ti_matched"] is False
        # assert "confirmed malicious infrastructure" not in enriched["assessment"]
        # OLD CODE END
        written = json.loads(cache.read_text())
        assert not any(
            written["ip_feeds"].values()
        )  # the old entries are gone from disk

    def test_a_current_cache_keeps_only_internet_addresses(self, tmp_path, monkeypatch):
        cache = tmp_path / "ti.json"
        monkeypatch.setattr("services.threat_intel._TI_CACHE_PATH", cache)
        cache.write_text(
            json.dumps(
                {
                    "version": 2,
                    "ip_feeds": {"et_compromised": ["10.1.2.3", "185.220.101.9"]},
                }
            )
        )
        svc = ThreatIntelService()
        svc.load_cache()

        assert svc.lookup_ip("185.220.101.9")
        assert svc.lookup_ip("10.1.2.3") == []
        assert json.loads(cache.read_text())["ip_feeds"] == {
            "et_compromised": ["185.220.101.9"]
        }


def _intel_request(client):
    from aiohttp import web
    from aiohttp.test_utils import make_mocked_request

    storage = MagicMock()
    storage._client = client
    app = web.Application()
    app["storage"] = storage
    return make_mocked_request("GET", "/api/threats/intel", app=app)


@pytest.mark.asyncio
async def test_rebuild_failure_leaves_an_empty_cache_and_says_unavailable(
    tmp_path, monkeypatch
):
    """I7 rollback: the purge is written before the rebuild, so a failed rebuild never
    brings the old entries back; the page shows threat intel as unavailable (an error)."""
    from api.threats import handle_threat_intel

    cache = tmp_path / "ti.json"
    monkeypatch.setattr("services.threat_intel._TI_CACHE_PATH", cache)
    cache.write_text(json.dumps({"ip_feeds": {"et_compromised": [_LAN]}}))
    client = MagicMock()
    client.search.side_effect = Exception("Connection refused")

    resp = await handle_threat_intel(_intel_request(client))

    assert resp.status == 500
    assert not any(json.loads(cache.read_text())["ip_feeds"].values())


@pytest.mark.asyncio
async def test_intel_counts_only_indicators_seen_in_the_window(tmp_path, monkeypatch):
    """I7: the card counted every indicator ever cached under the window's label."""
    from api.threats import handle_threat_intel

    cache = tmp_path / "ti.json"
    monkeypatch.setattr("services.threat_intel._TI_CACHE_PATH", cache)
    old = ["45.33.32.1", "45.33.32.2", "45.33.32.3"]
    cache.write_text(json.dumps({"version": 2, "ip_feeds": {"et_compromised": old}}))

    resp = await handle_threat_intel(
        _intel_request(_AlertIndex({"45.33.32.1": 2, "185.220.101.9": 1}))
    )
    body = json.loads(resp.text)

    assert body["total_indicators"] == 2
    assert body["feeds"]["et_compromised"]["indicator_count"] == 2
    assert body["new_indicators"] == 1


class TestAvailability:
    """NET-160: the address page says "not checked" until an indicator exists, not "no match"."""

    def test_no_cache_file_is_unavailable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "services.threat_intel._TI_CACHE_PATH", tmp_path / "ti.json"
        )
        svc = ThreatIntelService()
        svc.load_cache()
        assert (svc.available, svc.indicator_count) == (False, 0)

    def test_a_read_cache_with_no_indicators_is_still_unavailable(
        self, tmp_path, monkeypatch
    ):
        cache = tmp_path / "ti.json"
        cache.write_text(json.dumps({"version": 2, "ip_feeds": {"et_compromised": []}}))
        monkeypatch.setattr("services.threat_intel._TI_CACHE_PATH", cache)
        svc = ThreatIntelService()
        svc.load_cache()
        assert svc._loaded and not svc.available

    def test_added_indicators_are_available_at_once_without_a_reload(self):
        svc = ThreatIntelService()
        svc.add_indicators("et_compromised", ["198.51.100.5", "198.51.100.6"])
        assert (svc.available, svc.indicator_count) == (True, 2)
        assert svc.lookup_ip("198.51.100.5")[0]["feed"] == "et_compromised"


# ---------------------------------------------------------------------------
# NET-238: a capped scan checks the alert pairs it read and says it stopped
# ---------------------------------------------------------------------------

# OLD CODE START — NET-238: a capped scan was an error (NET-237), so enough alerts blanked
# the matches; it now answers what it read with complete=False
# @pytest.mark.asyncio
# async def test_intel_endpoint_answers_500_when_the_scan_hits_its_cap(
#     tmp_path, monkeypatch
# ):
#     """The cap was only logged, so the window's matches were those read before it."""
#     from aiohttp import web
#     from aiohttp.test_utils import make_mocked_request
#
#     from api.threats import handle_threat_intel
#
#     monkeypatch.setattr("services.threat_intel._TI_CACHE_PATH", tmp_path / "ti.json")
#     monkeypatch.setattr(
#         "services.threat_intel.all_buckets",
#         lambda *a, **k: ([{"key": {"src": "185.220.101.9", "dst": _LAN}}], False),
#     )
#     app = web.Application()
#     app["storage"] = MagicMock()
#
#     resp = await handle_threat_intel(
#         make_mocked_request("GET", "/api/threats/intel", app=app)
#     )
#
#     assert resp.status == 500
# OLD CODE END


def _scan_reads_one_pair(monkeypatch, complete: bool) -> None:
    monkeypatch.setattr(
        "services.threat_intel.all_buckets",
        lambda *a, **k: ([{"key": {"src": "185.220.101.9", "dst": _LAN}}], complete),
    )


@pytest.mark.parametrize("complete", [True, False])
def test_the_pairs_read_are_matched_and_merged(tmp_path, monkeypatch, caplog, complete):
    monkeypatch.setattr("services.threat_intel._TI_CACHE_PATH", tmp_path / "ti.json")
    _scan_reads_one_pair(monkeypatch, complete)
    svc = ThreatIntelService()

    assert svc.scan_suricata(MagicMock(), "now-1d", "now") == (
        {"185.220.101.9"},
        complete,
    )
    assert svc.populate_from_suricata(MagicMock(), "now-1d", "now") == 1
    assert svc.lookup_ip("185.220.101.9")
    assert ("stopped at 1 address pairs" in caplog.text) is not complete


@pytest.mark.asyncio
@pytest.mark.parametrize("complete", [True, False])
async def test_intel_endpoint_says_whether_the_scan_was_capped(
    tmp_path, monkeypatch, complete
):
    from aiohttp import web
    from aiohttp.test_utils import make_mocked_request

    from api.threats import handle_threat_intel

    monkeypatch.setattr("services.threat_intel._TI_CACHE_PATH", tmp_path / "ti.json")
    _scan_reads_one_pair(monkeypatch, complete)
    app = web.Application()
    app["storage"] = MagicMock()

    resp = await handle_threat_intel(
        make_mocked_request("GET", "/api/threats/intel", app=app)
    )

    body = json.loads(resp.text)
    assert resp.status == 200
    assert (body["complete"], body["total_indicators"]) == (complete, 1)
