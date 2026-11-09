"""Tests for the investigation service recommendation logic."""

import asyncio
import threading
from unittest.mock import MagicMock, patch

from services.investigation import _generate_recommendation, generate_threat_report


class TestGenerateRecommendation:
    """Tests for _generate_recommendation."""

    # OLD CODE START — NET-228 (audit B-j): "IMMEDIATE: Isolate the source host" is gone
    # def test_generate_recommendation_critical(self):
    #     """severity 1 includes 'Isolate'."""
    #     alert = {"severity": 1, "category": "exploit"}
    #     result = _generate_recommendation(alert)
    #     assert "Isolate" in result
    # OLD CODE END

    def test_critical_says_check_first_and_a_match_is_not_proof(self):
        result = _generate_recommendation({"severity": 1, "category": "exploit"})
        assert result.startswith("Check this first: a critical-severity rule matched.")
        assert "not proof of compromise" in result
        assert "isolat" not in result.lower()
        assert "IMMEDIATE" not in result

    def test_names_the_lan_devices_without_saying_who_opened_it(self):
        """A LAN server answering an internet scanner is not "the source host" to isolate."""
        alert = {
            "severity": 2,
            "category": "exploit",
            "source_ip": "198.51.100.7",
            "findings": [
                {"device": "192.0.2.24", "own": False},
                {"device": "192.0.2.10", "own": True},
            ],
        }
        result = _generate_recommendation(alert)
        assert "These matches involve 192.0.2.10, 192.0.2.24: start there." in result
        assert "198.51.100.7" not in result
        assert "source" not in result.lower()

    def test_no_findings_names_no_device(self):
        result = _generate_recommendation({"severity": 2, "category": "exploit"})
        assert result == "Check this soon: a high-severity rule matched."

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
    chain = {
        "source_ip": "192.168.1.66",
        "stages": [1, 3],
        "alert_count": 2,
        "alerts": [],
    }
    summary = MagicMock(return_value={"kill_chains": [chain]})
    with (
        patch("services.alert_intelligence.get_smart_alert_summary", summary),
        patch(
            "services.alert_intelligence.get_smart_alerts", MagicMock(return_value=[])
        ),
        patch("services.threat_detection.detect_beaconing", return_value=([], True)),
        patch(
            "services.threat_detection.detect_lateral_movement", return_value=([], True)
        ),
        patch("services.threat_detection.analyze_dns_anomalies", return_value={}),
    ):
        report = asyncio.run(generate_threat_report(MagicMock(), "now-1h", "now"))

    assert report["kill_chains"] == report["summary"]["kill_chains"] == [chain]


def test_threat_report_names_failed_and_partial_checks():
    """#96: a failed detector returned [] and /threats said "No beaconing patterns detected"."""
    move = {"source_ip": "192.168.1.66", "destination_ip": "192.168.1.10", "port": 445}
    with (
        patch(
            "services.alert_intelligence.get_smart_alert_summary",
            MagicMock(return_value={}),
        ),
        patch(
            "services.alert_intelligence.get_smart_alerts", MagicMock(return_value=[])
        ),
        patch(
            "services.threat_detection.detect_beaconing",
            side_effect=ConnectionError("down"),
        ),
        patch(
            "services.threat_detection.detect_lateral_movement",
            return_value=([move], False),
        ),
        patch(
            "services.threat_detection.analyze_dns_anomalies",
            return_value={
                "dga_suspects": [{"domain": "x"}],
                "tunnel_suspects": [],
                "nxdomain_spikes": [],
                "suspicious_tlds": [],
                "complete": True,
            },
        ),
    ):
        report = asyncio.run(generate_threat_report(MagicMock(), "now-1h", "now"))

    assert report["failed_checks"] == ["beaconing"]
    assert report["incomplete_checks"] == ["lateral_movement"]
    assert report["lateral_movement"] == [move]
    assert report["dns_anomalies"]["dga_suspects"] == [{"domain": "x"}]
    assert "complete" not in report["dns_anomalies"]


def test_threat_report_runs_its_checks_side_by_side():
    """#139: the checks ran one after another, so the report took their sum (8-13 s on the G11)."""
    all_three = threading.Barrier(3, timeout=5)

    def check(result):
        def run(*_args, **_kwargs):
            all_three.wait()  # BrokenBarrierError unless all three run at once
            return result

        return run

    with (
        patch(
            "services.alert_intelligence.get_smart_alert_summary",
            MagicMock(return_value={}),
        ),
        patch(
            "services.alert_intelligence.get_smart_alerts", MagicMock(return_value=[])
        ),
        patch(
            "services.threat_detection.detect_beaconing",
            side_effect=check(([{"source_ip": "192.168.1.66"}], True)),
        ),
        patch(
            "services.threat_detection.detect_lateral_movement",
            side_effect=check(([], True)),
        ),
        patch(
            "services.threat_detection.analyze_dns_anomalies",
            side_effect=check({"complete": True}),
        ),
    ):
        report = asyncio.run(generate_threat_report(MagicMock(), "now-1h", "now"))

    assert report["failed_checks"] == []
    assert report["beaconing"] == [{"source_ip": "192.168.1.66"}]


def test_failed_investigation_is_a_failed_check_not_zero_counts():
    """#96: a failed section query left {"error": ...}, which the page showed as 0 connections."""
    critical = {
        "severity": 1,
        "signature": "ET MALWARE x",
        "source_ip": "192.168.1.66",
        "destination_ip": "203.0.113.9",
    }
    client = MagicMock()
    client.search.side_effect = ConnectionError("down")
    with (
        patch(
            "services.alert_intelligence.get_smart_alert_summary",
            MagicMock(return_value={}),
        ),
        patch(
            "services.alert_intelligence.get_smart_alerts",
            MagicMock(return_value=[critical]),
        ),
        patch("services.threat_detection.detect_beaconing", return_value=([], True)),
        patch(
            "services.threat_detection.detect_lateral_movement", return_value=([], True)
        ),
        patch(
            "services.threat_detection.analyze_dns_anomalies",
            return_value={"complete": True},
        ),
    ):
        report = asyncio.run(generate_threat_report(client, "now-1h", "now"))

    assert report["investigations"] == []
    assert report["failed_checks"] == ["investigations"]
