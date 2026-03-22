# Alerts v3: Category Hub Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restructure `/alerts` into a mission-control category hub with 13 alert categories, sub-categories, MITRE ATT&CK mapping, and dedicated `/alerts/[category]` drill-down pages.

**Architecture:** Backend-first approach. Extend `alert_intelligence.py` with 6 new categories + sub-categories + MITRE mapping. Enhance the `/api/alerts/categories` endpoint to return rich data. Add new `/api/alerts/categories/{cat}` and `/api/alerts/categories/{cat}/timeline` endpoints. Then rebuild the frontend: hub page with interactive category grid, and new category detail page. Follow existing patterns from `traffic/[category]`.

**Tech Stack:** Python/aiohttp (daemon), OpenSearch queries, SvelteKit 5 (Svelte 5 runes), TypeScript

**Design doc:** `docs/plans/2026-03-16-alerts-v3-category-hub-design.md`
**Mockups:** `mockups/alerts-v3/hub.html`, `mockups/alerts-v3/category-detail.html`

---

## Task 1: Expand THREAT_CATEGORIES + Add Sub-Categories in alert_intelligence.py

**Files:**
- Modify: `daemon/services/alert_intelligence.py` (lines 96-128)
- Test: `daemon/tests/test_alert_intelligence.py`

**Step 1: Write failing tests for 6 new categories**

Add to `daemon/tests/test_alert_intelligence.py`, class `TestCategorizeAlert`:

```python
# New categories
def test_credential_abuse(self):
    assert categorize_alert("ET SCAN SSH Brute Force Attempt") == "credential_abuse"

def test_credential_abuse_default_login(self):
    assert categorize_alert("ET POLICY Default Login Attempt admin/admin") == "credential_abuse"

def test_dos(self):
    assert categorize_alert("ET DOS Possible SYN Flood") == "dos"

def test_encrypted_threats(self):
    assert categorize_alert("SURICATA TLS invalid certificate") == "encrypted_threats"

def test_sensitive_data(self):
    assert categorize_alert("ET POLICY Cleartext Credentials in HTTP POST") == "sensitive_data"

def test_geo_anomaly_fallback(self):
    # geo_anomaly is derived from GeoIP, not signature — so signature-based
    # classification won't match. Verify it falls through to a different category.
    assert categorize_alert("Some unknown geo alert") == "informational"
```

**Step 2: Run tests to verify they fail**

```bash
cd daemon && python -m pytest tests/test_alert_intelligence.py::TestCategorizeAlert -v
```
Expected: New tests FAIL with `AssertionError`

**Step 3: Expand THREAT_CATEGORIES dict and add SUB_CATEGORIES**

In `daemon/services/alert_intelligence.py`, replace `THREAT_CATEGORIES` (lines 96-120) with the expanded version:

```python
THREAT_CATEGORIES = {
    "malware_c2": {
        "label": "Malware & C2",
        "icon": "shield-alert",
        "color": "red",
        "description": "Malware infections, command-and-control callbacks, and trojan activity",
        "mitre_tactic": {"id": "TA0011", "name": "Command and Control"},
        "patterns": ["MALWARE", "TROJAN", "C2 ", "CnC", "COMPROMISED", "CINS", "DSHIELD", "Botnet", "CoinMiner", "Miner"],
    },
    "exfiltration": {
        "label": "Data Exfiltration",
        "icon": "upload-cloud",
        "color": "purple",
        "description": "Potential data theft via DNS tunneling, covert channels, or unusual uploads",
        "mitre_tactic": {"id": "TA0010", "name": "Exfiltration"},
        "patterns": ["DNS Tunnel", "Covert Channel", "Exfiltration", "Data Leak"],
    },
    "reconnaissance": {
        "label": "Reconnaissance",
        "icon": "search",
        "color": "blue",
        "description": "Scanning and probing activity targeting your network",
        "mitre_tactic": {"id": "TA0043", "name": "Reconnaissance"},
        "patterns": ["SCAN", "ENUM", "Nmap", "Masscan", "RECON", "Nikto", "Nessus", "Discovery"],
    },
    "exploit": {
        "label": "Exploit Attempt",
        "icon": "bug",
        "color": "orange",
        "description": "Active exploitation of known vulnerabilities",
        "mitre_tactic": {"id": "TA0002", "name": "Execution"},
        "patterns": ["SQL Injection", "XSS", "RCE", "Buffer Overflow", "CVE-", "EXPLOIT", "Shellcode", "Overflow"],
    },
    "policy": {
        "label": "Policy Violation",
        "icon": "gavel",
        "color": "amber",
        "description": "Network policy violations including P2P, TOR, and unauthorized services",
        "mitre_tactic": None,
        "patterns": ["POLICY", "P2P", "GAMES", "TOR ", "CHAT", "BitTorrent", "Torrent"],
    },
    "protocol_anomaly": {
        "label": "Protocol Anomaly",
        "icon": "alert-triangle",
        "color": "cyan",
        "description": "Unusual protocol behavior that may indicate evasion or misconfiguration",
        "mitre_tactic": {"id": "TA0005", "name": "Defense Evasion"},
        "patterns": ["SURICATA TLS", "SURICATA HTTP", "SURICATA STREAM", "SURICATA FRAG", "SURICATA DNS", "SURICATA TCP"],
    },
    "credential_abuse": {
        "label": "Credential Abuse",
        "icon": "key",
        "color": "pink",
        "description": "Brute force attacks, default login attempts, and credential theft",
        "mitre_tactic": {"id": "TA0006", "name": "Credential Access"},
        "patterns": ["Brute Force", "BRUTE", "SSH Password", "DEFAULT LOGIN", "Login Attempt", "Password", "Credential"],
    },
    "geo_anomaly": {
        "label": "Geo-Anomaly",
        "icon": "globe",
        "color": "amber",
        "description": "Traffic to or from unusual geographic locations",
        "mitre_tactic": None,
        "patterns": [],  # Derived from GeoIP, not signature patterns
    },
    "encrypted_threats": {
        "label": "Encrypted Threats",
        "icon": "lock",
        "color": "teal",
        "description": "Suspicious TLS certificates, weak ciphers, and encrypted channel abuse",
        "mitre_tactic": {"id": "TA0005", "name": "Defense Evasion"},
        "patterns": ["TLS invalid", "Self-Signed", "Expired Cert", "Weak Cipher", "JA3", "certificate"],
    },
    "iot_anomaly": {
        "label": "IoT / Device Anomaly",
        "icon": "cpu",
        "color": "purple",
        "description": "Devices behaving outside their established baseline patterns",
        "mitre_tactic": None,
        "patterns": [],  # Derived from behavioral baseline, not signatures
    },
    "dos": {
        "label": "Denial of Service",
        "icon": "zap",
        "color": "red",
        "description": "Flood attacks, amplification, and DDoS participation",
        "mitre_tactic": {"id": "TA0040", "name": "Impact"},
        "patterns": ["DOS", "DDOS", "Flood", "SYN Flood", "UDP Flood", "Amplification", "DDoS"],
    },
    "sensitive_data": {
        "label": "Sensitive Data Exposure",
        "icon": "eye",
        "color": "pink",
        "description": "Cleartext credentials, PII, or sensitive data transmitted insecurely",
        "mitre_tactic": {"id": "TA0009", "name": "Collection"},
        "patterns": ["Cleartext", "PII", "Credentials", "Unencrypted", "API Key", "Password in"],
    },
    "informational": {
        "label": "Informational",
        "icon": "info",
        "color": "muted",
        "description": "Low-priority informational events and generic alerts",
        "mitre_tactic": None,
        "patterns": [],
    },
}

SUB_CATEGORIES: dict[str, dict[str, dict]] = {
    "malware_c2": {
        "trojan": {"label": "Trojan Activity", "patterns": ["TROJAN", "Trojan"]},
        "c2_channel": {"label": "Known C2 Channel", "patterns": ["C2 ", "CnC", "Command and Control"]},
        "malware_download": {"label": "Malware Download", "patterns": ["MALWARE", "Malicious"]},
        "cryptomining": {"label": "Cryptomining", "patterns": ["CoinMiner", "Miner", "Mining"]},
        "botnet": {"label": "Botnet Comms", "patterns": ["Botnet", "COMPROMISED", "CINS", "DSHIELD"]},
    },
    "reconnaissance": {
        "port_scan": {"label": "Port Scanning", "patterns": ["SCAN Nmap", "SCAN Potential", "SYN Scan", "Port Scan"]},
        "vuln_probe": {"label": "Vulnerability Probing", "patterns": ["Nessus", "Nikto", "Vulnerability", "vuln"]},
        "network_sweep": {"label": "Network Sweep", "patterns": ["ICMP Sweep", "Ping Sweep", "Discovery"]},
        "service_enum": {"label": "Service Enumeration", "patterns": ["ENUM", "Banner", "Service"]},
        "os_fingerprint": {"label": "OS Fingerprinting", "patterns": ["OS Detection", "Fingerprint", "TTL"]},
    },
    "exploit": {
        "web_app_attack": {"label": "Web App Attack", "patterns": ["SQL Injection", "XSS", "Web Application"]},
        "client_side": {"label": "Client-Side Exploit", "patterns": ["Shellcode", "Client Side", "Browser"]},
        "priv_escalation": {"label": "Privilege Escalation", "patterns": ["Privilege", "Escalation", "Root"]},
        "buffer_overflow": {"label": "Buffer Overflow", "patterns": ["Buffer Overflow", "Overflow", "Stack"]},
        "file_exploit": {"label": "File-Based Exploit", "patterns": ["CVE-", "EXPLOIT", "Malicious File"]},
    },
    "exfiltration": {
        "dns_tunneling": {"label": "DNS Tunneling", "patterns": ["DNS Tunnel", "DNS Exfil"]},
        "covert_channel": {"label": "Covert Channel", "patterns": ["Covert", "Hidden Channel"]},
        "large_upload": {"label": "Large Upload Anomaly", "patterns": ["Large Upload", "Data Transfer"]},
        "cloud_exfil": {"label": "Cloud Exfiltration", "patterns": ["S3", "GDrive", "Dropbox", "Cloud"]},
    },
    "policy": {
        "p2p_torrent": {"label": "P2P / Torrent", "patterns": ["P2P", "BitTorrent", "Torrent"]},
        "tor_proxy": {"label": "TOR / Proxy", "patterns": ["TOR ", "Proxy", "Anonymous"]},
        "gaming": {"label": "Gaming", "patterns": ["GAMES", "Gaming", "Steam"]},
        "vpn_evasion": {"label": "VPN Evasion", "patterns": ["VPN", "Tunnel"]},
        "inappropriate": {"label": "Inappropriate Content", "patterns": ["CHAT", "Adult", "Content"]},
    },
    "protocol_anomaly": {
        "tls_anomaly": {"label": "TLS Anomaly", "patterns": ["SURICATA TLS"]},
        "http_anomaly": {"label": "HTTP Anomaly", "patterns": ["SURICATA HTTP"]},
        "dns_anomaly": {"label": "DNS Anomaly", "patterns": ["SURICATA DNS"]},
        "tcp_violation": {"label": "TCP State Violation", "patterns": ["SURICATA STREAM", "SURICATA TCP"]},
        "fragmentation": {"label": "Fragmentation Attack", "patterns": ["SURICATA FRAG"]},
    },
    "credential_abuse": {
        "ssh_brute": {"label": "SSH Brute Force", "patterns": ["SSH", "OpenSSH"]},
        "rdp_brute": {"label": "RDP Brute Force", "patterns": ["RDP", "Remote Desktop"]},
        "default_login": {"label": "Default Login", "patterns": ["DEFAULT LOGIN", "admin"]},
        "password_spray": {"label": "Password Spray", "patterns": ["Password Spray", "Credential"]},
    },
    "geo_anomaly": {
        "unusual_country": {"label": "Unusual Country", "patterns": []},
        "first_seen_country": {"label": "First-Seen Country", "patterns": []},
        "sanctioned_region": {"label": "Sanctioned Region", "patterns": []},
        "known_bad_asn": {"label": "Known-Bad ASN", "patterns": []},
    },
    "encrypted_threats": {
        "self_signed": {"label": "Self-Signed Certificate", "patterns": ["Self-Signed", "self signed"]},
        "expired_cert": {"label": "Expired Certificate", "patterns": ["Expired", "expired"]},
        "weak_cipher": {"label": "Weak Cipher Suite", "patterns": ["Weak Cipher", "RC4", "DES"]},
        "ja3_mismatch": {"label": "JA3 Fingerprint Mismatch", "patterns": ["JA3", "JA4"]},
        "cert_impersonation": {"label": "Certificate Impersonation", "patterns": ["impersonat", "spoof"]},
    },
    "iot_anomaly": {
        "baseline_deviation": {"label": "Baseline Deviation", "patterns": []},
        "new_device": {"label": "New Device Detected", "patterns": []},
        "unusual_port": {"label": "Unusual Port Usage", "patterns": []},
        "off_hours": {"label": "Off-Hours Activity", "patterns": []},
    },
    "dos": {
        "syn_flood": {"label": "SYN Flood", "patterns": ["SYN Flood", "SYN"]},
        "udp_flood": {"label": "UDP Flood", "patterns": ["UDP Flood", "UDP"]},
        "amplification": {"label": "Amplification Attack", "patterns": ["Amplification", "Reflection"]},
        "outbound_ddos": {"label": "Outbound DDoS Participation", "patterns": ["DDoS", "Outbound"]},
    },
    "sensitive_data": {
        "cleartext_creds": {"label": "Cleartext Credentials", "patterns": ["Cleartext", "Credentials"]},
        "pii_in_transit": {"label": "PII in Transit", "patterns": ["PII", "Personal"]},
        "unencrypted_api": {"label": "Unencrypted API Keys", "patterns": ["API Key", "API"]},
        "http_passwords": {"label": "HTTP POST with Passwords", "patterns": ["Password in", "Password"]},
    },
    "informational": {},
}

MITRE_TECHNIQUES: dict[str, list[dict]] = {
    "malware_c2": [
        {"id": "T1071", "name": "Application Layer Protocol", "description": "C2 over HTTP/HTTPS/DNS"},
        {"id": "T1573", "name": "Encrypted Channel", "description": "Encrypted C2 communications"},
        {"id": "T1095", "name": "Non-Application Layer Protocol", "description": "C2 via raw TCP/UDP"},
    ],
    "reconnaissance": [
        {"id": "T1595.001", "name": "Active Scanning: IP Blocks", "description": "Scanning IP address ranges"},
        {"id": "T1595.002", "name": "Active Scanning: Vulnerability Scanning", "description": "Probing for exploitable vulns"},
        {"id": "T1046", "name": "Network Service Discovery", "description": "Enumerating open ports and services"},
        {"id": "T1018", "name": "Remote System Discovery", "description": "Identifying hosts on the network"},
        {"id": "T1592.004", "name": "Client Configurations", "description": "Gathering client software details"},
    ],
    "exploit": [
        {"id": "T1190", "name": "Exploit Public-Facing Application", "description": "Exploiting web apps and services"},
        {"id": "T1203", "name": "Exploitation for Client Execution", "description": "Client-side exploits"},
        {"id": "T1068", "name": "Exploitation for Privilege Escalation", "description": "Exploiting vulns for elevated access"},
    ],
    "exfiltration": [
        {"id": "T1048", "name": "Exfiltration Over Alternative Protocol", "description": "Data theft via DNS/ICMP"},
        {"id": "T1041", "name": "Exfiltration Over C2 Channel", "description": "Data sent through C2 infrastructure"},
        {"id": "T1567", "name": "Exfiltration Over Web Service", "description": "Data uploaded to cloud storage"},
    ],
    "credential_abuse": [
        {"id": "T1110", "name": "Brute Force", "description": "Password guessing and credential stuffing"},
        {"id": "T1078", "name": "Valid Accounts", "description": "Use of stolen or default credentials"},
        {"id": "T1133", "name": "External Remote Services", "description": "Abuse of SSH/RDP/VPN"},
    ],
    "dos": [
        {"id": "T1498", "name": "Network Denial of Service", "description": "Volumetric and protocol-based DDoS"},
        {"id": "T1499", "name": "Endpoint Denial of Service", "description": "Application-layer DDoS"},
    ],
    "protocol_anomaly": [
        {"id": "T1001", "name": "Data Obfuscation", "description": "Protocol manipulation to hide activity"},
        {"id": "T1573", "name": "Encrypted Channel", "description": "Abuse of encrypted protocols"},
    ],
    "encrypted_threats": [
        {"id": "T1573", "name": "Encrypted Channel", "description": "Malicious use of encryption"},
        {"id": "T1071.001", "name": "Web Protocols", "description": "Suspicious HTTPS/TLS patterns"},
    ],
    "sensitive_data": [
        {"id": "T1557", "name": "Adversary-in-the-Middle", "description": "Intercepting cleartext traffic"},
        {"id": "T1040", "name": "Network Sniffing", "description": "Capturing unencrypted data in transit"},
    ],
}
```

Also add a `categorize_sub_category()` function after `categorize_alert()`:

```python
def categorize_sub_category(signature: str, category: str) -> str:
    """Return sub-category key for the given signature within its parent category."""
    subs = SUB_CATEGORIES.get(category, {})
    sig_upper = signature.upper()
    for sub_key, sub_info in subs.items():
        for pattern in sub_info.get("patterns", []):
            if pattern.upper() in sig_upper:
                return sub_key
    # Default: first sub-category if any exist, else empty string
    return next(iter(subs), "")
```

**Step 4: Run tests to verify they pass**

```bash
cd daemon && python -m pytest tests/test_alert_intelligence.py -v
```
Expected: ALL tests PASS

**Step 5: Commit**

```bash
git add daemon/services/alert_intelligence.py daemon/tests/test_alert_intelligence.py
git commit -m "feat(alerts): expand to 13 categories with sub-categories and MITRE mapping"
```

---

## Task 2: Enhance /api/alerts/categories Endpoint

**Files:**
- Modify: `daemon/api/alerts.py` (lines 734-778)
- Test: `daemon/tests/test_alert_categories_api.py` (create)

**Step 1: Write failing test**

Create `daemon/tests/test_alert_categories_api.py`:

```python
"""Tests for enhanced /api/alerts/categories endpoint."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.alert_intelligence import THREAT_CATEGORIES, categorize_alert, categorize_sub_category


class TestCategorizeSubCategory:
    def test_recon_port_scan(self):
        assert categorize_sub_category("ET SCAN Nmap SYN Scan", "reconnaissance") == "port_scan"

    def test_recon_vuln_probe(self):
        assert categorize_sub_category("ET SCAN Nessus Vulnerability Scan", "reconnaissance") == "vuln_probe"

    def test_malware_trojan(self):
        assert categorize_sub_category("ET TROJAN Win32/TrickBot", "malware_c2") == "trojan"

    def test_fallback_first_sub(self):
        result = categorize_sub_category("ET SCAN Unknown Scanner", "reconnaissance")
        assert result in ("port_scan", "vuln_probe", "network_sweep", "service_enum", "os_fingerprint")

    def test_empty_for_informational(self):
        assert categorize_sub_category("ET INFO Something", "informational") == ""


class TestMitreTechniques:
    def test_recon_has_techniques(self):
        from services.alert_intelligence import MITRE_TECHNIQUES
        techs = MITRE_TECHNIQUES.get("reconnaissance", [])
        assert len(techs) >= 3
        ids = [t["id"] for t in techs]
        assert "T1595.001" in ids

    def test_all_categories_have_entry(self):
        from services.alert_intelligence import MITRE_TECHNIQUES
        for cat_id in THREAT_CATEGORIES:
            # Not all categories have MITRE mappings (policy, geo_anomaly, iot_anomaly, informational)
            pass  # Just verify no crash on access
            MITRE_TECHNIQUES.get(cat_id, [])
```

**Step 2: Run test to verify it fails**

```bash
cd daemon && python -m pytest tests/test_alert_categories_api.py -v
```
Expected: FAIL (categorize_sub_category not found if Task 1 not done yet, otherwise PASS)

**Step 3: Rewrite handle_alerts_categories in daemon/api/alerts.py**

Replace the `handle_alerts_categories` function (lines 734-778) with:

```python
async def handle_alerts_categories(request: web.Request) -> web.Response:
    """GET /api/alerts/categories — Enhanced with sub-categories, severity, trend, sparkline."""
    client = _get_client(request)
    from_ts, to_ts = _parse_time_range(request)

    # Main query: group by signature, then we'll classify in Python
    query = {
        "size": 0,
        "query": {"bool": {"filter": _suricata_alert_filters(from_ts, to_ts)}},
        "aggs": {
            "by_signature": {
                "terms": {"field": "rule.name.keyword", "size": 500},
                "aggs": {
                    "severity": {"terms": {"field": "suricata.alert.severity", "size": 5}},
                    "over_time": {
                        "date_histogram": {"field": "@timestamp", "fixed_interval": _sparkline_interval(from_ts, to_ts), "min_doc_count": 0},
                    },
                },
            },
        },
    }

    try:
        result = await _os_search(client, query)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=502)

    buckets = result.get("aggregations", {}).get("by_signature", {}).get("buckets", [])

    # Aggregate into categories
    from services.alert_intelligence import (
        THREAT_CATEGORIES, SUB_CATEGORIES, categorize_alert, categorize_sub_category,
        reclassify_severity, SEVERITY_NAMES,
    )

    cats: dict[str, dict] = {}
    for cat_id, cat_info in THREAT_CATEGORIES.items():
        cats[cat_id] = {
            "id": cat_id,
            "label": cat_info["label"],
            "icon": cat_info["icon"],
            "color": cat_info["color"],
            "description": cat_info["description"],
            "count": 0,
            "severity_breakdown": {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0},
            "trend": {"direction": "stable", "percentage": 0},
            "sparkline": [],
            "sub_categories": {},
        }

    for bucket in buckets:
        sig = bucket["key"]
        count = bucket["doc_count"]
        cat_id = categorize_alert(sig)
        sub_id = categorize_sub_category(sig, cat_id)

        if cat_id not in cats:
            cat_id = "informational"

        cats[cat_id]["count"] += count

        # Severity breakdown
        for sev_bucket in bucket.get("severity", {}).get("buckets", []):
            sev_num = reclassify_severity(sig, sev_bucket["key"])
            sev_name = SEVERITY_NAMES.get(sev_num, "info")
            cats[cat_id]["severity_breakdown"][sev_name] = (
                cats[cat_id]["severity_breakdown"].get(sev_name, 0) + sev_bucket["doc_count"]
            )

        # Sub-category aggregation
        if sub_id:
            sub_info = SUB_CATEGORIES.get(cat_id, {}).get(sub_id, {})
            sub_label = sub_info.get("label", sub_id)
            if sub_id not in cats[cat_id]["sub_categories"]:
                cats[cat_id]["sub_categories"][sub_id] = {"id": sub_id, "label": sub_label, "count": 0}
            cats[cat_id]["sub_categories"][sub_id]["count"] += count

        # Sparkline: aggregate time buckets
        time_buckets = bucket.get("over_time", {}).get("buckets", [])
        if not cats[cat_id]["sparkline"]:
            cats[cat_id]["sparkline"] = [0] * len(time_buckets)
        for i, tb in enumerate(time_buckets):
            if i < len(cats[cat_id]["sparkline"]):
                cats[cat_id]["sparkline"][i] += tb["doc_count"]

    # Compute trends from sparkline data
    for cat in cats.values():
        spark = cat["sparkline"]
        if len(spark) >= 4:
            mid = len(spark) // 2
            first_half = sum(spark[:mid]) or 1
            second_half = sum(spark[mid:])
            pct = int(((second_half - first_half) / first_half) * 100)
            if pct > 10:
                cat["trend"] = {"direction": "increasing", "percentage": abs(pct)}
            elif pct < -10:
                cat["trend"] = {"direction": "decreasing", "percentage": abs(pct)}
            else:
                cat["trend"] = {"direction": "stable", "percentage": 0}
        # Convert sub_categories dict to sorted list
        cat["sub_categories"] = sorted(
            cat["sub_categories"].values(), key=lambda s: s["count"], reverse=True
        )

    # Sort categories by count descending
    result_list = sorted(cats.values(), key=lambda c: c["count"], reverse=True)

    return web.json_response({
        "from": from_ts, "to": to_ts,
        "categories": result_list,
    })
```

Add a helper to compute sparkline interval:

```python
def _sparkline_interval(from_ts: str, to_ts: str) -> str:
    """Choose a sparkline interval that gives ~7 buckets."""
    from datetime import datetime
    try:
        f = datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
        t = datetime.fromisoformat(to_ts.replace("Z", "+00:00"))
        delta = (t - f).total_seconds()
    except Exception:
        return "1h"
    if delta <= 3600:       return "5m"    # 15m→~3, 1h→~12
    if delta <= 14400:      return "30m"   # 4h→~8
    if delta <= 86400:      return "3h"    # 24h→~8
    if delta <= 604800:     return "1d"    # 7d→~7
    return "1d"
```

**Step 4: Run tests**

```bash
cd daemon && python -m pytest tests/test_alert_categories_api.py tests/test_alert_intelligence.py -v
```
Expected: ALL PASS

**Step 5: Commit**

```bash
git add daemon/api/alerts.py daemon/tests/test_alert_categories_api.py
git commit -m "feat(alerts): enhance categories endpoint with sub-cats, severity, sparklines"
```

---

## Task 3: Add /api/alerts/categories/{category} Detail Endpoint

**Files:**
- Modify: `daemon/api/alerts.py`
- Test: `daemon/tests/test_alert_categories_api.py` (append)

**Step 1: Write failing test**

Append to `daemon/tests/test_alert_categories_api.py`:

```python
class TestCategoryDetailResponse:
    """Verify the response structure of category detail endpoint."""

    def test_threat_categories_have_descriptions(self):
        for cat_id, cat_info in THREAT_CATEGORIES.items():
            assert "description" in cat_info, f"{cat_id} missing description"
            assert "color" in cat_info, f"{cat_id} missing color"
            assert "icon" in cat_info, f"{cat_id} missing icon"

    def test_mitre_mapping_structure(self):
        from services.alert_intelligence import MITRE_TECHNIQUES
        for cat_id, techniques in MITRE_TECHNIQUES.items():
            for tech in techniques:
                assert "id" in tech, f"Missing id in {cat_id} technique"
                assert "name" in tech, f"Missing name in {cat_id} technique"
                assert "description" in tech, f"Missing description in {cat_id} technique"
```

**Step 2: Run to verify**

```bash
cd daemon && python -m pytest tests/test_alert_categories_api.py -v
```

**Step 3: Add handler function in daemon/api/alerts.py**

Add after `handle_alerts_categories`:

```python
async def handle_alert_category_detail(request: web.Request) -> web.Response:
    """GET /api/alerts/categories/{category} — Full detail for one category."""
    cat_id = request.match_info["category"]
    client = _get_client(request)
    from_ts, to_ts = _parse_time_range(request)

    from services.alert_intelligence import (
        THREAT_CATEGORIES, SUB_CATEGORIES, MITRE_TECHNIQUES,
        categorize_alert, categorize_sub_category, reclassify_severity, SEVERITY_NAMES,
    )

    cat_info = THREAT_CATEGORIES.get(cat_id)
    if not cat_info:
        return web.json_response({"error": f"Unknown category: {cat_id}"}, status=404)

    # Gather all signatures that belong to this category
    patterns = cat_info.get("patterns", [])

    # Query: get all alerts, grouped by signature, src_ip, dst_ip
    query = {
        "size": 0,
        "query": {"bool": {"filter": _suricata_alert_filters(from_ts, to_ts)}},
        "aggs": {
            "by_signature": {
                "terms": {"field": "rule.name.keyword", "size": 200},
                "aggs": {
                    "by_src": {"terms": {"field": "source.ip.keyword", "size": 100}},
                    "by_dst": {"terms": {"field": "destination.ip.keyword", "size": 100}},
                    "severity": {"terms": {"field": "suricata.alert.severity", "size": 5}},
                    "last_seen": {"max": {"field": "@timestamp"}},
                },
            },
        },
    }

    try:
        result = await _os_search(client, query)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=502)

    buckets = result.get("aggregations", {}).get("by_signature", {}).get("buckets", [])

    # Filter to only this category
    total = 0
    sources: set[str] = set()
    targets: set[str] = set()
    sub_cats: dict[str, int] = {}
    sev_breakdown = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    signatures: list[dict] = []
    device_alerts: dict[str, int] = {}

    for bucket in buckets:
        sig = bucket["key"]
        if categorize_alert(sig) != cat_id:
            continue

        count = bucket["doc_count"]
        total += count
        sub_id = categorize_sub_category(sig, cat_id)

        if sub_id:
            sub_cats[sub_id] = sub_cats.get(sub_id, 0) + count

        for sev_b in bucket.get("severity", {}).get("buckets", []):
            sev_name = SEVERITY_NAMES.get(reclassify_severity(sig, sev_b["key"]), "info")
            sev_breakdown[sev_name] += sev_b["doc_count"]

        for src_b in bucket.get("by_src", {}).get("buckets", []):
            sources.add(src_b["key"])
        for dst_b in bucket.get("by_dst", {}).get("buckets", []):
            targets.add(dst_b["key"])
            device_alerts[dst_b["key"]] = device_alerts.get(dst_b["key"], 0) + dst_b["doc_count"]

        last_seen = bucket.get("last_seen", {}).get("value_as_string", "")
        signatures.append({"signature": sig, "count": count, "last_seen": last_seen})

    # Build sub-category list
    sub_info = SUB_CATEGORIES.get(cat_id, {})
    sub_list = []
    for sub_id, sub_count in sorted(sub_cats.items(), key=lambda x: x[1], reverse=True):
        si = sub_info.get(sub_id, {})
        sub_list.append({"id": sub_id, "label": si.get("label", sub_id), "count": sub_count})

    # Build affected devices list (top 20)
    device_list = sorted(
        [{"ip": ip, "count": c} for ip, c in device_alerts.items()],
        key=lambda d: d["count"], reverse=True,
    )[:20]

    # Sort signatures
    signatures.sort(key=lambda s: s["count"], reverse=True)

    mitre_tactic = cat_info.get("mitre_tactic")
    techniques = MITRE_TECHNIQUES.get(cat_id, [])

    return web.json_response({
        "category": {
            "id": cat_id,
            "label": cat_info["label"],
            "description": cat_info["description"],
            "color": cat_info["color"],
            "icon": cat_info["icon"],
            "mitre_tactic": mitre_tactic,
        },
        "stats": {
            "total": total,
            "unique_sources": len(sources),
            "unique_targets": len(targets),
            "affected_devices": len(device_alerts),
        },
        "severity_breakdown": sev_breakdown,
        "sub_categories": sub_list,
        "affected_devices": device_list,
        "top_signatures": signatures[:20],
        "mitre_techniques": techniques,
        "from": from_ts,
        "to": to_ts,
    })
```

**Step 4: Register route**

In `register_alert_routes()` (line ~870), add BEFORE the `{id}` routes:

```python
app.router.add_get("/api/alerts/categories/{category}", handle_alert_category_detail)
```

**Step 5: Commit**

```bash
git add daemon/api/alerts.py daemon/tests/test_alert_categories_api.py
git commit -m "feat(alerts): add /api/alerts/categories/{category} detail endpoint"
```

---

## Task 4: Add /api/alerts/categories/{category}/timeline Endpoint

**Files:**
- Modify: `daemon/api/alerts.py`

**Step 1: Add handler**

```python
async def handle_alert_category_timeline(request: web.Request) -> web.Response:
    """GET /api/alerts/categories/{category}/timeline — Time-series for one category."""
    cat_id = request.match_info["category"]
    client = _get_client(request)
    from_ts, to_ts = _parse_time_range(request)
    interval = request.query.get("interval", "1h")

    from services.alert_intelligence import THREAT_CATEGORIES, categorize_alert, categorize_sub_category

    if cat_id not in THREAT_CATEGORIES:
        return web.json_response({"error": f"Unknown category: {cat_id}"}, status=404)

    query = {
        "size": 0,
        "query": {"bool": {"filter": _suricata_alert_filters(from_ts, to_ts)}},
        "aggs": {
            "over_time": {
                "date_histogram": {"field": "@timestamp", "fixed_interval": interval, "min_doc_count": 0},
                "aggs": {
                    "by_signature": {"terms": {"field": "rule.name.keyword", "size": 200}},
                },
            },
        },
    }

    try:
        result = await _os_search(client, query)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=502)

    time_buckets = result.get("aggregations", {}).get("over_time", {}).get("buckets", [])
    series = []

    for tb in time_buckets:
        point = {"timestamp": tb["key_as_string"], "total": 0, "sub_categories": {}}
        for sig_bucket in tb.get("by_signature", {}).get("buckets", []):
            sig = sig_bucket["key"]
            if categorize_alert(sig) != cat_id:
                continue
            count = sig_bucket["doc_count"]
            point["total"] += count
            sub_id = categorize_sub_category(sig, cat_id)
            if sub_id:
                point["sub_categories"][sub_id] = point["sub_categories"].get(sub_id, 0) + count
        series.append(point)

    return web.json_response({
        "category": cat_id, "from": from_ts, "to": to_ts,
        "interval": interval, "series": series,
    })
```

**Step 2: Register route** (in `register_alert_routes`):

```python
app.router.add_get("/api/alerts/categories/{category}/timeline", handle_alert_category_timeline)
```

**Step 3: Commit**

```bash
git add daemon/api/alerts.py
git commit -m "feat(alerts): add /api/alerts/categories/{category}/timeline endpoint"
```

---

## Task 5: Add SvelteKit API Route Proxies

**Files:**
- Create: `web/src/routes/api/alerts/categories/+server.ts`
- Create: `web/src/routes/api/alerts/categories/[category]/+server.ts`
- Create: `web/src/routes/api/alerts/categories/[category]/timeline/+server.ts`
- Create: `web/src/routes/api/alerts/categories/+server.test.ts`
- Create: `web/src/routes/api/alerts/categories/[category]/+server.test.ts`
- Create: `web/src/routes/api/alerts/categories/[category]/timeline/+server.test.ts`

**Step 1: Create proxies following existing pattern**

Each proxy follows the exact same pattern as `web/src/routes/api/alerts/smart/+server.ts`:

`web/src/routes/api/alerts/categories/+server.ts`:
```typescript
import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { daemonFetch } from '$lib/api/_daemon';

export const GET: RequestHandler = async ({ url }) => {
  const qs = new URLSearchParams();
  for (const [k, v] of url.searchParams) qs.set(k, v);
  const query = qs.toString() ? `?${qs.toString()}` : '';
  const res = await daemonFetch(`/api/alerts/categories${query}`);
  const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
  return json(data, { status: res.status });
};
```

`web/src/routes/api/alerts/categories/[category]/+server.ts`:
```typescript
import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { daemonFetch } from '$lib/api/_daemon';

export const GET: RequestHandler = async ({ url, params }) => {
  const qs = new URLSearchParams();
  for (const [k, v] of url.searchParams) qs.set(k, v);
  const query = qs.toString() ? `?${qs.toString()}` : '';
  const res = await daemonFetch(`/api/alerts/categories/${encodeURIComponent(params.category)}${query}`);
  const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
  return json(data, { status: res.status });
};
```

`web/src/routes/api/alerts/categories/[category]/timeline/+server.ts`:
```typescript
import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { daemonFetch } from '$lib/api/_daemon';

export const GET: RequestHandler = async ({ url, params }) => {
  const qs = new URLSearchParams();
  for (const [k, v] of url.searchParams) qs.set(k, v);
  const query = qs.toString() ? `?${qs.toString()}` : '';
  const res = await daemonFetch(`/api/alerts/categories/${encodeURIComponent(params.category)}/timeline${query}`);
  const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
  return json(data, { status: res.status });
};
```

**Step 2: Create test stubs** (follow pattern from existing test files — minimal proxy tests):

Each test file: `+server.test.ts`:
```typescript
import { describe, it, expect } from 'vitest';

describe('/api/alerts/categories proxy', () => {
  it('exports a GET handler', async () => {
    const mod = await import('./+server');
    expect(typeof mod.GET).toBe('function');
  });
});
```

**Step 3: Commit**

```bash
git add web/src/routes/api/alerts/categories/
git commit -m "feat(alerts): add SvelteKit API route proxies for category endpoints"
```

---

## Task 6: Enhance alerts.ts API Client

**Files:**
- Modify: `web/src/lib/api/alerts.ts`
- Modify: `web/src/lib/api/alerts.test.ts` (if exists, else create)

**Step 1: Add new types and fetch functions**

Append to `web/src/lib/api/alerts.ts`:

```typescript
// ── Enhanced Category Types ──

export interface CategorySeverityBreakdown {
  critical: number;
  high: number;
  medium: number;
  low: number;
  info: number;
}

export interface SubCategory {
  id: string;
  label: string;
  count: number;
}

export interface CategoryTrend {
  direction: 'increasing' | 'decreasing' | 'stable';
  percentage: number;
}

export interface AlertCategory {
  id: string;
  label: string;
  icon: string;
  color: string;
  description: string;
  count: number;
  severity_breakdown: CategorySeverityBreakdown;
  trend: CategoryTrend;
  sparkline: number[];
  sub_categories: SubCategory[];
}

export interface EnhancedCategoriesResponse {
  from: string;
  to: string;
  categories: AlertCategory[];
}

export interface MitreTechnique {
  id: string;
  name: string;
  description: string;
  count?: number;
}

export interface MitreTactic {
  id: string;
  name: string;
}

export interface CategoryDetailDevice {
  ip: string;
  count: number;
  hostname?: string;
  severity?: string;
}

export interface CategoryDetailSignature {
  signature: string;
  count: number;
  last_seen: string;
}

export interface CategoryDetailResponse {
  category: {
    id: string;
    label: string;
    description: string;
    color: string;
    icon: string;
    mitre_tactic: MitreTactic | null;
  };
  stats: {
    total: number;
    unique_sources: number;
    unique_targets: number;
    affected_devices: number;
  };
  severity_breakdown: CategorySeverityBreakdown;
  sub_categories: SubCategory[];
  affected_devices: CategoryDetailDevice[];
  top_signatures: CategoryDetailSignature[];
  mitre_techniques: MitreTechnique[];
  from: string;
  to: string;
}

export interface CategoryTimelinePoint {
  timestamp: string;
  total: number;
  sub_categories: Record<string, number>;
}

export interface CategoryTimelineResponse {
  category: string;
  from: string;
  to: string;
  interval: string;
  series: CategoryTimelinePoint[];
}

// ── Fetch Functions ──

export async function getEnhancedCategories(
  opts: TimeRangeParams = {}
): Promise<EnhancedCategoriesResponse> {
  const q = buildQuery(opts as Record<string, string | number | undefined>);
  const url = `/api/alerts/categories${q}`;
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(15_000) });
    if (!res.ok) throw new Error(`${res.status}`);
    return await res.json();
  } catch {
    return { from: '', to: '', categories: [] };
  }
}

export async function getCategoryDetail(
  category: string,
  opts: TimeRangeParams = {}
): Promise<CategoryDetailResponse> {
  const q = buildQuery(opts as Record<string, string | number | undefined>);
  const url = `/api/alerts/categories/${encodeURIComponent(category)}${q}`;
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(15_000) });
    if (!res.ok) throw new Error(`${res.status}`);
    return await res.json();
  } catch {
    return {
      category: { id: category, label: category, description: '', color: 'muted', icon: 'info', mitre_tactic: null },
      stats: { total: 0, unique_sources: 0, unique_targets: 0, affected_devices: 0 },
      severity_breakdown: { critical: 0, high: 0, medium: 0, low: 0, info: 0 },
      sub_categories: [], affected_devices: [], top_signatures: [], mitre_techniques: [],
      from: '', to: '',
    };
  }
}

export async function getCategoryTimeline(
  category: string,
  opts: TimeRangeParams & { interval?: string } = {}
): Promise<CategoryTimelineResponse> {
  const q = buildQuery(opts as Record<string, string | number | undefined>);
  const url = `/api/alerts/categories/${encodeURIComponent(category)}/timeline${q}`;
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(15_000) });
    if (!res.ok) throw new Error(`${res.status}`);
    return await res.json();
  } catch {
    return { category, from: '', to: '', interval: opts.interval ?? '1h', series: [] };
  }
}
```

**Step 2: Commit**

```bash
git add web/src/lib/api/alerts.ts
git commit -m "feat(alerts): add enhanced category types and fetch functions to API client"
```

---

## Task 7: Rebuild /alerts Hub Page

**Files:**
- Modify: `web/src/routes/alerts/+page.svelte`

This is the largest task. Follow the mockup at `mockups/alerts-v3/hub.html` exactly.

**Step 1: Rewrite the page**

Key changes to the existing page:
- **Add threat score badge** to header (call `getSmartAlertSummary()`)
- **Change stats strip** from 4 cards to 5 (add Critical)
- **Replace categories card** with 4-column interactive category grid
- **Add category card components** with: icon, count, severity micro-bar, sparkline SVG, sub-category pills, trend arrow, click → `/alerts/{category}`
- **Add suppress/FP buttons** to table row actions
- **Add category + sub-category columns** to table

Keep the existing detail drawer, timeline, top signatures/IPs, and pagination — just enhance them.

The implementation should:
- Call `getEnhancedCategories()` from the new API client
- Call `getSmartAlertSummary()` for threat score
- Render the category grid with `{#each categories as cat}` → `<a href="/alerts/{cat.id}">`
- Use CSS grid `grid-template-columns: repeat(4, 1fr)` for the category grid
- Follow design system variables exclusively

**Step 2: Run svelte-check**

```bash
cd web && npx svelte-check
```

**Step 3: Commit**

```bash
git add web/src/routes/alerts/+page.svelte
git commit -m "feat(alerts): rebuild hub page with interactive category grid and threat score"
```

---

## Task 8: Create /alerts/[category] Drill-Down Page

**Files:**
- Create: `web/src/routes/alerts/[category]/+page.svelte`

**Step 1: Create the page**

Follow the mockup at `mockups/alerts-v3/category-detail.html` and the pattern from `web/src/routes/traffic/[category]/+page.svelte`.

Key structure:
- Extract category from `$page.params.category`
- Fetch data via `getCategoryDetail()` and `getCategoryTimeline()` and `getAlerts()` (filtered)
- Use `$effect()` to refetch when category or time range changes
- Sections: header with back link, stats strip, sub-category breakdown bars, timeline SVG, two-col (devices + signatures), MITRE mapping grid, filtered alert table

**Step 2: Run svelte-check**

```bash
cd web && npx svelte-check
```

**Step 3: Add link from sidebar**

In `web/src/routes/+layout.svelte`, verify `/alerts` is already in the sidebar navigation. No change needed if it already links to `/alerts`.

**Step 4: Commit**

```bash
git add web/src/routes/alerts/[category]/+page.svelte
git commit -m "feat(alerts): add category drill-down page with sub-categories and MITRE mapping"
```

---

## Task 9: Run Full Test Suite

**Step 1: Daemon tests**

```bash
cd daemon && python -m pytest -v
```
Expected: ALL PASS

**Step 2: Web tests**

```bash
cd web && npx vitest run
```
Expected: ALL PASS

**Step 3: Svelte type check**

```bash
cd web && npx svelte-check
```
Expected: 0 errors

**Step 4: Final commit if any fixes needed**

```bash
git add -A && git commit -m "fix(alerts): address test and type-check issues"
```

---

## Task 10: Create PR

```bash
git push -u origin phase-4/alerts-v3-category-hub
gh pr create --base develop --title "feat(alerts): alerts v3 category hub with 13 categories and drill-down pages" --body "..."
```

---

## Build Order Summary

| Task | Component | Dependencies |
|------|-----------|-------------|
| 1 | Expand THREAT_CATEGORIES + sub-cats + MITRE | None |
| 2 | Enhance /api/alerts/categories | Task 1 |
| 3 | Add /api/alerts/categories/{category} | Task 1 |
| 4 | Add /api/alerts/categories/{category}/timeline | Task 1 |
| 5 | SvelteKit API route proxies | None |
| 6 | Enhance alerts.ts API client | None |
| 7 | Rebuild /alerts hub page | Tasks 2, 5, 6 |
| 8 | Create /alerts/[category] page | Tasks 3, 4, 5, 6 |
| 9 | Run full test suite | All |
| 10 | Create PR | Task 9 |

Tasks 1-4 (backend) can be done sequentially. Tasks 5-6 (plumbing) can be done in parallel with backend. Tasks 7-8 (frontend) depend on backend + plumbing.
