"""
NetTap Bandwidth Tracker

Provides monthly/daily/per-device bandwidth aggregation, projected usage,
and hour-of-day heatmap data. All queries aggregate from arkime_sessions3-*
indices in OpenSearch.
"""

import calendar
import logging
import math
import os
from datetime import datetime, timezone
from typing import Any

from opensearchpy import OpenSearch

from services.device_accounting import (
    direction_aggs,
    gateways_if_needed,
    split_direction,
)
from services.excluded_ips import (
    CONN_ACCOUNTING,
    # OLD CODE: RFC1918_SOURCE_FILTER, (NET-226: only the per-device read used it)
    build_excluded_ips_filter,
)
from storage.time_slots import histogram_buckets, time_slots

logger = logging.getLogger("nettap.services.bandwidth_tracker")

NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

# Default monthly data cap in bytes (0 = no cap)
DEFAULT_MONTHLY_CAP_BYTES = 0

# Settings file for bandwidth cap
_CAP_FILE = os.environ.get("BANDWIDTH_CAP_FILE", "/opt/nettap/data/bandwidth_cap.json")


# Per-connection on-the-wire bytes, so terms can be ordered by device bandwidth
_TOTAL_BYTES_SUM = {
    "sum": {
        "script": {
            "source": "(doc['source.bytes'].size() > 0 ? doc['source.bytes'].value : 0)"
            " + (doc['destination.bytes'].size() > 0 ? doc['destination.bytes'].value : 0)",
            "lang": "painless",
        }
    }
}


def internet_bytes(usage: dict) -> int:
    """What crossed the ISP link: upload + download, without traffic between your own devices."""
    return int(usage.get("upload_bytes", 0) + usage.get("download_bytes", 0))


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
            # OLD CODE: round(self._monthly_cap_bytes / (1024**3), 1) (NET-166: GiB labelled GB)
            "monthly_cap_gb": round(self._monthly_cap_bytes / 1e9, 1)
            if self._monthly_cap_bytes
            else 0,
            "enabled": self._monthly_cap_bytes > 0,
        }

    def _base_filters(self) -> list[dict]:
        """Return base Zeek conn event filters."""
        return [
            {"term": {"event.provider": "zeek"}},
            # OLD CODE START — F1: also counted conn_long.log interim records
            # {"term": {"event.dataset": "conn"}},
            # OLD CODE END
            CONN_ACCOUNTING,
        ]

    def _bytes_aggs(self) -> dict:
        """Return standard byte aggregation fields."""
        # OLD CODE START — replaced 2026-11-01: client/server.bytes are Zeek orig_bytes/
        # resp_bytes (payload only), so monthly usage read lower than the 24 h summary
        # return {
        #     "orig_bytes": {"sum": {"field": "client.bytes", "missing": 0}},
        #     "resp_bytes": {"sum": {"field": "server.bytes", "missing": 0}},
        # }
        # OLD CODE END
        # source/destination.bytes are Zeek orig_ip_bytes/resp_ip_bytes: bytes on the wire
        return {
            "orig_bytes": {"sum": {"field": "source.bytes", "missing": 0}},
            "resp_bytes": {"sum": {"field": "destination.bytes", "missing": 0}},
        }

    def get_monthly_usage(
        self,
        year: int,
        month: int,
        excluded_ips: list[str] | None = None,
        lan_filter: dict | None = None,
    ) -> dict[str, Any]:
        """Get total bytes in/out for a given month.

        Args:
            year: The year (e.g. 2026).
            month: The month (1-12).
            excluded_ips: Optional list of IPs to exclude from results.
            lan_filter: The LAN rule, for upload/download/local (NET-226).

        Returns:
            Dict with total_bytes, orig_bytes, resp_bytes, upload_bytes, download_bytes,
            local_bytes, year, month.
        """
        if not self._client:
            return {
                "year": year,
                "month": month,
                "total_bytes": 0,
                "orig_bytes": 0,
                "resp_bytes": 0,
            }

        _, last_day = calendar.monthrange(year, month)
        from_ts = f"{year:04d}-{month:02d}-01T00:00:00Z"
        to_ts = f"{year:04d}-{month:02d}-{last_day:02d}T23:59:59Z"

        excluded = build_excluded_ips_filter(excluded_ips or [])
        bool_clause: dict = {
            "filter": [
                *self._base_filters(),
                {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
            ]
        }
        if excluded:
            bool_clause["must_not"] = excluded

        query = {
            "size": 0,
            "query": {"bool": bool_clause},
            # OLD CODE: "aggs": self._bytes_aggs(), (NET-226: + the direction split)
            "aggs": {**self._bytes_aggs(), **direction_aggs(lan_filter)},
        }

        # OLD CODE START — #96: a failed query read as 0 bytes used this month
        # try:
        #     result = self._client.search(index=NETWORK_INDEX, body=query)
        # except OpenSearchException as exc:
        #     logger.error("OpenSearch error in get_monthly_usage: %s", exc)
        #     return {"year": year, "month": month, "total_bytes": 0, "orig_bytes": 0, "resp_bytes": 0}
        # OLD CODE END
        result = self._client.search(index=NETWORK_INDEX, body=query)

        aggs = result.get("aggregations", {})
        orig = aggs.get("orig_bytes", {}).get("value", 0) or 0
        resp = aggs.get("resp_bytes", {}).get("value", 0) or 0
        gateways = gateways_if_needed(
            self._client, [aggs], bool_clause["filter"], lan_filter, "monthly usage"
        )

        return {
            "year": year,
            "month": month,
            "total_bytes": orig + resp,
            "orig_bytes": orig,
            "resp_bytes": resp,
            **split_direction(orig, resp, aggs, gateways),
        }

    def get_daily_usage(
        self,
        from_ts: str,
        to_ts: str,
        excluded_ips: list[str] | None = None,
        lan_filter: dict | None = None,
    ) -> list[dict[str, Any]]:
        """Get daily byte totals for a date range.

        Args:
            from_ts: ISO timestamp start.
            to_ts: ISO timestamp end.
            excluded_ips: Optional list of IPs to exclude from results.
            lan_filter: The LAN rule, for upload/download/local (NET-226).

        Returns:
            List of dicts with date, total_bytes, orig_bytes, resp_bytes, upload_bytes,
            download_bytes, local_bytes.
        """
        if not self._client:
            return []

        excluded = build_excluded_ips_filter(excluded_ips or [])
        bool_clause: dict = {
            "filter": [
                *self._base_filters(),
                {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
            ]
        }
        if excluded:
            bool_clause["must_not"] = excluded

        query = {
            "size": 0,
            "query": {"bool": bool_clause},
            "aggs": {
                "daily": {
                    # OLD CODE START — #120: OpenSearch 3.5's skip-list date_histogram misplaces records
                    # "date_histogram": {
                    #     "field": "@timestamp",
                    #     "calendar_interval": "1d",
                    #     "min_doc_count": 0,
                    #     "extended_bounds": {"min": from_ts, "max": to_ts},
                    # },
                    # OLD CODE END
                    **time_slots(
                        from_ts, to_ts, "1d"
                    ),  # UTC days, like calendar_interval 1d
                    # OLD CODE: "aggs": self._bytes_aggs(), (NET-226: + the direction split)
                    "aggs": {**self._bytes_aggs(), **direction_aggs(lan_filter)},
                }
            },
        }

        # OLD CODE START — #96: a failed query read as no traffic on any day
        # try:
        #     result = self._client.search(index=NETWORK_INDEX, body=query)
        # except OpenSearchException as exc:
        #     logger.error("OpenSearch error in get_daily_usage: %s", exc)
        #     return []
        # OLD CODE END
        result = self._client.search(index=NETWORK_INDEX, body=query)

        buckets = histogram_buckets(
            result.get("aggregations", {}).get("daily")
        )  # date_histogram before #120
        gateways = gateways_if_needed(
            self._client, buckets, bool_clause["filter"], lan_filter, "daily usage"
        )
        return [
            {
                "date": b.get("key_as_string", b.get("key", "")),
                "total_bytes": (b.get("orig_bytes", {}).get("value", 0) or 0)
                + (b.get("resp_bytes", {}).get("value", 0) or 0),
                "orig_bytes": b.get("orig_bytes", {}).get("value", 0) or 0,
                "resp_bytes": b.get("resp_bytes", {}).get("value", 0) or 0,
                **split_direction(
                    b.get("orig_bytes", {}).get("value", 0) or 0,
                    b.get("resp_bytes", {}).get("value", 0) or 0,
                    b,
                    gateways,
                ),
                "connections": b.get("doc_count", 0),
            }
            for b in buckets
        ]

    # OLD CODE START — NET-226: /api/bandwidth/devices reads the device list's accounting
    # (api.devices._accounted_devices): both sides of each connection and IPv6 by MAC
    # def get_per_device_usage(
    #     self,
    #     from_ts: str,
    #     to_ts: str,
    #     limit: int = 50,
    #     excluded_ips: list[str] | None = None,
    #     lan_filter: dict | None = None,
    # ) -> list[dict[str, Any]]:
    #     """Get bandwidth usage per source IP device.
    #
    #     Args:
    #         from_ts: ISO timestamp start.
    #         to_ts: ISO timestamp end.
    #         limit: Max devices to return.
    #         excluded_ips: Optional list of IPs to exclude from results.
    #         lan_filter: Source filter for LAN devices (the device list's rule);
    #             defaults to RFC1918 sources.
    #
    #     Returns:
    #         List of dicts with ip, total_bytes, orig_bytes, resp_bytes, sorted by
    #         total bytes; percent_of_total is the share of all LAN traffic.
    #     """
    #     if not self._client:
    #         return []
    #
    #     excluded = build_excluded_ips_filter(excluded_ips or [])
    #     # OLD CODE START — replaced 2026-11-01: the top 50 sources by connection count,
    #     # sorted by count, internet hosts included, and % of those 50 only. NetTap
    #     # itself (6.9 MB, 26K conns) ranked above a 22.7 GB device on the G11.
    #     # bool_clause: dict = {"filter": [*self._base_filters(), {"range": ...}]}
    #     # "by_device": {"terms": {"field": "source.ip", "size": limit},
    #     #     "aggs": {**self._bytes_aggs(), "bucket_sort": {"bucket_sort": {
    #     #         "sort": [{"_count": {"order": "desc"}}]}}}}
    #     # total_all = sum(orig + resp for b in buckets)
    #     # OLD CODE END
    #     bool_clause: dict = {
    #         "filter": [
    #             *self._base_filters(),
    #             {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
    #             lan_filter or RFC1918_SOURCE_FILTER,
    #         ]
    #     }
    #     if excluded:
    #         bool_clause["must_not"] = excluded
    #
    #     query = {
    #         "size": 0,
    #         "query": {"bool": bool_clause},
    #         "aggs": {
    #             **self._bytes_aggs(),
    #             "by_device": {
    #                 "terms": {
    #                     "field": "source.ip",
    #                     "size": limit,
    #                     "order": {"total_bytes": "desc"},
    #                 },
    #                 "aggs": {**self._bytes_aggs(), "total_bytes": _TOTAL_BYTES_SUM},
    #             },
    #         },
    #     }
    #
    #     # OLD CODE START — #96: a failed query read as no device using bandwidth
    #     # try:
    #     #     result = self._client.search(index=NETWORK_INDEX, body=query)
    #     # except OpenSearchException as exc:
    #     #     logger.error("OpenSearch error in get_per_device_usage: %s", exc)
    #     #     return []
    #     # OLD CODE END
    #     result = self._client.search(index=NETWORK_INDEX, body=query)
    #
    #     aggs = result.get("aggregations", {})
    #     buckets = aggs.get("by_device", {}).get("buckets", [])
    #     total_all = (aggs.get("orig_bytes", {}).get("value", 0) or 0) + (
    #         aggs.get("resp_bytes", {}).get("value", 0) or 0
    #     )
    #
    #     return [
    #         {
    #             "ip": b["key"],
    #             "total_bytes": (b.get("orig_bytes", {}).get("value", 0) or 0)
    #             + (b.get("resp_bytes", {}).get("value", 0) or 0),
    #             "orig_bytes": b.get("orig_bytes", {}).get("value", 0) or 0,
    #             "resp_bytes": b.get("resp_bytes", {}).get("value", 0) or 0,
    #             "connection_count": b.get("doc_count", 0),
    #             "percent_of_total": round(
    #                 (
    #                     (b.get("orig_bytes", {}).get("value", 0) or 0)
    #                     + (b.get("resp_bytes", {}).get("value", 0) or 0)
    #                 )
    #                 / total_all
    #                 * 100,
    #                 1,
    #             )
    #             if total_all > 0
    #             else 0,
    #         }
    #         for b in buckets
    #     ]
    # OLD CODE END

    # OLD CODE: def get_projected_monthly(self, year: int, month: int, excluded_ips: list[str] | None = None) -> dict[str, Any]:
    def get_projected_monthly(
        self,
        year: int,
        month: int,
        excluded_ips: list[str] | None = None,
        usage: dict | None = None,
    ) -> dict[str, Any]:
        """Get projected monthly usage based on current rate.

        Uses linear extrapolation: (usage_so_far / days_elapsed) * days_in_month.

        Args:
            year: The year.
            month: The month (1-12).
            excluded_ips: Optional list of IPs to exclude from results.
            usage: get_monthly_usage() for the same month, filters and LAN rule, if already read.

        Returns:
            Dict with current_bytes, projected_bytes, days_elapsed, days_in_month,
            cap info, and whether projection exceeds cap. Bytes are internet bytes
            (upload + download): local traffic never crosses the ISP link (NET-226 follow-up).
        """
        # OLD CODE START — NET-226 follow-up: counted traffic between your own devices too
        # usage = self.get_monthly_usage(year, month, excluded_ips=excluded_ips)
        # current_bytes = usage["total_bytes"]
        # OLD CODE END
        usage = usage or self.get_monthly_usage(year, month, excluded_ips=excluded_ips)
        current_bytes = internet_bytes(usage)

        _, days_in_month = calendar.monthrange(year, month)
        now = datetime.now(timezone.utc)

        # Calculate days elapsed in this month
        if now.year == year and now.month == month:
            # OLD CODE START — 2026-11-06 (O1): counted the current day as already over, so
            # 06:00 on the 1st was 1.25 days in: the rate and projection were a day too low
            # days_elapsed = now.day + (now.hour / 24.0)
            # OLD CODE END
            month_start = datetime(year, month, 1, tzinfo=timezone.utc)
            days_elapsed = (now - month_start).total_seconds() / 86400
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
            # OLD CODE START — 2026-11-06 (O1): rounding up read "0 days remaining" before the month ended
            # "days_elapsed": round(days_elapsed, 1),
            # OLD CODE END
            # Rounded down: the page's days remaining is days_in_month minus its whole days
            "days_elapsed": math.floor(days_elapsed * 10) / 10,
            "days_in_month": days_in_month,
            "daily_rate_bytes": int(current_bytes / days_elapsed)
            if days_elapsed > 0
            else 0,
        }

        # Add cap info
        if self._monthly_cap_bytes > 0:
            result["cap_bytes"] = self._monthly_cap_bytes
            result["usage_percent"] = round(
                current_bytes / self._monthly_cap_bytes * 100, 1
            )
            result["projected_percent"] = round(
                projected_bytes / self._monthly_cap_bytes * 100, 1
            )
            result["exceeds_cap"] = projected_bytes > self._monthly_cap_bytes
        else:
            result["cap_bytes"] = 0
            result["usage_percent"] = 0
            result["projected_percent"] = 0
            result["exceeds_cap"] = False

        return result

    def get_hourly_heatmap(
        self,
        from_ts: str,
        to_ts: str,
        excluded_ips: list[str] | None = None,
        tz: str = "UTC",
    ) -> list[list[int]]:
        """Get a 7x24 hour-of-day x day-of-week bandwidth matrix.

        Returns a 7-element list (Mon=0..Sun=6), each with 24 hourly byte totals.

        Args:
            from_ts: ISO timestamp start.
            to_ts: ISO timestamp end.
            excluded_ips: Optional list of IPs to exclude from results.
            tz: IANA time zone the days and hours are counted in (the caller validates it).

        Returns:
            7x24 matrix of byte totals.
        """
        if not self._client:
            return [[0] * 24 for _ in range(7)]

        excluded = build_excluded_ips_filter(excluded_ips or [])
        bool_clause: dict = {
            "filter": [
                *self._base_filters(),
                {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
            ]
        }
        if excluded:
            bool_clause["must_not"] = excluded

        # OLD CODE START — Joda getters OpenSearch 3.x removed ("dynamic getter
        # [java.time.ZonedDateTime, hourOfDay] not found"): the data shard failed and the heatmap
        # read empty; and the hours were UTC, so a Pacific evening showed at 02:00-06:00
        # "script": {"source": "doc['@timestamp'].value.dayOfWeek", "lang": "painless"},
        # "script": {"source": "doc['@timestamp'].value.hourOfDay", "lang": "painless"},
        # OLD CODE END
        local = "doc['@timestamp'].value.withZoneSameInstant(ZoneId.of(params.tz))"
        query = {
            "size": 0,
            "query": {"bool": bool_clause},
            "aggs": {
                "by_day_of_week": {
                    "terms": {
                        "script": {
                            # 1=Mon..7=Sun
                            "source": f"{local}.getDayOfWeek().getValue()",
                            "lang": "painless",
                            "params": {"tz": tz},
                        },
                        "size": 7,
                    },
                    "aggs": {
                        "by_hour": {
                            "terms": {
                                "script": {
                                    "source": f"{local}.getHour()",
                                    "lang": "painless",
                                    "params": {"tz": tz},
                                },
                                "size": 24,
                            },
                            "aggs": self._bytes_aggs(),
                        }
                    },
                }
            },
        }

        # OLD CODE START — #96: a failed query read as an all-zero heatmap
        # try:
        #     result = self._client.search(index=NETWORK_INDEX, body=query)
        # except OpenSearchException as exc:
        #     logger.error("OpenSearch error in get_hourly_heatmap: %s", exc)
        #     return [[0] * 24 for _ in range(7)]
        # OLD CODE END
        result = self._client.search(index=NETWORK_INDEX, body=query)

        # Initialize 7x24 matrix
        matrix = [[0] * 24 for _ in range(7)]

        day_buckets = (
            result.get("aggregations", {}).get("by_day_of_week", {}).get("buckets", [])
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
