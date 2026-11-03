"""Exact time slots for charts: a `date_range` aggregation in place of `date_histogram` (#120).

OpenSearch 3.3+ collects a `date_histogram` on `@timestamp` with skip lists. On the G11
(OpenSearch 3.5.0) that put records in the wrong slot — up to ~970 of ~23,000 an hour in
the Log Explorer timeline — while segments still held old copies of rewritten records;
both reads agreed, so nothing looked wrong. One `date_range` over the same slots counted
every slot exactly (= one range filter per slot) and was nearly as fast (0.27 s against
0.21 s for 288 slots, 0.63 s for 8,640).
"""

from datetime import datetime, timezone

MAX_SLOTS = 10_000  # 30 days at 5 min is 8,640
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_ISO_MS = "%Y-%m-%dT%H:%M:%S.000Z"  # how date_histogram writes key_as_string


def interval_seconds(interval: str) -> int:
    """'10s', '5m', '1h', '1d' (date_histogram's fixed intervals) in seconds.

    Raises:
        ValueError: for anything else.
    """
    number, unit = interval[:-1], interval[-1:]
    if unit not in _UNITS or not number.isdigit() or int(number) < 1:
        raise ValueError(f"not a fixed interval: {interval!r}")
    return int(number) * _UNITS[unit]


def _epoch(ts: str | datetime) -> float:
    """Epoch seconds; a time without a zone is UTC, as OpenSearch reads it."""
    when = (
        ts
        if isinstance(ts, datetime)
        else datetime.fromisoformat(ts.replace("Z", "+00:00"))
    )
    return (when if when.tzinfo else when.replace(tzinfo=timezone.utc)).timestamp()


def _iso(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, tz=timezone.utc).strftime(_ISO_MS)


def time_slots(
    start: str | datetime, end: str | datetime, interval: str, aggs: dict | None = None
) -> dict:
    """A `date_range` aggregation with the slots a `fixed_interval` date_histogram with
    `extended_bounds` [start, end] would have: aligned to the epoch in UTC, from the slot
    holding `start` to the slot holding `end`, empty slots included.

    Raises:
        ValueError: for an unknown interval, end before start, or more than MAX_SLOTS slots.
    """
    step = interval_seconds(interval)
    first = _epoch(start) // step * step
    count = int((_epoch(end) - first) // step) + 1
    if count < 1 or count > MAX_SLOTS:
        raise ValueError(f"{count} slots of {interval} between {start} and {end}")
    ranges = [
        {"from": _iso(first + i * step), "to": _iso(first + (i + 1) * step)}
        for i in range(count)
    ]
    agg: dict = {
        "date_range": {
            "field": "@timestamp",
            "format": "strict_date_optional_time",
            "ranges": ranges,
        }
    }
    if aggs:
        agg["aggs"] = aggs
    return agg


def histogram_buckets(agg: dict | None) -> list[dict]:
    """The `time_slots` buckets in date_histogram form, oldest first: `key` (slot start,
    epoch ms), `key_as_string`, `doc_count` and the sub-aggregations. Buckets already in
    date_histogram form (no `from`) pass through unchanged."""
    out = []
    for bucket in (agg or {}).get("buckets") or []:
        if "from" not in bucket:
            out.append(bucket)
            continue
        key = int(bucket["from"])
        rest = {
            k: v
            for k, v in bucket.items()
            if k not in ("key", "from", "to", "from_as_string", "to_as_string")
        }
        out.append({**rest, "key": key, "key_as_string": _iso(key / 1000)})
    return sorted(out, key=lambda b: b.get("key", 0))
