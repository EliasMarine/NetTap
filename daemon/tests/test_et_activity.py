"""ET informational alerts are activity: stored and listed, never counted (NET-191).

ET rates 94% of the G11's alerts Informational (STUN, DNS over HTTPS, …). The owner chose
"counts use ET's Minor, Major and Critical only": every count drops them, ?activity=true lists
them, and a smart-alert group is never part activity, part counted.
"""

import asyncio
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.alerts import (
    ET_ACTIVITY_CLAUSE,
    SURICATA_NOISE_EXCLUSION,
    alert_query,
    register_alert_routes,
)
from services import alert_intelligence
from services.alert_intelligence import get_smart_alert_summary, get_smart_alerts
from storage.manager import RetentionConfig, StorageManager

_FROM, _TO = "2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z"
_ENGINE = {"prefix": {"rule.name": "SURICATA "}}


# --- the shared rule -------------------------------------------------------------------------


def test_every_count_drops_et_informational_and_unknown():
    assert ET_ACTIVITY_CLAUSE == {
        "terms": {
            "suricata.alert.metadata.signature_severity": ["Informational", "Unknown"]
        }
    }
    assert ET_ACTIVITY_CLAUSE in SURICATA_NOISE_EXCLUSION
    assert _ENGINE in SURICATA_NOISE_EXCLUSION


def test_the_private_copies_use_the_shared_rule():
    """traffic.py and live_connections.py kept their own engine-only lists."""
    from api import traffic
    from services.live_connections import LiveConnectionTracker

    assert traffic._SURICATA_NOISE_EXCLUSION is SURICATA_NOISE_EXCLUSION
    assert LiveConnectionTracker._SURICATA_NOISE_EXCLUSION is SURICATA_NOISE_EXCLUSION


def test_alert_query_counted_and_activity_are_disjoint():
    counted = alert_query(_FROM, _TO)["bool"]
    activity = alert_query(_FROM, _TO, activity=True)["bool"]

    assert ET_ACTIVITY_CLAUSE in counted["must_not"]
    assert ET_ACTIVITY_CLAUSE not in counted["filter"]
    assert ET_ACTIVITY_CLAUSE in activity["filter"]
    assert ET_ACTIVITY_CLAUSE not in activity["must_not"]
    # engine events are neither
    assert _ENGINE in counted["must_not"] and _ENGINE in activity["must_not"]


def test_alert_query_keeps_narrow_and_exclude_in_activity_mode():
    narrow, exclude = (
        [{"term": {"rule.name": "x"}}],
        [{"term": {"source.ip": "1.2.3.4"}}],
    )
    q = alert_query(_FROM, _TO, narrow, exclude, activity=True)["bool"]
    assert narrow[0] in q["filter"] and exclude[0] in q["must_not"]


# --- /api/alerts and /api/alerts/count ---------------------------------------------------------


def _storage():
    with patch.object(StorageManager, "_create_client") as create:
        client = MagicMock()
        create.return_value = client
        storage = StorageManager(RetentionConfig(), "http://localhost:9200")
    return storage, client


_EMPTY = {
    "hits": {"total": {"value": 0, "relation": "eq"}, "hits": []},
    "aggregations": {"by_severity": {"buckets": []}},
}


class TestActivityParam(AioHTTPTestCase):
    def setUp(self):
        self.storage, self.client_mock = _storage()
        self.ack = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        self.ack.write("{}")
        self.ack.close()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        os.unlink(self.ack.name)

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        app["alert_ack_file"] = self.ack.name
        register_alert_routes(app, self.storage)
        return app

    def _bool(self):
        return self.client_mock.search.call_args.kwargs["body"]["query"]["bool"]

    @unittest_run_loop
    async def test_list_defaults_to_counted_alerts(self):
        self.client_mock.search.return_value = _EMPTY
        resp = await self.client.request("GET", "/api/alerts")
        assert resp.status == 200
        assert ET_ACTIVITY_CLAUSE in self._bool()["must_not"]

    @unittest_run_loop
    async def test_list_activity_true_lists_only_activity(self):
        self.client_mock.search.return_value = _EMPTY
        resp = await self.client.request("GET", "/api/alerts?activity=true")
        assert resp.status == 200
        q = self._bool()
        assert ET_ACTIVITY_CLAUSE in q["filter"]
        assert ET_ACTIVITY_CLAUSE not in q["must_not"]

    @unittest_run_loop
    async def test_count_activity_true_counts_the_same_alerts_the_list_shows(self):
        self.client_mock.search.return_value = _EMPTY
        window = f"from={_FROM}&to={_TO}"
        resp = await self.client.request(
            "GET", f"/api/alerts/count?activity=true&{window}"
        )
        assert resp.status == 200
        count_query = self.client_mock.search.call_args.kwargs["body"]["query"]
        await self.client.request("GET", f"/api/alerts?activity=true&{window}")
        list_query = self.client_mock.search.call_args.kwargs["body"]["query"]
        assert count_query == list_query

    @unittest_run_loop
    async def test_count_default_counts_only_counted_alerts(self):
        self.client_mock.search.return_value = _EMPTY
        resp = await self.client.request("GET", "/api/alerts/count")
        assert resp.status == 200
        assert ET_ACTIVITY_CLAUSE in self._bool()["must_not"]

    @unittest_run_loop
    async def test_an_unreadable_activity_value_is_a_400(self):
        for path in ("/api/alerts?activity=yes", "/api/alerts/count?activity=1"):
            resp = await self.client.request("GET", path)
            assert resp.status == 400, path
        self.client_mock.search.assert_not_called()

    @unittest_run_loop
    async def test_category_discovery_runs_in_the_same_mode(self):
        """The category filter first lists signatures; in activity mode it must find activity ones."""
        self.client_mock.search.return_value = {
            **_EMPTY,
            "aggregations": {"buckets": {"buckets": []}},
        }
        with patch("api.alerts._every_signature", return_value=[]) as every:
            resp = await self.client.request(
                "GET", "/api/alerts?category=credential_abuse&activity=true"
            )
        assert resp.status == 200
        base = every.call_args.args[1]["bool"]
        assert ET_ACTIVITY_CLAUSE in base["filter"]


# --- smart alerts: counted and activity are separate groups ------------------------------------


def _bucket(sig, src, dst, count, sev=2):
    return {
        "key": {"sig_name": sig, "src_ip": src, "dst_ip": dst},
        "doc_count": count,
        "first_seen": {"value_as_string": "2026-11-01T01:00:00Z"},
        "last_seen": {"value_as_string": "2026-11-01T02:00:00Z"},
        "sample": {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "alert": {
                                "signature": sig,
                                "signature_id": 2000001,
                                "severity": sev,
                                "category": "A Network Trojan was detected",
                            },
                            "destination": {"port": 22},
                        }
                    }
                ]
            }
        },
    }


def _page(buckets):
    return {"aggregations": {"grouped": {"buckets": buckets}}}


def _partitioned_client(counted, activity):
    """Answers the counted query with `counted` and the activity query with `activity`."""
    client = MagicMock()

    def search(index, body):
        is_activity = ET_ACTIVITY_CLAUSE in body["query"]["bool"]["filter"]
        return _page(activity if is_activity else counted)

    client.search.side_effect = search
    return client


# One signature/address pair seen both as ET Major (counted) and ET Informational (activity),
# to an internal SSH port that would normally boost the severity
_SIG, _SRC, _DST = "ET TROJAN Mixed metadata", "203.0.113.5", "192.168.1.24"


def test_without_info_only_the_counted_query_runs():
    client = _partitioned_client([_bucket(_SIG, _SRC, _DST, 3)], [])
    with patch.object(alert_intelligence, "is_suppressed", return_value=False):
        groups = asyncio.run(get_smart_alerts(client, _FROM, _TO, limit=None))
    assert client.search.call_count == 1
    assert (
        ET_ACTIVITY_CLAUSE
        in client.search.call_args.kwargs["body"]["query"]["bool"]["must_not"]
    )
    assert [g["activity"] for g in groups] == [False]


def test_a_pair_seen_in_both_partitions_is_two_groups():
    client = _partitioned_client(
        [_bucket(_SIG, _SRC, _DST, 3)], [_bucket(_SIG, _SRC, _DST, 40)]
    )
    with patch.object(alert_intelligence, "is_suppressed", return_value=False):
        groups = asyncio.run(
            get_smart_alerts(client, _FROM, _TO, limit=None, include_info=True)
        )
    by_activity = {g["activity"]: g for g in groups}
    assert by_activity[False]["count"] == 3
    assert by_activity[True]["count"] == 40
    # activity is informational whatever its prefix or port: never boosted
    assert by_activity[True]["severity"] == 5
    assert by_activity[False]["severity"] < 5
    # the drill-down key is the same pair; the activity flag tells the link which list to open
    assert by_activity[True]["key"] == by_activity[False]["key"]


def test_activity_adds_nothing_to_the_threat_summary():
    counted = [_bucket(_SIG, _SRC, _DST, 3)]
    with (
        patch.object(alert_intelligence, "is_suppressed", return_value=False),
        patch.object(alert_intelligence, "update_baseline", return_value=None),
    ):
        alone = asyncio.run(
            get_smart_alert_summary(_partitioned_client(counted, []), _FROM, _TO)
        )
        with_activity = asyncio.run(
            get_smart_alert_summary(
                _partitioned_client(
                    counted,
                    [
                        _bucket(_SIG, _SRC, _DST, 40),
                        _bucket("ET INFO STUN", "a", "b", 500),
                    ],
                ),
                _FROM,
                _TO,
            )
        )
    for key in (
        "threat_score",
        "threat_level",
        "total_groups",
        "total_events",
        "categories",
    ):
        assert with_activity[key] == alone[key], key
    assert with_activity["informational_events"] == alone["informational_events"] + 540
