"""
NetTap IoT Monitor Service

Classifies devices as IoT based on OUI/manufacturer matching,
builds behavioral baselines from historical data, and detects
anomalies by comparing current behavior to learned patterns.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("nettap.services.iot_monitor")

NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

# Known IoT manufacturer prefixes (case-insensitive matching)
IOT_MANUFACTURERS = {
    "ring",
    "nest",
    "google nest",
    "wyze",
    "tp-link",
    "kasa",
    "roku",
    "amazon",
    "echo",
    "fire tv",
    "sonos",
    "philips hue",
    "lifx",
    "wemo",
    "belkin",
    "tuya",
    "smartthings",
    "samsung smartthings",
    "arlo",
    "blink",
    "eufy",
    "ecobee",
    "honeywell",
    "lutron",
    "chamberlain",
    "myq",
    "august",
    "yale",
    "simplisafe",
    "abode",
    "wink",
    "hubitat",
    "shelly",
    "tasmota",
    "espressif",
    "raspberry pi",
    "arduino",
    "particle",
}

# Anomaly type constants
ANOMALY_NEW_DESTINATION = "NEW_DESTINATION"
ANOMALY_NEW_COUNTRY = "NEW_COUNTRY"
ANOMALY_NEW_PORT = "NEW_PORT"
ANOMALY_UNUSUAL_TIME = "UNUSUAL_TIME"
ANOMALY_VOLUME_SPIKE = "VOLUME_SPIKE"
ANOMALY_PROTOCOL_CHANGE = "PROTOCOL_CHANGE"


def _time_range_filter(from_ts: str, to_ts: str) -> dict:
    """Build an OpenSearch range filter on '@timestamp'."""
    return {
        "range": {
            "@timestamp": {
                "gte": from_ts,
                "lte": to_ts,
                "format": "strict_date_optional_time",
            }
        }
    }


class IoTMonitor:
    """IoT device classification, baseline building, and anomaly detection."""

    def __init__(self, client: Any):
        self._client = client
        # In-memory baselines keyed by MAC address
        self._baselines: dict[str, dict[str, Any]] = {}
        # In-memory IoT device registry
        self._iot_devices: dict[str, dict[str, Any]] = {}

    def classify_as_iot(
        self, device_mac: str, device_info: dict[str, Any]
    ) -> bool:
        """Classify a device as IoT based on manufacturer OUI matching.

        Args:
            device_mac: Device MAC address.
            device_info: Dict with 'manufacturer', 'hostname', etc.

        Returns:
            True if classified as IoT.
        """
        mac = device_mac.strip().upper()
        manufacturer = (device_info.get("manufacturer") or "").lower()
        hostname = (device_info.get("hostname") or "").lower()

        is_iot = any(
            vendor in manufacturer or vendor in hostname
            for vendor in IOT_MANUFACTURERS
        )

        if is_iot:
            self._iot_devices[mac] = {
                "mac": mac,
                "manufacturer": device_info.get("manufacturer", "Unknown"),
                "hostname": device_info.get("hostname"),
                "ip": device_info.get("ip"),
                "classified_at": datetime.now(timezone.utc).isoformat(),
                "is_iot": True,
            }

        return is_iot

    def build_baseline(
        self, device_mac: str, days: int = 14
    ) -> dict[str, Any]:
        """Build a behavioral baseline for a device from historical data.

        Queries OpenSearch for the device's traffic over the last N days
        and learns normal destinations, ports, volumes, and active hours.
        """
        mac = device_mac.strip().upper()
        now = datetime.now(timezone.utc)
        # Build from_ts as N days ago
        from datetime import timedelta
        from_iso = (now - timedelta(days=days)).isoformat()
        to_iso = now.isoformat()

        # Query for device traffic patterns
        query = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        _time_range_filter(from_iso, to_iso),
                        {"term": {"event.provider": "zeek"}},
                        {"term": {"event.dataset": "conn"}},
                        {
                            "bool": {
                                "should": [
                                    {"term": {"source.mac.keyword": mac}},
                                    {"term": {"source.mac.keyword": mac.lower()}},
                                ],
                                "minimum_should_match": 1,
                            }
                        },
                    ]
                }
            },
            "aggs": {
                "destinations": {
                    "terms": {"field": "destination.ip.keyword", "size": 100}
                },
                "dest_ports": {
                    "terms": {"field": "destination.port", "size": 50}
                },
                "protocols": {
                    "terms": {"field": "network.transport.keyword", "size": 10}
                },
                "hourly_activity": {
                    "date_histogram": {
                        "field": "@timestamp",
                        "calendar_interval": "hour",
                    }
                },
                "total_bytes": {
                    "sum": {"field": "client.bytes", "missing": 0}
                },
                "countries": {
                    "terms": {
                        "field": "destination.geo.country_name.keyword",
                        "size": 20,
                        "missing": "Unknown",
                    }
                },
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except Exception as exc:
            logger.error("Failed to build baseline for %s: %s", mac, exc)
            return {"error": str(exc)}

        aggs = result.get("aggregations", {})

        # Extract known destinations
        destinations = [
            b["key"]
            for b in aggs.get("destinations", {}).get("buckets", [])
        ]

        # Extract known ports
        ports = [
            b["key"]
            for b in aggs.get("dest_ports", {}).get("buckets", [])
        ]

        # Extract known protocols
        protocols = [
            b["key"]
            for b in aggs.get("protocols", {}).get("buckets", [])
        ]

        # Extract known countries
        countries = [
            b["key"]
            for b in aggs.get("countries", {}).get("buckets", [])
        ]

        # Calculate active hours from histogram
        hourly = aggs.get("hourly_activity", {}).get("buckets", [])
        active_hours: set[int] = set()
        for bucket in hourly:
            if bucket.get("doc_count", 0) > 0:
                ts = bucket.get("key_as_string", "")
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    active_hours.add(dt.hour)
                except (ValueError, TypeError):
                    pass

        total_bytes = aggs.get("total_bytes", {}).get("value", 0) or 0
        connection_count = result.get("hits", {}).get("total", {})
        if isinstance(connection_count, dict):
            connection_count = connection_count.get("value", 0)

        # Calculate daily average
        daily_avg_bytes = total_bytes / max(days, 1)

        baseline = {
            "mac": mac,
            "built_at": now.isoformat(),
            "period_days": days,
            "known_destinations": destinations,
            "known_ports": ports,
            "known_protocols": protocols,
            "known_countries": countries,
            "active_hours": sorted(active_hours),
            "total_bytes": total_bytes,
            "daily_avg_bytes": daily_avg_bytes,
            "connection_count": connection_count,
        }

        self._baselines[mac] = baseline
        return baseline

    def check_anomalies(
        self, device_mac: str
    ) -> list[dict[str, Any]]:
        """Compare current (last 1h) behavior against baseline.

        Returns a list of anomaly dicts.
        """
        mac = device_mac.strip().upper()
        baseline = self._baselines.get(mac)

        if not baseline:
            return []

        now = datetime.now(timezone.utc)
        from datetime import timedelta
        from_iso = (now - timedelta(hours=1)).isoformat()
        to_iso = now.isoformat()

        query = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        _time_range_filter(from_iso, to_iso),
                        {"term": {"event.provider": "zeek"}},
                        {"term": {"event.dataset": "conn"}},
                        {
                            "bool": {
                                "should": [
                                    {"term": {"source.mac.keyword": mac}},
                                    {"term": {"source.mac.keyword": mac.lower()}},
                                ],
                                "minimum_should_match": 1,
                            }
                        },
                    ]
                }
            },
            "aggs": {
                "destinations": {
                    "terms": {"field": "destination.ip.keyword", "size": 100}
                },
                "dest_ports": {
                    "terms": {"field": "destination.port", "size": 50}
                },
                "protocols": {
                    "terms": {"field": "network.transport.keyword", "size": 10}
                },
                "total_bytes": {
                    "sum": {"field": "client.bytes", "missing": 0}
                },
                "countries": {
                    "terms": {
                        "field": "destination.geo.country_name.keyword",
                        "size": 20,
                        "missing": "Unknown",
                    }
                },
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except Exception as exc:
            logger.error("Anomaly check failed for %s: %s", mac, exc)
            return []

        aggs = result.get("aggregations", {})
        anomalies: list[dict[str, Any]] = []
        known_dests = set(baseline.get("known_destinations", []))
        known_ports = set(baseline.get("known_ports", []))
        known_protocols = set(baseline.get("known_protocols", []))
        known_countries = set(baseline.get("known_countries", []))
        active_hours = set(baseline.get("active_hours", []))

        # Check new destinations
        for b in aggs.get("destinations", {}).get("buckets", []):
            if b["key"] not in known_dests:
                anomalies.append({
                    "type": ANOMALY_NEW_DESTINATION,
                    "mac": mac,
                    "detail": b["key"],
                    "count": b["doc_count"],
                    "severity": "medium",
                    "description": f"New destination IP {b['key']} not in baseline",
                    "detected_at": now.isoformat(),
                })

        # Check new countries
        for b in aggs.get("countries", {}).get("buckets", []):
            if b["key"] not in known_countries and b["key"] != "Unknown":
                anomalies.append({
                    "type": ANOMALY_NEW_COUNTRY,
                    "mac": mac,
                    "detail": b["key"],
                    "count": b["doc_count"],
                    "severity": "high",
                    "description": f"Traffic to new country: {b['key']}",
                    "detected_at": now.isoformat(),
                })

        # Check new ports
        for b in aggs.get("dest_ports", {}).get("buckets", []):
            if b["key"] not in known_ports:
                anomalies.append({
                    "type": ANOMALY_NEW_PORT,
                    "mac": mac,
                    "detail": str(b["key"]),
                    "count": b["doc_count"],
                    "severity": "medium",
                    "description": f"New destination port {b['key']}",
                    "detected_at": now.isoformat(),
                })

        # Check protocol changes
        for b in aggs.get("protocols", {}).get("buckets", []):
            if b["key"] not in known_protocols:
                anomalies.append({
                    "type": ANOMALY_PROTOCOL_CHANGE,
                    "mac": mac,
                    "detail": b["key"],
                    "count": b["doc_count"],
                    "severity": "medium",
                    "description": f"New protocol: {b['key']}",
                    "detected_at": now.isoformat(),
                })

        # Check volume spike (current hourly rate vs daily average / 24)
        current_bytes = aggs.get("total_bytes", {}).get("value", 0) or 0
        hourly_avg = baseline.get("daily_avg_bytes", 0) / 24
        if hourly_avg > 0 and current_bytes > hourly_avg * 5:
            anomalies.append({
                "type": ANOMALY_VOLUME_SPIKE,
                "mac": mac,
                "detail": f"{current_bytes} bytes (avg: {hourly_avg:.0f}/hr)",
                "severity": "high",
                "description": (
                    f"Volume spike: {current_bytes} bytes in last hour "
                    f"vs {hourly_avg:.0f} hourly average"
                ),
                "detected_at": now.isoformat(),
            })

        # Check unusual time
        current_hour = now.hour
        if active_hours and current_hour not in active_hours:
            anomalies.append({
                "type": ANOMALY_UNUSUAL_TIME,
                "mac": mac,
                "detail": f"Hour {current_hour}",
                "severity": "low",
                "description": (
                    f"Activity at unusual hour ({current_hour}:00) "
                    f"outside normal schedule"
                ),
                "detected_at": now.isoformat(),
            })

        return anomalies

    def get_iot_devices(self) -> list[dict[str, Any]]:
        """Return all IoT-classified devices."""
        return list(self._iot_devices.values())

    def get_device_baseline(self, mac: str) -> dict[str, Any] | None:
        """Return the learned baseline for a device, or None."""
        return self._baselines.get(mac.strip().upper())

    def get_anomalies(
        self, from_ts: str, to_ts: str
    ) -> list[dict[str, Any]]:
        """Check all IoT devices for anomalies and return combined list."""
        all_anomalies: list[dict[str, Any]] = []
        for mac in self._iot_devices:
            anomalies = self.check_anomalies(mac)
            all_anomalies.extend(anomalies)
        return all_anomalies
