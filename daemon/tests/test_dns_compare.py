"""
Tests for the DNS resolver compare (NET-262): DnsReconService.compare and POST /api/tools/dns-compare.

dig is mocked; its output is real (tests/dig_compare_fixtures.py, captured on the G11).
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.tools import register_tools_routes
from services.dns_recon_service import (
    LOOKUPS_BUSY,
    MAX_CONCURRENT_LOOKUPS,
    NO_REPLY,
    DnsReconBusyError,
    DnsReconService,
    DnsReconValidationError,
    _answer_key,
)
from tests import dig_compare_fixtures as dig
from tests.test_dns_recon_service import FakeDig

EXEC = "asyncio.create_subprocess_exec"


def resolver_of(argv) -> str:
    return argv[1].removeprefix("@")


def fake_exec_from(outputs: dict[str, tuple[str, int]], started: list | None = None):
    """create_subprocess_exec that answers each resolver with its (stdout, exit code)."""

    def fake_exec(*argv, **kwargs):
        if started is not None:
            started.append(argv)
        out, code = outputs[resolver_of(argv)]
        return FakeDig(argv[-1], out=out, code=code)

    return fake_exec


def record(name, rtype, value, ttl=300, cls="IN"):
    return {"name": name, "ttl": ttl, "class": cls, "type": rtype, "value": value}


class TestValidateResolvers(unittest.TestCase):
    def setUp(self):
        self.svc = DnsReconService()

    def test_normalises_and_keeps_each_address_once_in_order(self):
        self.assertEqual(
            self.svc.validate_resolvers(
                [" 9.9.9.9 ", "2606:4700:4700:0:0:0:0:1111", "192.168.1.1", "9.9.9.9"]
            ),
            ["9.9.9.9", "2606:4700:4700::1111", "192.168.1.1"],
        )

    def test_rejects_anything_that_is_not_an_ip_literal(self):
        for bad in (
            [],
            None,
            "9.9.9.9",
            ["dns.google"],
            ["-x"],
            ["9.9.9.9 +tcp"],
            ["fe80::1%eth0"],
            [53],
            ["1.1.1.1"] * 7,
        ):
            with self.subTest(bad=bad), self.assertRaises(DnsReconValidationError):
                self.svc.validate_resolvers(bad)

    def test_six_is_the_most(self):
        six = [f"10.0.0.{i}" for i in range(1, 7)]
        self.assertEqual(self.svc.validate_resolvers(six), six)


class TestCompareValidation(unittest.TestCase):
    def setUp(self):
        self.svc = DnsReconService()

    def test_bad_input_is_refused_before_any_dig_starts(self):
        cases = [
            ("", "A", ["9.9.9.9"]),
            ("; rm -rf /", "A", ["9.9.9.9"]),
            (["example.com"], "A", ["9.9.9.9"]),
            ("example.com", "ANY", ["9.9.9.9"]),
            ("example.com", 1, ["9.9.9.9"]),
            ("example.com", "A", ["not-an-ip"]),
        ]

        async def run_test():
            with patch(EXEC) as exec_:
                for name, rtype, resolvers in cases:
                    with (
                        self.subTest(name=name, rtype=rtype),
                        self.assertRaises(DnsReconValidationError),
                    ):
                        await self.svc.compare(name, rtype, resolvers)
            exec_.assert_not_called()

        asyncio.run(run_test())

    def test_record_type_defaults_to_a_and_is_upper_cased(self):
        async def run_test():
            started = []
            outputs = {"192.168.1.1": (dig.ROUTER_PRIVATE, 0)}
            with patch(EXEC, side_effect=fake_exec_from(outputs, started)):
                first = await self.svc.compare("Setup.UI.com", None, ["192.168.1.1"])
                second = await self.svc.compare("setup.ui.com", "aaaa", ["192.168.1.1"])
            self.assertEqual((first["name"], first["record_type"]), ("setup.ui.com", "A"))
            self.assertEqual(second["record_type"], "AAAA")
            self.assertEqual(started[1][-4:], ("-t", "AAAA", "-q", "setup.ui.com"))

        asyncio.run(run_test())


class TestCompareDig(unittest.TestCase):
    """One dig per resolver, with the resolver as @server and the name last."""

    def setUp(self):
        self.svc = DnsReconService()

    def test_argv_asks_each_resolver_once_with_the_name_last(self):
        async def run_test():
            started = []
            outputs = {
                "9.9.9.9": (dig.QUAD9_AAAA, 0),
                "2606:4700:4700::1111": (dig.V6_UNREACHABLE, 9),
            }
            with patch(EXEC, side_effect=fake_exec_from(outputs, started)):
                await self.svc.compare(
                    "example.com", "AAAA", ["9.9.9.9", "2606:4700:4700::1111"]
                )
            self.assertEqual(
                started[0],
                (
                    "dig",
                    "@9.9.9.9",
                    "+noall",
                    "+answer",
                    "+comments",
                    "+stats",
                    "+time=2",
                    "+tries=1",
                    "-t",
                    "AAAA",
                    "-q",
                    "example.com",
                ),
            )
            self.assertEqual(started[1][1], "@2606:4700:4700::1111")

        asyncio.run(run_test())

    def test_split_dns_on_the_g11_router_private_cloudflare_public_quad9_nxdomain(self):
        async def run_test():
            outputs = {
                "192.168.1.1": (dig.ROUTER_PRIVATE, 0),
                "1.1.1.1": (dig.CLOUDFLARE_PUBLIC, 0),
                "9.9.9.9": (dig.QUAD9_NXDOMAIN, 0),
            }
            with patch(EXEC, side_effect=fake_exec_from(outputs)):
                result = await self.svc.compare(
                    "setup.ui.com", "A", ["192.168.1.1", "1.1.1.1", "9.9.9.9"]
                )
            router, cloudflare, quad9 = result["results"]

            self.assertEqual(
                [r["resolver"] for r in result["results"]],
                ["192.168.1.1", "1.1.1.1", "9.9.9.9"],
            )
            self.assertEqual(
                (router["status"], router["ttl"], router["latency_ms"], router["error"]),
                ("NOERROR", 0, 0, None),
            )
            self.assertEqual(
                router["answers"],
                [
                    {
                        **record("setup.ui.com.", "A", "192.168.1.1", ttl=0),
                        "key": "setup.ui.com IN A 192.168.1.1",
                        "scope": "private",
                    }
                ],
            )
            self.assertEqual(
                (cloudflare["status"], cloudflare["ttl"], cloudflare["latency_ms"]),
                ("NOERROR", 32, 8),
            )
            self.assertEqual(
                [a["scope"] for a in cloudflare["answers"]], ["public"] * 4
            )
            self.assertEqual(
                (quad9["status"], quad9["answers"], quad9["ttl"], quad9["latency_ms"]),
                ("NXDOMAIN", [], None, 522),
            )

        asyncio.run(run_test())

    def test_no_reply_is_no_status_and_the_plain_reason(self):
        async def run_test():
            outputs = {
                "192.0.2.53": (dig.TIMED_OUT, 9),
                "2606:4700:4700::1111": (dig.V6_UNREACHABLE, 9),
                "192.0.2.54": (";; communications error: timed out\n", 1),
            }
            with patch(EXEC, side_effect=fake_exec_from(outputs)):
                result = await self.svc.compare("example.com", "A", list(outputs))
            for reply in result["results"]:
                with self.subTest(resolver=reply["resolver"]):
                    self.assertEqual(
                        (reply["status"], reply["answers"], reply["ttl"], reply["error"]),
                        (None, [], None, NO_REPLY),
                    )

        asyncio.run(run_test())

    def test_any_status_is_a_reply_even_one_dig_cannot_name(self):
        async def run_test():
            out = dig.QUAD9_NXDOMAIN.replace("status: NXDOMAIN", "status: RESERVED11")
            with patch(EXEC, side_effect=fake_exec_from({"9.9.9.9": (out, 0)})):
                result = await self.svc.compare("example.com", "A", ["9.9.9.9"])
            self.assertEqual(result["results"][0]["status"], "RESERVED11")

        asyncio.run(run_test())

    def test_another_dig_failure_keeps_digs_own_reason(self):
        async def run_test():
            outputs = {"9.9.9.9": ("dig: couldn't get address for 'x': failure\n", 10)}
            with patch(EXEC, side_effect=fake_exec_from(outputs)):
                result = await self.svc.compare("example.com", "A", ["9.9.9.9"])
            self.assertEqual(
                result["results"][0]["error"], "dig: couldn't get address for 'x': failure"
            )
            self.assertIsNone(result["results"][0]["status"])

        asyncio.run(run_test())

    def test_txt_cname_aaaa_and_duplicate_answers_parse(self):
        async def run_test():
            outputs = {
                "9.9.9.9": (dig.QUAD9_TXT, 0),
                "9.9.9.10": (dig.QUAD9_CNAME, 0),
                "9.9.9.11": (dig.QUAD9_AAAA, 0),
                "192.168.1.1": (dig.ROUTER_DUPLICATE, 0),
            }
            with patch(EXEC, side_effect=fake_exec_from(outputs)):
                result = await self.svc.compare("example.com", "A", list(outputs))
            txt, cname, aaaa, dup = result["results"]
            self.assertEqual(
                [a["key"] for a in txt["answers"]],
                [
                    'example.com IN TXT "v=spf1 -all"',
                    'example.com IN TXT "_k2n1y4vw3qtb4skdx9e7dxt97qrmmq9"',
                ],
            )
            self.assertNotIn("scope", txt["answers"][0])
            self.assertEqual(
                [a["key"] for a in cname["answers"]],
                ["www.github.com IN CNAME github.com", "github.com IN A 20.172.24.160"],
            )
            self.assertEqual(cname["ttl"], 46)  # the lowest of the chain
            self.assertEqual(cname["latency_ms"], 1149)
            self.assertEqual([a["scope"] for a in aaaa["answers"]], ["public", "public"])
            self.assertEqual(len(dup["answers"]), 2)
            self.assertEqual(dup["answers"][0]["key"], dup["answers"][1]["key"])

        asyncio.run(run_test())


class TestAnswerKey(unittest.TestCase):
    """Equal keys mean the same record: TTL left out, names and addresses normalised."""

    def test_the_same_records_from_two_resolvers_in_another_order_have_the_same_keys(self):
        svc = DnsReconService()
        router = {_answer_key(r) for r in svc._parse_dig_output(dig.ROUTER_PUBLIC)}
        quad9 = {_answer_key(r) for r in svc._parse_dig_output(dig.QUAD9_PUBLIC)}
        self.assertEqual(router, quad9)
        self.assertEqual(len(router), 2)

    def test_ttl_is_left_out(self):
        self.assertEqual(
            _answer_key(record("a.example.", "A", "192.0.2.1", ttl=0)),
            _answer_key(record("a.example.", "A", "192.0.2.1", ttl=86400)),
        )

    def test_owner_and_name_fields_ignore_case_and_the_trailing_dot(self):
        same = [
            (record("WWW.Example.COM.", "A", "192.0.2.1"), record("www.example.com", "A", "192.0.2.1")),
            (record("a.", "CNAME", "Target.Example."), record("a", "CNAME", "target.example")),
            (record("a.", "NS", "NS1.Example."), record("a", "NS", "ns1.example")),
            (record("1.2.0.192.in-addr.arpa.", "PTR", "Host.LAN."), record("1.2.0.192.in-addr.arpa", "PTR", "host.lan")),
            (record("a.", "MX", "10 Mail.Example."), record("a.", "MX", "10 mail.example")),
            (record("a.", "SRV", "30 30 5269 Scarlet.Jabber.org."), record("a.", "SRV", "30 30 5269 scarlet.jabber.org")),
            (
                record("a.", "SOA", "Elliott.NS.Cloudflare.com. DNS.cloudflare.com. 2420077714 10000 2400 604800 1800"),
                record("a.", "SOA", "elliott.ns.cloudflare.com dns.cloudflare.com 2420077714 10000 2400 604800 1800"),
            ),
            (record("a.", "AAAA", "::1"), record("a.", "AAAA", "0:0::1")),
            (record("a.", "AAAA", "2606:4700:10:0::AC42:93F3"), record("a.", "AAAA", "2606:4700:10::ac42:93f3")),
        ]  # fmt: skip
        for one, other in same:
            with self.subTest(one=one["value"], other=other["value"]):
                self.assertEqual(_answer_key(one), _answer_key(other))

    def test_txt_is_byte_for_byte_and_the_owner_counts(self):
        self.assertNotEqual(
            _answer_key(record("a.", "TXT", '"v=spf1 -all"')),
            _answer_key(record("a.", "TXT", '"V=SPF1 -ALL"')),
        )
        self.assertNotEqual(
            _answer_key(record("a.", "TXT", '"one" "two"')),
            _answer_key(record("a.", "TXT", '"one two"')),
        )
        self.assertNotEqual(
            _answer_key(record("a.example.", "A", "192.0.2.1")),
            _answer_key(record("b.example.", "A", "192.0.2.1")),
        )
        self.assertNotEqual(
            _answer_key(record("a.", "MX", "10 mail.example.")),
            _answer_key(record("a.", "MX", "20 mail.example.")),
        )


class TestCompareConcurrency(unittest.TestCase):
    def setUp(self):
        self.svc = DnsReconService()

    def test_resolvers_are_asked_at_the_same_time(self):
        async def run_test():
            release = asyncio.Event()
            started = []

            def fake_exec(*argv, **kwargs):
                started.append(resolver_of(argv))
                if len(started) == 3:
                    release.set()  # only once all three run: one after another would hang
                return FakeDig("A", release, out=dig.ROUTER_PRIVATE)

            with patch(EXEC, side_effect=fake_exec):
                result = await asyncio.wait_for(
                    self.svc.compare("setup.ui.com", "A", ["10.0.0.1", "10.0.0.2", "10.0.0.3"]),
                    timeout=2,
                )
            self.assertEqual(
                [r["resolver"] for r in result["results"]],
                ["10.0.0.1", "10.0.0.2", "10.0.0.3"],
            )

        asyncio.run(run_test())

    def test_a_hung_dig_is_no_reply_and_is_killed_and_reaped(self):
        async def run_test():
            hung = FakeDig("A", release=asyncio.Event())  # never released

            def fake_exec(*argv, **kwargs):
                if resolver_of(argv) == "192.0.2.53":
                    return hung
                return FakeDig("A", out=dig.ROUTER_PRIVATE)

            with (
                patch("services.dns_recon_service.QUERY_TIMEOUT", 0.05),
                patch(EXEC, side_effect=fake_exec),
            ):
                result = await self.svc.compare(
                    "setup.ui.com", "A", ["192.168.1.1", "192.0.2.53"]
                )
            self.assertEqual(
                [(r["status"], r["error"]) for r in result["results"]],
                [("NOERROR", None), (None, NO_REPLY)],
            )
            hung.kill.assert_called_once()
            hung.wait.assert_awaited_once()

        asyncio.run(run_test())

    def test_a_cancelled_compare_kills_and_reaps_every_child(self):
        async def run_test():
            children = []

            def fake_exec(*argv, **kwargs):
                child = FakeDig("A", release=asyncio.Event())  # never released
                children.append(child)
                return child

            with patch(EXEC, side_effect=fake_exec):
                task = asyncio.create_task(
                    self.svc.compare("example.com", "A", ["10.0.0.1", "10.0.0.2"])
                )
                for _ in range(50):
                    if len(children) == 2:
                        break
                    await asyncio.sleep(0)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertEqual(len(children), 2)
            for child in children:
                child.kill.assert_called_once()
                child.wait.assert_awaited_once()

        asyncio.run(run_test())

    def test_a_compare_takes_one_lookup_slot_and_is_refused_when_none_is_free(self):
        async def run_test():
            release = asyncio.Event()
            started = []

            def fake_exec(*argv, **kwargs):
                started.append(argv)
                return FakeDig(argv[-1], release, out=dig.ROUTER_PRIVATE)

            with patch(EXEC, side_effect=fake_exec):
                six = [f"10.0.0.{i}" for i in range(1, 7)]
                compare = asyncio.create_task(self.svc.compare("example.com", "A", six))
                lookups = [
                    asyncio.create_task(self.svc.lookup("example.com", ["A"]))
                    for _ in range(MAX_CONCURRENT_LOOKUPS - 1)
                ]
                for _ in range(50):
                    if len(started) == 6 + MAX_CONCURRENT_LOOKUPS - 1:
                        break
                    await asyncio.sleep(0)
                self.assertEqual(len(started), 6 + MAX_CONCURRENT_LOOKUPS - 1)

                with self.assertRaises(DnsReconBusyError):
                    await asyncio.wait_for(
                        self.svc.compare("example.com", "A", ["10.0.0.9"]), timeout=1
                    )
                self.assertEqual(len(started), 6 + MAX_CONCURRENT_LOOKUPS - 1)

                release.set()
                await asyncio.gather(compare, *lookups)

        asyncio.run(run_test())


class TestDnsCompareRoute(AioHTTPTestCase):
    async def get_application(self):
        self.svc = DnsReconService()
        app = web.Application()
        register_tools_routes(app, self.svc, MagicMock(), MagicMock(), MagicMock())
        return app

    async def test_answers_each_resolvers_reply(self):
        outputs = {"192.168.1.1": (dig.ROUTER_PRIVATE, 0), "9.9.9.9": (dig.QUAD9_NXDOMAIN, 0)}
        with patch(EXEC, side_effect=fake_exec_from(outputs)):
            resp = await self.client.post(
                "/api/tools/dns-compare",
                json={"name": "setup.ui.com", "record_type": "A", "resolvers": list(outputs)},
            )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual((body["name"], body["record_type"]), ("setup.ui.com", "A"))
        self.assertEqual([r["status"] for r in body["results"]], ["NOERROR", "NXDOMAIN"])

    async def test_bad_input_is_400_with_a_plain_sentence(self):
        for payload in (
            {"name": "example.com", "resolvers": ["dns.google"]},
            {"name": "example.com", "resolvers": []},
            {"name": "", "resolvers": ["9.9.9.9"]},
            ["example.com"],
        ):
            with self.subTest(payload=payload):
                resp = await self.client.post("/api/tools/dns-compare", json=payload)
                self.assertEqual(resp.status, 400)
                self.assertTrue((await resp.json())["error"])
        resp = await self.client.post("/api/tools/dns-compare", data="{not json")
        self.assertEqual(resp.status, 400)

    async def test_busy_is_503_with_the_reason(self):
        self.svc.compare = AsyncMock(side_effect=DnsReconBusyError(LOOKUPS_BUSY))
        resp = await self.client.post(
            "/api/tools/dns-compare", json={"name": "example.com", "resolvers": ["9.9.9.9"]}
        )
        self.assertEqual(resp.status, 503)
        self.assertEqual(await resp.json(), {"error": LOOKUPS_BUSY})


if __name__ == "__main__":
    unittest.main()
