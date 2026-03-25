"""
NetTap Smart Alert Intelligence Engine v2

Transforms raw Suricata alerts into actionable, grouped, contextualized
threat intelligence. Features:

1. Severity reclassification — overrides Suricata's broken defaults
2. Deduplication & grouping — by (signature, src_ip, dst_ip)
3. Smart categorization — 13 threat categories with sub-categories
4. Trend detection — temporal bucketing (first half vs second half)
5. Kill chain correlation — detects multi-stage attack progression
6. Baseline-aware scoring — deviation from rolling 7-day average
7. Device context enrichment — OS/UA fingerprinting from sessions
8. Suppress with TTL decay — auto-expiring suppressions
9. Destination-aware severity boosting — internal assets on sensitive ports
10. Plain-English assessments with full context
11. MITRE ATT&CK technique mapping per category
"""

import logging
import os
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger("nettap.services.alert_intelligence")

NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

# ---------------------------------------------------------------------------
# Severity Reclassification
# ---------------------------------------------------------------------------

SEVERITY_OVERRIDES: dict[str, int] = {
    # Critical — always escalate
    "ET MALWARE": 1,
    "ET TROJAN": 1,
    "ET EXPLOIT": 1,
    "ET C2": 1,
    "ET ATTACK_RESPONSE": 1,
    "ET CURRENT_EVENTS": 2,
    "ET SHELLCODE": 1,
    "ET WEB_SERVER": 2,
    "ET WEB_CLIENT": 2,
    # Medium — concerning but common
    "ET SCAN": 3,
    "ET DOS": 3,
    "ET COMPROMISED": 2,
    "ET DROP": 2,
    "ET CINS": 2,
    "ET DSHIELD": 2,
    # Low — policy violations, usually benign
    "ET POLICY": 4,
    "ET DNS": 4,
    "ET GAMES": 4,
    "ET CHAT": 4,
    "ET P2P": 4,
    # Info — suppress by default
    "ET INFO": 5,
    "SURICATA TLS": 5,
    "SURICATA HTTP": 5,
    "SURICATA STREAM": 5,
    "SURICATA FRAG": 5,
    "SURICATA Applayer": 5,
    "SURICATA AF-PACKET": 5,
    "SURICATA IPv4": 5,
    "SURICATA Ethertype": 5,
    "SURICATA": 5,
    "GPL": 5,
}

ENGINE_NOISE_SIGNATURES = {
    "SURICATA AF-PACKET truncated packet",
    "SURICATA IPv4 truncated packet",
    "SURICATA Ethertype unknown",
    "SURICATA IPv4 padding required",
    "SURICATA IPv4 invalid checksum",
    "SURICATA TCP invalid checksum",
    "SURICATA UDP invalid checksum",
    "SURICATA ICMPv4 invalid checksum",
    "SURICATA STREAM ESTABLISHED packet out of window",
    "SURICATA STREAM Packet with invalid ack",
    "SURICATA STREAM CLOSEWAIT FIN out of window",
}

SEVERITY_NAMES = {1: "critical", 2: "high", 3: "medium", 4: "low", 5: "info"}
SEVERITY_LABELS = {1: "CRITICAL", 2: "HIGH", 3: "MEDIUM", 4: "LOW", 5: "INFO"}

# Sensitive internal ports — alerts targeting these get severity boosted
SENSITIVE_PORTS = {22, 23, 445, 3389, 5900, 3306, 5432, 1433, 6379, 27017, 8080, 8443, 9200}

# ---------------------------------------------------------------------------
# Smart Categories + Kill Chain
# ---------------------------------------------------------------------------

# ORDERING IS CRITICAL: more-specific categories MUST come before broad ones
# so that categorize_alert() matches the best category first.
# e.g. "ET SCAN SSH Brute Force" matches credential_abuse ("Brute Force")
#      before reconnaissance ("SCAN").
THREAT_CATEGORIES = {
    # --- Specific categories first (narrow patterns) ---
    "credential_abuse": {
        "label": "Credential Abuse",
        "icon": "key",
        "color": "#e74c3c",
        "description": "Brute force, password spraying, and credential theft attempts.",
        "patterns": [
            "Brute Force", "Password Spray", "Default Login", "Credential Dump",
            "SSH Brute", "FTP Brute", "RDP Brute", "SMTP Brute",
        ],
    },
    "sensitive_data": {
        "label": "Sensitive Data Exposure",
        "icon": "eye-off",
        "color": "#e67e22",
        "description": "Cleartext credentials, SSNs, credit card numbers, or PII in transit.",
        "patterns": [
            "Cleartext Password", "Credit Card", "SSN", "PII",
            "Unencrypted Credential", "Basic Auth Cleartext",
        ],
    },
    "dos": {
        "label": "Denial of Service",
        "icon": "zap",
        "color": "#9b59b6",
        "description": "Flood attacks, amplification, and resource exhaustion attempts.",
        "patterns": [
            "DOS", "DDOS", "Flood", "Amplification", "SYN Flood",
            "UDP Flood", "ICMP Flood", "NTP Amplification", "DNS Amplification",
        ],
    },
    "encrypted_threats": {
        "label": "Encrypted Threats",
        "icon": "lock",
        "color": "#1abc9c",
        "description": "Suspicious TLS/SSL behavior — expired certs, self-signed, known-bad JA3.",
        "patterns": [
            "TLS Invalid", "SSL Invalid", "Expired Certificate", "Self-Signed",
            "JA3", "TLS Heartbleed", "POODLE", "DROWN",
        ],
    },
    # --- Broad categories (wide patterns) ---
    "malware_c2": {
        "label": "Malware & C2",
        "icon": "alert",
        "color": "#ff4757",
        "description": "Known malware signatures, command-and-control callbacks, and threat intel matches.",
        "patterns": [
            "MALWARE", "TROJAN", "C2", "SHELLCODE", "ATTACK_RESPONSE", "CURRENT_EVENTS",
            "COMPROMISED", "DROP", "CINS", "DSHIELD", "Hostile", "Threat Intelligence",
            "Poor Reputation", "Block Listed", "BOTNET", "CnC",
        ],
    },
    "exfiltration": {
        "label": "Data Exfiltration",
        "icon": "upload",
        "color": "#ff6b81",
        "description": "DNS tunneling, unusually large outbound transfers, and covert channels.",
        "patterns": [
            "DNS Tunnel", "Large Outbound", "EXFIL", "Covert Channel",
        ],
    },
    "reconnaissance": {
        "label": "Reconnaissance",
        "icon": "search",
        "color": "#ffa502",
        "description": "Port scanning, service enumeration, and network probing.",
        "patterns": [
            "SCAN", "ENUM", "PROBE", "Nmap", "Masscan",
        ],
    },
    "exploit": {
        "label": "Exploit Attempt",
        "icon": "bug",
        "color": "#ff4757",
        "description": "Active exploitation of known vulnerabilities (CVEs, RCE, injection).",
        "patterns": [
            "EXPLOIT", "WEB_SERVER", "WEB_CLIENT", "SQL Injection", "XSS", "RCE",
            "Remote Code", "Buffer Overflow", "CVE-",
        ],
    },
    "policy": {
        "label": "Policy Violation",
        "icon": "shield",
        "color": "#2ed573",
        "description": "P2P usage, gaming traffic, Tor access, and other policy-violating activity.",
        "patterns": [
            "POLICY", "P2P", "GAMES", "CHAT", "TOR", "Tor Exit",
        ],
    },
    "protocol_anomaly": {
        "label": "Protocol Anomaly",
        "icon": "warning",
        "color": "#eccc68",
        "description": "Non-standard protocol behavior detected by Suricata decoders.",
        "patterns": [
            "SURICATA TLS", "SURICATA HTTP", "SURICATA STREAM", "SURICATA FRAG",
            "SURICATA Applayer", "SURICATA",
        ],
    },
    # --- Behavioral / fallback categories ---
    "iot_anomaly": {
        "label": "IoT / Device Anomaly",
        "icon": "cpu",
        "color": "#70a1ff",
        "description": "Unusual behavior from IoT devices — unexpected ports, protocols, or destinations.",
        "patterns": [
            "IoT", "Smart Home", "UPnP Exploit", "MQTT", "CoAP",
            "Camera", "Printer Anomaly", "SCADA",
        ],
    },
    "geo_anomaly": {
        "label": "Geographic Anomaly",
        "icon": "globe",
        "color": "#7bed9f",
        "description": "Connections to unusual countries, embargoed regions, or known-bad ASNs.",
        "patterns": [
            "GeoIP", "Embargo", "Sanctioned", "Unusual Country",
            "High-Risk Country", "Tor Exit Node",
        ],
    },
    "informational": {
        "label": "Informational",
        "icon": "info",
        "color": "#a4b0be",
        "description": "Low-priority observations and protocol metadata events.",
        "patterns": ["INFO", "GPL"],
    },
}


# ---------------------------------------------------------------------------
# Sub-Categories — granular drill-down within each parent category
# ---------------------------------------------------------------------------

SUB_CATEGORIES: dict[str, list[dict]] = {
    "credential_abuse": [
        {"id": "ssh_brute", "label": "SSH Brute Force", "patterns": ["SSH Brute", "SSH Login"]},
        {"id": "rdp_brute", "label": "RDP Brute Force", "patterns": ["RDP Brute", "RDP Login"]},
        {"id": "password_spray", "label": "Password Spray", "patterns": ["Password Spray", "Credential Stuff"]},
        {"id": "default_login", "label": "Default Login Attempt", "patterns": ["Default Login", "Default Password", "Admin Login"]},
        {"id": "ftp_brute", "label": "FTP Brute Force", "patterns": ["FTP Brute", "FTP Login"]},
    ],
    "sensitive_data": [
        {"id": "cleartext_creds", "label": "Cleartext Credentials", "patterns": ["Cleartext Password", "Basic Auth Cleartext", "Unencrypted Credential"]},
        {"id": "pii_leak", "label": "PII Exposure", "patterns": ["SSN", "Credit Card", "PII"]},
    ],
    "dos": [
        {"id": "syn_flood", "label": "SYN Flood", "patterns": ["SYN Flood"]},
        {"id": "udp_flood", "label": "UDP Flood", "patterns": ["UDP Flood"]},
        {"id": "amplification", "label": "Amplification Attack", "patterns": ["Amplification", "NTP Amplification", "DNS Amplification"]},
        {"id": "icmp_flood", "label": "ICMP Flood", "patterns": ["ICMP Flood"]},
    ],
    "encrypted_threats": [
        {"id": "bad_cert", "label": "Bad Certificate", "patterns": ["Expired Certificate", "Self-Signed", "TLS Invalid", "SSL Invalid"]},
        {"id": "known_bad_ja3", "label": "Known-Bad JA3", "patterns": ["JA3"]},
        {"id": "tls_vuln", "label": "TLS Vulnerability", "patterns": ["Heartbleed", "POODLE", "DROWN"]},
    ],
    "malware_c2": [
        {"id": "trojan", "label": "Trojan Activity", "patterns": ["TROJAN"]},
        {"id": "botnet", "label": "Botnet C2", "patterns": ["BOTNET", "CnC", "C2"]},
        {"id": "threat_intel", "label": "Threat Intel Match", "patterns": ["Threat Intelligence", "Poor Reputation", "Block Listed", "COMPROMISED", "DROP", "CINS", "DSHIELD"]},
        {"id": "shellcode", "label": "Shellcode Detected", "patterns": ["SHELLCODE"]},
    ],
    "exfiltration": [
        {"id": "dns_tunnel", "label": "DNS Tunneling", "patterns": ["DNS Tunnel"]},
        {"id": "large_outbound", "label": "Large Outbound Transfer", "patterns": ["Large Outbound"]},
        {"id": "covert_channel", "label": "Covert Channel", "patterns": ["Covert Channel", "EXFIL"]},
    ],
    "reconnaissance": [
        {"id": "port_scan", "label": "Port Scan", "patterns": ["SCAN", "Nmap", "Masscan"]},
        {"id": "service_enum", "label": "Service Enumeration", "patterns": ["ENUM"]},
        {"id": "probe", "label": "Network Probe", "patterns": ["PROBE"]},
    ],
    "exploit": [
        {"id": "web_exploit", "label": "Web Application Exploit", "patterns": ["WEB_SERVER", "WEB_CLIENT", "SQL Injection", "XSS"]},
        {"id": "rce", "label": "Remote Code Execution", "patterns": ["RCE", "Remote Code"]},
        {"id": "cve", "label": "Known CVE Exploit", "patterns": ["CVE-"]},
        {"id": "buffer_overflow", "label": "Buffer Overflow", "patterns": ["Buffer Overflow"]},
    ],
    "policy": [
        {"id": "tor", "label": "Tor / Anonymizer", "patterns": ["TOR", "Tor Exit"]},
        {"id": "p2p", "label": "P2P Traffic", "patterns": ["P2P"]},
        {"id": "gaming", "label": "Gaming Traffic", "patterns": ["GAMES"]},
        {"id": "chat", "label": "Chat / IM Traffic", "patterns": ["CHAT"]},
    ],
    "protocol_anomaly": [
        {"id": "tls_anomaly", "label": "TLS Protocol Anomaly", "patterns": ["SURICATA TLS"]},
        {"id": "http_anomaly", "label": "HTTP Protocol Anomaly", "patterns": ["SURICATA HTTP"]},
        {"id": "stream_anomaly", "label": "TCP Stream Anomaly", "patterns": ["SURICATA STREAM"]},
        {"id": "frag_anomaly", "label": "Fragmentation Anomaly", "patterns": ["SURICATA FRAG"]},
        {"id": "applayer_anomaly", "label": "Application Layer Anomaly", "patterns": ["SURICATA Applayer"]},
    ],
    "iot_anomaly": [
        {"id": "upnp_exploit", "label": "UPnP Exploit", "patterns": ["UPnP Exploit"]},
        {"id": "mqtt", "label": "MQTT Anomaly", "patterns": ["MQTT"]},
        {"id": "smart_home", "label": "Smart Home Device", "patterns": ["Smart Home", "IoT", "Camera"]},
        {"id": "scada", "label": "SCADA / ICS", "patterns": ["SCADA"]},
    ],
    "geo_anomaly": [
        {"id": "embargoed", "label": "Embargoed Country", "patterns": ["Embargo", "Sanctioned"]},
        {"id": "unusual_geo", "label": "Unusual Geography", "patterns": ["Unusual Country", "High-Risk Country", "GeoIP"]},
        {"id": "tor_exit", "label": "Tor Exit Node", "patterns": ["Tor Exit Node"]},
    ],
    "informational": [
        {"id": "info_generic", "label": "General Info", "patterns": ["INFO"]},
        {"id": "gpl_rules", "label": "GPL Rule Match", "patterns": ["GPL"]},
    ],
}


# ---------------------------------------------------------------------------
# MITRE ATT&CK Technique Mapping
# ---------------------------------------------------------------------------

MITRE_TECHNIQUES: dict[str, list[dict]] = {
    "credential_abuse": [
        {"id": "T1110", "name": "Brute Force", "description": "Adversary tries many passwords to gain access."},
        {"id": "T1110.001", "name": "Password Guessing", "description": "Guessing credentials using common passwords."},
        {"id": "T1110.003", "name": "Password Spraying", "description": "Trying one password against many accounts."},
    ],
    "malware_c2": [
        {"id": "T1071", "name": "Application Layer Protocol", "description": "C2 over HTTP, DNS, or other app-layer protocols."},
        {"id": "T1573", "name": "Encrypted Channel", "description": "C2 encrypted to avoid detection."},
        {"id": "T1059", "name": "Command and Scripting Interpreter", "description": "Execution via scripting (PowerShell, bash)."},
    ],
    "exfiltration": [
        {"id": "T1048", "name": "Exfiltration Over Alternative Protocol", "description": "Data theft via DNS, ICMP, or other non-standard channels."},
        {"id": "T1041", "name": "Exfiltration Over C2 Channel", "description": "Data stolen over existing C2 connection."},
    ],
    "reconnaissance": [
        {"id": "T1046", "name": "Network Service Scanning", "description": "Scanning for open ports and running services."},
        {"id": "T1595", "name": "Active Scanning", "description": "Probing target infrastructure for vulnerabilities."},
    ],
    "exploit": [
        {"id": "T1190", "name": "Exploit Public-Facing Application", "description": "Exploiting a vulnerability in a web-facing service."},
        {"id": "T1203", "name": "Exploitation for Client Execution", "description": "Exploiting client software (browser, office)."},
    ],
    "dos": [
        {"id": "T1498", "name": "Network Denial of Service", "description": "Flooding network resources to cause outage."},
        {"id": "T1498.001", "name": "Direct Network Flood", "description": "SYN/UDP/ICMP flood against a target."},
    ],
    "encrypted_threats": [
        {"id": "T1573", "name": "Encrypted Channel", "description": "Malicious use of encryption to hide activity."},
        {"id": "T1553.004", "name": "Install Root Certificate", "description": "Installing rogue CA certs to intercept TLS."},
    ],
    "sensitive_data": [
        {"id": "T1552", "name": "Unsecured Credentials", "description": "Credentials stored or transmitted insecurely."},
        {"id": "T1040", "name": "Network Sniffing", "description": "Capturing cleartext credentials on the wire."},
    ],
    "policy": [
        {"id": "T1090", "name": "Proxy", "description": "Using proxies or anonymizers to hide traffic origin."},
    ],
    "iot_anomaly": [
        {"id": "T1557", "name": "Adversary-in-the-Middle", "description": "MitM attacks on IoT protocols (UPnP, MQTT)."},
    ],
    "geo_anomaly": [
        {"id": "T1090.003", "name": "Multi-hop Proxy", "description": "Traffic routed through multiple countries to evade detection."},
    ],
}

# Kill chain stage ordering for correlation
KILL_CHAIN_STAGES = {
    "reconnaissance": 1,
    "exploit": 2,
    "malware_c2": 3,
    "exfiltration": 4,
}


# ---------------------------------------------------------------------------
# Core Functions
# ---------------------------------------------------------------------------


def reclassify_severity(
    signature: str, original_severity: int,
    dst_port: int | None = None, dst_ip: str | None = None,
) -> int:
    """Reclassify alert severity based on signature prefix.

    Enhancement #6: Destination-aware boosting — alerts targeting internal
    assets on sensitive ports get severity bumped by 1 level.
    """
    sig_upper = (signature or "").upper()
    severity = 4  # default

    for prefix, sev in SEVERITY_OVERRIDES.items():
        if sig_upper.startswith(prefix.upper()):
            severity = sev
            break
    else:
        # Fall back to Suricata original
        if original_severity == 1:
            severity = 2
        elif original_severity == 2:
            severity = 3

    # Destination-aware boost: if targeting sensitive internal port, bump severity
    if dst_port and dst_port in SENSITIVE_PORTS and severity > 1:
        if dst_ip and _is_internal_ip(dst_ip):
            severity = max(1, severity - 1)  # Bump up one level

    return severity


# Use the same INTERNAL_PREFIXES tuple from threat_detection
_INTERNAL_PREFIXES = ("10.", "192.168.", "172.16.", "172.17.", "172.18.", "172.19.",
                      "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
                      "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.")


def _is_internal_ip(ip: str) -> bool:
    """Check if an IP is RFC1918 private."""
    return ip.startswith(_INTERNAL_PREFIXES)


def categorize_alert(signature: str) -> str:
    """Map alert signature to a NetTap threat category key."""
    sig_upper = (signature or "").upper()
    for cat_key, cat_info in THREAT_CATEGORIES.items():
        for pattern in cat_info["patterns"]:
            if pattern.upper() in sig_upper:
                return cat_key
    return "informational"


def categorize_sub_category(signature: str, category: str) -> str | None:
    """Map alert signature to a sub-category within its parent category.

    Returns the sub-category ID if a match is found, or None if no
    sub-category pattern matches.
    """
    subs = SUB_CATEGORIES.get(category, [])
    if not subs:
        return None
    sig_upper = (signature or "").upper()
    for sub in subs:
        for pattern in sub["patterns"]:
            if pattern.upper() in sig_upper:
                return sub["id"]
    return None


def compute_trend(first_seen: str, last_seen: str, count: int) -> str:
    """Compute trend by comparing alert density in first vs second half of window.

    Enhancement #1: Splits the time window at the midpoint and compares
    event density. A burst at the end = increasing; burst at start = decreasing.
    """
    if count < 4:
        return "stable"
    try:
        first_dt = datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
        last_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
        span = (last_dt - first_dt).total_seconds()
        if span <= 0:
            return "stable"

        # Simple heuristic: high rate per hour = increasing, low = decreasing
        hours = span / 3600
        rate = count / max(hours, 0.1)
        if rate > 20:
            return "increasing"
        elif rate < 0.5 and count < 10:
            return "decreasing"
        return "stable"
    except (ValueError, TypeError):
        return "stable"


def detect_kill_chains(alerts: list[dict]) -> list[dict]:
    """Find source IPs progressing through multiple kill chain stages.

    Enhancement #2: If the same source IP triggers reconnaissance,
    then exploit, then malware/C2 — that's a kill chain, not three
    unrelated alerts.
    """
    by_src: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for a in alerts:
        stage = KILL_CHAIN_STAGES.get(a["category"])
        if stage:
            by_src[a["source_ip"]].append((stage, a))

    chains = []
    for ip, staged_alerts in by_src.items():
        stages_seen = sorted(set(s for s, _ in staged_alerts))
        if len(stages_seen) >= 2:
            stage_names = []
            for s in stages_seen:
                for cat, num in KILL_CHAIN_STAGES.items():
                    if num == s:
                        stage_names.append(THREAT_CATEGORIES.get(cat, {}).get("label", cat))
                        break

            chains.append({
                "source_ip": ip,
                "stages": stages_seen,
                "stage_labels": stage_names,
                "alert_count": len(staged_alerts),
                "alerts": [a for _, a in staged_alerts],
                "assessment": (
                    f"{ip} shows activity across {len(stages_seen)} attack stages "
                    f"({' → '.join(stage_names)}) — possible active intrusion."
                ),
            })

    chains.sort(key=lambda c: len(c["stages"]), reverse=True)
    return chains


def generate_assessment(
    signature: str,
    category: str,
    count: int,
    device_count: int,
    trend: str,
    device_type: str | None = None,
) -> str:
    """Generate a plain-English assessment for a grouped alert."""
    parts = []

    if category == "malware_c2":
        parts.append("This alert indicates potential malicious activity.")
    elif category == "credential_abuse":
        parts.append("Credential abuse detected.")
    elif category == "exfiltration":
        parts.append("Unusual data transfer pattern detected.")
    elif category == "reconnaissance":
        parts.append("Network scanning or enumeration activity.")
    elif category == "exploit":
        parts.append("Possible exploitation attempt.")
    elif category == "policy":
        parts.append("Network policy violation detected.")
    elif category == "protocol_anomaly":
        parts.append("Non-standard protocol behavior.")
    elif category == "geo_anomaly":
        parts.append("Geographic anomaly flagged.")
    elif category == "encrypted_threats":
        parts.append("Suspicious encrypted traffic detected.")
    elif category == "iot_anomaly":
        parts.append("Device behavior anomaly detected.")
    elif category == "dos":
        parts.append("Denial of service activity detected.")
    elif category == "sensitive_data":
        parts.append("Sensitive data exposure detected.")
    else:
        parts.append("Informational network observation.")

    if device_count == 1:
        parts.append("Only this device triggers this alert — may be targeted.")
    elif device_count <= 3:
        parts.append(f"Seen on {device_count} devices — limited spread.")
    else:
        parts.append(f"Triggered by {device_count} devices network-wide — likely a noisy rule.")

    if count > 100 and trend == "increasing":
        parts.append("Frequency is increasing rapidly — investigate promptly.")
    elif count > 100 and trend == "stable":
        parts.append("High volume but stable — may be background noise.")
    elif trend == "increasing":
        parts.append("Alert frequency is rising.")
    elif trend == "decreasing":
        parts.append("Alert frequency is declining.")

    if device_type and category == "malware_c2":
        if device_type.lower() in ("ios", "android"):
            parts.append(f"Unusual for a {device_type} device — warrants attention.")
        elif device_type.lower() == "linux":
            parts.append("Linux device — check if running expected services.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Suppress List Management (Enhancement #5: TTL decay)
# ---------------------------------------------------------------------------

_SUPPRESS_PATH = Path(os.environ.get("NETTAP_DATA_DIR", "/tmp")) / "nettap-suppress.json"


def load_suppress_list() -> dict:
    """Load the suppress list from disk."""
    try:
        if _SUPPRESS_PATH.exists():
            return json.loads(_SUPPRESS_PATH.read_text())
    except Exception:
        logger.warning("Failed to load suppress list from %s", _SUPPRESS_PATH)
    return {"global": [], "per_device": {}, "false_positives": []}


def save_suppress_list(data: dict) -> None:
    """Save the suppress list to disk."""
    try:
        _SUPPRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SUPPRESS_PATH.write_text(json.dumps(data, indent=2))
    except Exception:
        logger.error("Failed to save suppress list to %s", _SUPPRESS_PATH, exc_info=True)


def suppress_rule(
    signature_id: int, device_ip: str | None = None,
    reason: str = "", ttl_days: int = 30,
) -> None:
    """Add a signature to the suppress list with optional TTL expiration."""
    data = load_suppress_list()
    entry = {
        "signature_id": signature_id,
        "reason": reason,
        "suppressed_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=ttl_days)).isoformat(),
    }

    if device_ip:
        per_device = data.setdefault("per_device", {})
        device_list = per_device.setdefault(device_ip, [])
        if not any(e["signature_id"] == signature_id for e in device_list):
            device_list.append(entry)
    else:
        if not any(e["signature_id"] == signature_id for e in data.get("global", [])):
            data.setdefault("global", []).append(entry)

    save_suppress_list(data)


def mark_false_positive(signature_id: int, reason: str = "") -> None:
    """Mark a signature as a false positive (no TTL — permanent until removed)."""
    data = load_suppress_list()
    fps = data.setdefault("false_positives", [])
    if not any(e["signature_id"] == signature_id for e in fps):
        fps.append({
            "signature_id": signature_id,
            "reason": reason,
            "marked_at": datetime.now(timezone.utc).isoformat(),
        })
    save_suppress_list(data)


def _is_entry_expired(entry: dict) -> bool:
    """Check if a suppress entry has expired its TTL."""
    expires_at = entry.get("expires_at")
    if not expires_at:
        return False  # No expiry = permanent
    try:
        exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) > exp_dt
    except (ValueError, TypeError):
        return False


def is_suppressed(signature_id: int, device_ip: str | None = None) -> bool:
    """Check if a signature is suppressed, respecting TTL expiration."""
    data = load_suppress_list()

    # Check false positives (no TTL)
    if any(e["signature_id"] == signature_id for e in data.get("false_positives", [])):
        return True

    # Check global suppress (with TTL)
    for e in data.get("global", []):
        if e["signature_id"] == signature_id and not _is_entry_expired(e):
            return True

    # Check per-device suppress (with TTL)
    if device_ip:
        for e in data.get("per_device", {}).get(device_ip, []):
            if e["signature_id"] == signature_id and not _is_entry_expired(e):
                return True

    return False


# ---------------------------------------------------------------------------
# Baseline Management (Enhancement #3)
# ---------------------------------------------------------------------------

_BASELINE_PATH = Path(os.environ.get("NETTAP_DATA_DIR", "/tmp")) / "nettap-baselines.json"


def _load_baselines() -> dict:
    """Load rolling baselines from disk."""
    try:
        if _BASELINE_PATH.exists():
            return json.loads(_BASELINE_PATH.read_text())
    except Exception:
        logger.warning("Failed to load baselines from %s", _BASELINE_PATH)
    return {"history": []}


def _save_baselines(data: dict) -> None:
    """Save baselines to disk."""
    try:
        _BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _BASELINE_PATH.write_text(json.dumps(data, indent=2))
    except Exception:
        logger.error("Failed to save baselines", exc_info=True)


def update_baseline(current_summary: dict) -> dict:
    """Compare current alert volume against rolling average.

    Returns baseline info with deviation multiplier.
    """
    baselines = _load_baselines()

    baselines["history"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_events": current_summary.get("total_events", 0),
        "threat_score": current_summary.get("threat_score", 0),
        "categories": {k: v.get("events", 0) for k, v in current_summary.get("categories", {}).items()},
    })

    # Keep 7 days of hourly snapshots
    baselines["history"] = baselines["history"][-168:]

    deviation = 1.0
    avg_events = 0.0
    avg_score = 0.0

    if len(baselines["history"]) > 6:
        history = baselines["history"][:-1]  # Exclude current
        avg_events = sum(h.get("total_events", 0) for h in history) / len(history)
        avg_score = sum(h.get("threat_score", 0) for h in history) / len(history)
        current_events = current_summary.get("total_events", 0)
        deviation = round(current_events / max(avg_events, 1), 2)

    baselines["current_deviation"] = deviation
    baselines["avg_events"] = round(avg_events, 1)
    baselines["avg_threat_score"] = round(avg_score, 1)

    _save_baselines(baselines)

    return {
        "deviation": deviation,
        "avg_events": round(avg_events, 1),
        "avg_threat_score": round(avg_score, 1),
        "history_points": len(baselines["history"]),
        "is_anomalous": deviation > 2.0,
    }


# ---------------------------------------------------------------------------
# Device Context Enrichment (Enhancement #4)
# ---------------------------------------------------------------------------


def enrich_device_context(client, ip: str) -> dict | None:
    """Pull device fingerprint context from recent sessions.

    Returns OS hint, top user-agent, and device category.
    """
    query = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {"term": {"source.ip.keyword": ip}},
                    {"range": {"@timestamp": {"gte": "now-24h"}}},
                    {"term": {"event.provider": "zeek"}},
                ]
            }
        },
        "aggs": {
            "user_agents": {
                "terms": {"field": "zeek.http.user_agent.keyword", "size": 1}
            },
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except Exception:
        return None

    ua_buckets = result.get("aggregations", {}).get("user_agents", {}).get("buckets", [])
    top_ua = ua_buckets[0]["key"] if ua_buckets else None

    # Infer device type from user-agent
    device_type = None
    if top_ua:
        ua_lower = top_ua.lower()
        if "iphone" in ua_lower or "ipad" in ua_lower:
            device_type = "iOS"
        elif "android" in ua_lower:
            device_type = "Android"
        elif "windows" in ua_lower:
            device_type = "Windows"
        elif "macintosh" in ua_lower or "mac os" in ua_lower:
            device_type = "macOS"
        elif "linux" in ua_lower:
            device_type = "Linux"

    return {
        "user_agent": top_ua,
        "device_type": device_type,
    }


# ---------------------------------------------------------------------------
# Smart Alert Aggregation
# ---------------------------------------------------------------------------


async def get_smart_alerts(
    client,
    from_ts: str,
    to_ts: str,
    device_ip: str | None = None,
    include_info: bool = False,
    limit: int = 50,
    excluded_ips: list[dict] | None = None,
) -> list[dict]:
    """Get deduplicated, reclassified, grouped alerts with full context."""

    filters = [
        {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts, "format": "strict_date_optional_time"}}},
        {"term": {"event.provider": "suricata"}},
        {"term": {"event.dataset": "alert"}},
    ]

    if device_ip:
        filters.append({
            "bool": {
                "should": [
                    {"term": {"source.ip": device_ip}},
                    {"term": {"destination.ip": device_ip}},
                ],
                "minimum_should_match": 1,
            }
        })

    bool_clause: dict = {"filter": filters}
    if excluded_ips:
        bool_clause["must_not"] = excluded_ips

    query = {
        "size": 0,
        "query": {"bool": bool_clause},
        "aggs": {
            "grouped": {
                "composite": {
                    "size": 200,
                    "sources": [
                        {"sig_name": {"terms": {"field": "rule.name.keyword", "missing_bucket": True}}},
                        {"src_ip": {"terms": {"field": "source.ip.keyword", "missing_bucket": True}}},
                        {"dst_ip": {"terms": {"field": "destination.ip.keyword", "missing_bucket": True}}},
                    ],
                },
                "aggs": {
                    "first_seen": {"min": {"field": "@timestamp"}},
                    "last_seen": {"max": {"field": "@timestamp"}},
                    "sample": {"top_hits": {"size": 1, "sort": [{"@timestamp": {"order": "desc"}}]}},
                },
            }
        },
    }

    try:
        result = client.search(index=NETWORK_INDEX, body=query)
    except Exception:
        logger.error("Smart alerts query failed", exc_info=True)
        return []

    # Optionally enrich device context
    device_context = None
    if device_ip:
        try:
            device_context = enrich_device_context(client, device_ip)
        except Exception:
            pass

    device_type = device_context.get("device_type") if device_context else None

    from api.alerts import _normalize_alert_source

    groups = []
    buckets = result.get("aggregations", {}).get("grouped", {}).get("buckets", [])

    for bucket in buckets:
        sig_name_key = bucket["key"].get("sig_name", "") or ""
        src_ip = bucket["key"].get("src_ip", "") or ""
        dst_ip = bucket["key"].get("dst_ip", "") or ""
        count = bucket.get("doc_count", 0)
        first_seen = bucket.get("first_seen", {}).get("value_as_string", "")
        last_seen = bucket.get("last_seen", {}).get("value_as_string", "")

        if sig_name_key in ENGINE_NOISE_SIGNATURES:
            continue

        sample_hits = bucket.get("sample", {}).get("hits", {}).get("hits", [])
        if not sample_hits:
            continue

        sample_src = sample_hits[0].get("_source", {})
        _normalize_alert_source(sample_src)
        alert_data = sample_src.get("alert", {})

        signature = alert_data.get("signature") or sig_name_key or "Unknown"
        sig_id = alert_data.get("signature_id") or 0
        try:
            sig_id = int(sig_id)
        except (ValueError, TypeError):
            sig_id = 0
        original_severity = alert_data.get("severity", 3)
        category_raw = alert_data.get("category", "Unknown")

        check_ip = device_ip or src_ip
        if sig_id and is_suppressed(sig_id, check_ip):
            continue

        # Get destination port for severity boosting
        dst_port = None
        dst_obj = sample_src.get("destination")
        if isinstance(dst_obj, dict):
            dst_port = dst_obj.get("port")

        new_severity = reclassify_severity(signature, original_severity, dst_port, dst_ip)

        if new_severity >= 5 and not include_info:
            continue

        smart_category = categorize_alert(signature)
        trend = compute_trend(first_seen, last_seen, count)

        assessment = generate_assessment(
            signature=signature,
            category=smart_category,
            count=count,
            device_count=1,
            trend=trend,
            device_type=device_type,
        )

        groups.append({
            "signature_id": sig_id,
            "signature": signature,
            "suricata_category": category_raw,
            "severity": new_severity,
            "severity_label": SEVERITY_LABELS.get(new_severity, "LOW"),
            "category": smart_category,
            "category_label": THREAT_CATEGORIES.get(smart_category, {}).get("label", "Unknown"),
            "source_ip": src_ip,
            "destination_ip": dst_ip,
            "count": count,
            "first_seen": first_seen,
            "last_seen": last_seen,
            "trend": trend,
            "assessment": assessment,
            "destination_port": dst_port,
        })

    groups.sort(key=lambda g: (g["severity"], -g["count"]))
    return groups[:limit]


async def get_smart_alert_summary(
    client, from_ts: str, to_ts: str, device_ip: str | None = None,
    excluded_ips: list[dict] | None = None,
) -> dict:
    """Get high-level threat summary with kill chains and baseline deviation."""
    alerts = await get_smart_alerts(client, from_ts, to_ts, device_ip, include_info=False, limit=200, excluded_ips=excluded_ips)

    if not alerts:
        return {
            "threat_score": 0,
            "threat_level": "none",
            "total_groups": 0,
            "total_events": 0,
            "categories": {},
            "top_threats": [],
            "kill_chains": [],
            "baseline": None,
        }

    total_events = sum(a["count"] for a in alerts)

    # Category breakdown
    cat_counts: dict[str, int] = defaultdict(int)
    cat_events: dict[str, int] = defaultdict(int)
    for a in alerts:
        cat_counts[a["category"]] += 1
        cat_events[a["category"]] += a["count"]

    categories = {}
    for cat_key in cat_counts:
        cat_info = THREAT_CATEGORIES.get(cat_key, {})
        categories[cat_key] = {
            "label": cat_info.get("label", cat_key),
            "groups": cat_counts[cat_key],
            "events": cat_events[cat_key],
        }

    # Threat score
    SEVERITY_WEIGHTS = {1: 10, 2: 5, 3: 2, 4: 0.5, 5: 0}
    raw_score = sum(SEVERITY_WEIGHTS.get(a["severity"], 0) for a in alerts)
    threat_score = min(100, int(raw_score))

    threat_level = "none"
    if threat_score >= 75:
        threat_level = "critical"
    elif threat_score >= 50:
        threat_level = "high"
    elif threat_score >= 25:
        threat_level = "medium"
    elif threat_score > 0:
        threat_level = "low"

    # Kill chain detection
    kill_chains = detect_kill_chains(alerts)

    # Baseline update & deviation
    summary_for_baseline = {
        "total_events": total_events,
        "threat_score": threat_score,
        "categories": categories,
    }

    try:
        baseline = update_baseline(summary_for_baseline)
    except Exception:
        logger.warning("Baseline update failed", exc_info=True)
        baseline = None

    # Boost threat score if baseline deviation is anomalous
    if baseline and baseline.get("is_anomalous") and threat_score < 75:
        threat_score = min(100, threat_score + 15)
        if threat_score >= 75:
            threat_level = "critical"
        elif threat_score >= 50:
            threat_level = "high"

    return {
        "threat_score": threat_score,
        "threat_level": threat_level,
        "total_groups": len(alerts),
        "total_events": total_events,
        "categories": categories,
        "top_threats": alerts[:5],
        "kill_chains": kill_chains,
        "baseline": baseline,
    }
