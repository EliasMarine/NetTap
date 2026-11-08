"""
NetTap Risk Scoring API Routes

Registers device risk scoring endpoints with the aiohttp application.
These endpoints compute per-device risk scores (0-100) based on network
telemetry data from OpenSearch indices.
"""

import logging
import os
from datetime import timedelta
# OLD CODE START — PR #192 review: the port read no longer groups (ip, port) pairs
# from itertools import groupby
# OLD CODE END

from aiohttp import web
from opensearchpy import OpenSearchException

from api.offload import in_thread, run_blocking
from api.time_range import parse_time_range
# OLD CODE: from api.alerts import SURICATA_NOISE_EXCLUSION (NET-209: alerts come from findings)
# OLD CODE: from api.devices import _incomplete, _lan_device_bool_query, _lan_device_buckets
from api.devices import (
    _incomplete,
    _iso_ms,
    _lan_device_bool_query,
    _lan_device_buckets,
    _time_range_filter,
)
from api.drilldown_runner import lan_check, lan_cidrs

# OLD CODE START — #96: the population's filters come from api.devices._lan_device_bool_query now
# from services.excluded_ips import build_excluded_ips_filter, RFC1918_SOURCE_FILTER
# OLD CODE END
# OLD CODE: from services.iot_monitor import ICMP_TRANSPORTS (NET-209: the port factor is gone)
from services.alert_findings import epoch_ms
from services.alert_intelligence import _INFO_SEVERITY, get_smart_alerts
from services.risk_scoring import RiskScorer
from services.threat_detection import NOT_INTERNET_CIDRS
from storage.all_buckets import all_buckets
from storage.manager import StorageManager
from storage.snapshot_search import QueryFailed, checked, total_hits

logger = logging.getLogger("nettap.api.risk")

# OLD CODE START — separate per-log-type indices replaced by unified Malcolm index
# ZEEK_CONN_INDEX = "zeek-conn-*"
# SURICATA_INDEX = "suricata-*"
# OLD CODE END
NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

# Default time range: last 24 hours
_DEFAULT_RANGE_HOURS = 24


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# OLD CODE START — #96: the baseline came from the busiest 500 devices, so larger sites lost the rest
# # Devices the network baseline (mean and stddev of connections) is taken over, in both views
# _BASELINE_DEVICES = 500
# OLD CODE END

# Scored devices per composite page: ~55 buckets each keeps a page well under search.max_buckets
_SCORE_PAGE_SIZE = 500
# OLD CODE START — NET-209: the per-IP alert-count searches are gone (see _own_alerts)
# # Device IPs per alert-count search: under index.max_terms_count (65,536) and search.max_buckets
# _ALERT_IP_CHUNK = 10_000
# OLD CODE END


def _baseline(counts: list[int]) -> tuple[float, float]:
    """Mean and population stddev of per-device connection counts."""
    if not counts:
        return 0.0, 0.0
    avg = sum(counts) / len(counts)
    return avg, (sum((c - avg) ** 2 for c in counts) / len(counts)) ** 0.5


def _parse_time_range(request: web.Request) -> tuple[str, str]:
    """'from'/'to' as ISO timestamps, defaulting to the last 24 hours; unreadable is a 400."""
    # OLD CODE START — 2026-11-02: an unreadable from/to (e.g. now-5m) silently became the
    # default window, so the Infrastructure page divided 24 h of events by 5 min
    # """Extract 'from' and 'to' query parameters as ISO timestamps."""
    # now = datetime.now(timezone.utc)
    # default_from = (now - timedelta(hours=_DEFAULT_RANGE_HOURS)).isoformat()
    # default_to = now.isoformat()
    #
    # raw_from = request.query.get("from", "")
    # raw_to = request.query.get("to", "")
    #
    # if raw_from:
    #     try:
    #         datetime.fromisoformat(raw_from.replace("Z", "+00:00"))
    #     except (ValueError, TypeError):
    #         raw_from = ""
    # if raw_to:
    #     try:
    #         datetime.fromisoformat(raw_to.replace("Z", "+00:00"))
    #     except (ValueError, TypeError):
    #         raw_to = ""
    #
    # return (raw_from or default_from, raw_to or default_to)
    # OLD CODE END
    return parse_time_range(request, timedelta(hours=_DEFAULT_RANGE_HOURS))


def _get_client(request: web.Request):
    """Retrieve the OpenSearch client from the StorageManager on the app."""
    storage: StorageManager = request.app["storage"]
    return storage._client


# OLD CODE START — NET-209: the port-list and external-share factors are gone, and the scorer no
# longer reads byte ratios (THREAT-SCORING.md rules 11, 12, 14)
# def _ports_cut_short(conn_bucket: dict) -> bool:
#     """True if the device used more ports than its top-50 ports_used list holds."""
#     # OLD CODE START — NET-158: ports_used is a non-ICMP filter around the terms list now
#     # return bool(conn_bucket.get("ports_used", {}).get("sum_other_doc_count", 0))
#     # OLD CODE END
#     return bool(_port_terms(conn_bucket).get("sum_other_doc_count", 0))
#
#
# def _port_terms(conn_bucket: dict) -> dict:
#     """The device's destination-port terms list (ICMP left out, see _device_score_aggs)."""
#     return conn_bucket.get("ports_used", {}).get("ports", {})
#
#
# # PR #192 review: one bucket per device with bounded lists, so a port scan from several
# # devices cannot push the read past a cap and blank every score
# _UNUSUAL_PORT_LIST = 100
# _PORT_PAGE_SIZE = 200  # ~110 buckets a device, far below search.max_buckets (65,535)
#
#
# # OLD CODE START — PR #192 review: every (device, port) pair; 8 devices scanning every port
# # passed the 500,000-bucket cap, which now fails the whole list
# # def _all_unsafe_ports(client, bool_query: dict, ips: list[str]) -> dict[str, list[int]]:
# #     """Every port outside SAFE_PORTS that each of `ips` connected to (#96).
# #
# #     For devices whose ports_used list was cut short: the scorer flags any port outside
# #     SAFE_PORTS, so a single connection to 4444 must not fall off the end of a top-50 list.
# #     """
# #     if not ips:
# #         return {}
# #     query = {
# #         "bool": {
# #             **bool_query,
# #             "filter": [*bool_query["filter"], {"terms": {"source.ip": ips}}],
# #             "must_not": [
# #                 *bool_query.get("must_not", []),
# #                 {"terms": {"destination.port": sorted(RiskScorer.SAFE_PORTS)}},
# #                 _ICMP,  # NET-158: Zeek writes the ICMP code there, not a port
# #             ],
# #         }
# #     }
# #     sources = [
# #         {"ip": {"terms": {"field": "source.ip"}}},
# #         {"port": {"terms": {"field": "destination.port"}}},
# #     ]
# #     # OLD CODE START — a capped or partial port read scored devices on the ports it held
# #     # buckets, complete = all_buckets(client, NETWORK_INDEX, query, sources)
# #     # if not complete:
# #     #     logger.warning(
# #     #         "Port lists stopped at %d device ports; scores cover those only",
# #     #         len(buckets),
# #     #     )
# #     # OLD CODE END
# #     buckets, complete = all_buckets(
# #         client, NETWORK_INDEX, query, sources, what="risk score ports"
# #     )
# #     if not complete:
# #         raise QueryFailed(f"risk score ports: stopped at {len(buckets)} device ports")
# #     # Composite buckets come in key order, so each IP's ports are together
# #     return {
# #         ip: [int(b["key"]["port"]) for b in group]
# #         for ip, group in groupby(buckets, key=lambda b: b["key"]["ip"])
# #     }
# # OLD CODE END
# def _all_unsafe_ports(
#     client, bool_query: dict, ips: list[str]
# ) -> dict[str, tuple[list[int], bool]]:
#     """Each of `ips`' ports outside SAFE_PORTS the scorer needs, and whether there are more (#96).
#
#     For devices whose ports_used list was cut short. Every suspicious port is listed, so a
#     single connection to 4444 is never missed; unusual ports are listed up to
#     _UNUSUAL_PORT_LIST, and the flag says the device used more than the list holds.
#     """
#     if not ips:
#         return {}
#     query = {
#         "bool": {
#             **bool_query,
#             "filter": [*bool_query["filter"], {"terms": {"source.ip": ips}}],
#             "must_not": [
#                 *bool_query.get("must_not", []),
#                 {"terms": {"destination.port": sorted(RiskScorer.SAFE_PORTS)}},
#                 _ICMP,  # NET-158: Zeek writes the ICMP code there, not a port
#             ],
#         }
#     }
#     suspicious = sorted(RiskScorer.SUSPICIOUS_PORTS)
#     not_unusual = sorted(RiskScorer.SUSPICIOUS_PORTS | RiskScorer.LOCAL_SERVICE_PORTS)
#     aggs = {
#         "suspicious": {
#             "filter": {"terms": {"destination.port": suspicious}},
#             "aggs": {
#                 "ports": {
#                     "terms": {"field": "destination.port", "size": len(suspicious)}
#                 }
#             },
#         },
#         "unusual": {
#             "filter": {
#                 "bool": {"must_not": [{"terms": {"destination.port": not_unusual}}]}
#             },
#             "aggs": {
#                 "ports": {
#                     "terms": {"field": "destination.port", "size": _UNUSUAL_PORT_LIST}
#                 }
#             },
#         },
#     }
#     buckets, complete = all_buckets(
#         client,
#         NETWORK_INDEX,
#         query,
#         [{"ip": {"terms": {"field": "source.ip"}}}],
#         aggs=aggs,
#         page_size=_PORT_PAGE_SIZE,
#         what="risk score ports",
#     )
#     if not complete:
#         raise QueryFailed(f"risk score ports: stopped at {len(buckets)} devices")
#     result = {}
#     for b in buckets:
#         sus, unusual = b["suspicious"]["ports"], b["unusual"]["ports"]
#         ports = [int(p["key"]) for p in [*sus["buckets"], *unusual["buckets"]]]
#         # Every document in a listed bucket means the list holds every unusual port
#         result[b["key"]["ip"]] = (ports, bool(unusual.get("sum_other_doc_count")))
#     return result
#
#
# def _build_device_stats(
#     ip: str,
#     conn_bucket: dict,
#     alert_count: int,
#     network_avg: float,
#     network_stddev: float,
#     more_ports: list[int] | None = None,
#     more_unusual: bool = False,
# ) -> dict:
#     """Build a device_stats dict from OpenSearch aggregation bucket data.
#
#     more_ports: the device's ports beyond its ports_used list (see _all_unsafe_ports).
#     more_unusual: the device used more unusual ports than those lists hold.
#     """
#     total_conn = conn_bucket.get("doc_count", 0)
#     external_count = conn_bucket.get("external_conns", {}).get("doc_count", 0)
#     orig_bytes = int(conn_bucket.get("total_orig_bytes", {}).get("value", 0) or 0)
#     resp_bytes = int(conn_bucket.get("total_resp_bytes", {}).get("value", 0) or 0)
#
#     # Extract ports used
#     # OLD CODE START — NET-158: see _port_terms
#     # port_buckets = conn_bucket.get("ports_used", {}).get("buckets", [])
#     # OLD CODE END
#     port_buckets = _port_terms(conn_bucket).get("buckets", [])
#     # OLD CODE START — #96: the top 50 ports only, so a busy device's rare port 4444 went unseen
#     # ports = [int(pb["key"]) for pb in port_buckets]
#     # OLD CODE END
#     ports = list(
#         dict.fromkeys([*(int(pb["key"]) for pb in port_buckets), *(more_ports or [])])
#     )
#
#     return {
#         "ip": ip,
#         "alert_count": alert_count,
#         "connection_count": total_conn,
#         "network_avg_connections": network_avg,
#         "network_stddev_connections": network_stddev,
#         "external_connection_count": external_count,
#         "total_connection_count": total_conn,
#         "ports_used": ports,
#         "more_unusual_ports": more_unusual,
#         "orig_bytes": orig_bytes,
#         "resp_bytes": resp_bytes,
#     }
#
#
# def _device_score_aggs() -> dict:
#     """Per-device aggregations the scorer reads (connection count is the bucket's doc_count)."""
#     # OLD CODE START — NET-158: ICMP codes counted as ports (an "unusual port 0" for pings), and
#     # "external" was anything outside RFC1918, so multicast, broadcast, link-local and every
#     # IPv6 address (fe80::, ff02::fb) counted as internet
#     # return {
#     #     "total_orig_bytes": {"sum": {"field": "source.bytes", "missing": 0}},
#     #     "total_resp_bytes": {"sum": {"field": "destination.bytes", "missing": 0}},
#     #     "ports_used": {"terms": {"field": "destination.port", "size": 50}},
#     #     "external_conns": {
#     #         "filter": {
#     #             "bool": {
#     #                 "must_not": [
#     #                     {"term": {"destination.ip": "10.0.0.0/8"}},
#     #                     {"term": {"destination.ip": "172.16.0.0/12"}},
#     #                     {"term": {"destination.ip": "192.168.0.0/16"}},
#     #                 ]
#     #             }
#     #         }
#     #     },
#     # }
#     # OLD CODE END
#     return {
#         "total_orig_bytes": {"sum": {"field": "source.bytes", "missing": 0}},
#         "total_resp_bytes": {"sum": {"field": "destination.bytes", "missing": 0}},
#         **_PORTS_AND_EXTERNAL_AGGS,
#     }
#
#
# _ICMP = {"terms": {"network.transport": ICMP_TRANSPORTS}}
# # The ports and external-share aggregations, shared by the list and the single device
# _PORTS_AND_EXTERNAL_AGGS = {
#     "ports_used": {
#         "filter": {"bool": {"must_not": [_ICMP]}},
#         "aggs": {"ports": {"terms": {"field": "destination.port", "size": 50}}},
#     },
#     # the shared not-internet list: private, loopback, link-local, multicast, broadcast
#     "external_conns": {
#         "filter": {
#             "bool": {"must_not": [{"terms": {"destination.ip": NOT_INTERNET_CIDRS}}]}
#         }
#     },
# }
# OLD CODE END

# THREAT-SCORING.md rule 11: each device is compared with its own last week
_HISTORY_DAYS = 7
_DAY_MS = 86_400_000
_NO_TRAFFIC = {"connections": 0, "upload_bytes": 0}


_ms = epoch_ms  # an ISO time from parse_time_range as epoch ms (no zone means UTC)


def _day_ranges(from_ms: int, to_ms: int) -> list[dict]:
    """Seven whole days before `from`, then the window itself (`to` included, as in the list).

    Explicit ranges aligned to `from`, never a date_histogram, whose calendar days would cut the
    window and the history at midnight UTC instead.
    """
    edges = [from_ms - d * _DAY_MS for d in range(_HISTORY_DAYS, -1, -1)]
    spans = [*zip(edges, edges[1:]), (from_ms, to_ms + 1)]
    return [{"key": str(i), "from": a, "to": b} for i, (a, b) in enumerate(spans)]


def _days_agg(ranges: list[dict], internet: dict, bytes_field: str) -> dict:
    """Per range: the connections, and the bytes the device sent to internet addresses."""
    sent = {"sum": {"field": bytes_field, "missing": 0}}
    return {
        "days": {
            "date_range": {"field": "@timestamp", "ranges": ranges},
            "aggs": {"internet": {"filter": internet, "aggs": {"bytes": sent}}},
        }
    }


def _history(
    client, app, from_ts: str, to_ts: str, ip: str | None = None
) -> dict[str, list[dict]]:
    """Per device, one {connections, upload_bytes} per _day_ranges entry (the last is the window).

    Connections are the ones it opened. Bytes count in both roles: what it sent on connections it
    opened, and what it answered on connections an internet address opened to it (a port-forwarded
    server). Every page is checked: a partial read raises QueryFailed, never a lower figure.
    """
    from_ms, to_ms = _ms(from_ts), _ms(to_ts)
    ranges = _day_ranges(from_ms, to_ms)
    since = _iso_ms(from_ms - _HISTORY_DAYS * _DAY_MS)
    conns = [
        _time_range_filter(since, to_ts),
        {"term": {"event.provider": "zeek"}},
        {"term": {"event.dataset": "conn"}},
    ]
    not_internet = {"terms": {"source.ip": NOT_INTERNET_CIDRS}}
    opened = (
        {"bool": {"filter": [*conns, {"term": {"source.ip": ip}}]}}
        if ip
        else {"bool": _lan_device_bool_query(app, since, to_ts)}
    )
    answered_by = (
        {"term": {"destination.ip": ip}}
        if ip
        else {"terms": {"destination.ip": lan_cidrs(app)}}
    )
    answered = {"bool": {"filter": [*conns, answered_by], "must_not": [not_internet]}}
    to_internet = {
        "bool": {"must_not": [{"terms": {"destination.ip": NOT_INTERNET_CIDRS}}]}
    }
    sides = (
        ("source.ip", opened, _days_agg(ranges, to_internet, "source.bytes"), True),
        ("destination.ip", answered, _days_agg(ranges, {"match_all": {}}, "destination.bytes"), False),
    )
    rows: dict[str, list[dict]] = {}
    for field, query, aggs, counts_connections in sides:
        buckets, complete = all_buckets(
            client,
            NETWORK_INDEX,
            query,
            [{"ip": {"terms": {"field": field}}}],
            aggs=aggs,
            page_size=_SCORE_PAGE_SIZE,
            what="risk score history",
        )
        if not complete:
            raise QueryFailed(f"risk score history: stopped at {len(buckets)} devices")
        for b in buckets:
            days = b.get("days", {}).get("buckets")
            if not isinstance(days, list) or sorted(d.get("key") for d in days) != sorted(
                r["key"] for r in ranges
            ):
                raise QueryFailed("risk score history: malformed day ranges")
            before = rows.get(b["key"]["ip"], [_NO_TRAFFIC] * len(ranges))
            got = {d["key"]: d for d in days}
            rows[b["key"]["ip"]] = [
                {
                    "connections": row["connections"]
                    + (got[r["key"]]["doc_count"] if counts_connections else 0),
                    "upload_bytes": row["upload_bytes"]
                    + int(got[r["key"]]["internet"]["bytes"]["value"] or 0),
                }
                for row, r in zip(before, ranges)
            ]
    return rows


def _own_alerts(client, app, from_ts: str, to_ts: str, ip: str | None = None) -> dict[str, dict]:
    """Per device: each signature in its own traffic at its worst severity, their alert count, and
    whether one is a high or critical alert that is not a reputation hit (rule 5, plan F).

    From the same checked findings as the Threats page, so attempts against a device and
    blocklist hits it did not start never count here.
    """
    groups = get_smart_alerts(
        client,
        from_ts,
        to_ts,
        device_ip=ip,
        include_info=False,
        limit=None,
        lan_cidrs=lan_cidrs(app),
    )
    devices: dict[str, dict] = {}
    for g in groups:
        for f in g["findings"]:
            if not f["own"] or f["severity"] >= _INFO_SEVERITY or (ip and f["device"] != ip):
                continue
            d = devices.get(f["device"], {"signatures": {}, "alert_count": 0, "corroborated": False})
            worst = min(d["signatures"].get(g["signature"], _INFO_SEVERITY), f["severity"])
            devices[f["device"]] = {
                "signatures": {**d["signatures"], g["signature"]: worst},
                "alert_count": d["alert_count"] + f["count"],
                "corroborated": d["corroborated"]
                or (f["severity"] <= 2 and not g["reputation"]),
            }
    return devices


def _device_stats(
    ip: str, connections: int, history: dict, alerts: dict, from_ts: str, to_ts: str
) -> dict:
    """What RiskScorer.score_device reads for one device."""
    days = history.get(ip) or [_NO_TRAFFIC] * (_HISTORY_DAYS + 1)
    own = alerts.get(ip, {})
    return {
        "signatures": own.get("signatures", {}),
        "alert_count": own.get("alert_count", 0),
        "corroborated": own.get("corroborated", False),
        "connections": connections,
        "upload_bytes": days[-1]["upload_bytes"],
        "history": days[:-1],
        "window_days": (_ms(to_ts) - _ms(from_ts)) / _DAY_MS,
    }


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


# OLD CODE START — #139: the scoring queries ran on the request loop and held up every other
# request for up to 7.5 s (the top bar's 5 s liveness check then said "Can't reach NetTap")
# async def handle_risk_scores(request: web.Request) -> web.Response:
# OLD CODE END
async def handle_risk_scores(request: web.Request) -> web.Response:
    """GET /api/risk/scores?from=&to=&limit= — scored in a worker thread (#139)."""
    return await run_blocking(_risk_scores, request)


def _risk_scores(request: web.Request) -> web.Response:
    """GET /api/risk/scores?from=&to=&limit=

    Returns risk scores for every device in the given time range, highest first;
    `limit` (1-500) keeps only the top ones.
    """
    from_ts, to_ts = _parse_time_range(request)
    # OLD CODE START — #96: listed the top 100 by default; Compliance compared that with a different top 100
    # limit_raw = request.query.get("limit", "100")
    # try:
    #     limit = max(1, min(500, int(limit_raw)))
    # except (ValueError, TypeError):
    #     limit = 100
    # OLD CODE END
    # Every device unless a limit is asked for: the list is the device list's whole population
    limit: int | None = None
    try:
        limit = max(1, min(500, int(request.query["limit"])))
    except (KeyError, ValueError, TypeError):
        pass

    client = _get_client(request)
    risk_scorer: RiskScorer = request.app["risk_scorer"]

    # OLD CODE START — #96: a terms list of the busiest 500 IPs; the baseline and the list came from it
    # # Query for device connection aggregations
    # excluded = build_excluded_ips_filter(request.app.get("excluded_ips", []))
    # risk_bool: dict = {
    #     "filter": [
    #         {
    #             "range": {
    #                 "@timestamp": {
    #                     "gte": from_ts,
    #                     "lte": to_ts,
    #                     "format": "strict_date_optional_time",
    #                 }
    #             }
    #         },
    #         {"term": {"event.provider": "zeek"}},
    #         {"term": {"event.dataset": "conn"}},
    #         request.app.get("lan_filter", RFC1918_SOURCE_FILTER),
    #     ],
    # }
    # if excluded:
    #     risk_bool["must_not"] = excluded
    #
    # conn_query = {
    #     "size": 0,
    #     "query": {"bool": risk_bool},
    #     "aggs": {
    #         "devices": {
    #             "terms": {
    #                 "field": "source.ip",
    #                 # OLD CODE START — #83: the baseline came from the top `limit` devices only
    #                 # "size": limit,
    #                 # OLD CODE END
    #                 "size": _BASELINE_DEVICES,
    #             },
    #             "aggs": {
    #                 # OLD CODE START — replaced 2026-11-01: Arkime client/server.bytes are inflated; match traffic.py's source/destination.bytes
    #                 # "total_orig_bytes": {
    #                 #     "sum": {
    #                 #         "script": {
    #                 #             "source": "doc['client.bytes'].size() > 0 ? doc['client.bytes'].value : 0",
    #                 #             "lang": "painless",
    #                 #         }
    #                 #     }
    #                 # },
    #                 # "total_resp_bytes": {
    #                 #     "sum": {
    #                 #         "script": {
    #                 #             "source": "doc['server.bytes'].size() > 0 ? doc['server.bytes'].value : 0",
    #                 #             "lang": "painless",
    #                 #         }
    #                 #     }
    #                 # },
    #                 # OLD CODE END
    #                 "total_orig_bytes": {
    #                     "sum": {"field": "source.bytes", "missing": 0}
    #                 },
    #                 "total_resp_bytes": {
    #                     "sum": {"field": "destination.bytes", "missing": 0}
    #                 },
    #                 "ports_used": {"terms": {"field": "destination.port", "size": 50}},
    #                 "external_conns": {
    #                     "filter": {
    #                         "bool": {
    #                             "must_not": [
    #                                 {"term": {"destination.ip": "10.0.0.0/8"}},
    #                                 {"term": {"destination.ip": "172.16.0.0/12"}},
    #                                 {"term": {"destination.ip": "192.168.0.0/16"}},
    #                             ]
    #                         }
    #                     }
    #                 },
    #             },
    #         },
    #         # OLD CODE START — replaced 2026-11-01: _doc_count is a metadata field, OpenSearch 400s on it (every call 502'd), and nothing read the result
    #         # "conn_stats": {"extended_stats": {"field": "_doc_count"}},
    #         # OLD CODE END
    #     },
    # }
    #
    # try:
    #     conn_result = client.search(index=NETWORK_INDEX, body=conn_query)
    # except OpenSearchException as exc:
    #     logger.error("OpenSearch error in risk scores: %s", exc)
    #     return web.json_response(
    #         {"error": f"OpenSearch query failed: {exc}"}, status=502
    #     )
    #
    # device_buckets = (
    #     conn_result.get("aggregations", {}).get("devices", {}).get("buckets", [])
    # )
    #
    # # Mean and population stddev of per-device connection counts, from the terms buckets
    # if device_buckets:
    #     counts = [b.get("doc_count", 0) for b in device_buckets]
    #     network_avg = sum(counts) / len(counts)
    #     if len(counts) > 1:
    #         variance = sum((c - network_avg) ** 2 for c in counts) / len(counts)
    #         network_stddev = variance**0.5
    #     else:
    #         network_stddev = 0.0
    # else:
    #     network_avg = 0.0
    #     network_stddev = 0.0
    #
    # # Buckets come busiest first: the baseline used all of them, the list shows the top `limit`
    # device_buckets = device_buckets[:limit]
    # OLD CODE END
    # #96: every device the device list can show, so the baseline and the ranking are complete
    # OLD CODE START — NET-209: port lists and byte sums per device; see _history and _own_alerts
    # try:
    #     device_buckets = _lan_device_buckets(
    #         client,
    #         request.app,
    #         from_ts,
    #         to_ts,
    #         aggs=_device_score_aggs(),
    #         page_size=_SCORE_PAGE_SIZE,
    #         what="risk scores",
    #     )
    #     more_ports = _all_unsafe_ports(
    #         client,
    #         _lan_device_bool_query(request.app, from_ts, to_ts),
    #         [b["key"] for b in device_buckets if _ports_cut_short(b)],
    #     )
    # OLD CODE END
    try:
        device_buckets = _lan_device_buckets(
            client,
            request.app,
            from_ts,
            to_ts,
            page_size=_SCORE_PAGE_SIZE,
            what="risk scores",
        )
        history = _history(client, request.app, from_ts, to_ts)
        alerts = _own_alerts(client, request.app, from_ts, to_ts)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in risk scores: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )
    except QueryFailed as exc:
        return _incomplete("risk scores", exc)
    network_avg, network_stddev = _baseline(
        [b.get("doc_count", 0) for b in device_buckets]
    )

    # OLD CODE START — NET-209: every alert whose source was the device, including blocklist hits
    # it never started and ET INFO activity; the alerts factor now reads the device's own findings
#     # Collect all device IPs for batch alert count query
#     device_ips = [b["key"] for b in device_buckets]
#
#     # Batch alert count query
#     # OLD CODE START — #96: one terms filter of every IP failed past 65,536 devices
#     # (index.max_terms_count), and any failure scored every device as having no alerts
#     # alert_counts: dict[str, int] = {}
#     # if device_ips:
#     #     alert_query = {... {"terms": {"source.ip": device_ips}} ... size len(device_ips)}
#     #     try:
#     #         alert_result = client.search(index=NETWORK_INDEX, body=alert_query)
#     #         for ab in alert_result.get("aggregations", {}).get("by_ip", {}).get("buckets", []):
#     #             alert_counts[ab["key"]] = ab["doc_count"]
#     #     except OpenSearchException as exc:
#     #         logger.warning("Alert count query failed: %s", exc)
#     # OLD CODE END
#     alert_counts: dict[str, int] = {}
#     for start in range(0, len(device_ips), _ALERT_IP_CHUNK):
#         chunk = device_ips[start : start + _ALERT_IP_CHUNK]
#         alert_query = {
#             "size": 0,
#             "query": {
#                 "bool": {
#                     "filter": [
#                         {
#                             "range": {
#                                 "@timestamp": {
#                                     "gte": from_ts,
#                                     "lte": to_ts,
#                                     "format": "strict_date_optional_time",
#                                 }
#                             }
#                         },
#                         {"terms": {"source.ip": chunk}},
#                         {"term": {"event.provider": "suricata"}},
#                         {"term": {"event.dataset": "alert"}},
#                     ],
#                     "must_not": SURICATA_NOISE_EXCLUSION,
#                 }
#             },
#             "aggs": {"by_ip": {"terms": {"field": "source.ip", "size": len(chunk)}}},
#         }
#
#         try:
#             alert_result = client.search(index=NETWORK_INDEX, body=alert_query)
#             what = "risk score alert counts"
#             got = checked(alert_result, what, ("by_ip",))["aggregations"]["by_ip"].get(
#                 "buckets"
#             )
#             if not isinstance(got, list):
#                 raise QueryFailed(f"{what}: missing buckets")
#         except OpenSearchException as exc:
#             logger.error("Alert count query failed in risk scores: %s", exc)
#             return web.json_response(
#                 {"error": f"OpenSearch query failed: {exc}"}, status=502
#             )
#         except QueryFailed as exc:
#             return _incomplete("risk scores", exc)
#         # OLD CODE START — a timed-out or partly failed reply read as fewer alerts
#         # for ab in (
#         #     alert_result.get("aggregations", {}).get("by_ip", {}).get("buckets", [])
#         # ):
#         #     alert_counts[ab["key"]] = ab["doc_count"]
#         # OLD CODE END
#         for ab in got:
#             alert_counts[ab["key"]] = ab["doc_count"]
#
#     # Score each device
#     scored_devices = []
#     for bucket in device_buckets:
#         ip = bucket["key"]
#         device_stats = _build_device_stats(
#             ip=ip,
#             conn_bucket=bucket,
#             alert_count=alert_counts.get(ip, 0),
#             network_avg=network_avg,
#             network_stddev=network_stddev,
#             # OLD CODE START — PR #192 review: the port read returns (ports, more) now
#             # more_ports=more_ports.get(ip),
#             # OLD CODE END
#             more_ports=more_ports.get(ip, ([], False))[0],
#             more_unusual=more_ports.get(ip, ([], False))[1],
#         )
#         score_result = risk_scorer.score_device(device_stats)
#         scored_devices.append(
#             {
#                 "ip": ip,
#                 "connection_count": bucket.get("doc_count", 0),
#                 "alert_count": alert_counts.get(ip, 0),
#                 **score_result,
#             }
#         )
    # OLD CODE END
    scored_devices = []
    for bucket in device_buckets:
        ip = bucket["key"]
        stats = _device_stats(ip, bucket.get("doc_count", 0), history, alerts, from_ts, to_ts)
        scored_devices.append(
            {
                "ip": ip,
                "connection_count": bucket.get("doc_count", 0),
                "alert_count": stats["alert_count"],
                **risk_scorer.score_device(stats),
            }
        )

    # OLD CODE START — #96: ranked only the busiest devices it had scored
    # # Sort by score descending (highest risk first)
    # scored_devices.sort(key=lambda d: d["score"], reverse=True)
    # OLD CODE END
    # Highest risk first, the busier device first on a tie; then the top `limit` if one was asked for
    scored_devices = sorted(
        scored_devices, key=lambda d: (d["score"], d["connection_count"]), reverse=True
    )[:limit]

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "device_count": len(scored_devices),
            "network_avg_connections": round(network_avg, 2),
            "network_stddev_connections": round(network_stddev, 2),
            "devices": scored_devices,
        }
    )


@in_thread
def handle_risk_score_single(request: web.Request) -> web.Response:
    """GET /api/risk/scores/{ip}?from=&to=

    Returns risk score for a single device.
    """
    ip = request.match_info["ip"]
    # NET-209: an internet address is never a device, so it has no risk score
    if not lan_check(request.app)(ip):
        return web.json_response({"error": f"{ip} is not on your network"}, status=404)
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)
    risk_scorer: RiskScorer = request.app["risk_scorer"]

    # Query for this device's connection stats
    conn_query = {
        "size": 0,
        # #83: hits.total stops at 10,000 without this; busy devices showed exactly 10,000
        "track_total_hits": True,
        "query": {
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
                    {"term": {"source.ip": ip}},
                    {"term": {"event.provider": "zeek"}},
                    {"term": {"event.dataset": "conn"}},
                ]
            }
        },
        # OLD CODE START — NET-209: byte sums, ports and external share; only the count is read now
#         "aggs": {
#             # OLD CODE START — replaced 2026-11-01: Arkime client/server.bytes are inflated; match traffic.py's source/destination.bytes
#             # "total_orig_bytes": {
#             #     "sum": {
#             #         "script": {
#             #             "source": "doc['client.bytes'].size() > 0 ? doc['client.bytes'].value : 0",
#             #             "lang": "painless",
#             #         }
#             #     }
#             # },
#             # "total_resp_bytes": {
#             #     "sum": {
#             #         "script": {
#             #             "source": "doc['server.bytes'].size() > 0 ? doc['server.bytes'].value : 0",
#             #             "lang": "painless",
#             #         }
#             #     }
#             # },
#             # OLD CODE END
#             "total_orig_bytes": {"sum": {"field": "source.bytes", "missing": 0}},
#             "total_resp_bytes": {"sum": {"field": "destination.bytes", "missing": 0}},
#             # OLD CODE START — NET-158: see _device_score_aggs
#             # "ports_used": {"terms": {"field": "destination.port", "size": 50}},
#             # "external_conns": {
#             #     "filter": {
#             #         "bool": {
#             #             "must_not": [
#             #                 {"term": {"destination.ip": "10.0.0.0/8"}},
#             #                 {"term": {"destination.ip": "172.16.0.0/12"}},
#             #                 {"term": {"destination.ip": "192.168.0.0/16"}},
#             #             ]
#             #         }
#             #     }
#             # },
#             # OLD CODE END
#             **_PORTS_AND_EXTERNAL_AGGS,
#         },
        # OLD CODE END
    }

    try:
        conn_result = client.search(index=NETWORK_INDEX, body=conn_query)
        what = "risk score connections"
        # OLD CODE: checked(conn_result, what, tuple(conn_query["aggs"])) (NET-209: no aggs)
        checked(conn_result, what)
        total_conn = total_hits(conn_result, what)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in single risk score: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )
    except QueryFailed as exc:
        return _incomplete("risk score", exc)

    # OLD CODE START — a timed-out reply or a lower-bound total read as fewer connections
    # total_hits = conn_result.get("hits", {}).get("total", {})
    # total_conn = (
    #     total_hits.get("value", 0) if isinstance(total_hits, dict) else total_hits
    # )
    # OLD CODE END

    if total_conn == 0:
        return web.json_response(
            {"error": f"No connection data found for {ip}"}, status=404
        )

    # OLD CODE START — NET-209: ports, a network-wide connection baseline and every alert from the
    # address; the score now reads the device's own findings and its own last week
#     aggs = conn_result.get("aggregations", {})
#
#     # Build a pseudo-bucket for _build_device_stats
#     pseudo_bucket = {
#         "doc_count": total_conn,
#         "total_orig_bytes": aggs.get("total_orig_bytes", {}),
#         "total_resp_bytes": aggs.get("total_resp_bytes", {}),
#         "ports_used": aggs.get("ports_used", {}),
#         "external_conns": aggs.get("external_conns", {}),
#     }
#
#     more_ports: list[int] = []
#     more_unusual = False
#     if _ports_cut_short(pseudo_bucket):
#         try:
#             # OLD CODE START — PR #192 review: the port read returns (ports, more) now
#             # more_ports = _all_unsafe_ports(
#             #     client, conn_query["query"]["bool"], [ip]
#             # ).get(ip, [])
#             # OLD CODE END
#             more_ports, more_unusual = _all_unsafe_ports(
#                 client, conn_query["query"]["bool"], [ip]
#             ).get(ip, ([], False))
#         except OpenSearchException as exc:
#             logger.error("OpenSearch error in single risk score ports: %s", exc)
#             return web.json_response(
#                 {"error": f"OpenSearch query failed: {exc}"}, status=502
#             )
#         except QueryFailed as exc:
#             return _incomplete("risk score", exc)
#
#     # OLD CODE START — #96: the baseline came from the busiest 500 devices
#     # # Get network-wide stats for anomaly detection
#     # net_excluded = build_excluded_ips_filter(request.app.get("excluded_ips", []))
#     # net_bool: dict = {
#     #     "filter": [
#     #         {
#     #             "range": {
#     #                 "@timestamp": {
#     #                     "gte": from_ts,
#     #                     "lte": to_ts,
#     #                     "format": "strict_date_optional_time",
#     #                 }
#     #             }
#     #         },
#     #         {"term": {"event.provider": "zeek"}},
#     #         {"term": {"event.dataset": "conn"}},
#     #         # Same LAN population as /api/risk/scores, so the baseline matches the list view
#     #         request.app.get("lan_filter", RFC1918_SOURCE_FILTER),
#     #     ],
#     # }
#     # if net_excluded:
#     #     net_bool["must_not"] = net_excluded
#     #
#     # network_query = {
#     #     "size": 0,
#     #     "query": {"bool": net_bool},
#     #     "aggs": {"devices": {"terms": {"field": "source.ip", "size": _BASELINE_DEVICES}}},
#     # }
#     #
#     # network_avg = 0.0
#     # network_stddev = 0.0
#     # try:
#     #     network_result = client.search(index=NETWORK_INDEX, body=network_query)
#     #     net_buckets = (
#     #         network_result.get("aggregations", {}).get("devices", {}).get("buckets", [])
#     #     )
#     #     if net_buckets:
#     #         counts = [b.get("doc_count", 0) for b in net_buckets]
#     #         network_avg = sum(counts) / len(counts)
#     #         if len(counts) > 1:
#     #             variance = sum((c - network_avg) ** 2 for c in counts) / len(counts)
#     #             network_stddev = variance**0.5
#     # except OpenSearchException as exc:
#     #     logger.warning("Network stats query failed: %s", exc)
#     # OLD CODE END
#     # Network-wide baseline over the list view's population: every device the device list can show
#     # OLD CODE START — #96: a failure scored the device against a 0 ± 0 baseline
#     # network_avg = 0.0
#     # network_stddev = 0.0
#     # try:
#     #     devices = _lan_device_buckets(client, request.app, from_ts, to_ts)
#     #     network_avg, network_stddev = _baseline([b.get("doc_count", 0) for b in devices])
#     # except OpenSearchException as exc:
#     #     logger.warning("Network stats query failed: %s", exc)
#     # OLD CODE END
#     try:
#         devices = _lan_device_buckets(
#             client, request.app, from_ts, to_ts, what="risk score baseline"
#         )
#     except OpenSearchException as exc:
#         logger.error("Network stats query failed in single risk score: %s", exc)
#         return web.json_response(
#             {"error": f"OpenSearch query failed: {exc}"}, status=502
#         )
#     except QueryFailed as exc:
#         return _incomplete("risk score", exc)
#     network_avg, network_stddev = _baseline([b.get("doc_count", 0) for b in devices])
#
#     # Alert count for this device
#     alert_count = 0
#     alert_query = {
#         "size": 0,
#         "track_total_hits": True,  # #83: same 10,000 cap as the connection count
#         "query": {
#             "bool": {
#                 "filter": [
#                     {
#                         "range": {
#                             "@timestamp": {
#                                 "gte": from_ts,
#                                 "lte": to_ts,
#                                 "format": "strict_date_optional_time",
#                             }
#                         }
#                     },
#                     {"term": {"source.ip": ip}},
#                     {"term": {"event.provider": "suricata"}},
#                     {"term": {"event.dataset": "alert"}},
#                 ],
#                 "must_not": SURICATA_NOISE_EXCLUSION,
#             }
#         },
#     }
#
#     try:
#         alert_result = client.search(index=NETWORK_INDEX, body=alert_query)
#         # OLD CODE START — a timed-out reply or a lower-bound total read as fewer alerts
#         # alert_total = alert_result.get("hits", {}).get("total", {})
#         # alert_count = (
#         #     alert_total.get("value", 0)
#         #     if isinstance(alert_total, dict)
#         #     else alert_total
#         # )
#         # OLD CODE END
#         what = "risk score alert count"
#         alert_count = total_hits(checked(alert_result, what), what)
#     # OLD CODE START — #96: a failure scored the device as having no alerts
#     # except OpenSearchException as exc:
#     #     logger.warning("Alert count query failed for %s: %s", ip, exc)
#     # OLD CODE END
#     except OpenSearchException as exc:
#         logger.error("Alert count query failed for %s: %s", ip, exc)
#         return web.json_response(
#             {"error": f"OpenSearch query failed: {exc}"}, status=502
#         )
#     except QueryFailed as exc:
#         return _incomplete("risk score", exc)
#
#     device_stats = _build_device_stats(
#         ip=ip,
#         conn_bucket=pseudo_bucket,
#         alert_count=alert_count,
#         network_avg=network_avg,
#         network_stddev=network_stddev,
#         more_ports=more_ports,
#         more_unusual=more_unusual,
#     )
#     score_result = risk_scorer.score_device(device_stats)
    # OLD CODE END
    try:
        history = _history(client, request.app, from_ts, to_ts, ip)
        alerts = _own_alerts(client, request.app, from_ts, to_ts, ip)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in single risk score: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )
    except QueryFailed as exc:
        return _incomplete("risk score", exc)
    device_stats = _device_stats(ip, total_conn, history, alerts, from_ts, to_ts)
    alert_count = device_stats["alert_count"]
    score_result = risk_scorer.score_device(device_stats)

    return web.json_response(
        {
            "ip": ip,
            "from": from_ts,
            "to": to_ts,
            "connection_count": total_conn,
            "alert_count": alert_count,
            **score_result,
        }
    )


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_risk_routes(
    app: web.Application,
    risk_scorer: RiskScorer,
    storage_manager: StorageManager,
) -> None:
    """Register all risk scoring API routes on the given aiohttp application."""
    app["risk_scorer"] = risk_scorer
    app.router.add_get("/api/risk/scores", handle_risk_scores)
    app.router.add_get("/api/risk/scores/{ip}", handle_risk_score_single)
    logger.info("Risk scoring API routes registered (2 endpoints)")
