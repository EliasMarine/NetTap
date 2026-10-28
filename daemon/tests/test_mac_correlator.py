"""
Tests for the MACCorrelator service.

Covers: randomized MAC detection, behavioral fingerprinting,
merge suggestions, merge/undo, merge history persistence.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from services.mac_correlator import MACCorrelator, is_randomized_mac


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client():
    """Return a MagicMock OpenSearch client."""
    return MagicMock()


@pytest.fixture
def correlator(mock_client, tmp_path):
    """Return a MACCorrelator with a mocked client and temp merge file."""
    merge_file = str(tmp_path / "mac_merges.json")
    return MACCorrelator(client=mock_client, merge_file=merge_file)


# ---------------------------------------------------------------------------
# is_randomized_mac
# ---------------------------------------------------------------------------


class TestIsRandomizedMac:
    def test_randomized_mac(self):
        """Locally-administered bit set = randomized."""
        # 0x02 has bit 1 set
        assert is_randomized_mac("02:00:00:00:00:00") is True
        # 0x06 = 0b00000110, bit 1 set
        assert is_randomized_mac("06:ab:cd:ef:12:34") is True
        # 0xfa = 0b11111010, bit 1 set
        assert is_randomized_mac("fa:11:22:33:44:55") is True

    def test_real_mac(self):
        """No locally-administered bit = real hardware MAC."""
        # 0x00 has no bit 1
        assert is_randomized_mac("00:11:22:33:44:55") is False
        # 0xac = 0b10101100, bit 1 not set
        assert is_randomized_mac("ac:de:48:00:11:22") is False

    def test_invalid_mac(self):
        """Invalid MACs should return False, not crash."""
        assert is_randomized_mac("") is False
        assert is_randomized_mac("not-a-mac") is False
        assert is_randomized_mac("zz:00:00:00:00:00") is False


# ---------------------------------------------------------------------------
# Detect randomized MACs
# ---------------------------------------------------------------------------


class TestDetectRandomizedMacs:
    def test_finds_randomized_macs(self, correlator, mock_client):
        """Should filter out non-randomized MACs from aggregation results."""
        mock_client.search.return_value = {
            "aggregations": {
                "macs": {
                    "buckets": [
                        {
                            "key": "02:aa:bb:cc:dd:ee",  # randomized
                            "doc_count": 100,
                            "first_seen": {"value_as_string": "2026-03-01T00:00:00Z"},
                            "last_seen": {"value_as_string": "2026-03-08T00:00:00Z"},
                            "total_bytes": {"value": 50000},
                            "top_dests": {
                                "buckets": [
                                    {"key": "8.8.8.8", "doc_count": 50},
                                ]
                            },
                        },
                        {
                            "key": "00:11:22:33:44:55",  # real
                            "doc_count": 200,
                            "first_seen": {"value_as_string": "2026-03-01T00:00:00Z"},
                            "last_seen": {"value_as_string": "2026-03-08T00:00:00Z"},
                            "total_bytes": {"value": 100000},
                            "top_dests": {"buckets": []},
                        },
                    ]
                }
            }
        }

        result = correlator.detect_randomized_macs(
            "2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z"
        )

        assert len(result) == 1
        assert result[0]["mac"] == "02:aa:bb:cc:dd:ee"
        assert result[0]["connection_count"] == 100
        assert result[0]["total_bytes"] == 50000
        assert result[0]["top_destinations"] == ["8.8.8.8"]

    def test_empty_results(self, correlator, mock_client):
        """Should return empty list when no MACs found."""
        mock_client.search.return_value = {
            "aggregations": {"macs": {"buckets": []}}
        }

        result = correlator.detect_randomized_macs(
            "2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z"
        )
        assert result == []

    def test_opensearch_error(self, correlator, mock_client):
        """Should return empty list on OpenSearch error."""
        from opensearchpy import OpenSearchException

        mock_client.search.side_effect = OpenSearchException("connection error")

        result = correlator.detect_randomized_macs(
            "2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z"
        )
        assert result == []


# ---------------------------------------------------------------------------
# Behavioral fingerprinting
# ---------------------------------------------------------------------------


class TestBehavioralFingerprint:
    def test_builds_fingerprint(self, correlator, mock_client):
        """Should build a complete fingerprint from OpenSearch data."""
        mock_client.search.return_value = {
            "aggregations": {
                "dns_domains": {
                    "buckets": [
                        {"key": "google.com", "doc_count": 50},
                        {"key": "apple.com", "doc_count": 30},
                    ]
                },
                "dest_ips": {
                    "buckets": [
                        {"key": "8.8.8.8", "doc_count": 100},
                    ]
                },
                "ja3_hashes": {
                    "buckets": [
                        {"key": "abc123", "doc_count": 80},
                    ]
                },
                "hourly_activity": {
                    "buckets": [
                        {"key_as_string": "2026-03-08T10:00:00Z", "doc_count": 20},
                    ]
                },
                "total_orig_bytes": {"value": 5000},
                "total_resp_bytes": {"value": 10000},
                "total_orig_pkts": {"value": 100},
                "total_resp_pkts": {"value": 200},
            }
        }

        fp = correlator.get_behavioral_fingerprint(
            "02:aa:bb:cc:dd:ee",
            "2026-03-01T00:00:00Z",
            "2026-03-08T00:00:00Z",
        )

        assert fp["mac"] == "02:aa:bb:cc:dd:ee"
        assert fp["is_randomized"] is True
        assert len(fp["dns_patterns"]) == 2
        assert fp["dns_patterns"][0]["domain"] == "google.com"
        assert len(fp["tls_fingerprints"]) == 1
        assert fp["tls_fingerprints"][0]["ja3"] == "abc123"
        assert len(fp["destination_ips"]) == 1
        assert fp["traffic_profile"]["total_bytes"] == 15000
        assert fp["traffic_profile"]["avg_packet_size"] == 50.0  # 15000 / 300

    def test_empty_fingerprint(self, correlator, mock_client):
        """Should return empty fingerprint when no data exists."""
        mock_client.search.return_value = {"aggregations": {}}

        fp = correlator.get_behavioral_fingerprint(
            "02:aa:bb:cc:dd:ee",
            "2026-03-01T00:00:00Z",
            "2026-03-08T00:00:00Z",
        )

        assert fp["mac"] == "02:aa:bb:cc:dd:ee"
        assert fp["dns_patterns"] == []
        assert fp["tls_fingerprints"] == []
        assert fp["destination_ips"] == []


# ---------------------------------------------------------------------------
# Similarity computation
# ---------------------------------------------------------------------------


class TestSimilarity:
    def test_identical_fingerprints(self, correlator):
        """Identical fingerprints should have high similarity."""
        fp = {
            "dns_patterns": [{"domain": "google.com"}, {"domain": "apple.com"}],
            "tls_fingerprints": [{"ja3": "abc123"}],
            "destination_ips": [{"ip": "8.8.8.8"}, {"ip": "1.1.1.1"}],
            "traffic_profile": {"total_bytes": 10000},
        }

        score = correlator._compute_similarity(fp, fp)
        assert score == 1.0

    def test_completely_different(self, correlator):
        """Completely different fingerprints should have zero similarity."""
        fp_a = {
            "dns_patterns": [{"domain": "google.com"}],
            "tls_fingerprints": [{"ja3": "abc123"}],
            "destination_ips": [{"ip": "8.8.8.8"}],
            "traffic_profile": {"total_bytes": 10000},
        }
        fp_b = {
            "dns_patterns": [{"domain": "facebook.com"}],
            "tls_fingerprints": [{"ja3": "xyz789"}],
            "destination_ips": [{"ip": "1.1.1.1"}],
            "traffic_profile": {"total_bytes": 10000},
        }

        score = correlator._compute_similarity(fp_a, fp_b)
        # Only traffic volume matches, rest is 0
        assert score < 0.2

    def test_partial_overlap(self, correlator):
        """Partial overlap should give a medium similarity score."""
        fp_a = {
            "dns_patterns": [
                {"domain": "google.com"},
                {"domain": "apple.com"},
            ],
            "tls_fingerprints": [{"ja3": "abc123"}],
            "destination_ips": [{"ip": "8.8.8.8"}, {"ip": "1.1.1.1"}],
            "traffic_profile": {"total_bytes": 10000},
        }
        fp_b = {
            "dns_patterns": [
                {"domain": "google.com"},
                {"domain": "microsoft.com"},
            ],
            "tls_fingerprints": [{"ja3": "abc123"}],
            "destination_ips": [{"ip": "8.8.8.8"}, {"ip": "9.9.9.9"}],
            "traffic_profile": {"total_bytes": 8000},
        }

        score = correlator._compute_similarity(fp_a, fp_b)
        assert 0.3 < score < 0.9

    def test_empty_fingerprints(self, correlator):
        """Empty fingerprints should return 0."""
        fp = {
            "dns_patterns": [],
            "tls_fingerprints": [],
            "destination_ips": [],
            "traffic_profile": {"total_bytes": 0},
        }
        score = correlator._compute_similarity(fp, fp)
        assert score == 0.0


# ---------------------------------------------------------------------------
# Merge / undo
# ---------------------------------------------------------------------------


class TestMerge:
    def test_merge_devices(self, correlator):
        """Should create a merge record and persist it."""
        record = correlator.merge_devices(
            "02:aa:bb:cc:dd:ee", "00:11:22:33:44:55"
        )

        assert record["mac_randomized"] == "02:aa:bb:cc:dd:ee"
        assert record["mac_real"] == "00:11:22:33:44:55"
        assert record["status"] == "active"
        assert "id" in record
        assert "merged_at" in record

    def test_merge_history(self, correlator):
        """Should track all merges in history."""
        correlator.merge_devices("02:aa:bb:cc:dd:ee", "00:11:22:33:44:55")
        correlator.merge_devices("06:11:22:33:44:55", "00:66:77:88:99:aa")

        history = correlator.get_merge_history()
        assert len(history) == 2

    def test_undo_merge(self, correlator):
        """Should mark a merge as undone."""
        record = correlator.merge_devices(
            "02:aa:bb:cc:dd:ee", "00:11:22:33:44:55"
        )
        merge_id = record["id"]

        success = correlator.undo_merge(merge_id)
        assert success is True

        history = correlator.get_merge_history()
        undone = [h for h in history if h["id"] == merge_id]
        assert undone[0]["status"] == "undone"

    def test_undo_nonexistent(self, correlator):
        """Should return False for nonexistent merge ID."""
        assert correlator.undo_merge("nonexistent-id") is False

    def test_active_merges(self, correlator):
        """Should return only active merge mappings."""
        correlator.merge_devices("02:aa:bb:cc:dd:ee", "00:11:22:33:44:55")
        r2 = correlator.merge_devices("06:11:22:33:44:55", "00:66:77:88:99:aa")

        correlator.undo_merge(r2["id"])

        active = correlator.get_active_merges()
        assert len(active) == 1
        assert active["02:aa:bb:cc:dd:ee"] == "00:11:22:33:44:55"

    def test_persistence(self, tmp_path, mock_client):
        """Merge history should survive service restart."""
        merge_file = str(tmp_path / "mac_merges.json")
        c1 = MACCorrelator(client=mock_client, merge_file=merge_file)
        c1.merge_devices("02:aa:bb:cc:dd:ee", "00:11:22:33:44:55")

        # Create new instance — should load from file
        c2 = MACCorrelator(client=mock_client, merge_file=merge_file)
        history = c2.get_merge_history()
        assert len(history) == 1
        assert history[0]["mac_randomized"] == "02:aa:bb:cc:dd:ee"


# ---------------------------------------------------------------------------
# Merge suggestions
# ---------------------------------------------------------------------------


class TestMergeSuggestions:
    def test_no_randomized_macs(self, correlator, mock_client):
        """Should return empty list when no randomized MACs exist."""
        mock_client.search.return_value = {
            "aggregations": {"macs": {"buckets": []}}
        }

        suggestions = correlator.suggest_merges(
            "2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z"
        )
        assert suggestions == []

    def test_no_known_macs(self, correlator, mock_client):
        """Should return empty when all MACs are randomized."""
        # First call: detect_randomized_macs
        # Second call: all_macs_query (only randomized MACs)
        mock_client.search.side_effect = [
            {
                "aggregations": {
                    "macs": {
                        "buckets": [
                            {
                                "key": "02:aa:bb:cc:dd:ee",
                                "doc_count": 100,
                                "first_seen": {"value_as_string": "2026-03-01T00:00:00Z"},
                                "last_seen": {"value_as_string": "2026-03-08T00:00:00Z"},
                                "total_bytes": {"value": 5000},
                                "top_dests": {"buckets": []},
                            }
                        ]
                    }
                }
            },
            {
                "aggregations": {
                    "macs": {
                        "buckets": [
                            {"key": "02:aa:bb:cc:dd:ee", "doc_count": 100},
                        ]
                    }
                }
            },
        ]

        suggestions = correlator.suggest_merges(
            "2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z"
        )
        assert suggestions == []
