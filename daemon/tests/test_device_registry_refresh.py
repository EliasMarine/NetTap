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


LAST_RECORD = "2026-11-02T21:30:00+00:00"


def _bucket(
    ip: str,
    mac: str | list[str] | None,
    oui: str | None = None,
    last: str = LAST_RECORD,
) -> dict:
    """A conn terms bucket as OpenSearch returns it for _conn_devices_query."""
    source = {"mac": mac, **({"oui": oui} if oui else {})}
    macs = (
        []
        if mac is None
        else [
            {
                "key": "x",
                "doc_count": 12,
                "latest": {"hits": {"hits": [{"_source": {"source": source}}]}},
            }
        ]
    )
    last_ms = datetime.fromisoformat(last).timestamp() * 1000
    return {
        "key": ip,
        "doc_count": 12,
        "with_mac": {"doc_count_error_upper_bound": 0, "buckets": macs},
        "last_record": {"value": last_ms, "value_as_string": last},
    }


def _fake_client(buckets: list[dict], store: dict | None = None) -> MagicMock:
    """OpenSearch client mock: get/index use an in-memory store, search serves conn buckets.

    Like OpenSearch, get by id sees every write but a search sees the store only as of
    the last refresh (indices.refresh or a refresh= write).
    """
    client = MagicMock()
    client.indices.exists.return_value = True
    client.store = {} if store is None else store
    client.searchable = copy.deepcopy(client.store)

    def make_searchable(**_kwargs) -> None:
        client.searchable = copy.deepcopy(client.store)

    def get(index: str, id: str) -> dict:
        if id not in client.store:
            raise NotFoundError(404, "not_found", {})
        return {"_source": copy.deepcopy(client.store[id])}

    def index(index: str, id: str, body: dict, refresh: str | None = None) -> dict:
        client.store[id] = copy.deepcopy(body)
        if refresh:
            make_searchable()
        return {"result": "created"}

    def search(index: str, body: dict) -> dict:
        aggs = body.get("aggs", {})
        if "devices" in aggs:  # a terms list, top `size` like OpenSearch
            return {
                "aggregations": {
                    "devices": {"buckets": buckets[: aggs["devices"]["terms"]["size"]]}
                }
            }
        if "all" in aggs:  # a composite, page by page in key order
            composite = aggs["all"]["composite"]
            after = (composite.get("after") or {}).get("ip")
            rest = [
                b
                for b in sorted(buckets, key=lambda b: b["key"])
                if after is None or b["key"] > after
            ]
            page = [{**b, "key": {"ip": b["key"]}} for b in rest[: composite["size"]]]
            return {
                "aggregations": {
                    "all": {
                        "buckets": page,
                        **({"after_key": page[-1]["key"]} if page else {}),
                    }
                }
            }
        if "match_all" in body.get("query", {}):  # registry listing
            return {
                "hits": {
                    "hits": [
                        {"_source": copy.deepcopy(d)}
                        for d in client.searchable.values()
                    ]
                }
            }
        return {"hits": {"hits": []}}

    def delete(index: str, id: str) -> dict:
        client.store.pop(id)
        return {"result": "deleted"}

    client.get.side_effect = get
    client.index.side_effect = index
    client.delete.side_effect = delete
    client.search.side_effect = search
    client.indices.refresh.side_effect = make_searchable
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
        # OLD CODE START — #96: the refresh's terms search became a composite
        # if "devices" in call.kwargs["body"].get("aggs", {}):
        # OLD CODE END
        if "all" in call.kwargs["body"].get("aggs", {}):
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
        # OLD CODE START — #96: a terms list of _MAX_DEVICE_LIMIT IPs
        # terms = body["aggs"]["devices"]["terms"]
        # assert terms == {
        #     "field": "source.ip",
        #     "size": _MAX_DEVICE_LIMIT,
        #     "min_doc_count": _MIN_CONNECTIONS,
        # }
        # OLD CODE END
        assert body["aggs"]["all"]["composite"]["sources"] == [
            {"ip": {"terms": {"field": "source.ip"}}}
        ]

    def test_ips_under_min_connections_are_not_devices(self):
        quiet = {
            **_bucket("192.168.1.10", "aa:bb:cc:00:00:01"),
            "doc_count": _MIN_CONNECTIONS - 1,
        }
        client = _fake_client([quiet])

        assert refresh_device_registry(_app(client)) == 0

    def test_registers_past_500_devices(self):
        """#96: the refresh kept a terms list of 500 IPs; devices past it were never registered."""
        ips = [
            f"192.168.{i // 200}.{i % 200 + 1}" for i in range(_MAX_DEVICE_LIMIT + 100)
        ]
        client = _fake_client(
            [
                _bucket(ip, f"aa:bb:cc:00:{i // 256:02x}:{i % 256:02x}")
                for i, ip in enumerate(ips)
            ]
        )

        assert refresh_device_registry(_app(client)) == len(ips)
        assert len(client.store) == len(ips)

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


class TestLastSeenIsTheLastRecord:
    """Home said "last seen 4m ago" for devices last heard 24 min or 17 h earlier: every
    registry update, a vendor or OS lookup included, set last_seen to the time it ran."""

    def test_last_seen_is_the_devices_last_record_not_the_refresh_time(self):
        client = _fake_client(
            [
                _bucket(
                    "192.168.1.20",
                    "aa:bb:cc:00:00:01",
                    last="2026-11-02T21:05:00+00:00",
                )
            ]
        )

        refresh_device_registry(_app(client))

        doc = client.store["AA:BB:CC:00:00:01"]
        assert doc["last_seen"] == "2026-11-02T21:05:00+00:00"
        assert doc["first_seen"] == "2026-11-02T21:05:00+00:00"

    def test_an_older_record_does_not_move_last_seen_back(self):
        newer = "2026-11-02T21:40:00+00:00"
        store = {
            "AA:BB:CC:00:00:01": {
                "mac": "AA:BB:CC:00:00:01",
                "ips": ["192.168.1.20"],
                "category": "unknown",
                "first_seen": "2026-11-01T00:00:00+00:00",
                "last_seen": newer,
            }
        }
        client = _fake_client(
            [
                _bucket(
                    "192.168.1.20",
                    "aa:bb:cc:00:00:01",
                    last="2026-11-02T21:05:00+00:00",
                )
            ],
            store,
        )

        refresh_device_registry(_app(client))

        assert client.store["AA:BB:CC:00:00:01"]["last_seen"] == newer

    def test_a_vendor_lookup_leaves_last_seen_alone(self):
        quiet = "2026-11-02T04:00:00+00:00"
        mac = "70:A7:41:3F:1B:59"
        store = {
            mac: {
                "mac": mac,
                "ips": ["192.168.1.220"],
                "manufacturer": None,
                "category": "unknown",
                "first_seen": quiet,
                "last_seen": quiet,
                "enrichment_sources": {},
            }
        }
        client = _fake_client([], store)
        mac_lookup = MagicMock()
        mac_lookup.lookup.return_value = {"found": True, "vendor": "Ubiquiti Inc"}

        refresh_device_registry({**_app(client), "mac_lookup": mac_lookup})

        assert client.store[mac]["manufacturer"] == "Ubiquiti Inc"
        assert client.store[mac]["last_seen"] == quiet


class TestCorrectLastSeen:
    """Installs that ran the old code keep last_seen values stamped by a lookup, later than
    any record; last_seen only moves forward, so a quiet device would keep one for good."""

    @staticmethod
    def _client(store: dict, newest: dict[str, str]) -> MagicMock:
        client = _fake_client([], store)
        serve = client.search.side_effect

        def search(index: str, body: dict) -> dict:
            if "newest" not in body.get("aggs", {}):
                return serve(index=index, body=body)
            mac = body["query"]["bool"]["should"][1]["term"]["source.mac"]
            value = (
                datetime.fromisoformat(newest[mac]).timestamp() * 1000
                if mac in newest
                else None
            )
            return {"aggregations": {"newest": {"value": value}}}

        client.search.side_effect = search
        return client

    def test_a_last_seen_later_than_every_record_moves_back_to_the_newest_record(self):
        mac, real = "FC:9D:05:98:2A:BE", "2026-11-02T05:10:00+00:00"
        store = {
            mac: {
                "mac": mac,
                "ips": ["192.168.1.10"],
                "category": "computer",
                "first_seen": "2026-11-02T08:04:00+00:00",
                "last_seen": "2026-11-02T08:51:00+00:00",
            }
        }
        client = self._client(store, {mac.lower(): real})

        assert DeviceRegistry(client=client).correct_last_seen() == 1
        assert (client.store[mac]["last_seen"], client.store[mac]["first_seen"]) == (
            real,
            real,
        )

    def test_a_last_seen_at_or_before_the_newest_record_and_aged_out_devices_are_left_alone(
        self,
    ):
        ok, gone = "AA:00:00:00:00:01", "AA:00:00:00:00:02"
        store = {
            ok: {
                "mac": ok,
                "ips": ["192.168.1.20"],
                "first_seen": "2026-11-01T00:00:00+00:00",
                "last_seen": "2026-11-02T21:00:00+00:00",
            },
            gone: {
                "mac": gone,
                "ips": ["192.168.1.21"],
                "first_seen": "2026-10-01T00:00:00+00:00",
                "last_seen": "2026-10-02T00:00:00+00:00",
            },
        }
        client = self._client(store, {ok.lower(): "2026-11-02T21:30:00+00:00"})

        assert DeviceRegistry(client=client).correct_last_seen() == 0
        client.index.assert_not_called()


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

    def test_last_seen_is_corrected_once_at_start_and_a_failure_does_not_stop_refreshes(
        self, monkeypatch
    ):
        registry = MagicMock()
        registry.correct_last_seen.side_effect = RuntimeError("OpenSearch not ready")

        async def scenario() -> int:
            loop = asyncio.get_running_loop()
            shutdown = asyncio.Event()
            refreshes = []

            def refresh(app: dict) -> int:
                refreshes.append(app)
                if len(refreshes) == 2:
                    loop.call_soon_threadsafe(shutdown.set)
                return 0

            monkeypatch.setattr(main, "refresh_device_registry", refresh)
            await asyncio.wait_for(
                main.device_registry_loop(
                    {"device_registry": registry}, 0.01, shutdown
                ),
                timeout=5,
            )
            return len(refreshes)

        assert asyncio.run(scenario()) == 2
        assert registry.correct_last_seen.call_count == 1


class TestLanSubnetsFollowTheNetwork:
    """#116: LAN detection ran only at startup, so a subnet first seen later (here a
    10.10.0.x network on the G11) was in no device count and the registry never got
    its devices' IPs until the daemon restarted."""

    def _run(self, monkeypatch, detected, manual=""):
        from services import excluded_ips

        monkeypatch.setenv("LAN_SUBNETS", manual)
        monkeypatch.setattr(main, "LAN_REDETECT_INTERVAL_S", 0)  # hourly in the daemon
        monkeypatch.setattr(excluded_ips, "detect_lan_subnets", lambda client: detected)
        lan_filter = excluded_ips.build_lan_filter([(192, 168, 1)])
        before = dict(lan_filter)
        seen: list[dict] = []

        async def scenario() -> None:
            loop = asyncio.get_running_loop()
            shutdown = asyncio.Event()

            def refresh(app: dict) -> int:
                seen.append(dict(app["lan_filter"]))
                loop.call_soon_threadsafe(shutdown.set)
                return 0

            monkeypatch.setattr(main, "refresh_device_registry", refresh)
            app = {"lan_filter": lan_filter, "storage": MagicMock()}
            await asyncio.wait_for(
                main.device_registry_loop(app, 0.01, shutdown), timeout=5
            )

        asyncio.run(scenario())
        return before, lan_filter, seen

    def test_a_new_subnet_is_counted_before_the_registry_pass(self, monkeypatch):
        from services.excluded_ips import build_lan_filter

        _, lan_filter, seen = self._run(monkeypatch, [(192, 168, 1), (10, 10, 0)])
        assert lan_filter == build_lan_filter([(192, 168, 1), (10, 10, 0)])
        assert seen == [
            lan_filter
        ]  # the same dict every handler reads, updated before the pass

    def test_the_filter_is_never_empty_while_it_changes(self, monkeypatch):
        """#139: slow handlers now read this dict from worker threads; clear() then update()
        left it empty in between, and a query built then had an empty clause."""
        from services import excluded_ips

        sizes: list[int] = []

        class Recording(dict):
            def clear(self):
                super().clear()
                sizes.append(len(self))

            def update(self, *args, **kwargs):
                super().update(*args, **kwargs)
                sizes.append(len(self))

            def __delitem__(self, key):
                super().__delitem__(key)
                sizes.append(len(self))

        lan_filter = Recording(excluded_ips.build_lan_filter([(192, 168, 1)]))
        new = excluded_ips.build_lan_filter([(192, 168, 1), (10, 10, 0)])
        monkeypatch.setattr(main, "changed_lan_filter", lambda client, current: new)

        async def scenario() -> None:
            app = {"lan_filter": lan_filter, "storage": MagicMock()}
            await main._redetect_lan(app, asyncio.get_running_loop())

        asyncio.run(scenario())

        assert lan_filter == new
        assert sizes and min(sizes) > 0

    def test_failed_detection_keeps_the_subnets(self, monkeypatch):
        before, lan_filter, _ = self._run(
            monkeypatch, []
        )  # not the all-RFC1918 fallback
        assert lan_filter == before

    def test_manual_subnets_are_never_replaced(self, monkeypatch):
        before, lan_filter, _ = self._run(
            monkeypatch, [(10, 10, 0)], manual="192.168.1.0/24"
        )
        assert lan_filter == before


class TestVendorFromMalcolm:
    """#26: the registry takes Malcolm's IEEE vendor and the category it implies."""

    def test_registers_vendor_and_category(self):
        hue = _bucket("192.168.1.154", "00:17:88:48:3c:07", "Philips Lighting BV")
        apple = _bucket("192.168.1.95", "7c:01:3e:74:d2:1c", "Apple, Inc.")
        client = _fake_client(
            [hue, apple, _bucket("192.168.1.151", "0e:cc:55:a1:28:66")]
        )

        refresh_device_registry(_app(client))

        assert "source.oui" in str(_conn_query(client)[1])
        hue_doc = client.store["00:17:88:48:3C:07"]
        assert (hue_doc["manufacturer"], hue_doc["category"]) == (
            "Philips Lighting BV",
            "iot",
        )
        apple_doc = client.store["7C:01:3E:74:D2:1C"]
        assert (apple_doc["manufacturer"], apple_doc["category"]) == (
            "Apple, Inc.",
            "unknown",
        )
        assert (
            client.store["0E:CC:55:A1:28:66"]["manufacturer"] is None
        )  # randomized MAC

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
        # OLD CODE START — #96: the terms search became a composite
        # with_mac = _conn_query(client)[1]["aggs"]["devices"]["aggs"]["with_mac"]
        # OLD CODE END
        with_mac = _conn_query(client)[1]["aggs"]["all"]["aggs"]["with_mac"]
        assert with_mac["terms"] == {"field": "source.mac", "size": 1}

    def test_ip_moves_off_the_router_and_0000_is_dropped(self):
        udm = "D0:21:F9:5E:35:32"
        store = {
            udm: {
                "mac": udm,
                "ips": ["192.168.1.1", "192.168.1.164"],
                "category": "infrastructure",
            },
            "AA:BB:CC:00:00:05": {
                "mac": "AA:BB:CC:00:00:05",
                "ips": ["0.0.0.0", "192.168.1.116"],
            },
        }
        client = _fake_client(
            [
                _bucket("192.168.1.164", "cc:f4:11:b4:7f:68"),
                _bucket("192.168.1.1", "d0:21:f9:5e:35:32"),
            ],
            store,
        )

        refresh_device_registry(_app(client))

        assert client.store[udm]["ips"] == ["192.168.1.1"]
        assert client.store[udm]["category"] == "infrastructure"  # rest of the doc kept
        assert client.store["CC:F4:11:B4:7F:68"]["ips"] == ["192.168.1.164"]
        assert client.store["AA:BB:CC:00:00:05"]["ips"] == ["192.168.1.116"]


class TestCategoryLikeDevicesPage:
    """#26: Home's grid (the registry) files devices the way the Devices page does."""

    def test_os_hint_hostnames_and_vendor_decide(self):
        fingerprint = MagicMock()
        fingerprint.get_os_hint.side_effect = lambda client, ip, f, t: {
            "192.168.1.10": "Linux"
        }.get(ip)
        fingerprint.get_hostname_for_ip.side_effect = lambda client, ip, f, t: {
            "192.168.1.95": "elias-mac-studio.local"
        }.get(ip)
        quiet = {
            "mac": "70:A7:41:3F:1B:59",
            "ips": ["192.168.1.220"],
            "manufacturer": "Ubiquiti Inc",
            "category": "unknown",
            "last_seen": "2026-11-02T04:00:00+00:00",
        }
        store = {
            "2A:37:F4:D9:20:F5": {
                "mac": "2A:37:F4:D9:20:F5",
                "ips": [],
                "hostnames": ["saras-macbook-air-2.local"],
                "category": "unknown",
            },
            "70:A7:41:3F:1B:59": quiet,  # not seen this hour: vendor still decides, last_seen kept
        }
        client = _fake_client(
            [
                _bucket("192.168.1.10", "fc:9d:05:98:2a:be"),  # OS hint: Linux
                _bucket("192.168.1.95", "7e:e8:ae:7a:dd:5b"),  # DNS name: mac-studio
                _bucket("192.168.1.191", "ce:bd:0e:fa:4d:42"),  # nothing known
            ],
            store,
        )

        refresh_device_registry({**_app(client), "device_fingerprint": fingerprint})

        assert client.store["FC:9D:05:98:2A:BE"]["category"] == "computer"
        assert client.store["7E:E8:AE:7A:DD:5B"]["category"] == "computer"
        assert client.store["2A:37:F4:D9:20:F5"]["category"] == "computer"
        assert client.store["CE:BD:0E:FA:4D:42"]["category"] == "unknown"
        assert client.store["70:A7:41:3F:1B:59"]["category"] == "infrastructure"
        assert client.store["70:A7:41:3F:1B:59"]["last_seen"] == quiet["last_seen"]


class TestRefreshSpeed:
    """The refresh took ~1 min because every device write waited ~1 s for an index refresh."""

    def test_writes_skip_wait_for_and_each_pass_still_reads_fresh_docs(self):
        old = "2026-11-01T00:00:00+00:00"
        mac = "00:17:88:48:3C:07"
        # Known device that held .154 and .155; this hour it is seen on .154 only
        store = {
            mac: {
                "mac": mac,
                "ips": ["192.168.1.154", "192.168.1.155"],
                "category": "unknown",
                "manufacturer": None,
                "first_seen": old,
                "last_seen": old,
                "enrichment_sources": {},
            }
        }
        client = _fake_client(
            [
                _bucket("192.168.1.154", "00:17:88:48:3c:07", "Philips Lighting BV"),
                _bucket("192.168.1.155", "cc:f4:11:b4:7f:68"),
            ],
            store,
        )
        mac_lookup = MagicMock()
        mac_lookup.lookup.return_value = {"found": False}

        refresh_device_registry({**_app(client), "mac_lookup": mac_lookup})

        assert all(not c.kwargs.get("refresh") for c in client.index.call_args_list)
        doc = client.store[mac]
        # A pass that read a stale listing would write the old doc back over this refresh's
        assert doc["last_seen"] > old
        assert doc["ips"] == ["192.168.1.154"]
        assert (doc["manufacturer"], doc["category"]) == ("Philips Lighting BV", "iot")


class TestLongMacs:
    """#76: Zeek printed a UniFi AP's DHCP chaddr as 8 bytes, which became a second device."""

    def test_dhcp_mac_longer_than_6_octets_files_under_the_real_device(self):
        assert (
            DeviceRegistry._normalize_mac("f4:e2:c6:ff:98:21:62:72")
            == "F4:E2:C6:FF:98:21"
        )
        assert DeviceRegistry._normalize_mac("f4-e2-c6-ff-98-21") == "F4:E2:C6:FF:98:21"

    def test_existing_long_entry_merges_into_the_real_device(self):
        real = {
            "mac": "F4:E2:C6:FF:98:21",
            "ips": ["192.168.1.198"],
            "hostnames": ["U7Pro"],
            "category": "infrastructure",
            "last_seen": "2026-11-02T10:16:31+00:00",
        }
        phantom = {
            "mac": "F4:E2:C6:FF:98:21:62:72",
            "ips": ["192.168.40.198"],
            "hostnames": ["U7Pro"],
            "category": "unknown",
            "last_seen": "2026-11-02T06:45:37+00:00",
        }
        orphan = {
            "mac": "AA:BB:CC:00:00:01:02:03",
            "ips": ["10.10.0.9"],
            "last_seen": "2026-11-02T05:00:00+00:00",
        }
        client = _fake_client(
            [], {real["mac"]: real, phantom["mac"]: phantom, orphan["mac"]: orphan}
        )

        refresh_device_registry(_app(client))

        assert set(client.store) == {"F4:E2:C6:FF:98:21", "AA:BB:CC:00:00:01"}
        ap = client.store["F4:E2:C6:FF:98:21"]
        assert ap["ips"] == ["192.168.1.198", "192.168.40.198"]
        assert ap["hostnames"] == ["U7Pro"]
        assert (ap["category"], ap["last_seen"]) == (
            "infrastructure",
            real["last_seen"],
        )
        assert client.store["AA:BB:CC:00:00:01"]["ips"] == [
            "10.10.0.9"
        ]  # no real entry: renamed
