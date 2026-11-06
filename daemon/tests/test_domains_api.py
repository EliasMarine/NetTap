"""GET /api/domains/{name} (NET-160): the DNS page's rules, any case and either dotted form."""

from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase

from api.domains import register_domain_routes
from services.excluded_ips import build_lan_filter
from services.hostnames import canonical_name
from storage import snapshot_search
from tests.fake_drill_opensearch import (
    AUTH,
    WINDOW,
    DrillOpenSearch,
    alert,
    dns,
    make_app,
    ssl_session,
)

PHONE, LAPTOP, EXCLUDED = "192.168.1.20", "192.168.1.30", "192.168.1.99"


class DomainCase(AioHTTPTestCase):
    docs: list = []

    async def get_application(self):
        self.os = DrillOpenSearch(list(self.docs))
        return make_app(
            self.os,
            register_domain_routes,
            lan_filter=build_lan_filter([(192, 168, 1)]),
            excluded_ips=[EXCLUDED],
        )

    async def figures(self, name="example.com", query=WINDOW, status=200):
        resp = await self.client.get(f"/api/domains/{name}?{query}", headers=AUTH)
        self.assertEqual(resp.status, status, await resp.text())
        return await resp.json()


def test_canonical_names():
    assert canonical_name("Example.COM.") == "example.com"
    assert canonical_name("_dmarc.example.com") == "_dmarc.example.com"
    assert canonical_name("wpad") == "wpad"
    for bad in (
        "",
        ".",
        "example..com",
        "exa mple.com",
        "a" * 64 + ".com",
        "x." * 127 + "com",
        "example.com..",
        "ex/ample",
        None,
    ):
        assert canonical_name(bad) is None, bad


class TestValidation(DomainCase):
    async def test_a_bad_name_or_window_is_a_400_and_no_search_runs(self):
        for name, query in (
            ("exa%20mple.com", WINDOW),
            ("example..com", WINDOW),
            ("a" * 64 + ".com", WINDOW),
            ("example.com", "to=yesterday"),
        ):
            self.assertIn("error", await self.figures(name, query, status=400))
        self.assertEqual(self.os.bodies, [])

    async def test_the_route_needs_the_token(self):
        self.assertEqual(
            (await self.client.get("/api/domains/example.com")).status, 401
        )


class TestNameMatching(DomainCase):
    docs = [
        dns("example.com", zeek__dns__answers=["93.184.216.34"]),
        dns("Example.COM.", src=LAPTOP),
        dns("EXAMPLE.com"),
        dns("example.com.", src=LAPTOP),
        dns("www.example.com"),  # a different name
        dns("example.co"),
    ]

    async def test_every_case_and_dot_variant_counts_once_whichever_way_it_is_asked(
        self,
    ):
        for asked in ("example.com", "EXAMPLE.Com.", "example.com."):
            body = await self.figures(asked)
            self.assertEqual(body["name"], "example.com")
            self.assertEqual(body["dns"]["lookups"], 4, asked)
        self.assertEqual(sum(s["n"] for s in body["dns"]["timeline"]), 4)

    async def test_the_query_uses_case_insensitive_terms_for_both_forms(self):
        await self.figures("Example.com")
        lookups = self.os.bodies[0]["query"]["bool"]
        should = next(c["bool"]["should"] for c in lookups["filter"] if "bool" in c)
        self.assertEqual(
            should,
            [
                {"term": {"zeek.dns.query": {"value": n, "case_insensitive": True}}}
                for n in ("example.com", "example.com.")
            ],
        )

    async def test_a_field_that_is_not_keyword_fails_loudly(self):
        self.os.mapping_types["zeek.dns.query"] = "text"
        body = await self.figures(status=502)
        self.assertIn("name matching unavailable", body["error"])
        self.assertEqual(self.os.bodies, [])


class TestDnsRules(DomainCase):
    docs = [
        dns("example.com", src=PHONE, t="2026-11-05T09:00:00.000Z"),
        dns("example.com", src=PHONE, t="2026-11-05T10:00:00.000Z"),
        dns("example.com", src=LAPTOP),
        dns("example.com", src=EXCLUDED),  # an excluded device: the DNS page skips it
        dns("example.com", dst="224.0.0.251", destination__port=5353),  # mDNS
        dns(
            "example.com", src=PHONE, t="2026-11-04T10:00:00.000Z"
        ),  # before the window
        dns("example.com", zeek__dns__rcode_name="NXDOMAIN", src=LAPTOP),
    ]

    async def test_lookups_and_askers_mean_what_the_dns_page_means(self):
        dns_figures = (await self.figures())["dns"]
        self.assertEqual(dns_figures["lookups"], 4)
        self.assertTrue(dns_figures["askers_complete"])
        self.assertEqual(
            dns_figures["askers"],
            [
                {
                    "ip": PHONE,
                    "lan": True,
                    "lookups": 2,
                    "last_seen": "2026-11-05T10:00:00.000Z",
                },
                {
                    "ip": LAPTOP,
                    "lan": True,
                    "lookups": 2,
                    "last_seen": "2026-11-05T10:00:00.000Z",
                },
            ],
        )
        self.assertEqual(
            dns_figures["rcodes"],
            [{"rcode": None, "lookups": 3}, {"rcode": "NXDOMAIN", "lookups": 1}],
        )


class TestAnswers(DomainCase):
    docs = [
        dns(
            "example.com", zeek__dns__answers=["93.184.216.34", "2606:2800:220:1::248"]
        ),  # A, AAAA
        dns(
            "example.com", zeek__dns__answers=["edge.example.NET", "93.184.216.34"]
        ),  # CNAME
        dns(
            "example.com", zeek__dns__answers=["v=spf1 include:_spf.example.com ~all"]
        ),  # TXT
        dns("example.com", zeek__dns__answers=["192.168.1.5"]),
        dns("example.com"),  # no answer
    ]

    async def test_answers_are_addresses_names_or_other_text(self):
        body = (await self.figures())["dns"]
        got = {
            (a["kind"], a["value"]): (a["lan"], a["lookups"]) for a in body["answers"]
        }
        self.assertEqual(
            got,
            {
                ("ip", "93.184.216.34"): (False, 2),
                ("ip", "2606:2800:220:1::248"): (False, 1),
                ("ip", "192.168.1.5"): (True, 1),
                ("name", "edge.example.net"): (None, 1),
                ("other", "v=spf1 include:_spf.example.com ~all"): (None, 1),
            },
        )
        self.assertTrue(body["answers_complete"])
        self.assertEqual(body["addresses"], 3)  # distinct IP answers only

    async def test_addresses_are_withheld_when_the_answers_are_capped(self):
        # OLD CODE START — NET-160 review: the drill-down lists stop at LIST_CAP
        # with (
        #     patch.object(snapshot_search, "GROUP_PAGE", 2),
        #     patch.object(snapshot_search, "MAX_GROUP_BUCKETS", 2),
        # ):
        # OLD CODE END
        with (
            patch.object(snapshot_search, "GROUP_PAGE", 2),
            patch("api.domains.LIST_CAP", 2),
        ):
            body = (await self.figures())["dns"]
        self.assertFalse(body["answers_complete"])
        self.assertIsNone(body["addresses"])


class TestTlsAndHttp(DomainCase):
    docs = [
        ssl_session("example.com", server="93.184.216.34", client=PHONE),
        ssl_session("EXAMPLE.com.", server="93.184.216.35", client=LAPTOP, status=None),
        ssl_session("example.com", server="93.184.216.34", client=EXCLUDED),
        ssl_session("other.com", server="93.184.216.34"),
        {
            "@timestamp": "2026-11-05T10:00:00.000Z",
            "event.provider": "zeek",
            "event.dataset": "http",
            "zeek.http.host": "Example.com",
        },
    ]

    async def test_tls_servers_clients_and_statuses(self):
        body = await self.figures()
        tls = body["tls"]
        self.assertEqual(tls["sessions"], 3)
        self.assertEqual(
            tls["servers"],
            [
                {"ip": "93.184.216.34", "lan": False, "sessions": 2},
                {"ip": "93.184.216.35", "lan": False, "sessions": 1},
            ],
        )
        self.assertEqual({c["ip"] for c in tls["clients"]}, {PHONE, LAPTOP, EXCLUDED})
        self.assertTrue(tls["servers_complete"] and tls["clients_complete"])
        self.assertEqual(tls["statuses"], {"ok": 2, "unchecked": 1})
        self.assertEqual(body["http"], {"requests": 1})


class TestAlertsMixed(DomainCase):
    docs = [
        alert(PHONE, "93.184.216.34", tls__client__server_name="Example.com"),
        alert(PHONE, "93.184.216.34", related__hosts=["example.com.", "cdn.net"]),
        alert(PHONE, "1.1.1.1", url__domain="other.com"),  # enriched, another name
        alert(PHONE, "93.184.216.34"),  # no host field at all
        alert(
            PHONE,
            "93.184.216.34",
            rule="SURICATA STREAM noise",
            url__domain="example.com",
        ),
    ]

    async def test_tagged_alerts_come_with_their_coverage(self):
        alerts = (await self.figures())["alerts"]
        self.assertEqual(
            alerts, {"tagged": 2, "alerts_in_window": 4, "with_host_field": 3}
        )


class TestAlertsUnrecorded(DomainCase):
    docs = [alert(PHONE, "93.184.216.34"), alert(LAPTOP, "1.1.1.1")]

    async def test_no_host_field_anywhere_is_not_recorded_rather_than_zero(self):
        alerts = (await self.figures())["alerts"]
        self.assertEqual(
            alerts, {"tagged": None, "alerts_in_window": 2, "with_host_field": 0}
        )


# ---------------------------------------------------------------------------
# NET-160 review
# ---------------------------------------------------------------------------


class TestAnswerSpellings(DomainCase):
    docs = [
        dns("example.com", zeek__dns__answers=["Edge.Example.NET", "2001:DB8::1"]),
        dns("example.com", zeek__dns__answers=["edge.example.net", "2001:db8::1"]),
        dns("example.com", zeek__dns__answers=["93.184.216.34"]),  # A
        dns("example.com", zeek__dns__answers=[" 93.184.216.34"]),  # as TXT text
    ]

    async def test_spellings_of_one_answer_are_one_row_with_lookups_summed(self):
        body = (await self.figures())["dns"]
        keys = [(a["kind"], a["value"]) for a in body["answers"]]
        self.assertEqual(len(keys), len(set(keys)))  # the page keys its list on these
        got = {key: a["lookups"] for key, a in zip(keys, body["answers"])}
        self.assertEqual(
            got,
            {
                ("name", "edge.example.net"): 2,
                ("ip", "2001:db8::1"): 2,
                ("ip", "93.184.216.34"): 2,
            },
        )
        self.assertEqual(body["addresses"], 2)


class TestShortListsNeverCut(DomainCase):
    docs = [
        dns("example.com", zeek__dns__rcode_name="NOERROR"),
        dns("example.com", zeek__dns__rcode_name="NXDOMAIN"),
        dns("example.com", zeek__dns__rcode_name="SERVFAIL"),
    ]

    async def test_a_cut_response_code_list_fails_rather_than_shrinks(self):
        with (
            patch.object(snapshot_search, "GROUP_PAGE", 2),
            patch("api.domains.LIST_CAP", 2),
        ):
            body = await self.figures(status=502)
        self.assertIn("domain response codes", body["error"])
