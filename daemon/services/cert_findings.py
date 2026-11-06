"""
Certificate facts, sites, findings and device endpoints from exact session tallies (NET-154).

Pure functions: no OpenSearch, no clock reads (callers pass `now`). The inputs come from
services/cert_overview.py, which credits every ssl session to the first certificate of its
ordered chain and tallies:

    usage[(fp, sni, server_ip, port, status, version)] = [sessions, first_iso, last_iso]
    clients[(fp, sni, server_ip, port, client_ip, status)] = sessions
    details[fp] = x509 fields (x509_fields()), absent when no x509 record is stored
    expired = (usage, clients) of only the sessions after a certificate's not_after

A finding counts, dates and names only the sessions it is about: the failing ones for a
verification finding, the ones after expiry for expired-at-use.

A missing field is None. Times are OpenSearch's strict_date_optional_time strings, which
sort correctly as text because they all come from the same formatter.
"""

import ipaddress
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

UsageKey = tuple[str, str | None, str | None, Any, str | None, str | None]
ClientKey = tuple[str, str | None, str | None, Any, str | None, str | None]
Cell = tuple[
    int, str, str, str | None, str | None, str | None
]  # n, first, last, status, version, server

UNCHECKED = "unchecked"  # no validation_status on the session
EXPIRY_WARN_DAYS = 30
NESTED_CAP = 200
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

# Networks a home owner's own servers sit on (RFC 1918, link-local, IPv6 ULA and link-local)
_LOCAL_NETS = [
    ipaddress.ip_network(n)
    for n in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "fc00::/7",
        "fe80::/10",
    )
]


# ---------------------------------------------------------------------------
# Small facts
# ---------------------------------------------------------------------------


def scope_of(ip: str | None) -> str:
    """'local' for a private/link-local address, 'public' for any other, 'unknown' when absent."""
    if not ip:
        return "unknown"
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return "unknown"
    return "local" if any(addr in net for net in _LOCAL_NETS) else "public"


def failed(status: str | None) -> bool:
    """A recorded verification failure: present, non-empty and not 'ok'. Unchecked never fails."""
    return bool(status) and status != "ok" and status != UNCHECKED


def is_expiry(status: str | None) -> bool:
    return failed(status) and "expired" in str(status).lower()


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def authority(detail: dict | None) -> str | None:
    """The issuing organisation, else the issuer CN; None when the certificate's details are unknown."""
    if not detail:
        return None
    return detail.get("issuer_org") or detail.get("issuer") or None


def weaknesses(detail: dict | None) -> list[str]:
    """SHA-1/MD5 signatures and RSA/DSA keys under 2,048 bits, as short labels."""
    if not detail:
        return []
    found = []
    sig = str(detail.get("sig_alg") or "").lower()
    if "md5" in sig:
        found.append("MD5 signature")
    elif "sha1" in sig or "sha-1" in sig:
        found.append("SHA-1 signature")
    key_type = str(detail.get("key_type") or "").lower()
    length = detail.get("key_length")
    if (
        key_type in ("rsa", "dsa")
        and isinstance(length, (int, float))
        and 0 < length < 2048
    ):
        found.append(f"{int(length)}-bit {key_type.upper()} key")
    return found


def site_id(sni: str | None, server: str | None) -> str:
    """A site is the server name asked for; sessions without one are grouped per server address."""
    return sni if sni else f"no-sni:{server or 'unknown'}"


def _capped(values: Iterable[Any], cap: int = NESTED_CAP) -> tuple[list[Any], int]:
    items = list(values)
    return items[:cap], len(items)


def _add_status(statuses: dict[str, int], status: str | None, n: int) -> None:
    key = status or UNCHECKED
    statuses[key] = statuses.get(key, 0) + n


def _verified(statuses: dict[str, int]) -> bool:
    """At least one session, and every session's status is 'ok'."""
    return bool(statuses) and set(statuses) == {"ok"}


# ---------------------------------------------------------------------------
# Tallies → per-certificate, per-site and per-endpoint facts
# ---------------------------------------------------------------------------


class _Tally:
    """Sessions, first/last, statuses and versions for one grouping."""

    __slots__ = (
        "sessions",
        "first",
        "last",
        "statuses",
        "versions",
        "servers",
        "clients",
    )

    def __init__(self) -> None:
        self.sessions = 0
        self.first = ""
        self.last = ""
        self.statuses: dict[str, int] = {}
        self.versions: dict[str, int] = {}
        self.servers: dict[str, int] = {}
        self.clients: dict[str, int] = {}

    def add(
        self,
        n: int,
        first: str,
        last: str,
        status: str | None,
        version: str | None,
        server: str | None,
    ) -> None:
        self.sessions += n
        if first and (not self.first or first < self.first):
            self.first = first
        if last and last > self.last:
            self.last = last
        _add_status(self.statuses, status, n)
        if version:
            self.versions[version] = self.versions.get(version, 0) + n
        if server:
            self.servers[server] = self.servers.get(server, 0) + n


def _busiest(counts: dict[str, int]) -> list[str]:
    return [k for k, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def _tally_of(cells: Iterable[Cell], keep: Any) -> _Tally:
    """One tally over the usage cells whose status `keep` accepts."""
    t = _Tally()
    for n, first, last, status, version, server in cells:
        if keep(status):
            t.add(n, first, last, status, version, server)
    return t


def _merge(counts: Iterable[dict[str, int]]) -> dict[str, int]:
    total: Counter[str] = Counter()
    for c in counts:
        total.update(c)
    return dict(total)


def build(
    usage: dict[UsageKey, list],
    clients: dict[ClientKey, int],
    details: dict[str, dict],
    now: datetime,
    expired: tuple[dict[UsageKey, list], dict[ClientKey, int]] | None = None,
) -> dict[str, Any]:
    """Every certificate, site, finding, device endpoint and summary figure, over complete data."""
    by_cert: dict[str, _Tally] = defaultdict(_Tally)
    by_site: dict[str, _Tally] = defaultdict(_Tally)
    by_pair: dict[tuple[str, str], _Tally] = defaultdict(_Tally)  # (site, fp)
    public_cells: dict[tuple[str, str], list[Cell]] = defaultdict(
        list
    )  # non-local servers only
    by_endpoint: dict[tuple[str, Any, str], dict[str, _Tally]] = defaultdict(
        lambda: defaultdict(_Tally)
    )
    site_names: dict[str, tuple[str | None, str | None]] = {}
    cert_sites: dict[str, dict[str, int]] = defaultdict(dict)
    site_certs: dict[str, dict[str, int]] = defaultdict(dict)

    for (fp, sni, server, port, status, version), (n, first, last) in usage.items():
        sid = site_id(sni, server)
        site_names.setdefault(sid, (sni, None if sni else server))
        for tally in (by_cert[fp], by_site[sid], by_pair[(sid, fp)]):
            tally.add(n, first, last, status, version, server)
        if scope_of(server) != "local":
            public_cells[(sid, fp)].append((n, first, last, status, version, server))
        else:
            by_endpoint[(server, port, sid)][fp].add(
                n, first, last, status, version, server
            )
        cert_sites[fp][sid] = cert_sites[fp].get(sid, 0) + n
        site_certs[sid][fp] = site_certs[sid].get(fp, 0) + n

    # (site, fp) → (public, status) → client → sessions
    pair_clients: dict[tuple[str, str], dict[tuple[bool, str], dict[str, int]]] = (
        defaultdict(lambda: defaultdict(dict))
    )
    # (server, port, site) → fp → client → sessions, for your network's servers
    endpoint_clients: dict[tuple[str, Any, str], dict[str, dict[str, int]]] = (
        defaultdict(lambda: defaultdict(dict))
    )
    for (fp, sni, server, port, client, status), n in clients.items():
        if client:
            sid = site_id(sni, server)
            public = scope_of(server) != "local"
            for counts in (
                by_cert[fp].clients,
                by_site[sid].clients,
                pair_clients[(sid, fp)][(public, status or UNCHECKED)],
            ):
                counts[client] = counts.get(client, 0) + n
            if not public:
                counts = endpoint_clients[(server, port, sid)][fp]
                counts[client] = counts.get(client, 0) + n

    expired_usage, expired_client_tally = expired or ({}, {})
    by_pair_expired: dict[tuple[str, str], _Tally] = defaultdict(_Tally)
    for (fp, sni, server, _port, status, version), (
        n,
        first,
        last,
    ) in expired_usage.items():
        by_pair_expired[(site_id(sni, server), fp)].add(
            n, first, last, status, version, server
        )
    expired_clients: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
    for (fp, sni, server, _port, client, _status), n in expired_client_tally.items():
        if client:
            counts = expired_clients[(site_id(sni, server), fp)]
            counts[client] = counts.get(client, 0) + n

    pair_findings = _findings(
        by_pair, public_cells, by_pair_expired, site_certs, details, site_names
    )
    devices, local_fps, device_findings = _devices(
        by_endpoint, details, site_names, now, pair_findings
    )
    devices = [
        {
            **d,
            **_clients_of(
                _merge(
                    endpoint_clients.get(
                        (d["server"], d["port"], d["site_id"]), {}
                    ).values()
                )
            ),
        }
        for d in devices
    ]
    findings = sorted(
        (
            _with_clients(f, pair_clients, endpoint_clients, expired_clients)
            for f in pair_findings + device_findings
        ),
        key=_finding_order,
    )
    worst = _worst_by_site(findings)

    certificates = [
        _cert_row(fp, tally, details.get(fp), _busiest(cert_sites[fp]), site_names, now)
        for fp, tally in by_cert.items()
    ]
    certificates.sort(key=lambda c: c["last_seen"], reverse=True)
    sites = [
        _site_row(
            sid,
            tally,
            site_names[sid],
            _busiest(site_certs[sid]),
            details,
            worst.get(sid),
        )
        for sid, tally in by_site.items()
    ]
    sites.sort(key=lambda s: (-s["sessions"], s["id"]))

    sessions = sum(t.sessions for t in by_cert.values())
    with_details = sum(t.sessions for fp, t in by_cert.items() if fp in details)
    known_days = [d["days_left"] for d in devices if d["days_left"] is not None]
    severities = {"high": 0, "medium": 0, "low": 0}
    for f in findings:
        severities[f["severity"]] += 1
    summary = {
        "certificates": len(by_cert),
        "certificates_without_details": sum(1 for fp in by_cert if fp not in details),
        "sites": len(by_site),
        "sessions": sessions,
        "sessions_with_details": with_details,
        "sessions_without_details": sessions - with_details,
        "findings": {**severities, "total": len(findings)},
        "local_certificates": len(local_fps),
        "local_endpoints": len(devices),
        "soonest_local_expiry_days": min(known_days) if known_days else None,
    }
    return {
        "summary": summary,
        "certificates": certificates,
        "sites": sites,
        "findings": findings,
        "devices": devices,
        "quiet_switches": _quiet_switches(site_certs, by_pair, details, site_names),
    }


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def _status_now(detail: dict | None, now: datetime) -> tuple[str, int | None]:
    """The legacy status and whole days left, judged against now (documented as such)."""
    expiry = parse_time((detail or {}).get("not_after"))
    if detail and detail.get("self_issued"):
        return "self-signed", (expiry - now).days if expiry else None
    if expiry is None:
        return "valid", None
    if expiry <= now:
        return "expired", (expiry - now).days
    if expiry <= now + timedelta(days=EXPIRY_WARN_DAYS):
        return "expiring", (expiry - now).days
    return "valid", (expiry - now).days


def _cert_row(
    fp: str,
    t: _Tally,
    detail: dict | None,
    sites: list[str],
    names: dict,
    now: datetime,
) -> dict[str, Any]:
    status, days = _status_now(detail, now)
    named = [names[s][0] for s in sites if names[s][0]]
    servers = _busiest(t.servers)
    clients = _busiest(t.clients)
    site_list, site_total = _capped(sites)
    server_list, server_total = _capped(servers)
    client_list, client_total = _capped(clients)
    d = detail or {}
    return {
        "fingerprint": fp,
        "details_available": detail is not None,
        **{
            k: d.get(k, "" if k not in ("key_length", "san_dns") else None)
            for k in _DETAIL_KEYS
        },
        "san_dns": d.get("san_dns") or [],
        "self_signed": bool(d.get("self_issued")),
        "authority": authority(detail),
        "sessions": t.sessions,
        "first_seen": t.first,
        "last_seen": t.last,
        "statuses": dict(t.statuses),
        "verified": _verified(t.statuses),
        "tls_versions": dict(t.versions),
        "sites": site_list,
        "sites_total": site_total,
        "servers": server_list,
        "servers_total": server_total,
        "clients": client_list,
        "clients_total": client_total,
        # Fields the older endpoints and web type already had, now from exact tallies
        "_id": fp,
        "hash_sha256": fp,
        "domain": named[0] if named else d.get("subject_cn") or "",
        "server_name": named[0] if named else "",
        "server_names": named[:NESTED_CAP],
        "source_ip": clients[0] if clients else "",
        "destination_ip": servers[0] if servers else "",
        "destination_port": "",
        "tls_version": _busiest(t.versions)[0] if t.versions else "",
        "validation_status": _busiest(t.statuses)[0] if t.statuses else "",
        "times_seen": t.sessions,
        "timestamp": t.last,
        "days_until_expiry": days,
        "status": status,
    }


_DETAIL_KEYS = (
    "subject",
    "subject_cn",
    "subject_full",
    "issuer",
    "issuer_org",
    "issuer_full",
    "not_before",
    "not_after",
    "key_type",
    "key_length",
    "sig_alg",
    "serial",
)


def _site_row(
    sid: str, t: _Tally, name: tuple, certs: list[str], details: dict, worst: str | None
) -> dict[str, Any]:
    scopes = {scope_of(s) for s in t.servers} or {"unknown"}
    cert_list, cert_total = _capped(certs)
    client_list, client_total = _capped(_busiest(t.clients))
    server_list, server_total = _capped(_busiest(t.servers))
    authorities = sorted({a for fp in certs if (a := authority(details.get(fp)))})
    return {
        "id": sid,
        "name": name[0],
        "server": name[1],
        "sessions": t.sessions,
        "first_seen": t.first,
        "last_seen": t.last,
        "statuses": dict(t.statuses),
        "verified": _verified(t.statuses),
        "scope": scopes.pop() if len(scopes) == 1 else "mixed",
        "certificates": cert_list,
        "certificates_total": cert_total,
        "clients": client_list,
        "clients_total": client_total,
        "servers": server_list,
        "servers_total": server_total,
        "authorities": authorities,
        "worst": worst,
    }


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def _finding(
    kind: str, severity: str, sid: str, fp: str, names: dict, t: _Tally, **extra: Any
) -> dict[str, Any]:
    sni, server = names[sid]
    servers = _busiest(t.servers)
    return {
        "id": f"{kind}:{sid}:{fp}",
        "kind": kind,
        "severity": severity,
        "site_id": sid,
        "site": sni,
        "server": servers[0] if servers else server,
        "servers": servers[:NESTED_CAP],
        "fingerprint": fp,
        "sessions": t.sessions,
        "last_seen": t.last,
        **extra,
    }


def _clients_of(counts: dict[str, int]) -> dict[str, Any]:
    names, total = _capped(_busiest(counts))
    return {"clients": names, "clients_total": total}


def _with_clients(
    f: dict, pair_clients: dict, endpoint_clients: dict, expired_clients: dict
) -> dict[str, Any]:
    """The finding plus the devices whose sessions it counts, busiest first."""
    kind, pair = f["kind"], (f["site_id"], f["fingerprint"])
    if kind == "device-expiry":
        endpoint = endpoint_clients.get((f["server"], f["port"], f["site_id"]), {})
        counts = endpoint.get(f["fingerprint"], {})
    elif kind == "expired-at-use":
        counts = expired_clients.get(pair, {})
    elif kind == "weak":
        counts = _merge(pair_clients.get(pair, {}).values())
    else:  # verification findings: the failing sessions to servers outside your network
        counts = _merge(
            c
            for (public, status), c in pair_clients.get(pair, {}).items()
            if public and status in f["failed"]
        )
    return {**f, **_clients_of(counts)}


def _finding_order(f: dict) -> tuple:
    return (
        _SEVERITY_ORDER[f["severity"]],
        f["site"] or f["server"] or "",
        f["kind"],
        f["id"],
    )


def _not_expiry_failure(status: str | None) -> bool:
    return failed(status) and not is_expiry(status)


def _findings(
    by_pair: dict,
    public_cells: dict,
    by_pair_expired: dict,
    site_certs: dict,
    details: dict,
    names: dict,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for (sid, fp), cells in public_cells.items():
        bad = _tally_of(cells, _not_expiry_failure)
        if bad.sessions:
            mine = authority(details.get(fp))
            other = _verified_other_authority(
                sid, fp, mine, site_certs, by_pair, details
            )
            findings.append(
                _finding(
                    "unverified-alongside-verified" if other else "unverified",
                    "high" if other else "medium",
                    sid,
                    fp,
                    names,
                    bad,
                    failed=dict(bad.statuses),
                    authority=mine,
                    other_authority=other,
                )
            )
    for sid, fp in by_pair:
        after = by_pair_expired.get((sid, fp))
        gone = _tally_of(public_cells.get((sid, fp), []), is_expiry)
        if after and after.sessions:
            findings.append(
                _finding(
                    "expired-at-use",
                    "medium",
                    sid,
                    fp,
                    names,
                    after,
                    not_after=(details.get(fp) or {}).get("not_after"),
                )
            )
        elif gone.sessions:
            findings.append(
                _finding(
                    "chain-expired",
                    "medium",
                    sid,
                    fp,
                    names,
                    gone,
                    failed=dict(gone.statuses),
                )
            )
    seen_weak: set[str] = set()
    for (sid, fp), t in sorted(by_pair.items(), key=lambda kv: -kv[1].sessions):
        weak = weaknesses(details.get(fp))
        if weak and fp not in seen_weak:
            seen_weak.add(fp)
            findings.append(_finding("weak", "low", sid, fp, names, t, weaknesses=weak))
    return findings


def _verified_other_authority(
    sid: str, fp: str, mine: str | None, site_certs: dict, by_pair: dict, details: dict
) -> str | None:
    """Another certificate at this site, from a different known authority, verified in every session."""
    if mine is None:
        return None
    for other in sorted(site_certs.get(sid, {})):
        theirs = authority(details.get(other))
        if (
            other != fp
            and theirs
            and theirs != mine
            and _verified(by_pair[(sid, other)].statuses)
        ):
            return theirs
    return None


def _worst_by_site(findings: list[dict]) -> dict[str, str]:
    worst: dict[str, str] = {}
    for f in findings:
        current = worst.get(f["site_id"])
        if current is None or _SEVERITY_ORDER[f["severity"]] < _SEVERITY_ORDER[current]:
            worst[f["site_id"]] = f["severity"]
    return worst


# ---------------------------------------------------------------------------
# Your network's endpoints
# ---------------------------------------------------------------------------


def _devices(
    by_endpoint: dict,
    details: dict,
    names: dict,
    now: datetime,
    pair_findings: list[dict],
) -> tuple[list[dict[str, Any]], set[str], list[dict[str, Any]]]:
    """One row per (server IP, port, site) on your network, for the certificate it presented last."""
    rows: list[dict[str, Any]] = []
    local_fps: set[str] = set()
    found: list[dict[str, Any]] = []
    expired_at_use = {
        (f["site_id"], f["fingerprint"])
        for f in pair_findings
        if f["kind"] == "expired-at-use"
    }
    for (server, port, sid), per_cert in by_endpoint.items():
        local_fps.update(per_cert)
        fp, t = max(per_cert.items(), key=lambda kv: (kv[1].last, kv[0]))
        detail = details.get(fp)
        expiry = parse_time((detail or {}).get("not_after"))
        days = (expiry - now).days if expiry else None
        statuses: dict[str, int] = {}
        for tally in per_cert.values():
            for s, n in tally.statuses.items():
                statuses[s] = statuses.get(s, 0) + n
        row = {
            "id": f"{server}:{port}:{sid}",
            "server": server,
            "port": port,
            "site_id": sid,
            "site": names[sid][0],
            "fingerprint": fp,
            "details_available": detail is not None,
            "authority": authority(detail),
            "not_after": (detail or {}).get("not_after") or None,
            "days_left": days,
            "self_signed": bool((detail or {}).get("self_issued")),
            "statuses": statuses,
            "verified": _verified(statuses),
            "sessions": sum(x.sessions for x in per_cert.values()),
            "last_seen": max(x.last for x in per_cert.values()),
            "certificates_total": len(per_cert),
        }
        rows.append(row)
        due = expiry is not None and expiry <= now + timedelta(days=EXPIRY_WARN_DAYS)
        if due and (sid, fp) not in expired_at_use:
            found.append(
                _finding(
                    "device-expiry",
                    "low",
                    sid,
                    fp,
                    names,
                    t,
                    id=f"device-expiry:{server}:{port}:{sid}:{fp}",  # one per endpoint, so two ports never collide
                    server=server,
                    port=port,
                    not_after=detail["not_after"],
                    days_left=days,
                )
            )
    rows.sort(
        key=lambda r: (
            r["days_left"] is None,
            r["days_left"] if r["days_left"] is not None else 0,
            r["server"] or "",
        )
    )
    return rows, local_fps, found


def _quiet_switches(
    site_certs: dict, by_pair: dict, details: dict, names: dict
) -> list[dict[str, Any]]:
    """Sites served by more than one authority in the window, where every certificate verified."""
    quiet = []
    for sid, certs in site_certs.items():
        auths = {authority(details.get(fp)) for fp in certs}
        if None in auths or len(auths) < 2:
            continue
        if all(_verified(by_pair[(sid, fp)].statuses) for fp in certs):
            quiet.append(
                {
                    "site_id": sid,
                    "site": names[sid][0],
                    "server": names[sid][1],
                    "authorities": sorted(auths),
                    "certificates": list(certs)[:NESTED_CAP],
                }
            )
    quiet.sort(key=lambda q: q["site"] or q["server"] or "")
    return quiet
