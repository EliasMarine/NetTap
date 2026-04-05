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
                            "sum": {"field": "source.bytes", "missing": 0}
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
                {"exists": {"field": "suricata.alert.severity"}},
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
                {"term": {"network.protocol": "dns"}},
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
                                "field": "dns.host.keyword",
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
                    "terms": {"field": "network.protocol.keyword", "size": 10}
                },
                "hourly_activity": {
                    "date_histogram": {
                        "field": "@timestamp",
                        "calendar_interval": "hour",
                    }
                },
                "total_bytes": {
                    "sum": {"field": "source.bytes", "missing": 0}
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
                    "terms": {"field": "network.protocol.keyword", "size": 10}
                },
                "total_bytes": {
                    "sum": {"field": "source.bytes", "missing": 0}
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

    # -----------------------------------------------------------------
    # Privacy Report
    # -----------------------------------------------------------------

    def get_privacy_report(
        self,
        from_ts: str,
        to_ts: str,
        excluded_ips: list[str] | None = None,
    ) -> dict[str, Any]:
        """Compute per-device privacy report with tracker domains,
        encryption ratio, and phone-home frequency.

        Returns dict with 'devices' list.
        """
        devices = self._iot_devices
        if not devices:
            return {"devices": []}

        excluded = build_excluded_ips_filter(excluded_ips or [])
        macs = list(devices.keys())

        # Batch query: connection stats (encryption ratio, bytes, etc.)
        conn_stats = self._query_conn_stats_batch(macs, from_ts, to_ts, excluded)

        # Batch query: DNS tracker stats with per-domain detail
        dns_detail = self._query_dns_tracker_detail_batch(macs, from_ts, to_ts, excluded)

        # Compute time window in hours for phone-home rate
        try:
            from_dt = datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
            to_dt = datetime.fromisoformat(to_ts.replace("Z", "+00:00"))
            window_hours = max(1.0, (to_dt - from_dt).total_seconds() / 3600)
        except (ValueError, TypeError):
            window_hours = 24.0

        device_results: list[dict[str, Any]] = []
        for mac, dev_info in devices.items():
            cs = conn_stats.get(mac, {})
            dd = dns_detail.get(mac, {})

            total_conns = cs.get("total_connections", 0)
            encrypted_conns = cs.get("encrypted_connections", 0)
            total_bytes = cs.get("total_bytes", 0)
            third_party_orgs = cs.get("third_party_orgs", 0)

            encryption_ratio = (
                encrypted_conns / total_conns if total_conns > 0 else 1.0
            )

            tracker_domains_list = dd.get("tracker_domains", [])
            tracker_count = len(tracker_domains_list)

            # Estimate telemetry bytes as a fraction of total bytes
            # proportional to tracker queries vs total queries
            total_queries = dd.get("total_dns_queries", 0)
            tracker_query_sum = sum(t["query_count"] for t in tracker_domains_list)
            if total_queries > 0 and total_bytes > 0:
                telemetry_bytes = int(total_bytes * tracker_query_sum / total_queries)
            else:
                telemetry_bytes = 0

            phone_home_per_hour = round(total_conns / window_hours, 2) if window_hours > 0 else 0

            # Compute privacy score (0-100) based on metrics
            privacy_score = self._compute_privacy_score(
                tracker_count, encryption_ratio, third_party_orgs, telemetry_bytes,
            )
            privacy_grade = self._scorer.score_to_grade(privacy_score)

            device_results.append({
                "mac": mac,
                "name": dev_info.get("hostname") or dev_info.get("manufacturer", "Unknown"),
                "privacy_grade": privacy_grade,
                "privacy_score": privacy_score,
                "tracker_domains": tracker_domains_list,
                "tracker_count": tracker_count,
                "telemetry_bytes": telemetry_bytes,
                "third_party_orgs": third_party_orgs,
                "encryption_ratio": round(min(1.0, max(0.0, encryption_ratio)), 4),
                "phone_home_per_hour": phone_home_per_hour,
            })

        # Sort worst privacy first
        device_results.sort(key=lambda d: d["privacy_score"])
        return {"devices": device_results}

    @staticmethod
    def _compute_privacy_score(
        tracker_count: int,
        encryption_ratio: float,
        third_party_orgs: int,
        telemetry_bytes: int,
    ) -> int:
        """Compute a 0-100 privacy score from privacy metrics."""
        # Tracker penalty: -5 per tracker domain (max -50)
        tracker_penalty = min(50, tracker_count * 5)
        # Encryption bonus: up to 30 points for full encryption
        encryption_bonus = int(encryption_ratio * 30)
        # Third-party penalty: -3 per org above 1 (max -20)
        org_penalty = min(20, max(0, third_party_orgs - 1) * 3)
        # Base score
        score = 100 - tracker_penalty + encryption_bonus - 30 - org_penalty
        return max(0, min(100, score))

    def _query_dns_tracker_detail_batch(
        self,
        macs: list[str],
        from_ts: str,
        to_ts: str,
        excluded: list[dict],
    ) -> dict[str, dict[str, Any]]:
        """Query DNS logs and return per-device tracker domain details.

        Returns dict keyed by MAC with:
            tracker_domains: list of {domain, query_count}
            total_dns_queries: int
        """
        if not macs:
            return {}

        mac_terms = []
        for mac in macs:
            mac_terms.extend([mac, mac.lower()])

        bool_clause: dict = {
            "filter": [
                _time_range_filter(from_ts, to_ts),
                {"term": {"network.protocol": "dns"}},
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
                                "field": "dns.host.keyword",
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
            logger.error("DNS tracker detail query failed: %s", exc)
            return {}

        out: dict[str, dict[str, Any]] = {}
        for bucket in (
            result.get("aggregations", {})
            .get("by_mac", {})
            .get("buckets", [])
        ):
            raw_mac = bucket["key"].upper()
            domains = bucket.get("queried_domains", {}).get("buckets", [])
            tracker_list: list[dict[str, Any]] = []
            for d_bucket in domains:
                domain = d_bucket.get("key", "")
                if self._is_tracker_domain(domain):
                    tracker_list.append({
                        "domain": domain,
                        "query_count": d_bucket.get("doc_count", 0),
                    })

            out[raw_mac] = {
                "tracker_domains": tracker_list,
                "total_dns_queries": bucket.get("doc_count", 0),
            }

        return out

    # -----------------------------------------------------------------
    # Communication Map
    # -----------------------------------------------------------------

    def get_communication_map(
        self,
        mac: str,
        from_ts: str,
        to_ts: str,
        excluded_ips: list[str] | None = None,
    ) -> dict[str, Any]:
        """Get all communication destinations for a single device.

        Returns dict with 'mac' and 'destinations' list.
        """
        mac = mac.strip().upper()
        excluded = build_excluded_ips_filter(excluded_ips or [])
        baseline = self._baselines.get(mac)
        baseline_dests = set(baseline.get("known_destinations", [])) if baseline else set()

        # Query conn logs for this device, aggregate by destination IP
        mac_filter = {
            "bool": {
                "should": [
                    {"term": {"source.mac.keyword": mac}},
                    {"term": {"source.mac.keyword": mac.lower()}},
                ],
                "minimum_should_match": 1,
            }
        }

        bool_clause: dict = {
            "filter": [
                _time_range_filter(from_ts, to_ts),
                mac_filter,
            ]
        }
        if excluded:
            bool_clause["must_not"] = excluded

        query = {
            "size": 0,
            "query": {"bool": bool_clause},
            "aggs": {
                "by_dest": {
                    "terms": {"field": "destination.ip.keyword", "size": 200},
                    "aggs": {
                        "ports": {
                            "terms": {"field": "destination.port", "size": 50}
                        },
                        "bytes_sent": {
                            "sum": {"field": "source.bytes", "missing": 0}
                        },
                        "bytes_received": {
                            "sum": {"field": "destination.bytes", "missing": 0}
                        },
                        "country": {
                            "terms": {
                                "field": "destination.geo.country_iso_code.keyword",
                                "size": 1,
                            }
                        },
                        "first_seen": {
                            "min": {"field": "@timestamp"}
                        },
                        "last_seen": {
                            "max": {"field": "@timestamp"}
                        },
                    },
                }
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except Exception as exc:
            logger.error("Communication map query failed for %s: %s", mac, exc)
            return {"mac": mac, "destinations": []}

        # Resolve hostnames via DNS logs
        dest_ips = []
        dest_buckets = (
            result.get("aggregations", {})
            .get("by_dest", {})
            .get("buckets", [])
        )
        for b in dest_buckets:
            dest_ips.append(b["key"])

        hostname_map = self._resolve_hostnames(dest_ips, from_ts, to_ts, excluded)

        destinations: list[dict[str, Any]] = []
        for b in dest_buckets:
            ip = b["key"]
            ports = [pb["key"] for pb in b.get("ports", {}).get("buckets", [])]
            country_buckets = b.get("country", {}).get("buckets", [])
            country = country_buckets[0]["key"] if country_buckets else None

            first_seen_ms = b.get("first_seen", {}).get("value")
            last_seen_ms = b.get("last_seen", {}).get("value")
            first_seen = (
                b.get("first_seen", {}).get("value_as_string")
                if first_seen_ms is not None else None
            )
            last_seen = (
                b.get("last_seen", {}).get("value_as_string")
                if last_seen_ms is not None else None
            )

            destinations.append({
                "ip": ip,
                "hostname": hostname_map.get(ip),
                "country": country,
                "ports": ports,
                "bytes_sent": int(b.get("bytes_sent", {}).get("value", 0) or 0),
                "bytes_received": int(b.get("bytes_received", {}).get("value", 0) or 0),
                "connection_count": b.get("doc_count", 0),
                "first_seen": first_seen,
                "last_seen": last_seen,
                "in_baseline": ip in baseline_dests,
            })

        return {"mac": mac, "destinations": destinations}

    def _resolve_hostnames(
        self,
        ips: list[str],
        from_ts: str,
        to_ts: str,
        excluded: list[dict],
    ) -> dict[str, str]:
        """Resolve IPs to hostnames by querying DNS answer records.

        Looks for DNS logs where zeek.dns.answers contains any of the IPs.
        Returns a dict mapping IP -> hostname (domain queried).
        """
        if not ips:
            return {}

        bool_clause: dict = {
            "filter": [
                _time_range_filter(from_ts, to_ts),
                {"term": {"network.protocol": "dns"}},
                {"terms": {"dns.ip": ips}},
            ]
        }
        if excluded:
            bool_clause["must_not"] = excluded

        query = {
            "size": 0,
            "query": {"bool": bool_clause},
            "aggs": {
                "by_answer_ip": {
                    "terms": {"field": "dns.ip.keyword", "size": len(ips)},
                    "aggs": {
                        "domain": {
                            "terms": {
                                "field": "dns.host.keyword",
                                "size": 1,
                            }
                        },
                    },
                }
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except Exception as exc:
            logger.error("Hostname resolution query failed: %s", exc)
            return {}

        out: dict[str, str] = {}
        for bucket in (
            result.get("aggregations", {})
            .get("by_answer_ip", {})
            .get("buckets", [])
        ):
            ip = bucket["key"]
            domain_buckets = bucket.get("domain", {}).get("buckets", [])
            if domain_buckets:
                out[ip] = domain_buckets[0]["key"]

        return out

    # -----------------------------------------------------------------
    # Activity Timeline
    # -----------------------------------------------------------------

    def get_activity_timeline(
        self,
        mac: str,
        from_ts: str,
        to_ts: str,
        excluded_ips: list[str] | None = None,
    ) -> dict[str, Any]:
        """Get hourly activity timeline for a single device.

        Returns dict with 'mac', 'interval', 'buckets', 'baseline_hours',
        and 'baseline_avg_hourly_bytes'.
        """
        mac = mac.strip().upper()
        excluded = build_excluded_ips_filter(excluded_ips or [])
        baseline = self._baselines.get(mac)

        mac_filter = {
            "bool": {
                "should": [
                    {"term": {"source.mac.keyword": mac}},
                    {"term": {"source.mac.keyword": mac.lower()}},
                ],
                "minimum_should_match": 1,
            }
        }

        bool_clause: dict = {
            "filter": [
                _time_range_filter(from_ts, to_ts),
                mac_filter,
            ]
        }
        if excluded:
            bool_clause["must_not"] = excluded

        query = {
            "size": 0,
            "query": {"bool": bool_clause},
            "aggs": {
                "hourly": {
                    "date_histogram": {
                        "field": "@timestamp",
                        "fixed_interval": "1h",
                    },
                    "aggs": {
                        "bytes": {
                            "sum": {"field": "source.bytes", "missing": 0}
                        },
                        "destinations": {
                            "cardinality": {"field": "destination.ip.keyword"}
                        },
                    },
                }
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except Exception as exc:
            logger.error("Activity timeline query failed for %s: %s", mac, exc)
            return {
                "mac": mac,
                "interval": "1h",
                "buckets": [],
                "baseline_hours": [],
                "baseline_avg_hourly_bytes": 0,
            }

        hourly_buckets = (
            result.get("aggregations", {})
            .get("hourly", {})
            .get("buckets", [])
        )

        buckets: list[dict[str, Any]] = []
        for hb in hourly_buckets:
            buckets.append({
                "time": hb.get("key_as_string", ""),
                "connections": hb.get("doc_count", 0),
                "bytes": int(hb.get("bytes", {}).get("value", 0) or 0),
                "destinations": int(hb.get("destinations", {}).get("value", 0) or 0),
            })

        # Baseline overlay
        baseline_hours: list[int] = []
        baseline_avg_hourly_bytes: int = 0
        if baseline:
            baseline_hours = baseline.get("active_hours", [])
            daily_avg = baseline.get("daily_avg_bytes", 0)
            baseline_avg_hourly_bytes = int(daily_avg / 24) if daily_avg > 0 else 0

        return {
            "mac": mac,
            "interval": "1h",
            "buckets": buckets,
            "baseline_hours": baseline_hours,
            "baseline_avg_hourly_bytes": baseline_avg_hourly_bytes,
        }

    # -----------------------------------------------------------------
    # Protocol Audit
    # -----------------------------------------------------------------

    # Category mapping heuristics: manufacturer/hostname keyword -> category
    _CATEGORY_KEYWORDS: list[tuple[list[str], str]] = [
        (["ring", "arlo", "blink", "wyze cam"], "doorbell"),
        (["nest", "ecobee", "honeywell"], "thermostat"),
        (["roku", "fire tv", "chromecast", "apple tv"], "smart_tv"),
        (["echo", "alexa", "google home", "sonos"], "smart_speaker"),
        (["hue", "lifx", "wiz"], "light"),
        (["smartthings", "hubitat", "wink"], "hub"),
        (["kasa", "wemo", "smart plug", "shelly"], "smart_plug"),
    ]

    def _categorize_device(self, dev_info: dict[str, Any]) -> str:
        """Categorize a device based on manufacturer/hostname keywords."""
        manufacturer = (dev_info.get("manufacturer") or "").lower()
        hostname = (dev_info.get("hostname") or "").lower()
        combined = manufacturer + " " + hostname

        for keywords, category in self._CATEGORY_KEYWORDS:
            for kw in keywords:
                if kw in combined:
                    return category
        return "default"

    def get_protocol_audit(
        self,
        from_ts: str,
        to_ts: str,
        excluded_ips: list[str] | None = None,
    ) -> dict[str, Any]:
        """Audit IoT devices for protocol compliance violations.

        Checks each device's traffic against expected protocol profiles
        based on device category. Flags unexpected ports, unencrypted
        external connections, and hardcoded DNS.

        Returns dict with 'devices' list.
        """
        devices = self._iot_devices
        if not devices:
            return {"devices": []}

        excluded = build_excluded_ips_filter(excluded_ips or [])
        macs = list(devices.keys())

        # Batch query connection stats (includes dest_ports)
        conn_stats = self._query_conn_stats_batch(macs, from_ts, to_ts, excluded)

        # Query per-device port usage with connection counts
        port_detail = self._query_port_detail_batch(macs, from_ts, to_ts, excluded)

        # Query for hardcoded DNS (destination port 53 to non-standard DNS servers)
        hardcoded_dns = self._query_hardcoded_dns_batch(macs, from_ts, to_ts, excluded)

        device_results: list[dict[str, Any]] = []
        for mac, dev_info in devices.items():
            category = self._categorize_device(dev_info)
            profile = self._protocol_profiles.get(category, self._protocol_profiles.get("default", {}))
            expected_ports = set(profile.get("expected_ports", [80, 443, 53, 123, 5353, 1900]))
            category_label = profile.get("label", "Unknown")

            cs = conn_stats.get(mac, {})
            pd = port_detail.get(mac, {})
            hd = hardcoded_dns.get(mac, [])

            findings: list[dict[str, Any]] = []

            # Check for unexpected ports
            actual_ports = pd.keys() if pd else set()
            for port in actual_ports:
                if port not in expected_ports:
                    count = pd[port]
                    severity = "high" if port in (22, 23, 445, 139, 3389, 5900) else "medium"
                    findings.append({
                        "type": "unexpected_port",
                        "severity": severity,
                        "port": port,
                        "connection_count": count,
                        "description": (
                            f"Uses port {port} which is not expected for "
                            f"a {category_label.lower()}"
                        ),
                    })

            # Check for unencrypted external connections
            total_conns = cs.get("total_connections", 0)
            encrypted_conns = cs.get("encrypted_connections", 0)
            unencrypted = total_conns - encrypted_conns
            if total_conns > 0 and unencrypted > 0:
                ratio = encrypted_conns / total_conns
                if ratio < 0.9:
                    findings.append({
                        "type": "unencrypted_traffic",
                        "severity": "high" if ratio < 0.5 else "medium",
                        "port": 0,
                        "connection_count": unencrypted,
                        "description": (
                            f"{int((1 - ratio) * 100)}% of connections are unencrypted "
                            f"({unencrypted} of {total_conns})"
                        ),
                    })

            # Check for hardcoded DNS
            for dns_entry in hd:
                findings.append({
                    "type": "hardcoded_dns",
                    "severity": "medium",
                    "port": 53,
                    "connection_count": dns_entry.get("count", 0),
                    "description": (
                        f"Sends DNS queries directly to {dns_entry['ip']} "
                        f"instead of using network DNS"
                    ),
                })

            device_results.append({
                "mac": mac,
                "name": dev_info.get("hostname") or dev_info.get("manufacturer", "Unknown"),
                "category": category,
                "findings": findings,
                "violation_count": len(findings),
                "compliant": len(findings) == 0,
            })

        # Sort by violation count descending (worst first)
        device_results.sort(key=lambda d: d["violation_count"], reverse=True)
        return {"devices": device_results}

    def _query_port_detail_batch(
        self,
        macs: list[str],
        from_ts: str,
        to_ts: str,
        excluded: list[dict],
    ) -> dict[str, dict[int, int]]:
        """Query destination port usage per device with connection counts.

        Returns dict keyed by MAC, value is dict of port -> connection_count.
        """
        if not macs:
            return {}

        mac_terms = []
        for mac in macs:
            mac_terms.extend([mac, mac.lower()])

        bool_clause: dict = {
            "filter": [
                _time_range_filter(from_ts, to_ts),
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
                        "ports": {
                            "terms": {"field": "destination.port", "size": 200}
                        },
                    },
                }
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except Exception as exc:
            logger.error("Port detail query failed: %s", exc)
            return {}

        out: dict[str, dict[int, int]] = {}
        for bucket in (
            result.get("aggregations", {})
            .get("by_mac", {})
            .get("buckets", [])
        ):
            raw_mac = bucket["key"].upper()
            port_map: dict[int, int] = {}
            for pb in bucket.get("ports", {}).get("buckets", []):
                port_map[pb["key"]] = pb.get("doc_count", 0)
            out[raw_mac] = port_map

        return out

    def _query_hardcoded_dns_batch(
        self,
        macs: list[str],
        from_ts: str,
        to_ts: str,
        excluded: list[dict],
    ) -> dict[str, list[dict[str, Any]]]:
        """Detect hardcoded DNS: IoT devices sending DNS to non-standard servers.

        Looks for connections on port 53 to non-local DNS servers
        (e.g., 8.8.8.8, 1.1.1.1 — known public DNS resolvers).

        Returns dict keyed by MAC with list of {ip, count}.
        """
        if not macs:
            return {}

        # Common hardcoded DNS servers that IoT devices phone home to
        well_known_dns = [
            "8.8.8.8", "8.8.4.4",  # Google DNS
            "1.1.1.1", "1.0.0.1",  # Cloudflare DNS
            "208.67.222.222", "208.67.220.220",  # OpenDNS
            "9.9.9.9",  # Quad9
        ]

        mac_terms = []
        for mac in macs:
            mac_terms.extend([mac, mac.lower()])

        bool_clause: dict = {
            "filter": [
                _time_range_filter(from_ts, to_ts),
                {"terms": {"source.mac.keyword": mac_terms}},
                {"term": {"destination.port": 53}},
                {"terms": {"destination.ip.keyword": well_known_dns}},
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
                        "dns_servers": {
                            "terms": {"field": "destination.ip.keyword", "size": 10}
                        },
                    },
                }
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except Exception as exc:
            logger.error("Hardcoded DNS query failed: %s", exc)
            return {}

        out: dict[str, list[dict[str, Any]]] = {}
        for bucket in (
            result.get("aggregations", {})
            .get("by_mac", {})
            .get("buckets", [])
        ):
            raw_mac = bucket["key"].upper()
            dns_list: list[dict[str, Any]] = []
            for db in bucket.get("dns_servers", {}).get("buckets", []):
                dns_list.append({
                    "ip": db["key"],
                    "count": db.get("doc_count", 0),
                })
            if dns_list:
                out[raw_mac] = dns_list

        return out

    # -----------------------------------------------------------------
    # Network Isolation
    # -----------------------------------------------------------------

    def get_network_isolation(
        self,
        from_ts: str,
        to_ts: str,
        excluded_ips: list[str] | None = None,
    ) -> dict[str, Any]:
        """Analyze IoT-to-internal network segmentation.

        Finds IoT devices communicating with internal (RFC1918) non-IoT
        hosts. Computes a segmentation score.

        Returns dict with 'segmentation_score', 'segmentation_grade',
        'pairs', and 'recommendation'.
        """
        devices = self._iot_devices
        if not devices:
            return {
                "segmentation_score": 100,
                "segmentation_grade": "A",
                "pairs": [],
                "recommendation": "No IoT devices detected yet.",
            }

        excluded = build_excluded_ips_filter(excluded_ips or [])
        macs = list(devices.keys())

        # Build MAC->device info lookup
        iot_macs = set(macs)
        iot_ips = set()
        for dev in devices.values():
            ip = dev.get("ip")
            if ip:
                iot_ips.add(ip)

        # Query conn logs where source is IoT device and destination is RFC1918
        mac_terms = []
        for mac in macs:
            mac_terms.extend([mac, mac.lower()])

        bool_clause: dict = {
            "filter": [
                _time_range_filter(from_ts, to_ts),
                {"terms": {"source.mac.keyword": mac_terms}},
                # Destination is RFC1918 (internal) — use script filter
                {
                    "script": {
                        "script": {
                            "source": """
                                def ip = doc['destination.ip.keyword'].size() > 0 ? doc['destination.ip.keyword'].value : '';
                                if (ip.length() == 0) return false;
                                def parts = ip.splitOnToken('.');
                                if (parts.length != 4) return false;
                                int a = Integer.parseInt(parts[0]);
                                int b = Integer.parseInt(parts[1]);
                                if (a == 10) return true;
                                if (a == 172 && b >= 16 && b <= 31) return true;
                                if (a == 192 && b == 168) return true;
                                return false;
                            """,
                            "lang": "painless",
                        }
                    }
                },
            ]
        }
        if excluded:
            bool_clause["must_not"] = excluded

        query = {
            "size": 0,
            "query": {"bool": bool_clause},
            "aggs": {
                "by_source_mac": {
                    "terms": {"field": "source.mac.keyword", "size": len(macs) * 2},
                    "aggs": {
                        "by_dest_ip": {
                            "terms": {"field": "destination.ip.keyword", "size": 50},
                            "aggs": {
                                "ports": {
                                    "terms": {"field": "destination.port", "size": 20}
                                },
                                "source_ip": {
                                    "terms": {"field": "source.ip.keyword", "size": 1}
                                },
                            },
                        },
                    },
                }
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except Exception as exc:
            logger.error("Network isolation query failed: %s", exc)
            return {
                "segmentation_score": 100,
                "segmentation_grade": "A",
                "pairs": [],
                "recommendation": "Could not analyze network isolation.",
            }

        pairs: list[dict[str, Any]] = []
        for mac_bucket in (
            result.get("aggregations", {})
            .get("by_source_mac", {})
            .get("buckets", [])
        ):
            raw_mac = mac_bucket["key"].upper()
            dev_info = devices.get(raw_mac, {})
            dev_name = dev_info.get("hostname") or dev_info.get("manufacturer", "Unknown")

            for dest_bucket in mac_bucket.get("by_dest_ip", {}).get("buckets", []):
                dest_ip = dest_bucket["key"]

                # Skip if destination is also an IoT device
                if dest_ip in iot_ips:
                    continue

                ports = [pb["key"] for pb in dest_bucket.get("ports", {}).get("buckets", [])]
                conn_count = dest_bucket.get("doc_count", 0)

                # Get source IP
                src_ip_buckets = dest_bucket.get("source_ip", {}).get("buckets", [])
                src_ip = src_ip_buckets[0]["key"] if src_ip_buckets else ""

                # Classify risk based on ports
                risk = self._classify_isolation_risk(ports)

                # Build description
                port_names = self._port_names(ports)
                desc = f"{dev_name} can reach {dest_ip} via {port_names}"

                pairs.append({
                    "iot_device": {
                        "mac": raw_mac,
                        "name": dev_name,
                        "ip": src_ip,
                    },
                    "internal_target": {
                        "ip": dest_ip,
                        "hostname": None,  # Would need reverse DNS
                    },
                    "risk": risk,
                    "connection_count": conn_count,
                    "ports": ports,
                    "description": desc,
                })

        # Compute segmentation score
        score = 100
        critical_count = 0
        high_count = 0
        medium_count = 0
        for pair in pairs:
            r = pair["risk"]
            if r == "critical":
                score -= 25
                critical_count += 1
            elif r == "high":
                score -= 15
                high_count += 1
            elif r == "medium":
                score -= 5
                medium_count += 1

        score = max(0, min(100, score))
        grade = self._scorer.score_to_grade(score)

        # Build recommendation
        iot_reaching_workstations = len(set(
            p["iot_device"]["mac"] for p in pairs if p["risk"] in ("high", "critical")
        ))
        if not pairs:
            recommendation = "Your IoT devices are well-isolated from internal hosts."
        elif iot_reaching_workstations > 0:
            recommendation = (
                f"Consider creating a separate VLAN for your IoT devices -- "
                f"{iot_reaching_workstations} IoT device{'s' if iot_reaching_workstations != 1 else ''} "
                f"can currently reach your workstations."
            )
        else:
            recommendation = (
                f"{len(pairs)} IoT-to-internal connection pair{'s' if len(pairs) != 1 else ''} "
                f"detected. Review for unnecessary access."
            )

        # Sort pairs by risk severity
        risk_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        pairs.sort(key=lambda p: risk_order.get(p["risk"], 99))

        return {
            "segmentation_score": score,
            "segmentation_grade": grade,
            "pairs": pairs,
            "recommendation": recommendation,
        }

    @staticmethod
    def _classify_isolation_risk(ports: list[int]) -> str:
        """Classify the risk level of IoT-to-internal communication."""
        critical_ports = {445, 139, 3389, 5900, 22, 23}  # SMB, RDP, VNC, SSH, Telnet
        high_ports = {80, 8080, 8443, 5000, 9090}  # Web services, management
        if any(p in critical_ports for p in ports):
            return "critical"
        if any(p in high_ports for p in ports):
            return "high"
        if ports:
            return "medium"
        return "low"

    @staticmethod
    def _port_names(ports: list[int]) -> str:
        """Convert a port list to human-readable names."""
        names = {
            22: "SSH", 23: "Telnet", 53: "DNS", 80: "HTTP", 139: "NetBIOS",
            443: "HTTPS", 445: "SMB", 3389: "RDP", 5900: "VNC",
            8080: "HTTP-Alt", 8443: "HTTPS-Alt",
        }
        parts = []
        for p in ports[:5]:  # Show first 5
            name = names.get(p, str(p))
            parts.append(name)
        if len(ports) > 5:
            parts.append(f"+{len(ports) - 5} more")
        return ", ".join(parts) if parts else "unknown"

    # -----------------------------------------------------------------
    # Manufacturer Profiles
    # -----------------------------------------------------------------

    def get_manufacturer_profiles(
        self,
        from_ts: str,
        to_ts: str,
        excluded_ips: list[str] | None = None,
    ) -> dict[str, Any]:
        """Group IoT devices by manufacturer and compute aggregate metrics.

        Returns dict with 'manufacturers' list sorted by worst hygiene first.
        """
        devices = self._iot_devices
        if not devices:
            return {"manufacturers": []}

        excluded = build_excluded_ips_filter(excluded_ips or [])
        macs = list(devices.keys())

        # Batch queries for data
        conn_stats = self._query_conn_stats_batch(macs, from_ts, to_ts, excluded)
        dns_stats = self._query_dns_tracker_batch(macs, from_ts, to_ts, excluded)
        port_detail = self._query_port_detail_batch(macs, from_ts, to_ts, excluded)

        expected_ports = self._get_expected_ports()

        # Group devices by manufacturer
        mfg_groups: dict[str, list[str]] = {}
        for mac, dev_info in devices.items():
            mfg = dev_info.get("manufacturer", "Unknown")
            mfg_groups.setdefault(mfg, []).append(mac)

        manufacturers: list[dict[str, Any]] = []
        for mfg_name, mfg_macs in mfg_groups.items():
            device_count = len(mfg_macs)
            trust_scores: list[int] = []
            privacy_scores: list[int] = []
            total_encrypted = 0
            total_conns = 0
            total_tracker_domains = 0
            total_violations = 0

            for mac in mfg_macs:
                cs = conn_stats.get(mac, {})
                ds = dns_stats.get(mac, {})
                baseline = self._baselines.get(mac)

                # Build stats for trust scoring
                stats = self._build_device_stats(
                    mac, cs, ds, baseline, expected_ports,
                )
                score_result = self._scorer.score_device(stats)
                trust_scores.append(score_result["score"])
                privacy_scores.append(score_result["privacy_score"])

                # Encryption stats
                mc = cs.get("total_connections", 0)
                me = cs.get("encrypted_connections", 0)
                total_conns += mc
                total_encrypted += me

                # Tracker domains
                total_tracker_domains += ds.get("tracker_domain_count", 0)

                # Protocol violations
                pd = port_detail.get(mac, {})
                dev_info = devices.get(mac, {})
                category = self._categorize_device(dev_info)
                profile = self._protocol_profiles.get(
                    category, self._protocol_profiles.get("default", {})
                )
                cat_expected = set(profile.get("expected_ports", [80, 443, 53, 123, 5353, 1900]))
                for port in pd:
                    if port not in cat_expected:
                        total_violations += 1

            avg_trust = int(round(sum(trust_scores) / len(trust_scores))) if trust_scores else 0
            avg_trust_grade = self._scorer.score_to_grade(avg_trust)
            avg_privacy = int(round(sum(privacy_scores) / len(privacy_scores))) if privacy_scores else 0
            avg_privacy_grade = self._scorer.score_to_grade(avg_privacy)
            encryption_pct = int(round(total_encrypted / total_conns * 100)) if total_conns > 0 else 100

            manufacturers.append({
                "name": mfg_name,
                "device_count": device_count,
                "avg_trust_score": avg_trust,
                "avg_trust_grade": avg_trust_grade,
                "avg_privacy_grade": avg_privacy_grade,
                "encryption_pct": encryption_pct,
                "total_tracker_domains": total_tracker_domains,
                "total_violations": total_violations,
            })

        # Sort by worst trust score first
        manufacturers.sort(key=lambda m: m["avg_trust_score"])
        return {"manufacturers": manufacturers}
