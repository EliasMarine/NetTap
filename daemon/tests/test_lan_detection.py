"""LAN subnet auto-detection keeps every real subnet, not just the busiest ones (#47)."""

from unittest.mock import MagicMock

from services.excluded_ips import detect_lan_subnets


def _client(per_ip: dict[str, int]) -> MagicMock:
    """OpenSearch mock answering the detection query's source.ip terms agg."""
    client = MagicMock()
    buckets = [{"key": ip, "doc_count": n} for ip, n in per_ip.items()]
    client.search.return_value = {"aggregations": {"top_sources": {"buckets": buckets}}}
    return client


def test_quiet_vlans_count_and_stray_sources_do_not():
    # Outbound connection counts seen on the G11's uplink mirror, 2026-11-02
    client = _client({
        "192.168.1.10": 100_000, "192.168.1.20": 38_902,  # main LAN, 85%
        "10.10.0.5": 17_454,  # IoT VLAN, 10.7% (12.6% of the main LAN: flipped at the old 10% line)
        "192.168.40.7": 6_463,  # one-device VLAN, 4% (the old rule never kept it)
        "10.182.5.9": 97, "10.166.11.2": 6,  # stray private sources
        "0.0.0.0": 57, "198.18.0.1": 3,  # DHCP and benchmark range: not RFC1918
    })

    assert detect_lan_subnets(client) == [(192, 168, 1), (10, 10, 0), (192, 168, 40)]


def test_single_lan_still_detected():
    assert detect_lan_subnets(_client({"192.168.0.2": 50, "192.168.0.3": 5})) == [(192, 168, 0)]


def test_no_private_sources_detects_nothing():
    assert detect_lan_subnets(_client({"8.8.8.8": 10})) == []
