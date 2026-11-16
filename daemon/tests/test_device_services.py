"""PR B: each listed device's registry first seen (known_since).

`known_since` comes from the same registry read as the names, keyed by the row's effective
MAC (the fingerprint's, else the bucket's).
"""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock

from aiohttp.test_utils import AioHTTPTestCase

from api.devices import (
    _registry_known,
    _registry_names,
    register_device_routes,
)
from services.device_fingerprint import DeviceFingerprint
from services.excluded_ips import build_lan_filter
from tests.fake_drill_opensearch import (
    AUTH,
    FROM,
    TO,
    WINDOW,
    DrillOpenSearch,
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
