"""
NetTap Natural Language Search Parser

Converts natural language search queries into OpenSearch DSL queries.
Supports time ranges, IP filters, protocol filters, port filters,
alert severity queries, device lookups, traffic patterns, and DNS queries.

Examples:
    "show connections from 192.168.1.1 in the last 24 hours"
    "high severity alerts today"
    "dns queries for example.com yesterday"
    "large traffic on port 443 using tcp"
"""

import logging
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("nettap.services.nl_search")


class NLSearchParser:
    """Converts natural language search queries to OpenSearch DSL."""

    # Pattern mappings: natural language -> query components
    # Each tuple: (compiled regex, method name)
    PATTERNS = [
        # Time patterns
        (r'(?:in the )?last (\d+)\s*(hours?|days?|weeks?|minutes?|mins?)', '_parse_time_range'),
        (r'\btoday\b', '_parse_today'),
        (r'\byesterday\b', '_parse_yesterday'),
        # IP patterns
        (r'\bfrom\s+((?:\d{1,3}\.){3}\d{1,3})\b', '_parse_source_ip'),
        (r'\bto\s+((?:\d{1,3}\.){3}\d{1,3})\b', '_parse_dest_ip'),
        (r'(?:ip|address)\s+((?:\d{1,3}\.){3}\d{1,3})', '_parse_any_ip'),
        # Protocol patterns
        (r'(?:using |over |protocol )(tcp|udp|http|https|dns|ssh|smtp|tls)', '_parse_protocol'),
        # Port patterns
        (r'(?:on )?port\s+(\d+)', '_parse_port'),
        # Alert patterns
        (r'(?:high|critical)\s+(?:severity\s+)?alerts?', '_parse_high_alerts'),
        (r'alerts?\s+(?:from|for)\s+((?:\d{1,3}\.){3}\d{1,3})', '_parse_alert_ip'),
        # Device patterns
        (r'(?:device|host)\s+((?:\d{1,3}\.){3}\d{1,3}|[\w.-]+)', '_parse_device'),
        # Traffic patterns
        (r'(?:large|big|heavy)\s+(?:traffic|transfers?|uploads?)', '_parse_large_traffic'),
        (r'dns\s+(?:queries?|lookups?)\s+(?:for|to)\s+([\w.-]+)', '_parse_dns_query'),
    ]

    # Pre-compiled patterns for performance
    _COMPILED_PATTERNS: list[tuple[re.Pattern, str]] = []

    # Search suggestion templates
    SUGGESTIONS = [
        "show connections from {ip} in the last 24 hours",
        "high severity alerts today",
        "dns queries for {domain}",
        "traffic on port {port}",
        "connections using {protocol}",
        "large traffic in the last 7 days",
        "alerts from {ip} yesterday",
        "device {ip}",
        "connections to {ip}",
        "show all alerts in the last 1 hour",
    ]

    # Keyword -> suggestion mappings for partial input matching
    KEYWORD_SUGGESTIONS = {
        "conn": [
            "show connections from 192.168.1.1 in the last 24 hours",
            "connections using tcp",
            "connections to 10.0.0.1",
        ],
        "alert": [
            "high severity alerts today",
            "alerts from 192.168.1.1",
            "critical alerts in the last 7 days",
        ],
        "dns": [
            "dns queries for example.com",
            "dns lookups for google.com in the last 1 hour",
        ],
        "traffic": [
            "large traffic in the last 7 days",
            "traffic on port 443",
            "heavy traffic today",
        ],
        "port": [
            "traffic on port 443",
            "connections on port 22",
            "port 80 in the last 24 hours",
        ],
        "device": [
            "device 192.168.1.1",
            "device 10.0.0.1",
        ],
        "host": [
            "host 192.168.1.1",
            "host router.local",
        ],
        "from": [
            "connections from 192.168.1.1",
            "alerts from 10.0.0.1",
            "show connections from 192.168.1.1 in the last 24 hours",
        ],
        "to": [
            "connections to 10.0.0.1",
            "connections to 8.8.8.8 using dns",
        ],
        "today": [
            "high severity alerts today",
            "large traffic today",
        ],
        "yesterday": [
            "alerts from 192.168.1.1 yesterday",
            "large traffic yesterday",
        ],
        "last": [
            "connections in the last 24 hours",
            "alerts in the last 7 days",
            "large traffic in the last 1 hour",
        ],
        "high": [
            "high severity alerts today",
            "high severity alerts in the last 24 hours",
        ],
        "critical": [
            "critical alerts today",
            "critical alerts in the last 7 days",
        ],
        "large": [
            "large traffic in the last 7 days",
            "large traffic today",
        ],
        "show": [
            "show connections from 192.168.1.1 in the last 24 hours",
            "show all alerts today",
        ],
    }

    def __init__(self) -> None:
        """Initialize the parser with compiled regex patterns."""
        if not self._COMPILED_PATTERNS:
            self.__class__._COMPILED_PATTERNS = [
                (re.compile(pattern, re.IGNORECASE), method)
                for pattern, method in self.PATTERNS
            ]

    def parse(self, query: str) -> dict:
        """Parse a natural language query into an OpenSearch DSL query dict.

        Returns:
            {
                index: str,            # 'zeek-*', 'suricata-*', or 'zeek-*,suricata-*'
                query: dict,           # OpenSearch query DSL
                sort: list,            # sort specification
                size: int,             # result limit
                description: str,      # Human-readable description of what was searched
            }
        """
        if not query or not query.strip():
            return {
                "index": "zeek-*,suricata-*",
                "query": {"query": {"match_all": {}}},
                "sort": [{"@timestamp": {"order": "desc"}}],
                "size": 50,
                "description": "All recent events",
            }

        query = query.strip()
        filters: list[dict] = []
        must_clauses: list[dict] = []
        descriptions: list[str] = []
        index = "zeek-*"  # Default to zeek
        is_alert_query = False
        time_filter_set = False

        for compiled_re, method_name in self._COMPILED_PATTERNS:
            match = compiled_re.search(query)
            if match:
                handler = getattr(self, method_name)
                result = handler(match)
                if result is None:
                    continue

                if "filter" in result:
                    filters.append(result["filter"])
                if "must" in result:
                    must_clauses.append(result["must"])
                if "description" in result:
                    descriptions.append(result["description"])
                if result.get("is_alert"):
                    is_alert_query = True
                if result.get("time_filter"):
                    time_filter_set = True
                if "index" in result:
                    index = result["index"]

        # If it's an alert query, use suricata index
        if is_alert_query:
            index = "suricata-*"

        # If no time filter was set, default to last 24 hours
        if not time_filter_set:
            now = datetime.now(timezone.utc)
            from_time = (now - timedelta(hours=24)).isoformat()
            filters.append({
                "range": {
                    "@timestamp": {
                        "gte": from_time,
                        "lte": now.isoformat(),
                    }
                }
            })
            descriptions.append("in the last 24 hours")

        # Build the query body
        bool_query: dict = {}
        if filters:
            bool_query["filter"] = filters
        if must_clauses:
            bool_query["must"] = must_clauses

        if bool_query:
            query_body = {"query": {"bool": bool_query}}
        else:
            query_body = {"query": {"match_all": {}}}

        description = ", ".join(descriptions) if descriptions else "Search results"

        return {
            "index": index,
            "query": query_body,
            "sort": [{"@timestamp": {"order": "desc"}}],
            "size": 50,
            "description": description,
        }

    def suggest(self, partial: str) -> list[str]:
        """Return search suggestions based on partial input.

        Returns up to 5 suggestions.
        """
        if not partial or not partial.strip():
            return [
                "show connections from 192.168.1.1 in the last 24 hours",
                "high severity alerts today",
                "dns queries for example.com",
                "large traffic in the last 7 days",
                "traffic on port 443",
            ]

        partial = partial.strip().lower()
        suggestions: list[str] = []

        # Check keyword-based suggestions
        for keyword, keyword_suggestions in self.KEYWORD_SUGGESTIONS.items():
            if keyword.startswith(partial) or partial.startswith(keyword):
                for s in keyword_suggestions:
                    if s not in suggestions:
                        suggestions.append(s)

        # Also check for partial matches within keywords
        for keyword, keyword_suggestions in self.KEYWORD_SUGGESTIONS.items():
            if partial in keyword:
                for s in keyword_suggestions:
                    if s not in suggestions:
                        suggestions.append(s)

        # If we still don't have enough, add general suggestions
        if len(suggestions) < 5:
            for s in self.SUGGESTIONS:
                formatted = s.format(
                    ip="192.168.1.1",
                    domain="example.com",
                    port="443",
                    protocol="tcp",
                )
                if formatted not in suggestions:
                    suggestions.append(formatted)

        return suggestions[:5]

    # -----------------------------------------------------------------
    # Pattern handlers -- each returns a dict with optional keys:
    #   filter, must, description, is_alert, time_filter, index
    # -----------------------------------------------------------------

    def _parse_time_range(self, match: re.Match) -> dict:
        """Parse 'last N hours/days/weeks/minutes'."""
        amount = int(match.group(1))
        unit = match.group(2).lower().rstrip("s")  # normalize: 'hours' -> 'hour'

        now = datetime.now(timezone.utc)
        if unit in ("hour", "hr"):
            delta = timedelta(hours=amount)
        elif unit == "day":
            delta = timedelta(days=amount)
        elif unit == "week":
            delta = timedelta(weeks=amount)
        elif unit in ("minute", "min"):
            delta = timedelta(minutes=amount)
        else:
            delta = timedelta(hours=amount)

        from_time = (now - delta).isoformat()
        return {
            "filter": {
                "range": {
                    "@timestamp": {
                        "gte": from_time,
                        "lte": now.isoformat(),
                    }
                }
            },
            "description": f"in the last {amount} {match.group(2)}",
            "time_filter": True,
        }

    def _parse_today(self, match: re.Match) -> dict:
        """Parse 'today' keyword."""
        now = datetime.now(timezone.utc)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return {
            "filter": {
                "range": {
                    "@timestamp": {
                        "gte": start_of_day.isoformat(),
                        "lte": now.isoformat(),
                    }
                }
            },
            "description": "today",
            "time_filter": True,
        }

    def _parse_yesterday(self, match: re.Match) -> dict:
        """Parse 'yesterday' keyword."""
        now = datetime.now(timezone.utc)
        start_of_yesterday = (now - timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end_of_yesterday = start_of_yesterday.replace(
            hour=23, minute=59, second=59, microsecond=999999
        )
        return {
            "filter": {
                "range": {
                    "@timestamp": {
                        "gte": start_of_yesterday.isoformat(),
                        "lte": end_of_yesterday.isoformat(),
                    }
                }
            },
            "description": "yesterday",
            "time_filter": True,
        }

    def _parse_source_ip(self, match: re.Match) -> dict:
        """Parse 'from <IP>'."""
        ip = match.group(1)
        return {
            "filter": {"term": {"id.orig_h": ip}},
            "description": f"from source IP {ip}",
        }

    def _parse_dest_ip(self, match: re.Match) -> dict:
        """Parse 'to <IP>'."""
        ip = match.group(1)
        return {
            "filter": {"term": {"id.resp_h": ip}},
            "description": f"to destination IP {ip}",
        }

    def _parse_any_ip(self, match: re.Match) -> dict:
        """Parse 'ip <IP>' or 'address <IP>'."""
        ip = match.group(1)
        return {
            "must": {
                "bool": {
                    "should": [
                        {"term": {"id.orig_h": ip}},
                        {"term": {"id.resp_h": ip}},
                        {"term": {"src_ip": ip}},
                        {"term": {"dest_ip": ip}},
                    ],
                    "minimum_should_match": 1,
                }
            },
            "description": f"involving IP {ip}",
        }

    def _parse_protocol(self, match: re.Match) -> dict:
        """Parse 'using/over/protocol <protocol>'."""
        proto = match.group(1).lower()
        return {
            "filter": {"term": {"proto": proto}},
            "description": f"using protocol {proto}",
        }

    def _parse_port(self, match: re.Match) -> dict:
        """Parse 'port <number>'."""
        port = int(match.group(1))
        return {
            "must": {
                "bool": {
                    "should": [
                        {"term": {"id.orig_p": port}},
                        {"term": {"id.resp_p": port}},
                    ],
                    "minimum_should_match": 1,
                }
            },
            "description": f"on port {port}",
        }

    def _parse_high_alerts(self, match: re.Match) -> dict:
        """Parse 'high/critical severity alerts'."""
        return {
            "filter": {
                "range": {"alert.severity": {"lte": 2}}
            },
            "description": "high/critical severity alerts",
            "is_alert": True,
            "index": "suricata-*",
        }

    def _parse_alert_ip(self, match: re.Match) -> dict:
        """Parse 'alerts from/for <IP>'."""
        ip = match.group(1)
        return {
            "must": {
                "bool": {
                    "should": [
                        {"term": {"src_ip": ip}},
                        {"term": {"dest_ip": ip}},
                    ],
                    "minimum_should_match": 1,
                }
            },
            "description": f"alerts involving {ip}",
            "is_alert": True,
            "index": "suricata-*",
        }

    def _parse_device(self, match: re.Match) -> dict:
        """Parse 'device/host <IP or hostname>'."""
        device = match.group(1)
        # Check if it looks like an IP
        ip_pattern = re.compile(r'^(?:\d{1,3}\.){3}\d{1,3}$')
        if ip_pattern.match(device):
            return {
                "must": {
                    "bool": {
                        "should": [
                            {"term": {"id.orig_h": device}},
                            {"term": {"id.resp_h": device}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "description": f"device {device}",
            }
        else:
            return {
                "must": {
                    "query_string": {
                        "query": device,
                        "fields": ["host", "hostname", "query"],
                    }
                },
                "description": f"device/host {device}",
            }

    def _parse_large_traffic(self, match: re.Match) -> dict:
        """Parse 'large/big/heavy traffic/transfers'."""
        return {
            "filter": {
                "range": {"orig_bytes": {"gte": 1048576}}  # 1MB+
            },
            "description": "large traffic transfers (>1MB)",
        }

    def _parse_dns_query(self, match: re.Match) -> dict:
        """Parse 'dns queries for <domain>'."""
        domain = match.group(1)
        return {
            "filter": {"term": {"query": domain}},
            "description": f"DNS queries for {domain}",
            "index": "zeek-dns-*",
        }
