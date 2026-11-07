"""
NetTap Threat Intelligence Enrichment Service

Cross-references IPs and domains against threat intelligence feeds.
Currently uses a local cache approach — feeds are loaded from disk
or populated by the alert intelligence engine's Suricata data.

Future: scheduled feed downloader.
"""

import ipaddress
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from services.capture_config import write_file_atomic
from storage.all_buckets import all_buckets

logger = logging.getLogger("nettap.services.threat_intel")

_TI_CACHE_PATH = (
    Path(os.environ.get("NETTAP_DATA_DIR", "/tmp")) / "nettap-threat-intel.json"
)
# Held by callers around load_cache .. save_cache (load_cache can write back), so two
# requests, or a request and the address drill-down, never interleave their transactions
CACHE_LOCK = threading.Lock()

# IP pages carry no sub-aggregations: 10x fewer scans than the default, far below max_buckets
_IP_PAGE = 10_000
# Caches without this version learned every alert's destination.ip, so inbound rules taught
# them the network's own addresses (I7); they are dropped at load and rebuilt from alerts.
_CACHE_VERSION = 2


def _is_outside(ip: str) -> bool:
    """An internet address: not LAN, private, CGNAT, link-local, loopback or multicast."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.is_global and not addr.is_multicast


# Known threat intel feed metadata
TI_FEEDS = {
    "abuse_ch_feodo": {"label": "Abuse.ch Feodo (Banking Trojans/C2)", "type": "ip"},
    "abuse_ch_sslbl": {"label": "Abuse.ch SSL Blacklist", "type": "ip"},
    "et_compromised": {"label": "ET Compromised IPs", "type": "ip"},
    "dshield_block": {"label": "DShield Block List", "type": "ip"},
}

# The Suricata rules that fire on a listed host; their alerts feed ALERT_FEED (NET-160 shares
# them with the address page, which checks its own window's alerts)
LISTING_RULES: dict = {
    "bool": {
        "should": [
            {"wildcard": {"rule.name": "*COMPROMISED*"}},
            {"wildcard": {"rule.name": "*DROP*"}},
            {"wildcard": {"rule.name": "*CINS*"}},
            {"wildcard": {"rule.name": "*Dshield*"}},
        ],
        "minimum_should_match": 1,
    }
}
ALERT_FEED = "et_compromised"


def listed_endpoint(src: str | None, dst: str | None) -> str | None:
    """The listed host of a listing-rule alert: its one internet endpoint, or None.

    With no internet endpoint, or two (e.g. an inbound alert to this network's public
    address), the listed one can't be told apart (I7).
    """
    outside = [ip for ip in (src, dst) if ip and _is_outside(ip)]
    return outside[0] if len(outside) == 1 else None


def feed_hit(feed_id: str, ip: str) -> dict:
    """One feed listing `ip`, as lookup_ip reports it."""
    feed_meta = TI_FEEDS.get(feed_id, {"label": feed_id, "type": "ip"})
    return {"feed": feed_id, "label": feed_meta["label"], "indicator": ip, "type": "ip"}


class ThreatIntelService:
    """Manages threat intel IP/domain lookups against cached feed data."""

    def __init__(self):
        self._ip_sets: dict[str, set[str]] = {}
        self._loaded = False
        # The outside addresses the last populate_from_suricata saw in its window (I7)
        self.seen_in_window: set[str] = set()

    # OLD CODE START — I7: loaded every cached address, including LAN and own addresses
    # learned from inbound rules, and an alert to one read as "confirmed malicious infrastructure"
    # def load_cache(self) -> None:
    #     """Load cached threat intel data from disk."""
    #     try:
    #         if _TI_CACHE_PATH.exists():
    #             data = json.loads(_TI_CACHE_PATH.read_text())
    #             for feed_id, ips in data.get("ip_feeds", {}).items():
    #                 self._ip_sets[feed_id] = set(ips)
    #             self._loaded = True
    #             total = sum(len(s) for s in self._ip_sets.values())
    #             logger.info(
    #                 "Loaded %d threat intel indicators from %d feeds",
    #                 total,
    #                 len(self._ip_sets),
    #             )
    #     except Exception:
    #         logger.warning("Failed to load threat intel cache", exc_info=True)
    # OLD CODE END
    def load_cache(self) -> None:
        """Load cached threat intel data from disk, keeping only internet addresses (I7).

        A cache from before _CACHE_VERSION is dropped whole: it can't tell which of its
        addresses were the network's own. Anything purged is written back at once, so an
        old entry is never read again even if the rebuild from alerts then fails.
        """
        try:
            if _TI_CACHE_PATH.exists():
                data = json.loads(_TI_CACHE_PATH.read_text())
                feeds = data.get("ip_feeds", {})
                if data.get("version") != _CACHE_VERSION:
                    feeds = {}
                self._ip_sets = {
                    feed_id: {ip for ip in ips if _is_outside(ip)}
                    for feed_id, ips in feeds.items()
                }
                self._loaded = True
                total = sum(len(s) for s in self._ip_sets.values())
                purged = (
                    sum(len(ips) for ips in data.get("ip_feeds", {}).values()) - total
                )
                if purged:
                    logger.warning(
                        "Dropped %d cached threat intel indicators (not internet addresses, or an old cache)",
                        purged,
                    )
                    self.save_cache()
                logger.info(
                    "Loaded %d threat intel indicators from %d feeds",
                    total,
                    len(self._ip_sets),
                )
        except Exception:
            logger.warning("Failed to load threat intel cache", exc_info=True)

    def save_cache(self) -> None:
        """Save current threat intel data to disk."""
        try:
            _TI_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "version": _CACHE_VERSION,
                "ip_feeds": {k: list(v) for k, v in self._ip_sets.items()},
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            # OLD CODE START — PR 2 (reliability): a reader in another thread could see a half-written file
            # _TI_CACHE_PATH.write_text(json.dumps(data))
            # OLD CODE END
            write_file_atomic(str(_TI_CACHE_PATH), json.dumps(data))
        except Exception:
            logger.error("Failed to save threat intel cache", exc_info=True)

    def add_indicators(self, feed_id: str, ips: list[str]) -> None:
        """Add IPs to a feed's indicator set."""
        if feed_id not in self._ip_sets:
            self._ip_sets[feed_id] = set()
        self._ip_sets[feed_id].update(ips)

    @property
    def indicator_count(self) -> int:
        """Indicators held across every feed."""
        return sum(len(ips) for ips in self._ip_sets.values())

    @property
    def available(self) -> bool:
        """At least one indicator to check against (_loaded only says a cache file was read)."""
        return self.indicator_count > 0

    def lookup_ip(self, ip: str) -> list[dict]:
        """Check IP against all loaded feeds."""
        # OLD CODE START — NET-160: the hit's shape moved to feed_hit, shared with the address page
        # hits = []
        # for feed_id, ip_set in self._ip_sets.items():
        #     if ip in ip_set:
        #         feed_meta = TI_FEEDS.get(feed_id, {"label": feed_id, "type": "ip"})
        #         hits.append(
        #             {
        #                 "feed": feed_id,
        #                 "label": feed_meta["label"],
        #                 "indicator": ip,
        #                 "type": "ip",
        #             }
        #         )
        # return hits
        # OLD CODE END
        return [
            feed_hit(feed_id, ip) for feed_id, ips in self._ip_sets.items() if ip in ips
        ]

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
                dst_hits = [
                    h for h in ti_hits if h["indicator"] == alert.get("destination_ip")
                ]
                if dst_hits:
                    alert["severity"] = max(1, alert["severity"] - 1)
                    alert["severity_label"] = SEVERITY_LABELS.get(
                        alert["severity"], "HIGH"
                    )
                    alert["assessment"] = alert.get("assessment", "") + (
                        f" Destination IP matches {dst_hits[0]['label']} — confirmed malicious infrastructure."
                    )

        return alerts

    def get_all_matches(self, within: set[str] | None = None) -> dict:
        """Return summary of all loaded feeds and their indicator counts; only the
        indicators in `within` (e.g. seen_in_window) when given."""
        return {
            feed_id: {
                "label": TI_FEEDS.get(feed_id, {}).get("label", feed_id),
                "indicator_count": len(ips if within is None else ips & within),
            }
            for feed_id, ips in self._ip_sets.items()
        }

    def populate_from_suricata(
        self, client, from_ts: str, to_ts: str, excluded_ips: list[str] | None = None
    ) -> int:
        """Extract known-bad IPs from Suricata ET COMPROMISED/DROP alerts.

        This bootstraps the TI database from alerts that already fired,
        building a local blocklist from Suricata's own detections.
        ``excluded_ips`` is ignored (kept for callers): excluded IPs stay visible here.
        """
        return self.merge_seen(self.scan_suricata(client, from_ts, to_ts, excluded_ips))

    def scan_suricata(
        self, client, from_ts: str, to_ts: str, excluded_ips: list[str] | None = None
    ) -> set[str]:
        """The listed hosts in the window's listing-rule alerts (the OpenSearch scan).

        Touches no cache, so it runs without CACHE_LOCK (PR 2 review: the scan pages for
        up to 30 s, and the address drill-down waited on the lock all that time).
        """
        import os
        # OLD CODE START — excluded IPs stay visible in threat detections
        # from services.excluded_ips import build_excluded_ips_filter
        # OLD CODE END

        NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

        # OLD CODE START — excluded IPs stay visible in threat detections
        # excluded = build_excluded_ips_filter(excluded_ips or [])
        # OLD CODE END
        bool_clause: dict = {
            "filter": [
                {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts}}},
                {"term": {"event.provider": "suricata"}},
                {"term": {"event.dataset": "alert"}},
                # OLD CODE START — NET-160: the same rules, now LISTING_RULES (shared)
                # {
                #     "bool": {
                #         "should": [
                #             {"wildcard": {"rule.name": "*COMPROMISED*"}},
                #             {"wildcard": {"rule.name": "*DROP*"}},
                #             {"wildcard": {"rule.name": "*CINS*"}},
                #             {"wildcard": {"rule.name": "*Dshield*"}},
                #         ],
                #         "minimum_should_match": 1,
                #     }
                # },
                # OLD CODE END
                LISTING_RULES,
            ]
        }
        # OLD CODE START — excluded IPs stay visible in threat detections
        # if excluded:
        #     bool_clause["must_not"] = excluded
        # OLD CODE END

        # OLD CODE START — #96: only the 500 most-alerted IPs became indicators, and
        # new_indicators counted them all, already known or not
        # query = {
        #     "size": 0,
        #     "query": {"bool": bool_clause},
        #     "aggs": {
        #         "bad_ips": {"terms": {"field": "destination.ip", "size": 500}},
        #     },
        # }
        #
        # try:
        #     result = client.search(index=NETWORK_INDEX, body=query)
        # except Exception:
        #     logger.error("Failed to populate TI from Suricata", exc_info=True)
        #     return 0
        #
        # bad_ips = [
        #     b["key"]
        #     for b in result.get("aggregations", {})
        #     .get("bad_ips", {})
        #     .get("buckets", [])
        # ]
        # if bad_ips:
        #     self.add_indicators("et_compromised", bad_ips)
        #     self.save_cache()
        # return len(bad_ips)
        # OLD CODE END
        # OLD CODE START — #96: 0 read as "no new indicators" when the alerts were never read
        # try:
        #     buckets, complete = all_buckets(...)
        # except Exception:
        #     logger.error("Failed to populate TI from Suricata", exc_info=True)
        #     return 0
        # OLD CODE END
        # OLD CODE START — I7: every alert's destination.ip, so inbound rules (listed host ->
        # this network) taught it the network's own addresses
        # buckets, complete = all_buckets(
        #     client,
        #     NETWORK_INDEX,
        #     {"bool": bool_clause},
        #     [{"ip": {"terms": {"field": "destination.ip"}}}],
        #     page_size=_IP_PAGE,
        # )
        # if not complete:
        #     logger.warning(
        #         "TI scan stopped at %d IPs; indicators are partial", len(buckets)
        #     )
        #
        # known = self._ip_sets.get("et_compromised", set())
        # new_ips = sorted({b["key"]["ip"] for b in buckets} - known)
        # OLD CODE END
        buckets, complete = all_buckets(
            client,
            NETWORK_INDEX,
            {"bool": bool_clause},
            [
                {"src": {"terms": {"field": "source.ip"}}},
                {"dst": {"terms": {"field": "destination.ip"}}},
            ],
            page_size=_IP_PAGE,
        )
        if not complete:
            logger.warning(
                "TI scan stopped at %d address pairs; indicators are partial",
                len(buckets),
            )

        # The listed host is the alert's one internet endpoint; with none or two (e.g. an
        # inbound alert to this network's public address) it can't be told apart, so skip it
        seen: set[str] = set()
        ambiguous = 0
        for b in buckets:
            # OLD CODE START — NET-160: the same rule, now listed_endpoint (shared)
            # outside = [ip for ip in b["key"].values() if ip and _is_outside(ip)]
            # if len(outside) == 1:
            #     seen.add(outside[0])
            # else:
            #     ambiguous += 1
            # OLD CODE END
            listed = listed_endpoint(b["key"].get("src"), b["key"].get("dst"))
            if listed:
                seen.add(listed)
            else:
                ambiguous += 1
        if ambiguous:
            logger.info(
                "TI scan skipped %d alert address pairs without exactly one internet endpoint",
                ambiguous,
            )
        self.seen_in_window = seen
        return seen

    def merge_seen(self, seen: set[str]) -> int:
        """Add the scan's new indicators to the loaded cache and save it; how many were new.

        Callers hold CACHE_LOCK from load_cache through this (milliseconds, no OpenSearch).
        """
        known = self._ip_sets.get(ALERT_FEED, set())
        new_ips = sorted(seen - known)
        if new_ips:
            self.add_indicators(ALERT_FEED, new_ips)
            self.save_cache()
        return len(new_ips)
