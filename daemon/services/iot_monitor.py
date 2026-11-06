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

from api.alerts import SURICATA_NOISE_EXCLUSION
from services.dns_analytics import LOCAL_NAME_SERVICE_PORTS
from services.excluded_ips import CONN_RECORDS, build_excluded_ips_filter
from services.iot_trust_scorer import IoTTrustScorer
from storage.all_buckets import all_buckets, complete_terms
from storage.time_slots import histogram_buckets, time_slots

logger = logging.getLogger("nettap.services.iot_monitor")

NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

# Zeek writes the ICMP type/code into the port fields (destination.port 0/3/8/11)
ICMP_TRANSPORTS = ["icmp", "icmp6", "ipv6-icmp"]
# DNS, DHCP, NTP, SSDP, NetBIOS datagram, plus mDNS/LLMNR/NetBIOS name service
LOCAL_SERVICE_PORTS = sorted({53, 67, 68, 123, 138, 1900, *LOCAL_NAME_SERVICE_PORTS})
MULTICAST_BROADCAST = ["224.0.0.0/4", "ff00::/8", "255.255.255.255"]
# Plumbing every device does (G11 false findings 2026-11-01): never an unexpected
# port or part of the encryption share. Dedicated checks such as hardcoded DNS
# query port 53 themselves, so they still see it.
LOCAL_CHATTER_EXCLUSION: list[dict] = [
    {"terms": {"network.transport": ICMP_TRANSPORTS}},
    {"terms": {"destination.port": LOCAL_SERVICE_PORTS}},
    {"terms": {"destination.ip": MULTICAST_BROADCAST}},
]
# HTTPS/QUIC, DNS-over-TLS, alt-HTTPS, MQTT over TLS, plus whatever Zeek itself
# identified as an encrypted protocol (network.protocol is Zeek's conn service)
ENCRYPTED_PORTS = [443, 853, 8443, 8883]
ENCRYPTED_PROTOCOLS = ["ssl", "ssh", "quic", "dtls", "ipsec", "wireguard", "openvpn"]
# NAT discovery carries no user data, so it is left out of the encryption share
NO_PAYLOAD_PROTOCOLS = ["stun"]
# One rule for "encrypted", shared with the Security Posture page (/api/traffic/protocols)
ENCRYPTED_CONN_FILTER: dict = {
    "bool": {
        "should": [
            {"terms": {"destination.port": ENCRYPTED_PORTS}},
            {"terms": {"network.protocol": ENCRYPTED_PROTOCOLS}},
        ],
        "minimum_should_match": 1,
    }
}
# Isolation is a security check, so it drops only UDP DNS/DHCP/NTP/discovery and
# multicast/broadcast. TCP on those ports and pings to LAN hosts stay visible.
ISOLATION_NOISE_EXCLUSION: list[dict] = [
    {
        "bool": {
            "filter": [
                {"term": {"network.transport": "udp"}},
                {"terms": {"destination.port": LOCAL_SERVICE_PORTS}},
            ]
        }
    },
    {"terms": {"destination.ip": MULTICAST_BROADCAST}},
]
# A port in an IoT-to-LAN pair makes it critical (SSH, Telnet, NetBIOS, SMB, RDP, VNC)
# or high (web, management)
ISOLATION_CRITICAL_PORTS = [22, 23, 139, 445, 3389, 5900]
ISOLATION_HIGH_PORTS = [80, 5000, 8080, 8443, 9090]
_ISOLATION_RISKY_PORTS = [*ISOLATION_CRITICAL_PORTS, *ISOLATION_HIGH_PORTS]
# Per (IoT MAC, LAN host) pair
ISOLATION_PAIR_AGGS: dict = {
    # Zeek stores the ICMP code in destination.port; keep it out
    "not_icmp": {
        "filter": {
            "bool": {"must_not": [{"terms": {"network.transport": ICMP_TRANSPORTS}}]}
        },
        "aggs": {
            "ports": {"terms": {"field": "destination.port", "size": 20}},
            # the top 20 can miss a sweep's one SMB connection; risky ports come apart (#96)
            "risky": {
                "filter": {"terms": {"destination.port": _ISOLATION_RISKY_PORTS}},
                "aggs": {
                    "ports": {
                        "terms": {
                            "field": "destination.port",
                            "size": len(_ISOLATION_RISKY_PORTS),
                        }
                    }
                },
            },
            "port_count": {"cardinality": {"field": "destination.port"}},
        },
    },
    "source_ip": {"terms": {"field": "source.ip", "size": 1}},
}

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
    "ai-link",
    "sichuan ai-link",
}

# OUI names that are ALWAYS IoT, regardless of keyword matching
IOT_OUI_ALWAYS = {
    "philips lighting bv",
    "philips hue",
    "tuya smart inc.",
    "espressif inc.",
    "sichuan ai-link technology co., ltd.",
    "shenzhen bilian electronic co.",  # Makes IoT modules
}

# OUI names that are NEVER IoT, even if they match a keyword
IOT_OUI_NEVER = {
    "ubiquiti inc",  # Network infrastructure
    "proxmox server solutions gmbh",  # Hypervisor
    "western digital technologies, inc.",  # NAS
}

# Anomaly type constants
ANOMALY_NEW_DESTINATION = "NEW_DESTINATION"
ANOMALY_NEW_COUNTRY = "NEW_COUNTRY"
ANOMALY_NEW_PORT = "NEW_PORT"
ANOMALY_UNUSUAL_TIME = "UNUSUAL_TIME"
ANOMALY_VOLUME_SPIKE = "VOLUME_SPIKE"
ANOMALY_PROTOCOL_CHANGE = "PROTOCOL_CHANGE"

# The baseline's "known" sets: anything outside them is flagged as new, so each holds
# every value of the window, not a top N (#96)
BASELINE_KNOWN_SOURCES: dict[str, dict] = {
    "known_destinations": {"terms": {"field": "destination.ip"}},
    "known_ports": {"terms": {"field": "destination.port"}},
    "known_protocols": {"terms": {"field": "network.protocol"}},
    "known_countries": {
        "terms": {"field": "destination.geo.country_name", "missing_bucket": True}
    },
}


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
            logger.warning(
                "Protocol profiles file not found: %s", _PROTOCOL_PROFILES_FILE
            )
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
    # Arkime OUI-based IoT device discovery
    # -----------------------------------------------------------------

    def _discover_iot_devices_from_arkime(
        self,
        from_ts: str,
        to_ts: str,
        excluded_ips: list[str] | None = None,
    ) -> None:
        """Discover IoT devices by querying Arkime sessions for unique
        source MACs with OUI manufacturer data, then classifying them
        as IoT based on manufacturer keyword matching.

        Replaces ``self._iot_devices`` with the devices that have traffic in this
        window, each with its newest IP and last record from the query (NET-158).

        Args:
            from_ts: ISO timestamp for the start of the query window.
            to_ts:   ISO timestamp for the end of the query window.
            excluded_ips: IPs to exclude from the query results.
        """
        excluded = build_excluded_ips_filter(excluded_ips or [])

        bool_clause: dict = {
            "filter": [
                {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
                {"exists": {"field": "source.mac"}},
                {"exists": {"field": "source.oui"}},
            ]
        }
        if excluded:
            bool_clause["must_not"] = excluded

        # OLD CODE START — #96: the 500 busiest MACs only; quiet IoT devices on a bigger
        # network were never discovered, so device_count stopped short
        # query = {
        #     "size": 0,
        #     "query": {"bool": bool_clause},
        #     "aggs": {
        #         "by_mac": {
        #             "terms": {"field": "source.mac", "size": 500},
        #             "aggs": {
        #                 "oui": {"terms": {"field": "source.oui", "size": 1}},
        #                 "latest_ip": {"terms": {"field": "source.ip", "size": 1}},
        #                 "last_seen": {"max": {"field": "@timestamp"}},
        #             },
        #         }
        #     },
        # }
        #
        # try:
        #     result = self._client.search(index=NETWORK_INDEX, body=query)
        # except Exception as exc:
        #     logger.error("IoT Arkime OUI discovery query failed: %s", exc)
        #     return
        #
        # buckets = result.get("aggregations", {}).get("by_mac", {}).get("buckets", [])
        # OLD CODE END
        try:
            buckets, complete = all_buckets(
                self._client,
                NETWORK_INDEX,
                {"bool": bool_clause},
                [{"mac": {"terms": {"field": "source.mac"}}}],
                aggs={
                    "oui": {"terms": {"field": "source.oui", "size": 1}},
                    # OLD CODE START — NET-158: the device's most frequent IP, not its newest
                    # "latest_ip": {"terms": {"field": "source.ip", "size": 1}},
                    # OLD CODE END
                    "latest_ip": {
                        "top_hits": {
                            "size": 1,
                            "sort": [{"@timestamp": {"order": "desc"}}],
                            "_source": ["source.ip"],
                        }
                    },
                    "last_seen": {"max": {"field": "@timestamp"}},
                },
            )
        except Exception as exc:
            logger.error("IoT Arkime OUI discovery query failed: %s", exc)
            # OLD CODE START — #96: the fleet read the cached devices, or "no IoT devices", as current
            # return
            # OLD CODE END
            raise
        if not complete:
            logger.warning("IoT discovery stopped at %d MACs", len(buckets))

        # NET-158: one set per window; a cached set ignored the range, kept scoring devices
        # with no traffic in it, and froze each device's IP and last seen
        devices: dict[str, dict[str, Any]] = {}
        for bucket in buckets:
            # OLD CODE START — #96: terms bucket key
            # mac = bucket["key"].upper()
            # OLD CODE END
            mac = bucket["key"]["mac"].upper()

            # OLD CODE START — NET-158: the first window's entry was kept for every later one
            # # Already registered — skip re-classification
            # if mac in self._iot_devices:
            #     continue
            # OLD CODE END

            oui_buckets = bucket.get("oui", {}).get("buckets", [])
            if not oui_buckets:
                continue
            oui_name = oui_buckets[0]["key"]

            # OLD CODE START — NET-158: terms bucket of the most frequent IP
            # ip_buckets = bucket.get("latest_ip", {}).get("buckets", [])
            # latest_ip = ip_buckets[0]["key"] if ip_buckets else None
            # OLD CODE END
            hits = bucket.get("latest_ip", {}).get("hits", {}).get("hits", [])
            latest_ip = (
                hits[0].get("_source", {}).get("source", {}).get("ip") if hits else None
            )

            if self._is_iot_oui(oui_name):
                devices[mac] = {
                    "mac": mac,
                    "manufacturer": oui_name,
                    "hostname": None,
                    "ip": latest_ip,
                    "classified_at": datetime.now(timezone.utc).isoformat(),
                    "last_seen": bucket.get("last_seen", {}).get("value_as_string"),
                    "is_iot": True,
                }
        self._iot_devices = devices

        logger.info(
            "Arkime OUI discovery found %d IoT devices total",
            len(self._iot_devices),
        )

    @staticmethod
    def _is_iot_oui(oui_name: str) -> bool:
        """Determine if an OUI manufacturer name indicates an IoT device.

        Uses three layers:
        1. IOT_OUI_NEVER — always reject (infrastructure, NAS, etc.)
        2. IOT_OUI_ALWAYS — always accept (known IoT chip/product makers)
        3. IOT_MANUFACTURERS keyword substring match (case-insensitive)

        Args:
            oui_name: The OUI manufacturer string from Arkime.

        Returns:
            True if the OUI indicates an IoT device.
        """
        oui_lower = oui_name.lower()

        # Layer 1: explicit exclusions take priority
        if oui_lower in IOT_OUI_NEVER:
            return False

        # Layer 2: explicit inclusions
        if oui_lower in IOT_OUI_ALWAYS:
            return True

        # Layer 3: substring matching against IoT manufacturer keywords
        return any(keyword in oui_lower for keyword in IOT_MANUFACTURERS)

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
        # Auto-discover IoT devices from Arkime OUI data
        self._discover_iot_devices_from_arkime(from_ts, to_ts, excluded_ips)

        devices = self._iot_devices
        if not devices:
            return self._empty_fleet_summary()

        excluded = build_excluded_ips_filter(excluded_ips or [])
        expected_ports = self._get_expected_ports()

        # ----- Batch query: per-device connection stats -----
        conn_stats = self._query_conn_stats_batch(
            list(devices.keys()),
            from_ts,
            to_ts,
            excluded,
        )

        # ----- Batch query: DNS tracker stats -----
        dns_stats = self._query_dns_tracker_batch(
            list(devices.keys()),
            from_ts,
            to_ts,
            excluded,
        )

        # ----- Score each device -----
        device_results: list[dict[str, Any]] = []
        device_scores: list[int | None] = []
        total_anomaly_count = 0
        # devices with a baseline: the only ones whose anomalies are checked (NET-158)
        anomalies_checked = 0
        privacy_concern_count = 0
        unencrypted_count = 0

        for mac, dev_info in devices.items():
            cs = conn_stats.get(mac, {})
            ds = dns_stats.get(mac, {})
            baseline = self._baselines.get(mac)

            # Build the stats dict expected by IoTTrustScorer.score_device()
            stats = self._build_device_stats(
                mac,
                cs,
                ds,
                baseline,
                expected_ports,
            )

            score_result = self._scorer.score_device(stats)
            score = score_result["score"]
            device_scores.append(score)

            # OLD CODE START — NET-158: a device with no baseline read 0 anomalies ("All
            # clear"), but check_anomalies() returns [] without one: nothing was checked
            # device_anomalies = self.check_anomalies(mac, excluded_ips=excluded_ips)
            # anomaly_count = len(device_anomalies)
            # total_anomaly_count += anomaly_count
            # OLD CODE END
            anomaly_count: int | None = None
            if baseline:
                anomaly_count = len(
                    self.check_anomalies(mac, excluded_ips=excluded_ips)
                )
                total_anomaly_count += anomaly_count
                anomalies_checked += 1

            # Privacy concern: tracker_domain_count > 5
            tracker_count = stats.get("tracker_domain_count", 0)
            if tracker_count > 5:
                privacy_concern_count += 1

            # OLD CODE START — NET-158: no eligible traffic is no ratio, not 100%
            # # Unencrypted: encryption_ratio < 0.5
            # encryption_ratio = stats.get("encryption_ratio", 1.0)
            # encryption_pct = int(round(encryption_ratio * 100))
            # if encryption_ratio < 0.5:
            #     unencrypted_count += 1
            # OLD CODE END
            encryption_ratio = stats["encryption_ratio"]
            encryption_pct = (
                None if encryption_ratio is None else int(round(encryption_ratio * 100))
            )
            if encryption_ratio is not None and encryption_ratio < 0.5:
                unencrypted_count += 1

            device_results.append(
                {
                    "mac": mac,
                    "name": dev_info.get("hostname")
                    or dev_info.get("manufacturer", "Unknown"),
                    "manufacturer": dev_info.get("manufacturer", "Unknown"),
                    "ip": dev_info.get("ip", ""),
                    "score": score,
                    "grade": score_result["grade"],
                    "coverage": score_result["coverage"],
                    "checks_available": score_result["checks_available"],
                    "checks_total": score_result["checks_total"],
                    "privacy_score": score_result["privacy_score"],
                    "security_score": score_result["security_score"],
                    "behavior_score": score_result["behavior_score"],
                    "anomaly_count": anomaly_count,
                    "encryption_pct": encryption_pct,
                    "encryption_applicable": stats["encryption_applicable"],
                    "tracker_count": tracker_count,
                    # OLD CODE START — NET-158: when the daemon first classified it
                    # "last_seen": dev_info.get("classified_at", ""),
                    # OLD CODE END
                    "last_seen": dev_info.get("last_seen"),
                }
            )

        # ----- Fleet-level aggregation -----
        fleet_score = self._scorer.compute_fleet_score(device_scores)
        fleet_grade = self._scorer.score_to_grade(fleet_score)
        scored = [d for d in device_results if d["score"] is not None]

        # Average sub-scores across the scored devices
        avg_privacy = self._avg_field(scored, "privacy_score")
        avg_security = self._avg_field(scored, "security_score")
        avg_behavior = self._avg_field(scored, "behavior_score")

        # Build subtitle
        subtitle = self._build_subtitle(
            fleet_score,
            len(devices),
            total_anomaly_count,
            privacy_concern_count,
        )

        # Sort devices by score ascending (worst first) for attention priority
        # OLD CODE START — NET-158: scores can be None now
        # device_results.sort(key=lambda d: d["score"])
        # OLD CODE END
        device_results.sort(key=lambda d: (d["score"] is None, d["score"] or 0))

        return {
            "health_score": fleet_score,
            "health_grade": fleet_grade,
            "privacy_score": avg_privacy,
            "security_score": avg_security,
            "behavior_score": avg_behavior,
            "device_count": len(devices),
            "scored_device_count": len(scored),
            "anomaly_count": total_anomaly_count,
            "anomalies_checked": anomalies_checked,
            "privacy_concerns": privacy_concern_count,
            "unencrypted_count": unencrypted_count,
            "subtitle": subtitle,
            "devices": device_results,
        }

    def _empty_fleet_summary(self) -> dict[str, Any]:
        """Return a fleet summary with no devices: nothing measured, so no score."""
        # OLD CODE START — NET-158: an empty fleet read 100, grade A
        # return {
        #     "health_score": 100,
        #     "health_grade": "A",
        #     "privacy_score": 100,
        #     "security_score": 100,
        #     "behavior_score": 100,
        # OLD CODE END
        return {
            "health_score": None,
            "health_grade": None,
            "privacy_score": None,
            "security_score": None,
            "behavior_score": None,
            "device_count": 0,
            "scored_device_count": 0,
            "anomaly_count": 0,
            "anomalies_checked": 0,
            "privacy_concerns": 0,
            "unencrypted_count": 0,
            "subtitle": "No IoT devices detected yet.",
            "devices": [],
        }

    @staticmethod
    def _avg_field(devices: list[dict], field: str) -> int | None:
        """Integer average of a field over the devices that have it; None if none do."""
        # OLD CODE START — NET-158: no devices read 100, and a missing value counted as 0
        # if not devices:
        #     return 100
        # total = sum(d.get(field, 0) for d in devices)
        # return int(round(total / len(devices)))
        # OLD CODE END
        values = [d[field] for d in devices if d.get(field) is not None]
        return int(round(sum(values) / len(values))) if values else None

    @staticmethod
    def _build_subtitle(
        score: int | None,
        device_count: int,
        anomaly_count: int,
        privacy_concerns: int,
    ) -> str:
        """Generate a human-readable fleet health subtitle."""
        if device_count == 0:
            return "No IoT devices detected yet."

        if score is None:
            prefix = "Not enough measured to score your smart home yet."
        elif score >= 90:
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

        Local chatter (ICMP, DNS/DHCP/NTP/discovery, multicast/broadcast) is
        left out, so every count below covers only traffic where encryption
        and destination ports mean something.

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
                CONN_RECORDS,
                {"terms": {"source.mac": mac_terms}},
            ],
            "must_not": [*excluded, *LOCAL_CHATTER_EXCLUSION],
        }
        # OLD CODE START — 2026-11-01: counted ICMP types as ports and DNS/mDNS as unencrypted
        # if excluded:
        #     bool_clause["must_not"] = excluded
        # OLD CODE END

        query = {
            "size": 0,
            "query": {"bool": bool_clause},
            "aggs": {
                "by_mac": {
                    "terms": {"field": "source.mac", "size": len(macs) * 2},
                    "aggs": {
                        "total_bytes": {"sum": {"field": "source.bytes", "missing": 0}},
                        # OLD CODE START — #96: top 100 ports per device; see _counts_by_mac
                        # "dest_ports": {
                        #     "terms": {"field": "destination.port", "size": 100}
                        # },
                        # OLD CODE END
                        # OLD CODE START — 2026-11-02: port list only; DNS-over-TLS (853),
                        # SSH and Zeek-identified TLS on other ports counted as plaintext
                        # "encrypted": {
                        #     "filter": {"terms": {"destination.port": [443, 8443, 8883]}}
                        # },
                        # OLD CODE END
                        # OLD CODE START — the same filter, now the shared ENCRYPTED_CONN_FILTER
                        # "encrypted": {
                        #     "filter": {
                        #         "bool": {
                        #             "should": [
                        #                 {"terms": {"destination.port": ENCRYPTED_PORTS}},
                        #                 {"terms": {"network.protocol": ENCRYPTED_PROTOCOLS}},
                        #             ],
                        #             "minimum_should_match": 1,
                        #         }
                        #     }
                        # },
                        # OLD CODE END
                        "encrypted": {"filter": ENCRYPTED_CONN_FILTER},
                        "no_payload": {
                            "filter": {
                                "terms": {"network.protocol": NO_PAYLOAD_PROTOCOLS}
                            }
                        },
                        "third_party_orgs": {
                            "cardinality": {
                                "field": "destination.as.full",
                            }
                        },
                    },
                }
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
            ports_by_mac = self._counts_by_mac(
                {"bool": bool_clause}, "destination.port"
            )
        except Exception as exc:
            logger.error("Fleet conn stats query failed: %s", exc)
            # OLD CODE START — #96: every device was scored as having no traffic
            # return {}
            # OLD CODE END
            raise

        out: dict[str, dict[str, Any]] = {}
        buckets = result.get("aggregations", {}).get("by_mac", {}).get("buckets", [])

        for bucket in buckets:
            raw_mac = bucket["key"].upper()
            no_payload = bucket.get("no_payload", {}).get("doc_count", 0)
            # connections where encryption means something (the ratio's denominator)
            total_conns = bucket.get("doc_count", 0) - no_payload
            encrypted_conns = bucket.get("encrypted", {}).get("doc_count", 0)
            total_bytes = bucket.get("total_bytes", {}).get("value", 0) or 0
            # OLD CODE START — #96: top 100 ports per device
            # ports = {b["key"] for b in bucket.get("dest_ports", {}).get("buckets", [])}
            # OLD CODE END
            ports = set(ports_by_mac.get(raw_mac, {}))
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
                {"terms": {"source.mac": mac_terms}},
            ],
            # #82: Suricata engine events aren't alerts (same rule as the Alerts page and the
            # device list, #60). G11: three IoT devices showed 521, 220 and 15 "alerts", all
            # engine events, which lowered their trust scores
            "must_not": [*SURICATA_NOISE_EXCLUSION, *excluded],
        }
        # OLD CODE START — #82: only the excluded IPs were left out
        # if excluded:
        #     bool_clause["must_not"] = excluded
        # OLD CODE END

        query = {
            "size": 0,
            "query": {"bool": bool_clause},
            "aggs": {
                "by_mac": {
                    "terms": {"field": "source.mac", "size": len(macs) * 2},
                }
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except Exception as exc:
            logger.error("Fleet alert count query failed: %s", exc)
            # OLD CODE START — #96: every device read 0 alerts
            # return {}
            # OLD CODE END
            raise

        out: dict[str, int] = {}
        for bucket in (
            result.get("aggregations", {}).get("by_mac", {}).get("buckets", [])
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
                {"terms": {"source.mac": mac_terms}},
            ]
        }
        if excluded:
            bool_clause["must_not"] = excluded

        query = {
            "size": 0,
            "query": {"bool": bool_clause},
            "aggs": {
                "by_mac": {
                    "terms": {"field": "source.mac", "size": len(macs) * 2},
                    # OLD CODE START — #96: the 500 most-queried domains only; trackers
                    # are usually in the quiet tail, so the count fell short
                    # "aggs": {
                    #     "queried_domains": {
                    #         "terms": {
                    #             "field": "dns.host",
                    #             "size": 500,
                    #         }
                    #     },
                    # },
                    # OLD CODE END
                }
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
            domains_by_mac = self._counts_by_mac({"bool": bool_clause}, "dns.host")
        except Exception as exc:
            logger.error("Fleet DNS tracker query failed: %s", exc)
            # OLD CODE START — #96: every device read 0 tracker domains
            # return {}
            # OLD CODE END
            raise

        out: dict[str, dict[str, Any]] = {}
        for bucket in (
            result.get("aggregations", {}).get("by_mac", {}).get("buckets", [])
        ):
            raw_mac = bucket["key"].upper()
            # OLD CODE START — #96: counted from the top-500 list
            # domains = bucket.get("queried_domains", {}).get("buckets", [])
            # tracker_count = 0
            # for d_bucket in domains:
            #     domain = d_bucket.get("key", "")
            #     if self._is_tracker_domain(domain):
            #         tracker_count += 1
            # OLD CODE END
            tracker_count = sum(
                1 for d in domains_by_mac.get(raw_mac, {}) if self._is_tracker_domain(d)
            )

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

        Each input is measured or unavailable (None) here, at its source (NET-158). A
        constant placeholder is never a measurement:
          - telemetry bytes: nothing measures them;
          - firmware: no signal ("unknown");
          - encryption: no eligible traffic, so there is no ratio;
          - all four behaviour checks: with no baseline there is nothing to compare, and
            with one they don't yet measure what their names say. baseline_adherence
            compares this window's destination ports with ports learned over the 14 days
            before the baseline was built (not destinations, not this window) and falls
            back to 1.0 / 0.5 constants; new_destinations counts new ports;
            volume_spike sets the window's total against a daily average; unusual_timing
            reads the hour of the request, not of the traffic. Correcting them is a
            follow-up.
        """
        total_conns = conn_stats.get("total_connections", 0)
        encrypted_conns = conn_stats.get("encrypted_connections", 0)
        # OLD CODE START — NET-158: only the baseline block below used it
        # total_bytes = conn_stats.get("total_bytes", 0)
        # OLD CODE END
        dest_ports = conn_stats.get("dest_ports", set())
        third_party_orgs = conn_stats.get("third_party_orgs", 0)
        alert_count = conn_stats.get("alert_count", 0)

        tracker_domain_count = dns_stats.get("tracker_domain_count", 0)

        # Encryption ratio
        # OLD CODE START — NET-158: no eligible traffic earned the full 15 points
        # if total_conns > 0:
        #     encryption_ratio = encrypted_conns / total_conns
        # else:
        #     encryption_ratio = 1.0  # No data = assume OK
        # OLD CODE END
        encryption_ratio = encrypted_conns / total_conns if total_conns > 0 else None

        # Protocol violations: ports not in expected set
        protocol_violations = 0
        for port in dest_ports:
            if port not in expected_ports:
                protocol_violations += 1

        # OLD CODE START — NET-158: scored as measured; see the docstring for why each is
        # unavailable now
        # # Baseline-derived stats
        # if baseline:
        #     known_dests = set(baseline.get("known_destinations", []))
        #     # OLD CODE START — all_dests was assigned but never used (F841)
        #     # all_dests = set()  # We don't have current destinations here individually,
        #     # OLD CODE END
        #     # We don't have current destinations here individually,
        #     # but dest_ports gives us a proxy. Use known_destinations count ratio.
        #     known_count = len(known_dests)
        #     # baseline_adherence: fraction of baseline destinations vs total seen
        #     # Simplified: if baseline exists, use ratio of known ports to all ports
        #     known_ports = set(baseline.get("known_ports", []))
        #     total_port_count = len(dest_ports)
        #     known_port_hits = len(dest_ports & known_ports) if dest_ports else 0
        #     if total_port_count > 0:
        #         baseline_adherence = known_port_hits / total_port_count
        #     elif known_count > 0:
        #         baseline_adherence = 1.0
        #     else:
        #         baseline_adherence = 0.5
        #
        #     new_destinations = max(0, total_port_count - known_port_hits)
        #
        #     # Volume spike: compare current bytes to baseline daily avg
        #     daily_avg = baseline.get("daily_avg_bytes", 0)
        #     volume_spike = total_bytes > daily_avg * 3 if daily_avg > 0 else False
        #
        #     # Unusual timing: check if current hour is outside baseline hours
        #     active_hours = set(baseline.get("active_hours", []))
        #     current_hour = datetime.now(timezone.utc).hour
        #     unusual_timing = bool(active_hours) and current_hour not in active_hours
        # else:
        #     # No baseline: use conservative defaults
        #     baseline_adherence = 0.5
        #     new_destinations = 0
        #     volume_spike = False
        #     unusual_timing = False
        #
        # return {
        #     "tracker_domain_count": tracker_domain_count,
        #     "telemetry_bytes": 0,  # Would need IP-to-tracker resolution; simplified for now
        #     "third_party_orgs": third_party_orgs,
        #     "encryption_ratio": min(1.0, max(0.0, encryption_ratio)),
        #     # False when only local chatter was seen: the ratio is then N/A, not 100%
        #     "encryption_applicable": total_conns > 0,
        #     "protocol_violations": protocol_violations,
        #     "alert_count": alert_count,
        #     "firmware_age_signal": "unknown",
        #     "baseline_adherence": min(1.0, max(0.0, baseline_adherence)),
        #     "new_destinations": new_destinations,
        #     "volume_spike": volume_spike,
        #     "unusual_timing": unusual_timing,
        # }
        # OLD CODE END
        return {
            "tracker_domain_count": tracker_domain_count,
            "telemetry_bytes": None,
            "third_party_orgs": third_party_orgs,
            "encryption_ratio": None
            if encryption_ratio is None
            else min(1.0, max(0.0, encryption_ratio)),
            # False when only local chatter was seen: the ratio is then N/A, not 100%
            "encryption_applicable": total_conns > 0,
            "protocol_violations": protocol_violations,
            "alert_count": alert_count,
            "firmware_age_signal": None,
            "baseline_adherence": None,
            "new_destinations": None,
            "volume_spike": None,
            "unusual_timing": None,
        }

    def classify_as_iot(self, device_mac: str, device_info: dict[str, Any]) -> bool:
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
            vendor in manufacturer or vendor in hostname for vendor in IOT_MANUFACTURERS
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
        self,
        device_mac: str,
        days: int = 14,
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
                CONN_RECORDS,
                {
                    "bool": {
                        "should": [
                            {"term": {"source.mac": mac}},
                            {"term": {"source.mac": mac.lower()}},
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
            # hits.total is shown as a count; without this OpenSearch stops at 10,000
            "track_total_hits": True,
            "query": {"bool": bool_clause},
            "aggs": {
                # OLD CODE START — #96: top 100/50/10/20 only; the rest read as "new" every hour
                # "destinations": {"terms": {"field": "destination.ip", "size": 100}},
                # "dest_ports": {"terms": {"field": "destination.port", "size": 50}},
                # "protocols": {"terms": {"field": "network.protocol", "size": 10}},
                # OLD CODE END
                # OLD CODE START — #120: OpenSearch 3.5's skip-list date_histogram misplaces records
                # "hourly_activity": {
                #     "date_histogram": {"field": "@timestamp", "calendar_interval": "hour"}
                # },
                # OLD CODE END
                "hourly_activity": time_slots(from_iso, to_iso, "1h"),
                "total_bytes": {"sum": {"field": "source.bytes", "missing": 0}},
                # OLD CODE START — #96: see above
                # "countries": {
                #     "terms": {
                #         "field": "destination.geo.country_name",
                #         "size": 20,
                #         "missing": "Unknown",
                #     }
                # },
                # OLD CODE END
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
            known = self._baseline_known_sets({"bool": bool_clause}, mac)
        except Exception as exc:
            logger.error("Failed to build baseline for %s: %s", mac, exc)
            # OLD CODE START — #96: answered 200 with {"error": ...} as the baseline
            # return {"error": str(exc)}
            # OLD CODE END
            raise

        aggs = result.get("aggregations", {})

        # OLD CODE START — #96: top-N lists treated as every known value
        # # Extract known destinations
        # destinations = [
        #     b["key"] for b in aggs.get("destinations", {}).get("buckets", [])
        # ]
        #
        # # Extract known ports
        # ports = [b["key"] for b in aggs.get("dest_ports", {}).get("buckets", [])]
        #
        # # Extract known protocols
        # protocols = [b["key"] for b in aggs.get("protocols", {}).get("buckets", [])]
        #
        # # Extract known countries
        # countries = [b["key"] for b in aggs.get("countries", {}).get("buckets", [])]
        # OLD CODE END

        # Calculate active hours from histogram
        hourly = histogram_buckets(
            aggs.get("hourly_activity")
        )  # date_histogram before #120
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
            # OLD CODE START — #96: top-N lists
            # "known_destinations": destinations,
            # "known_ports": ports,
            # "known_protocols": protocols,
            # "known_countries": countries,
            # OLD CODE END
            **known,
            "active_hours": sorted(active_hours),
            "total_bytes": total_bytes,
            "daily_avg_bytes": daily_avg_bytes,
            "connection_count": connection_count,
        }

        self._baselines[mac] = baseline
        return baseline

    def _baseline_known_sets(self, query: dict, mac: str) -> dict[str, list]:
        """Every destination, port, protocol and country the device used in `query`.

        A missing country reads as "Unknown", as the terms aggregation's `missing` did.
        """
        known: dict[str, list] = {}
        for name, source in BASELINE_KNOWN_SOURCES.items():
            buckets, complete = all_buckets(
                self._client, NETWORK_INDEX, query, [{"value": source}]
            )
            if not complete:
                logger.warning(
                    "Baseline %s for %s stopped at %d values", name, mac, len(buckets)
                )
            known[name] = [
                "Unknown" if b["key"]["value"] is None else b["key"]["value"]
                for b in buckets
            ]
        return known

    def check_anomalies(
        self,
        device_mac: str,
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
                CONN_RECORDS,
                {
                    "bool": {
                        "should": [
                            {"term": {"source.mac": mac}},
                            {"term": {"source.mac": mac.lower()}},
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
            "query": {"bool": bool_clause},
            "aggs": {
                "destinations": {"terms": {"field": "destination.ip", "size": 100}},
                "dest_ports": {"terms": {"field": "destination.port", "size": 50}},
                "protocols": {"terms": {"field": "network.protocol", "size": 10}},
                "total_bytes": {"sum": {"field": "source.bytes", "missing": 0}},
                "countries": {
                    "terms": {
                        "field": "destination.geo.country_name",
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
            # OLD CODE START — #96: read as "no anomalies" and a fleet anomaly count of 0
            # return []
            # OLD CODE END
            raise

        aggs = result.get("aggregations", {})

        def every(name: str, known: str) -> list[dict]:
            # #96: the hour's top 100/20/50/10 only; a new value ranked past them went unreported
            return complete_terms(
                self._client,
                NETWORK_INDEX,
                {"bool": bool_clause},
                aggs.get(name, {}),
                BASELINE_KNOWN_SOURCES[known],
                missing="Unknown",
            )

        anomalies: list[dict[str, Any]] = []
        known_dests = set(baseline.get("known_destinations", []))
        known_ports = set(baseline.get("known_ports", []))
        known_protocols = set(baseline.get("known_protocols", []))
        known_countries = set(baseline.get("known_countries", []))
        active_hours = set(baseline.get("active_hours", []))

        # Check new destinations
        # OLD CODE START — #96: see every()
        # for b in aggs.get("destinations", {}).get("buckets", []):
        # OLD CODE END
        for b in every("destinations", "known_destinations"):
            if b["key"] not in known_dests:
                anomalies.append(
                    {
                        "type": ANOMALY_NEW_DESTINATION,
                        "mac": mac,
                        "detail": b["key"],
                        "count": b["doc_count"],
                        "severity": "medium",
                        "description": f"New destination IP {b['key']} not in baseline",
                        "detected_at": now.isoformat(),
                    }
                )

        # Check new countries
        # OLD CODE START — #96: see every()
        # for b in aggs.get("countries", {}).get("buckets", []):
        # OLD CODE END
        for b in every("countries", "known_countries"):
            if b["key"] not in known_countries and b["key"] != "Unknown":
                anomalies.append(
                    {
                        "type": ANOMALY_NEW_COUNTRY,
                        "mac": mac,
                        "detail": b["key"],
                        "count": b["doc_count"],
                        "severity": "high",
                        "description": f"Traffic to new country: {b['key']}",
                        "detected_at": now.isoformat(),
                    }
                )

        # Check new ports
        # OLD CODE START — #96: see every()
        # for b in aggs.get("dest_ports", {}).get("buckets", []):
        # OLD CODE END
        for b in every("dest_ports", "known_ports"):
            if b["key"] not in known_ports:
                anomalies.append(
                    {
                        "type": ANOMALY_NEW_PORT,
                        "mac": mac,
                        "detail": str(b["key"]),
                        "count": b["doc_count"],
                        "severity": "medium",
                        "description": f"New destination port {b['key']}",
                        "detected_at": now.isoformat(),
                    }
                )

        # Check protocol changes
        # OLD CODE START — #96: see every()
        # for b in aggs.get("protocols", {}).get("buckets", []):
        # OLD CODE END
        for b in every("protocols", "known_protocols"):
            if b["key"] not in known_protocols:
                anomalies.append(
                    {
                        "type": ANOMALY_PROTOCOL_CHANGE,
                        "mac": mac,
                        "detail": b["key"],
                        "count": b["doc_count"],
                        "severity": "medium",
                        "description": f"New protocol: {b['key']}",
                        "detected_at": now.isoformat(),
                    }
                )

        # Check volume spike (current hourly rate vs daily average / 24)
        current_bytes = aggs.get("total_bytes", {}).get("value", 0) or 0
        hourly_avg = baseline.get("daily_avg_bytes", 0) / 24
        if hourly_avg > 0 and current_bytes > hourly_avg * 5:
            anomalies.append(
                {
                    "type": ANOMALY_VOLUME_SPIKE,
                    "mac": mac,
                    "detail": f"{current_bytes} bytes (avg: {hourly_avg:.0f}/hr)",
                    "severity": "high",
                    "description": (
                        f"Volume spike: {current_bytes} bytes in last hour "
                        f"vs {hourly_avg:.0f} hourly average"
                    ),
                    "detected_at": now.isoformat(),
                }
            )

        # Check unusual time
        current_hour = now.hour
        if active_hours and current_hour not in active_hours:
            anomalies.append(
                {
                    "type": ANOMALY_UNUSUAL_TIME,
                    "mac": mac,
                    "detail": f"Hour {current_hour}",
                    "severity": "low",
                    "description": (
                        f"Activity at unusual hour ({current_hour}:00) "
                        f"outside normal schedule"
                    ),
                    "detected_at": now.isoformat(),
                }
            )

        return anomalies

    def get_iot_devices(self) -> list[dict[str, Any]]:
        """Return all IoT-classified devices."""
        return list(self._iot_devices.values())

    def get_device_baseline(self, mac: str) -> dict[str, Any] | None:
        """Return the learned baseline for a device, or None."""
        return self._baselines.get(mac.strip().upper())

    def get_anomalies(
        self,
        from_ts: str,
        to_ts: str,
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
        # Auto-discover IoT devices from Arkime OUI data
        self._discover_iot_devices_from_arkime(from_ts, to_ts, excluded_ips)

        devices = self._iot_devices
        if not devices:
            return {"devices": []}

        excluded = build_excluded_ips_filter(excluded_ips or [])
        macs = list(devices.keys())

        # Batch query: connection stats (encryption ratio, bytes, etc.)
        conn_stats = self._query_conn_stats_batch(macs, from_ts, to_ts, excluded)

        # Batch query: DNS tracker stats with per-domain detail
        dns_detail = self._query_dns_tracker_detail_batch(
            macs, from_ts, to_ts, excluded
        )

        # Compute time window in hours for phone-home rate
        try:
            from_dt = datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
            to_dt = datetime.fromisoformat(to_ts.replace("Z", "+00:00"))
            window_hours = max(1.0, (to_dt - from_dt).total_seconds() / 3600)
        except (ValueError, TypeError):
            window_hours = 24.0

        expected_ports = self._get_expected_ports()
        device_results: list[dict[str, Any]] = []
        for mac, dev_info in devices.items():
            cs = conn_stats.get(mac, {})
            dd = dns_detail.get(mac, {})

            total_conns = cs.get("total_connections", 0)
            encrypted_conns = cs.get("encrypted_connections", 0)
            # OLD CODE START — NET-158: only the telemetry estimate below used it
            # total_bytes = cs.get("total_bytes", 0)
            # OLD CODE END
            third_party_orgs = cs.get("third_party_orgs", 0)

            encryption_ratio = encrypted_conns / total_conns if total_conns > 0 else 1.0

            tracker_domains_list = dd.get("tracker_domains", [])
            tracker_count = len(tracker_domains_list)

            # OLD CODE START — NET-158: an estimate shown as bytes; the lookup share is what
            # was measured
            # # Estimate telemetry bytes as a fraction of total bytes
            # # proportional to tracker queries vs total queries
            # total_queries = dd.get("total_dns_queries", 0)
            # tracker_query_sum = sum(t["query_count"] for t in tracker_domains_list)
            # if total_queries > 0 and total_bytes > 0:
            #     telemetry_bytes = int(total_bytes * tracker_query_sum / total_queries)
            # else:
            #     telemetry_bytes = 0
            # OLD CODE END
            total_queries = dd.get("total_dns_queries", 0)
            tracker_query_sum = sum(t["query_count"] for t in tracker_domains_list)
            tracker_lookup_share = (
                round(tracker_query_sum / total_queries, 4) if total_queries else None
            )

            phone_home_per_hour = (
                round(total_conns / window_hours, 2) if window_hours > 0 else 0
            )

            # OLD CODE START — NET-158: a second formula, so the drawer and the Privacy tab
            # showed two different privacy scores for one device
            # privacy_score = self._compute_privacy_score(
            #     tracker_count,
            #     encryption_ratio,
            #     third_party_orgs,
            #     telemetry_bytes,
            # )
            # OLD CODE END
            # The trust score's privacy pillar, from the same inputs as the fleet summary
            privacy_score = self._scorer.score_device(
                self._build_device_stats(
                    mac,
                    cs,
                    {"tracker_domain_count": tracker_count},
                    None,
                    expected_ports,
                )
            )["privacy_score"]
            privacy_grade = self._scorer.score_to_grade(privacy_score)

            device_results.append(
                {
                    "mac": mac,
                    "name": dev_info.get("hostname")
                    or dev_info.get("manufacturer", "Unknown"),
                    "privacy_grade": privacy_grade,
                    "privacy_score": privacy_score,
                    "tracker_domains": tracker_domains_list,
                    "tracker_count": tracker_count,
                    # OLD CODE START — NET-158: see the estimate above
                    # "telemetry_bytes": telemetry_bytes,
                    # OLD CODE END
                    "tracker_lookup_share": tracker_lookup_share,
                    "third_party_orgs": third_party_orgs,
                    "encryption_ratio": round(min(1.0, max(0.0, encryption_ratio)), 4),
                    # Only local chatter seen: ratio stays 1.0 so nothing is penalised
                    "encryption_applicable": total_conns > 0,
                    "phone_home_per_hour": phone_home_per_hour,
                }
            )

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
                {"terms": {"source.mac": mac_terms}},
            ]
        }
        if excluded:
            bool_clause["must_not"] = excluded

        query = {
            "size": 0,
            "query": {"bool": bool_clause},
            "aggs": {
                "by_mac": {
                    "terms": {"field": "source.mac", "size": len(macs) * 2},
                    # OLD CODE START — #96: the 500 most-queried domains only
                    # "aggs": {
                    #     "queried_domains": {
                    #         "terms": {
                    #             "field": "dns.host",
                    #             "size": 500,
                    #         }
                    #     },
                    # },
                    # OLD CODE END
                }
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
            domains_by_mac = self._counts_by_mac({"bool": bool_clause}, "dns.host")
        except Exception as exc:
            logger.error("DNS tracker detail query failed: %s", exc)
            # OLD CODE START — #96: the privacy report read no trackers for every device
            # return {}
            # OLD CODE END
            raise

        out: dict[str, dict[str, Any]] = {}
        for bucket in (
            result.get("aggregations", {}).get("by_mac", {}).get("buckets", [])
        ):
            raw_mac = bucket["key"].upper()
            # OLD CODE START — #96: listed from the top-500 list
            # domains = bucket.get("queried_domains", {}).get("buckets", [])
            # tracker_list: list[dict[str, Any]] = []
            # for d_bucket in domains:
            #     domain = d_bucket.get("key", "")
            #     if self._is_tracker_domain(domain):
            #         tracker_list.append(
            #             {
            #                 "domain": domain,
            #                 "query_count": d_bucket.get("doc_count", 0),
            #             }
            #         )
            # OLD CODE END
            tracker_list = [
                {"domain": domain, "query_count": count}
                for domain, count in domains_by_mac.get(raw_mac, {}).items()
                if self._is_tracker_domain(domain)
            ]

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
        baseline_dests = (
            set(baseline.get("known_destinations", [])) if baseline else set()
        )

        # Query conn logs for this device, aggregate by destination IP
        mac_filter = {
            "bool": {
                "should": [
                    {"term": {"source.mac": mac}},
                    {"term": {"source.mac": mac.lower()}},
                ],
                "minimum_should_match": 1,
            }
        }

        bool_clause: dict = {
            "filter": [
                _time_range_filter(from_ts, to_ts),
                CONN_RECORDS,
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
                    "terms": {"field": "destination.ip", "size": 200},
                    "aggs": {
                        "ports": {"terms": {"field": "destination.port", "size": 50}},
                        "bytes_sent": {"sum": {"field": "source.bytes", "missing": 0}},
                        "bytes_received": {
                            "sum": {"field": "destination.bytes", "missing": 0}
                        },
                        "country": {
                            "terms": {
                                "field": "destination.geo.country_iso_code",
                                "size": 1,
                            }
                        },
                        "first_seen": {"min": {"field": "@timestamp"}},
                        "last_seen": {"max": {"field": "@timestamp"}},
                    },
                }
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except Exception as exc:
            logger.error("Communication map query failed for %s: %s", mac, exc)
            # OLD CODE START — #96: read as a device that talks to nobody
            # return {"mac": mac, "destinations": []}
            # OLD CODE END
            raise

        # Resolve hostnames via DNS logs
        dest_ips = []
        dest_buckets = (
            result.get("aggregations", {}).get("by_dest", {}).get("buckets", [])
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
                if first_seen_ms is not None
                else None
            )
            last_seen = (
                b.get("last_seen", {}).get("value_as_string")
                if last_seen_ms is not None
                else None
            )

            destinations.append(
                {
                    "ip": ip,
                    "hostname": hostname_map.get(ip),
                    "country": country,
                    "ports": ports,
                    "bytes_sent": int(b.get("bytes_sent", {}).get("value", 0) or 0),
                    "bytes_received": int(
                        b.get("bytes_received", {}).get("value", 0) or 0
                    ),
                    "connection_count": b.get("doc_count", 0),
                    "first_seen": first_seen,
                    "last_seen": last_seen,
                    # OLD CODE START — NET-158: with no baseline every destination read "new"
                    # "in_baseline": ip in baseline_dests,
                    # OLD CODE END
                    # None: no baseline, so "new" was not checked
                    "in_baseline": (ip in baseline_dests) if baseline else None,
                }
            )

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
                    "terms": {"field": "dns.ip", "size": len(ips)},
                    "aggs": {
                        "domain": {
                            "terms": {
                                "field": "dns.host",
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
            result.get("aggregations", {}).get("by_answer_ip", {}).get("buckets", [])
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
                    {"term": {"source.mac": mac}},
                    {"term": {"source.mac": mac.lower()}},
                ],
                "minimum_should_match": 1,
            }
        }

        bool_clause: dict = {
            "filter": [
                _time_range_filter(from_ts, to_ts),
                CONN_RECORDS,
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
                    # OLD CODE START — #120: OpenSearch 3.5's skip-list date_histogram misplaces records
                    # "date_histogram": {"field": "@timestamp", "fixed_interval": "1h"},
                    # OLD CODE END
                    **time_slots(from_ts, to_ts, "1h"),
                    "aggs": {
                        "bytes": {"sum": {"field": "source.bytes", "missing": 0}},
                        "destinations": {"cardinality": {"field": "destination.ip"}},
                    },
                }
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except Exception as exc:
            logger.error("Activity timeline query failed for %s: %s", mac, exc)
            # OLD CODE START — #96: read as a device with no activity
            # return {
            #     "mac": mac,
            #     "interval": "1h",
            #     "buckets": [],
            #     "baseline_hours": [],
            #     "baseline_avg_hourly_bytes": 0,
            # }
            # OLD CODE END
            raise

        hourly_buckets = histogram_buckets(
            result.get("aggregations", {}).get("hourly")
        )  # date_histogram before #120

        buckets: list[dict[str, Any]] = []
        for hb in hourly_buckets:
            buckets.append(
                {
                    "time": hb.get("key_as_string", ""),
                    "connections": hb.get("doc_count", 0),
                    "bytes": int(hb.get("bytes", {}).get("value", 0) or 0),
                    "destinations": int(
                        hb.get("destinations", {}).get("value", 0) or 0
                    ),
                }
            )

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
        based on device category. Flags unexpected ports and hardcoded DNS
        (encryption is reported once, by the privacy report).

        Returns dict with 'devices' list.
        """
        # Auto-discover IoT devices from Arkime OUI data
        self._discover_iot_devices_from_arkime(from_ts, to_ts, excluded_ips)

        devices = self._iot_devices
        if not devices:
            return {"devices": []}

        excluded = build_excluded_ips_filter(excluded_ips or [])
        macs = list(devices.keys())

        # OLD CODE START — 2026-11-01: only fed the unencrypted finding removed below
        # # Batch query connection stats (includes dest_ports)
        # conn_stats = self._query_conn_stats_batch(macs, from_ts, to_ts, excluded)
        # OLD CODE END

        # Query per-device port usage with connection counts
        port_detail = self._query_port_detail_batch(macs, from_ts, to_ts, excluded)

        # Query for hardcoded DNS (destination port 53 to non-standard DNS servers)
        hardcoded_dns = self._query_hardcoded_dns_batch(macs, from_ts, to_ts, excluded)

        device_results: list[dict[str, Any]] = []
        for mac, dev_info in devices.items():
            category = self._categorize_device(dev_info)
            profile = self._protocol_profiles.get(
                category, self._protocol_profiles.get("default", {})
            )
            expected_ports = set(
                profile.get("expected_ports", [80, 443, 53, 123, 5353, 1900])
            )
            category_label = profile.get("label", "Unknown")

            # OLD CODE START — 2026-11-01: conn stats no longer queried here
            # cs = conn_stats.get(mac, {})
            # OLD CODE END
            pd = port_detail.get(mac, {})
            hd = hardcoded_dns.get(mac, [])

            findings: list[dict[str, Any]] = []

            # Check for unexpected ports
            actual_ports = pd.keys() if pd else set()
            for port in actual_ports:
                if port not in expected_ports:
                    count = pd[port]
                    severity = (
                        "high" if port in (22, 23, 445, 139, 3389, 5900) else "medium"
                    )
                    findings.append(
                        {
                            "type": "unexpected_port",
                            "severity": severity,
                            "port": port,
                            "connection_count": count,
                            "description": (
                                f"Uses port {port} which is not expected for "
                                f"a {category_label.lower()}"
                            ),
                        }
                    )

            # OLD CODE START — 2026-11-01: duplicated the findings feed's "has only N%
            # encrypted connections", which /iot builds from the privacy report's
            # encryption_ratio; the same fact was listed twice per device.
            # # Check for unencrypted external connections
            # total_conns = cs.get("total_connections", 0)
            # encrypted_conns = cs.get("encrypted_connections", 0)
            # unencrypted = total_conns - encrypted_conns
            # if total_conns > 0 and unencrypted > 0:
            #     ratio = encrypted_conns / total_conns
            #     if ratio < 0.9:
            #         findings.append(
            #             {
            #                 "type": "unencrypted_traffic",
            #                 "severity": "high" if ratio < 0.5 else "medium",
            #                 "port": 0,
            #                 "connection_count": unencrypted,
            #                 "description": (
            #                     f"{int((1 - ratio) * 100)}% of connections are unencrypted "
            #                     f"({unencrypted} of {total_conns})"
            #                 ),
            #             }
            #         )
            # OLD CODE END

            # Check for hardcoded DNS
            for dns_entry in hd:
                findings.append(
                    {
                        "type": "hardcoded_dns",
                        "severity": "medium",
                        "port": 53,
                        "connection_count": dns_entry.get("count", 0),
                        "description": (
                            f"Sends DNS queries directly to {dns_entry['ip']} "
                            f"instead of using network DNS"
                        ),
                    }
                )

            device_results.append(
                {
                    "mac": mac,
                    "name": dev_info.get("hostname")
                    or dev_info.get("manufacturer", "Unknown"),
                    "category": category,
                    "findings": findings,
                    "violation_count": len(findings),
                    "compliant": len(findings) == 0,
                }
            )

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
                CONN_RECORDS,
                {"terms": {"source.mac": mac_terms}},
            ],
            "must_not": [*excluded, *LOCAL_CHATTER_EXCLUSION],
        }
        # OLD CODE START — 2026-11-01: ICMP type/code showed up as "Uses port 0/3"
        # if excluded:
        #     bool_clause["must_not"] = excluded
        # OLD CODE END

        # OLD CODE START — #96: top 200 ports per device; a quiet telnet/SMB port fell off
        # query = {
        #     "size": 0,
        #     "query": {"bool": bool_clause},
        #     "aggs": {
        #         "by_mac": {
        #             "terms": {"field": "source.mac", "size": len(macs) * 2},
        #             "aggs": {
        #                 "ports": {"terms": {"field": "destination.port", "size": 200}},
        #             },
        #         }
        #     },
        # }
        #
        # try:
        #     result = self._client.search(index=NETWORK_INDEX, body=query)
        # except Exception as exc:
        #     logger.error("Port detail query failed: %s", exc)
        #     return {}
        #
        # out: dict[str, dict[int, int]] = {}
        # for bucket in (
        #     result.get("aggregations", {}).get("by_mac", {}).get("buckets", [])
        # ):
        #     raw_mac = bucket["key"].upper()
        #     port_map: dict[int, int] = {}
        #     for pb in bucket.get("ports", {}).get("buckets", []):
        #         port_map[pb["key"]] = pb.get("doc_count", 0)
        #     out[raw_mac] = port_map
        #
        # return out
        # OLD CODE END
        try:
            return self._counts_by_mac({"bool": bool_clause}, "destination.port")
        except Exception as exc:
            logger.error("Port detail query failed: %s", exc)
            # OLD CODE START — #96: the protocol audit read no ports for every device
            # return {}
            # OLD CODE END
            raise

    def _counts_by_mac(self, query: dict, field: str) -> dict[str, dict[Any, int]]:
        """Documents per value of `field` for each source MAC in `query`: every value,
        busiest first (ties in value order, as a terms aggregation lists them)."""
        buckets, complete = all_buckets(
            self._client,
            NETWORK_INDEX,
            query,
            [
                {"mac": {"terms": {"field": "source.mac"}}},
                {"value": {"terms": {"field": field}}},
            ],
        )
        if not complete:
            logger.warning("%s per device stopped at %d pairs", field, len(buckets))
        counts: dict[str, dict[Any, int]] = {}
        for b in buckets:
            per_mac = counts.setdefault(b["key"]["mac"].upper(), {})
            value = b["key"]["value"]
            per_mac[value] = per_mac.get(value, 0) + b.get("doc_count", 0)
        return {
            mac: dict(sorted(c.items(), key=lambda kv: kv[1], reverse=True))
            for mac, c in counts.items()
        }

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
            "8.8.8.8",
            "8.8.4.4",  # Google DNS
            "1.1.1.1",
            "1.0.0.1",  # Cloudflare DNS
            "208.67.222.222",
            "208.67.220.220",  # OpenDNS
            "9.9.9.9",  # Quad9
        ]

        mac_terms = []
        for mac in macs:
            mac_terms.extend([mac, mac.lower()])

        bool_clause: dict = {
            "filter": [
                _time_range_filter(from_ts, to_ts),
                CONN_RECORDS,
                {"terms": {"source.mac": mac_terms}},
                {"term": {"destination.port": 53}},
                {"terms": {"destination.ip": well_known_dns}},
            ]
        }
        if excluded:
            bool_clause["must_not"] = excluded

        query = {
            "size": 0,
            "query": {"bool": bool_clause},
            "aggs": {
                "by_mac": {
                    "terms": {"field": "source.mac", "size": len(macs) * 2},
                    "aggs": {
                        "dns_servers": {
                            "terms": {"field": "destination.ip", "size": 10}
                        },
                    },
                }
            },
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except Exception as exc:
            logger.error("Hardcoded DNS query failed: %s", exc)
            # OLD CODE START — #96: read as "no device bypasses your DNS"
            # return {}
            # OLD CODE END
            raise

        out: dict[str, list[dict[str, Any]]] = {}
        for bucket in (
            result.get("aggregations", {}).get("by_mac", {}).get("buckets", [])
        ):
            raw_mac = bucket["key"].upper()
            dns_list: list[dict[str, Any]] = []
            for db in bucket.get("dns_servers", {}).get("buckets", []):
                dns_list.append(
                    {
                        "ip": db["key"],
                        "count": db.get("doc_count", 0),
                    }
                )
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
        # Auto-discover IoT devices from Arkime OUI data
        self._discover_iot_devices_from_arkime(from_ts, to_ts, excluded_ips)

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
        # OLD CODE START — iot_macs was assigned but never used (F841)
        # iot_macs = set(macs)
        # OLD CODE END
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
                CONN_RECORDS,
                {"terms": {"source.mac": mac_terms}},
                # Destination is RFC1918 (internal) — use script filter
                {
                    "script": {
                        "script": {
                            "source": """
                                def ip = doc['destination.ip'].size() > 0 ? doc['destination.ip'].value : '';
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
            ],
            # OLD CODE START — 2026-11-01: port-only exclusion also hid TCP 53/123 and ICMP
            # sweeps to LAN hosts (security review); pings are now a low-risk signal
            # "must_not": [*excluded, *LOCAL_CHATTER_EXCLUSION],
            # OLD CODE END
            # UDP DNS/DHCP/NTP/discovery to a LAN server is expected, not lateral movement
            "must_not": [*excluded, *ISOLATION_NOISE_EXCLUSION],
        }
        # OLD CODE START — 2026-11-01: flagged DNS/DHCP to the gateway as an isolation risk
        # if excluded:
        #     bool_clause["must_not"] = excluded
        # OLD CODE END

        # OLD CODE START — #96: 50 LAN hosts per device and 20 ports per pair; a pair past
        # the 50th host or a sweep's quiet 445 dropped out, so risk and score read too low
        # query = {
        #     "size": 0,
        #     "query": {"bool": bool_clause},
        #     "aggs": {
        #         "by_source_mac": {
        #             "terms": {"field": "source.mac", "size": len(macs) * 2},
        #             "aggs": {
        #                 "by_dest_ip": {
        #                     "terms": {"field": "destination.ip", "size": 50},
        #                     "aggs": {
        #                         # Zeek stores the ICMP code in destination.port; keep it out
        #                         "not_icmp": {
        #                             "filter": {
        #                                 "bool": {
        #                                     "must_not": [
        #                                         {
        #                                             "terms": {
        #                                                 "network.transport": ICMP_TRANSPORTS
        #                                             }
        #                                         }
        #                                     ]
        #                                 }
        #                             },
        #                             "aggs": {
        #                                 "ports": {
        #                                     "terms": {
        #                                         "field": "destination.port",
        #                                         "size": 20,
        #                                     }
        #                                 }
        #                             },
        #                         },
        #                         "source_ip": {
        #                             "terms": {"field": "source.ip", "size": 1}
        #                         },
        #                     },
        #                 },
        #             },
        #         }
        #     },
        # }
        #
        # try:
        #     result = self._client.search(index=NETWORK_INDEX, body=query)
        # except Exception as exc:
        #     logger.error("Network isolation query failed: %s", exc)
        #     return {
        #         "segmentation_score": 100,
        #         "segmentation_grade": "A",
        #         "pairs": [],
        #         "recommendation": "Could not analyze network isolation.",
        #     }
        #
        # pairs: list[dict[str, Any]] = []
        # for mac_bucket in (
        #     result.get("aggregations", {}).get("by_source_mac", {}).get("buckets", [])
        # ):
        #     raw_mac = mac_bucket["key"].upper()
        #     dev_info = devices.get(raw_mac, {})
        #     dev_name = dev_info.get("hostname") or dev_info.get(
        #         "manufacturer", "Unknown"
        #     )
        #
        #     for dest_bucket in mac_bucket.get("by_dest_ip", {}).get("buckets", []):
        #         dest_ip = dest_bucket["key"]
        #
        #         # Skip if destination is also an IoT device
        #         if dest_ip in iot_ips:
        #             continue
        #
        #         not_icmp = dest_bucket.get("not_icmp", {})
        #         ports = [
        #             pb["key"] for pb in not_icmp.get("ports", {}).get("buckets", [])
        #         ]
        #         conn_count = dest_bucket.get("doc_count", 0)
        #         pinged = conn_count > not_icmp.get("doc_count", 0)
        #
        #         # Get source IP
        #         src_ip_buckets = dest_bucket.get("source_ip", {}).get("buckets", [])
        #         src_ip = src_ip_buckets[0]["key"] if src_ip_buckets else ""
        #
        #         # Classify risk based on ports
        #         risk = self._classify_isolation_risk(ports)
        #
        #         # Build description
        #         port_names = self._port_names(ports) if ports else ""
        #         if pinged:
        #             # ping-only pairs get no ports, so they classify as low risk
        #             port_names = f"{port_names}, ping" if port_names else "ping (ICMP)"
        #         desc = f"{dev_name} can reach {dest_ip} via {port_names}"
        #
        #         pairs.append(
        #             {
        #                 "iot_device": {
        #                     "mac": raw_mac,
        #                     "name": dev_name,
        #                     "ip": src_ip,
        #                 },
        #                 "internal_target": {
        #                     "ip": dest_ip,
        #                     "hostname": None,  # Would need reverse DNS
        #                 },
        #                 "risk": risk,
        #                 "connection_count": conn_count,
        #                 "ports": ports,
        #                 "description": desc,
        #             }
        #         )
        # OLD CODE END
        try:
            buckets, complete = all_buckets(
                self._client,
                NETWORK_INDEX,
                {"bool": bool_clause},
                [
                    {"mac": {"terms": {"field": "source.mac"}}},
                    {"dest": {"terms": {"field": "destination.ip"}}},
                ],
                aggs=ISOLATION_PAIR_AGGS,
            )
        except Exception as exc:
            logger.error("Network isolation query failed: %s", exc)
            # OLD CODE START — #96: a failure scored the network 100 / grade A
            # return {
            #     "segmentation_score": 100,
            #     "segmentation_grade": "A",
            #     "pairs": [],
            #     "recommendation": "Could not analyze network isolation.",
            # }
            # OLD CODE END
            raise
        if not complete:
            logger.warning("Network isolation stopped at %d pairs", len(buckets))

        # A destination that is also an IoT device is not an isolation finding
        pairs = [
            self._isolation_pair(b, devices)
            for b in buckets
            if b["key"]["dest"] not in iot_ips
        ]

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
        iot_reaching_workstations = len(
            set(
                p["iot_device"]["mac"]
                for p in pairs
                if p["risk"] in ("high", "critical")
            )
        )
        if not pairs:
            recommendation = "Your IoT devices are well-isolated from internal hosts."
        elif all(p["risk"] == "low" for p in pairs):
            recommendation = (
                "Only pings from IoT devices to internal hosts were seen. "
                "That is usually a connectivity check, not a risk."
            )
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
        # OLD CODE START — #96: pairs arrived busiest first from terms; composite pages
        # them in key order, so the busiest-first tiebreak is now explicit
        # pairs.sort(key=lambda p: risk_order.get(p["risk"], 99))
        # OLD CODE END
        pairs.sort(
            key=lambda p: (risk_order.get(p["risk"], 99), -p["connection_count"])
        )

        return {
            "segmentation_score": score,
            "segmentation_grade": grade,
            "pairs": pairs,
            "recommendation": recommendation,
        }

    def _isolation_pair(self, bucket: dict, devices: dict) -> dict[str, Any]:
        """One IoT-device-to-LAN-host pair from a (mac, dest) composite bucket."""
        raw_mac = bucket["key"]["mac"].upper()
        dest_ip = bucket["key"]["dest"]
        dev_info = devices.get(raw_mac, {})
        dev_name = dev_info.get("hostname") or dev_info.get("manufacturer", "Unknown")

        not_icmp = bucket.get("not_icmp", {})
        top = [pb["key"] for pb in not_icmp.get("ports", {}).get("buckets", [])]
        risky = not_icmp.get("risky", {}).get("ports", {}).get("buckets", [])
        ports = [*top, *(pb["key"] for pb in risky if pb["key"] not in top)]
        conn_count = bucket.get("doc_count", 0)
        pinged = conn_count > not_icmp.get("doc_count", 0)

        src_ip_buckets = bucket.get("source_ip", {}).get("buckets", [])
        src_ip = src_ip_buckets[0]["key"] if src_ip_buckets else ""

        port_count = not_icmp.get("port_count", {}).get("value")
        port_names = self._port_names(ports, port_count) if ports else ""
        if pinged:
            # ping-only pairs get no ports, so they classify as low risk
            port_names = f"{port_names}, ping" if port_names else "ping (ICMP)"

        return {
            "iot_device": {"mac": raw_mac, "name": dev_name, "ip": src_ip},
            "internal_target": {
                "ip": dest_ip,
                "hostname": None,  # Would need reverse DNS
            },
            "risk": self._classify_isolation_risk(ports),
            "connection_count": conn_count,
            "ports": ports,
            "description": f"{dev_name} can reach {dest_ip} via {port_names}",
        }

    @staticmethod
    def _classify_isolation_risk(ports: list[int]) -> str:
        """Classify the risk level of IoT-to-internal communication."""
        # OLD CODE START — #96: now module constants, shared with the isolation query
        # critical_ports = {445, 139, 3389, 5900, 22, 23}  # SMB, RDP, VNC, SSH, Telnet
        # high_ports = {80, 8080, 8443, 5000, 9090}  # Web services, management
        # OLD CODE END
        critical_ports = set(ISOLATION_CRITICAL_PORTS)
        high_ports = set(ISOLATION_HIGH_PORTS)
        if any(p in critical_ports for p in ports):
            return "critical"
        if any(p in high_ports for p in ports):
            return "high"
        if ports:
            return "medium"
        return "low"

    @staticmethod
    def _port_names(ports: list[int], total: int | None = None) -> str:
        """Convert a port list to human-readable names; `total` is every port used."""
        names = {
            22: "SSH",
            23: "Telnet",
            53: "DNS",
            80: "HTTP",
            139: "NetBIOS",
            443: "HTTPS",
            445: "SMB",
            3389: "RDP",
            5900: "VNC",
            8080: "HTTP-Alt",
            8443: "HTTPS-Alt",
        }
        parts = []
        for p in ports[:5]:  # Show first 5
            name = names.get(p, str(p))
            parts.append(name)
        # OLD CODE START — #96: "+N more" counted the listed ports, at most 20 + the risky
        # if len(ports) > 5:
        #     parts.append(f"+{len(ports) - 5} more")
        # OLD CODE END
        port_count = max(len(ports), total or 0)
        if port_count > 5:
            parts.append(f"+{port_count - 5} more")
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
        # Auto-discover IoT devices from Arkime OUI data
        self._discover_iot_devices_from_arkime(from_ts, to_ts, excluded_ips)

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
            trust_scores: list[int | None] = []
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
                    mac,
                    cs,
                    ds,
                    baseline,
                    expected_ports,
                )
                score_result = self._scorer.score_device(stats)
                trust_scores.append(score_result["score"])
                # OLD CODE START — NET-158: every device's pillar, scored or not
                # privacy_scores.append(score_result["privacy_score"])
                # OLD CODE END
                if score_result["score"] is not None:
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
                cat_expected = set(
                    profile.get("expected_ports", [80, 443, 53, 123, 5353, 1900])
                )
                for port in pd:
                    if port not in cat_expected:
                        total_violations += 1

            # OLD CODE START — NET-158: an arithmetic mean over every device (unscored ones
            # too), 0 for none, and 100% encrypted with no eligible traffic
            # avg_trust = (
            #     int(round(sum(trust_scores) / len(trust_scores))) if trust_scores else 0
            # )
            # avg_trust_grade = self._scorer.score_to_grade(avg_trust)
            # avg_privacy = (
            #     int(round(sum(privacy_scores) / len(privacy_scores)))
            #     if privacy_scores
            #     else 0
            # )
            # avg_privacy_grade = self._scorer.score_to_grade(avg_privacy)
            # encryption_pct = (
            #     int(round(total_encrypted / total_conns * 100))
            #     if total_conns > 0
            #     else 100
            # )
            # OLD CODE END
            # The fleet rule: harmonic mean over the scored devices; none scored, no score
            avg_trust = self._scorer.compute_fleet_score(trust_scores)
            avg_trust_grade = self._scorer.score_to_grade(avg_trust)
            avg_privacy = (
                int(round(sum(privacy_scores) / len(privacy_scores)))
                if privacy_scores
                else None
            )
            avg_privacy_grade = self._scorer.score_to_grade(avg_privacy)
            encryption_pct = (
                int(round(total_encrypted / total_conns * 100))
                if total_conns > 0
                else None
            )

            manufacturers.append(
                {
                    "name": mfg_name,
                    "device_count": device_count,
                    "scored_device_count": sum(s is not None for s in trust_scores),
                    "avg_trust_score": avg_trust,
                    "avg_trust_grade": avg_trust_grade,
                    "avg_privacy_grade": avg_privacy_grade,
                    "encryption_pct": encryption_pct,
                    "total_tracker_domains": total_tracker_domains,
                    "total_violations": total_violations,
                }
            )

        # Sort by worst trust score first; unscored last
        # OLD CODE START — NET-158: scores can be None now
        # manufacturers.sort(key=lambda m: m["avg_trust_score"])
        # OLD CODE END
        manufacturers.sort(
            key=lambda m: (m["avg_trust_score"] is None, m["avg_trust_score"] or 0)
        )
        return {"manufacturers": manufacturers}
