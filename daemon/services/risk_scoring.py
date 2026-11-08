"""
NetTap Device Risk Scoring Service

Computes a 0-100 risk score for each device from three factors (NET-209; the rules cited are
in Debugging/THREAT-SCORING.md):

1. Alerts (50 pts) -- distinct signatures in the device's own traffic, by severity
2. Connection anomaly (25 pts) -- connections opened vs the device's own usual day
3. Upload spike (25 pts) -- bytes sent to the internet vs the device's own usual day

The two volume factors score only alongside a high or critical alert in the device's own traffic.

Risk levels:
    0-24:  low
    25-49: medium
    50-74: high
    75-100: critical
"""

# OLD CODE START — NET-209: five factors, of which external share, port lists and the upload ratio
# have no published basis as threat signals (THREAT-SCORING.md rules 11, 12, 14)
# """
# NetTap Device Risk Scoring Service
#
# Computes a 0-100 risk score for each device on the network based on
# multiple weighted risk factors derived from network telemetry:
#
# 1. Alert Count (35 pts) -- More Suricata alerts = higher risk
# 2. Connection Volume Anomaly (20 pts) -- Unusual connection count vs network avg
# 3. External Connection Ratio (15 pts) -- High ratio of external connections
# 4. Suspicious Protocol Usage (15 pts) -- Use of unusual ports/protocols
# 5. Data Exfiltration Signal (15 pts) -- Unusually high upload vs download ratio
#
# Risk levels:
#     0-24:  low
#     25-49: medium
#     50-74: high
#     75-100: critical
# """
# OLD CODE END

import logging
from statistics import median
from typing import Any

logger = logging.getLogger("nettap.services.risk_scoring")

# OLD CODE START — NET-209: the five-factor scorer
# class RiskScorer:
#     """Computes per-device risk scores (0-100) from network telemetry."""
#
#     # Known suspicious ports commonly associated with malware, backdoors, etc.
#     SUSPICIOUS_PORTS = {4444, 5555, 6666, 8888, 9999, 31337, 12345, 65535}
#
#     # Common/safe ports that are expected in normal network traffic
#     SAFE_PORTS = {
#         80,
#         443,
#         53,
#         22,
#         21,
#         25,
#         110,
#         143,
#         993,
#         995,
#         587,
#         465,
#         8080,
#         8443,
#         3389,
#         5900,
#     }
#
#     # Local network services (DHCP, NTP, NetBIOS, SSDP, mDNS, LLMNR): never "unusual"
#     # (NET-158: ordinary LAN chatter scored 8 points as unusual ports)
#     LOCAL_SERVICE_PORTS = {67, 68, 123, 137, 138, 139, 1900, 5353, 5355}
#
#     # Weight / max points per factor
#     WEIGHT_ALERT_COUNT = 35
#     WEIGHT_CONNECTION_ANOMALY = 20
#     WEIGHT_EXTERNAL_RATIO = 15
#     WEIGHT_SUSPICIOUS_PORTS = 15
#     WEIGHT_DATA_EXFILTRATION = 15
#
#     def __init__(self) -> None:
#         pass
#
#     def score_device(self, device_stats: dict[str, Any]) -> dict[str, Any]:
#         """Compute risk score for a single device.
#
#         Args:
#             device_stats: Dictionary with the following keys:
#                 alert_count: int
#                 connection_count: int
#                 network_avg_connections: float
#                 network_stddev_connections: float
#                 external_connection_count: int
#                 total_connection_count: int
#                 ports_used: list[int]
#                 orig_bytes: int  (uploaded)
#                 resp_bytes: int  (downloaded)
#
#         Returns:
#             Dictionary with:
#                 score: int (0-100)
#                 level: str ('low', 'medium', 'high', 'critical')
#                 factors: list[dict] with {name, score, max, description}
#         """
#         factors: list[dict[str, Any]] = []
#
#         # Factor 1: Alert count
#         alert_points, alert_desc = self.score_alert_count(
#             device_stats.get("alert_count", 0)
#         )
#         factors.append(
#             {
#                 "name": "alert_count",
#                 "score": alert_points,
#                 "max": self.WEIGHT_ALERT_COUNT,
#                 "description": alert_desc,
#             }
#         )
#
#         # Factor 2: Connection volume anomaly
#         conn_points, conn_desc = self.score_connection_anomaly(
#             device_stats.get("connection_count", 0),
#             device_stats.get("network_avg_connections", 0.0),
#             device_stats.get("network_stddev_connections", 0.0),
#         )
#         factors.append(
#             {
#                 "name": "connection_anomaly",
#                 "score": conn_points,
#                 "max": self.WEIGHT_CONNECTION_ANOMALY,
#                 "description": conn_desc,
#             }
#         )
#
#         # Factor 3: External connection ratio
#         ext_points, ext_desc = self.score_external_ratio(
#             device_stats.get("external_connection_count", 0),
#             device_stats.get("total_connection_count", 0),
#         )
#         factors.append(
#             {
#                 "name": "external_ratio",
#                 "score": ext_points,
#                 "max": self.WEIGHT_EXTERNAL_RATIO,
#                 "description": ext_desc,
#             }
#         )
#
#         # Factor 4: Suspicious port usage
#         port_points, port_desc = self.score_suspicious_ports(
#             device_stats.get("ports_used", []),
#             device_stats.get("more_unusual_ports", False),
#         )
#         factors.append(
#             {
#                 "name": "suspicious_ports",
#                 "score": port_points,
#                 "max": self.WEIGHT_SUSPICIOUS_PORTS,
#                 "description": port_desc,
#             }
#         )
#
#         # Factor 5: Data exfiltration signal
#         exfil_points, exfil_desc = self.score_data_exfiltration(
#             device_stats.get("orig_bytes", 0),
#             device_stats.get("resp_bytes", 0),
#         )
#         factors.append(
#             {
#                 "name": "data_exfiltration",
#                 "score": exfil_points,
#                 "max": self.WEIGHT_DATA_EXFILTRATION,
#                 "description": exfil_desc,
#             }
#         )
#
#         total_score = sum(f["score"] for f in factors)
#         # Clamp to 0-100 range
#         total_score = max(0, min(100, total_score))
#
#         return {
#             "score": total_score,
#             "level": self.risk_level(total_score),
#             "factors": factors,
#         }
#
#     def score_alert_count(self, count: int) -> tuple[int, str]:
#         """Score based on Suricata alert count.
#
#         Returns:
#             (points, description) tuple.
#         """
#         if count <= 0:
#             return (0, "No alerts detected")
#         elif count <= 2:
#             return (10, f"{count} alert(s) detected")
#         elif count <= 5:
#             return (20, f"{count} alerts detected -- moderate concern")
#         elif count <= 10:
#             return (30, f"{count} alerts detected -- elevated risk")
#         else:
#             return (35, f"{count} alerts detected -- high alert volume")
#
#     def score_connection_anomaly(
#         self, count: int, avg: float, stddev: float
#     ) -> tuple[int, str]:
#         """Score based on connection volume deviation from network average.
#
#         Returns:
#             (points, description) tuple.
#         """
#         if stddev <= 0 or avg <= 0:
#             # Cannot compute deviation with zero/negative stddev or avg
#             return (0, "Insufficient network data for anomaly detection")
#
#         deviation = (count - avg) / stddev
#
#         if deviation <= 1.0:
#             return (0, f"Connection count within normal range ({count} conns)")
#         elif deviation <= 2.0:
#             return (
#                 10,
#                 f"Slightly elevated connection count ({count} conns, {deviation:.1f} stddev)",
#             )
#         elif deviation <= 3.0:
#             return (
#                 15,
#                 f"Elevated connection count ({count} conns, {deviation:.1f} stddev)",
#             )
#         else:
#             return (
#                 20,
#                 f"Anomalous connection volume ({count} conns, {deviation:.1f} stddev)",
#             )
#
#     def score_external_ratio(self, external: int, total: int) -> tuple[int, str]:
#         """Score based on the ratio of external to total connections.
#
#         Returns:
#             (points, description) tuple.
#         """
#         if total <= 0:
#             return (0, "No connections recorded")
#
#         ratio = external / total
#         pct = ratio * 100
#
#         if ratio < 0.30:
#             return (0, f"{pct:.0f}% external connections -- normal")
#         elif ratio < 0.60:
#             return (5, f"{pct:.0f}% external connections -- moderate")
#         elif ratio < 0.80:
#             return (10, f"{pct:.0f}% external connections -- elevated")
#         else:
#             return (15, f"{pct:.0f}% external connections -- high")
#
#     def score_suspicious_ports(
#         self, ports: list[int], more_unusual: bool = False
#     ) -> tuple[int, str]:
#         """Score based on suspicious port usage.
#
#         more_unusual: the device used more unusual ports than `ports` holds, so the
#         count is a lower bound (PR #192 review: the port read is bounded per device).
#
#         Returns:
#             (points, description) tuple.
#         """
#         if not ports:
#             return (0, "No port data available")
#
#         port_set = set(ports)
#         suspicious_found = port_set & self.SUSPICIOUS_PORTS
#         # OLD CODE START — NET-158: local services counted as unusual
#         # unusual_found = port_set - self.SAFE_PORTS - self.SUSPICIOUS_PORTS
#         # OLD CODE END
#         unusual_found = (
#             port_set
#             - self.SAFE_PORTS
#             - self.SUSPICIOUS_PORTS
#             - self.LOCAL_SERVICE_PORTS
#         )
#
#         if suspicious_found:
#             port_list = ", ".join(str(p) for p in sorted(suspicious_found))
#             return (15, f"Known suspicious ports used: {port_list}")
#         elif unusual_found:
#             count = len(unusual_found)
#             # OLD CODE START — PR #192 review: a bounded list's count read as exact
#             # return (8, f"{count} unusual port(s) detected")
#             # OLD CODE END
#             at_least = "At least " if more_unusual else ""
#             return (8, f"{at_least}{count} unusual port(s) detected")
#         else:
#             return (0, "Only common protocols/ports used")
#
#     def score_data_exfiltration(
#         self, orig_bytes: int, resp_bytes: int
#     ) -> tuple[int, str]:
#         """Score based on upload-to-download ratio (data exfiltration signal).
#
#         orig_bytes is the amount uploaded by the device.
#         resp_bytes is the amount downloaded by the device.
#
#         Returns:
#             (points, description) tuple.
#         """
#         total = orig_bytes + resp_bytes
#         if total <= 0:
#             return (0, "No traffic data available")
#
#         upload_ratio = orig_bytes / total
#         pct = upload_ratio * 100
#
#         if upload_ratio < 0.10:
#             return (0, f"Upload ratio {pct:.0f}% -- normal")
#         elif upload_ratio < 0.30:
#             return (5, f"Upload ratio {pct:.0f}% -- slightly elevated")
#         elif upload_ratio < 0.50:
#             return (10, f"Upload ratio {pct:.0f}% -- elevated, possible exfiltration")
#         else:
#             return (15, f"Upload ratio {pct:.0f}% -- high, potential data exfiltration")
# OLD CODE END


# Points per distinct own-traffic signature: one critical is High alone, policy and recon barely
# move it (rule 5: one signature on one host is one finding)
SIGNATURE_POINTS = {1: 50, 2: 25, 3: 5, 4: 1}
_SEVERITY_WORD = {1: "critical", 2: "high", 3: "medium", 4: "low"}
MIN_HISTORY_DAYS = 3  # rule 11: compare with the device's own normal, so it needs one
MIN_CONNECTIONS = 500  # rule 11: a floor, so a quiet device doubling is not an anomaly
UPLOAD_FLOOR = 100 * 1000**2  # rule 13: Firewalla's smallest abnormal-upload alarm
UPLOAD_LARGE = 1000**3  # rule 13: Malcolm/Splunk's 1 GB to the internet
SPIKE, BIG_SPIKE = 3, 5  # times the usual day (rule 11)


def _size(n: float) -> str:
    """Decimal units, as the rest of NetTap shows bytes (NET-166)."""
    for unit, scale in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if n >= scale:
            return f"{n / scale:.1f} {unit}"
    return f"{int(n)} B"


class RiskScorer:
    """Computes per-device risk scores (0-100) from the device's own alerts and history."""

    WEIGHT_ALERTS = 50
    WEIGHT_CONNECTION_ANOMALY = 25
    WEIGHT_UPLOAD_SPIKE = 25

    def score_device(self, stats: dict[str, Any]) -> dict[str, Any]:
        """Score one device.

        stats: signatures {signature: worst own severity 1-4}, alert_count, corroborated (an own
        high or critical alert that is not a reputation hit), connections, upload_bytes,
        window_days, and history: one {"connections", "upload_bytes"} per day before the window.
        """
        days = [
            d for d in stats.get("history", []) if d["connections"] or d["upload_bytes"]
        ]
        window_days = max(1.0, stats.get("window_days", 1.0))
        corroborated = stats.get("corroborated", False)
        factors = [
            self._factor(
                "alert_count",
                self.WEIGHT_ALERTS,
                *self.score_alerts(
                    stats.get("signatures", {}), stats.get("alert_count", 0)
                ),
            ),
            self._factor(
                "connection_anomaly",
                self.WEIGHT_CONNECTION_ANOMALY,
                *self.score_connection_anomaly(
                    stats.get("connections", 0),
                    [d["connections"] for d in days],
                    window_days,
                    corroborated,
                ),
            ),
            self._factor(
                "upload_spike",
                self.WEIGHT_UPLOAD_SPIKE,
                *self.score_upload_spike(
                    stats.get("upload_bytes", 0),
                    [d["upload_bytes"] for d in days],
                    window_days,
                    corroborated,
                ),
            ),
        ]
        total = min(100, sum(f["score"] for f in factors))
        return {"score": total, "level": self.risk_level(total), "factors": factors}

    @staticmethod
    def _factor(
        name: str, weight: int, points: int, description: str
    ) -> dict[str, Any]:
        return {
            "name": name,
            "score": points,
            "max": weight,
            "description": description,
        }

    def score_alerts(self, signatures: dict[str, int], events: int) -> tuple[int, str]:
        """Distinct signatures in the device's own traffic, each at its worst severity."""
        if not signatures:
            return (0, "No alerts in this device's own traffic")
        points = min(
            self.WEIGHT_ALERTS,
            sum(SIGNATURE_POINTS.get(s, 0) for s in signatures.values()),
        )
        worst = _SEVERITY_WORD.get(min(signatures.values()), "low")
        n = len(signatures)
        return (
            points,
            f"{n} signature{'s' if n != 1 else ''} in its own traffic "
            f"({events:,} alert{'s' if events != 1 else ''}), worst {worst}",
        )

    def score_connection_anomaly(
        self, count: int, usual_days: list[int], window_days: float, corroborated: bool
    ) -> tuple[int, str]:
        """Connections opened vs the device's median day (scaled to the window)."""
        if len(usual_days) < MIN_HISTORY_DAYS:
            return (
                0,
                f"{count:,} connections; not enough earlier days to compare with",
            )
        ratio = count / max(1.0, median(usual_days) * window_days)
        facts = f"{count:,} connections, {ratio:.1f}× its usual"
        points = 0
        if count >= MIN_CONNECTIONS:
            points = 25 if ratio >= BIG_SPIKE else 10 if ratio >= SPIKE else 0
        if points and not corroborated:
            return (0, f"{facts}, not scored without a high or critical alert")
        return (points, facts)

    def score_upload_spike(
        self, sent: int, usual_days: list[int], window_days: float, corroborated: bool
    ) -> tuple[int, str]:
        """Bytes sent to the internet vs the device's median day (scaled to the window)."""
        if len(usual_days) < MIN_HISTORY_DAYS:
            return (0, f"Sent {_size(sent)}; not enough earlier days to compare with")
        ratio = sent / max(1.0, median(usual_days) * window_days)
        facts = f"Sent {_size(sent)} to the internet, {ratio:.1f}× its usual"
        points = 0
        if sent >= UPLOAD_FLOOR and ratio >= SPIKE:
            points = 25 if sent >= UPLOAD_LARGE else 10
        if points and not corroborated:
            return (0, f"{facts}, not scored without a high or critical alert")
        return (points, facts)

    @staticmethod
    def risk_level(score: int) -> str:
        """Convert numeric score to risk level string.

        0-24:  'low'
        25-49: 'medium'
        50-74: 'high'
        75-100: 'critical'
        """
        if score < 0:
            return "low"
        elif score <= 24:
            return "low"
        elif score <= 49:
            return "medium"
        elif score <= 74:
            return "high"
        else:
            return "critical"
