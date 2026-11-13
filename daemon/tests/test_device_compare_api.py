"""GET /api/moment/device-compare (NET-265): what one device started in two periods.

The evaluator fake runs the real queries over fixed documents, as the moment tests do, so
the half-open windows, the totals and the lists are checked against the records behind them.
"""

from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase
from opensearchpy import ConnectionTimeout

from api import device_compare
from api.device_compare import compare, register_device_compare_routes
from api.moment import register_moment_routes
from api.traffic import _ZEEK_CONN_FILTERS
from storage.exact_terms import SearchTimedOut
from storage.snapshot_search import Budget
from tests.fake_drill_opensearch import AUTH, DrillOpenSearch, conn, make_app

DEVICE, OTHER = "192.168.1.30", "192.168.1.31"
EXCLUDED = ["192.168.1.2"]
KEPT, GROWN, SAME, OLD, NEW1, NEW2 = (
    "203.0.113.5",
    "203.0.113.6",
    "203.0.113.7",
    "198.51.100.7",
    "192.0.2.80",
    "192.0.2.81",
)
A_FROM, A_TO = "2026-11-05T00:00:00.000Z", "2026-11-05T06:00:00.000Z"
B_FROM, B_TO = A_TO, "2026-11-05T12:00:00.000Z"
WINDOWS = f"a_from={A_FROM}&a_to={A_TO}&b_from={B_FROM}&b_to={B_TO}"
ORG = "AS64500 Example Networks"


def _conn(dst, t, n, src=DEVICE, **fields):
    return conn(src, dst, t, network__bytes=n, **fields)


DOCS = [
    # the first period: A starts on its own first millisecond
    _conn(KEPT, A_FROM, 100, destination__as__full=ORG),
    _conn(GROWN, "2026-11-05T01:00:00.000Z", 50),
    _conn(SAME, "2026-11-05T02:00:00.000Z", 70),
    _conn(OLD, "2026-11-05T03:00:00.000Z", 400),
    # exactly on the boundary: the second period's, never both
    _conn(KEPT, A_TO, 300),
    _conn(GROWN, "2026-11-05T07:00:00.000Z", 1050),
    _conn(SAME, "2026-11-05T08:00:00.000Z", 70),
    _conn(NEW1, "2026-11-05T09:00:00.000Z", 20),
    _conn(NEW2, "2026-11-05T10:00:00.000Z", 900),
    # B's end is outside it
    _conn(NEW1, B_TO, 5000),
    # not this device, an excluded source, and an interim conn_long record
    _conn(OLD, "2026-11-05T07:00:00.000Z", 999, src=OTHER),
    _conn(
        NEW1, "2026-11-05T07:00:00.000Z", 999, log__file__path="conn_long.log"
    ),
]


def _register(app, client):
    register_moment_routes(app, client)
    register_device_compare_routes(app)


class Case(AioHTTPTestCase):
    docs: list = DOCS
    tamper = None

    async def get_application(self):
        self.os = DrillOpenSearch(self.docs, tamper=self.tamper)
        return make_app(self.os, _register, excluded_ips=EXCLUDED)

    async def get(self, query: str = f"ip={DEVICE}&{WINDOWS}") -> tuple[int, dict]:
        resp = await self.client.get(f"/api/moment/device-compare?{query}", headers=AUTH)
        return resp.status, await resp.json()


class TestCompare(Case):
    async def test_new_gone_and_changed_from_the_records(self):
        status, body = await self.get()
        self.assertEqual(status, 200, body)
        self.assertEqual((body["ip"], body["exact"], body["complete"]), (DEVICE, True, True))
        self.assertEqual(
            body["new"],
            {
                "total": 2,
                "items": [
                    {"ip": NEW2, "org": None, "bytes": 900},
                    {"ip": NEW1, "org": None, "bytes": 20},
                ],
            },
        )
        self.assertEqual(
            body["gone"], {"total": 1, "items": [{"ip": OLD, "org": None, "bytes": 400}]}
        )
        # SAME didn't change; GROWN moved more than KEPT
        self.assertEqual(
            body["changed"],
            {
                "total": 2,
                "partial": False,
                "items": [
                    {"ip": GROWN, "org": None, "a_bytes": 50, "b_bytes": 1050, "delta": 1000},
                    {"ip": KEPT, "org": ORG, "a_bytes": 100, "b_bytes": 300, "delta": 200},
                ],
            },
        )

    async def test_a_record_on_the_boundary_counts_in_one_period_only(self):
        _, body = await self.get()
        a, b = body["a"], body["b"]
        self.assertEqual((a["from"], a["to"], b["from"], b["to"]), (A_FROM, A_TO, B_FROM, B_TO))
        # A: its first-millisecond record, not the one at A_TO; B: A_TO's, not B_TO's
        self.assertEqual((a["total_bytes"], a["destinations"]), (620, 4))
        self.assertEqual((b["total_bytes"], b["destinations"]), (2340, 5))
        for p in (a, b):
            self.assertEqual((p["list_complete"], p["buckets_exact"]), (True, True))

    async def test_each_period_is_one_half_open_body_with_the_started_predicate(self):
        await self.get()
        self.assertEqual(len(self.os.bodies), 2)
        for body, (lo, hi) in zip(self.os.bodies, ((A_FROM, A_TO), (B_FROM, B_TO))):
            query = body["query"]["bool"]
            self.assertEqual(
                query["filter"][0]["range"]["@timestamp"],
                {"gte": lo, "lt": hi, "format": "strict_date_optional_time"},
            )
            self.assertEqual(query["filter"][1:], [*_ZEEK_CONN_FILTERS, {"term": {"source.ip": DEVICE}}])
            self.assertEqual(query["must_not"], [{"terms": {"source.ip": EXCLUDED}}])
            terms = body["aggs"]["destinations"]["terms"]
            # doc-count order, so the error bound means something; bytes are ranked in Python
            self.assertEqual(terms, {"field": "destination.ip", "size": 10_000})
            self.assertIn("total", body["aggs"])

    async def test_both_reads_carry_one_request_budget(self):
        await self.get()
        self.assertEqual(len(self.os.budgets), 2)
        self.assertTrue(all(isinstance(b, Budget) for b in self.os.budgets))
        self.assertEqual(len({id(b) for b in self.os.budgets}), 1)

    async def test_the_periods_may_come_in_either_order(self):
        status, body = await self.get(
            f"ip={DEVICE}&a_from={B_FROM}&a_to={B_TO}&b_from={A_FROM}&b_to={A_TO}"
        )
        self.assertEqual(status, 200, body)
        self.assertEqual([r["ip"] for r in body["new"]["items"]], [OLD])

    async def test_without_the_token_it_is_refused(self):
        resp = await self.client.get(f"/api/moment/device-compare?ip={DEVICE}&{WINDOWS}")
        self.assertEqual(resp.status, 401)


class TestLongLists(Case):
    docs = [
        _conn(f"203.0.113.{n}", "2026-11-05T07:00:00.000Z", 1000 + n) for n in range(60)
    ]

    async def test_each_list_stops_at_50_and_keeps_its_full_count(self):
        _, body = await self.get()
        self.assertEqual(body["new"]["total"], 60)
        self.assertEqual(len(body["new"]["items"]), 50)
        self.assertEqual(body["new"]["items"][0], {"ip": "203.0.113.59", "org": None, "bytes": 1059})
        self.assertEqual(body["gone"], {"total": 0, "items": []})


class TestListIncomplete(Case):
    """More destinations than the terms size, counted exactly (sum_other > 0, error 0)."""

    async def test_new_and_gone_are_withheld_and_changes_are_partial(self):
        # a second connection each makes KEPT and GROWN the two listed in both periods
        self.os.docs = [
            *DOCS,
            *(_conn(ip, "2026-11-05T04:00:00.000Z", 1) for ip in (KEPT, GROWN)),
            *(_conn(ip, "2026-11-05T07:30:00.000Z", 1) for ip in (KEPT, GROWN)),
        ]
        with patch.object(device_compare, "_TERMS_SIZE", 2):
            status, body = await self.get()
        self.assertEqual(status, 200, body)
        self.assertEqual((body["exact"], body["complete"]), (True, False))
        self.assertEqual((body["new"], body["gone"]), (None, None))
        self.assertEqual(
            body["changed"],
            {
                "total": 2,
                "partial": True,
                "items": [
                    {"ip": GROWN, "org": None, "a_bytes": 51, "b_bytes": 1051, "delta": 1000},
                    {"ip": KEPT, "org": ORG, "a_bytes": 101, "b_bytes": 301, "delta": 200},
                ],
            },
        )
        for p in (body["a"], body["b"]):
            self.assertEqual((p["list_complete"], p["buckets_exact"]), (False, True))
            self.assertEqual(p["destinations"], 2)  # a lower bound
        # the totals don't depend on the lists
        self.assertEqual((body["a"]["total_bytes"], body["b"]["total_bytes"]), (622, 2342))


def _estimated(bound):
    """A tamper: the destinations list of every reply counted from a cut shard list."""

    def tamper(body, reply):
        aggs = reply["aggregations"]
        return {
            **reply,
            "aggregations": {
                **aggs,
                "destinations": {**aggs["destinations"], "doc_count_error_upper_bound": bound},
            },
        }

    return tamper


class TestBucketsEstimated(Case):
    tamper = staticmethod(_estimated(3))

    async def test_only_the_totals_are_sent(self):
        status, body = await self.get()
        self.assertEqual(status, 200, body)
        self.assertEqual((body["exact"], body["complete"]), (False, False))
        self.assertEqual((body["new"], body["gone"], body["changed"]), (None, None, None))
        self.assertEqual((body["a"]["total_bytes"], body["b"]["total_bytes"]), (620, 2340))
        self.assertEqual((body["a"]["destinations"], body["b"]["destinations"]), (None, None))
        self.assertFalse(body["a"]["buckets_exact"])


class TestBucketsUnknownError(Case):
    tamper = staticmethod(_estimated(-1))  # what a metric-ordered list reports

    async def test_is_not_exact_either(self):
        _, body = await self.get()
        self.assertEqual((body["exact"], body["changed"]), (False, None))


class TestOneSubListEstimated(Case):
    @staticmethod
    def tamper(body, reply):
        dest = reply["aggregations"]["destinations"]
        bucket = {**dest["buckets"][0]}
        bucket["org"] = {**bucket["org"], "doc_count_error_upper_bound": 1}
        dest = {**dest, "buckets": [bucket, *dest["buckets"][1:]]}
        return {**reply, "aggregations": {**reply["aggregations"], "destinations": dest}}

    async def test_a_cut_organisation_list_makes_the_period_not_exact(self):
        _, body = await self.get()
        self.assertEqual(body["exact"], False)


class TestValidation(Case):
    async def test_bad_input_is_a_400_with_a_sentence(self):
        cases = {
            f"ip=not-an-ip&{WINDOWS}": "ip must be an IP address.",
            f"ip=fe80::1%25eth0&{WINDOWS}": "ip must be an IP address.",
            f"{WINDOWS}": "ip must be an IP address.",
            f"ip={DEVICE}&a_from={A_FROM}&a_to={A_TO}&b_from={B_FROM}": "are all required",
            f"ip={DEVICE}&a_from=yesterday&a_to={A_TO}&b_from={B_FROM}&b_to={B_TO}": "ISO 8601",
            f"ip={DEVICE}&a_from={A_TO}&a_to={A_FROM}&b_from={B_FROM}&b_to={B_TO}": "end after it starts",
            f"ip={DEVICE}&a_from={A_FROM}&a_to={A_TO}&b_from={B_FROM}&b_to={B_FROM}": "end after it starts",
            f"ip={DEVICE}&a_from={A_FROM}&a_to={A_TO}&b_from={B_FROM}&b_to=2026-11-05T12:00:02Z": "same length",
            f"ip={DEVICE}&a_from=2026-10-20T00:00:00Z&a_to=2026-10-28T00:00:00Z&b_from=2026-10-28T00:00:00Z&b_to=2026-11-05T00:00:00Z": "at most 7 days",
            f"ip={DEVICE}&a_from={A_FROM}&a_to={A_TO}&b_from=2026-11-05T05:59:59Z&b_to=2026-11-05T11:59:59Z": "must not overlap",
            f"ip={DEVICE}&a_from={A_FROM}&a_to={A_TO}&b_from={A_FROM}&b_to={A_TO}": "must not overlap",
            f"ip={DEVICE}&a_from=2099-01-01T00:00:00Z&a_to=2099-01-01T01:00:00Z&b_from=2099-01-01T01:00:00Z&b_to=2099-01-01T02:00:00Z": "in the future",
        }
        for query, words in cases.items():
            status, body = await self.get(query)
            self.assertEqual(status, 400, query)
            self.assertIn(words, body["error"], query)
        self.assertEqual(self.os.bodies, [])  # nothing reached OpenSearch

    async def test_lengths_within_a_second_and_exactly_7_days_are_taken(self):
        ok = [
            f"ip={DEVICE}&a_from={A_FROM}&a_to={A_TO}&b_from={B_FROM}&b_to=2026-11-05T12:00:01Z",
            f"ip={DEVICE}&a_from=2026-10-22T00:00:00Z&a_to=2026-10-29T00:00:00Z&b_from=2026-10-29T00:00:00Z&b_to=2026-11-05T00:00:00Z",
            f"ip=2001:db8::1&{WINDOWS}",
        ]
        for query in ok:
            status, body = await self.get(query)
            self.assertEqual(status, 200, (query, body))


INCOMPLETE = "Couldn't read the network data: the device compare was incomplete."


class TestShardFailed(Case):
    @staticmethod
    def tamper(body, reply):
        return {**reply, "_shards": {"total": 2, "failed": 1}}

    async def test_is_a_502_never_shorter_lists(self):
        with self.assertLogs("nettap.api.device_compare", "WARNING") as logs:
            status, body = await self.get()
        self.assertEqual((status, body["error"]), (502, INCOMPLETE))
        self.assertIn("shard(s) failed", logs.output[0])  # the reason, in the log only


class TestTimedOut(Case):
    @staticmethod
    def tamper(body, reply):
        raise SearchTimedOut("the search timed out")

    async def test_is_the_written_502(self):
        status, body = await self.get()
        self.assertEqual((status, body["error"]), (502, INCOMPLETE))


class TestOutOfTime(Case):
    @staticmethod
    def tamper(body, reply):
        raise ConnectionTimeout("TIMEOUT", "read timed out", None)

    async def test_is_a_503_too_slow(self):
        status, body = await self.get()
        self.assertEqual(status, 503, body)
        self.assertIn("took too long", body["error"])


class TestShortReply(Case):
    async def test_a_reply_short_of_a_period_is_a_502(self):
        real = self.os.msearch
        with patch.object(
            self.os, "msearch", lambda body, **kw: {"responses": real(body, **kw)["responses"][:1]}
        ):
            status, body = await self.get()
        self.assertEqual((status, body["error"]), (502, INCOMPLETE))


# The shape the G11 answered for a busy device over 24 h (2026-11-13, trimmed to two buckets)
G11_PERIOD = {
    "took": 426,
    "timed_out": False,
    "_shards": {"total": 7, "successful": 7, "skipped": 0, "failed": 0},
    "hits": {"total": {"value": 10000, "relation": "gte"}, "max_score": None, "hits": []},
    "aggregations": {
        "total": {"value": 1717490.0},
        "destinations": {
            "doc_count_error_upper_bound": 0,
            "sum_other_doc_count": 0,
            "buckets": [
                {
                    "key": "146.70.174.142",
                    "doc_count": 1586,
                    "org": {"doc_count_error_upper_bound": 0, "sum_other_doc_count": 0, "buckets": []},
                    "bytes": {"value": 1031410.0},
                },
                {
                    "key": "91.204.255.33",
                    "doc_count": 1493,
                    "org": {
                        "doc_count_error_upper_bound": 0,
                        "sum_other_doc_count": 0,
                        "buckets": [{"key": "AS47635 InfoSet-Com Ltd.", "doc_count": 1493}],
                    },
                    "bytes": {"value": 684777.0},
                },
            ],
        },
    },
    "status": 200,
}


def test_the_g11_reply_shape_reads_as_two_new_destinations():
    empty = {
        **G11_PERIOD,
        "aggregations": {
            "total": {"value": 0.0},
            "destinations": {"doc_count_error_upper_bound": 0, "sum_other_doc_count": 0, "buckets": []},
        },
    }
    a, b = (A_FROM, A_TO), (B_FROM, B_TO)
    out = compare(a, b, empty, G11_PERIOD)
    assert (out["exact"], out["complete"]) == (True, True)
    assert out["b"]["total_bytes"] == 1717490
    assert out["new"]["items"] == [
        {"ip": "146.70.174.142", "org": None, "bytes": 1031410},
        {"ip": "91.204.255.33", "org": "AS47635 InfoSet-Com Ltd.", "bytes": 684777},
    ]
    assert out["changed"] == {"total": 0, "items": [], "partial": False}
