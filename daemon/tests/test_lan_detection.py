"""LAN subnet auto-detection keeps every real subnet, not just the busiest ones (#47)."""

from unittest.mock import MagicMock

from services.excluded_ips import detect_lan_subnets


def _client(per_ip: dict[str, int]) -> MagicMock:
    """OpenSearch stand-in for the detection query: a terms list keeps its top `size`
    sources (#96), a composite pages every source."""

    def search(index: str, body: dict) -> dict:
        ((name, agg),) = body["aggs"].items()
        if "composite" in agg:
            if "after" in agg["composite"]:
                return {"aggregations": {name: {"buckets": []}}}
            buckets = [{"key": {"ip": ip}, "doc_count": n} for ip, n in per_ip.items()]
            after = {"after_key": buckets[-1]["key"]} if buckets else {}
            return {"aggregations": {name: {"buckets": buckets, **after}}}
        top = sorted(per_ip.items(), key=lambda kv: kv[1], reverse=True)[
            : agg["terms"]["size"]
        ]
        return {
            "aggregations": {
                name: {"buckets": [{"key": ip, "doc_count": n} for ip, n in top]}
            }
        }

    client = MagicMock()
    client.search.side_effect = search
    return client


def test_quiet_vlans_count_and_stray_sources_do_not():
    # Outbound connection counts seen on the G11's uplink mirror, 2026-11-02
    client = _client(
        {
            "192.168.1.10": 100_000,
            "192.168.1.20": 38_902,  # main LAN, 85%
            "10.10.0.5": 17_454,  # IoT VLAN, 10.7% (12.6% of the main LAN: flipped at the old 10% line)
            "192.168.40.7": 6_463,  # one-device VLAN, 4% (the old rule never kept it)
            "10.182.5.9": 97,
            "10.166.11.2": 6,  # stray private sources
            "0.0.0.0": 57,
            "198.18.0.1": 3,  # DHCP and benchmark range: not RFC1918
        }
    )

    assert detect_lan_subnets(client) == [(192, 168, 1), (10, 10, 0), (192, 168, 40)]


def test_single_lan_still_detected():
    assert detect_lan_subnets(_client({"192.168.0.2": 50, "192.168.0.3": 5})) == [
        (192, 168, 0)
    ]


def test_no_private_sources_detects_nothing():
    assert detect_lan_subnets(_client({"8.8.8.8": 10})) == []


def test_vlan_of_quiet_devices_beyond_the_busiest_500_sources_counts():
    """#96: only the 500 busiest sources were summed, so this VLAN (2% of outbound
    connections, every device quieter than the main LAN's) was never detected."""
    main = {f"192.168.{1 + i // 250}.{1 + i % 250}": 100 for i in range(500)}  # 50,000
    iot = {f"10.10.0.{i}": 5 for i in range(1, 201)}  # 1,000

    assert detect_lan_subnets(_client({**main, **iot})) == [
        (192, 168, 1),
        (192, 168, 2),
        (10, 10, 0),
    ]
