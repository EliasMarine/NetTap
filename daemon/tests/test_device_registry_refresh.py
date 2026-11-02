"""Tests for the periodic device registry refresh.

Covers: registration from conn buckets (incl. list-valued MACs), parity with
the device list's query and skip rules, first_seen kept on re-registration,
one changelog event per new device, DHCP enrichment against Malcolm's Zeek
fields, no .keyword field names, and a loop that survives a failed refresh.
"""

import asyncio
import copy
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from opensearchpy import ConnectionError as OSConnectionError
from opensearchpy import NotFoundError

import main
from api.devices import (
    NETWORK_INDEX,
    _MAX_DEVICE_LIMIT,
    _MIN_CONNECTIONS,
    _device_bool_query,
    _is_skipped_device_ip,
)
from api.devices_v2 import REGISTRY_REFRESH_WINDOW, refresh_device_registry
from services.changelog import CHANGELOG_EVENT_TYPES
from services.device_registry import DeviceRegistry

LAN_FILTER = {"terms": {"source.ip": ["192.168.1.0/24"]}}


def _bucket(ip: str, mac: str | list[str] | None, oui: str | None = None) -> dict:
    """A conn terms bucket as OpenSearch returns it for _conn_devices_query."""
    source = {"mac": mac, **({"oui": oui} if oui else {})}
    macs = [] if mac is None else [{"key": "x", "doc_count": 12, "latest": {"hits": {"hits": [{"_source": {"source": source}}]}}}]
    return {"key": ip, "doc_count": 12, "with_mac": {"doc_count_error_upper_bound": 0, "buckets": macs}}


def _fake_client(buckets: list[dict], store: dict | None = None) -> MagicMock:
    """OpenSearch client mock: get/index use an in-memory store, search serves conn buckets."""
    client = MagicMock()
    client.indices.exists.return_value = True
    client.store = {} if store is None else store

    def get(index: str, id: str) -> dict:
        if id not in client.store:
            raise NotFoundError(404, "not_found", {})
        return {"_source": copy.deepcopy(client.store[id])}

    def index(index: str, id: str, body: dict, refresh: str) -> dict:
        client.store[id] = copy.deepcopy(body)
        return {"result": "created"}

    def search(index: str, body: dict) -> dict:
        if "devices" in body.get("aggs", {}):
            return {"aggregations": {"devices": {"buckets": buckets}}}
        if "match_all" in body.get("query", {}):  # registry listing
            return {"hits": {"hits": [{"_source": copy.deepcopy(d)} for d in client.store.values()]}}
        return {"hits": {"hits": []}}

    client.get.side_effect = get
    client.index.side_effect = index
    client.search.side_effect = search
    return client


def _app(client: MagicMock, changelog: MagicMock | None = None) -> dict:
    return {
        "device_registry": DeviceRegistry(client=client, changelog=changelog),
        "lan_filter": LAN_FILTER,
        "excluded_ips": ["192.168.1.77"],
    }


def _conn_query(client: MagicMock) -> tuple[str, dict]:
    """The (index, body) of the refresh's conn device search."""
    for call in client.search.call_args_list:
        if "devices" in call.kwargs["body"].get("aggs", {}):
            return call.kwargs["index"], call.kwargs["body"]
    raise AssertionError("refresh made no conn device search")


class TestRegisterFromConn:
    def test_registers_each_lan_device_under_its_mac(self):
        client = _fake_client(
            [
                _bucket("192.168.1.10", "aa:bb:cc:00:00:01"),
                # Malcolm stores source.mac as a list
                _bucket("192.168.1.11", ["aa:bb:cc:00:00:02", "aa:bb:cc:00:00:02"]),
                _bucket("192.168.1.12", None),  # no MAC in its conn records
            ]
        )

        count = refresh_device_registry(_app(client))

        assert count == 2
        assert set(client.store) == {"AA:BB:CC:00:00:01", "AA:BB:CC:00:00:02"}
        assert client.store["AA:BB:CC:00:00:01"]["ips"] == ["192.168.1.10"]
        assert client.store["AA:BB:CC:00:00:02"]["ips"] == ["192.168.1.11"]

    def test_skips_the_ips_the_device_list_skips(self):
        skipped = ["192.168.1.255", "192.168.1.0", "224.0.0.251"]
        assert all(_is_skipped_device_ip(ip) for ip in skipped)
        client = _fake_client([_bucket(ip, "aa:bb:cc:00:00:09") for ip in skipped])

        assert refresh_device_registry(_app(client)) == 0
        assert client.store == {}

    def test_conn_query_is_the_device_list_query(self):
        client = _fake_client([])
        app = _app(client)

        refresh_device_registry(app)

        index, body = _conn_query(client)
        assert index == NETWORK_INDEX
        window = body["query"]["bool"]["filter"][0]["range"]["@timestamp"]
        from_ts, to_ts = window["gte"], window["lte"]
        span = datetime.fromisoformat(to_ts) - datetime.fromisoformat(from_ts)
        assert span == REGISTRY_REFRESH_WINDOW
        request = SimpleNamespace(app=app)
        assert body["query"]["bool"] == _device_bool_query(request, from_ts, to_ts)
        terms = body["aggs"]["devices"]["terms"]
        assert terms == {
            "field": "source.ip",
            "size": _MAX_DEVICE_LIMIT,
            "min_doc_count": _MIN_CONNECTIONS,
        }

    def test_no_registry_does_nothing(self):
        assert refresh_device_registry({}) == 0


class TestReRegistration:
    def test_first_seen_kept_last_seen_and_ip_updated(self):
        old = "2026-01-01T00:00:00+00:00"
        store = {
            "AA:BB:CC:00:00:01": {
                "mac": "AA:BB:CC:00:00:01",
                "ips": ["192.168.1.10"],
                "hostnames": [],
                "manufacturer": None,
                "friendly_name": None,
                "category": "unknown",
                "first_seen": old,
                "last_seen": old,
                "is_new": True,
                "enrichment_sources": {},
            }
        }
        client = _fake_client([_bucket("192.168.1.20", "aa:bb:cc:00:00:01")], store)

        refresh_device_registry(_app(client))

        doc = client.store["AA:BB:CC:00:00:01"]
        assert doc["first_seen"] == old
        assert doc["last_seen"] > old
        assert doc["ips"] == ["192.168.1.10", "192.168.1.20"]


class TestNewDeviceChangelog:
    def test_logged_once_per_new_mac(self):
        assert "device_joined" in CHANGELOG_EVENT_TYPES
        changelog = MagicMock()
        client = _fake_client([_bucket("192.168.1.10", "aa:bb:cc:00:00:01")])
        app = _app(client, changelog)

        refresh_device_registry(app)
        refresh_device_registry(app)

        changelog.log_event.assert_called_once()
        event_type, title, description, metadata = changelog.log_event.call_args.args
        assert event_type == "device_joined"
        assert "AA:BB:CC:00:00:01" in title
        assert "192.168.1.10" in description
        assert metadata == {
            "mac": "AA:BB:CC:00:00:01",
            "ip": "192.168.1.10",
            "source": "conn",
        }

    def test_failed_lookup_never_recreates_a_device(self):
        """A timeout on the lookup must not reset first_seen or log a new device."""
        changelog = MagicMock()
        client = _fake_client([_bucket("192.168.1.10", "aa:bb:cc:00:00:01")])
        client.get.side_effect = OSConnectionError("N/A", "timed out", None)
        registry = DeviceRegistry(client=client, changelog=changelog)

        try:
            registry.register_device(mac="aa:bb:cc:00:00:01", ip="192.168.1.10")
        except OSConnectionError:
            pass
        else:
            raise AssertionError("a failed lookup must raise")

        client.index.assert_not_called()
        changelog.log_event.assert_not_called()


class TestEnrichmentFieldNames:
    def test_dhcp_reads_malcolm_zeek_records(self):
        client = _fake_client([])
        hit = {
            "_source": {
                "source": {"mac": ["aa:bb:cc:00:00:05"], "ip": "192.168.1.50"},
                "zeek": {
                    "dhcp": {
                        "host_name": "living-room-tv",
                        "assigned_ip": "192.168.1.50",
                    }
                },
            }
        }
        client.search.side_effect = lambda index, body: {"hits": {"hits": [hit]}}
        registry = DeviceRegistry(client=client)

        assert registry.enrich_from_dhcp("2026-11-01T00:00:00Z", "now") == 1

        query = client.search.call_args.kwargs["body"]
        filters = query["query"]["bool"]["filter"]
        assert {"term": {"network.protocol": "dhcp"}} in filters
        assert "dhcp.id" not in json.dumps(query)
        doc = client.store["AA:BB:CC:00:00:05"]
        assert doc["hostnames"] == ["living-room-tv"]
        assert doc["ips"] == ["192.168.1.50"]

    def test_refresh_queries_have_no_keyword_fields(self):
        client = _fake_client([_bucket("192.168.1.10", "aa:bb:cc:00:00:01")])
        app = {**_app(client), "mac_lookup": MagicMock()}

        refresh_device_registry(app)

        assert client.search.call_count >= 4  # conn, DHCP, mDNS, SSDP (+ OUI list)
        for call in client.search.call_args_list:
            assert ".keyword" not in json.dumps(call.kwargs["body"])


class TestDeviceRegistryLoop:
    def test_loop_survives_a_failed_refresh(self, monkeypatch):
        async def scenario() -> list[dict]:
            loop = asyncio.get_running_loop()
            shutdown = asyncio.Event()
            calls: list[dict] = []

            def refresh(app: dict) -> int:
                calls.append(app)
                if len(calls) == 1:
                    raise RuntimeError("OpenSearch not ready")
                loop.call_soon_threadsafe(shutdown.set)
                return 0

            monkeypatch.setattr(main, "refresh_device_registry", refresh)
            app = {"device_registry": object()}
            await asyncio.wait_for(
                main.device_registry_loop(app, 0.01, shutdown), timeout=5
            )
            return calls

        calls = asyncio.run(scenario())
        assert len(calls) == 2


class TestVendorFromMalcolm:
    """#26: the registry takes Malcolm's IEEE vendor and the category it implies."""

    def test_registers_vendor_and_category(self):
        hue = _bucket("192.168.1.154", "00:17:88:48:3c:07", "Philips Lighting BV")
        apple = _bucket("192.168.1.95", "7c:01:3e:74:d2:1c", "Apple, Inc.")
        client = _fake_client([hue, apple, _bucket("192.168.1.151", "0e:cc:55:a1:28:66")])

        refresh_device_registry(_app(client))

        assert "source.oui" in str(_conn_query(client)[1])
        hue_doc = client.store["00:17:88:48:3C:07"]
        assert (hue_doc["manufacturer"], hue_doc["category"]) == ("Philips Lighting BV", "iot")
        apple_doc = client.store["7C:01:3E:74:D2:1C"]
        assert (apple_doc["manufacturer"], apple_doc["category"]) == ("Apple, Inc.", "unknown")
        assert client.store["0E:CC:55:A1:28:66"]["manufacturer"] is None  # randomized MAC

    def test_category_outside_the_grid_groups_is_unknown(self):
        sonos = _bucket("192.168.1.30", "48:a6:b8:00:00:01", "Sonos, Inc.")
        client = _fake_client([sonos])

        refresh_device_registry(_app(client))

        doc = client.store["48:A6:B8:00:00:01"]
        assert (doc["manufacturer"], doc["category"]) == ("Sonos, Inc.", "unknown")


class TestIpOwnership:
    """#26: each IP is filed under its most common MAC and leaves any other device."""

    def test_query_takes_the_most_common_mac(self):
        client = _fake_client([])
        refresh_device_registry(_app(client))
        with_mac = _conn_query(client)[1]["aggs"]["devices"]["aggs"]["with_mac"]
        assert with_mac["terms"] == {"field": "source.mac", "size": 1}

    def test_ip_moves_off_the_router_and_0000_is_dropped(self):
        udm = "D0:21:F9:5E:35:32"
        store = {
            udm: {"mac": udm, "ips": ["192.168.1.1", "192.168.1.164"], "category": "infrastructure"},
            "AA:BB:CC:00:00:05": {"mac": "AA:BB:CC:00:00:05", "ips": ["0.0.0.0", "192.168.1.116"]},
        }
        client = _fake_client(
            [_bucket("192.168.1.164", "cc:f4:11:b4:7f:68"), _bucket("192.168.1.1", "d0:21:f9:5e:35:32")],
            store,
        )

        refresh_device_registry(_app(client))

        assert client.store[udm]["ips"] == ["192.168.1.1"]
        assert client.store[udm]["category"] == "infrastructure"  # rest of the doc kept
        assert client.store["CC:F4:11:B4:7F:68"]["ips"] == ["192.168.1.164"]
        assert client.store["AA:BB:CC:00:00:05"]["ips"] == ["192.168.1.116"]


class TestCategoryLikeDevicesPage:
    """#26: Home's grid (the registry) files devices the way the Devices page does."""

    def test_os_hint_hostname_and_vendor_decide(self):
        fingerprint = MagicMock()
        fingerprint.get_os_hint.side_effect = lambda client, ip, f, t: {"192.168.1.10": "Linux"}.get(ip)
        store = {"2A:37:F4:D9:20:F5": {"mac": "2A:37:F4:D9:20:F5", "ips": [], "hostnames": ["saras-macbook-air-2.local"], "category": "unknown"}}
        client = _fake_client(
            [
                _bucket("192.168.1.10", "fc:9d:05:98:2a:be"),  # OS hint: Linux
                _bucket("192.168.1.116", "2a:37:f4:d9:20:f5"),  # hostname: macbook
                _bucket("192.168.1.191", "ce:bd:0e:fa:4d:42"),  # nothing known
            ],
            store,
        )
        app = {**_app(client), "device_fingerprint": fingerprint}

        refresh_device_registry(app)

        assert client.store["FC:9D:05:98:2A:BE"]["category"] == "computer"
        assert client.store["2A:37:F4:D9:20:F5"]["category"] == "computer"
        assert client.store["CE:BD:0E:FA:4D:42"]["category"] == "unknown"
