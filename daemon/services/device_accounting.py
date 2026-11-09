"""
Device accounting: both sides of every connection, IPv6 by MAC, and LAN-side direction (NET-226).

A device's traffic is every Zeek conn record it took part in: the ones it started (it is
`source.ip`), the ones it answered (it is `destination.ip`), and its IPv6 records, which belong
to it by MAC. Its upload is what it sent: the originator's bytes where it started, the
responder's where it answered.

On a LAN-side mirror the router's MAC is on every frame it forwards, so IPv6 folds by MAC only
for MACs that are not a next hop to the internet (gateway_macs). Link-local records
(fe80::/10) are never forwarded, so they fold for every MAC.
"""

import os
from typing import Any

from services.excluded_ips import RFC1918_CIDRS, cidr, lan_subnets_of
from storage.snapshot_search import QueryFailed, checked

NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

# Matches every IPv4 address and no IPv6 one (OpenSearch keeps IPv4 as ::ffff:0:0/96)
IPV4_ALL = ["0.0.0.0/0"]
LINK_LOCAL = ["fe80::/10"]
GLOBAL_V6 = ["2000::/3"]
# Destinations that never leave the LAN, whatever the source
LOCAL_DESTINATIONS = [
    "224.0.0.0/4",
    "255.255.255.255/32",
    "fe80::/10",
    "fc00::/7",
    "ff00::/8",
]

# IPs per answered-side search: under index.max_terms_count (65,536) and search.max_buckets
_IP_CHUNK = 10_000
# shortcut: past 1,000 MACs on one side of global IPv6 traffic the rest keeps the originator's
# direction; no home has that many
_MAC_LIMIT = 1_000

ROUTER = "router"
NO_GATEWAY = "no_gateway"


def _value(agg: Any) -> int:
    return int((agg or {}).get("value") or 0)


def lan_cidrs(lan_filter: dict | None) -> list[str]:
    """The CIDRs a build_lan_filter() filter matches (all of RFC1918 when it lists none)."""
    return [cidr(s) for s in lan_subnets_of(lan_filter)] or RFC1918_CIDRS


def _side_aggs(sent: str, received: str) -> dict:
    """Sums for one side; `sent` holds the device's own bytes on that side."""
    return {
        "upload": {"sum": {"field": sent, "missing": 0}},
        "download": {"sum": {"field": received, "missing": 0}},
    }


STARTED = _side_aggs("source.bytes", "destination.bytes")
ANSWERED = _side_aggs("destination.bytes", "source.bytes")


def totals(bucket: dict) -> dict:
    """{connections, upload, download} from a bucket that carries STARTED or ANSWERED."""
    return {
        "connections": bucket.get("doc_count", 0),
        "upload": _value(bucket.get("upload")),
        "download": _value(bucket.get("download")),
    }


def add(*parts: dict | None) -> dict:
    """The sum of {connections, upload, download} parts; None adds nothing."""
    keys = ("connections", "upload", "download")
    return {k: sum((p or {}).get(k, 0) for p in parts) for k in keys}


# Both IP byte counts: originator (src) and responder (dst)
BYTE_SUMS = {
    "src": {"sum": {"field": "source.bytes", "missing": 0}},
    "dst": {"sum": {"field": "destination.bytes", "missing": 0}},
}


def bucket_bytes(bucket: dict) -> int:
    """Both IP byte counts of a bucket carrying BYTE_SUMS."""
    return _value(bucket.get("src")) + _value(bucket.get("dst"))


def side_sums(answered: dict) -> dict:
    """BYTE_SUMS, plus the same sums over the sessions the device answered (`answered`)."""
    return {**BYTE_SUMS, "answered": {"filter": answered, "aggs": BYTE_SUMS}}


def side_bytes(bucket: dict) -> tuple[int, int]:
    """(upload, download) of a bucket carrying side_sums(): on a session the device
    answered, the responder's bytes are its upload."""
    src, dst = _value(bucket.get("src")), _value(bucket.get("dst"))
    ans = bucket.get("answered") or {}
    a_src, a_dst = _value(ans.get("src")), _value(ans.get("dst"))
    return src - a_src + a_dst, dst - a_dst + a_src


def answered_by_ip(
    client, filters: list[dict], ips: list[str], what: str
) -> dict[str, dict]:
    """{ip: totals} over the connections each IP answered; QueryFailed if a reply is partial."""
    out: dict[str, dict] = {}
    for start in range(0, len(ips), _IP_CHUNK):
        chunk = ips[start : start + _IP_CHUNK]
        body = {
            "size": 0,
            "query": {
                "bool": {"filter": [*filters, {"terms": {"destination.ip": chunk}}]}
            },
            "aggs": {
                "answered": {
                    "terms": {"field": "destination.ip", "size": len(chunk)},
                    "aggs": ANSWERED,
                }
            },
        }
        reply = checked(
            client.search(index=NETWORK_INDEX, body=body), what, ("answered",)
        )
        buckets = reply["aggregations"]["answered"].get("buckets") or []
        out = {**out, **{b["key"]: totals(b) for b in buckets}}
    return out


def ipv6_by_mac(
    client, filters: list[dict], macs: list[str], what: str
) -> dict[str, dict]:
    """{mac: {"all": totals, "link_local": totals}} over each MAC's IPv6 records, both sides.

    Started = the MAC is `source.mac`, answered = `destination.mac`; "link_local" is the part
    whose address on the device's side is in fe80::/10. QueryFailed if the reply is partial.
    """
    if not macs:
        return {}
    sides = {"started": ("source", STARTED), "answered": ("destination", ANSWERED)}
    body = {
        "size": 0,
        "query": {
            "bool": {
                "filter": filters,
                "must_not": [{"terms": {"source.ip": IPV4_ALL}}],
                "should": [{"terms": {f"{s}.mac": macs}} for s, _ in sides.values()],
                "minimum_should_match": 1,
            }
        },
        "aggs": {
            name: {
                "filter": {"terms": {f"{side}.mac": macs}},
                "aggs": {
                    "macs": {
                        "terms": {"field": f"{side}.mac", "size": len(macs)},
                        "aggs": {
                            **sums,
                            "link_local": {
                                "filter": {"terms": {f"{side}.ip": LINK_LOCAL}},
                                "aggs": sums,
                            },
                        },
                    }
                },
            }
            for name, (side, sums) in sides.items()
        },
    }
    aggs = checked(client.search(index=NETWORK_INDEX, body=body), what, tuple(sides))[
        "aggregations"
    ]
    out: dict[str, dict] = {}
    for name in sides:
        for b in (aggs[name].get("macs") or {}).get("buckets") or []:
            seen = out.get(b["key"], {})
            out = {
                **out,
                b["key"]: {
                    "all": add(seen.get("all"), totals(b)),
                    "link_local": add(seen.get("link_local"), totals(b["link_local"])),
                },
            }
    return out


def gateway_macs(
    client,
    filters: list[dict],
    lan_filter: dict | None,
    candidates: list[str],
    what: str,
) -> set[str] | None:
    """Which `candidates` the LAN sent internet-bound IPv4 frames to in the window; None when
    there are no candidates or the LAN sent no such frame at all (no gateway known).

    Any frame counts, so a second router, or one replaced mid-window, is a gateway too;
    inbound connections start outside the LAN, so a LAN server never is. One existence check
    per MAC (a first match is enough), all in one _msearch: on the G11 over 30 days about
    0.5 s where a terms list of every next hop took 1-1.6 s. QueryFailed if any check fails.
    """
    if not candidates:
        return None
    lan = lan_cidrs(lan_filter)
    outbound = {
        "bool": {
            "filter": [
                *filters,
                {"terms": {"source.ip": lan}},
                {"exists": {"field": "destination.mac"}},
            ],
            "must_not": [{"terms": {"destination.ip": [*lan, *LOCAL_DESTINATIONS]}}],
        }
    }
    checks = [[], *([{"term": {"destination.mac": mac}}] for mac in candidates)]
    body: list[dict] = []
    for extra in checks:
        body += [
            {"index": NETWORK_INDEX},
            {
                "size": 0,
                "track_total_hits": 1,
                "terminate_after": 1,
                "query": {"bool": {"filter": [outbound, *extra]}},
            },
        ]
    replies = client.msearch(body=body).get("responses")
    if not isinstance(replies, list) or len(replies) != len(checks):
        raise QueryFailed(f"{what}: malformed next-hop reply")
    if any("error" in r for r in replies if isinstance(r, dict)):
        raise QueryFailed(f"{what}: a next-hop check failed")
    seen = [
        ((checked(r, what).get("hits") or {}).get("total") or {}).get("value", 0) > 0
        for r in replies
    ]
    if not seen[0]:
        return None
    return {mac for mac, hit in zip(candidates, seen[1:]) if hit}


def forwarded_macs(per_mac: dict) -> list[str]:
    """The MACs with IPv6 beyond link-local, the only kind a router forwards: the ones whose
    gateway status changes what folds."""
    return sorted(
        mac
        for mac, p in per_mac.items()
        if p["all"]["connections"] > p["link_local"]["connections"]
    )


def fold_ipv6(per_mac: dict, gateways: set[str] | None) -> dict[str, dict]:
    """{mac: {"totals", "left_out", "reason"}}: what of each MAC's IPv6 a device row carries.

    A MAC that isn't a gateway carries all of it. A gateway's MAC, or every MAC when no
    gateway is known, carries only link-local; `left_out` counts the connections that drops,
    and `reason` says why ("router" or "no_gateway").
    """
    out: dict[str, dict] = {}
    for mac, parts in per_mac.items():
        whole = gateways is not None and mac not in gateways
        kept = parts["all"] if whole else parts["link_local"]
        left_out = parts["all"]["connections"] - kept["connections"]
        reason = (NO_GATEWAY if gateways is None else ROUTER) if left_out else None
        out = {**out, mac: {"totals": kept, "left_out": left_out, "reason": reason}}
    return out


def ipv6_clause(side: str, mac: str, link_local_only: bool) -> dict:
    """IPv6 records whose `side` ("source" or "destination") MAC is `mac`, as fold_ipv6 keeps them."""
    wanted = [{"term": {f"{side}.mac": mac}}]
    if link_local_only:
        wanted = [*wanted, {"terms": {f"{side}.ip": LINK_LOCAL}}]
    return {
        "bool": {"filter": wanted, "must_not": [{"terms": {"source.ip": IPV4_ALL}}]}
    }


# ---------------------------------------------------------------------------
# Network direction (B-d): download, upload and local for network totals
# ---------------------------------------------------------------------------


def direction_aggs(lan_filter: dict | None) -> dict:
    """Sub-aggregations that split a bucket's bytes for split_direction().

    local: LAN to LAN, or to a multicast, broadcast or IPv6 local address. inbound: an IPv4
    connection from outside the LAN rule to inside it, so upload and download swap. v6_pairs:
    global IPv6 with both MACs, by MAC pair, so a gateway-to-device pair swaps too. The rest
    keeps the originator's direction: outbound traffic, and a capture where no side is on
    the LAN (inline bridge), which reads as before.
    """
    lan = lan_cidrs(lan_filter)
    local = {
        "bool": {
            "should": [
                {"terms": {"destination.ip": LOCAL_DESTINATIONS}},
                {
                    "bool": {
                        "filter": [
                            {"terms": {"source.ip": lan}},
                            {"terms": {"destination.ip": lan}},
                        ]
                    }
                },
            ],
            "minimum_should_match": 1,
        }
    }
    inbound = {
        "bool": {
            "filter": [{"terms": {"destination.ip": lan}}],
            "must_not": [{"terms": {"source.ip": lan}}],
        }
    }
    v6_global = {
        "bool": {
            "filter": [
                {"terms": {"source.ip": GLOBAL_V6}},
                {"terms": {"destination.ip": GLOBAL_V6}},
                {"exists": {"field": "source.mac"}},
                {"exists": {"field": "destination.mac"}},
            ]
        }
    }
    return {
        "inbound": {"filter": inbound, "aggs": BYTE_SUMS},
        "local": {"filter": local, "aggs": BYTE_SUMS},
        "v6_pairs": {
            "filter": v6_global,
            "aggs": {
                "src": {
                    "terms": {"field": "source.mac", "size": _MAC_LIMIT},
                    "aggs": {
                        "dst": {
                            "terms": {"field": "destination.mac", "size": _MAC_LIMIT},
                            "aggs": BYTE_SUMS,
                        }
                    },
                }
            },
        },
    }


def _pair_macs(buckets: list[dict]) -> list[str]:
    """Every MAC on either side of the buckets' global IPv6 pairs."""
    macs: set[str] = set()
    for bucket in buckets:
        for src in ((bucket.get("v6_pairs") or {}).get("src") or {}).get(
            "buckets"
        ) or []:
            dsts = (src.get("dst") or {}).get("buckets") or []
            macs = macs | {src["key"], *(d["key"] for d in dsts)}
    return sorted(macs)


def gateways_if_needed(
    client, buckets: list[dict], filters: list[dict], lan_filter: dict | None, what: str
) -> set[str] | None:
    """gateway_macs() over the MACs of the buckets' global IPv6 pairs; None when there are none."""
    return gateway_macs(client, filters, lan_filter, _pair_macs(buckets), what)


def split_direction(
    orig: float, resp: float, bucket: dict, gateways: set[str] | None = None
) -> dict:
    """{upload_bytes, download_bytes, local_bytes} for a bucket carrying direction_aggs().

    `orig`/`resp` are the bucket's originator and responder byte sums; the three parts add up
    to orig + resp. With `gateways`, global IPv6 from a gateway's MAC to another MAC is inbound.
    """
    inb, loc = bucket.get("inbound") or {}, bucket.get("local") or {}
    in_o, in_r = _value(inb.get("src")), _value(inb.get("dst"))
    for src in ((bucket.get("v6_pairs") or {}).get("src") or {}).get("buckets") or []:
        if src["key"] not in (gateways or ()):
            continue
        for dst in (src.get("dst") or {}).get("buckets") or []:
            if dst["key"] not in gateways:
                in_o, in_r = (
                    in_o + _value(dst.get("src")),
                    in_r + _value(dst.get("dst")),
                )
    lo_o, lo_r = _value(loc.get("src")), _value(loc.get("dst"))
    return {
        "upload_bytes": int(orig) - in_o + in_r - lo_o,
        "download_bytes": int(resp) - in_r + in_o - lo_r,
        "local_bytes": lo_o + lo_r,
    }
