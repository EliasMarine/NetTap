"""PR B: each listed device's registry first seen (known_since) and commonest protocols (services).

`known_since` comes from the same registry read as the names, keyed by the row's effective
MAC (the fingerprint's, else the bucket's). `services` is one separate search over the listed
IPs, both sides of their IPv4 connections, read after the list is cut. It is an extra: if it
fails the list still answers, with services None on every row.
"""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock

from aiohttp.test_utils import AioHTTPTestCase
from opensearchpy import TransportError

from api.devices import (
    SERVICES_PER_SIDE,
    _conn_filters,
    _device_services,
    _registry_known,
    _registry_names,
    register_device_routes,
)
from services.device_fingerprint import DeviceFingerprint
from services.excluded_ips import build_lan_filter
from storage.snapshot_search import QueryFailed
from tests.fake_drill_opensearch import (
    AUTH,
    FROM,
    TO,
    WINDOW,
    DrillOpenSearch,
    alert,
    conn,
    make_app,
)
from tests.test_devices_api import _registry_with

LAN = build_lan_filter([(192, 168, 1)])
LAPTOP, NAS, TV = "192.168.1.30", "192.168.1.40", "192.168.1.50"
M_LAPTOP, M_NAS, M_TV = "00:00:5e:00:53:30", "00:00:5e:00:53:40", "00:00:5e:00:53:50"
NET_A, OUTSIDER = "203.0.113.5", "198.51.100.7"
STUDY = "2026-09-01T08:00:00+00:00"
NAS_FIRST = "2026-10-12T19:30:00+00:00"


def _at(minute: int) -> str:
    return f"2026-11-05T10:{minute:02d}:00.000Z"


def _conns(src, dst, protocol, n, src_mac=None, dst_mac=None, minute=0, nbytes=10):
    return [
        conn(
            src,
            dst,
            _at(minute + i % 50),
            source__bytes=nbytes,
            destination__bytes=20,
            destination__packets=1,
            network__transport="tcp",
            network__protocol=protocol,
            **({"source__mac": src_mac} if src_mac else {}),
            **({"destination__mac": dst_mac} if dst_mac else {}),
        )
        for i in range(n)
    ]


def _registry_device(mac: str, name: str, first_seen: str) -> dict:
    return {
        "mac": mac,
        "hostnames": [name],
        "enrichment_sources": {"dhcp": {"hostname": name}},
        "first_seen": first_seen,
    }


class ListCase(AioHTTPTestCase):
    docs: list = []
    lan = LAN
    tamper = None
    registry = None

    async def get_application(self):
        self.os = DrillOpenSearch(self.docs, tamper=self.tamper)
        return make_app(self.os, self._register, lan_filter=self.lan)

    def _register(self, app, client):
        storage = SimpleNamespace(_client=client)
        app["storage"] = storage
        if self.registry is not None:
            app["device_registry"] = self.registry
        register_device_routes(app, storage)

    async def rows(self, query: str = "") -> dict:
        resp = await self.client.get(f"/api/devices?{WINDOW}{query}", headers=AUTH)
        body = await resp.json()
        self.assertEqual(resp.status, 200, body)
        return {d["ip"]: d for d in body["devices"]}


# ---------------------------------------------------------------------------
# known_since
# ---------------------------------------------------------------------------

M_LAPTOP_DASHED = "00-00-5E-00-53-30"
KNOWN_DOCS = [
    *_conns(LAPTOP, NET_A, "ssl", 4, src_mac=M_LAPTOP_DASHED),
    *_conns(TV, NET_A, "quic", 3, src_mac=M_TV),
    *_conns(LAPTOP, NAS, "http", 3, src_mac=M_LAPTOP_DASHED, dst_mac=M_NAS),
]


class TestKnownSince(ListCase):
    docs = KNOWN_DOCS
    registry = _registry_with(
        {
            "00:00:5E:00:53:30": _registry_device(
                "00:00:5E:00:53:30", "Study-laptop", STUDY
            ),
            "00:00:5E:00:53:40": _registry_device(
                "00:00:5E:00:53:40", "Media-NAS", NAS_FIRST
            ),
        }
    )

    async def test_from_the_registry_by_normalized_mac(self):
        rows = await self.rows()
        self.assertEqual(rows[LAPTOP]["mac"], M_LAPTOP_DASHED)
        self.assertEqual(rows[LAPTOP]["known_since"], STUDY)
        self.assertEqual(rows[LAPTOP]["hostname"], "Study-laptop")

    async def test_none_for_a_mac_the_registry_doesnt_know(self):
        rows = await self.rows()
        self.assertEqual(rows[TV]["mac"], M_TV)
        self.assertIsNone(rows[TV]["known_since"])

    async def test_an_answer_only_device_uses_its_bucket_mac(self):
        # the fingerprint finds no MAC for the NAS: it never started a connection
        lookups = DeviceFingerprint().lookup_many(self.os, [NAS], FROM, TO)
        self.assertIsNone(lookups.get(NAS, (None,))[0])
        rows = await self.rows()
        self.assertEqual(rows[NAS]["mac"], M_NAS)
        self.assertEqual(rows[NAS]["known_since"], NAS_FIRST)
        self.assertEqual(rows[NAS]["hostname"], "Media-NAS")


def _broken_registry() -> MagicMock:
    registry = MagicMock()
    registry.get_devices.side_effect = RuntimeError("registry index unavailable")
    return registry


class TestKnownSinceRegistryDown(ListCase):
    docs = KNOWN_DOCS
    registry = _broken_registry()

    async def test_none_everywhere_and_the_list_still_answers(self):
        rows = await self.rows()
        self.assertEqual(set(rows), {LAPTOP, NAS, TV})
        self.assertEqual({d["known_since"] for d in rows.values()}, {None})
        # one read feeds both names and known_since, so a failure is not asked twice
        self.registry.get_devices.assert_called_once()


class TestRegistryNames(TestCase):
    """The device page still asks _registry_names on its own; the list hands it its reading."""

    def test_the_same_names_with_or_without_a_reading(self):
        registry = _registry_with(
            {"00:00:5E:00:53:40": _registry_device(M_NAS, "Media-NAS", NAS_FIRST)}
        )
        request = SimpleNamespace(app={"device_registry": registry})
        alone = _registry_names(request, [M_NAS])
        shared = _registry_names(request, [M_NAS], _registry_known(request, [M_NAS]))
        self.assertEqual(alone, {"00:00:5E:00:53:40": "Media-NAS"})
        self.assertEqual(shared, alone)

    def test_a_failed_read_is_no_names(self):
        request = SimpleNamespace(app={"device_registry": _broken_registry()})
        self.assertEqual(_registry_known(request, [M_NAS]), {})
        self.assertEqual(_registry_names(request, [M_NAS]), {})


# ---------------------------------------------------------------------------
# services
# ---------------------------------------------------------------------------

# The laptop browses (ssl) and streams from the NAS (http); the NAS only answers, plus one
# ntp it never started; an outsider's dns is no listed device's
DOCS = [
    *_conns(LAPTOP, NET_A, "ssl", 4, src_mac=M_LAPTOP),
    *_conns(LAPTOP, NAS, "http", 3, src_mac=M_LAPTOP, dst_mac=M_NAS),
    *_conns(NET_A, NAS, "ntp", 1, dst_mac=M_NAS),
    *_conns(OUTSIDER, NET_A, "dns", 5),
]


def _is_services(body: dict) -> bool:
    return "by_ip" in (body.get("aggs", {}).get("started") or {}).get("aggs", {})


def _side(per_ip: dict, other: int = 0) -> dict:
    """One side of a services reply from {ip: ({protocol: count}, that IP's cut count)}."""
    return {
        "doc_count": 1,
        "by_ip": {
            "sum_other_doc_count": other,
            "buckets": [
                {
                    "key": ip,
                    "doc_count": sum(counts.values()),
                    "services": {
                        "sum_other_doc_count": cut,
                        "buckets": [
                            {"key": p, "doc_count": n} for p, n in counts.items()
                        ],
                    },
                }
                for ip, (counts, cut) in per_ip.items()
            ],
        },
    }


def _reply(started: dict, answered: dict) -> dict:
    return {
        "timed_out": False,
        "_shards": {"total": 1, "failed": 0},
        "aggregations": {"started": started, "answered": answered},
    }


def _client(reply: dict) -> MagicMock:
    client = MagicMock()
    client.search.return_value = reply
    return client


class TestDeviceServices(TestCase):
    def test_the_body_reads_both_sides_of_the_listed_ips_only(self):
        client = _client(_reply(_side({}), _side({})))
        filters = _conn_filters(FROM, TO)
        _device_services(client, filters, [LAPTOP, NAS], "services")
        body = client.search.call_args.kwargs["body"]
        self.assertEqual(body["size"], 0)
        *window, either = body["query"]["bool"]["filter"]
        self.assertEqual(window, filters)
        self.assertEqual(
            either["bool"]["should"],
            [
                {"terms": {"source.ip": [LAPTOP, NAS]}},
                {"terms": {"destination.ip": [LAPTOP, NAS]}},
            ],
        )
        for side, field in (("started", "source.ip"), ("answered", "destination.ip")):
            agg = body["aggs"][side]
            self.assertEqual(agg["filter"], {"terms": {field: [LAPTOP, NAS]}})
            self.assertEqual(agg["aggs"]["by_ip"]["terms"], {"field": field, "size": 2})
            self.assertEqual(
                agg["aggs"]["by_ip"]["aggs"]["services"]["terms"],
                {"field": "network.protocol", "size": SERVICES_PER_SIDE},
            )

    def test_the_real_query_counts_started_and_answered(self):
        fake = DrillOpenSearch(DOCS)
        got = _device_services(fake, _conn_filters(FROM, TO), [LAPTOP, NAS], "t")
        # the laptop's streams from the NAS count for both of them; the outsider for neither
        self.assertEqual(got, {LAPTOP: ["ssl", "http"], NAS: ["http", "ntp"]})

    def test_both_sides_are_added_before_the_top_three(self):
        # x is 4th on each side but 7 + 9 = 16 is the most combined
        client = _client(
            _reply(
                _side({LAPTOP: ({"a": 10, "b": 9, "c": 8, "x": 7}, 0)}),
                _side({LAPTOP: ({"d": 12, "e": 11, "f": 10, "x": 9}, 0)}),
            )
        )
        got = _device_services(client, [], [LAPTOP], "t")
        self.assertEqual(got, {LAPTOP: ["x", "d", "e"]})

    def test_a_cut_side_makes_that_device_unknown(self):
        client = _client(
            _reply(
                _side({LAPTOP: ({"ssl": 5}, 0), NAS: ({"http": 4}, 0)}),
                _side({NAS: ({"smb": 3}, 2)}),
            )
        )
        got = _device_services(client, [], [LAPTOP, NAS], "t")
        self.assertEqual(got, {LAPTOP: ["ssl"], NAS: None})

    def test_devices_past_the_asked_ones_fail_the_read(self):
        client = _client(_reply(_side({LAPTOP: ({"ssl": 5}, 0)}, other=1), _side({})))
        with self.assertRaises(QueryFailed):
            _device_services(client, [], [LAPTOP], "t")

    def test_a_missing_nested_aggregation_fails_the_read(self):
        no_by_ip = _reply({"doc_count": 0}, _side({}))
        no_services = _reply(_side({LAPTOP: ({"ssl": 5}, 0)}), _side({}))
        del no_services["aggregations"]["started"]["by_ip"]["buckets"][0]["services"]
        no_side = {"_shards": {"failed": 0}, "aggregations": {"started": _side({})}}
        no_count = _reply(_side({LAPTOP: ({"ssl": 5}, 0)}), _side({}))
        del no_count["aggregations"]["started"]["by_ip"]["buckets"][0]["doc_count"]
        text_count = _reply(_side({LAPTOP: ({"ssl": 5}, 0)}), _side({}))
        ssl = text_count["aggregations"]["started"]["by_ip"]["buckets"][0]["services"]
        ssl["buckets"][0]["doc_count"] = "5"
        # review: a dict where the list belongs would iterate to nothing and read as "none"
        dict_by_ip = _reply({"sum_other_doc_count": 0, "buckets": {}}, _side({}))
        dict_services = _reply(_side({LAPTOP: ({"ssl": 5}, 0)}), _side({}))
        dict_services["aggregations"]["started"]["by_ip"]["buckets"][0]["services"] = {
            "buckets": {}
        }
        for reply in (
            no_by_ip,
            no_services,
            no_side,
            no_count,
            text_count,
            dict_by_ip,
            dict_services,
        ):
            with self.assertRaises(QueryFailed):
                _device_services(_client(reply), [], [LAPTOP], "t")

    def test_no_ips_asks_nothing(self):
        client = MagicMock()
        self.assertEqual(_device_services(client, [], [], "t"), {})
        client.search.assert_not_called()


class TestListServices(ListCase):
    docs = DOCS

    async def test_rows_carry_both_sides_protocols(self):
        rows = await self.rows()
        self.assertEqual(
            {ip: d["services"] for ip, d in rows.items()},
            {LAPTOP: ["ssl", "http"], NAS: ["http", "ntp"]},
        )


# More eligible devices than the list's maximum, each with its own bytes, so the top 5 by
# bytes are the last five; five quiet ones have alerts, so the alert sort lists those
MANY = [f"192.168.{i // 250}.{i % 250 + 1}" for i in range(505)]
ALERTED = MANY[:5]
MANY_DOCS = [
    *(d for i, ip in enumerate(MANY) for d in _conns(ip, NET_A, "dns", 3, nbytes=i)),
    *(alert(ip, NET_A, t=_at(1)) for n, ip in enumerate(ALERTED) for _ in range(n + 1)),
]


class TestServicesReadOnlyTheListedDevices(ListCase):
    docs = MANY_DOCS
    lan = build_lan_filter([(192, 168, -1)])

    def _asked(self) -> list[list[str]]:
        return [
            b["aggs"]["started"]["filter"]["terms"]["source.ip"]
            for b in self.os.bodies
            if _is_services(b)
        ]

    async def test_the_bytes_sort(self):
        rows = await self.rows("&limit=5")
        self.assertEqual(set(rows), set(MANY[-5:]))
        self.assertEqual(len(self._asked()), 1)
        self.assertEqual(sorted(self._asked()[0]), sorted(MANY[-5:]))
        self.assertTrue(all(d["services"] == ["dns"] for d in rows.values()))

    async def test_the_alert_sort(self):
        rows = await self.rows("&limit=5&sort=alerts")
        self.assertEqual(set(rows), set(ALERTED))
        self.assertEqual(len(self._asked()), 1)
        self.assertEqual(sorted(self._asked()[0]), sorted(ALERTED))


def _failed_shard(body, reply):
    return (
        {**reply, "_shards": {"total": 1, "failed": 1}} if _is_services(body) else reply
    )


def _transport_error(body, reply):
    if _is_services(body):
        raise TransportError(503, "search_phase_execution_exception")
    return reply


def _without(name):
    """A tamper that takes `name` out of every started-side IP bucket of the services reply."""

    def tamper(body, reply):
        if not _is_services(body):
            return reply
        started = reply["aggregations"]["started"]
        buckets = [
            {k: v for k, v in b.items() if k != name}
            for b in started["by_ip"]["buckets"]
        ]
        by_ip = {**started["by_ip"], "buckets": buckets}
        aggs = {**reply["aggregations"], "started": {**started, "by_ip": by_ip}}
        return {**reply, "aggregations": aggs}

    return tamper


class _ServicesFail(ListCase):
    docs = DOCS

    async def check_services_unknown_everywhere(self):
        rows = await self.rows()
        self.assertEqual(set(rows), {LAPTOP, NAS})
        self.assertEqual({d["services"] for d in rows.values()}, {None})
        # the rest of the row is untouched
        self.assertEqual(rows[NAS]["mac"], M_NAS)


class TestServicesQueryFailed(_ServicesFail):
    tamper = staticmethod(_failed_shard)

    async def test_is_200_with_services_unknown(self):
        await self.check_services_unknown_everywhere()


class TestServicesTransportError(_ServicesFail):
    tamper = staticmethod(_transport_error)

    async def test_is_200_with_services_unknown(self):
        await self.check_services_unknown_everywhere()


class TestServicesMalformed(_ServicesFail):
    tamper = staticmethod(_without("services"))

    async def test_is_200_with_services_unknown(self):
        await self.check_services_unknown_everywhere()


class TestServicesBucketWithoutKey(_ServicesFail):
    tamper = staticmethod(_without("key"))

    async def test_is_200_with_services_unknown(self):
        await self.check_services_unknown_everywhere()
