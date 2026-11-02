"""Tests for the investigation service recommendation logic."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from services.investigation import _generate_recommendation, generate_threat_report


class TestGenerateRecommendation:
    """Tests for _generate_recommendation."""

    def test_generate_recommendation_critical(self):
        """severity 1 includes 'Isolate'."""
        alert = {"severity": 1, "category": "exploit"}
        result = _generate_recommendation(alert)
        assert "Isolate" in result

    def test_generate_recommendation_malware(self):
        """malware category mentions 'malware'."""
        alert = {"severity": 2, "category": "malware_c2"}
        result = _generate_recommendation(alert)
        assert "malware" in result.lower()

    def test_generate_recommendation_with_ti(self):
        """alert with threat_intel mentions 'block'."""
        alert = {
            "severity": 3,
            "category": "policy",
            "threat_intel": [{"label": "Abuse.ch Feodo"}],
        }
        result = _generate_recommendation(alert)
        assert "block" in result.lower()


def test_threat_report_kill_chains_match_the_summary():
    """#96: the report rebuilt kill chains from the top 200 groups only, so a chain whose
    alerts ranked lower showed in summary.kill_chains but not in the report's own list."""
    chain = {"source_ip": "192.168.1.66", "stages": [1, 3], "alert_count": 2, "alerts": []}
    summary = AsyncMock(return_value={"kill_chains": [chain]})
    with (
        patch("services.alert_intelligence.get_smart_alert_summary", summary),
        patch("services.alert_intelligence.get_smart_alerts", AsyncMock(return_value=[])),
        patch("services.threat_detection.detect_beaconing", return_value=[]),
        patch("services.threat_detection.detect_lateral_movement", return_value=[]),
        patch("services.threat_detection.analyze_dns_anomalies", return_value={}),
    ):
        report = asyncio.run(generate_threat_report(MagicMock(), "now-1h", "now"))

    assert report["kill_chains"] == report["summary"]["kill_chains"] == [chain]
