"""Tests for storage.time_slots (#120: date_range slots in place of date_histogram)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from storage.time_slots import MAX_SLOTS, histogram_buckets, interval_seconds, time_slots


def test_slots_are_date_histograms_with_extended_bounds():
    agg = time_slots("2026-11-01T21:42:05Z", "2026-11-02T00:10:00Z", "1h", aggs={"t": {"terms": {"field": "x"}}})
    ranges = agg["date_range"]["ranges"]
    # from the slot holding the start to the slot holding the end, epoch-aligned in UTC
    assert [r["from"] for r in ranges] == [
        "2026-11-01T21:00:00.000Z", "2026-11-01T22:00:00.000Z", "2026-11-01T23:00:00.000Z", "2026-11-02T00:00:00.000Z",
    ]
    assert ranges[-1]["to"] == "2026-11-02T01:00:00.000Z"
    assert agg["date_range"]["field"] == "@timestamp"
    assert agg["aggs"] == {"t": {"terms": {"field": "x"}}}


def test_an_end_on_a_slot_boundary_keeps_that_slot():
    """extended_bounds max is inclusive: a record at exactly the end belongs to the last slot."""
    ranges = time_slots("2026-11-02T00:00:00Z", "2026-11-02T00:10:00Z", "5m")["date_range"]["ranges"]
    assert len(ranges) == 3


def test_buckets_read_like_date_histogram_buckets():
    reply = {"buckets": [
        {"key": "b", "from": 1793581200000.0, "from_as_string": "2026-11-02T01:00:00.000Z", "to": 1.0, "doc_count": 4, "s": {"value": 9}},
        {"key": "a", "from": 1793577600000.0, "from_as_string": "2026-11-02T00:00:00.000Z", "to": 1.0, "doc_count": 2},
    ]}
    assert histogram_buckets(reply) == [
        {"key": 1793577600000, "key_as_string": "2026-11-02T00:00:00.000Z", "doc_count": 2},
        {"key": 1793581200000, "key_as_string": "2026-11-02T01:00:00.000Z", "doc_count": 4, "s": {"value": 9}},
    ]


def test_date_histogram_buckets_pass_through():
    bucket = {"key": 1793577600000, "key_as_string": "2026-11-02T00:00:00.000Z", "doc_count": 2}
    assert histogram_buckets({"buckets": [bucket]}) == [bucket]
    assert histogram_buckets(None) == []


@pytest.mark.parametrize("interval, seconds", [("10s", 10), ("5m", 300), ("1h", 3600), ("1d", 86400)])
def test_fixed_intervals(interval, seconds):
    assert interval_seconds(interval) == seconds


@pytest.mark.parametrize("interval", ["1M", "h", "0m", "-5m", "month"])
def test_other_intervals_are_refused(interval):
    with pytest.raises(ValueError):
        interval_seconds(interval)


def test_too_many_slots_or_a_backwards_range_is_refused():
    with pytest.raises(ValueError):
        time_slots("2026-01-01T00:00:00Z", "2026-11-01T00:00:00Z", "10s")  # far over MAX_SLOTS
    with pytest.raises(ValueError):
        time_slots("2026-11-02T00:00:00Z", "2026-11-01T00:00:00Z", "1h")
    assert MAX_SLOTS >= 30 * 24 * 12
