"""
Tests for ASN-based traffic classification.

Validates classify_asn() maps ASN full strings (e.g. 'AS2906 Netflix Inc')
to the correct category keys, handles edge cases, and covers all expected
categories in ASN_CATEGORY_MAP.
"""

import os
import sys


# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.traffic_classifier import classify_asn, ASN_CATEGORY_MAP


class TestClassifyAsn:
    def test_netflix_is_streaming(self):
        assert classify_asn("AS2906 Netflix Inc") == "streaming"

    def test_google_is_streaming(self):
        assert classify_asn("AS15169 Google LLC") == "streaming"

    def test_microsoft_is_work(self):
        assert classify_asn("AS8075 Microsoft Corporation") == "work"

    def test_meta_is_social(self):
        assert classify_asn("AS32934 Meta Platforms, Inc.") == "social"

    def test_valve_is_gaming(self):
        assert classify_asn("AS32590 Valve Corporation") == "gaming"

    def test_amazon_is_cloud(self):
        assert classify_asn("AS16509 Amazon.com, Inc.") == "cloud"

    def test_cloudflare_is_security(self):
        assert classify_asn("AS13335 Cloudflare, Inc.") == "security"

    def test_unknown_asn_is_other(self):
        assert classify_asn("AS99999 Unknown ISP") == "other"

    def test_empty_string_is_other(self):
        assert classify_asn("") == "other"

    def test_none_is_other(self):
        assert classify_asn(None) == "other"

    def test_case_insensitive(self):
        assert classify_asn("AS2906 NETFLIX INC") == "streaming"

    def test_all_categories_have_at_least_one_asn(self):
        mapped_categories = set(ASN_CATEGORY_MAP.values())
        expected = {"streaming", "gaming", "social", "communication", "work",
                    "cloud", "shopping", "news", "security", "iot"}
        assert expected.issubset(mapped_categories)
