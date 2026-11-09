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
# Alert times are read per minute, so a flood on one connection is one bucket a minute, not one
# per alert (security review F3); a minute's alerts match a conn that overlaps that minute
_INSTANT, INSTANT_MS = "1m", 60_000
# Suricata stamps an alert raised when a flow times out with the timeout time: on the G11 600 s
# (established TCP) after the last packet, seen 600-608 s. A record that ended this long before
# the alert minute can still be its connection
FLOW_TIMEOUT_MS = 11 * 60_000
# A conn record that cannot say who opened its connection: no live session on the device
# (late fragments, a probe answered only by a reset), or a live session picked up mid-stream
DEBRIS, UNKNOWN = "debris", "unknown"
# An alert with no conn record yet: Zeek writes the record when the connection ends (idle TCP after
# 5 min) and Malcolm indexes it within a minute. Younger alerts wait for it as attempts; older ones
# are a connection still held open, whose opener is unknown (a C2 session must not vanish)
SETTLE_MS = 10 * 60 * 1000
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
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


# NET-228 (audit B-i): ET rates some rules about a secret sent or exposed in the clear Informational
# or Unknown ("Outgoing Basic Auth Base64 HTTP Password detected unencrypted", "GPL WEB_SERVER
# .htpasswd access"), so they were left out of every count, though the owner can act on them. A
# record with that rating, no Minor/Major/Critical, and one of these words in its rule name counts.
# api/alerts.py CREDENTIAL_EXPOSURE_CLAUSE is the same test as a query.
CREDENTIAL_MARKERS = ("cleartext", "password", "passwd", "credential")
# Checked against the 42 enabled rules these words catch (G11, 2026-11-09): these name an admin
# event, not a secret exposed ("ET INFO external cPanel password change")
CREDENTIAL_NOT = ("password change", "expired password")
ACTIVITY_RATINGS = ("Informational", "Unknown")
ET_RATINGS = ("Minor", "Major", "Critical")
CREDENTIAL_SEVERITY = 3  # medium: counted, below an active attempt (Major)


def is_credential_exposure(signature: str | None, et_severity: Any) -> bool:
    """A rule ET rates only Informational/Unknown whose name names a secret in the clear.
    Ratings compare exactly, as the query's terms clause does; a scalar or Malcolm's list."""
    ratings = et_severity if isinstance(et_severity, list) else [et_severity]
    name = (signature or "").lower()
    return (
        any(r in ACTIVITY_RATINGS for r in ratings)
        and not any(r in ET_RATINGS for r in ratings)
        and any(m in name for m in CREDENTIAL_MARKERS)
        and not any(x in name for x in CREDENTIAL_NOT)
    )


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
    when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    # exact: float seconds × 1000 can land 1 ms low (….123 read as ….122)
    return (when - _EPOCH) // timedelta(milliseconds=1)


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
        # one Suricata flow is one connection: its alerts share one decision
        {"flow": {"terms": {"field": "suricata.flow_id", "missing_bucket": True}}},
        # OLD CODE: {"ts": {"terms": {"field": "@timestamp"}}}, (review F3: a bucket per alert)
        {"ts": {"date_histogram": {"field": "@timestamp", "fixed_interval": _INSTANT}}},
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
    """Zeek conn records per community ID: (who opened it, start ms, end ms), where "who" is an
    address, DEBRIS or UNKNOWN (`_verdict`)."""
    # a conn is stamped with its start, and written when it ends
    start = (
        datetime.fromisoformat(from_ts.replace("Z", "+00:00")) - timedelta(days=1)
    ).isoformat()
    end = (
        datetime.fromisoformat(to_ts.replace("Z", "+00:00")) + timedelta(hours=1)
    ).isoformat()
    records: dict[str, list[tuple[int, int, str, bool]]] = defaultdict(list)
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
            {"resp": {"terms": {"field": "destination.ip", "missing_bucket": True}}},
            {"start": {"terms": {"field": "event.start"}}},
            {"end": {"terms": {"field": "event.end", "missing_bucket": True}}},
            {"hist": {"terms": {"field": "zeek.conn.history", "missing_bucket": True}}},
            {
                "proto": {
                    "terms": {"field": "network.transport", "missing_bucket": True}
                }
            },
            {
                "ob": {
                    "terms": {"field": "zeek.conn.orig_bytes", "missing_bucket": True}
                }
            },
            {
                "rb": {
                    "terms": {"field": "zeek.conn.resp_bytes", "missing_bucket": True}
                }
            },
        ]
        buckets, complete = all_buckets(
            client,
            index,
            query,
            sources,
            page_size=_INSTANT_PAGE,
            what="alert connections",
        )
        if not complete:
            raise QueryFailed(f"alert connections: stopped at {len(buckets)}")
        for b in buckets:
            k = b["key"]
            # OLD CODE START — G11 trace: skipping these made scanner probes "no record", then own
            # if not _opener_trusted(k.get("hist"), k.get("proto")):
            #     continue  # who opened it is a guess: the alert falls back to "no record"
            # spans[k["cid"]].append(
            #     (k["orig"], _key_ms(k["start"]), _key_ms(k["end"] or k["start"]))
            # )
            # OLD CODE END
            who = _verdict(
                k["orig"],
                k.get("resp"),
                k.get("hist"),
                k.get("proto"),
                k.get("ob"),
                k.get("rb"),
            )
            start_ms = _key_ms(k["start"])
            end_ms = _key_ms(k["end"] or k["start"])
            records[k["cid"]].append((start_ms, end_ms, who, k.get("proto") == "tcp"))
    return {cid: _chained(recs) for cid, recs in records.items()}


def _chained(records: list[tuple[int, int, str, bool]]) -> list[tuple[str, int, int]]:
    """Spans of one community ID. A UDP/ICMP record that starts within FLOW_TIMEOUT_MS of the
    previous one continues it: Zeek closes UDP after 60 s of silence, but the outside can only
    reach the device while the router's NAT mapping from the earlier traffic lives (security
    review: a C2 that speaks first after a pause is not the opener)."""
    spans, prev = [], None
    for start, end, who, tcp in sorted(records, key=lambda r: r[:2]):
        if not tcp:
            if prev and start - prev[0] <= FLOW_TIMEOUT_MS:
                who = prev[1]
            prev = (end, who)
        spans.append((who, start, end))
    return spans


# OLD CODE START — G11 trace: a scanner's lone data packet (`D`, `DShR`) was skipped too
# def _opener_trusted(history: str | None, transport: str | None) -> bool:
#     """Zeek's originator is the opener unless it flipped the direction (`^`, e.g. UDP from port
#     5353 to a high port) or picked a TCP connection up mid-stream (no SYN first): review F2."""
#     if not history:
#         return True
#     return "^" not in history and (transport != "tcp" or history.startswith("S"))
# OLD CODE END


def _oriented(history: str) -> str:
    """The history with every letter relative to the record's final originator (upper case) and
    responder (lower case): Zeek's flip (`^`) swaps the endpoints without rewriting earlier letters."""
    letters, flips = [], 0
    for ch in reversed(history):
        if ch == "^":
            flips += 1
        else:
            letters.append(ch.swapcase() if flips % 2 else ch)
    return "".join(reversed(letters))


def _verdict(
    orig: str,
    resp: str | None,
    history: str | None,
    transport: str | None,
    orig_bytes: int | None,
    resp_bytes: int | None,
) -> str:
    """Who opened a conn record's connection: an address, DEBRIS or UNKNOWN (rules in the brief)."""
    if not history:
        return orig
    h = _oriented(history)
    if transport != "tcp":  # no handshake: whoever sent the first packet
        return orig if not h or h[0].isupper() else resp
    # only a pure SYN shows the opener; a SYN-ACK can be a scan or backscatter
    if "S" in h and "s" not in h:
        return orig
    if "s" in h and "S" not in h:
        return resp
    two_sided = any(c.isupper() and c != "R" for c in h) and any(
        c.islower() and c != "r" for c in h
    )
    if not two_sided:  # one side only, or answered by a reset: no live session
        return DEBRIS
    # a FIN can carry payload too (`F`), so the byte counters count; none indexed: assume payload
    payload = (
        "D" in h
        or "d" in h
        or (orig_bytes is None and resp_bytes is None)
        or (orig_bytes or 0) + (resp_bytes or 0) > 0
    )
    return UNKNOWN if payload else DEBRIS


# OLD CODE START — G11 trace: 10 s after the end missed flow-timeout alerts, and a disagreement
# (a late `^f` fragment beside the real record) fell through to "no record"
# def opener_at(spans: list[tuple[str, int, int]], ts: int) -> str | None:
#     found = {
#         orig
#         for orig, start, end in spans
#         if start - CONN_SLACK_MS < ts + INSTANT_MS and ts <= end + CONN_SLACK_MS
#     }
#     return next(iter(found)) if len(found) == 1 else None
# OLD CODE END


def minute_state(spans: list[tuple[str, int, int]], ts: int) -> tuple[str, str | None]:
    """What the records say about the connection of an alert minute [ts, ts + 60 s):
    ("direct", opener) from a record the minute is in, ("after", opener) from the latest record
    that ended up to FLOW_TIMEOUT_MS before it, or ("unknown" | "undecided" | "none", None)."""
    direct = {
        who
        for who, start, end in spans
        if start - CONN_SLACK_MS < ts + INSTANT_MS and ts <= end + CONN_SLACK_MS
    }
    ended = [
        (end, who)
        for who, start, end in spans
        if end + CONN_SLACK_MS < ts <= end + FLOW_TIMEOUT_MS
    ]
    after = _latest([(end, who) for end, who in ended if who != DEBRIS])
    openers = direct - {DEBRIS, UNKNOWN}
    if len(openers) > 1:
        return "unknown", None
    if openers:
        (opener,) = openers
        # a reused tuple: the record the minute is in, or the one that just timed out
        if after not in (None, UNKNOWN, opener):
            return "unknown", None
        return "direct", opener
    if direct or after == UNKNOWN:
        # picked up mid-stream (a resumed session, keepalives): the session's handshake record,
        # however old, names the opener (security review: a held-open C2 must not turn debris)
        prior = _latest(
            [
                (end, who)
                for who, start, end in spans
                if end + CONN_SLACK_MS < ts and who not in (DEBRIS, UNKNOWN)
            ]
        )
        if prior not in (None, UNKNOWN):
            return "after", prior
        if UNKNOWN in direct or after == UNKNOWN:
            return "unknown", None
        return "undecided", None
    if after:
        return "after", after
    return ("undecided", None) if ended else ("none", None)


def _latest(ended: list[tuple[int, str]]) -> str | None:
    """The verdict of the record that ended last; UNKNOWN when records tied on it disagree."""
    last = max((end for end, _ in ended), default=None)
    found = {who for end, who in ended if end == last}
    return (next(iter(found)) if len(found) == 1 else UNKNOWN) if found else None


def flow_states(
    instants: list[dict],
    spans: dict[str, list[tuple[str, int, int]]],
    is_lan: Callable[[str | None], bool],
) -> list[tuple[str, str | None]]:
    """minute_state for each instant toward a LAN address, decided per Suricata flow: one direct
    opener in any of the flow's minutes decides all of them, two make them all "unknown"; an
    "after" inference stays with its own minute."""
    local: list[tuple[str, str | None]] = []
    direct: dict[tuple, set] = defaultdict(set)
    for inst in instants:
        ts = _key_ms(inst["ts"])
        state = (
            minute_state(spans.get(inst["cid"]) or [], ts)
            if inst["cid"] and is_lan(inst["dst"])
            else ("none", None)
        )
        local.append(state)
        if state[0] == "direct":
            direct[_flow(inst, ts)].add(state[1])
    out = []
    for inst, state in zip(instants, local):
        found = direct.get(_flow(inst, _key_ms(inst["ts"])), set())
        if len(found) == 1:
            out.append(("direct", next(iter(found))))
        elif found:
            out.append(("unknown", None))
        else:
            out.append(state)
    return out


def _flow(inst: dict, ts: int) -> tuple:
    """An alert's connection: its Suricata flow, or (with no flow ID) its own minute."""
    return (
        (inst["cid"], inst.get("flow")) if inst.get("flow") else (inst["cid"], None, ts)
    )


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
        return (
            src,
            True,
        )  # its request, or its response on an internet-opened connection
    if dst_lan and not src_lan:
        return (
            dst,
            opener == dst,
        )  # a reply to its own connection, or an attempt against it
    if src_lan and dst_lan:
        if (
            client_target
        ):  # the client (opener) is affected, not a proxy relaying for it
            return (opener, True) if opener in (src, dst) else (None, False)
        return src, True
    return None, False


def findings_by_group(
    instants: list[dict],
    spans: dict[str, list[tuple[str, int, int]]],
    client_targets: dict[str, bool],
    is_lan: Callable[[str | None], bool],
    settled_before: int | None = None,
) -> dict[tuple, list[dict]]:
    """Per (rule, src, dst): findings {device, own, count, times[(ms, count)]}, sorted by time.

    `settled_before` (epoch ms): an inbound alert after it with no conn record yet is an
    attempt while its record is on the way; one before it is the device's own traffic (a
    connection held open). None: every unmatched one counts as own.
    """
    parts: dict[tuple, dict[tuple, dict]] = defaultdict(dict)
    for inst, (state, who) in zip(instants, flow_states(instants, spans, is_lan)):
        sig, src, dst, ts = inst["sig"], inst["src"], inst["dst"], _key_ms(inst["ts"])
        # OLD CODE: opener = opener_at(spans.get(inst["cid"]) or [], ts) if is_lan(dst) else None
        opener = who if state in ("direct", "after") else None
        device, own = charge(src, dst, opener, client_targets.get(sig, False), is_lan)
        if device is None:
            continue
        # OLD CODE START — reviews: unknown openers were attempts (a held-open C2 session scored
        # 0.5 and left device risk), then listed reputation hits only
        # known = own or opener is not None
        # OLD CODE END
        # No record matched, or a live session of unknown origin: while the record may still be on
        # its way it is an attempt; after SETTLE_MS it is a connection held open, and counts as the
        # device's own traffic. "undecided" (debris only) and no community ID: packet direction.
        # OLD CODE: unmatched = (opener is None and device == dst and not is_lan(src) and bool(inst["cid"]))
        unmatched = (
            state in ("none", "unknown")
            and device == dst
            and not is_lan(src)
            and bool(inst["cid"])
        )
        fresh = settled_before is not None and ts > settled_before
        own = own or (unmatched and not fresh)
        known = not unmatched
        part = parts[(sig, src, dst)].setdefault(
            (device, own, known),
            {
                "device": device,
                "own": own,
                "opener_known": known,
                "count": 0,
                "times": [],
            },
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
    """The finding's effective severity: a reputation hit counts only as the device's own traffic
    (which includes a connection still unmatched after SETTLE_MS)."""
    if not reputation:
        return base
    # OLD CODE START — reviews: an unmatched hit is own after SETTLE_MS (findings_by_group) now
    # if finding["own"] or not finding.get("opener_known", True):
    #     return max(base, REPUTATION_OWN_SEVERITY)
    # return _COUNTED
    # OLD CODE END
    return max(base, REPUTATION_OWN_SEVERITY) if finding["own"] else _COUNTED


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
                # OLD CODE START — NET-228 (audit ALR-18): stated stages as fact, and "within 24 hours
                # of each other" though only the gap between successive stages is bounded
                # "assessment": (
                #     f"{device} shows {len(stages)} attack stages in order within "
                #     f"24 hours of each other, including its own traffic "
                #     f"({' → '.join(labels)}): possible active intrusion."
                # ),
                # OLD CODE END
                "assessment": (
                    f"{device}: rule matches NetTap maps to {len(stages)} attack stages "
                    f"({' → '.join(labels)}), in order, with no more than 24 hours between "
                    "successive stages and at least one from its own traffic. This can mean "
                    "an intrusion in progress; each stage is NetTap's reading of a rule "
                    "match, not a confirmed step."
                ),
            }
        )
    chains.sort(key=lambda c: len(c["stages"]), reverse=True)
    return chains
