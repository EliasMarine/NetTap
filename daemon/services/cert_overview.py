"""
Certificate overview: every TLS session's certificate in a window, counted exactly (NET-154).

Each ssl record with a certificate chain is credited to the FIRST fingerprint of its chain,
read in order from _source (doc values sort arrays, losing which one was the server's own
certificate). The scan pages one point-in-time snapshot with search_after, so the session
tallies and the x509 details lookup see the same data. Nothing is cut to a top N: a figure
is either complete or the pass fails (CertQueryFailed → 503), never smaller-but-shown.

TLS 1.3 encrypts the certificate, and resumed sessions don't resend it; neither has a
chain, so neither is counted.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterator

from opensearchpy import OpenSearchException

from services import cert_findings
from services.excluded_ips import build_excluded_ips_filter

logger = logging.getLogger("nettap.services.cert_overview")

NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

PAGE_SIZE = 10_000
DETAIL_CHUNK = 1_000
MAX_KEYS = 200_000  # distinct (certificate, site, server, port, status, version/client) tallies
BUDGET_SECONDS = 50.0  # the web proxy gives this path 60 s
MAX_REPLY_BYTES = 5_000_000
PIT_KEEP_ALIVE = "2m"
PIT_CLOSE_SECONDS = (
    5  # closing runs in `finally`, often when OpenSearch is already slow
)
MAX_TEXT = (
    1_000  # characters kept of a certificate's name fields, which the network controls
)

_CHAIN = "zeek.ssl.cert_chain_fps"
_FINGERPRINT = "zeek.x509.fingerprint"
# docvalue field → accumulator slot
_SESSION_FIELDS = (
    "zeek.ssl.server_name",
    "destination.ip",
    "destination.port",
    "source.ip",
    "zeek.ssl.validation_status",
    "zeek.ssl.ssl_version",
)


class CertQueryFailed(Exception):
    """A certificate query failed or was incomplete; never show partial figures as counts (#96)."""


class CertTooSlow(CertQueryFailed):
    """The pass ran past its time budget."""


class CertTooBig(CertQueryFailed):
    """Too many distinct certificate uses, or a reply too large, to show for this window."""


class Budget:
    """One monotonic deadline for a whole request: queueing, searches and encoding."""

    def __init__(
        self,
        seconds: float = BUDGET_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._end = clock() + seconds

    def remaining(self) -> float:
        return self._end - self._clock()

    def check(self, what: str) -> None:
        if self.remaining() <= 0:
            raise CertTooSlow(f"{what} took too long")


# ---------------------------------------------------------------------------
# x509 fields
# ---------------------------------------------------------------------------


def _first(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    return "" if value is None else str(value)


def _dn_part(dn: Any, key: str) -> str:
    return _first(dn.get(key)) if isinstance(dn, dict) else ""


def _cut(text: str) -> str:
    """A name field kept to MAX_TEXT characters, marked when cut."""
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"


def x509_fields(x509: dict[str, Any]) -> dict[str, Any]:
    """Certificate facts from one zeek.x509 record (Malcolm splits DNs into objects)."""
    subject, issuer = x509.get("certificate_subject"), x509.get("certificate_issuer")
    subject_full = _first(x509.get("certificate_subject_full"))
    issuer_full = _first(x509.get("certificate_issuer_full"))
    san = x509.get("san_dns")
    sans = (
        [str(s) for s in san] if isinstance(san, list) else ([str(san)] if san else [])
    )
    # Names and SANs come from whoever sent the certificate: cut them, so one crafted
    # certificate can't push every window's reply past MAX_REPLY_BYTES
    return {
        "subject": _cut(_dn_part(subject, "CN") or subject_full),
        "subject_cn": _cut(_dn_part(subject, "CN")),
        "subject_full": _cut(subject_full),
        "issuer": _cut(_dn_part(issuer, "CN") or issuer_full),
        "issuer_org": _cut(_dn_part(issuer, "O")),
        "issuer_full": _cut(issuer_full),
        "not_before": _first(x509.get("certificate_not_valid_before")),
        "not_after": _first(x509.get("certificate_not_valid_after")),
        "key_type": _first(x509.get("certificate_key_type")),
        "key_length": x509.get("certificate_key_length"),
        "sig_alg": _first(x509.get("certificate_sig_alg")),
        "serial": _first(x509.get("certificate_serial")),
        "san_dns": [_cut(s) for s in sans[: cert_findings.NESTED_CAP]],
        "san_dns_total": len(sans),
        # Subject equal to issuer: self-issued. Self-SIGNED would also need the signature checked.
        "self_issued": bool(subject_full) and subject_full == issuer_full,
    }


# ---------------------------------------------------------------------------
# Reply checks
# ---------------------------------------------------------------------------


def _checked(reply: Any, what: str) -> dict:
    """A complete, well-formed reply, or CertQueryFailed."""
    if not isinstance(reply, dict):
        raise CertQueryFailed(f"{what}: malformed reply")
    if reply.get("timed_out"):
        raise CertQueryFailed(f"{what} timed out")
    shards = reply.get("_shards")
    if isinstance(shards, dict) and shards.get("failed"):
        raise CertQueryFailed(f"{what}: {shards.get('failed')} shard(s) failed")
    return reply


def _hits(reply: dict, what: str) -> list[dict]:
    hits = (reply.get("hits") or {}).get("hits")
    if not isinstance(hits, list) or any(
        not isinstance(h, dict) or "sort" not in h for h in hits
    ):
        raise CertQueryFailed(f"{what}: malformed hits")
    return hits


def _buckets(reply: dict, name: str, what: str) -> list[dict]:
    agg = (reply.get("aggregations") or {}).get(name)
    buckets = agg.get("buckets") if isinstance(agg, dict) else None
    if not isinstance(buckets, list):
        raise CertQueryFailed(f"{what}: malformed aggregation")
    if agg.get("sum_other_doc_count"):
        raise CertQueryFailed(f"{what}: incomplete aggregation")
    return buckets


def _value(fields: dict, name: str) -> Any:
    values = fields.get(name)
    if isinstance(values, list):
        return values[0] if values else None
    return values


def _chain(hit: dict) -> list[str]:
    """The ssl record's certificate chain in the order Zeek logged it (server's own first)."""
    source = hit.get("_source") or {}
    chain = ((source.get("zeek") or {}).get("ssl") or {}).get("cert_chain_fps")
    if chain is None:
        chain = source.get(_CHAIN)
    if isinstance(chain, str):
        chain = [chain]
    return [str(c) for c in chain or [] if c]


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------


class CertOverview:
    """One complete, consistent pass over a window's TLS sessions and their certificates."""

    def __init__(self, client: Any) -> None:
        self._client = client

    # -- OpenSearch I/O -------------------------------------------------------

    def _search(self, body: dict, budget: Budget, what: str) -> dict:
        budget.check(what)
        timeout = max(1.0, budget.remaining())
        body = {**body, "timeout": f"{int(timeout * 1000)}ms"}
        try:
            reply = self._client.search(body=body, request_timeout=timeout)
        except OpenSearchException as exc:
            logger.error("Failed to query %s: %s", what, exc)
            raise CertQueryFailed(f"{what} query failed") from exc
        return _checked(reply, what)

    def _open_pit(self, budget: Budget) -> str:
        budget.check("opening a snapshot")
        try:
            # A partial snapshot would silently drop the failed shards' sessions from every count
            reply = self._client.create_pit(
                index=NETWORK_INDEX,
                keep_alive=PIT_KEEP_ALIVE,
                allow_partial_pit_creation="false",
                request_timeout=max(1.0, budget.remaining()),
            )
        except OpenSearchException as exc:
            logger.error("Failed to open a point in time: %s", exc)
            raise CertQueryFailed("snapshot failed") from exc
        pit = _checked(reply, "snapshot").get("pit_id")
        if not pit:
            raise CertQueryFailed("snapshot failed: no pit_id")
        return str(pit)

    def _close_pit(self, pit: str) -> None:
        try:
            self._client.delete_pit(
                body={"pit_id": [pit]}, request_timeout=PIT_CLOSE_SECONDS
            )
        except (
            OpenSearchException
        ) as exc:  # it expires on its own; the figures are already safe
            logger.warning("Couldn't close point in time: %s", exc)

    # -- Steps ------------------------------------------------------------------

    def _session_pages(
        self, query: dict, pit: list[str], budget: Budget
    ) -> Iterator[list[dict]]:
        after = None
        while True:
            body: dict = {
                "size": PAGE_SIZE,
                "query": query,
                "_source": [_CHAIN],
                "docvalue_fields": [
                    *_SESSION_FIELDS,
                    {"field": "@timestamp", "format": "strict_date_optional_time"},
                ],
                "sort": [{"_shard_doc": "asc"}],
                "track_total_hits": False,
                "pit": {"id": pit[0], "keep_alive": PIT_KEEP_ALIVE},
            }
            if after is not None:
                body["search_after"] = after
            reply = self._search(body, budget, "certificate sessions")
            pit[0] = reply.get("pit_id") or pit[0]
            hits = _hits(reply, "certificate sessions")
            if hits:
                yield hits
            if len(hits) < PAGE_SIZE:
                return
            after = hits[-1]["sort"]

    def _tally(
        self,
        query: dict,
        pit: list[str],
        budget: Budget,
        keep: Callable[[str, str], bool] | None = None,
    ) -> tuple[dict, dict]:
        """Tallies of the sessions `query` matches; `keep(chain[0], time)` can drop some."""
        usage: dict[tuple, list] = {}
        clients: dict[tuple, int] = {}
        for hits in self._session_pages(query, pit, budget):
            for hit in hits:
                chain = _chain(hit)
                if not chain:
                    continue
                fields = hit.get("fields") or {}
                sni, server, port, client, status, version = (
                    _value(fields, f) for f in _SESSION_FIELDS
                )
                when = _value(fields, "@timestamp") or ""
                if keep and not keep(chain[0], when):
                    continue
                key = (chain[0], sni or None, server, port, status or None, version)
                cell = usage.get(key)
                if cell is None:
                    usage[key] = [1, when, when]
                else:
                    cell[0] += 1
                    if when and (not cell[1] or when < cell[1]):
                        cell[1] = when
                    if when > cell[2]:
                        cell[2] = when
                ckey = (chain[0], sni or None, server, port, client, status or None)
                clients[ckey] = clients.get(ckey, 0) + 1
            if len(usage) + len(clients) > MAX_KEYS:
                raise CertTooBig(
                    "too many distinct certificate uses to show for this window"
                )
        return usage, clients

    def _details(
        self, fingerprints: set[str], pit: list[str], budget: Budget
    ) -> dict[str, dict]:
        """The newest stored x509 record per fingerprint, at any time OpenSearch still holds."""
        details: dict[str, dict] = {}
        ordered = sorted(fingerprints)
        for i in range(0, len(ordered), DETAIL_CHUNK):
            chunk = ordered[i : i + DETAIL_CHUNK]
            body = {
                "size": 0,
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"event.provider": "zeek"}},
                            {"term": {"event.dataset": "x509"}},
                            {"terms": {_FINGERPRINT: chunk}},
                        ]
                    }
                },
                "aggs": {
                    "fps": {
                        # size >= candidates, so every bucket comes back
                        "terms": {
                            "field": _FINGERPRINT,
                            "size": len(chunk),
                            "shard_size": 2 * len(chunk),
                        },
                        "aggs": {
                            "latest": {
                                "top_hits": {
                                    "size": 1,
                                    "sort": [{"@timestamp": {"order": "desc"}}],
                                    "_source": ["zeek.x509"],
                                }
                            }
                        },
                    }
                },
                "pit": {"id": pit[0], "keep_alive": PIT_KEEP_ALIVE},
            }
            reply = self._search(body, budget, "certificate details")
            pit[0] = reply.get("pit_id") or pit[0]
            for bucket in _buckets(reply, "fps", "certificate details"):
                hits = ((bucket.get("latest") or {}).get("hits") or {}).get(
                    "hits"
                ) or []
                x509 = (
                    ((hits[0].get("_source") or {}).get("zeek") or {}).get("x509")
                    if hits
                    else None
                )
                if isinstance(x509, dict):
                    details[str(bucket.get("key"))] = x509_fields(x509)
        return details

    def _after_expiry(
        self,
        query: dict,
        usage: dict[tuple, list],
        details: dict[str, dict],
        pit: list[str],
        budget: Budget,
    ) -> tuple[dict, dict]:
        """Exact tallies of the sessions after each used-after-expiry certificate ran out.

        The main tally can't split a cell at a date it didn't know yet, so these certificates
        get one more scan of the same snapshot per DETAIL_CHUNK of them: sessions after the
        chunk's earliest expiry, each then kept only if it is after its own certificate's.
        """
        expired: dict[str, datetime] = {}
        for (fp, *_), (_, _, last) in usage.items():
            expiry = cert_findings.parse_time((details.get(fp) or {}).get("not_after"))
            used = cert_findings.parse_time(last)
            if expiry and used and used > expiry and fp not in expired:
                expired[fp] = expiry
        usage_after: dict[tuple, list] = {}
        clients_after: dict[tuple, int] = {}
        ordered = sorted(expired)
        for i in range(0, len(ordered), DETAIL_CHUNK):
            chunk = set(ordered[i : i + DETAIL_CHUNK])
            bool_q = query["bool"]
            after_q = {
                "bool": {
                    **bool_q,
                    "filter": [
                        *bool_q["filter"],
                        {"terms": {_CHAIN: sorted(chunk)}},
                        {
                            "range": {
                                "@timestamp": {
                                    "gt": min(expired[fp] for fp in chunk).isoformat(),
                                    "format": "strict_date_optional_time",
                                }
                            }
                        },
                    ],
                }
            }

            # The terms match a fingerprint anywhere in a chain; a session counts only for the
            # certificate it is credited to, and only after that certificate's own expiry
            def after_own_expiry(first: str, when: str, chunk: set = chunk) -> bool:
                at = cert_findings.parse_time(when)
                return first in chunk and at is not None and at > expired[first]

            u, c = self._tally(after_q, pit, budget, keep=after_own_expiry)
            usage_after.update(u)
            clients_after.update(c)
        return usage_after, clients_after

    # -- Public -----------------------------------------------------------------

    def overview(
        self,
        from_ts: str,
        to_ts: str,
        excluded_ips: list[str] | None = None,
        budget: Budget | None = None,
        pit_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Every figure the Certificates page shows, over complete data for [from_ts, to_ts]."""
        budget = budget or Budget()
        query: dict = {
            "bool": {
                "filter": [
                    {
                        "range": {
                            "@timestamp": {
                                "gte": from_ts,
                                "lte": to_ts,
                                "format": "strict_date_optional_time",
                            }
                        }
                    },
                    {"term": {"event.provider": "zeek"}},
                    {"term": {"event.dataset": "ssl"}},
                    {"exists": {"field": _CHAIN}},
                ]
            }
        }
        excluded = build_excluded_ips_filter(excluded_ips or [])
        if excluded:
            query["bool"]["must_not"] = excluded
        owned = pit_id is None
        pit = [pit_id or self._open_pit(budget)]
        try:
            usage, clients = self._tally(query, pit, budget)
            details = self._details({key[0] for key in usage}, pit, budget)
            expired = self._after_expiry(query, usage, details, pit, budget)
        finally:
            if owned:
                self._close_pit(pit[0])
        budget.check("building the certificate figures")
        built = cert_findings.build(
            usage, clients, details, now or datetime.now(timezone.utc), expired
        )
        return {**built, "from": from_ts, "to": to_ts}


# ---------------------------------------------------------------------------
# Reply shaping and encoding
# ---------------------------------------------------------------------------


def paginate(data: dict[str, Any], cap: int) -> dict[str, Any]:
    """Cap each list on its own, with totals, after every figure was computed on complete data.

    Certificates go out only as `details`: every certificate any returned site, finding or
    device row refers to, so a drawer never shows "unavailable" for one cut by a cap.
    """
    out = {
        k: v
        for k, v in data.items()
        if k not in ("sites", "certificates", "findings", "devices")
    }
    for name in ("sites", "findings", "devices"):
        rows = data.get(name) or []
        out[name] = rows[:cap]
        out[f"{name}_total"] = len(rows)
        out[f"{name}_truncated"] = len(rows) > cap
    by_fp = {c["fingerprint"]: c for c in data.get("certificates") or []}
    wanted = {fp for s in out["sites"] for fp in s["certificates"]}
    wanted |= {f["fingerprint"] for f in out["findings"]} | {
        d["fingerprint"] for d in out["devices"]
    }
    out["details"] = {fp: by_fp[fp] for fp in sorted(wanted) if fp in by_fp}
    return out


def encode_bounded(
    payload: Any, budget: Budget, max_bytes: int = MAX_REPLY_BYTES
) -> bytes:
    """JSON bytes, or CertTooBig / CertTooSlow before any partial body could be sent."""
    parts: list[bytes] = []
    size = 0
    for i, chunk in enumerate(json.JSONEncoder(ensure_ascii=False).iterencode(payload)):
        piece = chunk.encode("utf-8")
        size += len(piece)
        if size > max_bytes:
            raise CertTooBig("the certificate reply is too large for this window")
        if i % 1024 == 0:
            budget.check("encoding the certificate reply")
        parts.append(piece)
    budget.check("encoding the certificate reply")
    return b"".join(parts)
