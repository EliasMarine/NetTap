"""
NetTap ChangelogService — Network event audit log with OpenSearch persistence.

Records and queries network events (device joins/leaves, alerts, config changes,
etc.) indexed to ``nettap-changelog-*`` in OpenSearch.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from opensearchpy import OpenSearch, OpenSearchException

logger = logging.getLogger("nettap.services.changelog")

CHANGELOG_INDEX_PREFIX = "nettap-changelog"

# OLD CODE START — NET-173: six of these are never written, but the filter offered them all
# # Supported event types
# CHANGELOG_EVENT_TYPES = {
#     "device_joined",
#     "device_left",
#     "alert_triggered",
#     "config_changed",
#     "rule_updated",
#     "capture_started",
#     "capture_stopped",
#     "storage_pruned",
# }
# OLD CODE END
# OLD CODE START — NET-182: the device cap writes its own event now
# # The event types NetTap records: device_registry._log_new_device and the manual storage cleanup
# # in api/server.py. Add a type here only when something writes it.
# CHANGELOG_EVENT_TYPES = {
#     "device_joined",
#     "storage_pruned",
# }
# OLD CODE END
# The event types NetTap records: device_registry._log_new_device, the manual storage cleanup
# in api/server.py and the device cap (api/devices._report_device_cap). Add a type here only when
# something writes it.
CHANGELOG_EVENT_TYPES = {
    "device_joined",
    "storage_pruned",
    "device_cap_reached",
}


class ChangelogService:
    """Network event audit log backed by OpenSearch."""

    def __init__(self, client: OpenSearch) -> None:
        self._client = client

    def _index_name(self) -> str:
        """Generate the daily index name.

        shortcut: events are filed by the day they are written, not by their @timestamp, so a
        backdated device_joined can sit in the next day's index and a manual date-based cleanup
        (storage/manager.py) removes it a day later than its timestamp suggests. Changelog
        indices have no automatic retention tier. The page searches by @timestamp, so what it
        shows is unaffected. File by @timestamp if changelog retention ever becomes automatic.
        """
        today = datetime.now(timezone.utc).strftime("%Y.%m.%d")
        return f"{CHANGELOG_INDEX_PREFIX}-{today}"

    def log_event(
        self,
        event_type: str,
        title: str,
        description: str = "",
        metadata: dict[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        """Record a network event to OpenSearch.

        Args:
            event_type: One of the CHANGELOG_EVENT_TYPES.
            title: Short summary of the event.
            description: Detailed description.
            metadata: Additional key-value data.
            timestamp: When it happened (ISO); now if not given.

        Returns:
            The indexed document with its assigned _id.
        """
        doc = {
            # OLD CODE START — NET-158: always the time of logging; a device join was stamped
            # when the registry refresh ran, up to a refresh window after its first record
            # "@timestamp": datetime.now(timezone.utc).isoformat(),
            # OLD CODE END
            "@timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "title": title,
            "description": description,
            "metadata": metadata or {},
        }

        try:
            result = self._client.index(index=self._index_name(), body=doc)
            doc["_id"] = result.get("_id", "")
            logger.info("Logged changelog event: %s — %s", event_type, title)
        except OpenSearchException as exc:
            logger.error("Failed to log changelog event: %s", exc)
            doc["_id"] = ""

        return doc

    def get_events(
        self,
        from_ts: str | None = None,
        to_ts: str | None = None,
        event_types: list[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query changelog events from OpenSearch.

        Args:
            from_ts: Start of time range (ISO timestamp).
            to_ts: End of time range (ISO timestamp).
            event_types: Filter to these event types only.
            limit: Maximum events to return.

        Returns:
            List of event dicts ordered by timestamp descending.
        """
        now = datetime.now(timezone.utc)
        if not from_ts:
            from_ts = (now - timedelta(days=7)).isoformat()
        if not to_ts:
            to_ts = now.isoformat()

        filters: list[dict] = [
            {
                "range": {
                    "@timestamp": {
                        "gte": from_ts,
                        "lte": to_ts,
                        "format": "strict_date_optional_time",
                    }
                }
            }
        ]

        if event_types:
            filters.append({"terms": {"event_type": event_types}})

        query = {
            "size": min(limit, 1000),
            "query": {"bool": {"filter": filters}},
            "sort": [{"@timestamp": {"order": "desc"}}],
        }

        # OLD CODE START — #96: [] read as "no changes recorded"
        # try:
        #     result = self._client.search(
        #         index=f"{CHANGELOG_INDEX_PREFIX}-*", body=query
        #     )
        # except OpenSearchException as exc:
        #     logger.error("Failed to query changelog events: %s", exc)
        #     return []
        # OLD CODE END
        result = self._client.search(index=f"{CHANGELOG_INDEX_PREFIX}-*", body=query)

        events = []
        for hit in result.get("hits", {}).get("hits", []):
            doc = hit.get("_source", {})
            doc["_id"] = hit.get("_id", "")
            events.append(doc)

        return events

    # OLD CODE START — NET-173: a terms aggregation on event_type, which is dynamically mapped as
    # text (Malcolm's template covers arkime_sessions3-* only), so it failed and the fallback
    # offered all eight types; only two are ever written
    # def get_event_types(self) -> list[str]:
    #     """Return a list of distinct event types seen in the changelog index.
    #
    #     Falls back to the static CHANGELOG_EVENT_TYPES if no data exists.
    #     """
    #     query = {
    #         "size": 0,
    #         # OLD CODE: "aggs": {"event_types": {"terms": {"field": "event_type", "size": 50}}},
    #         # (NET-173: event_type is dynamically mapped as text, so the query failed and the
    #         # fallback offered every type)
    #         "aggs": {
    #             "event_types": {"terms": {"field": "event_type.keyword", "size": 50}}
    #         },
    #     }
    #
    #     try:
    #         result = self._client.search(
    #             index=f"{CHANGELOG_INDEX_PREFIX}-*", body=query
    #         )
    #         buckets = (
    #             result.get("aggregations", {}).get("event_types", {}).get("buckets", [])
    #         )
    #         if buckets:
    #             return [b["key"] for b in buckets]
    #     except OpenSearchException as exc:
    #         logger.warning("Failed to query event types: %s", exc)
    #
    #     return sorted(CHANGELOG_EVENT_TYPES)
    # OLD CODE END
    def get_event_types(self) -> list[str]:
        """The event types NetTap records, for the Changelog filter (NET-173)."""
        return sorted(CHANGELOG_EVENT_TYPES)
