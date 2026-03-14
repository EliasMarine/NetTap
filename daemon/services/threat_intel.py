"""
NetTap Threat Intelligence Enrichment Service

Cross-references IPs and domains against threat intelligence feeds.
Currently uses a local cache approach — feeds are loaded from disk
or populated by the alert intelligence engine's Suricata data.

Future: scheduled feed downloader.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("nettap.services.threat_intel")

_TI_CACHE_PATH = Path(os.environ.get("NETTAP_DATA_DIR", "/tmp")) / "nettap-threat-intel.json"

# Known threat intel feed metadata
TI_FEEDS = {
    "abuse_ch_feodo": {"label": "Abuse.ch Feodo (Banking Trojans/C2)", "type": "ip"},
    "abuse_ch_sslbl": {"label": "Abuse.ch SSL Blacklist", "type": "ip"},
    "et_compromised": {"label": "ET Compromised IPs", "type": "ip"},
    "dshield_block": {"label": "DShield Block List", "type": "ip"},
}


class ThreatIntelService:
    """Manages threat intel IP/domain lookups against cached feed data."""

    def __init__(self):
        self._ip_sets: dict[str, set[str]] = {}
        self._loaded = False

    def load_cache(self) -> None:
        """Load cached threat intel data from disk."""
        try:
            if _TI_CACHE_PATH.exists():
                data = json.loads(_TI_CACHE_PATH.read_text())
                for feed_id, ips in data.get("ip_feeds", {}).items():
                    self._ip_sets[feed_id] = set(ips)
                self._loaded = True
                total = sum(len(s) for s in self._ip_sets.values())
                logger.info("Loaded %d threat intel indicators from %d feeds", total, len(self._ip_sets))
        except Exception:
            logger.warning("Failed to load threat intel cache", exc_info=True)

    def save_cache(self) -> None:
        """Save current threat intel data to disk."""
        try:
            _TI_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "ip_feeds": {k: list(v) for k, v in self._ip_sets.items()},
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            _TI_CACHE_PATH.write_text(json.dumps(data))
        except Exception:
            logger.error("Failed to save threat intel cache", exc_info=True)

    def add_indicators(self, feed_id: str, ips: list[str]) -> None:
        """Add IPs to a feed's indicator set."""
        if feed_id not in self._ip_sets:
            self._ip_sets[feed_id] = set()
        self._ip_sets[feed_id].update(ips)

    def lookup_ip(self, ip: str) -> list[dict]:
        """Check IP against all loaded feeds."""
        hits = []
        for feed_id, ip_set in self._ip_sets.items():
            if ip in ip_set:
                feed_meta = TI_FEEDS.get(feed_id, {"label": feed_id, "type": "ip"})
                hits.append({
                    "feed": feed_id,
                    "label": feed_meta["label"],
                    "indicator": ip,
                    "type": "ip",
                })
        return hits

    def enrich_alerts(self, alerts: list[dict]) -> list[dict]:
        """Add threat intel context to alert groups."""
        from services.alert_intelligence import SEVERITY_LABELS

        for alert in alerts:
            ti_hits = []
            ti_hits.extend(self.lookup_ip(alert.get("source_ip", "")))
            ti_hits.extend(self.lookup_ip(alert.get("destination_ip", "")))

            alert["threat_intel"] = ti_hits
            alert["ti_matched"] = len(ti_hits) > 0

            # Boost severity if destination is on a known list
            if ti_hits and alert.get("severity", 5) > 1:
                dst_hits = [h for h in ti_hits if h["indicator"] == alert.get("destination_ip")]
                if dst_hits:
                    alert["severity"] = max(1, alert["severity"] - 1)
                    alert["severity_label"] = SEVERITY_LABELS.get(alert["severity"], "HIGH")
                    alert["assessment"] = alert.get("assessment", "") + (
                        f" Destination IP matches {dst_hits[0]['label']} — confirmed malicious infrastructure."
                    )

        return alerts

    def get_all_matches(self) -> dict:
        """Return summary of all loaded feeds and their indicator counts."""
        return {
            feed_id: {
                "label": TI_FEEDS.get(feed_id, {}).get("label", feed_id),
                "indicator_count": len(ips),
            }
            for feed_id, ips in self._ip_sets.items()
        }

    def populate_from_suricata(self, client, from_ts: str, to_ts: str) -> int:
        """Extract known-bad IPs from Suricata ET COMPROMISED/DROP alerts.

        This bootstraps the TI database from alerts that already fired,
        building a local blocklist from Suricata's own detections.
        """
        import os
        NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

        query = {
            "size": 0,
            "query": {"bool": {"filter": [
                {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
                {"term": {"event.provider": "suricata"}},
                {"term": {"event.dataset": "alert"}},
                {"bool": {"should": [
                    {"wildcard": {"rule.name.keyword": "*COMPROMISED*"}},
                    {"wildcard": {"rule.name.keyword": "*DROP*"}},
                    {"wildcard": {"rule.name.keyword": "*CINS*"}},
                    {"wildcard": {"rule.name.keyword": "*Dshield*"}},
                ], "minimum_should_match": 1}},
            ]}},
            "aggs": {
                "bad_ips": {"terms": {"field": "destination.ip.keyword", "size": 500}},
            },
        }

        try:
            result = client.search(index=NETWORK_INDEX, body=query)
        except Exception:
            logger.error("Failed to populate TI from Suricata", exc_info=True)
            return 0

        bad_ips = [b["key"] for b in result.get("aggregations", {}).get("bad_ips", {}).get("buckets", [])]
        if bad_ips:
            self.add_indicators("et_compromised", bad_ips)
            self.save_cache()
        return len(bad_ips)
