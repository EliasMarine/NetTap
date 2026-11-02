"""
NetTap CertificateMonitor — TLS certificate inventory from Zeek x509 logs.

Zeek 6+ writes certificate details (subject, issuer, validity, key, SANs) to
x509.log. ssl.log only carries the chain fingerprints (zeek.ssl.cert_chain_fps),
the SNI and the validation status. So the inventory aggregates x509 records into
one row per fingerprint, then joins ssl sessions in one bounded query for the
server names and clients.

Field names checked against Malcolm v26.02.0: logstash/pipelines/zeek/
1069_zeek_x509.conf, 1200_zeek_mutate.conf, 1400_zeek_convert.conf and
dashboards/templates/composable/component/zeek.json.

TLS 1.3 encrypts the server certificate, so Zeek only sees certificates from
TLS 1.2 and older handshakes.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from opensearchpy import OpenSearch, OpenSearchException

from services.excluded_ips import build_excluded_ips_filter
from storage.all_buckets import PAGE_SIZE, all_buckets

logger = logging.getLogger("nettap.services.cert_monitor")

NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

# Zeek SSL event filters for the unified Malcolm index
_SSL_FILTERS = [
    {"term": {"event.provider": "zeek"}},
    {"term": {"event.dataset": "ssl"}},
]

_X509_FILTERS = [
    {"term": {"event.provider": "zeek"}},
    {"term": {"event.dataset": "x509"}},
]

# End-host certs only. Chains also log intermediates and roots, and a root
# always has subject == issuer. Zeek JSON logs the flag as true, TSV as T.
_LEAF_CERT_FILTER = {"terms": {"zeek.x509.host_cert": ["true", "T"]}}

_FINGERPRINT = "zeek.x509.fingerprint"
_NOT_AFTER = "zeek.x509.certificate_not_valid_after"
_CHAIN_FPS = "zeek.ssl.cert_chain_fps"

_EXPIRY_WARN_DAYS = 30
_MAX_EXPIRY_DAYS = 3650
_MAX_CERTS = 1000

# Cardinality is exact up to precision_threshold (40000 is OpenSearch's max)
_DISTINCT_CERTS = {"cardinality": {"field": _FINGERPRINT, "precision_threshold": 40000}}

_SELF_SIGNED_FILTER = {
    "script": {
        "script": {
            "lang": "painless",
            "source": (
                "if (!doc.containsKey('zeek.x509.certificate_subject_full')"
                " || !doc.containsKey('zeek.x509.certificate_issuer_full')) return false;"
                " def s = doc['zeek.x509.certificate_subject_full'];"
                " def i = doc['zeek.x509.certificate_issuer_full'];"
                " return s.size() > 0 && i.size() > 0 && s.value == i.value;"
            ),
        }
    }
}

# A row reads only the zeek.x509 object of the latest record
_X509_SOURCE = ["zeek.x509"]
# The issuer comparison reads only the CA and subject of a certificate
_ISSUER_SOURCE = [
    "zeek.x509.certificate_subject",
    "zeek.x509.certificate_issuer",
    "zeek.x509.certificate_issuer_full",
]
# (fingerprint, server name) pages carry no sub-aggregations: 10x fewer scans, far below max_buckets
_PAIR_PAGE = 10_000


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


def _default_range() -> tuple[str, str]:
    """Return default time range (last 7 days)."""
    now = datetime.now(timezone.utc)
    return (now - timedelta(days=7)).isoformat(), now.isoformat()


# ---------------------------------------------------------------------------
# Row building
# ---------------------------------------------------------------------------


def _first(value: Any) -> str:
    """First item of a list-or-scalar field as a string ('' when missing)."""
    if isinstance(value, list):
        value = value[0] if value else ""
    return "" if value is None else str(value)


def _as_list(value: Any) -> list[str]:
    """A list-or-scalar field as a list of strings."""
    if value is None or value == "":
        return []
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def _dn_part(dn: Any, key: str) -> str:
    """One attribute (CN, O, ...) of a DN that Malcolm split into an object."""
    return _first(dn.get(key)) if isinstance(dn, dict) else ""


def _keys(agg: dict | None) -> list[Any]:
    """Bucket keys of a terms aggregation, biggest first."""
    return [b.get("key") for b in (agg or {}).get("buckets", [])]


def _top_terms(field: str, size: int) -> dict:
    return {"terms": {"field": field, "size": size}}


def _seen(agg_parent: dict, name: str) -> str:
    """ISO string of a min/max date sub-aggregation ('' when empty)."""
    return (agg_parent.get(name) or {}).get("value_as_string") or ""


def _agg_count(aggs: dict, name: str) -> int:
    """Value of a cardinality agg, directly or under a filter agg's 'n'."""
    node = aggs.get(name) or {}
    return int((node.get("n") or node).get("value") or 0)


def _parse_date(value: str) -> datetime | None:
    """Parse an ISO date from OpenSearch; None when missing or unparseable."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Unparseable certificate date: %r", value)
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _status(expiry: datetime | None, self_signed: bool, now: datetime) -> str:
    if self_signed:
        return "self-signed"
    if expiry is None:
        return "valid"
    if expiry <= now:
        return "expired"
    if expiry <= now + timedelta(days=_EXPIRY_WARN_DAYS):
        return "expiring"
    return "valid"


def _x509_fields(x509: dict[str, Any]) -> dict[str, Any]:
    """Certificate details from the latest x509 record of a fingerprint."""
    subject, issuer = x509.get("certificate_subject"), x509.get("certificate_issuer")
    subject_full = _first(x509.get("certificate_subject_full"))
    issuer_full = _first(x509.get("certificate_issuer_full"))
    return {
        "subject": _dn_part(subject, "CN") or subject_full,
        "subject_cn": _dn_part(subject, "CN"),
        "subject_full": subject_full,
        "issuer": _dn_part(issuer, "CN") or issuer_full,
        "issuer_org": _dn_part(issuer, "O"),
        "issuer_full": issuer_full,
        "not_before": _first(x509.get("certificate_not_valid_before")),
        "not_after": _first(x509.get("certificate_not_valid_after")),
        "key_type": _first(x509.get("certificate_key_type")),
        "key_length": x509.get("certificate_key_length"),
        "sig_alg": _first(x509.get("certificate_sig_alg")),
        "serial": _first(x509.get("certificate_serial")),
        "san_dns": _as_list(x509.get("san_dns")),
    }


def _session_fields(session: dict[str, Any]) -> dict[str, Any]:
    """Server names and clients from the ssl sessions that sent the cert."""
    server_names = [str(k) for k in _keys(session.get("server_names"))]
    clients = [str(k) for k in _keys(session.get("clients"))]
    servers = _keys(session.get("servers"))
    ports = _keys(session.get("ports"))
    return {
        "server_name": server_names[0] if server_names else "",
        "server_names": server_names,
        "clients": clients,
        "source_ip": clients[0] if clients else "",
        "destination_ip": str(servers[0]) if servers else "",
        "destination_port": ports[0] if ports else "",
        "tls_version": _first(_keys(session.get("versions"))),
        "validation_status": _first(_keys(session.get("validation"))),
    }


def _cert_row(bucket: dict, session: dict, now: datetime) -> dict[str, Any]:
    """One inventory row from an x509 fingerprint bucket and its sessions."""
    hits = (bucket.get("latest") or {}).get("hits", {}).get("hits", [])
    source = hits[0].get("_source", {}) if hits else {}
    cert = {
        **_x509_fields(source.get("zeek", {}).get("x509", {})),
        **_session_fields(session),
    }
    fingerprint = str(bucket.get("key", ""))
    self_signed = bool(cert["subject_full"]) and (
        cert["subject_full"] == cert["issuer_full"]
    )
    expiry = _parse_date(cert["not_after"])
    # Seen counts are TLS sessions. x509.log relogs a cert at most daily, so it
    # only stands in when no ssl session in range carried the fingerprint.
    seen = session if session.get("doc_count") else bucket
    last_seen = _seen(seen, "last_seen")
    return {
        **cert,
        "_id": fingerprint,
        "fingerprint": fingerprint,
        "hash_sha256": fingerprint,  # Zeek's X509::hash_function defaults to SHA-256
        "domain": cert["server_name"] or cert["subject_cn"] or _first(cert["san_dns"]),
        "first_seen": _seen(seen, "first_seen"),
        "last_seen": last_seen,
        "timestamp": last_seen,
        "times_seen": int(seen.get("doc_count") or 0),
        "days_until_expiry": max(0, (expiry - now).days) if expiry else None,
        "self_signed": self_signed,
        "status": _status(expiry, self_signed, now),
    }


def _issuer_changes(certs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Server names whose certificates come from more than one CA.

    Compares the issuing organisation, not the issuer CN: Let's Encrypt and
    others rotate intermediates (R10/R11, E5/E6), which is not a change of CA.
    """
    by_name: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for cert in certs:
        ca = cert["issuer_org"] or cert["issuer"]
        for name in cert["server_names"] or [cert["subject_cn"]]:
            if ca and name:
                by_name.setdefault(name, {}).setdefault(ca, []).append(cert)
    return [
        {
            "domain": name,
            "issuers": sorted(cas),
            "issuer_count": len(cas),
            "certificates": [c for group in cas.values() for c in group],
        }
        for name, cas in sorted(by_name.items())
        if len(cas) > 1
    ]


def _leaf_cert(bucket: dict, names: dict[str, list[str]]) -> dict[str, Any]:
    """What _issuer_changes reads of one leaf certificate: its CA, subject and server names."""
    fp = bucket["key"]["fp"]
    hits = (bucket.get("latest") or {}).get("hits", {}).get("hits", [])
    x509 = hits[0].get("_source", {}).get("zeek", {}).get("x509", {}) if hits else {}
    return {**_x509_fields(x509), "fingerprint": fp, "server_names": names.get(fp, [])}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class CertStatsUnavailable(Exception):
    """The stats query failed; callers must not show zeros as if they were counts."""


class CertificateMonitor:
    """TLS certificate inventory from Zeek x509 logs joined to ssl sessions."""

    def __init__(self, client: OpenSearch) -> None:
        self._client = client

    def _search(self, body: dict, what: str) -> dict:
        """Run a search on the network index; {} (logged) on failure."""
        try:
            return self._client.search(index=NETWORK_INDEX, body=body) or {}
        except OpenSearchException as exc:
            logger.error("Failed to query %s: %s", what, exc)
            return {}

    def _all_buckets(
        self,
        query: dict,
        sources: list[dict],
        aggs: dict | None,
        what: str,
        page_size: int = PAGE_SIZE,
    ) -> list[dict]:
        """Every composite bucket on the network index; [] (logged) on failure."""
        try:
            buckets, complete = all_buckets(
                self._client, NETWORK_INDEX, query, sources, aggs, page_size
            )
        except OpenSearchException as exc:
            logger.error("Failed to query %s: %s", what, exc)
            return []
        if not complete:
            logger.warning("%s stopped at %d buckets; result is partial", what, len(buckets))
        return buckets

    def _leaf_certs(
        self, from_ts: str, to_ts: str, excluded_ips: list[str] | None
    ) -> list[dict[str, Any]]:
        """Every leaf certificate in range, with every server name ssl sessions sent it for."""
        x509_query = {
            "bool": {
                "filter": [
                    _time_range_filter(from_ts, to_ts),
                    *_X509_FILTERS,
                    _LEAF_CERT_FILTER,
                ]
            }
        }
        certs = self._all_buckets(
            x509_query,
            [{"fp": {"terms": {"field": _FINGERPRINT}}}],
            {"latest": {"top_hits": {"size": 1, "_source": _ISSUER_SOURCE}}},
            "certificate issuers",
        )
        if not certs:
            return []
        ssl_query: dict = {
            "bool": {"filter": [_time_range_filter(from_ts, to_ts), *_SSL_FILTERS]}
        }
        excluded = build_excluded_ips_filter(excluded_ips or [])
        if excluded:
            ssl_query["bool"]["must_not"] = excluded
        # The chain also lists intermediates; their pairs match no leaf and drop out
        pairs = self._all_buckets(
            ssl_query,
            [
                {"fp": {"terms": {"field": _CHAIN_FPS}}},
                {"name": {"terms": {"field": "zeek.ssl.server_name"}}},
            ],
            None,
            "certificate server names",
            page_size=_PAIR_PAGE,
        )
        names: dict[str, list[str]] = {}
        for pair in pairs:
            names.setdefault(pair["key"]["fp"], []).append(str(pair["key"]["name"]))
        return [_leaf_cert(b, names) for b in certs]

    def _rows(
        self,
        fingerprints: list[str],
        from_ts: str,
        to_ts: str,
        excluded_ips: list[str] | None,
    ) -> list[dict[str, Any]]:
        """Inventory rows for these fingerprints, _MAX_CERTS per query."""
        chunks = [
            fingerprints[i : i + _MAX_CERTS]
            for i in range(0, len(fingerprints), _MAX_CERTS)
        ]
        return [
            row
            for chunk in chunks
            for row in self._inventory(
                from_ts, to_ts, [{"terms": {_FINGERPRINT: chunk}}], len(chunk), excluded_ips
            )
        ]

    def _inventory(
        self,
        from_ts: str | None,
        to_ts: str | None,
        extra_filters: list[dict],
        limit: int,
        excluded_ips: list[str] | None,
    ) -> list[dict[str, Any]]:
        """One row per certificate fingerprint, most recently seen first.

        excluded_ips only narrows the clients: x509 records carry no IPs.
        """
        if not from_ts or not to_ts:
            from_ts, to_ts = _default_range()
        filters = [
            _time_range_filter(from_ts, to_ts),
            *_X509_FILTERS,
            _LEAF_CERT_FILTER,
            *extra_filters,
        ]
        latest = {"size": 1, "sort": [{"@timestamp": {"order": "desc"}}]}
        body = {
            "size": 0,
            "query": {"bool": {"filter": filters}},
            "aggs": {
                "certs": {
                    "terms": {
                        "field": _FINGERPRINT,
                        "size": max(1, min(limit, _MAX_CERTS)),
                        "order": {"last_seen": "desc"},
                    },
                    "aggs": {
                        "first_seen": {"min": {"field": "@timestamp"}},
                        "last_seen": {"max": {"field": "@timestamp"}},
                        "latest": {"top_hits": {**latest, "_source": _X509_SOURCE}},
                    },
                }
            },
        }
        result = self._search(body, "certificate inventory")
        buckets = (result.get("aggregations") or {}).get("certs", {}).get("buckets", [])
        sessions = self._sessions_by_fingerprint(
            [b["key"] for b in buckets], from_ts, to_ts, excluded_ips
        )
        now = datetime.now(timezone.utc)
        return [_cert_row(b, sessions.get(b["key"], {}), now) for b in buckets]

    def _sessions_by_fingerprint(
        self,
        fingerprints: list[str],
        from_ts: str,
        to_ts: str,
        excluded_ips: list[str] | None,
    ) -> dict[str, dict]:
        """ssl session stats per fingerprint, in one query (empty on failure)."""
        if not fingerprints:
            return {}
        bool_clause: dict = {
            "filter": [
                _time_range_filter(from_ts, to_ts),
                *_SSL_FILTERS,
                {"terms": {_CHAIN_FPS: fingerprints}},
            ]
        }
        excluded = build_excluded_ips_filter(excluded_ips or [])
        if excluded:
            bool_clause["must_not"] = excluded
        body = {
            "size": 0,
            "query": {"bool": bool_clause},
            "aggs": {
                "fps": {
                    # include: the chain also lists intermediates' fingerprints
                    "terms": {
                        "field": _CHAIN_FPS,
                        "include": fingerprints,
                        "size": len(fingerprints),
                    },
                    "aggs": {
                        "first_seen": {"min": {"field": "@timestamp"}},
                        "last_seen": {"max": {"field": "@timestamp"}},
                        "server_names": _top_terms("zeek.ssl.server_name", 10),
                        "clients": _top_terms("source.ip", 10),
                        "servers": _top_terms("destination.ip", 1),
                        "ports": _top_terms("destination.port", 1),
                        "versions": _top_terms("zeek.ssl.ssl_version", 1),
                        "validation": _top_terms("zeek.ssl.validation_status", 1),
                    },
                }
            },
        }
        result = self._search(body, "certificate sessions")
        buckets = (result.get("aggregations") or {}).get("fps", {}).get("buckets", [])
        return {b["key"]: b for b in buckets}

    def get_certificates(
        self,
        from_ts: str | None = None,
        to_ts: str | None = None,
        limit: int = _MAX_CERTS,
        excluded_ips: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """All certificates seen in the time range, one row per fingerprint."""
        return self._inventory(from_ts, to_ts, [], limit, excluded_ips)

    def get_expiring_certs(
        self,
        days: int = _EXPIRY_WARN_DAYS,
        from_ts: str | None = None,
        to_ts: str | None = None,
        excluded_ips: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Certificates expiring within N days, including already expired ones."""
        days = min(max(0, int(days)), _MAX_EXPIRY_DAYS)
        expiring = {"range": {_NOT_AFTER: {"lte": f"now+{days}d"}}}
        certs = self._inventory(from_ts, to_ts, [expiring], _MAX_CERTS, excluded_ips)
        now = datetime.now(timezone.utc)
        return [
            {**c, "status": "expired" if _is_expired(c, now) else "expiring"}
            for c in certs
        ]

    def detect_self_signed(
        self,
        from_ts: str | None = None,
        to_ts: str | None = None,
        excluded_ips: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Certificates whose subject DN equals their issuer DN."""
        certs = self._inventory(
            from_ts, to_ts, [_SELF_SIGNED_FILTER], _MAX_CERTS, excluded_ips
        )
        return [{**c, "detection_reason": "subject matches issuer"} for c in certs]

    def detect_issuer_changes(
        self,
        from_ts: str | None = None,
        to_ts: str | None = None,
        excluded_ips: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Server names served by certificates from more than one CA."""
        # OLD CODE START — #96: compared only the newest 1,000 certificates and each one's
        # 10 busiest server names, so a CA change on a busier network went unseen
        # certs = self.get_certificates(from_ts, to_ts, excluded_ips=excluded_ips)
        # return _issuer_changes(certs)
        # OLD CODE END
        if not from_ts or not to_ts:
            from_ts, to_ts = _default_range()
        changes = _issuer_changes(self._leaf_certs(from_ts, to_ts, excluded_ips))
        fps = sorted({c["fingerprint"] for ch in changes for c in ch["certificates"]})
        rows = {r["fingerprint"]: r for r in self._rows(fps, from_ts, to_ts, excluded_ips)}
        return [
            {
                **ch,
                "certificates": [
                    rows[c["fingerprint"]]
                    for c in ch["certificates"]
                    if c["fingerprint"] in rows
                ],
            }
            for ch in changes
        ]

    def get_cert_stats(
        self,
        from_ts: str | None = None,
        to_ts: str | None = None,
        excluded_ips: list[str] | None = None,
    ) -> dict[str, Any]:
        """Hero card counts of distinct certificates (not capped by the list)."""
        if not from_ts or not to_ts:
            from_ts, to_ts = _default_range()
        # Absolute times: a "now" range inside a filter aggregation intermittently fails
        # on OpenSearch 2.x ("DateRangeIncludingNowQuery does not implement createWeight")
        now = datetime.now(timezone.utc)
        within_warning = {
            "gte": now.isoformat(),
            "lte": (now + timedelta(days=_EXPIRY_WARN_DAYS)).isoformat(),
        }
        body = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        _time_range_filter(from_ts, to_ts),
                        *_X509_FILTERS,
                        _LEAF_CERT_FILTER,
                    ]
                }
            },
            "aggs": {
                "total": _DISTINCT_CERTS,
                "expiring": {
                    "filter": {"range": {_NOT_AFTER: within_warning}},
                    "aggs": {"n": _DISTINCT_CERTS},
                },
                "expired": {
                    "filter": {"range": {_NOT_AFTER: {"lt": now.isoformat()}}},
                    "aggs": {"n": _DISTINCT_CERTS},
                },
                "self_signed": {
                    "filter": _SELF_SIGNED_FILTER,
                    "aggs": {"n": _DISTINCT_CERTS},
                },
            },
        }
        aggs = self._search(body, "certificate stats").get("aggregations")
        if aggs is None:
            raise CertStatsUnavailable("certificate stats query failed")
        # OLD CODE START — #96: counted changes among the newest 1,000 certificates only
        # changes = self.detect_issuer_changes(from_ts, to_ts, excluded_ips=excluded_ips)
        # OLD CODE END
        # The count needs no inventory rows
        changes = _issuer_changes(self._leaf_certs(from_ts, to_ts, excluded_ips))
        return {
            "total_certs": _agg_count(aggs, "total"),
            "expiring_count": _agg_count(aggs, "expiring"),
            "expired_count": _agg_count(aggs, "expired"),
            "self_signed_count": _agg_count(aggs, "self_signed"),
            "issuer_changes_count": len(changes),
            "from": from_ts,
            "to": to_ts,
        }


def _is_expired(cert: dict[str, Any], now: datetime) -> bool:
    expiry = _parse_date(cert["not_after"])
    return expiry is not None and expiry <= now


# OLD CODE START — 2026-11-01: read cert fields from zeek.ssl.* / tls.server.*,
# which Zeek 6+ ssl.log does not carry (they live in x509.log). Every row was a TLS
# session with empty subject/issuer/dates, and total_certs was the 1000-hit fetch cap.
# class CertificateMonitor:
#     """TLS certificate tracking service using Zeek SSL logs."""
#
#     def __init__(self, client: OpenSearch) -> None:
#         self._client = client
#
#     def get_certificates(
#         self,
#         from_ts: str | None = None,
#         to_ts: str | None = None,
#         limit: int = 200,
#         excluded_ips: list[str] | None = None,
#     ) -> list[dict[str, Any]]:
#         """Get all observed TLS certificates in the time range.
#
#         Returns certificate records with domain, issuer, validity, and
#         connection metadata.
#         """
#         if not from_ts or not to_ts:
#             from_ts, to_ts = _default_range()
#
#         excluded = build_excluded_ips_filter(excluded_ips or [])
#         bool_clause: dict = {
#             "filter": [
#                 _time_range_filter(from_ts, to_ts),
#                 *_SSL_FILTERS,
#             ]
#         }
#         if excluded:
#             bool_clause["must_not"] = excluded
#
#         query = {
#             "size": min(limit, 1000),
#             "query": {"bool": bool_clause},
#             "sort": [{"@timestamp": {"order": "desc"}}],
#             "_source": [
#                 "@timestamp",
#                 "tls.server.subject",
#                 "tls.server.issuer",
#                 "tls.server.not_before",
#                 "tls.server.not_after",
#                 "tls.server.hash.sha256",
#                 "tls.version",
#                 "destination.domain",
#                 "source.ip",
#                 "destination.ip",
#                 "destination.port",
#                 "tls.server.x509.subject.common_name",
#                 "tls.server.x509.issuer.common_name",
#                 "tls.server.x509.not_before",
#                 "tls.server.x509.not_after",
#                 "zeek.ssl.server_name",
#                 "zeek.ssl.subject",
#                 "zeek.ssl.issuer",
#                 "zeek.ssl.not_valid_before",
#                 "zeek.ssl.not_valid_after",
#                 "zeek.ssl.validation_status",
#             ],
#         }
#
#         try:
#             result = self._client.search(index=NETWORK_INDEX, body=query)
#         except OpenSearchException as exc:
#             logger.error("Failed to query certificates: %s", exc)
#             return []
#
#         certs = []
#         for hit in result.get("hits", {}).get("hits", []):
#             src = hit.get("_source", {})
#             cert = self._normalize_cert(src)
#             cert["_id"] = hit.get("_id", "")
#             certs.append(cert)
#
#         return certs
#
#     def get_expiring_certs(
#         self,
#         days: int = 30,
#         from_ts: str | None = None,
#         to_ts: str | None = None,
#         excluded_ips: list[str] | None = None,
#     ) -> list[dict[str, Any]]:
#         """Get certificates expiring within N days.
#
#         Returns certs whose not_after falls within the window.
#         """
#         if not from_ts or not to_ts:
#             from_ts, to_ts = _default_range()
#
#         now = datetime.now(timezone.utc)
#         expiry_cutoff = (now + timedelta(days=days)).isoformat()
#
#         # Query all certs then filter client-side for expiry
#         # (Zeek SSL cert dates may be in various fields)
#         all_certs = self.get_certificates(
#             from_ts, to_ts, limit=1000, excluded_ips=excluded_ips
#         )
#         expiring = []
#
#         for cert in all_certs:
#             not_after = cert.get("not_after", "")
#             if not not_after:
#                 continue
#             try:
#                 expiry_dt = datetime.fromisoformat(not_after.replace("Z", "+00:00"))
#                 if expiry_dt <= datetime.fromisoformat(
#                     expiry_cutoff.replace("Z", "+00:00")
#                 ):
#                     cert["days_until_expiry"] = max(0, (expiry_dt - now).days)
#                     cert["status"] = "expired" if expiry_dt <= now else "expiring"
#                     expiring.append(cert)
#             except (ValueError, TypeError):
#                 continue
#
#         return expiring
#
#     def detect_self_signed(
#         self,
#         from_ts: str | None = None,
#         to_ts: str | None = None,
#         excluded_ips: list[str] | None = None,
#     ) -> list[dict[str, Any]]:
#         """Detect self-signed certificate usage in the time range.
#
#         A certificate is considered self-signed when the subject matches
#         the issuer, or when Zeek reports validation_status as self-signed.
#         """
#         if not from_ts or not to_ts:
#             from_ts, to_ts = _default_range()
#
#         all_certs = self.get_certificates(
#             from_ts, to_ts, limit=1000, excluded_ips=excluded_ips
#         )
#         self_signed = []
#
#         for cert in all_certs:
#             subject = cert.get("subject", "")
#             issuer = cert.get("issuer", "")
#             validation = cert.get("validation_status", "")
#
#             is_self_signed = False
#             if subject and issuer and subject == issuer:
#                 is_self_signed = True
#             if (
#                 "self signed" in validation.lower()
#                 or "self_signed" in validation.lower()
#             ):
#                 is_self_signed = True
#
#             if is_self_signed:
#                 cert["detection_reason"] = (
#                     "subject matches issuer"
#                     if subject == issuer
#                     else "validation status"
#                 )
#                 self_signed.append(cert)
#
#         return self_signed
#
#     def detect_issuer_changes(
#         self,
#         from_ts: str | None = None,
#         to_ts: str | None = None,
#         excluded_ips: list[str] | None = None,
#     ) -> list[dict[str, Any]]:
#         """Detect domains with multiple issuers (potential MITM indicator).
#
#         Groups certificates by domain and flags any that have different
#         issuers within the time range.
#         """
#         if not from_ts or not to_ts:
#             from_ts, to_ts = _default_range()
#
#         all_certs = self.get_certificates(
#             from_ts, to_ts, limit=1000, excluded_ips=excluded_ips
#         )
#
#         # Group by domain
#         domain_issuers: dict[str, set[str]] = {}
#         domain_certs: dict[str, list[dict]] = {}
#
#         for cert in all_certs:
#             domain = cert.get("domain", "") or cert.get("server_name", "")
#             issuer = cert.get("issuer", "")
#             if not domain or not issuer:
#                 continue
#
#             domain_issuers.setdefault(domain, set()).add(issuer)
#             domain_certs.setdefault(domain, []).append(cert)
#
#         changes = []
#         for domain, issuers in domain_issuers.items():
#             if len(issuers) > 1:
#                 changes.append(
#                     {
#                         "domain": domain,
#                         "issuers": sorted(issuers),
#                         "issuer_count": len(issuers),
#                         "certificates": domain_certs[domain],
#                     }
#                 )
#
#         return changes
#
#     def get_cert_stats(
#         self,
#         from_ts: str | None = None,
#         to_ts: str | None = None,
#         excluded_ips: list[str] | None = None,
#     ) -> dict[str, Any]:
#         """Get certificate hero card statistics.
#
#         Returns: total_certs, expiring_count, self_signed_count, issuer_changes_count.
#         """
#         if not from_ts or not to_ts:
#             from_ts, to_ts = _default_range()
#
#         all_certs = self.get_certificates(
#             from_ts, to_ts, limit=1000, excluded_ips=excluded_ips
#         )
#         expiring = self.get_expiring_certs(
#             days=30, from_ts=from_ts, to_ts=to_ts, excluded_ips=excluded_ips
#         )
#         self_signed = self.detect_self_signed(from_ts, to_ts, excluded_ips=excluded_ips)
#         issuer_changes = self.detect_issuer_changes(
#             from_ts, to_ts, excluded_ips=excluded_ips
#         )
#
#         return {
#             "total_certs": len(all_certs),
#             "expiring_count": len(expiring),
#             "self_signed_count": len(self_signed),
#             "issuer_changes_count": len(issuer_changes),
#             "from": from_ts,
#             "to": to_ts,
#         }
#
#     # ------------------------------------------------------------------
#     # Helpers
#     # ------------------------------------------------------------------
#
#     @staticmethod
#     def _normalize_cert(src: dict[str, Any]) -> dict[str, Any]:
#         """Normalize a Zeek SSL log entry into a consistent cert record.
#
#         Zeek and Malcolm can store cert fields in different locations
#         depending on the version. This normalizes to a flat structure.
#         """
#         # Try ECS fields first, then Zeek-native
#         tls_server = src.get("tls", {}).get("server", {})
#         x509 = tls_server.get("x509", {})
#         zeek_ssl = src.get("zeek", {}).get("ssl", {})
#
#         subject = (
#             x509.get("subject", {}).get("common_name", "")
#             or tls_server.get("subject", "")
#             or zeek_ssl.get("subject", "")
#         )
#         issuer = (
#             x509.get("issuer", {}).get("common_name", "")
#             or tls_server.get("issuer", "")
#             or zeek_ssl.get("issuer", "")
#         )
#         not_before = (
#             x509.get("not_before", "")
#             or tls_server.get("not_before", "")
#             or zeek_ssl.get("not_valid_before", "")
#         )
#         not_after = (
#             x509.get("not_after", "")
#             or tls_server.get("not_after", "")
#             or zeek_ssl.get("not_valid_after", "")
#         )
#         domain = src.get("destination", {}).get("domain", "") or zeek_ssl.get(
#             "server_name", ""
#         )
#         validation_status = zeek_ssl.get("validation_status", "")
#
#         # Determine status
#         status = "valid"
#         if not_after:
#             try:
#                 expiry = datetime.fromisoformat(not_after.replace("Z", "+00:00"))
#                 now = datetime.now(timezone.utc)
#                 if expiry <= now:
#                     status = "expired"
#                 elif expiry <= now + timedelta(days=30):
#                     status = "expiring"
#             except (ValueError, TypeError):
#                 pass
#
#         if subject and issuer and subject == issuer:
#             status = "self-signed"
#         if "self signed" in validation_status.lower():
#             status = "self-signed"
#
#         return {
#             "timestamp": src.get("@timestamp", ""),
#             "domain": domain,
#             "server_name": zeek_ssl.get("server_name", ""),
#             "subject": subject,
#             "issuer": issuer,
#             "not_before": not_before,
#             "not_after": not_after,
#             "tls_version": src.get("tls", {}).get("version", ""),
#             "hash_sha256": tls_server.get("hash", {}).get("sha256", ""),
#             "source_ip": src.get("source", {}).get("ip", ""),
#             "destination_ip": src.get("destination", {}).get("ip", ""),
#             "destination_port": src.get("destination", {}).get("port", ""),
#             "validation_status": validation_status,
#             "status": status,
#         }
# OLD CODE END
