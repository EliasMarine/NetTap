"""
IoT findings must not count local network chatter (G11 false findings, 2026-11-01).

Covers: ICMP type/code read as ports, DNS/DHCP to the gateway flagged as an
isolation risk, DNS/mDNS counted as unencrypted traffic, and the encryption
finding listed twice per device. OpenSearch is mocked; the fake routes each
query by its aggregation names so the tests don't depend on query order.
"""

import json
import os
import sys
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.excluded_ips import CONN_ACCOUNTING  # noqa: E402
from services.iot_monitor import IoTMonitor  # noqa: E402

FROM_TS = "2026-11-01T00:00:00Z"
TO_TS = "2026-11-01T12:00:00Z"
HUE_MAC = "EC:B5:FA:00:00:01"
ICMP_CLAUSE = {"terms": {"network.transport": ["icmp", "icmp6", "ipv6-icmp"]}}
MULTICAST_CLAUSE = {
    "terms": {"destination.ip": ["224.0.0.0/4", "ff00::/8", "255.255.255.255"]}
}
# the isolation query's (MAC, LAN host) composite source
PAIR_SOURCE = {"dest": {"terms": {"field": "destination.ip"}}}


def _empty() -> dict[str, Any]:
    return {"aggregations": {"by_mac": {"buckets": []}}}


def _fake_search(
    conn: list[dict] | None = None,
    ports: list[dict] | None = None,
    isolation: list[dict] | None = None,
):
    """Return a search() that answers each IoT query by its aggregation names."""

    def search(index: str, body: dict) -> dict[str, Any]:
        aggs = body.get("aggs", {})
        if PAIR_SOURCE in aggs.get("all", {}).get("composite", {}).get("sources", []):
            # #96: isolation pages (MAC, LAN host) pairs; one page, no after_key
            pairs = [
                {**dest, "key": {"mac": mac["key"], "dest": dest["key"]}}
                for mac in isolation or []
                for dest in mac["by_dest_ip"]["buckets"]
            ]
            return {"aggregations": {"all": {"buckets": pairs}}}
        sub = aggs.get("by_mac", {}).get("aggs", {})
        if "encrypted" in sub:
            return {"aggregations": {"by_mac": {"buckets": conn or []}}}
        if "ports" in sub:
            return {"aggregations": {"by_mac": {"buckets": ports or []}}}
        return _empty()

    return search


def _bodies(client: MagicMock) -> list[dict]:
    return [c.kwargs["body"] for c in client.search.call_args_list]


def _body_with_agg(client: MagicMock, agg_name: str) -> dict:
    for body in _bodies(client):
        aggs = body.get("aggs", {})
        if agg_name in aggs or agg_name in aggs.get("by_mac", {}).get("aggs", {}):
            return body
    raise AssertionError(f"no query with aggregation {agg_name!r}")


def _paged_body(client: MagicMock, source: dict) -> dict:
    """#96: the query whose composite aggregation pages over `source`."""
    for body in _bodies(client):
        sources = (
            body.get("aggs", {}).get("all", {}).get("composite", {}).get("sources", [])
        )
        if source in sources:
            return body
    raise AssertionError(f"no paged query over {source}")


def _port_counts_body(client: MagicMock) -> dict:
    return _paged_body(client, {"value": {"terms": {"field": "destination.port"}}})


def _isolation_body(client: MagicMock) -> dict:
    return _paged_body(client, PAIR_SOURCE)


def _must_not(body: dict) -> list[dict]:
    return body["query"]["bool"].get("must_not", [])


def _excluded_ports(body: dict) -> set[int]:
    for clause in _must_not(body):
        # a bare port clause, or one scoped by transport inside bool.filter
        for part in [clause, *clause.get("bool", {}).get("filter", [])]:
            ports = part.get("terms", {}).get("destination.port")
            if ports:
                return set(ports)
    return set()


def _dest_bucket(ip: str, total: int, ports: dict[int, int]) -> dict:
    """A by_dest_ip bucket; flows not counted in ports are ICMP."""
    return {
        "key": ip,
        "doc_count": total,
        "not_icmp": {
            "doc_count": sum(ports.values()),
            "ports": {
                "buckets": [{"key": k, "doc_count": v} for k, v in ports.items()]
            },
        },
        "source_ip": {"buckets": [{"key": "192.168.1.40"}]},
    }


@pytest.fixture
def client() -> MagicMock:
    return MagicMock()


@pytest.fixture
def iot(client: MagicMock) -> IoTMonitor:
    monitor = IoTMonitor(client=client)
    monitor._iot_devices = {
        HUE_MAC: {
            "mac": HUE_MAC,
            "manufacturer": "Philips Lighting BV",
            "hostname": None,
            "ip": "192.168.1.40",
            "classified_at": FROM_TS,
        }
    }
    # discovery rebuilds the set per range (NET-158); these tests set it themselves
    monitor._discover_iot_devices_from_arkime = lambda *a, **k: None
    return monitor


# ---------------------------------------------------------------------------
# 1. ICMP type/code is not a destination port
# ---------------------------------------------------------------------------


class TestIcmpIsNotAPort:
    def test_port_audit_query_skips_icmp(self, iot, client):
        client.search.side_effect = _fake_search()
        iot.get_protocol_audit(FROM_TS, TO_TS)
        assert ICMP_CLAUSE in _must_not(_port_counts_body(client))

    def test_trust_score_port_query_skips_icmp(self, iot, client):
        client.search.side_effect = _fake_search()
        iot.get_fleet_summary(FROM_TS, TO_TS)
        assert ICMP_CLAUSE in _must_not(_port_counts_body(client))

    def test_excluded_ips_are_still_applied(self, iot, client):
        client.search.side_effect = _fake_search()
        iot.get_protocol_audit(FROM_TS, TO_TS, excluded_ips=["192.168.1.2"])
        must_not = _must_not(_port_counts_body(client))
        assert {"terms": {"source.ip": ["192.168.1.2"]}} in must_not
        assert ICMP_CLAUSE in must_not

    def test_hardcoded_dns_check_still_sees_port_53(self, iot, client):
        """'Sends DNS queries directly to 9.9.9.9' is a real finding; keep it."""
        client.search.side_effect = _fake_search()
        iot.get_protocol_audit(FROM_TS, TO_TS)
        body = _body_with_agg(client, "dns_servers")
        assert {"term": {"destination.port": 53}} in body["query"]["bool"]["filter"]
        assert _excluded_ports(body) == set()


# ---------------------------------------------------------------------------
# 2. Expected LAN services are not an isolation risk
# ---------------------------------------------------------------------------


class TestIsolationIgnoresLanServices:
    def test_query_excludes_dns_dhcp_ntp_and_discovery(self, iot, client):
        client.search.side_effect = _fake_search()
        iot.get_network_isolation(FROM_TS, TO_TS)
        body = _isolation_body(client)
        excluded = _excluded_ports(body)
        assert {53, 67, 68, 123, 137, 138, 1900, 5353, 5355} <= excluded
        assert MULTICAST_CLAUSE in _must_not(body)

    def test_only_udp_on_service_ports_is_dropped(self, iot, client):
        # TCP 53/123 to a LAN host and ICMP sweeps are lateral-movement signals
        client.search.side_effect = _fake_search()
        iot.get_network_isolation(FROM_TS, TO_TS)
        must_not = _must_not(_isolation_body(client))
        assert ICMP_CLAUSE not in must_not
        assert not any(c.get("terms", {}).get("destination.port") for c in must_not)
        scoped = [c["bool"]["filter"] for c in must_not if "bool" in c]
        assert [{"term": {"network.transport": "udp"}}] == [f[0] for f in scoped]

    def test_ping_only_pair_is_low_risk(self, iot, client):
        client.search.side_effect = _fake_search(
            isolation=[
                {
                    "key": HUE_MAC,
                    "by_dest_ip": {"buckets": [_dest_bucket("192.168.1.1", 6, {})]},
                }
            ]
        )
        result = iot.get_network_isolation(FROM_TS, TO_TS)
        [pair] = result["pairs"]
        assert (pair["risk"], pair["ports"]) == ("low", [])
        assert pair["description"].endswith("via ping (ICMP)")
        assert result["segmentation_score"] == 100
        assert result["recommendation"].startswith("Only pings")

    def test_icmp_codes_never_appear_as_ports(self, iot, client):
        client.search.side_effect = _fake_search(
            isolation=[
                {
                    "key": HUE_MAC,
                    "by_dest_ip": {
                        "buckets": [_dest_bucket("192.168.1.20", 9, {445: 5})]
                    },
                }
            ]
        )
        [pair] = iot.get_network_isolation(FROM_TS, TO_TS)["pairs"]
        assert pair["ports"] == [445]
        assert pair["risk"] == "critical"
        assert pair["description"].endswith("via SMB, ping")

    def test_lateral_movement_ports_stay_in(self, iot, client):
        client.search.side_effect = _fake_search()
        iot.get_network_isolation(FROM_TS, TO_TS)
        excluded = _excluded_ports(_isolation_body(client))
        assert not excluded & {22, 23, 80, 139, 443, 445, 3389, 5900, 8080}

    def test_iot_to_lan_ssh_is_still_critical(self, iot, client):
        client.search.side_effect = _fake_search(
            isolation=[
                {
                    "key": HUE_MAC,
                    "by_dest_ip": {
                        "buckets": [_dest_bucket("192.168.1.20", 4, {22: 4})]
                    },
                }
            ]
        )
        result = iot.get_network_isolation(FROM_TS, TO_TS)
        assert [p["risk"] for p in result["pairs"]] == ["critical"]
        assert result["segmentation_score"] == 75


# ---------------------------------------------------------------------------
# 3. Encryption share covers only traffic where encryption is meaningful
# ---------------------------------------------------------------------------


class TestEncryptionShare:
    def test_conn_stats_query_excludes_local_chatter(self, iot, client):
        client.search.side_effect = _fake_search()
        iot.get_privacy_report(FROM_TS, TO_TS)
        body = _body_with_agg(client, "encrypted")
        must_not = _must_not(body)
        assert ICMP_CLAUSE in must_not
        assert MULTICAST_CLAUSE in must_not
        assert {53, 67, 68, 123, 137, 138, 1900, 5353, 5355} <= _excluded_ports(body)
        assert 80 not in _excluded_ports(body)

    def test_only_local_chatter_is_not_applicable(self, iot, client):
        """All traffic excluded -> no bucket: N/A, never 0% or a penalty."""
        client.search.side_effect = _fake_search(conn=[])
        privacy = iot.get_privacy_report(FROM_TS, TO_TS)["devices"][0]
        assert privacy["encryption_applicable"] is False
        # 1.0 keeps /iot from listing "has only 0% encrypted connections"
        assert privacy["encryption_ratio"] == 1.0

        fleet = iot.get_fleet_summary(FROM_TS, TO_TS)
        assert fleet["devices"][0]["encryption_applicable"] is False
        assert fleet["unencrypted_count"] == 0

    def test_not_applicable_is_unavailable_not_full_points(self, iot):
        """NET-158: no eligible traffic is no ratio; it used to earn the full 15 points."""
        stats = iot._build_device_stats(HUE_MAC, {}, {}, None, set())
        assert stats["encryption_applicable"] is False
        scored = iot._scorer.score_device(stats)
        assert scored["security_breakdown"]["encryption_ratio"] is None

    def test_relevant_traffic_still_measured(self, iot, client):
        conn = [
            {
                "key": HUE_MAC,
                "doc_count": 10,
                "total_bytes": {"value": 5000},
                "dest_ports": {"buckets": [{"key": 443, "doc_count": 9}]},
                "encrypted": {"doc_count": 9},
                "third_party_orgs": {"value": 1},
            }
        ]
        client.search.side_effect = _fake_search(conn=conn)
        privacy = iot.get_privacy_report(FROM_TS, TO_TS)["devices"][0]
        assert privacy["encryption_applicable"] is True
        assert privacy["encryption_ratio"] == 0.9

    def test_encrypted_means_tls_ports_or_zeek_encrypted_protocol(self, iot, client):
        """DNS-over-TLS on 853 and Zeek-identified TLS/SSH/QUIC count as encrypted."""
        client.search.side_effect = _fake_search()
        iot.get_privacy_report(FROM_TS, TO_TS)
        agg = _body_with_agg(client, "encrypted")["aggs"]["by_mac"]["aggs"]
        should = agg["encrypted"]["filter"]["bool"]["should"]
        ports = next(
            c["terms"]["destination.port"]
            for c in should
            if "terms" in c and "destination.port" in c["terms"]
        )
        protocols = next(
            c["terms"]["network.protocol"]
            for c in should
            if "network.protocol" in c.get("terms", {})
        )
        assert {443, 853, 8883} <= set(ports)
        assert {"ssl", "ssh", "quic"} <= set(protocols)

    def test_stun_only_device_is_not_applicable(self, iot, client):
        """192.168.1.149 on the G11: 591 STUN keepalives and nothing else read as 0%."""
        conn = [
            {
                "key": HUE_MAC,
                "doc_count": 591,
                "total_bytes": {"value": 60000},
                "dest_ports": {"buckets": [{"key": 19302, "doc_count": 591}]},
                "encrypted": {"doc_count": 0},
                "no_payload": {"doc_count": 591},
                "third_party_orgs": {"value": 1},
            }
        ]
        client.search.side_effect = _fake_search(conn=conn)
        privacy = iot.get_privacy_report(FROM_TS, TO_TS)["devices"][0]
        assert privacy["encryption_applicable"] is False
        assert privacy["encryption_ratio"] == 1.0


# ---------------------------------------------------------------------------
# 3b. Connection stats count connection records, not alerts or DNS/SSL logs
# ---------------------------------------------------------------------------


class TestConnectionRecordsOnly:
    # OLD CODE: CONN_ONLY = {"term": {"event.dataset": "conn"}} (F1: final records only)
    CONN_ONLY = CONN_ACCOUNTING

    def test_connection_queries_skip_alerts_and_other_logs(self, iot, client):
        """An ESP device read 1% encrypted: 162 alert records + 2 TLS connections."""
        client.search.side_effect = _fake_search()
        iot.get_privacy_report(FROM_TS, TO_TS)
        iot.get_protocol_audit(FROM_TS, TO_TS)
        iot.get_network_isolation(FROM_TS, TO_TS)
        bodies = [
            _body_with_agg(client, "encrypted"),
            _port_counts_body(client),
            _isolation_body(client),
        ]
        for body in bodies:
            assert self.CONN_ONLY in body["query"]["bool"]["filter"]

    def test_arkime_sessions_are_not_counted_twice(self, iot, client):
        """Arkime sessions (no event.dataset) duplicate Zeek conn flows."""
        client.search.side_effect = _fake_search()
        iot.get_privacy_report(FROM_TS, TO_TS)
        # OLD CODE START — F1: CONN_ACCOUNTING's must_not drops conn_long.log, not Arkime sessions
        # assert "must_not" not in json.dumps(
        #     [
        #         f
        #         for f in _body_with_agg(client, "encrypted")["query"]["bool"]["filter"]
        #         if "bool" in f
        #     ]
        # )
        # OLD CODE END
        # The old clause matched Arkime sessions by a missing event.dataset
        assert '"exists": {"field": "event.dataset"}' not in json.dumps(
            _body_with_agg(client, "encrypted")["query"]["bool"]["filter"]
        )


# ---------------------------------------------------------------------------
# 4. One finding per fact
# ---------------------------------------------------------------------------


class TestNoDuplicateEncryptionFinding:
    def test_protocol_audit_leaves_encryption_to_privacy_report(self, iot, client):
        """194 of 194 unencrypted was listed by both the audit and the privacy feed."""
        conn = [
            {
                "key": HUE_MAC,
                "doc_count": 194,
                "total_bytes": {"value": 1000},
                "dest_ports": {"buckets": [{"key": 80, "doc_count": 194}]},
                "encrypted": {"doc_count": 0},
                "third_party_orgs": {"value": 1},
            }
        ]
        client.search.side_effect = _fake_search(conn=conn)

        audit = iot.get_protocol_audit(FROM_TS, TO_TS)["devices"][0]
        assert [f for f in audit["findings"] if "encrypt" in f["description"]] == []

        # The privacy report is now the single source the /iot feed reads
        privacy = iot.get_privacy_report(FROM_TS, TO_TS)["devices"][0]
        assert privacy["encryption_ratio"] == 0.0


def test_fleet_alert_counts_leave_out_suricata_engine_events():
    """#82: engine events (rule.name "SURICATA ...") counted as IoT device alerts.

    On the G11 three IoT devices showed 521, 220 and 15 alerts in 24 h, all engine events.
    """
    client = MagicMock()
    client.search.return_value = _empty()
    monitor = IoTMonitor(client=client)

    monitor._query_alert_counts(
        [HUE_MAC], FROM_TS, TO_TS, [{"terms": {"source.ip": ["10.0.0.9"]}}]
    )

    must_not = _bodies(client)[0]["query"]["bool"]["must_not"]
    assert {"prefix": {"rule.name": "SURICATA "}} in must_not
    assert {"terms": {"source.ip": ["10.0.0.9"]}} in must_not
