"""
Tests for the DeviceRegistry service.

Covers: device registration, enrichment merging, name priority,
new device detection, search, get_device_traffic, IP list tracking,
passive enrichment (DHCP, ARP, mDNS, SSDP), OUI enrichment, JA3 enrichment.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from services.device_registry import DeviceRegistry, DEVICES_INDEX
from services.excluded_ips import CONN_ACCOUNTING
from tests.test_devices_api import _answering


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client():
    """Return a MagicMock OpenSearch client with nettap-devices index existing."""
    client = MagicMock()
    client.indices.exists.return_value = True
    return client


@pytest.fixture
def mock_client_no_index():
    """Return a MagicMock OpenSearch client where nettap-devices does not exist."""
    client = MagicMock()
    client.indices.exists.return_value = False
    client.indices.create.return_value = {"acknowledged": True}
    return client


@pytest.fixture
def registry(mock_client):
    """Return a DeviceRegistry with a mocked client (index already exists)."""
    return DeviceRegistry(client=mock_client)


@pytest.fixture
def registry_fresh(mock_client_no_index):
    """Return a DeviceRegistry that creates the index on init."""
    return DeviceRegistry(client=mock_client_no_index)


# ---------------------------------------------------------------------------
# Index creation
# ---------------------------------------------------------------------------


class TestIndexCreation:
    def test_index_already_exists(self, mock_client):
        """Should NOT create the index if it already exists."""
        DeviceRegistry(client=mock_client)
        mock_client.indices.create.assert_not_called()

    def test_index_created_when_missing(self, mock_client_no_index):
        """Should create the index when it does not exist."""
        DeviceRegistry(client=mock_client_no_index)
        mock_client_no_index.indices.create.assert_called_once()
        call_kwargs = mock_client_no_index.indices.create.call_args
        assert call_kwargs[1]["index"] == DEVICES_INDEX


# ---------------------------------------------------------------------------
# Device registration
# ---------------------------------------------------------------------------


class TestRegisterDevice:
    def test_register_new_device(self, registry, mock_client):
        """Registering a new MAC should create a new document with is_new=True."""
        from opensearchpy import NotFoundError

        mock_client.get.side_effect = NotFoundError(404, "not found", {})

        result = registry.register_device(
            mac="AA:BB:CC:DD:EE:FF",
            ip="192.168.1.100",
            source="dhcp",
            metadata={"hostname": "my-laptop"},
        )

        assert result["mac"] == "AA:BB:CC:DD:EE:FF"
        assert result["is_new"] is True
        assert "192.168.1.100" in result["ips"]
        assert "my-laptop" in result["hostnames"]
        assert result["enrichment_sources"]["dhcp"]["hostname"] == "my-laptop"
        mock_client.index.assert_called_once()

    def test_register_existing_device_merges_ips(self, registry, mock_client):
        """Re-registering with a new IP should merge it into the ips list."""
        mock_client.get.return_value = {
            "_source": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "ips": ["192.168.1.100"],
                "hostnames": ["laptop"],
                "manufacturer": None,
                "friendly_name": None,
                "category": "unknown",
                "first_seen": "2026-01-01T00:00:00+00:00",
                "last_seen": "2026-01-01T00:00:00+00:00",
                "is_new": True,
                "enrichment_sources": {},
            }
        }

        result = registry.register_device(
            mac="AA:BB:CC:DD:EE:FF",
            ip="192.168.1.200",
            source="arp",
        )

        assert "192.168.1.100" in result["ips"]
        assert "192.168.1.200" in result["ips"]
        assert result["is_new"] is False  # No longer new after update

    def test_register_merges_hostnames(self, registry, mock_client):
        """Re-registering with a new hostname should merge it."""
        mock_client.get.return_value = {
            "_source": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "ips": ["192.168.1.100"],
                "hostnames": ["laptop"],
                "manufacturer": None,
                "friendly_name": None,
                "category": "unknown",
                "first_seen": "2026-01-01T00:00:00+00:00",
                "last_seen": "2026-01-01T00:00:00+00:00",
                "is_new": True,
                "enrichment_sources": {},
            }
        }

        result = registry.register_device(
            mac="AA:BB:CC:DD:EE:FF",
            ip="192.168.1.100",
            source="mdns",
            metadata={"hostname": "my-macbook"},
        )

        assert "laptop" in result["hostnames"]
        assert "my-macbook" in result["hostnames"]

    def test_register_sets_manufacturer(self, registry, mock_client):
        """Registering with manufacturer metadata should set it."""
        from opensearchpy import NotFoundError

        mock_client.get.side_effect = NotFoundError(404, "not found", {})

        result = registry.register_device(
            mac="AA:BB:CC:DD:EE:FF",
            source="oui",
            metadata={"manufacturer": "Apple, Inc."},
        )

        assert result["manufacturer"] == "Apple, Inc."

    def test_register_does_not_overwrite_manufacturer(self, registry, mock_client):
        """Should not overwrite existing manufacturer."""
        mock_client.get.return_value = {
            "_source": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "ips": [],
                "hostnames": [],
                "manufacturer": "Apple, Inc.",
                "friendly_name": None,
                "category": "unknown",
                "first_seen": "2026-01-01T00:00:00+00:00",
                "last_seen": "2026-01-01T00:00:00+00:00",
                "is_new": False,
                "enrichment_sources": {},
            }
        }

        result = registry.register_device(
            mac="AA:BB:CC:DD:EE:FF",
            source="oui",
            metadata={"manufacturer": "Samsung"},
        )

        assert result["manufacturer"] == "Apple, Inc."

    def test_register_unifi_alias_takes_priority(self, registry, mock_client):
        """UniFi alias should override existing friendly_name."""
        mock_client.get.return_value = {
            "_source": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "ips": [],
                "hostnames": [],
                "manufacturer": None,
                "friendly_name": "Old Name",
                "category": "unknown",
                "first_seen": "2026-01-01T00:00:00+00:00",
                "last_seen": "2026-01-01T00:00:00+00:00",
                "is_new": False,
                "enrichment_sources": {},
            }
        }

        result = registry.register_device(
            mac="AA:BB:CC:DD:EE:FF",
            source="unifi",
            metadata={"unifi_alias": "Living Room TV"},
        )

        assert result["friendly_name"] == "Living Room TV"

    def test_mac_normalization(self, registry, mock_client):
        """MAC addresses with dashes or dots should be normalized to colons."""
        from opensearchpy import NotFoundError

        mock_client.get.side_effect = NotFoundError(404, "not found", {})

        result = registry.register_device(mac="aa-bb-cc-dd-ee-ff")
        assert result["mac"] == "AA:BB:CC:DD:EE:FF"

    def test_category_update_from_unknown(self, registry, mock_client):
        """Category should update if current is unknown."""
        mock_client.get.return_value = {
            "_source": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "ips": [],
                "hostnames": [],
                "manufacturer": None,
                "friendly_name": None,
                "category": "unknown",
                "first_seen": "2026-01-01T00:00:00+00:00",
                "last_seen": "2026-01-01T00:00:00+00:00",
                "is_new": False,
                "enrichment_sources": {},
            }
        }

        result = registry.register_device(
            mac="AA:BB:CC:DD:EE:FF",
            source="ssdp",
            metadata={"category": "iot"},
        )

        assert result["category"] == "iot"

    def test_category_not_overwritten_from_valid(self, registry, mock_client):
        """Category should NOT update if current is not unknown."""
        mock_client.get.return_value = {
            "_source": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "ips": [],
                "hostnames": [],
                "manufacturer": None,
                "friendly_name": None,
                "category": "computer",
                "first_seen": "2026-01-01T00:00:00+00:00",
                "last_seen": "2026-01-01T00:00:00+00:00",
                "is_new": False,
                "enrichment_sources": {},
            }
        }

        result = registry.register_device(
            mac="AA:BB:CC:DD:EE:FF",
            source="ssdp",
            metadata={"category": "iot"},
        )

        assert result["category"] == "computer"


# ---------------------------------------------------------------------------
# Get device
# ---------------------------------------------------------------------------


class TestGetDevice:
    def test_get_existing_device(self, registry, mock_client):
        """Should return the device document."""
        mock_client.get.return_value = {
            "_source": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "ips": ["192.168.1.100"],
            }
        }

        result = registry.get_device("AA:BB:CC:DD:EE:FF")
        assert result is not None
        assert result["mac"] == "AA:BB:CC:DD:EE:FF"

    def test_get_nonexistent_device(self, registry, mock_client):
        """Should return None for unknown MAC."""
        from opensearchpy import NotFoundError

        mock_client.get.side_effect = NotFoundError(404, "not found", {})

        result = registry.get_device("FF:FF:FF:FF:FF:FF")
        assert result is None

    def test_get_device_error_raises_not_none(self, registry, mock_client):
        """#96: a failed lookup answered "Device not found" (404)."""
        from opensearchpy import ConnectionTimeout

        mock_client.get.side_effect = ConnectionTimeout("TIMEOUT", "timed out", None)

        with pytest.raises(ConnectionTimeout):
            registry.get_device("AA:BB:CC:DD:EE:FF")


# ---------------------------------------------------------------------------
# Get all devices
# ---------------------------------------------------------------------------


class TestGetAllDevices:
    def test_get_all_devices(self, registry, mock_client):
        """Should return a list of device documents."""
        mock_client.search.return_value = {
            "hits": {
                "hits": [
                    {"_source": {"mac": "AA:BB:CC:DD:EE:FF"}},
                    {"_source": {"mac": "11:22:33:44:55:66"}},
                ]
            }
        }

        result = registry.get_all_devices(limit=10, offset=0)
        assert len(result) == 2

    def test_get_all_devices_empty(self, registry, mock_client):
        """Should return empty list when no devices exist."""
        mock_client.search.return_value = {"hits": {"hits": []}}

        result = registry.get_all_devices()
        assert result == []

    def test_get_all_devices_error_raises(self, registry, mock_client):
        """#96: a failed list raises; [] read as "no devices known"."""
        from opensearchpy import OpenSearchException

        mock_client.search.side_effect = OpenSearchException("test error")

        with pytest.raises(OpenSearchException):
            registry.get_all_devices()


# ---------------------------------------------------------------------------
# Device traffic
# ---------------------------------------------------------------------------


class TestGetDeviceTraffic:
    def test_get_device_traffic(self, registry, mock_client):
        """Should return traffic summary for a device."""
        # First call: get_device (for IPs)
        mock_client.get.return_value = {
            "_source": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "ips": ["192.168.1.100"],
            }
        }
        # Then the traffic search (NET-226: after the MAC's IPv6, which finds none here)
        mock_client.search.side_effect = _answering(
            {
                "hits": {"total": {"value": 42}},
                "aggregations": {
                    "src": {"value": 1048576},
                    "protocols": {"buckets": [{"key": "tcp", "doc_count": 30}]},
                    "started": {
                        "top_destinations": {
                            "buckets": [
                                {"key": "8.8.8.8", "doc_count": 10},
                            ]
                        }
                    },
                },
            }
        )

        # OLD CODE: result = registry.get_device_traffic(mac, from, to) (NET-260: + the chart's bucket)
        result = registry.get_device_traffic(
            "AA:BB:CC:DD:EE:FF",
            "2026-01-01T00:00:00Z",
            "2026-01-02T00:00:00Z",
            "1h",
        )

        assert result["mac"] == "AA:BB:CC:DD:EE:FF"
        # NET-260: a reply without the series' aggregation draws no chart, not a crash
        assert result["bandwidth_series"] == []
        assert result["total_bytes"] == 1048576
        assert result["connection_count"] == 42
        assert "tcp" in result["protocols"]
        assert len(result["top_destinations"]) == 1
        # DNS/SSL logs and Suricata alerts share source.mac; only connections count
        filters = mock_client.search.call_args.kwargs["body"]["query"]["bool"]["filter"]
        # OLD CODE: assert {"term": {"event.dataset": "conn"}} in filters (F1: final records only)
        assert CONN_ACCOUNTING in filters

    def test_get_device_traffic_has_what_the_mac_page_shows(
        self, registry, mock_client
    ):
        """#89: the MAC page shows in/out bytes, bytes per destination and protocol counts.

        Without them it read "0 in / 0 out" and drew every destination bar as 0 bytes.
        """
        mock_client.get.return_value = {
            "_source": {"mac": "AA:BB:CC:DD:EE:FF", "ips": []}
        }
        # NET-226: both IP byte counts, and the same over the sessions the device answered
        mock_client.search.side_effect = _answering(
            {
                "hits": {"total": {"value": 42}},
                "aggregations": {
                    "src": {"value": 500},
                    "dst": {"value": 1000},
                    "answered": {"src": {"value": 200}, "dst": {"value": 50}},
                    "protocols": {"buckets": [{"key": "tcp", "doc_count": 30}]},
                    "started": {
                        "top_destinations": {
                            "buckets": [
                                {
                                    "key": "8.8.8.8",
                                    "doc_count": 10,
                                    "src": {"value": 100},
                                    "dst": {"value": 900},
                                },
                            ]
                        }
                    },
                },
            }
        )

        result = registry.get_device_traffic(
            "AA:BB:CC:DD:EE:FF", "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", "1h"
        )

        # OLD CODE START — NET-226: in/out were the originator's bytes of the sessions it started
        # assert result["inbound_bytes"] == 1000
        # assert result["outbound_bytes"] == 500
        # OLD CODE END
        # on the sessions it answered the responder's 50 B are its upload, the 200 B its download
        assert result["inbound_bytes"] == 1000 - 50 + 200
        assert result["outbound_bytes"] == 500 - 200 + 50
        assert result["total_bytes"] == 1500
        assert result["top_destinations"] == [
            {"ip": "8.8.8.8", "connections": 10, "bytes": 1000}
        ]
        assert result["top_protocols"] == [{"name": "tcp", "count": 30}]
        aggs = mock_client.search.call_args.kwargs["body"]["aggs"]
        # OLD CODE START — NET-226: renamed src/dst, with the answered side beside them
        # assert aggs["outbound_bytes"] == {
        #     "sum": {"field": "source.bytes", "missing": 0}
        # }
        # assert aggs["inbound_bytes"] == {
        #     "sum": {"field": "destination.bytes", "missing": 0}
        # }
        # # ranked by the bytes the page draws, not by connection count
        # assert aggs["top_destinations"]["terms"]["order"] == {"bytes": "desc"}
        # # #90: ranking by a sum is only exact when each shard returns every destination
        # assert aggs["top_destinations"]["terms"]["shard_size"] >= 10_000
        # OLD CODE END
        assert aggs["src"] == {"sum": {"field": "source.bytes", "missing": 0}}
        assert aggs["dst"] == {"sum": {"field": "destination.bytes", "missing": 0}}
        destinations = aggs["started"]["aggs"]["top_destinations"]
        # ranked by the bytes the page draws, not by connection count
        assert destinations["terms"]["order"] == {"order_bytes": "desc"}
        assert destinations["aggs"]["order_bytes"] == {
            "sum": {"field": "network.bytes"}
        }
        # #90: ranking by a sum is only exact when each shard returns every destination
        assert destinations["terms"]["shard_size"] >= 10_000

    def test_get_device_traffic_sends_the_bandwidth_series(self, registry, mock_client):
        """NET-260: the MAC page draws its bandwidth chart from `bandwidth_series`, which the
        reply never had. Slots are time_slots' date_range (#120), not a date_histogram."""
        mock_client.get.return_value = {
            "_source": {"mac": "AA:BB:CC:DD:EE:FF", "ips": ["192.168.1.100"]}
        }
        hour = 3_600_000
        start = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000

        def slot(n, src=0, dst=0, a_src=0, a_dst=0):
            # a range bucket as OpenSearch returns it: float epoch-ms from/to
            return {
                "key": f"slot-{n}",
                "from": start + n * hour,
                "from_as_string": "ignored",
                "to": start + (n + 1) * hour,
                "to_as_string": "ignored",
                "doc_count": 1 if src or dst else 0,
                "src": {"value": src},
                "dst": {"value": dst},
                "answered": {"src": {"value": a_src}, "dst": {"value": a_dst}},
            }

        mock_client.search.side_effect = _answering(
            {
                "hits": {"total": {"value": 3}},
                "aggregations": {
                    "src": {"value": 500},
                    "dst": {"value": 1000},
                    "answered": {"src": {"value": 200}, "dst": {"value": 50}},
                    # out of order: histogram_buckets sorts by slot start
                    "bandwidth_series": {
                        "buckets": [slot(1), slot(0, 500, 1000, 200, 50)]
                    },
                },
            }
        )

        result = registry.get_device_traffic(
            "AA:BB:CC:DD:EE:FF", "2026-01-01T00:00:00Z", "2026-01-01T01:30:00Z", "1h"
        )

        body = next(
            c.kwargs["body"]
            for c in mock_client.search.call_args_list
            if "bandwidth_series" in c.kwargs["body"].get("aggs", {})
        )
        series = body["aggs"]["bandwidth_series"]
        assert "date_histogram" not in series
        assert series["date_range"]["field"] == "@timestamp"
        # spaced by the bucket asked for, from the slot holding `from` to the one holding `to`
        assert series["date_range"]["ranges"] == [
            {"from": "2026-01-01T00:00:00.000Z", "to": "2026-01-01T01:00:00.000Z"},
            {"from": "2026-01-01T01:00:00.000Z", "to": "2026-01-01T02:00:00.000Z"},
        ]
        # each slot is counted from the device's side, as the totals are
        assert series["aggs"] == {
            k: body["aggs"][k] for k in ("src", "dst", "answered")
        }
        # upload 500 - 200 + 50, download 1000 - 50 + 200 (side_bytes)
        assert result["bandwidth_series"] == [
            {
                "timestamp": "2026-01-01T00:00:00.000Z",
                "bytes": 1500,
                "download_bytes": 1150,
                "upload_bytes": 350,
            },
            {
                "timestamp": "2026-01-01T01:00:00.000Z",
                "bytes": 0,
                "download_bytes": 0,
                "upload_bytes": 0,
            },
        ]
        assert (
            sum(p["bytes"] for p in result["bandwidth_series"]) == result["total_bytes"]
        )

    def test_get_device_traffic_error_raises(self, registry, mock_client):
        """#96: a failed query raises; zeros read as a device with no traffic."""
        mock_client.get.return_value = {
            "_source": {"mac": "AA:BB:CC:DD:EE:FF", "ips": []}
        }
        from opensearchpy import OpenSearchException

        mock_client.search.side_effect = OpenSearchException("test error")

        with pytest.raises(OpenSearchException):
            registry.get_device_traffic(
                "AA:BB:CC:DD:EE:FF",
                "2026-01-01T00:00:00Z",
                "2026-01-02T00:00:00Z",
                "1h",
            )


# ---------------------------------------------------------------------------
# Search devices
# ---------------------------------------------------------------------------


class TestSearchDevices:
    def test_search_by_ip(self, registry, mock_client):
        """Should find devices matching an IP search."""
        mock_client.search.return_value = {
            "hits": {
                "hits": [
                    {"_source": {"mac": "AA:BB:CC:DD:EE:FF", "ips": ["192.168.1.100"]}},
                ]
            }
        }

        result = registry.search_devices("192.168.1")
        assert len(result) == 1

    def test_search_no_results(self, registry, mock_client):
        """Should return empty list for no matches."""
        mock_client.search.return_value = {"hits": {"hits": []}}

        result = registry.search_devices("nonexistent")
        assert result == []

    def test_search_error_raises(self, registry, mock_client):
        """#96: [] read as "no device matches"."""
        from opensearchpy import OpenSearchException

        mock_client.search.side_effect = OpenSearchException("test error")

        with pytest.raises(OpenSearchException):
            registry.search_devices("192.168.1")


# ---------------------------------------------------------------------------
# Display name priority
# ---------------------------------------------------------------------------


class TestDisplayName:
    def test_unifi_alias_highest_priority(self, registry):
        """UniFi alias should win over everything else."""
        device = {
            "mac": "AA:BB:CC:DD:EE:FF",
            "friendly_name": "User Name",
            "hostnames": ["dhcp-host"],
            "manufacturer": "Apple",
            "enrichment_sources": {
                "unifi": {"unifi_alias": "Living Room Apple TV"},
                "dhcp": {"hostname": "dhcp-host"},
            },
        }
        assert registry.get_display_name(device) == "Living Room Apple TV"

    def test_friendly_name_second_priority(self, registry):
        """User-set friendly name should win when no UniFi alias."""
        device = {
            "mac": "AA:BB:CC:DD:EE:FF",
            "friendly_name": "My Laptop",
            "hostnames": ["dhcp-host"],
            "manufacturer": "Dell",
            "enrichment_sources": {
                "dhcp": {"hostname": "dhcp-host"},
            },
        }
        assert registry.get_display_name(device) == "My Laptop"

    def test_dhcp_hostname_third_priority(self, registry):
        """DHCP hostname should win when no friendly name."""
        device = {
            "mac": "AA:BB:CC:DD:EE:FF",
            "friendly_name": None,
            "hostnames": [],
            "manufacturer": "Dell",
            "enrichment_sources": {
                "dhcp": {"hostname": "DESKTOP-ABC"},
            },
        }
        assert registry.get_display_name(device) == "DESKTOP-ABC"

    def test_mdns_hostname_fourth_priority(self, registry):
        """mDNS hostname should win when no DHCP hostname."""
        device = {
            "mac": "AA:BB:CC:DD:EE:FF",
            "friendly_name": None,
            "hostnames": [],
            "manufacturer": "Apple",
            "enrichment_sources": {
                "mdns": {"hostname": "MacBook-Pro"},
            },
        }
        assert registry.get_display_name(device) == "MacBook-Pro"

    def test_hostname_list_fifth_priority(self, registry):
        """First hostname in list should be used when no enrichment hostnames."""
        device = {
            "mac": "AA:BB:CC:DD:EE:FF",
            "friendly_name": None,
            "hostnames": ["some-host"],
            "manufacturer": "Dell",
            "enrichment_sources": {},
        }
        assert registry.get_display_name(device) == "some-host"

    def test_manufacturer_fallback(self, registry):
        """Manufacturer should be used when nothing else is available."""
        device = {
            "mac": "AA:BB:CC:DD:EE:FF",
            "friendly_name": None,
            "hostnames": [],
            "manufacturer": "TP-Link",
            "enrichment_sources": {},
        }
        assert registry.get_display_name(device) == "TP-Link"

    def test_mac_last_resort(self, registry):
        """MAC address should be the last resort."""
        device = {
            "mac": "AA:BB:CC:DD:EE:FF",
            "friendly_name": None,
            "hostnames": [],
            "manufacturer": None,
            "enrichment_sources": {},
        }
        assert registry.get_display_name(device) == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# DHCP enrichment
# ---------------------------------------------------------------------------


class TestDHCPEnrichment:
    def test_enrich_from_dhcp(self, registry, mock_client):
        """Should register devices from DHCP log hits."""
        # get_device returns None (new device) for the register call
        from opensearchpy import NotFoundError

        # search for DHCP logs returns results
        mock_client.search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "source": {
                                "mac": "AA:BB:CC:DD:EE:FF",
                                "ip": "192.168.1.100",
                            },
                            "dhcp": {
                                "host": ["my-laptop"],
                                "ip": ["192.168.1.100"],
                                "id": "abc123",
                            },
                        }
                    },
                ]
            }
        }
        # get_device via get() returns not found
        mock_client.get.side_effect = NotFoundError(404, "not found", {})

        count = registry.enrich_from_dhcp(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        assert count == 1
        # Verify index was called (device was registered)
        assert mock_client.index.called

    def test_enrich_from_dhcp_skips_unassigned_address(self, registry, mock_client):
        """#26: a DISCOVER's 0.0.0.0 source is not the device's IP."""
        from opensearchpy import NotFoundError

        mock_client.get.side_effect = NotFoundError(404, "not found", {})
        mock_client.search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "source": {"mac": "2A:37:F4:D9:20:F5", "ip": "0.0.0.0"},
                            "dhcp": {"id": "d1"},
                        }
                    }
                ]
            }
        }

        registry.enrich_from_dhcp("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")

        assert mock_client.index.call_args.kwargs["body"]["ips"] == []

    def test_enrich_from_dhcp_deduplicates(self, registry, mock_client):
        """Should not register the same MAC twice."""
        from opensearchpy import NotFoundError

        mock_client.get.side_effect = NotFoundError(404, "not found", {})

        mock_client.search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "source": {
                                "mac": "AA:BB:CC:DD:EE:FF",
                                "ip": "192.168.1.100",
                            },
                            "dhcp": {"id": "a1"},
                        }
                    },
                    {
                        "_source": {
                            "source": {
                                "mac": "AA:BB:CC:DD:EE:FF",
                                "ip": "192.168.1.101",
                            },
                            "dhcp": {"id": "a2"},
                        }
                    },
                ]
            }
        }

        count = registry.enrich_from_dhcp(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        assert count == 1  # Deduplicated


# ---------------------------------------------------------------------------
# ARP enrichment
# ---------------------------------------------------------------------------


class TestARPEnrichment:
    def test_enrich_from_arp(self, registry, mock_client):
        """Should register MAC-IP pairs from conn log aggregation."""
        from opensearchpy import NotFoundError

        # First call: search for ARP data (aggregation)
        # Second+ calls: get_device during register_device
        search_response = {
            "aggregations": {
                "by_mac": {
                    "buckets": [
                        {
                            "key": "AA:BB:CC:DD:EE:FF",
                            "ips": {
                                "buckets": [
                                    {"key": "192.168.1.100", "doc_count": 5},
                                    {"key": "192.168.1.101", "doc_count": 2},
                                ]
                            },
                        },
                    ]
                }
            }
        }
        mock_client.search.return_value = search_response
        mock_client.get.side_effect = NotFoundError(404, "not found", {})

        count = registry.enrich_from_arp("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")

        assert count == 2  # Two IP-MAC pairs


# ---------------------------------------------------------------------------
# mDNS enrichment
# ---------------------------------------------------------------------------


class TestMDNSEnrichment:
    def test_enrich_from_mdns(self, registry, mock_client):
        """Should extract device names from .local DNS queries."""
        from opensearchpy import NotFoundError

        mock_client.get.side_effect = NotFoundError(404, "not found", {})

        mock_client.search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "source": {
                                "mac": "AA:BB:CC:DD:EE:FF",
                                "ip": "192.168.1.100",
                            },
                            "dns": {"host": ["MacBook-Pro._tcp.local"]},
                        }
                    },
                ]
            }
        }

        count = registry.enrich_from_mdns(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        assert count == 1
        # Verify the registered metadata
        call_kwargs = mock_client.index.call_args
        body = call_kwargs[1]["body"]
        assert "MacBook-Pro" in body["hostnames"]


# ---------------------------------------------------------------------------
# SSDP enrichment
# ---------------------------------------------------------------------------


class TestSSDPEnrichment:
    def test_enrich_from_ssdp(self, registry, mock_client):
        """Should extract device info from SSDP/UPnP HTTP logs."""
        from opensearchpy import NotFoundError

        mock_client.get.side_effect = NotFoundError(404, "not found", {})

        mock_client.search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "source": {
                                "mac": "AA:BB:CC:DD:EE:FF",
                                "ip": "192.168.1.100",
                            },
                            "http": {"useragent": "Google-Home/1.0"},
                        }
                    },
                ]
            }
        }

        count = registry.enrich_from_ssdp(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        assert count == 1


class TestEnrichmentSkipsPartialReplies:
    """Follow-up to PR #191: a partial reply could re-add an old lease's IP to a MAC."""

    HIT = {
        "_source": {
            "source": {"mac": "AA:BB:CC:DD:EE:FF", "ip": "192.168.1.100"},
            "zeek": {"dhcp": {"host_name": "laptop", "assigned_ip": "192.168.1.100"}},
            "dns": {"host": ["laptop.local"]},
            "http": {"useragent": "Google-Home/1.0"},
        }
    }

    @pytest.mark.parametrize(
        "method", ["enrich_from_dhcp", "enrich_from_mdns", "enrich_from_ssdp"]
    )
    def test_a_reply_with_a_failed_shard_registers_nothing(
        self, registry, mock_client, method
    ):
        from opensearchpy import NotFoundError

        mock_client.get.side_effect = NotFoundError(404, "not found", {})
        mock_client.search.return_value = {
            "_shards": {"total": 2, "successful": 1, "failed": 1},
            "hits": {"hits": [self.HIT]},
        }

        assert (
            getattr(registry, method)("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
            == 0
        )
        mock_client.index.assert_not_called()

    @pytest.mark.parametrize(
        "method", ["enrich_from_dhcp", "enrich_from_mdns", "enrich_from_ssdp"]
    )
    def test_the_same_reply_complete_registers(self, registry, mock_client, method):
        from opensearchpy import NotFoundError

        mock_client.get.side_effect = NotFoundError(404, "not found", {})
        mock_client.search.return_value = {"hits": {"hits": [self.HIT]}}

        assert (
            getattr(registry, method)("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
            == 1
        )


# ---------------------------------------------------------------------------
# OUI enrichment
# ---------------------------------------------------------------------------


class TestOUIEnrichment:
    def test_enrich_with_oui(self, registry, mock_client):
        """Should lookup OUI for devices without a manufacturer."""
        mock_client.search.return_value = {
            "hits": {
                "hits": [
                    {"_source": {"mac": "AA:BB:CC:DD:EE:FF", "manufacturer": None}},
                ]
            }
        }
        mock_client.get.return_value = {
            "_source": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "ips": [],
                "hostnames": [],
                "manufacturer": None,
                "friendly_name": None,
                "category": "unknown",
                "first_seen": "2026-01-01T00:00:00+00:00",
                "last_seen": "2026-01-01T00:00:00+00:00",
                "is_new": False,
                "enrichment_sources": {},
            }
        }

        mac_lookup = MagicMock()
        mac_lookup.lookup.return_value = {
            "mac": "AA:BB:CC:DD:EE:FF",
            "vendor": "Apple, Inc.",
            "found": True,
        }

        count = registry.enrich_with_oui(mac_lookup)
        assert count == 1

    def test_enrich_with_oui_skips_existing(self, registry, mock_client):
        """Should skip devices that already have a manufacturer."""
        mock_client.search.return_value = {
            "hits": {
                "hits": [
                    {"_source": {"mac": "AA:BB:CC:DD:EE:FF", "manufacturer": "Apple"}},
                ]
            }
        }

        mac_lookup = MagicMock()

        count = registry.enrich_with_oui(mac_lookup)
        assert count == 0
        mac_lookup.lookup.assert_not_called()


# ---------------------------------------------------------------------------
# JA3 enrichment
# ---------------------------------------------------------------------------


class TestJA3Enrichment:
    def test_enrich_with_ja3(self, registry, mock_client):
        """Should add OS hint from JA3 fingerprinting."""
        mock_client.search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "mac": "AA:BB:CC:DD:EE:FF",
                            "ips": ["192.168.1.100"],
                            "enrichment_sources": {},
                        }
                    },
                ]
            }
        }
        mock_client.get.return_value = {
            "_source": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "ips": ["192.168.1.100"],
                "hostnames": [],
                "manufacturer": None,
                "friendly_name": None,
                "category": "unknown",
                "first_seen": "2026-01-01T00:00:00+00:00",
                "last_seen": "2026-01-01T00:00:00+00:00",
                "is_new": False,
                "enrichment_sources": {},
            }
        }

        fingerprint = MagicMock()
        fingerprint.get_os_hint.return_value = "macOS"

        count = registry.enrich_with_ja3(
            fingerprint, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        assert count == 1

    def test_enrich_with_ja3_skips_existing(self, registry, mock_client):
        """Should skip devices that already have a JA3 OS hint."""
        mock_client.search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "mac": "AA:BB:CC:DD:EE:FF",
                            "ips": ["192.168.1.100"],
                            "enrichment_sources": {
                                "ja3": {"os_hint": "Windows 10"},
                            },
                        }
                    },
                ]
            }
        }

        fingerprint = MagicMock()

        count = registry.enrich_with_ja3(
            fingerprint, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        assert count == 0
        fingerprint.get_os_hint.assert_not_called()

    def test_enrich_with_ja3_no_ips(self, registry, mock_client):
        """Should skip devices with no known IPs."""
        mock_client.search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "mac": "AA:BB:CC:DD:EE:FF",
                            "ips": [],
                            "enrichment_sources": {},
                        }
                    },
                ]
            }
        }

        fingerprint = MagicMock()

        count = registry.enrich_with_ja3(
            fingerprint, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        assert count == 0


# ---------------------------------------------------------------------------
# New device detection
# ---------------------------------------------------------------------------


class TestNewDeviceDetection:
    def test_new_device_flagged(self, registry, mock_client):
        """First registration should flag device as new."""
        from opensearchpy import NotFoundError

        mock_client.get.side_effect = NotFoundError(404, "not found", {})

        result = registry.register_device(mac="AA:BB:CC:DD:EE:FF")
        assert result["is_new"] is True

    def test_subsequent_update_clears_new_flag(self, registry, mock_client):
        """Updating an existing device should clear the is_new flag."""
        mock_client.get.return_value = {
            "_source": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "ips": [],
                "hostnames": [],
                "manufacturer": None,
                "friendly_name": None,
                "category": "unknown",
                "first_seen": "2026-01-01T00:00:00+00:00",
                "last_seen": "2026-01-01T00:00:00+00:00",
                "is_new": True,
                "enrichment_sources": {},
            }
        }

        result = registry.register_device(mac="AA:BB:CC:DD:EE:FF", ip="10.0.0.1")
        assert result["is_new"] is False


# ---------------------------------------------------------------------------
# IP list tracking
# ---------------------------------------------------------------------------


class TestIPTracking:
    def test_multiple_ips_tracked(self, registry, mock_client):
        """Device should accumulate all IPs it has used."""
        from opensearchpy import NotFoundError

        # First registration: new device
        mock_client.get.side_effect = NotFoundError(404, "not found", {})
        registry.register_device(mac="AA:BB:CC:DD:EE:FF", ip="192.168.1.100")

        # Reset side_effect: existing device with first IP
        mock_client.get.side_effect = None
        mock_client.get.return_value = {
            "_source": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "ips": ["192.168.1.100"],
                "hostnames": [],
                "manufacturer": None,
                "friendly_name": None,
                "category": "unknown",
                "first_seen": "2026-01-01T00:00:00+00:00",
                "last_seen": "2026-01-01T00:00:00+00:00",
                "is_new": False,
                "enrichment_sources": {},
            }
        }

        result = registry.register_device(mac="AA:BB:CC:DD:EE:FF", ip="192.168.1.200")
        assert "192.168.1.100" in result["ips"]
        assert "192.168.1.200" in result["ips"]

    def test_duplicate_ip_not_added(self, registry, mock_client):
        """Same IP should not appear twice."""
        mock_client.get.return_value = {
            "_source": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "ips": ["192.168.1.100"],
                "hostnames": [],
                "manufacturer": None,
                "friendly_name": None,
                "category": "unknown",
                "first_seen": "2026-01-01T00:00:00+00:00",
                "last_seen": "2026-01-01T00:00:00+00:00",
                "is_new": False,
                "enrichment_sources": {},
            }
        }

        result = registry.register_device(mac="AA:BB:CC:DD:EE:FF", ip="192.168.1.100")
        assert result["ips"].count("192.168.1.100") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/devices/registry",
        "/api/devices/registry/AA:BB:CC:DD:EE:FF",
        "/api/devices/registry/AA:BB:CC:DD:EE:FF/traffic",
        "/api/devices/registry/search?q=192.168",
    ],
)
async def test_registry_endpoints_answer_502_when_opensearch_fails(
    registry, mock_client, path
):
    """#96: a failed query listed no devices, a known device as "not found", or zero traffic."""
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    from opensearchpy import ConnectionTimeout

    from api.devices_v2 import register_devices_v2_routes

    mock_client.get.side_effect = ConnectionTimeout("TIMEOUT", "timed out", None)
    mock_client.search.side_effect = ConnectionTimeout("TIMEOUT", "timed out", None)
    app = web.Application()
    register_devices_v2_routes(app, registry, MagicMock())

    async with TestClient(TestServer(app)) as client:
        resp = await client.get(path)
        assert resp.status == 502
        assert "error" in await resp.json()


@pytest.mark.asyncio
async def test_registry_traffic_takes_a_bucket_and_names_it(registry):
    """NET-260: the MAC page's chart bucket, as the IP page's (NET-249): `?interval=` or
    _bandwidth_interval's pick, checked before any search and echoed as bandwidth_interval."""
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from api.devices_v2 import register_devices_v2_routes
    from api.time_range import TOO_MANY_SLOTS

    registry.get_device = MagicMock(return_value={"mac": "AA:BB:CC:DD:EE:FF"})
    registry.get_device_traffic = MagicMock(return_value={"bandwidth_series": []})
    app = web.Application()
    register_devices_v2_routes(app, registry, MagicMock())
    path = "/api/devices/registry/AA:BB:CC:DD:EE:FF/traffic"
    window = {"from": "2026-11-05T00:00:00Z", "to": "2026-11-05T12:00:00Z"}

    async with TestClient(TestServer(app)) as client:
        own = await client.get(path, params=window)
        # 12 h: _bandwidth_interval's pick
        assert (await own.json())["bandwidth_interval"] == "5m"
        hourly = await client.get(path, params={**window, "interval": "1h"})
        assert hourly.status == 200
        assert (await hourly.json())["bandwidth_interval"] == "1h"
        assert registry.get_device_traffic.call_args.args[3] == "1h"

        unknown = await client.get(path, params={**window, "interval": "7s"})
        assert unknown.status == 400
        assert (await unknown.json())["error"].startswith("Unknown interval")
        week = {"from": "2026-10-29T12:00:00Z", "to": "2026-11-05T12:00:00Z"}
        too_fine = await client.get(path, params={**week, "interval": "1m"})
        assert (too_fine.status, await too_fine.json()) == (
            400,
            {"error": TOO_MANY_SLOTS},
        )
    # the two refusals searched nothing
    assert registry.get_device.call_count == 2
