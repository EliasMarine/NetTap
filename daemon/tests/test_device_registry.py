"""
Tests for the DeviceRegistry service.

Covers: device registration, enrichment merging, name priority,
new device detection, search, get_device_traffic, IP list tracking,
passive enrichment (DHCP, ARP, mDNS, SSDP), OUI enrichment, JA3 enrichment.
"""

from unittest.mock import MagicMock, patch

import pytest

from services.device_registry import DeviceRegistry, DEVICES_INDEX, CATEGORY_UNKNOWN


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

    def test_get_all_devices_error(self, registry, mock_client):
        """Should return empty list on OpenSearch error."""
        from opensearchpy import OpenSearchException
        mock_client.search.side_effect = OpenSearchException("test error")

        result = registry.get_all_devices()
        assert result == []


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
        # Second call: search for traffic
        mock_client.search.return_value = {
            "hits": {"total": {"value": 42}},
            "aggregations": {
                "total_bytes": {"value": 1048576},
                "protocols": {"buckets": [{"key": "tcp", "doc_count": 30}]},
                "top_destinations": {
                    "buckets": [
                        {"key": "8.8.8.8", "doc_count": 10},
                    ]
                },
            },
        }

        result = registry.get_device_traffic(
            "AA:BB:CC:DD:EE:FF",
            "2026-01-01T00:00:00Z",
            "2026-01-02T00:00:00Z",
        )

        assert result["mac"] == "AA:BB:CC:DD:EE:FF"
        assert result["total_bytes"] == 1048576
        assert result["connection_count"] == 42
        assert "tcp" in result["protocols"]
        assert len(result["top_destinations"]) == 1

    def test_get_device_traffic_error(self, registry, mock_client):
        """Should return empty summary on OpenSearch error."""
        mock_client.get.return_value = {
            "_source": {"mac": "AA:BB:CC:DD:EE:FF", "ips": []}
        }
        from opensearchpy import OpenSearchException
        mock_client.search.side_effect = OpenSearchException("test error")

        result = registry.get_device_traffic(
            "AA:BB:CC:DD:EE:FF",
            "2026-01-01T00:00:00Z",
            "2026-01-02T00:00:00Z",
        )

        assert result["total_bytes"] == 0
        assert result["connection_count"] == 0


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
                            "source.mac": "AA:BB:CC:DD:EE:FF",
                            "source.ip": "192.168.1.100",
                            "zeek.dhcp.hostname": "my-laptop",
                            "zeek.dhcp.vendor_class": "MSFT 5.0",
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

    def test_enrich_from_dhcp_deduplicates(self, registry, mock_client):
        """Should not register the same MAC twice."""
        from opensearchpy import NotFoundError
        mock_client.get.side_effect = NotFoundError(404, "not found", {})

        mock_client.search.return_value = {
            "hits": {
                "hits": [
                    {"_source": {"source.mac": "AA:BB:CC:DD:EE:FF", "source.ip": "192.168.1.100"}},
                    {"_source": {"source.mac": "AA:BB:CC:DD:EE:FF", "source.ip": "192.168.1.101"}},
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

        count = registry.enrich_from_arp(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

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
                            "source.mac": "AA:BB:CC:DD:EE:FF",
                            "source.ip": "192.168.1.100",
                            "zeek.dns.query": "MacBook-Pro._tcp.local",
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
                            "source.mac": "AA:BB:CC:DD:EE:FF",
                            "source.ip": "192.168.1.100",
                            "zeek.http.user_agent": "Google-Home/1.0",
                        }
                    },
                ]
            }
        }

        count = registry.enrich_from_ssdp(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        assert count == 1


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
