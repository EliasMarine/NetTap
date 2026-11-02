"""
NetTap Risk Scoring API Routes

Registers device risk scoring endpoints with the aiohttp application.
These endpoints compute per-device risk scores (0-100) based on network
telemetry data from OpenSearch indices.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from itertools import groupby

from aiohttp import web
from opensearchpy import OpenSearchException

from api.alerts import SURICATA_NOISE_EXCLUSION
from api.devices import _lan_device_bool_query, _lan_device_buckets
# OLD CODE START — #96: the population's filters come from api.devices._lan_device_bool_query now
# from services.excluded_ips import build_excluded_ips_filter, RFC1918_SOURCE_FILTER
# OLD CODE END
from services.risk_scoring import RiskScorer
from storage.all_buckets import all_buckets
from storage.manager import StorageManager

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


def _baseline(counts: list[int]) -> tuple[float, float]:
    """Mean and population stddev of per-device connection counts."""
    if not counts:
        return 0.0, 0.0
    avg = sum(counts) / len(counts)
    return avg, (sum((c - avg) ** 2 for c in counts) / len(counts)) ** 0.5


def _parse_time_range(request: web.Request) -> tuple[str, str]:
    """Extract 'from' and 'to' query parameters as ISO timestamps."""
    now = datetime.now(timezone.utc)
    default_from = (now - timedelta(hours=_DEFAULT_RANGE_HOURS)).isoformat()
    default_to = now.isoformat()

    raw_from = request.query.get("from", "")
    raw_to = request.query.get("to", "")

    if raw_from:
        try:
            datetime.fromisoformat(raw_from.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raw_from = ""
    if raw_to:
        try:
            datetime.fromisoformat(raw_to.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raw_to = ""

    return (raw_from or default_from, raw_to or default_to)


def _get_client(request: web.Request):
    """Retrieve the OpenSearch client from the StorageManager on the app."""
    storage: StorageManager = request.app["storage"]
    return storage._client


def _ports_cut_short(conn_bucket: dict) -> bool:
    """True if the device used more ports than its top-50 ports_used list holds."""
    return bool(conn_bucket.get("ports_used", {}).get("sum_other_doc_count", 0))


def _all_unsafe_ports(client, bool_query: dict, ips: list[str]) -> dict[str, list[int]]:
    """Every port outside SAFE_PORTS that each of `ips` connected to (#96).

    For devices whose ports_used list was cut short: the scorer flags any port outside
    SAFE_PORTS, so a single connection to 4444 must not fall off the end of a top-50 list.
    """
    if not ips:
        return {}
    query = {
        "bool": {
            **bool_query,
            "filter": [*bool_query["filter"], {"terms": {"source.ip": ips}}],
            "must_not": [
                *bool_query.get("must_not", []),
                {"terms": {"destination.port": sorted(RiskScorer.SAFE_PORTS)}},
            ],
        }
    }
    sources = [{"ip": {"terms": {"field": "source.ip"}}}, {"port": {"terms": {"field": "destination.port"}}}]
    buckets, complete = all_buckets(client, NETWORK_INDEX, query, sources)
    if not complete:
        logger.warning("Port lists stopped at %d device ports; scores cover those only", len(buckets))
    # Composite buckets come in key order, so each IP's ports are together
    return {
        ip: [int(b["key"]["port"]) for b in group]
        for ip, group in groupby(buckets, key=lambda b: b["key"]["ip"])
    }


def _build_device_stats(
    ip: str,
    conn_bucket: dict,
    alert_count: int,
    network_avg: float,
    network_stddev: float,
    more_ports: list[int] | None = None,
) -> dict:
    """Build a device_stats dict from OpenSearch aggregation bucket data.

    more_ports: the device's ports beyond its ports_used list (see _all_unsafe_ports).
    """
    total_conn = conn_bucket.get("doc_count", 0)
    external_count = conn_bucket.get("external_conns", {}).get("doc_count", 0)
    orig_bytes = int(conn_bucket.get("total_orig_bytes", {}).get("value", 0) or 0)
    resp_bytes = int(conn_bucket.get("total_resp_bytes", {}).get("value", 0) or 0)

    # Extract ports used
    port_buckets = conn_bucket.get("ports_used", {}).get("buckets", [])
    # OLD CODE START — #96: the top 50 ports only, so a busy device's rare port 4444 went unseen
    # ports = [int(pb["key"]) for pb in port_buckets]
    # OLD CODE END
    ports = list(dict.fromkeys([*(int(pb["key"]) for pb in port_buckets), *(more_ports or [])]))

    return {
        "ip": ip,
        "alert_count": alert_count,
        "connection_count": total_conn,
        "network_avg_connections": network_avg,
        "network_stddev_connections": network_stddev,
        "external_connection_count": external_count,
        "total_connection_count": total_conn,
        "ports_used": ports,
        "orig_bytes": orig_bytes,
        "resp_bytes": resp_bytes,
    }


def _device_score_aggs() -> dict:
    """Per-device aggregations the scorer reads (connection count is the bucket's doc_count)."""
    return {
        "total_orig_bytes": {"sum": {"field": "source.bytes", "missing": 0}},
        "total_resp_bytes": {"sum": {"field": "destination.bytes", "missing": 0}},
        "ports_used": {"terms": {"field": "destination.port", "size": 50}},
        "external_conns": {
            "filter": {
                "bool": {
                    "must_not": [
                        {"term": {"destination.ip": "10.0.0.0/8"}},
                        {"term": {"destination.ip": "172.16.0.0/12"}},
                        {"term": {"destination.ip": "192.168.0.0/16"}},
                    ]
                }
            }
        },
    }


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def handle_risk_scores(request: web.Request) -> web.Response:
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
    try:
        device_buckets = _lan_device_buckets(
            client, request.app, from_ts, to_ts, aggs=_device_score_aggs(), page_size=_SCORE_PAGE_SIZE
        )
        more_ports = _all_unsafe_ports(
            client,
            _lan_device_bool_query(request.app, from_ts, to_ts),
            [b["key"] for b in device_buckets if _ports_cut_short(b)],
        )
    except OpenSearchException as exc:
        logger.error("OpenSearch error in risk scores: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )
    network_avg, network_stddev = _baseline([b.get("doc_count", 0) for b in device_buckets])

    # Collect all device IPs for batch alert count query
    device_ips = [b["key"] for b in device_buckets]

    # Batch alert count query
    # shortcut: one terms filter of every device IP; past 65,536 devices (index.max_terms_count)
    # it fails and scores count no alerts, so chunk the IPs if a site ever gets there
    alert_counts: dict[str, int] = {}
    if device_ips:
        alert_query = {
            "size": 0,
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
                        {"terms": {"source.ip": device_ips}},
                        {"term": {"event.provider": "suricata"}},
                        {"term": {"event.dataset": "alert"}},
                    ],
                    "must_not": SURICATA_NOISE_EXCLUSION,
                }
            },
            "aggs": {
                "by_ip": {"terms": {"field": "source.ip", "size": len(device_ips)}}
            },
        }

        try:
            alert_result = client.search(index=NETWORK_INDEX, body=alert_query)
            for ab in (
                alert_result.get("aggregations", {}).get("by_ip", {}).get("buckets", [])
            ):
                alert_counts[ab["key"]] = ab["doc_count"]
        except OpenSearchException as exc:
            logger.warning("Alert count query failed: %s", exc)

    # Score each device
    scored_devices = []
    for bucket in device_buckets:
        ip = bucket["key"]
        device_stats = _build_device_stats(
            ip=ip,
            conn_bucket=bucket,
            alert_count=alert_counts.get(ip, 0),
            network_avg=network_avg,
            network_stddev=network_stddev,
            more_ports=more_ports.get(ip),
        )
        score_result = risk_scorer.score_device(device_stats)
        scored_devices.append(
            {
                "ip": ip,
                "connection_count": bucket.get("doc_count", 0),
                "alert_count": alert_counts.get(ip, 0),
                **score_result,
            }
        )

    # OLD CODE START — #96: ranked only the busiest devices it had scored
    # # Sort by score descending (highest risk first)
    # scored_devices.sort(key=lambda d: d["score"], reverse=True)
    # OLD CODE END
    # Highest risk first, the busier device first on a tie; then the top `limit` if one was asked for
    scored_devices = sorted(scored_devices, key=lambda d: (d["score"], d["connection_count"]), reverse=True)[:limit]

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


async def handle_risk_score_single(request: web.Request) -> web.Response:
    """GET /api/risk/scores/{ip}?from=&to=

    Returns risk score for a single device.
    """
    ip = request.match_info["ip"]
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
        "aggs": {
            # OLD CODE START — replaced 2026-11-01: Arkime client/server.bytes are inflated; match traffic.py's source/destination.bytes
            # "total_orig_bytes": {
            #     "sum": {
            #         "script": {
            #             "source": "doc['client.bytes'].size() > 0 ? doc['client.bytes'].value : 0",
            #             "lang": "painless",
            #         }
            #     }
            # },
            # "total_resp_bytes": {
            #     "sum": {
            #         "script": {
            #             "source": "doc['server.bytes'].size() > 0 ? doc['server.bytes'].value : 0",
            #             "lang": "painless",
            #         }
            #     }
            # },
            # OLD CODE END
            "total_orig_bytes": {"sum": {"field": "source.bytes", "missing": 0}},
            "total_resp_bytes": {"sum": {"field": "destination.bytes", "missing": 0}},
            "ports_used": {"terms": {"field": "destination.port", "size": 50}},
            "external_conns": {
                "filter": {
                    "bool": {
                        "must_not": [
                            {"term": {"destination.ip": "10.0.0.0/8"}},
                            {"term": {"destination.ip": "172.16.0.0/12"}},
                            {"term": {"destination.ip": "192.168.0.0/16"}},
                        ]
                    }
                }
            },
        },
    }

    try:
        conn_result = client.search(index=NETWORK_INDEX, body=conn_query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in single risk score: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    total_hits = conn_result.get("hits", {}).get("total", {})
    total_conn = (
        total_hits.get("value", 0) if isinstance(total_hits, dict) else total_hits
    )

    if total_conn == 0:
        return web.json_response(
            {"error": f"No connection data found for {ip}"}, status=404
        )

    aggs = conn_result.get("aggregations", {})

    # Build a pseudo-bucket for _build_device_stats
    pseudo_bucket = {
        "doc_count": total_conn,
        "total_orig_bytes": aggs.get("total_orig_bytes", {}),
        "total_resp_bytes": aggs.get("total_resp_bytes", {}),
        "ports_used": aggs.get("ports_used", {}),
        "external_conns": aggs.get("external_conns", {}),
    }

    more_ports: list[int] = []
    if _ports_cut_short(pseudo_bucket):
        try:
            more_ports = _all_unsafe_ports(client, conn_query["query"]["bool"], [ip]).get(ip, [])
        except OpenSearchException as exc:
            logger.error("OpenSearch error in single risk score ports: %s", exc)
            return web.json_response(
                {"error": f"OpenSearch query failed: {exc}"}, status=502
            )

    # OLD CODE START — #96: the baseline came from the busiest 500 devices
    # # Get network-wide stats for anomaly detection
    # net_excluded = build_excluded_ips_filter(request.app.get("excluded_ips", []))
    # net_bool: dict = {
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
    #         # Same LAN population as /api/risk/scores, so the baseline matches the list view
    #         request.app.get("lan_filter", RFC1918_SOURCE_FILTER),
    #     ],
    # }
    # if net_excluded:
    #     net_bool["must_not"] = net_excluded
    #
    # network_query = {
    #     "size": 0,
    #     "query": {"bool": net_bool},
    #     "aggs": {"devices": {"terms": {"field": "source.ip", "size": _BASELINE_DEVICES}}},
    # }
    #
    # network_avg = 0.0
    # network_stddev = 0.0
    # try:
    #     network_result = client.search(index=NETWORK_INDEX, body=network_query)
    #     net_buckets = (
    #         network_result.get("aggregations", {}).get("devices", {}).get("buckets", [])
    #     )
    #     if net_buckets:
    #         counts = [b.get("doc_count", 0) for b in net_buckets]
    #         network_avg = sum(counts) / len(counts)
    #         if len(counts) > 1:
    #             variance = sum((c - network_avg) ** 2 for c in counts) / len(counts)
    #             network_stddev = variance**0.5
    # except OpenSearchException as exc:
    #     logger.warning("Network stats query failed: %s", exc)
    # OLD CODE END
    # Network-wide baseline over the list view's population: every device the device list can show
    network_avg = 0.0
    network_stddev = 0.0
    try:
        devices = _lan_device_buckets(client, request.app, from_ts, to_ts)
        network_avg, network_stddev = _baseline([b.get("doc_count", 0) for b in devices])
    except OpenSearchException as exc:
        logger.warning("Network stats query failed: %s", exc)

    # Alert count for this device
    alert_count = 0
    alert_query = {
        "size": 0,
        "track_total_hits": True,  # #83: same 10,000 cap as the connection count
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
                    {"term": {"event.provider": "suricata"}},
                    {"term": {"event.dataset": "alert"}},
                ],
                "must_not": SURICATA_NOISE_EXCLUSION,
            }
        },
    }

    try:
        alert_result = client.search(index=NETWORK_INDEX, body=alert_query)
        alert_total = alert_result.get("hits", {}).get("total", {})
        alert_count = (
            alert_total.get("value", 0)
            if isinstance(alert_total, dict)
            else alert_total
        )
    except OpenSearchException as exc:
        logger.warning("Alert count query failed for %s: %s", ip, exc)

    device_stats = _build_device_stats(
        ip=ip,
        conn_bucket=pseudo_bucket,
        alert_count=alert_count,
        network_avg=network_avg,
        network_stddev=network_stddev,
        more_ports=more_ports,
    )
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
