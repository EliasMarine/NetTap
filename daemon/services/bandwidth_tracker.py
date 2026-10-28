"""
NetTap Bandwidth Tracker

Provides monthly/daily/per-device bandwidth aggregation, projected usage,
and hour-of-day heatmap data. All queries aggregate from arkime_sessions3-*
indices in OpenSearch.
"""

import calendar
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from opensearchpy import OpenSearch, OpenSearchException

logger = logging.getLogger("nettap.services.bandwidth_tracker")

NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

# Default monthly data cap in bytes (0 = no cap)
DEFAULT_MONTHLY_CAP_BYTES = 0

# Settings file for bandwidth cap
_CAP_FILE = os.environ.get("BANDWIDTH_CAP_FILE", "/opt/nettap/data/bandwidth_cap.json")


class BandwidthTracker:
    """Aggregates bandwidth data from OpenSearch arkime sessions."""

    def __init__(self, client: OpenSearch | None = None) -> None:
        self._client = client
        self._monthly_cap_bytes: int = DEFAULT_MONTHLY_CAP_BYTES
        self._load_cap()

    def set_client(self, client: OpenSearch) -> None:
        """Set the OpenSearch client (for deferred initialization)."""
        self._client = client

    def _load_cap(self) -> None:
        """Load monthly cap from settings file if it exists."""
        import json
        try:
            with open(_CAP_FILE, "r") as f:
                data = json.load(f)
                self._monthly_cap_bytes = int(data.get("monthly_cap_bytes", 0))
        except (FileNotFoundError, json.JSONDecodeError, ValueError, TypeError):
            self._monthly_cap_bytes = DEFAULT_MONTHLY_CAP_BYTES

    def save_cap(self, cap_bytes: int) -> None:
        """Save monthly bandwidth cap to settings file."""
        import json
        from pathlib import Path
        self._monthly_cap_bytes = max(0, cap_bytes)
        Path(_CAP_FILE).parent.mkdir(parents=True, exist_ok=True)
        with open(_CAP_FILE, "w") as f:
            json.dump({"monthly_cap_bytes": self._monthly_cap_bytes}, f)

    def get_cap(self) -> dict[str, Any]:
        """Get configured monthly cap and current usage percentage."""
        return {
            "monthly_cap_bytes": self._monthly_cap_bytes,
            "monthly_cap_gb": round(self._monthly_cap_bytes / (1024**3), 1) if self._monthly_cap_bytes else 0,
            "enabled": self._monthly_cap_bytes > 0,
        }

    def _base_filters(self) -> list[dict]:
        """Return base Zeek conn event filters."""
        return [
            {"term": {"event.provider": "zeek"}},
            {"term": {"event.dataset": "conn"}},
        ]

    def _bytes_aggs(self) -> dict:
        """Return standard byte aggregation fields."""
        return {
            "orig_bytes": {"sum": {"field": "client.bytes", "missing": 0}},
            "resp_bytes": {"sum": {"field": "server.bytes", "missing": 0}},
        }

    def get_monthly_usage(self, year: int, month: int) -> dict[str, Any]:
        """Get total bytes in/out for a given month.

        Args:
            year: The year (e.g. 2026).
            month: The month (1-12).

        Returns:
            Dict with total_bytes, orig_bytes, resp_bytes, year, month.
        """
        if not self._client:
            return {"year": year, "month": month, "total_bytes": 0, "orig_bytes": 0, "resp_bytes": 0}

        _, last_day = calendar.monthrange(year, month)
        from_ts = f"{year:04d}-{month:02d}-01T00:00:00Z"
        to_ts = f"{year:04d}-{month:02d}-{last_day:02d}T23:59:59Z"

        query = {
            "size": 0,
            "query": {"bool": {"filter": [
                *self._base_filters(),
                {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
            ]}},
            "aggs": self._bytes_aggs(),
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except OpenSearchException as exc:
            logger.error("OpenSearch error in get_monthly_usage: %s", exc)
            return {"year": year, "month": month, "total_bytes": 0, "orig_bytes": 0, "resp_bytes": 0}

        aggs = result.get("aggregations", {})
        orig = aggs.get("orig_bytes", {}).get("value", 0) or 0
        resp = aggs.get("resp_bytes", {}).get("value", 0) or 0

        return {
            "year": year,
            "month": month,
            "total_bytes": orig + resp,
            "orig_bytes": orig,
            "resp_bytes": resp,
        }

    def get_daily_usage(self, from_ts: str, to_ts: str) -> list[dict[str, Any]]:
        """Get daily byte totals for a date range.

        Args:
            from_ts: ISO timestamp start.
            to_ts: ISO timestamp end.

        Returns:
            List of dicts with date, total_bytes, orig_bytes, resp_bytes.
        """
        if not self._client:
            return []

        query = {
            "size": 0,
            "query": {"bool": {"filter": [
                *self._base_filters(),
                {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
            ]}},
            "aggs": {
                "daily": {
                    "date_histogram": {
                        "field": "@timestamp",
                        "calendar_interval": "1d",
                        "min_doc_count": 0,
                        "extended_bounds": {"min": from_ts, "max": to_ts},
                    },
                    "aggs": self._bytes_aggs(),
                }
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except OpenSearchException as exc:
            logger.error("OpenSearch error in get_daily_usage: %s", exc)
            return []

        buckets = result.get("aggregations", {}).get("daily", {}).get("buckets", [])
        return [
            {
                "date": b.get("key_as_string", b.get("key", "")),
                "total_bytes": (b.get("orig_bytes", {}).get("value", 0) or 0)
                    + (b.get("resp_bytes", {}).get("value", 0) or 0),
                "orig_bytes": b.get("orig_bytes", {}).get("value", 0) or 0,
                "resp_bytes": b.get("resp_bytes", {}).get("value", 0) or 0,
                "connections": b.get("doc_count", 0),
            }
            for b in buckets
        ]

    def get_per_device_usage(self, from_ts: str, to_ts: str, limit: int = 50) -> list[dict[str, Any]]:
        """Get bandwidth usage per source IP device.

        Args:
            from_ts: ISO timestamp start.
            to_ts: ISO timestamp end.
            limit: Max devices to return.

        Returns:
            List of dicts with ip, total_bytes, orig_bytes, resp_bytes.
        """
        if not self._client:
            return []

        query = {
            "size": 0,
            "query": {"bool": {"filter": [
                *self._base_filters(),
                {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
            ]}},
            "aggs": {
                "by_device": {
                    "terms": {"field": "source.ip.keyword", "size": limit},
                    "aggs": {
                        **self._bytes_aggs(),
                        "bucket_sort": {
                            "bucket_sort": {
                                "sort": [{"_count": {"order": "desc"}}],
                            }
                        },
                    },
                }
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except OpenSearchException as exc:
            logger.error("OpenSearch error in get_per_device_usage: %s", exc)
            return []

        buckets = result.get("aggregations", {}).get("by_device", {}).get("buckets", [])
        total_all = sum(
            (b.get("orig_bytes", {}).get("value", 0) or 0)
            + (b.get("resp_bytes", {}).get("value", 0) or 0)
            for b in buckets
        )

        return [
            {
                "ip": b["key"],
                "total_bytes": (b.get("orig_bytes", {}).get("value", 0) or 0)
                    + (b.get("resp_bytes", {}).get("value", 0) or 0),
                "orig_bytes": b.get("orig_bytes", {}).get("value", 0) or 0,
                "resp_bytes": b.get("resp_bytes", {}).get("value", 0) or 0,
                "connection_count": b.get("doc_count", 0),
                "percent_of_total": round(
                    ((b.get("orig_bytes", {}).get("value", 0) or 0)
                     + (b.get("resp_bytes", {}).get("value", 0) or 0))
                    / total_all * 100, 1
                ) if total_all > 0 else 0,
            }
            for b in buckets
        ]

    def get_projected_monthly(self, year: int, month: int) -> dict[str, Any]:
        """Get projected monthly usage based on current rate.

        Uses linear extrapolation: (usage_so_far / days_elapsed) * days_in_month.

        Args:
            year: The year.
            month: The month (1-12).

        Returns:
            Dict with current_bytes, projected_bytes, days_elapsed, days_in_month,
            cap info, and whether projection exceeds cap.
        """
        usage = self.get_monthly_usage(year, month)
        current_bytes = usage["total_bytes"]

        _, days_in_month = calendar.monthrange(year, month)
        now = datetime.now(timezone.utc)

        # Calculate days elapsed in this month
        if now.year == year and now.month == month:
            days_elapsed = now.day + (now.hour / 24.0)
        elif (now.year > year) or (now.year == year and now.month > month):
            days_elapsed = float(days_in_month)
        else:
            days_elapsed = 0.0

        # Project
        if days_elapsed > 0:
            daily_rate = current_bytes / days_elapsed
            projected_bytes = int(daily_rate * days_in_month)
        else:
            projected_bytes = 0

        result: dict[str, Any] = {
            "year": year,
            "month": month,
            "current_bytes": current_bytes,
            "projected_bytes": projected_bytes,
            "days_elapsed": round(days_elapsed, 1),
            "days_in_month": days_in_month,
            "daily_rate_bytes": int(current_bytes / days_elapsed) if days_elapsed > 0 else 0,
        }

        # Add cap info
        if self._monthly_cap_bytes > 0:
            result["cap_bytes"] = self._monthly_cap_bytes
            result["usage_percent"] = round(current_bytes / self._monthly_cap_bytes * 100, 1)
            result["projected_percent"] = round(projected_bytes / self._monthly_cap_bytes * 100, 1)
            result["exceeds_cap"] = projected_bytes > self._monthly_cap_bytes
        else:
            result["cap_bytes"] = 0
            result["usage_percent"] = 0
            result["projected_percent"] = 0
            result["exceeds_cap"] = False

        return result

    def get_hourly_heatmap(self, from_ts: str, to_ts: str) -> list[list[int]]:
        """Get a 7x24 hour-of-day x day-of-week bandwidth matrix.

        Returns a 7-element list (Mon=0..Sun=6), each with 24 hourly byte totals.

        Args:
            from_ts: ISO timestamp start.
            to_ts: ISO timestamp end.

        Returns:
            7x24 matrix of byte totals.
        """
        if not self._client:
            return [[0] * 24 for _ in range(7)]

        query = {
            "size": 0,
            "query": {"bool": {"filter": [
                *self._base_filters(),
                {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
            ]}},
            "aggs": {
                "by_day_of_week": {
                    "terms": {
                        "script": {
                            "source": "doc['@timestamp'].value.dayOfWeek",
                            "lang": "painless",
                        },
                        "size": 7,
                    },
                    "aggs": {
                        "by_hour": {
                            "terms": {
                                "script": {
                                    "source": "doc['@timestamp'].value.hourOfDay",
                                    "lang": "painless",
                                },
                                "size": 24,
                            },
                            "aggs": self._bytes_aggs(),
                        }
                    },
                }
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except OpenSearchException as exc:
            logger.error("OpenSearch error in get_hourly_heatmap: %s", exc)
            return [[0] * 24 for _ in range(7)]

        # Initialize 7x24 matrix
        matrix = [[0] * 24 for _ in range(7)]

        day_buckets = (
            result.get("aggregations", {})
            .get("by_day_of_week", {})
            .get("buckets", [])
        )

        for day_bucket in day_buckets:
            day_key = int(day_bucket["key"])
            # dayOfWeek: 1=Mon, 7=Sun -> index 0=Mon, 6=Sun
            day_idx = day_key - 1
            if 0 <= day_idx <= 6:
                hour_buckets = day_bucket.get("by_hour", {}).get("buckets", [])
                for hour_bucket in hour_buckets:
                    hour = int(hour_bucket["key"])
                    if 0 <= hour <= 23:
                        orig = hour_bucket.get("orig_bytes", {}).get("value", 0) or 0
                        resp = hour_bucket.get("resp_bytes", {}).get("value", 0) or 0
                        matrix[day_idx][hour] = int(orig + resp)

        return matrix
