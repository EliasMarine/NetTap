"""#96: IoT figures that need every value of a grouping, not the top N of a terms aggregation.

The fakes answer a terms aggregation the way OpenSearch does (top `size` buckets only) and a
composite aggregation page by page, so each test fails on the capped query and passes on the
paged one.
"""

import os
import sys
from typing import Any
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.iot_monitor import (  # noqa: E402
    ANOMALY_NEW_DESTINATION,
    ANOMALY_NEW_PORT,
    IoTMonitor,
)

MAC = "AA:BB:CC:00:00:01"


def _composite_reply(body: dict, rows: list[dict]) -> dict[str, Any]:
    """One composite page over `rows` ({"key": {field: value}, ...}), keyed by the query's source names."""
    composite = body["aggs"]["all"]["composite"]
    names = {
        spec["terms"]["field"]: name
        for source in composite["sources"]
        for name, spec in source.items()
    }
    buckets = [{**r, "key": {names[f]: v for f, v in r["key"].items()}} for r in rows]
    start = 0
    if "after" in composite:
        start = 1 + next(i for i, b in enumerate(buckets) if b["key"] == composite["after"])
    page = buckets[start : start + composite["size"]]
    after = {"after_key": page[-1]["key"]} if page else {}
    return {"aggregations": {"all": {"buckets": page, **after}}}


def _composite_field(body: dict) -> str | None:
    """The first source's field of a composite query, else None."""
    composite = body.get("aggs", {}).get("all", {}).get("composite")
    if not composite:
        return None
    return next(iter(composite["sources"][0].values()))["terms"]["field"]


def _top(values: list, size: int) -> list[dict]:
    """A terms aggregation's reply: the `size` busiest values (they arrive busiest first)."""
    return [{"key": v, "doc_count": len(values) - i} for i, v in enumerate(values)][:size]


# ---------------------------------------------------------------------------
# 1. The baseline's "known" sets hold every value of the 14 days
# ---------------------------------------------------------------------------

HISTORY = {
    "destination.ip": [f"52.0.0.{i}" for i in range(150)],
    "destination.port": [10_000 + i for i in range(60)],
    "network.protocol": ["tls"],
    "destination.geo.country_name": ["United States"],
}
TERMS_AGG_FIELDS = {
    "destinations": "destination.ip",
    "dest_ports": "destination.port",
    "protocols": "network.protocol",
    "countries": "destination.geo.country_name",
}


def _terms_reply(body: dict, values_by_field: dict[str, list]) -> dict[str, Any]:
    aggs = {
        name: {"buckets": _top(values_by_field[field], body["aggs"][name]["terms"]["size"])}
        for name, field in TERMS_AGG_FIELDS.items()
        if name in body["aggs"]
    }
    return {
        "hits": {"total": {"value": 5000}},
        "aggregations": {**aggs, "hourly_activity": {"buckets": []}, "total_bytes": {"value": 0}},
    }


def _history_search(index: str, body: dict) -> dict[str, Any]:
    field = _composite_field(body)
    if field:
        rows = [{"key": {field: v}, "doc_count": 1} for v in HISTORY[field]]
        return _composite_reply(body, rows)
    return _terms_reply(body, HISTORY)


def _this_hour(destinations: list[str], ports: list[int]):
    current = {
        "destination.ip": destinations,
        "destination.port": ports,
        "network.protocol": ["tls"],
        "destination.geo.country_name": ["United States"],
    }
    return lambda index, body: _terms_reply(body, current)


class TestBaselineKnowsEveryValue:
    def test_known_sets_hold_every_destination_and_port(self):
        client = MagicMock()
        client.search.side_effect = _history_search
        baseline = IoTMonitor(client=client).build_baseline(MAC)

        # was 100 and 50: the top of a terms aggregation
        assert len(baseline["known_destinations"]) == 150
        assert len(baseline["known_ports"]) == 60

    def test_a_quiet_but_familiar_destination_is_not_new(self):
        """An Echo reaching >100 CDN IPs over 14 days got "new destination" anomalies hourly."""
        client = MagicMock()
        client.search.side_effect = _history_search
        iot = IoTMonitor(client=client)
        iot.build_baseline(MAC)

        # 52.0.0.120 and port 10055 were used in the 14 days, outside the old top 100 / 50
        client.search.side_effect = _this_hour(["52.0.0.120", "203.0.113.9"], [10_055])
        anomalies = iot.check_anomalies(MAC)

        new = {(a["type"], a["detail"]) for a in anomalies}
        assert (ANOMALY_NEW_DESTINATION, "52.0.0.120") not in new
        assert (ANOMALY_NEW_PORT, "10055") not in new
        # a destination truly absent from the 14 days is still flagged
        assert (ANOMALY_NEW_DESTINATION, "203.0.113.9") in new

    def test_known_sets_cover_only_this_device_and_window(self):
        client = MagicMock()
        client.search.side_effect = _history_search
        IoTMonitor(client=client).build_baseline(MAC)

        bodies = [c.kwargs["body"] for c in client.search.call_args_list]
        [main] = [b for b in bodies if "hourly_activity" in b["aggs"]]
        paged = [b for b in bodies if _composite_field(b)]
        assert {_composite_field(b) for b in paged} == set(HISTORY)
        assert all(b["query"] == main["query"] for b in paged)
