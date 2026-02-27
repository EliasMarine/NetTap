"""
NetTap Device Risk Scoring Service

Computes a 0-100 risk score for each device on the network based on
multiple weighted risk factors derived from network telemetry:

1. Alert Count (35 pts) -- More Suricata alerts = higher risk
2. Connection Volume Anomaly (20 pts) -- Unusual connection count vs network avg
3. External Connection Ratio (15 pts) -- High ratio of external connections
4. Suspicious Protocol Usage (15 pts) -- Use of unusual ports/protocols
5. Data Exfiltration Signal (15 pts) -- Unusually high upload vs download ratio

Risk levels:
    0-24:  low
    25-49: medium
    50-74: high
    75-100: critical
"""

import logging
from typing import Any

logger = logging.getLogger("nettap.services.risk_scoring")


class RiskScorer:
    """Computes per-device risk scores (0-100) from network telemetry."""

    # Known suspicious ports commonly associated with malware, backdoors, etc.
    SUSPICIOUS_PORTS = {4444, 5555, 6666, 8888, 9999, 31337, 12345, 65535}

    # Common/safe ports that are expected in normal network traffic
    SAFE_PORTS = {
        80,
        443,
        53,
        22,
        21,
        25,
        110,
        143,
        993,
        995,
        587,
        465,
        8080,
        8443,
        3389,
        5900,
    }

    # Weight / max points per factor
    WEIGHT_ALERT_COUNT = 35
    WEIGHT_CONNECTION_ANOMALY = 20
    WEIGHT_EXTERNAL_RATIO = 15
    WEIGHT_SUSPICIOUS_PORTS = 15
    WEIGHT_DATA_EXFILTRATION = 15

    def __init__(self) -> None:
        pass

    def score_device(self, device_stats: dict[str, Any]) -> dict[str, Any]:
        """Compute risk score for a single device.

        Args:
            device_stats: Dictionary with the following keys:
                alert_count: int
                connection_count: int
                network_avg_connections: float
                network_stddev_connections: float
                external_connection_count: int
                total_connection_count: int
                ports_used: list[int]
                orig_bytes: int  (uploaded)
                resp_bytes: int  (downloaded)

        Returns:
            Dictionary with:
                score: int (0-100)
                level: str ('low', 'medium', 'high', 'critical')
                factors: list[dict] with {name, score, max, description}
        """
        factors: list[dict[str, Any]] = []

        # Factor 1: Alert count
        alert_points, alert_desc = self.score_alert_count(
            device_stats.get("alert_count", 0)
        )
        factors.append(
            {
                "name": "alert_count",
                "score": alert_points,
                "max": self.WEIGHT_ALERT_COUNT,
                "description": alert_desc,
            }
        )

        # Factor 2: Connection volume anomaly
        conn_points, conn_desc = self.score_connection_anomaly(
            device_stats.get("connection_count", 0),
            device_stats.get("network_avg_connections", 0.0),
            device_stats.get("network_stddev_connections", 0.0),
        )
        factors.append(
            {
                "name": "connection_anomaly",
                "score": conn_points,
                "max": self.WEIGHT_CONNECTION_ANOMALY,
                "description": conn_desc,
            }
        )

        # Factor 3: External connection ratio
        ext_points, ext_desc = self.score_external_ratio(
            device_stats.get("external_connection_count", 0),
            device_stats.get("total_connection_count", 0),
        )
        factors.append(
            {
                "name": "external_ratio",
                "score": ext_points,
                "max": self.WEIGHT_EXTERNAL_RATIO,
                "description": ext_desc,
            }
        )

        # Factor 4: Suspicious port usage
        port_points, port_desc = self.score_suspicious_ports(
            device_stats.get("ports_used", [])
        )
        factors.append(
            {
                "name": "suspicious_ports",
                "score": port_points,
                "max": self.WEIGHT_SUSPICIOUS_PORTS,
                "description": port_desc,
            }
        )

        # Factor 5: Data exfiltration signal
        exfil_points, exfil_desc = self.score_data_exfiltration(
            device_stats.get("orig_bytes", 0),
            device_stats.get("resp_bytes", 0),
        )
        factors.append(
            {
                "name": "data_exfiltration",
                "score": exfil_points,
                "max": self.WEIGHT_DATA_EXFILTRATION,
                "description": exfil_desc,
            }
        )

        total_score = sum(f["score"] for f in factors)
        # Clamp to 0-100 range
        total_score = max(0, min(100, total_score))

        return {
            "score": total_score,
            "level": self.risk_level(total_score),
            "factors": factors,
        }

    def score_alert_count(self, count: int) -> tuple[int, str]:
        """Score based on Suricata alert count.

        Returns:
            (points, description) tuple.
        """
        if count <= 0:
            return (0, "No alerts detected")
        elif count <= 2:
            return (10, f"{count} alert(s) detected")
        elif count <= 5:
            return (20, f"{count} alerts detected -- moderate concern")
        elif count <= 10:
            return (30, f"{count} alerts detected -- elevated risk")
        else:
            return (35, f"{count} alerts detected -- high alert volume")

    def score_connection_anomaly(
        self, count: int, avg: float, stddev: float
    ) -> tuple[int, str]:
        """Score based on connection volume deviation from network average.

        Returns:
            (points, description) tuple.
        """
        if stddev <= 0 or avg <= 0:
            # Cannot compute deviation with zero/negative stddev or avg
            return (0, "Insufficient network data for anomaly detection")

        deviation = (count - avg) / stddev

        if deviation <= 1.0:
            return (0, f"Connection count within normal range ({count} conns)")
        elif deviation <= 2.0:
            return (
                10,
                f"Slightly elevated connection count ({count} conns, {deviation:.1f} stddev)",
            )
        elif deviation <= 3.0:
            return (
                15,
                f"Elevated connection count ({count} conns, {deviation:.1f} stddev)",
            )
        else:
            return (
                20,
                f"Anomalous connection volume ({count} conns, {deviation:.1f} stddev)",
            )

    def score_external_ratio(self, external: int, total: int) -> tuple[int, str]:
        """Score based on the ratio of external to total connections.

        Returns:
            (points, description) tuple.
        """
        if total <= 0:
            return (0, "No connections recorded")

        ratio = external / total
        pct = ratio * 100

        if ratio < 0.30:
            return (0, f"{pct:.0f}% external connections -- normal")
        elif ratio < 0.60:
            return (5, f"{pct:.0f}% external connections -- moderate")
        elif ratio < 0.80:
            return (10, f"{pct:.0f}% external connections -- elevated")
        else:
            return (15, f"{pct:.0f}% external connections -- high")

    def score_suspicious_ports(self, ports: list[int]) -> tuple[int, str]:
        """Score based on suspicious port usage.

        Returns:
            (points, description) tuple.
        """
        if not ports:
            return (0, "No port data available")

        port_set = set(ports)
        suspicious_found = port_set & self.SUSPICIOUS_PORTS
        unusual_found = port_set - self.SAFE_PORTS - self.SUSPICIOUS_PORTS

        if suspicious_found:
            port_list = ", ".join(str(p) for p in sorted(suspicious_found))
            return (15, f"Known suspicious ports used: {port_list}")
        elif unusual_found:
            count = len(unusual_found)
            return (8, f"{count} unusual port(s) detected")
        else:
            return (0, "Only common protocols/ports used")

    def score_data_exfiltration(
        self, orig_bytes: int, resp_bytes: int
    ) -> tuple[int, str]:
        """Score based on upload-to-download ratio (data exfiltration signal).

        orig_bytes is the amount uploaded by the device.
        resp_bytes is the amount downloaded by the device.

        Returns:
            (points, description) tuple.
        """
        total = orig_bytes + resp_bytes
        if total <= 0:
            return (0, "No traffic data available")

        upload_ratio = orig_bytes / total
        pct = upload_ratio * 100

        if upload_ratio < 0.10:
            return (0, f"Upload ratio {pct:.0f}% -- normal")
        elif upload_ratio < 0.30:
            return (5, f"Upload ratio {pct:.0f}% -- slightly elevated")
        elif upload_ratio < 0.50:
            return (10, f"Upload ratio {pct:.0f}% -- elevated, possible exfiltration")
        else:
            return (15, f"Upload ratio {pct:.0f}% -- high, potential data exfiltration")

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
