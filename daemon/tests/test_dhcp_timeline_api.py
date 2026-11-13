"""GET /api/dhcp/timeline (NET-263): one device's DHCP transactions and their server endpoints.

The documents are the G11's own dhcp.log and conn.log records (2026-11-13, a UniFi U6-LR and a
Mac), moved into the test window; the evaluator fake runs the real queries over them.
"""

from unittest.mock import patch

import pytest
from aiohttp.test_utils import AioHTTPTestCase
from opensearchpy import ConnectionError as OpenSearchConnectionError
from opensearchpy import ConnectionTimeout

from api.dhcp_timeline import (
    BAD_MAC,
    canonical_mac,
    outcome,
    register_dhcp_timeline_routes,
)
from api.drilldown_runner import zeek
from storage.exact_terms import PartialResultsError, SearchTimedOut
from storage.snapshot_search import Budget
from tests.fake_drill_opensearch import AUTH, WINDOW, DrillOpenSearch, make_app

U6 = "78:45:58:ed:b2:e9"
MAC = "2a:37:f4:d9:20:f5"
OTHER = "74:ac:b9:a7:c9:b2"
ROUTER, VLAN40 = "192.168.1.1", "192.168.40.1"
PATH = "/api/dhcp/timeline"


def dhcp(t, mac, uids, msg_types, src=None, server=None, **fields) -> dict:
    """A Zeek dhcp.log record as Malcolm indexes it (zeek.dhcp.*, client source.ip, server_addr)."""
    doc = {
        "@timestamp": t,
        "event.provider": "zeek",
        "event.dataset": "dhcp",
        "log.file.path": "dhcp.log",
        "zeek.uid": uids,
        "zeek.dhcp.mac": mac,
        "zeek.dhcp.msg_types": msg_types,
        "source.port": 68,
        "destination.port": 67,
        **{f"zeek.dhcp.{k}": v for k, v in fields.items()},
    }
    if src:
        doc["source.ip"] = src
    if server:
        doc["destination.ip"] = server
    return doc


def conn(uid, src, sport, dst, dport, dataset="conn", path="conn.log") -> dict:
    return {
        "@timestamp": "2026-11-05T09:00:00.000Z",
        "event.provider": "zeek",
        "event.dataset": dataset,
        "log.file.path": path,
        "zeek.uid": uid,
        "source.ip": src,
        "source.port": sport,
        "destination.ip": dst,
        "destination.port": dport,
    }


DOCS = [
    # The U6-LR's DORA: Zeek's msg_types out of order; the broadcast connection is shared
    dhcp(
        "2026-11-05T10:37:46.191000064Z",
        U6,
        ["CGCkLG3QHqvdGkXpK8", "CmQg8T3eqcXHEWx4e5"],
        ["OFFER", "DISCOVER", "ACK", "REQUEST"],
        src="192.168.1.138",
        server=ROUTER,
        lease_time=86400.0,
        requested_ip="192.168.1.138",
        assigned_ip="192.168.1.138",
        host_name="U6-LR",
        client_software="ubnt",
        duration=0.023529052734375,
    ),
    conn("CGCkLG3QHqvdGkXpK8", "0.0.0.0", 68, "255.255.255.255", 67),
    conn("CmQg8T3eqcXHEWx4e5", "192.168.1.138", 68, ROUTER, 67),
    # the same broadcast connection in another device's transaction
    dhcp(
        "2026-11-05T10:36:50.557999936Z",
        OTHER,
        ["CGCkLG3QHqvdGkXpK8", "CfXxYo22NMnXjbx9m7"],
        ["DISCOVER", "OFFER", "REQUEST", "ACK"],
        src="192.168.1.89",
        server=ROUTER,
    ),
    # Its renewal on VLAN 40, two seconds earlier
    dhcp(
        "2026-11-05T10:37:44.756Z",
        U6,
        ["ClupXu27QLeXuEw8Ja"],
        ["REQUEST", "ACK"],
        src="192.168.40.140",
        server=VLAN40,
        lease_time=86400.0,
        assigned_ip="192.168.40.140",
        host_name="U6-LR",
        client_software="ubnt",
        duration=0.00038313865661621094,
    ),
    conn("ClupXu27QLeXuEw8Ja", "192.168.40.140", 68, VLAN40, 67),
    # a ja4d record shares the uid; it isn't a connection
    conn("ClupXu27QLeXuEw8Ja", "192.168.40.140", 68, "192.0.2.66", 67, "ja4d", "ja4d.log"),
    # A renewal NAKed: the server answers from port 67 to the broadcast address, no server_addr
    dhcp(
        "2026-11-05T08:37:43.156Z",
        U6,
        ["C2bnisGUlez2bctsb", "CzrQcE44MCh5ZseACa"],
        ["REQUEST", "NAK"],
        src="192.168.1.139",
        host_name="U6-LR",
        client_software="ubnt",
        server_message="lease not found",
        duration=0.0004949569702148438,
    ),
    conn("C2bnisGUlez2bctsb", "192.168.1.139", 68, ROUTER, 67),
    conn("CzrQcE44MCh5ZseACa", ROUTER, 67, "255.255.255.255", 68),
    # an interim record for the NAK's connection, from another server: final records only
    conn("CzrQcE44MCh5ZseACa", "192.0.2.77", 67, "255.255.255.255", 68, path="conn_long.log"),
    # outside the window
    dhcp("2026-11-04T23:59:59.000Z", U6, ["Cold"], ["REQUEST", "ACK"]),
]

ACK_DORA = {
    "ts": "2026-11-05T10:37:46.191000064Z",
    "duration": 0.023529052734375,
    "messages": {"ACK": 1, "DISCOVER": 1, "OFFER": 1, "REQUEST": 1},
    "requested_ip": "192.168.1.138",
    "assigned_ip": "192.168.1.138",
    "client_ip": "192.168.1.138",
    "lease_time": 86400.0,
    "host_name": "U6-LR",
    "client_software": "ubnt",
    "zeek_server": ROUTER,
    "server_endpoints": [ROUTER],
    "endpoints_complete": True,
    "server_message": None,
    "outcome": "ack",
}


class Case(AioHTTPTestCase):
    docs: list = DOCS

    async def get_application(self):
        self.os = DrillOpenSearch(self.docs)
        return make_app(self.os, register_dhcp_timeline_routes)

    async def get(self, query: str, headers=AUTH) -> tuple[int, dict]:
        resp = await self.client.get(f"{PATH}?{query}&{WINDOW}", headers=headers)
        return resp.status, await resp.json()


class TestTimeline(Case):
    async def test_the_devices_transactions_newest_first_with_their_server(self):
        status, body = await self.get(f"mac={U6}")
        self.assertEqual(status, 200, body)
        self.assertEqual(
            (body["mac"], body["from"], body["to"], body["truncated"]),
            (U6, "2026-11-05T00:00:00Z", "2026-11-05T12:00:00Z", False),
        )
        dora, renewal, nak = body["transactions"]
        self.assertEqual(dora, ACK_DORA)
        self.assertEqual(
            (renewal["server_endpoints"], renewal["requested_ip"], renewal["outcome"]),
            ([VLAN40], None, "ack"),
        )

    async def test_a_nak_from_port_67_to_broadcast_names_the_sender(self):
        _, body = await self.get(f"mac={U6}")
        nak = body["transactions"][2]
        self.assertEqual(
            (nak["outcome"], nak["messages"], nak["server_endpoints"]),
            ("nak", {"NAK": 1, "REQUEST": 1}, [ROUTER]),
        )
        # no server_addr in the record; the client's address is what it renewed
        self.assertEqual((nak["zeek_server"], nak["client_ip"]), (None, "192.168.1.139"))
        self.assertEqual(nak["server_message"], "lease not found")
        self.assertTrue(nak["endpoints_complete"])

    async def test_any_mac_notation_reads_the_stored_form(self):
        for typed in ("78:45:58:ED:B2:E9", "78-45-58-ed-b2-e9", "7845.58ed.b2e9", f" {U6} "):
            status, body = await self.get(f"mac={typed}")
            self.assertEqual((status, body["mac"], len(body["transactions"])), (200, U6, 3))

    async def test_conn_records_are_read_by_uid_without_a_window(self):
        await self.get(f"mac={U6}")
        records, conns = self.os.bodies
        self.assertIn({"term": {"zeek.dhcp.mac": U6}}, records["query"]["bool"]["filter"])
        self.assertEqual(records["size"], 200)
        self.assertEqual(
            conns["query"]["bool"]["filter"],
            [
                *zeek("conn"),
                {
                    "terms": {
                        "zeek.uid": [
                            "C2bnisGUlez2bctsb",
                            "CGCkLG3QHqvdGkXpK8",
                            "ClupXu27QLeXuEw8Ja",
                            "CmQg8T3eqcXHEWx4e5",
                            "CzrQcE44MCh5ZseACa",
                        ]
                    }
                },
            ],
        )

    async def test_every_read_carries_the_requests_budget(self):
        await self.get(f"mac={U6}")
        self.assertEqual(len(self.os.budgets), 2)
        self.assertTrue(all(isinstance(b, Budget) for b in self.os.budgets))
        self.assertEqual(len({id(b) for b in self.os.budgets}), 1)

    async def test_no_records_is_an_empty_list_and_no_conn_read(self):
        status, body = await self.get("mac=02:00:00:00:00:01")
        self.assertEqual((status, body["transactions"], body["truncated"]), (200, [], False))
        self.assertEqual(len(self.os.bodies), 1)

    async def test_a_mac_that_is_not_six_bytes_is_a_400(self):
        for bad in ("", "f4:e2:c6:ff:98:21:62:72", "78:45:58:ed:b2", "78:45-58:ed:b2:e9", "zz:45:58:ed:b2:e9", "-x"):
            status, body = await self.get(f"mac={bad}")
            self.assertEqual((status, body["error"]), (400, BAD_MAC), bad)
        resp = await self.client.get(PATH, headers=AUTH)
        self.assertEqual(resp.status, 400)
        self.assertEqual(self.os.bodies, [])

    async def test_a_backwards_window_is_a_400(self):
        resp = await self.client.get(
            f"{PATH}?mac={U6}&from=2026-11-05T12:00:00Z&to=2026-11-05T00:00:00Z", headers=AUTH
        )
        self.assertEqual(resp.status, 400)

    async def test_the_route_needs_the_token(self):
        resp = await self.client.get(f"{PATH}?mac={U6}")
        self.assertEqual(resp.status, 401)


class TestSharedAndMissingConnections(Case):
    # Two transactions share the broadcast connection; an OFFER from one server, a NAK from another
    docs = [
        dhcp("2026-11-05T10:00:00.000Z", MAC, ["Cshared", "Ca"], ["REQUEST", "ACK"], server=ROUTER),
        dhcp("2026-11-05T09:00:00.000Z", MAC, ["Cshared", "Cb"], ["REQUEST", "ACK"], server=VLAN40),
        conn("Cshared", "0.0.0.0", 68, "255.255.255.255", 67),
        conn("Ca", ROUTER, 67, "255.255.255.255", 68),
        conn("Cb", VLAN40, 67, "255.255.255.255", 68),
        dhcp(
            "2026-11-05T08:00:00.000Z",
            MAC,
            ["Coffer", "Cnak"],
            ["DISCOVER", "OFFER", "REQUEST", "NAK"],
            server="255.255.255.255",
        ),
        conn("Coffer", "192.168.1.5", 67, "255.255.255.255", 68),
        conn("Cnak", ROUTER, 67, "255.255.255.255", 68),
        # a relay to a server: both sides on port 67
        dhcp("2026-11-05T07:00:00.000Z", MAC, ["Crelay"], ["INFORM", "ACK"]),
        conn("Crelay", "10.0.0.2", 67, "10.0.0.9", 67),
        # one connection has no conn record yet (Zeek writes a UDP one once it goes idle)
        dhcp("2026-11-05T06:00:00.000Z", MAC, ["Cseen", "Cpending"], ["REQUEST", "ACK"]),
        conn("Cseen", ROUTER, 67, "255.255.255.255", 68),
    ]

    async def test_a_shared_connection_gives_each_transaction_only_its_own_servers(self):
        _, body = await self.get(f"mac={MAC}")
        first, second, *_ = body["transactions"]
        self.assertEqual(first["server_endpoints"], [ROUTER])
        self.assertEqual(second["server_endpoints"], [VLAN40])
        self.assertTrue(first["endpoints_complete"] and second["endpoints_complete"])

    async def test_offer_from_one_server_and_nak_from_another_lists_both(self):
        _, body = await self.get(f"mac={MAC}")
        mixed = body["transactions"][2]
        self.assertEqual(
            (mixed["outcome"], mixed["server_endpoints"], mixed["zeek_server"]),
            ("nak", [ROUTER, "192.168.1.5"], None),
        )

    async def test_a_relay_counts_both_sides(self):
        _, body = await self.get(f"mac={MAC}")
        relay = body["transactions"][3]
        self.assertEqual((relay["outcome"], relay["server_endpoints"]), ("ack", ["10.0.0.2", "10.0.0.9"]))

    async def test_a_connection_without_a_record_makes_the_endpoints_incomplete(self):
        _, body = await self.get(f"mac={MAC}")
        pending = body["transactions"][4]
        self.assertEqual(
            (pending["server_endpoints"], pending["endpoints_complete"]), ([ROUTER], False)
        )


class TestTruncated(Case):
    docs = [
        dhcp(f"2026-11-05T0{h}:{m:02d}:00.000Z", MAC, [f"C{h}{m}"], ["REQUEST"])
        for h in range(4)
        for m in range(51)
    ]  # 204 transactions, no conn records

    async def test_the_newest_200_and_a_flag(self):
        status, body = await self.get(f"mac={MAC}")
        self.assertEqual(status, 200, body)
        self.assertTrue(body["truncated"])
        self.assertEqual(len(body["transactions"]), 200)
        self.assertEqual(body["transactions"][0]["ts"], "2026-11-05T03:50:00.000Z")
        self.assertEqual(body["transactions"][-1]["ts"], "2026-11-05T00:04:00.000Z")
        self.assertFalse(any(t["endpoints_complete"] for t in body["transactions"]))


class TestFailures(Case):
    async def failing(self, error, status: int, message: str):
        with patch.object(self.os, "search", side_effect=error):
            got = await self.get(f"mac={U6}")
        self.assertEqual(got, (status, {"error": message}))

    async def test_a_client_time_out_is_a_503(self):
        await self.failing(
            ConnectionTimeout("TIMEOUT", "read timed out", None),
            503,
            "Working this out took too long. Try a shorter time range.",
        )

    async def test_an_opensearch_time_out_is_a_503(self):
        await self.failing(
            SearchTimedOut("the search timed out on arkime_sessions3-*"),
            503,
            "Working this out took too long. Try a shorter time range.",
        )

    async def test_a_partial_reply_is_a_502(self):
        await self.failing(
            PartialResultsError("1 shard(s) failed"),
            502,
            "Couldn't read the network data: the DHCP search was incomplete.",
        )

    async def test_an_unreachable_opensearch_is_a_502_without_its_text(self):
        await self.failing(
            OpenSearchConnectionError("N/A", "https://localhost:9200 refused", None),
            502,
            "Couldn't read the network data: the DHCP search failed.",
        )

    async def test_a_failed_conn_read_fails_the_request(self):
        real = self.os.search

        def second_fails(body, **kwargs):
            if "sort" not in body:
                raise PartialResultsError("1 shard(s) failed")
            return real(body, **kwargs)

        with patch.object(self.os, "search", second_fails):
            got = await self.get(f"mac={U6}")
        self.assertEqual(
            got,
            (502, {"error": "Couldn't read the network data: the DHCP connections search was incomplete."}),
        )


@pytest.mark.parametrize(
    "messages, expected",
    [
        (["ACK", "NAK", "REQUEST"], "mixed"),
        (["REQUEST", "ACK"], "ack"),
        (["INFORM", "ACK"], "ack"),
        (["NAK", "REQUEST"], "nak"),
        (["DISCOVER", "OFFER"], "offer_no_reply"),
        (["DISCOVER", "OFFER", "REQUEST"], "offer_no_reply"),
        (["DISCOVER"], "discover_no_offer"),
        (["DISCOVER", "DISCOVER", "DECLINE"], "discover_no_offer"),
        (["REQUEST"], "request_no_reply"),
        (["DISCOVER", "REQUEST"], "request_no_reply"),
        (["RELEASE"], "release"),
        (["DECLINE"], "decline"),
        (["INFORM"], "inform"),
        (["LEASEQUERY"], "other"),
        ([], "other"),
    ],
)
def test_outcome_table(messages, expected):
    from collections import Counter

    assert outcome(Counter(messages)) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("78:45:58:ED:B2:E9", U6),
        ("78-45-58-ed-b2-e9", U6),
        ("7845.58ed.b2e9", U6),
        ("784558EDB2E9", U6),
        ("78:45:58:ed:b2:e9\n:00", None),
        (None, None),
        (7, None),
    ],
)
def test_canonical_mac(raw, expected):
    assert canonical_mac(raw) == expected
