"""
NetTap Auto-Investigation Service

When a critical alert fires, automatically gathers the forensic context
an analyst would need: host profile, connection history, related alerts,
DNS context, and actionable recommendations.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from functools import partial

from services.excluded_ips import CONN_ACCOUNTING
from storage.time_slots import histogram_buckets, time_slots

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
    investigation["sections"]["connection_history"] = _get_pair_history(
        client, src_ip, dst_ip
    )

    # 4. Recommendation
    investigation["recommendation"] = _generate_recommendation(alert)

    return investigation


def _get_host_profile(client, ip: str) -> dict:
    """Get basic host profile from connection data."""
    query = {
        "size": 0,
        # hits.total is shown as a count; without this OpenSearch stops at 10,000
        "track_total_hits": True,
        "query": {
            "bool": {
                "filter": [
                    {"range": {"@timestamp": {"gte": "now-24h"}}},
                    {"term": {"source.ip": ip}},
                    {"term": {"event.provider": "zeek"}},
                    # OLD CODE START — F1: also counted conn_long.log interim records
                    # {"term": {"event.dataset": "conn"}},
                    # OLD CODE END
                    CONN_ACCOUNTING,
                ]
            }
        },
        "aggs": {
            "total_bytes": {"sum": {"field": "source.bytes"}},
            "unique_dests": {"cardinality": {"field": "destination.ip"}},
            "protocols": {"terms": {"field": "network.transport", "size": 5}},
            "top_ports": {"terms": {"field": "destination.port", "size": 5}},
        },
    }

    # OLD CODE START — #96: the page read the missing counts as 0 connections and 0 bytes
    # try:
    #     result = client.search(index=NETWORK_INDEX, body=query)
    # except Exception:
    #     return {"ip": ip, "error": "Query failed"}
    # OLD CODE END
    result = client.search(index=NETWORK_INDEX, body=query)

    aggs = result.get("aggregations", {})
    hits_total = result.get("hits", {}).get("total", {})
    conn_count = (
        hits_total.get("value", 0) if isinstance(hits_total, dict) else hits_total
    )

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
    now = datetime.now(timezone.utc)
    query = {
        "size": 0,
        # hits.total is shown as a count; without this OpenSearch stops at 10,000
        "track_total_hits": True,
        "query": {
            "bool": {
                "filter": [
                    {"range": {"@timestamp": {"gte": "now-7d"}}},
                    {"term": {"source.ip": src_ip}},
                    {"term": {"destination.ip": dst_ip}},
                    {"term": {"event.provider": "zeek"}},
                    # OLD CODE START — F1: also counted conn_long.log interim records
                    # {"term": {"event.dataset": "conn"}},
                    # OLD CODE END
                    CONN_ACCOUNTING,
                ]
            }
        },
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
            # OLD CODE START — #120: OpenSearch 3.5's skip-list date_histogram misplaces records
            # "by_day": {
            #     "date_histogram": {"field": "@timestamp", "calendar_interval": "day", "min_doc_count": 0},
            # },
            # OLD CODE END
            "by_day": time_slots(
                now - timedelta(days=7), now, "1d"
            ),  # the query's now-7d, UTC days
        },
    }

    # OLD CODE START — #96: the page read the missing history as no connections
    # try:
    #     result = client.search(index=NETWORK_INDEX, body=query)
    # except Exception:
    #     return {"error": "Query failed"}
    # OLD CODE END
    result = client.search(index=NETWORK_INDEX, body=query)

    aggs = result.get("aggregations", {})
    hits_total = result.get("hits", {}).get("total", {})
    total_conns = (
        hits_total.get("value", 0) if isinstance(hits_total, dict) else hits_total
    )

    daily = [
        {"date": b.get("key_as_string", ""), "count": b["doc_count"]}
        for b in histogram_buckets(aggs.get("by_day"))  # date_histogram before #120
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


# OLD CODE START — NET-228 (audit B-j, HON-15, ALR-6): "IMMEDIATE: Isolate the source host" for every
# severity-1 group, though for an inbound attempt the source is the internet attacker, and a match
# is not proof of compromise
# def _generate_recommendation(alert: dict) -> str:
#     """Generate specific action recommendation."""
#     parts = []
#     sev = alert.get("severity", 4)
#     cat = alert.get("category", "")
#
#     if sev <= 1:
#         parts.append("IMMEDIATE: Isolate the source host from the network.")
#     elif sev <= 2:
#         parts.append("HIGH PRIORITY: Investigate this alert within the next hour.")
#
#     if cat == "malware_c2":
#         parts.append(
#             "Check for malware on the source device. Scan with endpoint security tools."
#         )
#     elif cat == "exfiltration":
#         parts.append("Check for data exfiltration — review large outbound transfers.")
#     elif cat == "reconnaissance":
#         parts.append(
#             "Determine if this is authorized scanning (pentest, vulnerability scan)."
#         )
#
#     ti = alert.get("threat_intel", [])
#     if ti:
#         parts.append(
#             f"Destination matches {ti[0].get('label', 'threat intel')} — block at firewall."
#         )
#
#     if not parts:
#         parts.append("Review the connection history and related alerts for patterns.")
#
#     return " ".join(parts)
# OLD CODE END
def _generate_recommendation(alert: dict) -> str:
    """What to check for a smart-alert group: what a match can mean, then where to start.

    Names the group's LAN devices without saying who opened the connection: `own` is not proof of
    that (a LAN device's reply to an internet-opened connection counts as its own traffic).
    """
    parts = []
    sev = alert.get("severity", 4)
    cat = alert.get("category", "")

    if sev <= 1:
        parts.append(
            "Check this first: a critical-severity rule matched. A match is evidence to "
            "check, not proof of compromise."
        )
    elif sev <= 2:
        parts.append("Check this soon: a high-severity rule matched.")

    devices = sorted(
        {f["device"] for f in alert.get("findings") or [] if f.get("device")}
    )
    if devices:
        parts.append(f"These matches involve {', '.join(devices)}: start there.")

    if cat == "malware_c2":
        parts.append("Check the device with up-to-date security software for malware.")
    elif cat == "exfiltration":
        parts.append("Review large outbound transfers in the connection history.")
    elif cat == "reconnaissance":
        parts.append(
            "Check whether this is scanning you authorised (a vulnerability scan or a pentest)."
        )

    ti = alert.get("threat_intel", [])
    if ti:
        parts.append(
            f"The destination is on {ti[0].get('label', 'a threat list')}: consider "
            "blocking it at your firewall."
        )

    if not parts:
        parts.append("Review the connection history and related alerts for patterns.")

    return " ".join(parts)


async def generate_threat_report(
    client,
    from_ts: str,
    to_ts: str,
    excluded_ips: list[str] | None = None,
    beaconing: list[dict] | None = None,
    lan_cidrs: list[str] | None = None,
) -> dict:
    """Unified threat report — the single API call that powers the /threats page.

    ``beaconing``: rows from the background snapshot (NET-192 PR 3); the beaconing check then
    doesn't run here. None runs it live, as before.
    """
    from services.alert_intelligence import (
        get_smart_alerts,
        get_smart_alert_summary,
        # OLD CODE START — #96: kill chains now come from the summary (every group)
        # detect_kill_chains,
        # OLD CODE END
    )
    from services.threat_detection import (
        detect_beaconing,
        detect_lateral_movement,
        analyze_dns_anomalies,
    )

    # OLD CODE START — investigation reports must not hide alerts for excluded IPs
    # from services.excluded_ips import build_excluded_ips_filter
    #
    # excluded = build_excluded_ips_filter(excluded_ips or [])
    #
    # summary = await get_smart_alert_summary(
    #     client, from_ts, to_ts, excluded_ips=excluded
    # )
    # alerts = await get_smart_alerts(
    #     client, from_ts, to_ts, include_info=False, limit=200, excluded_ips=excluded
    # )
    # OLD CODE END
    # #139: the three checks block on OpenSearch and don't depend on each other or on the
    # alerts: run them side by side in threads, so the report waits for the slowest one only
    loop = asyncio.get_running_loop()
    # OLD CODE START — NET-192 PR 3: beaconing may come from the background snapshot
    # running = {
    #     name: loop.run_in_executor(
    #         None, partial(detect, client, from_ts, to_ts, excluded_ips=excluded_ips)
    #     )
    #     for name, detect in (
    #         ("beaconing", detect_beaconing),
    #         ("dns_anomalies", analyze_dns_anomalies),
    #         ("lateral_movement", detect_lateral_movement),
    #     )
    # }
    # OLD CODE END
    running = {
        name: loop.run_in_executor(
            None, partial(detect, client, from_ts, to_ts, excluded_ips=excluded_ips)
        )
        for name, detect in (
            ("beaconing", detect_beaconing),
            ("dns_anomalies", analyze_dns_anomalies),
            ("lateral_movement", detect_lateral_movement),
        )
        if not (name == "beaconing" and beaconing is not None)
    }
    try:
        # OLD CODE START — NET-209: the LAN rule decides which device each alert concerns
        # summary = get_smart_alert_summary(client, from_ts, to_ts)
        # alerts = get_smart_alerts(client, from_ts, to_ts, include_info=False, limit=200)
        # OLD CODE END
        summary = get_smart_alert_summary(client, from_ts, to_ts, lan_cidrs=lan_cidrs)
        alerts = get_smart_alerts(
            client, from_ts, to_ts, include_info=False, limit=200, lan_cidrs=lan_cidrs
        )
    except BaseException:
        await asyncio.gather(*running.values(), return_exceptions=True)
        raise

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period": {"from": from_ts, "to": to_ts},
        "summary": summary,
        # OLD CODE START — #96: chains from the top 200 groups disagreed with summary.kill_chains
        # "kill_chains": detect_kill_chains(alerts),
        # OLD CODE END
        "kill_chains": summary.get("kill_chains", []),
        # OLD CODE START — #96: a failed detector returned [], shown as "No ... detected"
        # "beaconing": detect_beaconing(client, from_ts, to_ts, excluded_ips=excluded_ips),
        # "dns_anomalies": analyze_dns_anomalies(client, from_ts, to_ts, excluded_ips=excluded_ips),
        # "lateral_movement": detect_lateral_movement(client, from_ts, to_ts, excluded_ips=excluded_ips),
        # OLD CODE END
        # OLD CODE START — NET-192 PR 3: or the background snapshot's rows
        # "beaconing": [],
        # OLD CODE END
        "beaconing": beaconing if beaconing is not None else [],
        "dns_anomalies": {
            "dga_suspects": [],
            "tunnel_suspects": [],
            "nxdomain_spikes": [],
            "suspicious_tlds": [],
        },
        "lateral_movement": [],
        # checks that could not run, and checks a bucket cap stopped part way
        "failed_checks": [],
        "incomplete_checks": [],
        "investigations": [],
    }
    # OLD CODE START — #139: each check ran after the previous one, on the request loop
    # for name, detect in (
    #     ("beaconing", detect_beaconing),
    #     ("dns_anomalies", analyze_dns_anomalies),
    #     ("lateral_movement", detect_lateral_movement),
    # ):
    #     try:
    #         found = detect(client, from_ts, to_ts, excluded_ips=excluded_ips)
    #     except Exception:
    #         logger.error("Threat report: the %s check failed", name, exc_info=True)
    #         report["failed_checks"] = [*report["failed_checks"], name]
    #         continue
    #     if isinstance(found, dict):  # DNS anomalies: findings plus "complete"
    #         complete = found.get("complete", True)
    #         found = {k: v for k, v in found.items() if k != "complete"}
    #     else:
    #         found, complete = found
    #     report[name] = found
    #     if not complete:
    #         report["incomplete_checks"] = [*report["incomplete_checks"], name]
    # OLD CODE END

    # Auto-investigate top critical alerts (cap at 3)
    critical = [a for a in alerts if a.get("severity", 5) <= 2]
    for alert in critical[:3]:
        try:
            inv = await auto_investigate(client, alert)
            report["investigations"].append(inv)
        # OLD CODE START — #96: a failed investigation just left the list shorter
        # except Exception:
        #     logger.warning("Auto-investigation failed for alert %s", alert.get("signature"), exc_info=True)
        # OLD CODE END
        except Exception:
            logger.warning(
                "Auto-investigation failed for alert %s",
                alert.get("signature"),
                exc_info=True,
            )
            if "investigations" not in report["failed_checks"]:
                report["failed_checks"] = [*report["failed_checks"], "investigations"]

    for name, check in running.items():
        try:
            found = await check
        except Exception:
            logger.error("Threat report: the %s check failed", name, exc_info=True)
            report["failed_checks"] = [*report["failed_checks"], name]
            continue
        if isinstance(found, dict):  # DNS anomalies: findings plus "complete"
            complete = found.get("complete", True)
            found = {k: v for k, v in found.items() if k != "complete"}
        else:
            found, complete = found
        report[name] = found
        if not complete:
            report["incomplete_checks"] = [*report["incomplete_checks"], name]

    return report
