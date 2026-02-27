"""
NetTap Risk Scoring API Routes

Registers device risk scoring endpoints with the aiohttp application.
These endpoints compute per-device risk scores (0-100) based on network
telemetry data from OpenSearch indices.
"""

import logging
from datetime import datetime, timedelta, timezone

from aiohttp import web
from opensearchpy import OpenSearchException

from services.risk_scoring import RiskScorer
from storage.manager import StorageManager

logger = logging.getLogger("nettap.api.risk")

# Index patterns
ZEEK_CONN_INDEX = "zeek-conn-*"
SURICATA_INDEX = "suricata-*"

# Default time range: last 24 hours
_DEFAULT_RANGE_HOURS = 24


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _build_device_stats(
    ip: str,
    conn_bucket: dict,
    alert_count: int,
    network_avg: float,
    network_stddev: float,
) -> dict:
    """Build a device_stats dict from OpenSearch aggregation bucket data."""
    total_conn = conn_bucket.get("doc_count", 0)
    external_count = conn_bucket.get("external_conns", {}).get("doc_count", 0)
    orig_bytes = int(conn_bucket.get("total_orig_bytes", {}).get("value", 0) or 0)
    resp_bytes = int(conn_bucket.get("total_resp_bytes", {}).get("value", 0) or 0)

    # Extract ports used
    port_buckets = conn_bucket.get("ports_used", {}).get("buckets", [])
    ports = [int(pb["key"]) for pb in port_buckets]

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


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def handle_risk_scores(request: web.Request) -> web.Response:
    """GET /api/risk/scores?from=&to=&limit=100

    Returns risk scores for all devices in the given time range.
    """
    from_ts, to_ts = _parse_time_range(request)
    limit_raw = request.query.get("limit", "100")
    try:
        limit = max(1, min(500, int(limit_raw)))
    except (ValueError, TypeError):
        limit = 100

    client = _get_client(request)
    risk_scorer: RiskScorer = request.app["risk_scorer"]

    # Query for device connection aggregations
    conn_query = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {
                        "range": {
                            "ts": {
                                "gte": from_ts,
                                "lte": to_ts,
                                "format": "strict_date_optional_time",
                            }
                        }
                    }
                ]
            }
        },
        "aggs": {
            "devices": {
                "terms": {
                    "field": "id.orig_h",
                    "size": limit,
                },
                "aggs": {
                    "total_orig_bytes": {
                        "sum": {
                            "script": {
                                "source": "doc['orig_bytes'].size() > 0 ? doc['orig_bytes'].value : 0",
                                "lang": "painless",
                            }
                        }
                    },
                    "total_resp_bytes": {
                        "sum": {
                            "script": {
                                "source": "doc['resp_bytes'].size() > 0 ? doc['resp_bytes'].value : 0",
                                "lang": "painless",
                            }
                        }
                    },
                    "ports_used": {"terms": {"field": "id.resp_p", "size": 50}},
                    "external_conns": {
                        "filter": {
                            "bool": {
                                "must_not": [
                                    {"term": {"id.resp_h": "10.0.0.0/8"}},
                                    {"term": {"id.resp_h": "172.16.0.0/12"}},
                                    {"term": {"id.resp_h": "192.168.0.0/16"}},
                                ]
                            }
                        }
                    },
                },
            },
            "conn_stats": {"extended_stats": {"field": "_doc_count"}},
        },
    }

    try:
        conn_result = client.search(index=ZEEK_CONN_INDEX, body=conn_query)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in risk scores: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    device_buckets = (
        conn_result.get("aggregations", {}).get("devices", {}).get("buckets", [])
    )

    # Compute network average and stddev from bucket doc_counts
    if device_buckets:
        counts = [b.get("doc_count", 0) for b in device_buckets]
        network_avg = sum(counts) / len(counts)
        if len(counts) > 1:
            variance = sum((c - network_avg) ** 2 for c in counts) / len(counts)
            network_stddev = variance**0.5
        else:
            network_stddev = 0.0
    else:
        network_avg = 0.0
        network_stddev = 0.0

    # Collect all device IPs for batch alert count query
    device_ips = [b["key"] for b in device_buckets]

    # Batch alert count query
    alert_counts: dict[str, int] = {}
    if device_ips:
        alert_query = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {
                            "range": {
                                "timestamp": {
                                    "gte": from_ts,
                                    "lte": to_ts,
                                    "format": "strict_date_optional_time",
                                }
                            }
                        },
                        {"terms": {"src_ip": device_ips}},
                    ]
                }
            },
            "aggs": {"by_ip": {"terms": {"field": "src_ip", "size": len(device_ips)}}},
        }

        try:
            alert_result = client.search(index=SURICATA_INDEX, body=alert_query)
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

    # Sort by score descending (highest risk first)
    scored_devices.sort(key=lambda d: d["score"], reverse=True)

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
        "query": {
            "bool": {
                "filter": [
                    {
                        "range": {
                            "ts": {
                                "gte": from_ts,
                                "lte": to_ts,
                                "format": "strict_date_optional_time",
                            }
                        }
                    },
                    {"term": {"id.orig_h": ip}},
                ]
            }
        },
        "aggs": {
            "total_orig_bytes": {
                "sum": {
                    "script": {
                        "source": "doc['orig_bytes'].size() > 0 ? doc['orig_bytes'].value : 0",
                        "lang": "painless",
                    }
                }
            },
            "total_resp_bytes": {
                "sum": {
                    "script": {
                        "source": "doc['resp_bytes'].size() > 0 ? doc['resp_bytes'].value : 0",
                        "lang": "painless",
                    }
                }
            },
            "ports_used": {"terms": {"field": "id.resp_p", "size": 50}},
            "external_conns": {
                "filter": {
                    "bool": {
                        "must_not": [
                            {"term": {"id.resp_h": "10.0.0.0/8"}},
                            {"term": {"id.resp_h": "172.16.0.0/12"}},
                            {"term": {"id.resp_h": "192.168.0.0/16"}},
                        ]
                    }
                }
            },
        },
    }

    try:
        conn_result = client.search(index=ZEEK_CONN_INDEX, body=conn_query)
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

    # Get network-wide stats for anomaly detection
    network_query = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {
                        "range": {
                            "ts": {
                                "gte": from_ts,
                                "lte": to_ts,
                                "format": "strict_date_optional_time",
                            }
                        }
                    }
                ]
            }
        },
        "aggs": {"devices": {"terms": {"field": "id.orig_h", "size": 500}}},
    }

    network_avg = 0.0
    network_stddev = 0.0
    try:
        network_result = client.search(index=ZEEK_CONN_INDEX, body=network_query)
        net_buckets = (
            network_result.get("aggregations", {}).get("devices", {}).get("buckets", [])
        )
        if net_buckets:
            counts = [b.get("doc_count", 0) for b in net_buckets]
            network_avg = sum(counts) / len(counts)
            if len(counts) > 1:
                variance = sum((c - network_avg) ** 2 for c in counts) / len(counts)
                network_stddev = variance**0.5
    except OpenSearchException as exc:
        logger.warning("Network stats query failed: %s", exc)

    # Alert count for this device
    alert_count = 0
    alert_query = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {
                        "range": {
                            "timestamp": {
                                "gte": from_ts,
                                "lte": to_ts,
                                "format": "strict_date_optional_time",
                            }
                        }
                    },
                    {"term": {"src_ip": ip}},
                ]
            }
        },
    }

    try:
        alert_result = client.search(index=SURICATA_INDEX, body=alert_query)
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
