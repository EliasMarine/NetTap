"""Who each alert is about, and what it is evidence of (NET-209).

The rules and their sources are in Debugging/THREAT-SCORING.md; rule numbers below refer to it.

Every counted alert with a LAN party is read one instant at a time and charged to exactly one
finding: a LAN device's own traffic, an attempt against a LAN device, or nobody. An alert toward a
LAN address is the device's own traffic when the device opened the connection: the opener is the
source of the Zeek conn record with the alert's community ID whose time span contains the alert.
A community ID is a direction-less hash of the tuple with no time, so it repeats when a tuple is
reused, and the time has to match as well.
"""

import ipaddress
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from services.excluded_ips import RFC1918_CIDRS
from storage.all_buckets import all_buckets
from storage.snapshot_search import QueryFailed

# ET's IP-list rules are `alert ip [list] any -> $HOME_NET any` with no flow keyword, so they also
# fire on replies to our own connections; they are not evidence of an attack by themselves (rule 8)
REPUTATION_PREFIXES = (
    "ET DROP ",
    "ET DSHIELD",
    "ET CINS ",
    "ET COMPROMISED ",
    "ET TOR ",
    "ET 3CORESEC ",
)
# A reputation hit on a connection the device opened counts, as Minor at most (rule 8)
REPUTATION_OWN_SEVERITY = 3
# An attempt against a device weighs at most "low" on the Threats page (rule 4, NetTap's policy)
ATTEMPT_MAX_WEIGHT = 0.5
# Zeek and Suricata stamp the same packets from separate processes: a little slack (G11: 1 ms)
CONN_SLACK_MS = 10_000
# Kill chain: each step at most this long after the previous one (NetTap's choice, see the brief)
CHAIN_STEP_MS = 24 * 3600 * 1000
# Attempts against a device can only be these stages: reconnaissance, exploit attempt
ATTEMPT_STAGES = {1, 2}

_INSTANT_PAGE = 10_000  # small buckets with no sub-aggregations
_CID_CHUNK = 10_000  # under index.max_terms_count (65,536)
_COUNTED = 5  # severities below this count


def is_reputation(signature: str | None) -> bool:
    """True for ET's IP reputation-list rules (DROP, DShield, CINS, COMPROMISED, TOR, 3CORESec)."""
    return (signature or "").upper().startswith(REPUTATION_PREFIXES)


def lan_test(cidrs: list[str] | None) -> Callable[[str | None], bool]:
    """Membership in the daemon's LAN subnets (RFC 1918 when none are given)."""
    nets = [ipaddress.ip_network(c, strict=False) for c in (cidrs or RFC1918_CIDRS)]

    def is_lan(ip: str | None) -> bool:
        try:
            addr = ipaddress.ip_address(ip or "")
        except ValueError:
            return False
        return any(addr in net for net in nets if net.version == addr.version)

    return is_lan


def client_only_target(attack_target: Any) -> bool:
    """ET `attack_target` names only clients (Client_Endpoint, Mobile_Client), no server."""
    values = attack_target if isinstance(attack_target, list) else [attack_target]
    values = [str(v).upper() for v in values if v]
    return bool(values) and all("CLIENT" in v and "SERVER" not in v for v in values)


def epoch_ms(ts: str) -> int:
    """An ISO time as epoch ms; no zone means UTC, as OpenSearch and api/time_range read it."""
    when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return int((when if when.tzinfo else when.replace(tzinfo=timezone.utc)).timestamp() * 1000)


def _key_ms(value: Any) -> int:
    """A composite key on a date field: epoch ms, or an ISO string if a reply formats dates."""
    if isinstance(value, (int, float)) or str(value).lstrip("-").isdigit():
        return int(value)
    return epoch_ms(str(value))


def _iso_ms(ms: int) -> str:
    when = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return when.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def alert_instants(
    client: Any, index: str, bool_query: dict, lan_cidrs: list[str]
) -> list[dict]:
    """Every alert instant with a LAN party: rule, src, dst, community ID, time (ms), count."""
    lan_party = {
        "bool": {
            "should": [
                {"terms": {"source.ip": lan_cidrs}},
                {"terms": {"destination.ip": lan_cidrs}},
            ],
            "minimum_should_match": 1,
        }
    }
    query = {"bool": {**bool_query, "filter": [*bool_query["filter"], lan_party]}}
    sources = [
        {"sig": {"terms": {"field": "rule.name", "missing_bucket": True}}},
        {"src": {"terms": {"field": "source.ip", "missing_bucket": True}}},
        {"dst": {"terms": {"field": "destination.ip", "missing_bucket": True}}},
        {"cid": {"terms": {"field": "network.community_id", "missing_bucket": True}}},
        {"ts": {"terms": {"field": "@timestamp"}}},
    ]
    buckets, complete = all_buckets(
        client, index, query, sources, page_size=_INSTANT_PAGE, what="alert instants"
    )
    if not complete:
        raise QueryFailed(f"alert instants: stopped at {len(buckets)}")
    return [{**b["key"], "count": b.get("doc_count", 0)} for b in buckets]


def connection_spans(
    client: Any, index: str, cids: list[str], from_ts: str, to_ts: str
) -> dict[str, list[tuple[str, int, int]]]:
    """Zeek conn records per community ID: (originator, start ms, end ms)."""
    # a conn is stamped with its start, and written when it ends
    start = (datetime.fromisoformat(from_ts.replace("Z", "+00:00")) - timedelta(days=1)).isoformat()
    end = (datetime.fromisoformat(to_ts.replace("Z", "+00:00")) + timedelta(hours=1)).isoformat()
    spans: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
    for i in range(0, len(cids), _CID_CHUNK):
        query = {
            "bool": {
                "filter": [
                    {
                        "range": {
                            "@timestamp": {
                                "gte": start,
                                "lte": end,
                                "format": "strict_date_optional_time",
                            }
                        }
                    },
                    {"term": {"event.provider": "zeek"}},
                    {"term": {"event.dataset": "conn"}},
                    {"terms": {"network.community_id": cids[i : i + _CID_CHUNK]}},
                ]
            }
        }
        sources = [
            {"cid": {"terms": {"field": "network.community_id"}}},
            {"orig": {"terms": {"field": "source.ip"}}},
            {"start": {"terms": {"field": "event.start"}}},
            {"end": {"terms": {"field": "event.end", "missing_bucket": True}}},
        ]
        buckets, complete = all_buckets(
            client, index, query, sources, page_size=_INSTANT_PAGE, what="alert connections"
        )
        if not complete:
            raise QueryFailed(f"alert connections: stopped at {len(buckets)}")
        for b in buckets:
            k = b["key"]
            spans[k["cid"]].append(
                (k["orig"], _key_ms(k["start"]), _key_ms(k["end"] or k["start"]))
            )
    return spans


def opener_at(spans: list[tuple[str, int, int]], ts: int) -> str | None:
    """The one originator of the conns whose span holds `ts`; None if none or they disagree."""
    found = {
        orig
        for orig, start, end in spans
        if start - CONN_SLACK_MS <= ts <= end + CONN_SLACK_MS
    }
    return next(iter(found)) if len(found) == 1 else None


# ---------------------------------------------------------------------------
# Charging each alert to one finding
# ---------------------------------------------------------------------------


def charge(
    src: str | None,
    dst: str | None,
    opener: str | None,
    client_target: bool,
    is_lan: Callable[[str | None], bool],
) -> tuple[str | None, bool]:
    """(device, own traffic) for one alert, or (None, False) when it concerns no one device."""
    src_lan, dst_lan = is_lan(src), is_lan(dst)
    if src_lan and not dst_lan:
        return src, True  # its request, or its response on an internet-opened connection
    if dst_lan and not src_lan:
        return dst, opener == dst  # a reply to its own connection, or an attempt against it
    if src_lan and dst_lan:
        if client_target:  # the client (opener) is affected, not a proxy relaying for it
            return (opener, True) if opener in (src, dst) else (None, False)
        return src, True
    return None, False


def findings_by_group(
    instants: list[dict],
    spans: dict[str, list[tuple[str, int, int]]],
    client_targets: dict[str, bool],
    is_lan: Callable[[str | None], bool],
) -> dict[tuple, list[dict]]:
    """Per (rule, src, dst): findings {device, own, count, times[(ms, count)]}, sorted by time."""
    parts: dict[tuple, dict[tuple, dict]] = defaultdict(dict)
    for inst in instants:
        sig, src, dst, ts = inst["sig"], inst["src"], inst["dst"], _key_ms(inst["ts"])
        opener = opener_at(spans.get(inst["cid"]) or [], ts) if is_lan(dst) else None
        device, own = charge(src, dst, opener, client_targets.get(sig, False), is_lan)
        if device is None:
            continue
        # an attempt is known only when a conn record shows the other side opened it; an open
        # connection has no record yet (deep-review: a held-open C2 session must not vanish)
        known = own or opener is not None
        part = parts[(sig, src, dst)].setdefault(
            (device, own, known),
            {"device": device, "own": own, "opener_known": known, "count": 0, "times": []},
        )
        part["count"] += inst["count"]
        part["times"].append((ts, inst["count"]))
    out: dict[tuple, list[dict]] = {}
    for key, by_role in parts.items():
        findings = []
        for f in by_role.values():
            times = sorted(f["times"])
            findings.append(
                {
                    **f,
                    "times": times,
                    "first_seen": _iso_ms(times[0][0]),
                    "last_seen": _iso_ms(times[-1][0]),
                }
            )
        out[key] = findings
    return out


def finding_severity(base: int, finding: dict, reputation: bool) -> int:
    """The finding's effective severity: a reputation hit counts as the device's own traffic, and is
    left out only when a conn record shows the other side opened the connection."""
    if not reputation:
        return base
    # OLD CODE: return max(base, REPUTATION_OWN_SEVERITY) if finding["own"] else _COUNTED
    if finding["own"] or not finding.get("opener_known", True):
        return max(base, REPUTATION_OWN_SEVERITY)
    return _COUNTED


def public(group: dict) -> dict:
    """The group without its findings' occurrence lists (kept for kill chains only)."""
    if not group.get("findings"):
        return group
    return {
        **group,
        "findings": [
            {k: v for k, v in f.items() if k != "times"} for f in group["findings"]
        ],
    }


# ---------------------------------------------------------------------------
# Kill chains (rules in the brief: per device, real alert instants in stage and time order)
# ---------------------------------------------------------------------------


def _occurrences(groups: list[dict], stage_of: Callable[[str], int | None]) -> dict:
    """Per device: eligible occurrences (ms, stage, own, group index, finding index)."""
    per_device: dict[str, list[tuple]] = defaultdict(list)
    for gi, group in enumerate(groups):
        stage = stage_of(group.get("category", ""))
        if not stage or is_reputation(group.get("signature")):
            continue
        for fi, f in enumerate(group.get("findings") or []):
            if f.get("severity", _COUNTED) >= _COUNTED:
                continue
            if not f["own"] and stage not in ATTEMPT_STAGES:
                continue
            for ts, _count in f.get("times", []):
                per_device[f["device"]].append((ts, stage, f["own"], gi, fi))
    return per_device


def longest_chain(occ: list[tuple]) -> list[tuple]:
    """The longest stage-increasing, time-ordered run with ≤24 h steps and some own traffic.

    `occ` items are (ms, stage, own, ...). Stage order is strict, so with 4 stages each lower stage
    keeps a sliding-window maximum (monotonic deque) of chain lengths: O(stages² · n).
    """
    occ = sorted(occ, key=lambda o: (o[0], o[1]))
    n = len(occ)
    any_len, own_len = [0] * n, [0] * n
    any_pred: list[int | None] = [None] * n
    own_pred: list[int | None] = [None] * n
    windows = {
        s: {"any": deque(), "own": deque()} for s in range(1, 5)
    }  # (ms, length, index), lengths decreasing

    def best(kind: str, below: int, now: int) -> tuple[int, int | None]:
        top, at = 0, None
        for s in range(1, below):
            dq = windows[s][kind]
            while dq and dq[0][0] < now - CHAIN_STEP_MS:
                dq.popleft()
            if dq and dq[0][1] > top:
                top, at = dq[0][1], dq[0][2]
        return top, at

    def push(kind: str, stage: int, ms: int, length: int, i: int) -> None:
        dq = windows[stage][kind]
        while dq and dq[-1][1] <= length:
            dq.pop()
        dq.append((ms, length, i))

    for i, (ms, stage, own, *_rest) in enumerate(occ):
        prev_any, at_any = best("any", stage, ms)
        any_len[i], any_pred[i] = prev_any + 1, at_any
        if own:
            own_len[i], own_pred[i] = any_len[i], at_any
        else:
            prev_own, at_own = best("own", stage, ms)
            if prev_own:
                own_len[i], own_pred[i] = prev_own + 1, at_own
        push("any", stage, ms, any_len[i], i)
        if own_len[i]:
            push("own", stage, ms, own_len[i], i)

    end = max(range(n), key=lambda i: own_len[i], default=None)
    if end is None or own_len[end] < 2:
        return []
    chain, i, need_own = [], end, True
    while i is not None:
        chain.append(occ[i])
        if need_own and not occ[i][2]:
            i = own_pred[i]
        else:
            i, need_own = any_pred[i], False
    return chain[::-1]


def kill_chains(
    groups: list[dict],
    stage_of: Callable[[str], int | None],
    label_of: Callable[[int], str],
) -> list[dict]:
    """One chain per device that shows one, longest first."""
    chains = []
    for device, occ in _occurrences(groups, stage_of).items():
        chain = longest_chain(occ)
        if not chain:
            continue
        stages = [o[1] for o in chain]
        picked = list(dict.fromkeys((o[3], o[4]) for o in chain))
        chain_groups = list(dict.fromkeys(gi for gi, _fi in picked))
        labels = [label_of(s) for s in stages]
        chains.append(
            {
                "source_ip": device,  # the device; the web reads this field name
                "stages": stages,
                "stage_labels": labels,
                "alert_count": sum(
                    groups[gi]["findings"][fi]["count"] for gi, fi in picked
                ),
                "alerts": [public(groups[gi]) for gi in chain_groups],
                "first_seen": _iso_ms(chain[0][0]),
                "last_seen": _iso_ms(chain[-1][0]),
                "assessment": (
                    f"{device} shows {len(stages)} attack stages in order within "
                    f"24 hours of each other, including its own traffic "
                    f"({' → '.join(labels)}): possible active intrusion."
                ),
            }
        )
    chains.sort(key=lambda c: len(c["stages"]), reverse=True)
    return chains
