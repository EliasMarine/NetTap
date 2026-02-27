"""
Tests for daemon/services/nl_search.py

Covers all pattern types (time, IP, protocol, port, alert, device,
traffic, DNS), combined queries, edge cases, and suggestion generation.
All tests are self-contained with no external dependencies.
"""

import unittest

import sys
import os

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.nl_search import NLSearchParser


class TestTimePatterns(unittest.TestCase):
    """Tests for time range parsing."""

    def setUp(self):
        self.parser = NLSearchParser()

    def test_last_24_hours(self):
        """Parse 'last 24 hours'."""
        result = self.parser.parse("show connections in the last 24 hours")
        self.assertIn("@timestamp", str(result["query"]))
        self.assertIn("24 hours", result["description"])

    def test_last_7_days(self):
        """Parse 'last 7 days'."""
        result = self.parser.parse("alerts in the last 7 days")
        self.assertIn("7 days", result["description"])

    def test_last_2_weeks(self):
        """Parse 'last 2 weeks'."""
        result = self.parser.parse("traffic in the last 2 weeks")
        self.assertIn("2 weeks", result["description"])

    def test_last_30_minutes(self):
        """Parse 'last 30 minutes'."""
        result = self.parser.parse("connections in the last 30 minutes")
        self.assertIn("30 minutes", result["description"])

    def test_last_5_mins(self):
        """Parse 'last 5 mins' (abbreviated)."""
        result = self.parser.parse("connections in the last 5 mins")
        self.assertIn("5 mins", result["description"])

    def test_today(self):
        """Parse 'today'."""
        result = self.parser.parse("alerts today")
        self.assertIn("today", result["description"])

    def test_yesterday(self):
        """Parse 'yesterday'."""
        result = self.parser.parse("connections yesterday")
        self.assertIn("yesterday", result["description"])

    def test_default_time_range_when_no_time_specified(self):
        """Default to last 24 hours when no time is specified."""
        result = self.parser.parse("connections from 192.168.1.1")
        self.assertIn("last 24 hours", result["description"])


class TestIPPatterns(unittest.TestCase):
    """Tests for IP address parsing."""

    def setUp(self):
        self.parser = NLSearchParser()

    def test_from_ip(self):
        """Parse 'from <IP>'."""
        result = self.parser.parse("connections from 192.168.1.1")
        query_str = str(result["query"])
        self.assertIn("id.orig_h", query_str)
        self.assertIn("192.168.1.1", query_str)
        self.assertIn("source IP 192.168.1.1", result["description"])

    def test_to_ip(self):
        """Parse 'to <IP>'."""
        result = self.parser.parse("connections to 10.0.0.1")
        query_str = str(result["query"])
        self.assertIn("id.resp_h", query_str)
        self.assertIn("10.0.0.1", query_str)
        self.assertIn("destination IP 10.0.0.1", result["description"])

    def test_ip_keyword(self):
        """Parse 'ip <IP>'."""
        result = self.parser.parse("ip 172.16.0.1")
        query_str = str(result["query"])
        self.assertIn("172.16.0.1", query_str)
        self.assertIn("involving IP 172.16.0.1", result["description"])

    def test_address_keyword(self):
        """Parse 'address <IP>'."""
        result = self.parser.parse("address 8.8.8.8")
        query_str = str(result["query"])
        self.assertIn("8.8.8.8", query_str)
        self.assertIn("involving IP 8.8.8.8", result["description"])


class TestProtocolPatterns(unittest.TestCase):
    """Tests for protocol parsing."""

    def setUp(self):
        self.parser = NLSearchParser()

    def test_using_tcp(self):
        """Parse 'using tcp'."""
        result = self.parser.parse("connections using tcp")
        query_str = str(result["query"])
        self.assertIn("proto", query_str)
        self.assertIn("tcp", query_str)
        self.assertIn("protocol tcp", result["description"])

    def test_over_udp(self):
        """Parse 'over udp'."""
        result = self.parser.parse("traffic over udp")
        query_str = str(result["query"])
        self.assertIn("udp", query_str)

    def test_protocol_dns(self):
        """Parse 'protocol dns'."""
        result = self.parser.parse("traffic protocol dns")
        query_str = str(result["query"])
        self.assertIn("dns", query_str)

    def test_using_http(self):
        """Parse 'using http'."""
        result = self.parser.parse("connections using http")
        query_str = str(result["query"])
        self.assertIn("http", query_str)

    def test_using_ssh(self):
        """Parse 'using ssh'."""
        result = self.parser.parse("connections using ssh")
        self.assertIn("protocol ssh", result["description"])

    def test_protocol_case_insensitive(self):
        """Protocol matching should be case insensitive."""
        result = self.parser.parse("connections using TCP")
        query_str = str(result["query"])
        self.assertIn("tcp", query_str)


class TestPortPatterns(unittest.TestCase):
    """Tests for port parsing."""

    def setUp(self):
        self.parser = NLSearchParser()

    def test_port_80(self):
        """Parse 'port 80'."""
        result = self.parser.parse("traffic on port 80")
        query_str = str(result["query"])
        self.assertIn("80", query_str)
        self.assertIn("port 80", result["description"])

    def test_port_443(self):
        """Parse 'port 443'."""
        result = self.parser.parse("connections on port 443")
        query_str = str(result["query"])
        self.assertIn("443", query_str)

    def test_port_without_on(self):
        """Parse 'port 22' without 'on' prefix."""
        result = self.parser.parse("traffic port 22")
        query_str = str(result["query"])
        self.assertIn("22", query_str)


class TestAlertPatterns(unittest.TestCase):
    """Tests for alert-related parsing."""

    def setUp(self):
        self.parser = NLSearchParser()

    def test_high_severity_alerts(self):
        """Parse 'high severity alerts'."""
        result = self.parser.parse("high severity alerts")
        self.assertEqual(result["index"], "suricata-*")
        self.assertIn("high/critical severity alerts", result["description"])

    def test_critical_alerts(self):
        """Parse 'critical alerts'."""
        result = self.parser.parse("critical alerts")
        self.assertEqual(result["index"], "suricata-*")

    def test_alerts_from_ip(self):
        """Parse 'alerts from <IP>'."""
        result = self.parser.parse("alerts from 192.168.1.100")
        self.assertEqual(result["index"], "suricata-*")
        self.assertIn("192.168.1.100", str(result["query"]))
        self.assertIn("alerts involving 192.168.1.100", result["description"])

    def test_alerts_for_ip(self):
        """Parse 'alerts for <IP>'."""
        result = self.parser.parse("alerts for 10.0.0.5")
        self.assertEqual(result["index"], "suricata-*")
        self.assertIn("10.0.0.5", str(result["query"]))


class TestDevicePatterns(unittest.TestCase):
    """Tests for device/host parsing."""

    def setUp(self):
        self.parser = NLSearchParser()

    def test_device_ip(self):
        """Parse 'device <IP>'."""
        result = self.parser.parse("device 192.168.1.50")
        query_str = str(result["query"])
        self.assertIn("192.168.1.50", query_str)
        self.assertIn("device 192.168.1.50", result["description"])

    def test_host_ip(self):
        """Parse 'host <IP>'."""
        result = self.parser.parse("host 10.0.0.1")
        query_str = str(result["query"])
        self.assertIn("10.0.0.1", query_str)

    def test_host_hostname(self):
        """Parse 'host <hostname>'."""
        result = self.parser.parse("host router.local")
        query_str = str(result["query"])
        self.assertIn("router.local", query_str)
        self.assertIn("device/host router.local", result["description"])


class TestTrafficPatterns(unittest.TestCase):
    """Tests for traffic pattern parsing."""

    def setUp(self):
        self.parser = NLSearchParser()

    def test_large_traffic(self):
        """Parse 'large traffic'."""
        result = self.parser.parse("large traffic")
        query_str = str(result["query"])
        self.assertIn("orig_bytes", query_str)
        self.assertIn("large traffic transfers", result["description"])

    def test_heavy_uploads(self):
        """Parse 'heavy uploads'."""
        result = self.parser.parse("heavy uploads")
        query_str = str(result["query"])
        self.assertIn("orig_bytes", query_str)

    def test_big_transfers(self):
        """Parse 'big transfers'."""
        result = self.parser.parse("big transfers")
        self.assertIn("large traffic transfers", result["description"])


class TestDNSPatterns(unittest.TestCase):
    """Tests for DNS query parsing."""

    def setUp(self):
        self.parser = NLSearchParser()

    def test_dns_queries_for_domain(self):
        """Parse 'dns queries for example.com'."""
        result = self.parser.parse("dns queries for example.com")
        query_str = str(result["query"])
        self.assertIn("example.com", query_str)
        self.assertIn("DNS queries for example.com", result["description"])

    def test_dns_lookups_to_domain(self):
        """Parse 'dns lookups to google.com'."""
        result = self.parser.parse("dns lookups to google.com")
        query_str = str(result["query"])
        self.assertIn("google.com", query_str)


class TestCombinedQueries(unittest.TestCase):
    """Tests for combined natural language queries."""

    def setUp(self):
        self.parser = NLSearchParser()

    def test_source_ip_with_time(self):
        """Parse 'connections from 192.168.1.1 in the last 24 hours'."""
        result = self.parser.parse(
            "show connections from 192.168.1.1 in the last 24 hours"
        )
        query_str = str(result["query"])
        self.assertIn("192.168.1.1", query_str)
        self.assertIn("@timestamp", query_str)
        self.assertIn("source IP 192.168.1.1", result["description"])
        self.assertIn("24 hours", result["description"])

    def test_protocol_with_time(self):
        """Parse 'connections using tcp today'."""
        result = self.parser.parse("connections using tcp today")
        query_str = str(result["query"])
        self.assertIn("tcp", query_str)
        self.assertIn("today", result["description"])

    def test_port_with_ip(self):
        """Parse 'traffic on port 443 from 10.0.0.1'."""
        result = self.parser.parse("traffic on port 443 from 10.0.0.1")
        query_str = str(result["query"])
        self.assertIn("443", query_str)
        self.assertIn("10.0.0.1", query_str)

    def test_alert_with_time(self):
        """Parse 'high severity alerts in the last 1 hour'."""
        result = self.parser.parse("high severity alerts in the last 1 hour")
        self.assertEqual(result["index"], "suricata-*")
        self.assertIn("1 hour", result["description"])


class TestEdgeCases(unittest.TestCase):
    """Tests for edge cases and error handling."""

    def setUp(self):
        self.parser = NLSearchParser()

    def test_empty_query(self):
        """Empty query returns match_all."""
        result = self.parser.parse("")
        self.assertIn("match_all", str(result["query"]))
        self.assertEqual(result["index"], "zeek-*,suricata-*")
        self.assertEqual(result["size"], 50)

    def test_none_query(self):
        """None query handled gracefully."""
        result = self.parser.parse(None)
        self.assertIn("match_all", str(result["query"]))

    def test_whitespace_only_query(self):
        """Whitespace-only query returns match_all."""
        result = self.parser.parse("   ")
        self.assertIn("match_all", str(result["query"]))

    def test_unknown_pattern(self):
        """Query with no matching patterns defaults to 24h time range."""
        result = self.parser.parse("foobar baz quux")
        self.assertIn("last 24 hours", result["description"])

    def test_special_characters(self):
        """Query with special characters does not crash."""
        result = self.parser.parse("!@#$%^&*()")
        self.assertIsInstance(result, dict)
        self.assertIn("query", result)

    def test_result_has_required_keys(self):
        """All results have index, query, sort, size, description."""
        result = self.parser.parse("test query")
        self.assertIn("index", result)
        self.assertIn("query", result)
        self.assertIn("sort", result)
        self.assertIn("size", result)
        self.assertIn("description", result)

    def test_sort_is_timestamp_desc(self):
        """Default sort is @timestamp descending."""
        result = self.parser.parse("connections")
        self.assertEqual(result["sort"], [{"@timestamp": {"order": "desc"}}])

    def test_default_size_is_50(self):
        """Default size is 50."""
        result = self.parser.parse("connections")
        self.assertEqual(result["size"], 50)

    def test_very_long_query(self):
        """Very long query does not crash."""
        long_query = "connections " * 1000
        result = self.parser.parse(long_query)
        self.assertIsInstance(result, dict)


class TestSuggestions(unittest.TestCase):
    """Tests for search suggestions."""

    def setUp(self):
        self.parser = NLSearchParser()

    def test_empty_input_returns_defaults(self):
        """Empty input returns default suggestions."""
        suggestions = self.parser.suggest("")
        self.assertEqual(len(suggestions), 5)
        self.assertIsInstance(suggestions, list)

    def test_none_input_returns_defaults(self):
        """None input returns default suggestions."""
        suggestions = self.parser.suggest(None)
        self.assertEqual(len(suggestions), 5)

    def test_max_five_suggestions(self):
        """At most 5 suggestions are returned."""
        suggestions = self.parser.suggest("a")
        self.assertLessEqual(len(suggestions), 5)

    def test_alert_keyword_suggestions(self):
        """Typing 'alert' returns alert-related suggestions."""
        suggestions = self.parser.suggest("alert")
        self.assertTrue(len(suggestions) > 0)
        self.assertTrue(any("alert" in s.lower() for s in suggestions))

    def test_dns_keyword_suggestions(self):
        """Typing 'dns' returns DNS-related suggestions."""
        suggestions = self.parser.suggest("dns")
        self.assertTrue(len(suggestions) > 0)
        self.assertTrue(any("dns" in s.lower() for s in suggestions))

    def test_traffic_keyword_suggestions(self):
        """Typing 'traffic' returns traffic-related suggestions."""
        suggestions = self.parser.suggest("traffic")
        self.assertTrue(len(suggestions) > 0)
        self.assertTrue(any("traffic" in s.lower() for s in suggestions))

    def test_conn_keyword_suggestions(self):
        """Typing 'conn' returns connection-related suggestions."""
        suggestions = self.parser.suggest("conn")
        self.assertTrue(len(suggestions) > 0)

    def test_port_keyword_suggestions(self):
        """Typing 'port' returns port-related suggestions."""
        suggestions = self.parser.suggest("port")
        self.assertTrue(any("port" in s.lower() for s in suggestions))

    def test_suggestions_are_strings(self):
        """All suggestions should be strings."""
        suggestions = self.parser.suggest("test")
        for s in suggestions:
            self.assertIsInstance(s, str)

    def test_suggestions_no_duplicates(self):
        """Suggestions should not contain duplicates."""
        suggestions = self.parser.suggest("conn")
        self.assertEqual(len(suggestions), len(set(suggestions)))


class TestParserInstantiation(unittest.TestCase):
    """Tests for parser creation and configuration."""

    def test_parser_creates_without_error(self):
        """NLSearchParser can be instantiated."""
        parser = NLSearchParser()
        self.assertIsInstance(parser, NLSearchParser)

    def test_compiled_patterns_populated(self):
        """Compiled patterns should be populated after init."""
        parser = NLSearchParser()
        self.assertTrue(len(parser._COMPILED_PATTERNS) > 0)

    def test_patterns_match_count(self):
        """Number of compiled patterns matches PATTERNS list."""
        parser = NLSearchParser()
        self.assertEqual(len(parser._COMPILED_PATTERNS), len(parser.PATTERNS))


if __name__ == "__main__":
    unittest.main()
