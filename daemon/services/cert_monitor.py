"""
NetTap CertificateMonitor — TLS certificate tracking from Zeek SSL logs.

Queries the arkime_sessions3-* index for Zeek SSL event data to surface
certificate inventory, expiry warnings, self-signed usage, and issuer
change detections (potential MITM indicators).
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from opensearchpy import OpenSearch, OpenSearchException

from services.excluded_ips import build_excluded_ips_filter

logger = logging.getLogger("nettap.services.cert_monitor")

NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

# Zeek SSL event filters for the unified Malcolm index
_SSL_FILTERS = [
    {"term": {"event.provider": "zeek"}},
    {"term": {"event.dataset": "ssl"}},
]


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


class CertificateMonitor:
    """TLS certificate tracking service using Zeek SSL logs."""

    def __init__(self, client: OpenSearch) -> None:
        self._client = client

    def get_certificates(
        self,
        from_ts: str | None = None,
        to_ts: str | None = None,
        limit: int = 200,
        excluded_ips: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Get all observed TLS certificates in the time range.

        Returns certificate records with domain, issuer, validity, and
        connection metadata.
        """
        if not from_ts or not to_ts:
            from_ts, to_ts = _default_range()

        excluded = build_excluded_ips_filter(excluded_ips or [])
        bool_clause: dict = {
            "filter": [
                _time_range_filter(from_ts, to_ts),
                *_SSL_FILTERS,
            ]
        }
        if excluded:
            bool_clause["must_not"] = excluded

        query = {
            "size": min(limit, 1000),
            "query": {
                "bool": bool_clause
            },
            "sort": [{"@timestamp": {"order": "desc"}}],
            "_source": [
                "@timestamp",
                "tls.server.subject",
                "tls.server.issuer",
                "tls.server.not_before",
                "tls.server.not_after",
                "tls.server.hash.sha256",
                "tls.version",
                "destination.domain",
                "source.ip",
                "destination.ip",
                "destination.port",
                "tls.server.x509.subject.common_name",
                "tls.server.x509.issuer.common_name",
                "tls.server.x509.not_before",
                "tls.server.x509.not_after",
                "zeek.ssl.server_name",
                "zeek.ssl.subject",
                "zeek.ssl.issuer",
                "zeek.ssl.not_valid_before",
                "zeek.ssl.not_valid_after",
                "zeek.ssl.validation_status",
            ],
        }

        try:
            result = self._client.search(index=NETWORK_INDEX, body=query)
        except OpenSearchException as exc:
            logger.error("Failed to query certificates: %s", exc)
            return []

        certs = []
        for hit in result.get("hits", {}).get("hits", []):
            src = hit.get("_source", {})
            cert = self._normalize_cert(src)
            cert["_id"] = hit.get("_id", "")
            certs.append(cert)

        return certs

    def get_expiring_certs(
        self,
        days: int = 30,
        from_ts: str | None = None,
        to_ts: str | None = None,
        excluded_ips: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Get certificates expiring within N days.

        Returns certs whose not_after falls within the window.
        """
        if not from_ts or not to_ts:
            from_ts, to_ts = _default_range()

        now = datetime.now(timezone.utc)
        expiry_cutoff = (now + timedelta(days=days)).isoformat()

        # Query all certs then filter client-side for expiry
        # (Zeek SSL cert dates may be in various fields)
        all_certs = self.get_certificates(from_ts, to_ts, limit=1000, excluded_ips=excluded_ips)
        expiring = []

        for cert in all_certs:
            not_after = cert.get("not_after", "")
            if not not_after:
                continue
            try:
                expiry_dt = datetime.fromisoformat(
                    not_after.replace("Z", "+00:00")
                )
                if expiry_dt <= datetime.fromisoformat(expiry_cutoff.replace("Z", "+00:00")):
                    cert["days_until_expiry"] = max(0, (expiry_dt - now).days)
                    cert["status"] = "expired" if expiry_dt <= now else "expiring"
                    expiring.append(cert)
            except (ValueError, TypeError):
                continue

        return expiring

    def detect_self_signed(
        self,
        from_ts: str | None = None,
        to_ts: str | None = None,
        excluded_ips: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Detect self-signed certificate usage in the time range.

        A certificate is considered self-signed when the subject matches
        the issuer, or when Zeek reports validation_status as self-signed.
        """
        if not from_ts or not to_ts:
            from_ts, to_ts = _default_range()

        all_certs = self.get_certificates(from_ts, to_ts, limit=1000, excluded_ips=excluded_ips)
        self_signed = []

        for cert in all_certs:
            subject = cert.get("subject", "")
            issuer = cert.get("issuer", "")
            validation = cert.get("validation_status", "")

            is_self_signed = False
            if subject and issuer and subject == issuer:
                is_self_signed = True
            if "self signed" in validation.lower() or "self_signed" in validation.lower():
                is_self_signed = True

            if is_self_signed:
                cert["detection_reason"] = "subject matches issuer" if subject == issuer else "validation status"
                self_signed.append(cert)

        return self_signed

    def detect_issuer_changes(
        self,
        from_ts: str | None = None,
        to_ts: str | None = None,
        excluded_ips: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Detect domains with multiple issuers (potential MITM indicator).

        Groups certificates by domain and flags any that have different
        issuers within the time range.
        """
        if not from_ts or not to_ts:
            from_ts, to_ts = _default_range()

        all_certs = self.get_certificates(from_ts, to_ts, limit=1000, excluded_ips=excluded_ips)

        # Group by domain
        domain_issuers: dict[str, set[str]] = {}
        domain_certs: dict[str, list[dict]] = {}

        for cert in all_certs:
            domain = cert.get("domain", "") or cert.get("server_name", "")
            issuer = cert.get("issuer", "")
            if not domain or not issuer:
                continue

            domain_issuers.setdefault(domain, set()).add(issuer)
            domain_certs.setdefault(domain, []).append(cert)

        changes = []
        for domain, issuers in domain_issuers.items():
            if len(issuers) > 1:
                changes.append({
                    "domain": domain,
                    "issuers": sorted(issuers),
                    "issuer_count": len(issuers),
                    "certificates": domain_certs[domain],
                })

        return changes

    def get_cert_stats(
        self,
        from_ts: str | None = None,
        to_ts: str | None = None,
        excluded_ips: list[str] | None = None,
    ) -> dict[str, Any]:
        """Get certificate hero card statistics.

        Returns: total_certs, expiring_count, self_signed_count, issuer_changes_count.
        """
        if not from_ts or not to_ts:
            from_ts, to_ts = _default_range()

        all_certs = self.get_certificates(from_ts, to_ts, limit=1000, excluded_ips=excluded_ips)
        expiring = self.get_expiring_certs(days=30, from_ts=from_ts, to_ts=to_ts, excluded_ips=excluded_ips)
        self_signed = self.detect_self_signed(from_ts, to_ts, excluded_ips=excluded_ips)
        issuer_changes = self.detect_issuer_changes(from_ts, to_ts, excluded_ips=excluded_ips)

        return {
            "total_certs": len(all_certs),
            "expiring_count": len(expiring),
            "self_signed_count": len(self_signed),
            "issuer_changes_count": len(issuer_changes),
            "from": from_ts,
            "to": to_ts,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_cert(src: dict[str, Any]) -> dict[str, Any]:
        """Normalize a Zeek SSL log entry into a consistent cert record.

        Zeek and Malcolm can store cert fields in different locations
        depending on the version. This normalizes to a flat structure.
        """
        # Try ECS fields first, then Zeek-native
        tls_server = src.get("tls", {}).get("server", {})
        x509 = tls_server.get("x509", {})
        zeek_ssl = src.get("zeek", {}).get("ssl", {})

        subject = (
            x509.get("subject", {}).get("common_name", "")
            or tls_server.get("subject", "")
            or zeek_ssl.get("subject", "")
        )
        issuer = (
            x509.get("issuer", {}).get("common_name", "")
            or tls_server.get("issuer", "")
            or zeek_ssl.get("issuer", "")
        )
        not_before = (
            x509.get("not_before", "")
            or tls_server.get("not_before", "")
            or zeek_ssl.get("not_valid_before", "")
        )
        not_after = (
            x509.get("not_after", "")
            or tls_server.get("not_after", "")
            or zeek_ssl.get("not_valid_after", "")
        )
        domain = (
            src.get("destination", {}).get("domain", "")
            or zeek_ssl.get("server_name", "")
        )
        validation_status = zeek_ssl.get("validation_status", "")

        # Determine status
        status = "valid"
        if not_after:
            try:
                expiry = datetime.fromisoformat(not_after.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                if expiry <= now:
                    status = "expired"
                elif expiry <= now + timedelta(days=30):
                    status = "expiring"
            except (ValueError, TypeError):
                pass

        if subject and issuer and subject == issuer:
            status = "self-signed"
        if "self signed" in validation_status.lower():
            status = "self-signed"

        return {
            "timestamp": src.get("@timestamp", ""),
            "domain": domain,
            "server_name": zeek_ssl.get("server_name", ""),
            "subject": subject,
            "issuer": issuer,
            "not_before": not_before,
            "not_after": not_after,
            "tls_version": src.get("tls", {}).get("version", ""),
            "hash_sha256": tls_server.get("hash", {}).get("sha256", ""),
            "source_ip": src.get("source", {}).get("ip", ""),
            "destination_ip": src.get("destination", {}).get("ip", ""),
            "destination_port": src.get("destination", {}).get("port", ""),
            "validation_status": validation_status,
            "status": status,
        }
