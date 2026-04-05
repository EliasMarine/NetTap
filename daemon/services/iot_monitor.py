"""
NetTap IoT Monitor Service

Classifies devices as IoT based on OUI/manufacturer matching,
builds behavioral baselines from historical data, and detects
anomalies by comparing current behavior to learned patterns.

Also provides fleet-level health summaries via get_fleet_summary(),
which aggregates per-device trust scores (from IoTTrustScorer) into
an overall fleet health score, sub-scores, and stat card values for
the IoT dashboard hero section.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from services.excluded_ips import build_excluded_ips_filter
from services.iot_trust_scorer import IoTTrustScorer

logger = logging.getLogger("nettap.services.iot_monitor")

NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

# Path to tracker domains list (suffix-matched against DNS queries)
_TRACKER_DOMAINS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "tracker_domains.txt"
)

# Path to protocol profiles JSON (expected ports per device category)
_PROTOCOL_PROFILES_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "protocol_profiles.json"
)

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
        # Trust scorer instance
        self._scorer = IoTTrustScorer()
        # Load tracker domains (suffix set for fast lookup)
        self._tracker_domains: set[str] = self._load_tracker_domains()
        # Load protocol profiles (expected ports per category)
        self._protocol_profiles: dict[str, Any] = self._load_protocol_profiles()

    # -----------------------------------------------------------------
    # Data loading helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _load_tracker_domains() -> set[str]:
        """Load tracker domains from the data file.

        Returns a set of lowercase domain suffixes.
        """
        domains: set[str] = set()
        try:
            with open(_TRACKER_DOMAINS_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    domains.add(line.lower())
        except FileNotFoundError:
            logger.warning("Tracker domains file not found: %s", _TRACKER_DOMAINS_FILE)
        except OSError as exc:
            logger.warning("Failed to load tracker domains: %s", exc)
        logger.info("Loaded %d tracker domains", len(domains))
        return domains

    @staticmethod
    def _load_protocol_profiles() -> dict[str, Any]:
        """Load protocol profiles from the JSON data file.

        Returns the 'profiles' dict mapping category -> profile.
        """
        try:
            with open(_PROTOCOL_PROFILES_FILE, "r") as f:
                data = json.load(f)
                return data.get("profiles", {})
        except FileNotFoundError:
            logger.warning("Protocol profiles file not found: %s", _PROTOCOL_PROFILES_FILE)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load protocol profiles: %s", exc)
        return {}

    def _is_tracker_domain(self, domain: str) -> bool:
        """Check if a domain suffix-matches any tracker domain."""
        domain = domain.lower().rstrip(".")
        for tracker in self._tracker_domains:
            if domain == tracker or domain.endswith("." + tracker):
                return True
        return False

    def _get_expected_ports(self) -> set[int]:
        """Get the union of all expected ports from the default profile.

        For fleet summary we use the 'default' profile since we don't
        yet classify device categories.
        """
        default = self._protocol_profiles.get("default", {})
        return set(default.get("expected_ports", [80, 443, 53, 123, 5353, 1900]))

    # -----------------------------------------------------------------
    # Fleet Summary
    # -----------------------------------------------------------------

    def get_fleet_summary(
        self,
        from_ts: str,
        to_ts: str,
        excluded_ips: list[str] | None = None,
    ) -> dict[str, Any]:
        """Compute the fleet-level IoT health summary.

        Queries OpenSearch for per-device connection stats and DNS tracker
        data, scores each device via IoTTrustScorer, then aggregates into
        a fleet-level result that powers the IoT dashboard hero section.

        Args:
            from_ts: ISO timestamp for the start of the query window.
            to_ts:   ISO timestamp for the end of the query window.
            excluded_ips: IPs to filter out of queries.

        Returns:
            Dict with health_score, sub-scores, stat cards, and per-device details.
        """
        devices = self._iot_devices
        if not devices:
            return self._empty_fleet_summary()

        excluded = build_excluded_ips_filter(excluded_ips or [])
        expected_ports = self._get_expected_ports()

        # ----- Batch query: per-device connection stats -----
        conn_stats = self._query_conn_stats_batch(
            list(devices.keys()), from_ts, to_ts, excluded,
        )

        # ----- Batch query: DNS tracker stats -----
        dns_stats = self._query_dns_tracker_batch(
            list(devices.keys()), from_ts, to_ts, excluded,
        )

        # ----- Score each device -----
        device_results: list[dict[str, Any]] = []
        device_scores: list[int] = []
        total_anomaly_count = 0
        privacy_concern_count = 0
        unencrypted_count = 0

        for mac, dev_info in devices.items():
            cs = conn_stats.get(mac, {})
            ds = dns_stats.get(mac, {})
            baseline = self._baselines.get(mac)

            # Build the stats dict expected by IoTTrustScorer.score_device()
            stats = self._build_device_stats(
                mac, cs, ds, baseline, expected_ports,
            )

            score_result = self._scorer.score_device(stats)
            score = score_result["score"]
            device_scores.append(score)

            # Count anomalies from check_anomalies (uses cached baseline)
            device_anomalies = self.check_anomalies(mac, excluded_ips=excluded_ips)
            anomaly_count = len(device_anomalies)
            total_anomaly_count += anomaly_count

            # Privacy concern: tracker_domain_count > 5
            tracker_count = stats.get("tracker_domain_count", 0)
            if tracker_count > 5:
                privacy_concern_count += 1

            # Unencrypted: encryption_ratio < 0.5
            encryption_ratio = stats.get("encryption_ratio", 1.0)
            encryption_pct = int(round(encryption_ratio * 100))
            if encryption_ratio < 0.5:
                unencrypted_count += 1

            device_results.append({
                "mac": mac,
                "name": dev_info.get("hostname") or dev_info.get("manufacturer", "Unknown"),
                "manufacturer": dev_info.get("manufacturer", "Unknown"),
                "ip": dev_info.get("ip", ""),
                "score": score,
                "grade": score_result["grade"],
                "privacy_score": score_result["privacy_score"],
                "security_score": score_result["security_score"],
                "behavior_score": score_result["behavior_score"],
                "anomaly_count": anomaly_count,
                "encryption_pct": encryption_pct,
                "tracker_count": tracker_count,
                "last_seen": dev_info.get("classified_at", ""),
            })

        # ----- Fleet-level aggregation -----
        fleet_score = self._scorer.compute_fleet_score(device_scores)
        fleet_grade = self._scorer.score_to_grade(fleet_score)

        # Average sub-scores across devices
        avg_privacy = self._avg_field(device_results, "privacy_score")
        avg_security = self._avg_field(device_results, "security_score")
        avg_behavior = self._avg_field(device_results, "behavior_score")

        # Build subtitle
        subtitle = self._build_subtitle(
            fleet_score, len(devices), total_anomaly_count, privacy_concern_count,
        )

        # Sort devices by score ascending (worst first) for attention priority
        device_results.sort(key=lambda d: d["score"])

        return {
            "health_score": fleet_score,
            "health_grade": fleet_grade,
            "privacy_score": avg_privacy,
            "security_score": avg_security,
            "behavior_score": avg_behavior,
            "device_count": len(devices),
            "anomaly_count": total_anomaly_count,
            "privacy_concerns": privacy_concern_count,
            "unencrypted_count": unencrypted_count,
            "subtitle": subtitle,
            "devices": device_results,
        }

    def _empty_fleet_summary(self) -> dict[str, Any]:
        """Return a fleet summary with no devices."""
        return {
            "health_score": 100,
            "health_grade": "A",
            "privacy_score": 100,
            "security_score": 100,
            "behavior_score": 100,
            "device_count": 0,
            "anomaly_count": 0,
            "privacy_concerns": 0,
            "unencrypted_count": 0,
            "subtitle": "No IoT devices detected yet.",
            "devices": [],
        }

    @staticmethod
    def _avg_field(devices: list[dict], field: str) -> int:
        """Compute integer average of a field across device dicts."""
        if not devices:
            return 100
        total = sum(d.get(field, 0) for d in devices)
        return int(round(total / len(devices)))

    @staticmethod
    def _build_subtitle(
        score: int, device_count: int, anomaly_count: int, privacy_concerns: int,
    ) -> str:
        """Generate a human-readable fleet health subtitle."""
        if device_count == 0:
            return "No IoT devices detected yet."

        if score >= 90:
            prefix = "Your smart home is healthy."
        elif score >= 75:
            prefix = "Your smart home is mostly healthy."
        elif score >= 60:
            prefix = "Your smart home needs some attention."
        elif score >= 40:
            prefix = "Your smart home has significant concerns."
        else:
            prefix = "Your smart home needs immediate attention."

        parts = []
        if anomaly_count > 0:
            parts.append(
                f"{anomaly_count} anomal{'y' if anomaly_count == 1 else 'ies'} detected"
            )
        if privacy_concerns > 0:
            parts.append(
                f"{privacy_concerns} device{'s' if privacy_concerns != 1 else ''} "
                f"{'have' if privacy_concerns != 1 else 'has'} privacy concerns"
            )

        if parts:
            return f"{prefix} {'. '.join(parts)}."
        return prefix

    # -----------------------------------------------------------------
    # OpenSearch batch query helpers
    # -----------------------------------------------------------------

    def _query_conn_stats_batch(
        self,
        macs: list[str],
        from_ts: str,
        to_ts: str,
        excluded: list[dict],
    ) -> dict[str, dict[str, Any]]:
        """Query connection stats for all devices in one OpenSearch call.

        Returns dict keyed by MAC with:
            total_connections, encrypted_connections, total_bytes,
            dest_ports (set), alert_count, third_party_orgs (int)
        """
        if not macs:
            return {}

        mac_terms = []
        for mac in macs:
            mac_terms.extend([mac, mac.lower()])

        bool_clause: dict = {
            "filter": [
                _time_range_filter(from_ts, to_ts),
                {"term": {"event.provider": "zeek"}},
                {"term": {"event.dataset": "conn"}},
                {"terms": {"source.mac.keyword": mac_terms}},
            ]
        }
        if excluded:
            bool_clause["must_not"] = excluded

        query = {
            "size": 0,
            "query": {"bool": bool_clause},
            "aggs": {
                "by_mac": {
                    "terms": {"field": "source.mac.keyword", "size": len(macs) * 2},
                    "aggs": {
                        "total_bytes": {
                            "sum": {"field": "client.bytes", "missing": 0}
                        },
                        "dest_ports": {
                            "terms": {"field": "destination.port", "size": 100}
                        },
                        "encrypted": {
                            "filter": {
                                "terms": {"destination.port": [443, 8443, 8883]}
                            }
                        },
                        "third_party_orgs": {
                            "cardinality": {
                                "field": "destination.as.full.keyword",
                            }
                        },
                    },
                }
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except Exception as exc:
            logger.error("Fleet conn stats query failed: %s", exc)
            return {}

        out: dict[str, dict[str, Any]] = {}
        buckets = (
            result.get("aggregations", {})
            .get("by_mac", {})
            .get("buckets", [])
        )

        for bucket in buckets:
            raw_mac = bucket["key"].upper()
            total_conns = bucket.get("doc_count", 0)
            encrypted_conns = bucket.get("encrypted", {}).get("doc_count", 0)
            total_bytes = bucket.get("total_bytes", {}).get("value", 0) or 0
            ports = {
                b["key"]
                for b in bucket.get("dest_ports", {}).get("buckets", [])
            }
            third_party = bucket.get("third_party_orgs", {}).get("value", 0) or 0

            out[raw_mac] = {
                "total_connections": total_conns,
                "encrypted_connections": encrypted_conns,
                "total_bytes": total_bytes,
                "dest_ports": ports,
                "third_party_orgs": int(third_party),
            }

        # Now query Suricata alert counts per device
        alert_stats = self._query_alert_counts(macs, from_ts, to_ts, excluded)
        for mac, alert_count in alert_stats.items():
            if mac in out:
                out[mac]["alert_count"] = alert_count
            else:
                out[mac] = {"alert_count": alert_count}

        return out

    def _query_alert_counts(
        self,
        macs: list[str],
        from_ts: str,
        to_ts: str,
        excluded: list[dict],
    ) -> dict[str, int]:
        """Query Suricata alert counts per device MAC."""
        if not macs:
            return {}

        mac_terms = []
        for mac in macs:
            mac_terms.extend([mac, mac.lower()])

        bool_clause: dict = {
            "filter": [
                _time_range_filter(from_ts, to_ts),
                {"term": {"event.provider": "suricata"}},
                {"term": {"event.dataset": "alert"}},
                {"terms": {"source.mac.keyword": mac_terms}},
            ]
        }
        if excluded:
            bool_clause["must_not"] = excluded

        query = {
            "size": 0,
            "query": {"bool": bool_clause},
            "aggs": {
                "by_mac": {
                    "terms": {"field": "source.mac.keyword", "size": len(macs) * 2},
                }
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except Exception as exc:
            logger.error("Fleet alert count query failed: %s", exc)
            return {}

        out: dict[str, int] = {}
        for bucket in (
            result.get("aggregations", {})
            .get("by_mac", {})
            .get("buckets", [])
        ):
            out[bucket["key"].upper()] = bucket.get("doc_count", 0)
        return out

    def _query_dns_tracker_batch(
        self,
        macs: list[str],
        from_ts: str,
        to_ts: str,
        excluded: list[dict],
    ) -> dict[str, dict[str, Any]]:
        """Query DNS logs to count tracker domain hits per device.

        Returns dict keyed by MAC with:
            tracker_domain_count (int), total_dns_queries (int)
        """
        if not macs:
            return {}

        mac_terms = []
        for mac in macs:
            mac_terms.extend([mac, mac.lower()])

        bool_clause: dict = {
            "filter": [
                _time_range_filter(from_ts, to_ts),
                {"term": {"event.provider": "zeek"}},
                {"term": {"event.dataset": "dns"}},
                {"terms": {"source.mac.keyword": mac_terms}},
            ]
        }
        if excluded:
            bool_clause["must_not"] = excluded

        query = {
            "size": 0,
            "query": {"bool": bool_clause},
            "aggs": {
                "by_mac": {
                    "terms": {"field": "source.mac.keyword", "size": len(macs) * 2},
                    "aggs": {
                        "queried_domains": {
                            "terms": {
                                "field": "dns.question.name.keyword",
                                "size": 500,
                            }
                        },
                    },
                }
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except Exception as exc:
            logger.error("Fleet DNS tracker query failed: %s", exc)
            return {}

        out: dict[str, dict[str, Any]] = {}
        for bucket in (
            result.get("aggregations", {})
            .get("by_mac", {})
            .get("buckets", [])
        ):
            raw_mac = bucket["key"].upper()
            domains = bucket.get("queried_domains", {}).get("buckets", [])
            tracker_count = 0
            for d_bucket in domains:
                domain = d_bucket.get("key", "")
                if self._is_tracker_domain(domain):
                    tracker_count += 1

            out[raw_mac] = {
                "tracker_domain_count": tracker_count,
                "total_dns_queries": bucket.get("doc_count", 0),
            }

        return out

    def _build_device_stats(
        self,
        mac: str,
        conn_stats: dict[str, Any],
        dns_stats: dict[str, Any],
        baseline: dict[str, Any] | None,
        expected_ports: set[int],
    ) -> dict[str, Any]:
        """Build the stats dict expected by IoTTrustScorer.score_device().

        Combines connection stats, DNS tracker stats, and baseline data
        into a single dict with all required keys.
        """
        total_conns = conn_stats.get("total_connections", 0)
        encrypted_conns = conn_stats.get("encrypted_connections", 0)
        total_bytes = conn_stats.get("total_bytes", 0)
        dest_ports = conn_stats.get("dest_ports", set())
        third_party_orgs = conn_stats.get("third_party_orgs", 0)
        alert_count = conn_stats.get("alert_count", 0)

        tracker_domain_count = dns_stats.get("tracker_domain_count", 0)

        # Encryption ratio
        if total_conns > 0:
            encryption_ratio = encrypted_conns / total_conns
        else:
            encryption_ratio = 1.0  # No data = assume OK

        # Protocol violations: ports not in expected set
        protocol_violations = 0
        for port in dest_ports:
            if port not in expected_ports:
                protocol_violations += 1

        # Baseline-derived stats
        if baseline:
            known_dests = set(baseline.get("known_destinations", []))
            all_dests = set()  # We don't have current destinations here individually,
            # but dest_ports gives us a proxy. Use known_destinations count ratio.
            known_count = len(known_dests)
            # baseline_adherence: fraction of baseline destinations vs total seen
            # Simplified: if baseline exists, use ratio of known ports to all ports
            known_ports = set(baseline.get("known_ports", []))
            total_port_count = len(dest_ports)
            known_port_hits = len(dest_ports & known_ports) if dest_ports else 0
            if total_port_count > 0:
                baseline_adherence = known_port_hits / total_port_count
            elif known_count > 0:
                baseline_adherence = 1.0
            else:
                baseline_adherence = 0.5

            new_destinations = max(0, total_port_count - known_port_hits)

            # Volume spike: compare current bytes to baseline daily avg
            daily_avg = baseline.get("daily_avg_bytes", 0)
            volume_spike = total_bytes > daily_avg * 3 if daily_avg > 0 else False

            # Unusual timing: check if current hour is outside baseline hours
            active_hours = set(baseline.get("active_hours", []))
            current_hour = datetime.now(timezone.utc).hour
            unusual_timing = (
                bool(active_hours) and current_hour not in active_hours
            )
        else:
            # No baseline: use conservative defaults
            baseline_adherence = 0.5
            new_destinations = 0
            volume_spike = False
            unusual_timing = False

        return {
            "tracker_domain_count": tracker_domain_count,
            "telemetry_bytes": 0,  # Would need IP-to-tracker resolution; simplified for now
            "third_party_orgs": third_party_orgs,
            "encryption_ratio": min(1.0, max(0.0, encryption_ratio)),
            "protocol_violations": protocol_violations,
            "alert_count": alert_count,
            "firmware_age_signal": "unknown",
            "baseline_adherence": min(1.0, max(0.0, baseline_adherence)),
            "new_destinations": new_destinations,
            "volume_spike": volume_spike,
            "unusual_timing": unusual_timing,
        }

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
        self, device_mac: str, days: int = 14,
        excluded_ips: list[str] | None = None,
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

        excluded = build_excluded_ips_filter(excluded_ips or [])
        bool_clause: dict = {
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
        if excluded:
            bool_clause["must_not"] = excluded

        # Query for device traffic patterns
        query = {
            "size": 0,
            "query": {
                "bool": bool_clause
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
        self, device_mac: str,
        excluded_ips: list[str] | None = None,
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

        excluded = build_excluded_ips_filter(excluded_ips or [])
        bool_clause: dict = {
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
        if excluded:
            bool_clause["must_not"] = excluded

        query = {
            "size": 0,
            "query": {
                "bool": bool_clause
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
        self, from_ts: str, to_ts: str,
        excluded_ips: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Check all IoT devices for anomalies and return combined list."""
        all_anomalies: list[dict[str, Any]] = []
        for mac in self._iot_devices:
            anomalies = self.check_anomalies(mac, excluded_ips=excluded_ips)
            all_anomalies.extend(anomalies)
        return all_anomalies
