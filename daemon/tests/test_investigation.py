"""Tests for the investigation service recommendation logic."""

from services.investigation import _generate_recommendation


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
