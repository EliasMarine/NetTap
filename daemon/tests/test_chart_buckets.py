"""NET-249 slice 2: every time chart's bucket is checked with its window before any search,
and every chart reply names the window and bucket its slots were counted over.

A pick on a chart opens [slot start, slot end - 1 ms] clipped to the reply's window, so the web
needs the bucket the daemon really used. A silent fallback (an unknown interval read as 1h) or
a too-fine bucket that only fails deep in a search would make that window wrong.
"""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import quote, urlencode

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.addresses import register_address_routes
from api.alerts import _sparkline_interval, register_alert_routes
from api.bandwidth import register_bandwidth_routes
from api.devices import _bandwidth_interval, register_device_routes
from api.dns import register_dns_routes
from api.domains import register_domain_routes
from api.iot import register_iot_routes
from api.logs import register_log_routes
from api.suricata_categories import register_suricata_category_routes
from api.time_range import TOO_MANY_SLOTS, slot_interval
from api.traffic import register_traffic_routes
from services.bandwidth_tracker import BandwidthTracker
from services.excluded_ips import build_lan_filter
from services.live_connections import LiveConnectionTracker
from storage.time_slots import slot_count, time_slots
from tests.fake_drill_opensearch import (
    AUTH,
    FROM,
    TO,
    DrillOpenSearch,
    alert,
    conn,
    dns,
    make_app,
)

LAN = build_lan_filter([(192, 168, 1)])
LAPTOP, M_LAPTOP, M_ROUTER = "192.168.1.30", "00:00:5e:00:53:30", "00:00:5e:00:53:01"
ADDR, NAME, CATEGORY = "93.184.216.34", "example.com", "Misc activity"
END = datetime.fromisoformat(TO.replace("Z", "+00:00"))
RANGES = {  # the five standard ranges, ending at TO
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def _iso(when: datetime) -> str:
    return when.isoformat().replace("+00:00", "Z")


def _window(span: timedelta, **extra) -> str:
    return urlencode({"from": _iso(END - span), "to": TO, **extra})


# --------------------------------------------------------------------- slot_count


@pytest.mark.parametrize(
    ("start", "end", "interval"),
    [
        (FROM, FROM, "1m"),  # one instant is one slot
        ("2026-11-05T00:00:30Z", "2026-11-05T01:00:00Z", "5m"),  # an end on a boundary
        ("2026-11-04T23:59:59.999Z", "2026-11-05T00:00:00Z", "1h"),
        ("2026-10-06T12:00:00Z", TO, "3h"),
        ("2026-11-04T12:00:00+02:00", TO, "1d"),  # an offset is read as UTC
    ],
)
def test_slot_count_is_what_time_slots_builds(start, end, interval):
    assert slot_count(start, end, interval) == len(
        time_slots(start, end, interval)["date_range"]["ranges"]
    )


# ------------------------------------------------------------------ slot_interval


def _req(**query) -> SimpleNamespace:
    return SimpleNamespace(query=query, path="/api/test")


def _minutes_after_from(n: int) -> str:
    return _iso(
        datetime.fromisoformat(FROM.replace("Z", "+00:00")) + timedelta(minutes=n)
    )


def test_an_absent_or_empty_interval_is_the_default():
    for query in ({}, {"interval": ""}):
        assert slot_interval(_req(**query), FROM, TO, {"5m", "1h"}, "1h") == "1h"


def test_an_unknown_interval_is_a_400_naming_the_allowed_ones():
    with pytest.raises(web.HTTPBadRequest) as caught:
        slot_interval(_req(interval="2m"), FROM, TO, {"3h", "1m", "1h", "5m"}, "5m")
    assert json.loads(caught.value.text) == {
        "error": "Unknown interval; use one of 1m, 5m, 1h, 3h"
    }


def test_the_budget_counts_slots_as_time_slots_does():
    # 1 min slots from 00:00 to 16:39 inclusive are 1,000; a minute more is 1,001
    assert slot_interval(
        _req(interval="1m"), FROM, _minutes_after_from(999), {"1m"}, "1m"
    )
    for query in ({"interval": "1m"}, {}):  # a defaulted interval meets the same budget
        with pytest.raises(web.HTTPBadRequest) as caught:
            slot_interval(_req(**query), FROM, _minutes_after_from(1000), {"1m"}, "1m")
        assert json.loads(caught.value.text) == {"error": TOO_MANY_SLOTS}


# ------------------------------------------------------------------------ routes


def _register(app, client):
    storage = SimpleNamespace(_client=client)
    app["storage"] = storage
    for register in (
        register_alert_routes,
        register_log_routes,
        register_dns_routes,
        register_traffic_routes,
        register_device_routes,
        register_iot_routes,
    ):
        register(app, storage)
    with patch("services.bandwidth_tracker._CAP_FILE", "/nonexistent/path"):
        register_bandwidth_routes(app, BandwidthTracker(client=client))
    for register in (
        register_address_routes,
        register_domain_routes,
        register_suricata_category_routes,
    ):
        register(app, client)


# Every route whose chart takes `interval` (NET-249 slice 2)
CHART_ROUTES = [
    "/api/alerts/timeline",
    "/api/alerts/categories/malware_c2/timeline",
    "/api/logs/timeline",
    "/api/dns/timeline",
    "/api/traffic/connections/timeline",
    "/api/traffic/categories/streaming/bandwidth",
    f"/api/addresses/{ADDR}",
    f"/api/domains/{NAME}",
    f"/api/alerts/suricata/{quote(CATEGORY)}",
    f"/api/devices/{LAPTOP}",
    f"/api/iot/devices/{quote(M_LAPTOP)}/activity-timeline",
]

DOCS = [
    *[
        conn(LAPTOP, ADDR, t=t, source__mac=M_LAPTOP, destination__mac=M_ROUTER,
             source__bytes=10, destination__bytes=100)
        for t in ("2026-11-05T08:00:00.000Z", "2026-11-05T09:00:00.000Z",
                  "2026-11-05T10:00:00.000Z")
    ],
    # the laptop's IPv6, which the parent window folds in by MAC and one 5 min slot doesn't
    conn("2001:db8::30", "2001:db8:ffff::1", t="2026-11-05T10:01:00.000Z",
         source__mac=M_LAPTOP, destination__mac=M_ROUTER,
         source__bytes=300, destination__bytes=3000),
    dns(NAME, src=LAPTOP, t="2026-11-05T11:30:00.000Z"),
    dns(NAME, src=LAPTOP, t="2026-11-05T06:00:00.000Z"),
    alert(LAPTOP, ADDR, t="2026-11-05T11:15:00.000Z", rule__category=CATEGORY,
          suricata__alert__severity=2),
]  # fmt: skip


class ChartCase(AioHTTPTestCase):
    async def get_application(self):
        self.os = DrillOpenSearch(list(DOCS))
        return make_app(
            self.os,
            _register,
            lan_filter=LAN,
            excluded_ips=["192.168.1.99", "10.0.0.0/8"],
        )

    async def get(self, path, query, status=200):
        resp = await self.client.get(f"{path}?{query}", headers=AUTH)
        body = await resp.json()
        self.assertEqual(resp.status, status, (path, query, body))
        return body


class TestEveryRouteChecksBeforeSearching(ChartCase):
    async def test_an_unknown_interval_is_a_400(self):
        for path in CHART_ROUTES:
            body = await self.get(path, _window(RANGES["24h"], interval="42x"), 400)
            self.assertTrue(body["error"].startswith("Unknown interval"), path)
        self.assertEqual(self.os.bodies, [])

    async def test_too_many_slots_is_a_400_sent_or_defaulted(self):
        for query in (
            _window(RANGES["7d"], interval="1m"),  # valid but too fine: 10,081 slots
            _window(timedelta(days=200), interval="3h"),  # a long custom window: 1,601
            _window(timedelta(days=3000)),  # every route's own default is over budget
        ):
            for path in CHART_ROUTES:
                body = await self.get(path, query, 400)
                self.assertEqual(body, {"error": TOO_MANY_SLOTS}, (path, query))
        self.assertEqual(self.os.bodies, [])

    async def test_routes_with_their_own_bucket_check_the_budget_too(self):
        """NET-275: from=1970 passes the year rule; then 20,772 1 d slots were over MAX_SLOTS,
        time_slots raised and these routes, which take no ?interval=, answered a 500."""
        for path in ("/api/alerts/categories", "/api/bandwidth/daily"):
            body = await self.get(path, "from=1970-01-01T00:00:00Z", 400)
            self.assertEqual(body, {"error": TOO_MANY_SLOTS}, path)
        self.assertEqual(self.os.bodies, [])


class TestRepliesNameTheirWindow(ChartCase):
    async def test_every_chart_reply_echoes_the_window_and_bucket_it_counted(self):
        window = {"from": FROM, "to": TO}
        for path, key in (
            ("/api/alerts/timeline", "interval"),
            ("/api/logs/timeline", "interval"),
            ("/api/dns/timeline", "interval"),
            ("/api/traffic/connections/timeline", "interval"),
            ("/api/traffic/categories/streaming/bandwidth", "interval"),
            (f"/api/addresses/{ADDR}", "interval"),
            (f"/api/domains/{NAME}", "interval"),
            (f"/api/alerts/suricata/{quote(CATEGORY)}", "interval"),
            (f"/api/iot/devices/{quote(M_LAPTOP)}/activity-timeline", "interval"),
            (f"/api/devices/{LAPTOP}", "bandwidth_interval"),
        ):
            body = await self.get(path, urlencode({**window, "interval": "3h"}))
            self.assertEqual(
                (body["from"], body["to"], body[key]), (FROM, TO, "3h"), path
            )

    async def test_bandwidth_daily_names_its_day_buckets(self):
        body = await self.get(
            "/api/bandwidth/daily", urlencode({"from": FROM, "to": TO})
        )
        self.assertEqual((body["from"], body["to"], body["interval"]), (FROM, TO, "1d"))
        self.assertEqual(len(body["daily"]), slot_count(FROM, TO, "1d"))

    async def test_the_alert_and_log_timelines_take_3h(self):
        for path in (
            "/api/alerts/timeline",
            "/api/alerts/categories/malware_c2/timeline",
            "/api/logs/timeline",
        ):
            body = await self.get(path, _window(RANGES["30d"], interval="3h"))
            self.assertEqual(body["interval"], "3h", path)
            slots = body.get("buckets", body.get("series"))
            self.assertEqual(
                len(slots), slot_count(_iso(END - RANGES["30d"]), TO, "3h")
            )

    async def test_the_iot_timeline_names_the_excluded_ips_it_applied(self):
        body = await self.get(
            f"/api/iot/devices/{quote(M_LAPTOP)}/activity-timeline",
            urlencode({"from": FROM, "to": TO, "interval": "5m"}),
        )
        # the CIDR isn't a single IP, so it isn't applied
        self.assertEqual(body["excluded_ips"], ["192.168.1.99"])
        must_not = self.os.bodies[-1]["query"]["bool"]["must_not"]
        self.assertEqual(must_not, [{"terms": {"source.ip": body["excluded_ips"]}}])
        self.assertEqual(len(body["buckets"]), slot_count(FROM, TO, "5m"))
        # the three IPv4 connections and the IPv6 one, by MAC
        self.assertEqual(sum(b["connections"] for b in body["buckets"]), 4)


def _timeline(body: dict) -> list[dict]:
    """The page's chart: the domain page keeps it under `dns`."""
    return body["timeline"] if "timeline" in body else body["dns"]["timeline"]


class TestChartSlotRoutes(ChartCase):
    """The address, domain and Suricata category pages: the bucket table, plus the buckets
    they picked before `interval` existed."""

    PAGES = (
        f"/api/addresses/{ADDR}",
        f"/api/domains/{NAME}",
        f"/api/alerts/suricata/{quote(CATEGORY)}",
    )

    async def test_an_omitted_interval_answers_as_its_legacy_bucket_written_out(self):
        for path in self.PAGES:
            for span in RANGES.values():
                legacy = _sparkline_interval(_iso(END - span), TO)
                omitted = await self.get(path, _window(span))
                explicit = await self.get(path, _window(span, interval=legacy))
                self.assertEqual(omitted["interval"], legacy, path)
                self.assertEqual(omitted, explicit, (path, span))

    async def test_each_table_bucket_gives_its_slots(self):
        span = RANGES["6h"]
        for path in self.PAGES:
            for interval in ("1m", "5m", "1h", "3h"):
                body = await self.get(path, _window(span, interval=interval))
                self.assertEqual(body["interval"], interval, path)
                self.assertEqual(
                    len(_timeline(body)),
                    slot_count(_iso(END - span), TO, interval),
                    (path, interval),
                )
            # the whole window's records, whatever the bucket
            sums = [
                sum(
                    s["n"]
                    for s in _timeline(await self.get(path, _window(span, interval=i)))
                )
                for i in ("1m", "3h")
            ]
            self.assertEqual(sums[0], sums[1], path)
            self.assertGreater(sums[0], 0, path)


class TestOwnBucketRoutes(ChartCase):
    """The device and IoT routes, whose omitted interval is their own default (plan §2)."""

    async def test_an_omitted_interval_answers_as_its_default_written_out(self):
        for span in RANGES.values():
            frm = _iso(END - span)
            for path, key, default, series in (
                (f"/api/devices/{LAPTOP}", "bandwidth_interval",
                 _bandwidth_interval(frm, TO), lambda b: b["device"]["bandwidth_series"]),
                (f"/api/iot/devices/{quote(M_LAPTOP)}/activity-timeline", "interval",
                 "1h", lambda b: b["buckets"]),
            ):  # fmt: skip
                omitted = await self.get(path, _window(span))
                explicit = await self.get(path, _window(span, interval=default))
                self.assertEqual(omitted[key], default, (path, span))
                self.assertEqual(series(omitted), series(explicit), (path, span))


class TestRefusalLog(ChartCase):
    async def test_a_newline_in_the_path_stays_inside_one_log_record(self):
        with self.assertLogs("nettap.api.time_range", "INFO") as logs:
            resp = await self.client.get(
                "/api/iot/devices/x%0A[NetTap]%20ERROR%20forged/activity-timeline?interval=zz",
                headers=AUTH,
            )
        self.assertEqual(resp.status, 400)
        self.assertTrue(logs.records)
        self.assertTrue(all("\n" not in r.getMessage() for r in logs.records))


class TestDeviceAndDns(ChartCase):
    async def test_the_device_chart_takes_a_bucket_or_keeps_its_own(self):
        query = urlencode({"from": FROM, "to": TO})
        own = await self.get(f"/api/devices/{LAPTOP}", query)
        # 12 h: _bandwidth_interval's pick
        self.assertEqual(own["bandwidth_interval"], "5m")
        self.assertEqual(
            len(own["device"]["bandwidth_series"]), slot_count(FROM, TO, "5m")
        )
        hourly = await self.get(f"/api/devices/{LAPTOP}", query + "&interval=1h")
        series = hourly["device"]["bandwidth_series"]
        self.assertEqual((hourly["bandwidth_interval"], len(series)), ("1h", 13))
        total = lambda s: sum(p["upload_bytes"] + p["download_bytes"] for p in s)  # noqa: E731
        self.assertEqual(total(series), total(own["device"]["bandwidth_series"]))

    async def test_a_narrow_bucket_can_count_less_ipv6_than_its_parent_window(self):
        """The device page re-works out which IPv6 is the device's for each window (by MAC,
        from at least three of its connections), so a picked slot can differ from its bar."""
        parent = await self.get(
            f"/api/devices/{LAPTOP}",
            urlencode({"from": FROM, "to": TO, "interval": "5m"}),
        )
        bar = next(
            p for p in parent["device"]["bandwidth_series"]
            if p["timestamp"] == "2026-11-05T10:00:00.000Z"
        )  # fmt: skip
        self.assertEqual(bar["upload_bytes"] + bar["download_bytes"], 110 + 3300)
        picked = await self.get(
            f"/api/devices/{LAPTOP}",
            urlencode({"from": "2026-11-05T10:00:00.000Z", "to": "2026-11-05T10:04:59.999Z",
                       "interval": "5m"}),
        )  # fmt: skip
        series = picked["device"]["bandwidth_series"]
        self.assertEqual(
            sum(p["upload_bytes"] + p["download_bytes"] for p in series), 110
        )
        self.assertEqual(picked["device"]["ipv6_connections"], 0)

    async def test_the_dns_default_still_answers_and_a_longer_default_does_not(self):
        # 1 min over the last 24 h: 1,441 slots
        body = await self.get("/api/dns/timeline", "")
        self.assertEqual((body["interval"], len(body["series"])), ("1m", 1441))
        six_days = timedelta(days=6)  # 8,641 slots, sent or defaulted
        for query in (_window(six_days), _window(six_days, interval="1m")):
            self.assertEqual(
                await self.get("/api/dns/timeline", query, 400),
                {"error": TOO_MANY_SLOTS},
            )


# ------------------------------------------------------------- live connection detail


def _history_body_and_reply(dst_port):
    client = MagicMock()
    client.search.return_value = {"hits": {"total": {"value": 0}, "hits": []}}
    reply = LiveConnectionTracker(client=client).fetch_connection_detail(
        LAPTOP, ADDR, dst_port=dst_port
    )
    body = client.search.call_args_list[2].kwargs["body"]  # query C, the history
    return body, reply["history"]


def test_live_history_uses_one_absolute_window_for_filter_slots_and_reply():
    body, history = _history_body_and_reply(443)
    filters = body["query"]["bool"]["filter"]
    window = [f["range"]["@timestamp"] for f in filters if "range" in f]
    # the filter is the echoed window itself, both ends included, never now-24h date math
    assert window == [{"gte": history["from"], "lte": history["to"]}]
    span = datetime.fromisoformat(
        history["to"].replace("Z", "+00:00")
    ) - datetime.fromisoformat(history["from"].replace("Z", "+00:00"))
    assert span == timedelta(hours=24)
    assert history["interval"] == "5m"
    ranges = body["aggs"]["over_time"]["date_range"]["ranges"]
    assert (
        ranges
        == time_slots(history["from"], history["to"], "5m")["date_range"]["ranges"]
    )
    assert len(ranges) == 289
    # the port the history applied, beside the two-way pair
    assert history["port"] == 443
    assert {"term": {"destination.port": 443}} in filters
    pair = next(f for f in filters if "should" in f.get("bool", {}))["bool"]["should"]
    assert len(pair) == 2  # either direction


def test_live_history_without_a_port_says_so():
    body, history = _history_body_and_reply(None)
    assert history["port"] is None
    assert not any(
        "destination.port" in json.dumps(f) for f in body["query"]["bool"]["filter"]
    )
