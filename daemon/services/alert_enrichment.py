"""
Alert description enrichment for NetTap.

Translates Suricata signature names into plain English descriptions
with risk context and recommendations. Maintains a curated mapping
of common ET (Emerging Threats) signature prefixes.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger("nettap.services.alert_enrichment")

# Path to curated SID description mapping
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DESCRIPTIONS_FILE = _DATA_DIR / "suricata_descriptions.json"


# ---------------------------------------------------------------------------
# Pattern-based prefix descriptions
# ---------------------------------------------------------------------------

_PREFIX_PATTERNS: list[tuple[str, str, str]] = [
    # (prefix, category_key, description_template)
    ("ET MALWARE", "malware", "Potential malware activity detected: {}"),
    ("ET SCAN", "scan", "Network scanning activity detected: {}"),
    ("ET TROJAN", "trojan", "Trojan horse communication detected: {}"),
    ("ET EXPLOIT", "exploit", "Exploit attempt detected: {}"),
    ("ET POLICY", "policy", "Network policy violation: {}"),
    ("ET INFO", "info", "Informational network event: {}"),
    ("ET DNS", "dns", "Suspicious DNS activity: {}"),
    ("ET WEB_SERVER", "web_server", "Web server attack detected: {}"),
    ("ET WEB_CLIENT", "web_client", "Web client vulnerability activity: {}"),
    ("ET HUNTING", "hunting", "Threat hunting indicator detected: {}"),
    ("ET CURRENT_EVENTS", "current_events", "Current threat campaign activity: {}"),
    (
        "ET ATTACK_RESPONSE",
        "attack_response",
        "Attack response or successful compromise indicator: {}",
    ),
    ("ET DOS", "dos", "Denial of service activity detected: {}"),
    ("ET DROP", "drop", "Traffic from known malicious source: {}"),
    ("GPL", "gpl", "Known threat signature matched: {}"),
]


# ---------------------------------------------------------------------------
# Recommendation mapping
# ---------------------------------------------------------------------------

_RECOMMENDATIONS: dict[str, str] = {
    "malware": (
        "Investigate the affected device for malware infection. "
        "Consider isolating it from the network and running a full antivirus scan."
    ),
    "scan": (
        "This may indicate reconnaissance activity. Monitor for follow-up "
        "connection attempts and verify the scanning source is authorized."
    ),
    "trojan": (
        "A device may be communicating with a command-and-control server. "
        "Immediately isolate the device and perform a thorough malware scan."
    ),
    "exploit": (
        "An exploit attempt was detected. Ensure all devices and software are "
        "updated to the latest versions. Check for signs of compromise."
    ),
    "policy": (
        "Review your network usage policies. This may be legitimate activity "
        "that violates organizational guidelines, or it may indicate shadow IT."
    ),
    "info": (
        "This is an informational alert and may not require immediate action. "
        "Review the details to determine if the activity is expected."
    ),
    "dns": (
        "Suspicious DNS activity can indicate malware, data exfiltration, or "
        "tunneling. Investigate the queried domains for known threats."
    ),
    "web_server": (
        "A web server on your network may be under attack. Review server logs, "
        "ensure web applications are patched, and consider WAF protection."
    ),
    "web_client": (
        "A device may have visited a malicious website or downloaded harmful "
        "content. Check browser history and scan the device for threats."
    ),
    "hunting": (
        "This is a threat hunting indicator that may warrant investigation. "
        "Correlate with other alerts to determine if this is part of a broader attack."
    ),
    "current_events": (
        "This alert matches a known active threat campaign. Prioritize "
        "investigation and check for indicators of compromise across your network."
    ),
    "attack_response": (
        "This may indicate a successful compromise. Investigate immediately "
        "for data exfiltration, lateral movement, or persistent access."
    ),
    "dos": (
        "Denial of service activity detected. Monitor bandwidth and service "
        "availability. Consider rate limiting or upstream filtering."
    ),
    "drop": (
        "Traffic from a known malicious source was detected. Block this IP "
        "at your firewall and investigate any devices that communicated with it."
    ),
    "gpl": (
        "A well-known threat signature was matched. Review the specific "
        "signature details and investigate the affected devices."
    ),
    "unknown": (
        "Review this alert and investigate the network activity. Check "
        "the source and destination for any signs of suspicious behavior."
    ),
}


# ---------------------------------------------------------------------------
# Risk context generation
# ---------------------------------------------------------------------------

_SEVERITY_LABELS = {
    1: "High",
    2: "Medium",
    3: "Low",
}

_CATEGORY_RISK_NOTES: dict[str, dict[int, str]] = {
    "malware": {
        1: "This is a critical threat. Malware with high severity often indicates active infection with data theft or ransomware capabilities.",
        2: "This is a moderate threat. The malware variant detected may be attempting to establish persistence or download additional payloads.",
        3: "This is a low-severity malware indicator. It may be adware or a potentially unwanted program (PUP).",
    },
    "trojan": {
        1: "Critical risk. An active trojan communication channel suggests the device is compromised and under remote control.",
        2: "Moderate risk. Trojan-like behavior was detected but may not yet have established a full command-and-control channel.",
        3: "Low risk. This may be a false positive or an older trojan variant with limited capabilities.",
    },
    "exploit": {
        1: "Critical risk. A high-severity exploit attempt may lead to immediate system compromise if successful.",
        2: "Moderate risk. The exploit attempt targets a known vulnerability. Verify that affected systems are patched.",
        3: "Low risk. The exploit attempt is unlikely to succeed against properly patched systems.",
    },
    "scan": {
        1: "Aggressive scanning from this source. This often precedes a targeted attack.",
        2: "Moderate scanning activity. May be automated vulnerability assessment or reconnaissance.",
        3: "Light scanning detected. This is common internet background noise but worth monitoring.",
    },
}

_DEFAULT_RISK_NOTES: dict[int, str] = {
    1: "This is a high-severity alert requiring immediate attention. Investigate promptly to prevent potential damage.",
    2: "This is a medium-severity alert. Investigate when possible to determine if action is needed.",
    3: "This is a low-severity alert. Review during routine security monitoring.",
}


# ---------------------------------------------------------------------------
# AlertEnrichment class
# ---------------------------------------------------------------------------


class AlertEnrichment:
    """Enriches Suricata alerts with plain English descriptions, risk context,
    and actionable recommendations.

    Loads a curated SID-to-description mapping from a JSON file and falls
    back to pattern-based generation for unmapped signatures.
    """

    def __init__(self, descriptions_file: str | Path | None = None):
        self._descriptions_file = (
            Path(descriptions_file) if descriptions_file else _DESCRIPTIONS_FILE
        )
        self._sid_descriptions: dict[str, dict] = {}
        self._prefix_descriptions: dict[str, str] = {}
        self._load_descriptions()

    def _load_descriptions(self) -> None:
        """Load the curated SID descriptions from the JSON file."""
        try:
            if self._descriptions_file.exists():
                with open(self._descriptions_file, "r") as f:
                    data = json.load(f)
                self._sid_descriptions = data.get("descriptions", {})
                self._prefix_descriptions = data.get("prefix_descriptions", {})
                logger.info(
                    "Loaded %d SID descriptions and %d prefix descriptions",
                    len(self._sid_descriptions),
                    len(self._prefix_descriptions),
                )
            else:
                logger.warning(
                    "Suricata descriptions file not found: %s — using pattern-based fallback",
                    self._descriptions_file,
                )
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Failed to load suricata descriptions from %s: %s — using pattern-based fallback",
                self._descriptions_file,
                exc,
            )

    def enrich_alert(self, alert: dict) -> dict:
        """Add plain_description, risk_context, and recommendation to an alert.

        Looks up by SID first, then falls back to pattern matching on the
        signature name. All original alert fields are preserved.

        Args:
            alert: A Suricata alert dict, expected to contain an 'alert'
                   sub-dict with 'signature', 'signature_id', 'severity',
                   and optionally 'category'.

        Returns:
            The same alert dict with added enrichment fields.
        """
        alert_data = alert.get("alert", {})
        signature = alert_data.get("signature", "")
        sid = str(alert_data.get("signature_id", ""))
        severity = alert_data.get("severity", 3)

        # Try SID lookup first
        if sid and sid in self._sid_descriptions:
            sid_info = self._sid_descriptions[sid]
            alert["plain_description"] = sid_info.get("description", "")
            alert["risk_context"] = sid_info.get(
                "risk_context",
                get_risk_context(severity, _get_category_from_signature(signature)),
            )
            alert["recommendation"] = sid_info.get(
                "recommendation",
                get_recommendation(_get_category_from_signature(signature)),
            )
            return alert

        # Fall back to pattern-based generation
        category = _get_category_from_signature(signature)
        alert["plain_description"] = generate_description(signature)
        alert["risk_context"] = get_risk_context(severity, category)
        alert["recommendation"] = get_recommendation(category)

        return alert


# ---------------------------------------------------------------------------
# Module-level utility functions
# ---------------------------------------------------------------------------


def generate_description(signature: str) -> str:
    """Generate a plain English description from a Suricata signature name.

    Matches the signature against known ET prefix patterns and produces
    a human-readable description. Falls back to a generic message if
    no prefix matches.

    Args:
        signature: The Suricata signature string (e.g. "ET MALWARE Win32/Emotet").

    Returns:
        A plain English description string.
    """
    if not signature:
        return "Network security event detected."

    for prefix, _category, template in _PREFIX_PATTERNS:
        if signature.upper().startswith(prefix.upper()):
            # Extract the descriptive part after the prefix
            detail = signature[len(prefix) :].strip()
            if not detail:
                detail = signature
            return template.format(detail)

    return f"Network security event detected: {signature}"


def get_recommendation(category: str) -> str:
    """Return an actionable recommendation based on the alert category.

    Args:
        category: The alert category key (e.g. "malware", "scan").

    Returns:
        A recommendation string for the user.
    """
    return _RECOMMENDATIONS.get(category, _RECOMMENDATIONS["unknown"])


def get_risk_context(severity: int, category: str) -> str:
    """Return risk context based on severity level and alert category.

    Provides category-specific context when available, otherwise
    falls back to generic severity-based context.

    Args:
        severity: Suricata severity level (1=high, 2=medium, 3=low).
        category: The alert category key.

    Returns:
        A risk context description string.
    """
    # Try category-specific context first
    if category in _CATEGORY_RISK_NOTES:
        cat_notes = _CATEGORY_RISK_NOTES[category]
        if severity in cat_notes:
            return cat_notes[severity]

    # Fall back to generic severity context
    return _DEFAULT_RISK_NOTES.get(
        severity,
        f"Severity {severity} alert detected. Review the alert details for more information.",
    )


def _get_category_from_signature(signature: str) -> str:
    """Extract the alert category from a signature string by matching prefixes.

    Returns the category key for the first matching prefix, or "unknown"
    if no prefix matches.
    """
    if not signature:
        return "unknown"

    sig_upper = signature.upper()
    for prefix, category, _template in _PREFIX_PATTERNS:
        if sig_upper.startswith(prefix.upper()):
            return category

    return "unknown"
