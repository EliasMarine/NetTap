"""GET /api/alerts/rule/{name} — one Suricata rule over a window (the rule page).

The page is keyed by the exact rule name, as the Alerts list's signature= filter is (a term on
rule.name), and counts with the list's own query for ?signature=name&activity=…, so every figure
equals the list its link opens. A name can belong to several SIDs, so the rule's facts are given
per SID, each from that SID's newest alert, and only reach the page level when every SID agrees.

The addresses involved are found with one terms list per side, then every shown row is counted
exactly with per-address filters in the same snapshot. Which rows are shown is a bounded
selection (by source count plus destination count, so self-alerts weigh twice), and says so.
IPv4 addresses are split by the daemon's LAN rule; IPv6 ones are "unplaced", since that rule
has no IPv6.
"""

import ipaddress
import logging
import re
from datetime import timedelta
from typing import Any, Callable

from aiohttp import web

from api.alerts import (
    _alert_enrichment,
    activity_param,
    alert_query,
    rule_categories,
    severity_clauses,
    valid_suricata_category,
)
from api.drilldown_runner import (
    LAST_SEEN,
    LIST_CAP,
    chart_interval,
    chart_slots,
    either_side,
    install,
    iso_ms,
    json_error,
    lan_check,
    run_drilldown,
    timeline,
)
from api.suricata_categories import _SEVERITIES
from api.time_range import parse_time_range
from services import rule_explainer as rx
from services.alert_findings import is_credential_exposure
from storage.snapshot_search import (
    NETWORK_INDEX,
    Budget,
    QueryFailed,
    SnapshotSearch,
    doc_count,
    metric,
    total_hits,
)

logger = logging.getLogger("nettap.api.suricata_rule")

_DEFAULT_RANGE = timedelta(hours=24)
# OLD CODE START — over-engineering gate: the category page's validator and severity tiles, one copy each
# _RULE_NAME_MAX = 1_024  # rule.name as the list matches it (valid_suricata_category's limit)
# PICKED_BY = "source_plus_destination"  (nobody read it)
# _SEVERITIES = {"high": "1", "medium": "2", "low": "3", "info": "info"}
# _FIRST_LAST = {"first": {"min": {"field": "@timestamp"}}, "last": {"max": {"field": "@timestamp"}}}
# OLD CODE END
_TOP_SIDS = 10
SHOWN = {"devices": 100, "remotes": 20, "unplaced": 20}
EXACT_BATCH = 50  # addresses per exact-count search (three filters each)
_FIRST_LAST = {"first": {"min": {"field": "@timestamp"}}, **LAST_SEEN}
_FACTS = [
    "rule.category",
    "threat.technique.id",
    "threat.technique.name",
    "threat.tactic.id",
    "threat.tactic.name",
    "vulnerability.id",
    "tags",
    "suricata.alert.metadata.signature_severity",
    "suricata.alert.metadata.dbl",
]
_DBL_SUFFIX = ".dbl.ipfire.org"
_SLUG = re.compile(r"[a-z0-9-]{1,40}")


# OLD CODE START — over-engineering gate: the same rule as a raw Suricata category's
# def valid_rule_name(raw: object) -> str | None:
#     """A rule name exactly as given, or None: 1–1,024 characters, not only whitespace."""
#     if isinstance(raw, str) and 0 < len(raw) <= _RULE_NAME_MAX and raw.strip():
#         return raw
#     return None
# OLD CODE END
# A rule name exactly as given: 1–1,024 characters (the keyword's ignore_above), not only whitespace
valid_rule_name = valid_suricata_category


# OLD CODE START — review: no caller passed severity=
# def _query(from_ts, to_ts, name, activity, severity=""):
#     narrow, exclude = severity_clauses(severity)
#     return alert_query(from_ts, to_ts, [{"term": {"rule.name": name}}, *narrow], exclude, activity=activity)
# OLD CODE END
def _query(from_ts: str, to_ts: str, name: str, activity: bool) -> dict:
    """The list's query for signature=name and activity=."""
    return alert_query(
        from_ts, to_ts, [{"term": {"rule.name": name}}], activity=activity
    )


def _listed(value: Any) -> list[str]:
    """A stored field as a list of strings (a scalar is one, missing none)."""
    found = value if isinstance(value, list) else [value]
    return [str(v) for v in found if v is not None and str(v) != ""]


# OLD CODE START — review: paired after _listed dropped empties, so the lists could stop lining up
# def _paired(ids: list[str], names: list[str], pattern: re.Pattern) -> list[dict]:
#     lined_up = len(ids) == len(names)
#     paired = [{"id": tid, "name": names[i] if lined_up else None} for i, tid in enumerate(ids) if pattern.fullmatch(tid)]
#     return list({t["id"]: t for t in paired}.values())
# OLD CODE END
def _paired(ids: Any, names: Any, pattern: re.Pattern) -> list[dict]:
    """ATT&CK ids with their names, from Malcolm's raw parallel lists: paired by position first,
    then invalid ids dropped (so a name never shifts onto another id), each id once (two
    techniques under one tactic repeat the tactic, and the page keys on the id)."""
    raw_ids = ids if isinstance(ids, list) else [ids]
    raw_names = names if isinstance(names, list) else [names]
    lined_up = len(raw_ids) == len(raw_names)
    paired = [
        {
            "id": str(tid),
            "name": str(raw_names[i])
            if lined_up and raw_names[i] not in (None, "")
            else None,
        }
        for i, tid in enumerate(raw_ids)
        if tid is not None and pattern.fullmatch(str(tid))
    ]
    return list({t["id"]: t for t in paired}.values())


def _sid_facts(sid: str, alerts: int, src: dict, name: str) -> dict:
    """One SID's facts from its newest alert's _source."""
    rule = src.get("rule") or {}
    threat = src.get("threat") or {}
    technique = threat.get("technique") or {}
    tactic = threat.get("tactic") or {}
    meta = ((src.get("suricata") or {}).get("alert") or {}).get("metadata") or {}
    et_ratings = _listed(meta.get("signature_severity"))
    # OLD CODE: techniques = _paired(_listed(technique.get("id")), _listed(technique.get("name")), …) (and tactics; raw lists now)
    techniques = _paired(technique.get("id"), technique.get("name"), rx.TECHNIQUE_ID)
    tactics = _paired(tactic.get("id"), tactic.get("name"), rx.TACTIC_ID)
    cves = [
        c
        for c in _listed((src.get("vulnerability") or {}).get("id"))
        if rx.CVE_ID.fullmatch(c)
    ]
    cisa_kev = "CISA_KEV" in _listed(src.get("tags"))
    dbl = [
        v.removesuffix(_DBL_SUFFIX)
        for v in _listed(meta.get("dbl"))
        if v.endswith(_DBL_SUFFIX) and _SLUG.fullmatch(v.removesuffix(_DBL_SUFFIX))
    ]
    credential = is_credential_exposure(name, et_ratings)
    return {
        "sid": sid,
        "alerts": alerts,
        # OLD CODE: "categories": _listed(rule.get("category")), (each links to its category page now)
        "categories": rule_categories(rule),
        "et_ratings": et_ratings,
        "techniques": techniques,
        "tactics": tactics,
        "cves": cves,
        "cisa_kev": cisa_kev,
        "dbl_lists": dbl,
        "credential": credential,
        # OLD CODE: "advice": rx.sid_advice(_alert_enrichment.sid_text(sid), name, et_ratings), (the curated text must name this rule)
        # OLD CODE: "advice": rx.sid_advice(_alert_enrichment.sid_text(sid, name), name, et_ratings), (gate: no helper)
        "advice": _alert_enrichment.sid_text(sid, name)
        or (rx.CREDENTIAL if credential else None),
        "learn_more": rx.sid_links(techniques, tactics, cves, cisa_kev, credential),
    }


def _explained(
    name: str, severity: int, rules: list[dict], agreed: bool
) -> tuple[dict, list]:
    """(explanation, links) for the page: the name's, unless every SID agrees on its own."""
    explanation = rx.explain_name(name, severity)
    links = rx.name_links(name, explanation["family"])
    if not agreed or not rules:
        return explanation, links
    if len(rules) == 1:
        only = rules[0]
        links = rx.merged_links(only["learn_more"], links)
        if rx.is_own_sid(only["sid"]):
            return rx.own_rule(), links
        if only["advice"]:
            family = "credential" if only["credential"] else explanation["family"]
            return {"family": family, **only["advice"]}, links
        return explanation, links
    if all(r["credential"] for r in rules):
        return rx.credential_advice(), links
    return explanation, links


def _group_of(ip: str, is_lan: Callable[[str], bool]) -> str | None:
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if parsed.version == 6:
        return "unplaced"
    return "devices" if is_lan(ip) else "remotes"


def _discover(
    snap: SnapshotSearch, base: dict, field: str, what: str
) -> tuple[dict, bool]:
    """{address: alerts on that side} for one side, and False when the list stopped at its cap."""
    buckets, complete = snap.groups(
        base, [{"ip": {"terms": {"field": field}}}], None, what, max_buckets=LIST_CAP
    )
    if not complete:
        logger.info("Rule page: the %s list stopped at its cap", what)
    return {b["key"]["ip"]: doc_count(b, what) for b in buckets}, complete


def _exact(snap: SnapshotSearch, base: dict, ips: list[str]) -> dict[str, dict]:
    """Every figure of each address's row, counted exactly: as source, as target, at either end
    (the list's ip= filter), first and last seen."""
    what = "rule addresses"
    rows: dict[str, dict] = {}
    for start in range(0, len(ips), EXACT_BATCH):
        chunk = ips[start : start + EXACT_BATCH]
        aggs: dict = {}
        for i, ip in enumerate(chunk):
            aggs[f"s{i}"] = {"filter": {"term": {"source.ip": ip}}}
            aggs[f"d{i}"] = {"filter": {"term": {"destination.ip": ip}}}
            aggs[f"e{i}"] = {"filter": either_side(ip), "aggs": _FIRST_LAST}
        found = snap.search(
            {"size": 0, "query": base, "aggs": aggs}, what, tuple(aggs)
        )["aggregations"]
        for i, ip in enumerate(chunk):
            either = found[f"e{i}"]
            rows[ip] = {
                "ip": ip,
                "as_source": doc_count(found[f"s{i}"], what),
                "as_target": doc_count(found[f"d{i}"], what),
                "alerts": doc_count(either, what),
                "first_seen": iso_ms(metric(either, "first", what)),
                "last_seen": iso_ms(metric(either, "last", what)),
            }
    return rows


def _involved(snap: SnapshotSearch, base: dict, is_lan: Callable[[str], bool]) -> dict:
    """The devices, remote and unplaced addresses of these alerts, each row exact."""
    sources, src_complete = _discover(snap, base, "source.ip", "rule sources")
    targets, dst_complete = _discover(snap, base, "destination.ip", "rule targets")
    complete = src_complete and dst_complete
    candidates: dict[str, list[tuple[int, str]]] = {g: [] for g in SHOWN}
    for ip in sources.keys() | targets.keys():
        group = _group_of(ip, is_lan)
        if group:
            candidates[group].append((sources.get(ip, 0) + targets.get(ip, 0), ip))
    shown = {
        g: [ip for _, ip in sorted(found, key=lambda c: (-c[0], c[1]))[: SHOWN[g]]]
        for g, found in candidates.items()
    }
    rows = _exact(snap, base, [ip for ips in shown.values() for ip in ips])
    return {
        g: {
            "rows": sorted(
                (rows[ip] for ip in ips), key=lambda r: (-r["alerts"], r["ip"])
            ),
            "distinct": len(candidates[g]) if complete else None,
            "examined": len(candidates[g]),
            "complete": complete,
            # OLD CODE: "picked_by": PICKED_BY, (nobody read it)
        }
        for g, ips in shown.items()
    }


def suricata_rule_figures(
    client: Any,
    name: str,
    activity: bool,
    from_ts: str,
    to_ts: str,
    slots: dict,
    is_lan: Callable[[str], bool],
    budget: Budget,
) -> dict:
    """Every figure the rule page shows, over one snapshot."""
    base = _query(from_ts, to_ts, name, activity)
    what = "rule alerts"
    severity_aggs = {
        f"sev_{tile}": {
            "filter": {
                "bool": dict(zip(("filter", "must_not"), severity_clauses(code)))
            }
        }
        for tile, code in _SEVERITIES.items()
    }
    aggs = {
        "timeline": slots,
        **_FIRST_LAST,
        **severity_aggs,
        "no_sid": {
            "filter": {"bool": {"must_not": [{"exists": {"field": "rule.id"}}]}}
        },
        "sids": {
            "terms": {"field": "rule.id", "size": _TOP_SIDS},
            "aggs": {
                "newest": {
                    "top_hits": {
                        "size": 1,
                        "sort": [{"@timestamp": {"order": "desc"}}],
                        "_source": _FACTS,
                    }
                }
            },
        },
    }
    with SnapshotSearch(client, NETWORK_INDEX, budget) as snap:
        reply = snap.search(
            {"size": 0, "track_total_hits": True, "query": base, "aggs": aggs},
            what,
            tuple(aggs),
        )
        found = reply["aggregations"]
        total = total_hits(reply, what)
        severity = {tile: doc_count(found[f"sev_{tile}"], what) for tile in _SEVERITIES}
        # Only a multi-valued severity could do this; tiles that don't add up are wrong
        if sum(severity.values()) != total:
            raise QueryFailed("the severity counts don't add up to the total")
        other = snap.count(
            _query(from_ts, to_ts, name, not activity), "rule other list"
        )
        sid_buckets = found["sids"].get("buckets")
        if not isinstance(sid_buckets, list):
            raise QueryFailed(f"{what}: malformed aggregation")
        rules = []
        for b in sid_buckets:
            hits = ((b.get("newest") or {}).get("hits") or {}).get("hits") or [{}]
            rules.append(
                _sid_facts(
                    str(b["key"]),
                    doc_count(b, what),
                    hits[0].get("_source") or {},
                    name,
                )
            )
        rules_complete = found["sids"].get("sum_other_doc_count", 0) == 0
        no_sid = doc_count(found["no_sid"], what)
        involved = _involved(snap, base, is_lan)
        without = {
            "bool": {
                "filter": [base],
                "must_not": [
                    {"exists": {"field": "source.ip"}},
                    {"exists": {"field": "destination.ip"}},
                ],
            }
        }
        missing = snap.count(without, "rule alerts without addresses")
    levels = ("high", "medium", "low")
    # The most common Suricata severity (the higher on a tie); 3 when none has one
    dominant = (
        max((1, 2, 3), key=lambda s: (severity[levels[s - 1]], -s))
        if any(severity[level] for level in levels)
        else 3
    )
    explanation, links = _explained(
        name, dominant, rules, rules_complete and no_sid == 0
    )
    return {
        "name": name,
        "from": from_ts,
        "to": to_ts,
        "activity": activity,
        "total": total,
        "counted_total": other if activity else total,
        "activity_total": total if activity else other,
        "severity": severity,
        "timeline": timeline(reply),
        "first_seen": iso_ms(metric(found, "first", what)),
        "last_seen": iso_ms(metric(found, "last", what)),
        "rules": rules,
        "rules_complete": rules_complete,
        "no_sid": no_sid,
        "explanation": explanation,
        "learn_more": links,
        **involved,
        "missing_address": missing,
    }


async def handle_suricata_rule(request: web.Request) -> web.Response:
    """GET /api/alerts/rule/{name}?from=&to=&interval=&activity= — the rule page's figures."""
    name = valid_rule_name(request.match_info["name"])
    if name is None:
        logger.debug("Rule page: invalid name")
        return json_error("That isn't a rule name.", 400)
    activity = activity_param(request)
    if activity is None:
        return json_error("activity must be true or false", 400)
    from_ts, to_ts = parse_time_range(request, _DEFAULT_RANGE)
    interval = chart_interval(request, from_ts, to_ts)
    slots = chart_slots(from_ts, to_ts, interval)
    if slots is None:
        return json_error("This time range is too long; choose a shorter one.", 400)
    client, is_lan = request.app["drill_client"], lan_check(request.app)
    return await run_drilldown(
        request,
        lambda budget: {
            **suricata_rule_figures(
                client, name, activity, from_ts, to_ts, slots, is_lan, budget
            ),
            "interval": interval,
        },
        "a Suricata rule",
    )


def register_suricata_rule_routes(app: web.Application, client: Any) -> None:
    install(app, client)
    # .+ keeps a name with a "/" (aiohttp decodes %2F before routing), as the category route does
    app.router.add_get("/api/alerts/rule/{name:.+}", handle_suricata_rule)
    logger.info("Suricata rule API routes registered (1 endpoint)")
