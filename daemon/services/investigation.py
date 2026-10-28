"""
NetTap Auto-Investigation Service

When a critical alert fires, automatically gathers the forensic context
an analyst would need: host profile, connection history, related alerts,
DNS context, and actionable recommendations.
"""

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("nettap.services.investigation")

NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")


async def auto_investigate(client, alert: dict) -> dict:
    """Auto-gather forensic context for a critical alert."""
    src_ip = alert.get("source_ip", "")
    dst_ip = alert.get("destination_ip", "")

    investigation = {
        "alert": {
            "signature": alert.get("signature"),
            "severity_label": alert.get("severity_label"),
            "category_label": alert.get("category_label"),
            "source_ip": src_ip,
            "destination_ip": dst_ip,
            "count": alert.get("count"),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sections": {},
    }

    # 1. Source host profile
    investigation["sections"]["source_profile"] = _get_host_profile(client, src_ip)

    # 2. Destination host profile
    investigation["sections"]["destination_profile"] = _get_host_profile(client, dst_ip)

    # 3. Connection history between this pair (last 7 days)
    investigation["sections"]["connection_history"] = _get_pair_history(client, src_ip, dst_ip)

    # 4. Recommendation
    investigation["recommendation"] = _generate_recommendation(alert)

    return investigation


def _get_host_profile(client, ip: str) -> dict:
    """Get basic host profile from connection data."""
    query = {
        "size": 0,
        "query": {"bool": {"filter": [
            {"range": {"@timestamp": {"gte": "now-24h"}}},
            {"term": {"source.ip.keyword": ip}},
            {"term": {"event.provider": "zeek"}},
            {"term": {"event.dataset": "conn"}},
        ]}},
        "aggs": {
            "total_bytes": {"sum": {"field": "source.bytes"}},
            "unique_dests": {"cardinality": {"field": "destination.ip.keyword"}},
            "protocols": {"terms": {"field": "network.transport.keyword", "size": 5}},
            "top_ports": {"terms": {"field": "destination.port", "size": 5}},
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except Exception:
        return {"ip": ip, "error": "Query failed"}

    aggs = result.get("aggregations", {})
    hits_total = result.get("hits", {}).get("total", {})
    conn_count = hits_total.get("value", 0) if isinstance(hits_total, dict) else hits_total

    return {
        "ip": ip,
        "connection_count_24h": conn_count,
        "total_bytes_24h": int(aggs.get("total_bytes", {}).get("value", 0)),
        "unique_destinations": aggs.get("unique_dests", {}).get("value", 0),
        "protocols": [b["key"] for b in aggs.get("protocols", {}).get("buckets", [])],
        "top_ports": [b["key"] for b in aggs.get("top_ports", {}).get("buckets", [])],
    }


def _get_pair_history(client, src_ip: str, dst_ip: str) -> dict:
    """Get connection history between two IPs over last 7 days."""
    query = {
        "size": 0,
        "query": {"bool": {"filter": [
            {"range": {"@timestamp": {"gte": "now-7d"}}},
            {"term": {"source.ip.keyword": src_ip}},
            {"term": {"destination.ip.keyword": dst_ip}},
            {"term": {"event.provider": "zeek"}},
            {"term": {"event.dataset": "conn"}},
        ]}},
        "aggs": {
            "total_bytes": {
                "sum": {
                    "script": {
                        "source": "(doc['source.bytes'].size() > 0 ? doc['source.bytes'].value : 0) + (doc['destination.bytes'].size() > 0 ? doc['destination.bytes'].value : 0)",
                        "lang": "painless",
                    }
                }
            },
            "first_seen": {"min": {"field": "@timestamp"}},
            "last_seen": {"max": {"field": "@timestamp"}},
            "by_day": {
                "date_histogram": {"field": "@timestamp", "calendar_interval": "day", "min_doc_count": 0},
            },
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except Exception:
        return {"error": "Query failed"}

    aggs = result.get("aggregations", {})
    hits_total = result.get("hits", {}).get("total", {})
    total_conns = hits_total.get("value", 0) if isinstance(hits_total, dict) else hits_total

    daily = [
        {"date": b.get("key_as_string", ""), "count": b["doc_count"]}
        for b in aggs.get("by_day", {}).get("buckets", [])
    ]

    return {
        "source_ip": src_ip,
        "destination_ip": dst_ip,
        "total_connections_7d": total_conns,
        "total_bytes_7d": int(aggs.get("total_bytes", {}).get("value", 0)),
        "first_seen": aggs.get("first_seen", {}).get("value_as_string"),
        "last_seen": aggs.get("last_seen", {}).get("value_as_string"),
        "daily_breakdown": daily,
    }


def _generate_recommendation(alert: dict) -> str:
    """Generate specific action recommendation."""
    parts = []
    sev = alert.get("severity", 4)
    cat = alert.get("category", "")

    if sev <= 1:
        parts.append("IMMEDIATE: Isolate the source host from the network.")
    elif sev <= 2:
        parts.append("HIGH PRIORITY: Investigate this alert within the next hour.")

    if cat == "malware_c2":
        parts.append("Check for malware on the source device. Scan with endpoint security tools.")
    elif cat == "exfiltration":
        parts.append("Check for data exfiltration — review large outbound transfers.")
    elif cat == "reconnaissance":
        parts.append("Determine if this is authorized scanning (pentest, vulnerability scan).")

    ti = alert.get("threat_intel", [])
    if ti:
        parts.append(f"Destination matches {ti[0].get('label', 'threat intel')} — block at firewall.")

    if not parts:
        parts.append("Review the connection history and related alerts for patterns.")

    return " ".join(parts)


async def generate_threat_report(client, from_ts: str, to_ts: str) -> dict:
    """Unified threat report — the single API call that powers the /threats page."""
    from services.alert_intelligence import get_smart_alerts, get_smart_alert_summary, detect_kill_chains
    from services.threat_detection import detect_beaconing, detect_lateral_movement, analyze_dns_anomalies

    summary = await get_smart_alert_summary(client, from_ts, to_ts)
    alerts = await get_smart_alerts(client, from_ts, to_ts, include_info=False, limit=200)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period": {"from": from_ts, "to": to_ts},
        "summary": summary,
        "kill_chains": detect_kill_chains(alerts),
        "beaconing": detect_beaconing(client, from_ts, to_ts),
        "dns_anomalies": analyze_dns_anomalies(client, from_ts, to_ts),
        "lateral_movement": detect_lateral_movement(client, from_ts, to_ts),
        "investigations": [],
    }

    # Auto-investigate top critical alerts (cap at 3)
    critical = [a for a in alerts if a.get("severity", 5) <= 2]
    for alert in critical[:3]:
        try:
            inv = await auto_investigate(client, alert)
            report["investigations"].append(inv)
        except Exception:
            logger.warning("Auto-investigation failed for alert %s", alert.get("signature"), exc_info=True)

    return report
