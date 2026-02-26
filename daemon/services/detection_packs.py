"""
NetTap Community Detection Packs Manager

Manages community-contributed Suricata rule packs for enhanced threat
detection. Supports installing, enabling/disabling, and updating rule
packs. All pack metadata is persisted to a local JSON file.

Built-in packs include Emerging Threats Open, IoT rulesets, Abuse.ch
threat intelligence, TGreen hunting rules, and NetTap defaults.
"""

import json
import logging
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

logger = logging.getLogger("nettap.services.detection_packs")


@dataclass
class DetectionPack:
    """A community detection rule pack for Suricata."""

    id: str
    name: str
    description: str
    version: str
    author: str
    rule_count: int
    enabled: bool
    installed_at: str
    updated_at: str
    category: str  # 'malware', 'network', 'web', 'iot', 'custom'
    tags: list[str] = field(default_factory=list)
    source_url: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# Built-in pack definitions (templates for installation)
BUILTIN_PACK_DEFS: list[dict] = [
    {
        "id": "et-open",
        "name": "Emerging Threats Open",
        "description": "Open-source Suricata rules from Proofpoint/ET. "
                       "Covers malware, exploits, policy violations, and more.",
        "version": "2026.02.01",
        "author": "Proofpoint Emerging Threats",
        "rule_count": 47000,
        "category": "malware",
        "tags": ["malware", "exploits", "network", "policy"],
        "source_url": "https://rules.emergingthreats.net/open/suricata/emerging.rules.tar.gz",
    },
    {
        "id": "et-iot",
        "name": "ET IoT Ruleset",
        "description": "Emerging Threats rules focused on IoT device detection, "
                       "known IoT botnets, and vulnerable firmware signatures.",
        "version": "2026.01.15",
        "author": "Proofpoint Emerging Threats",
        "rule_count": 3200,
        "category": "iot",
        "tags": ["iot", "botnets", "firmware", "smart-home"],
        "source_url": "https://rules.emergingthreats.net/open/suricata/emerging-iot.rules",
    },
    {
        "id": "abuse-ch",
        "name": "Abuse.ch Threat Intelligence",
        "description": "Suricata rules from abuse.ch covering botnet C2 servers, "
                       "malware distribution URLs, and SSL certificate blocklists.",
        "version": "2026.02.10",
        "author": "abuse.ch",
        "rule_count": 8500,
        "category": "malware",
        "tags": ["c2", "botnet", "malware-urls", "ssl-blocklist"],
        "source_url": "https://sslbl.abuse.ch/blacklist/sslblacklist.rules",
    },
    {
        "id": "tgreen-hunting",
        "name": "TGreen Hunting Rules",
        "description": "Community threat hunting rules by Travis Green. "
                       "Focused on lateral movement, persistence, and exfiltration detection.",
        "version": "2025.12.01",
        "author": "Travis Green",
        "rule_count": 1200,
        "category": "network",
        "tags": ["hunting", "lateral-movement", "persistence", "exfiltration"],
        "source_url": "https://github.com/travgreen/hunting-rules/releases/latest",
    },
    {
        "id": "nettap-defaults",
        "name": "NetTap Default Rules",
        "description": "Curated ruleset optimized for home/small business networks. "
                       "Includes DNS tunneling, port scan detection, and unusual traffic patterns.",
        "version": "1.0.0",
        "author": "NetTap Team",
        "rule_count": 500,
        "category": "network",
        "tags": ["dns-tunneling", "port-scan", "anomaly", "home-network"],
        "source_url": "",
    },
]

VALID_CATEGORIES = ("malware", "network", "web", "iot", "custom")


class DetectionPackManager:
    """Manages community detection rule packs for Suricata.

    Pack metadata is persisted to a JSON file in the packs directory.
    Actual rule files would be downloaded and stored in subdirectories
    (not implemented in v1 -- only metadata management).
    """

    def __init__(self, packs_dir: str = "/opt/nettap/data/detection-packs"):
        self._packs_dir = packs_dir
        self._metadata_file = os.path.join(packs_dir, "packs_metadata.json")
        self._packs: dict[str, DetectionPack] = {}
        self._load()

    def _load(self) -> None:
        """Load pack metadata from disk. Starts empty if missing."""
        try:
            if os.path.exists(self._metadata_file):
                with open(self._metadata_file, "r") as f:
                    raw = json.load(f)
                for pack_data in raw:
                    pack = DetectionPack(**pack_data)
                    self._packs[pack.id] = pack
                logger.info(
                    "Loaded %d detection packs from %s",
                    len(self._packs),
                    self._metadata_file,
                )
        except (json.JSONDecodeError, OSError, TypeError) as exc:
            logger.warning(
                "Failed to load detection packs from %s: %s",
                self._metadata_file,
                exc,
            )
            self._packs = {}

    def _save(self) -> None:
        """Persist all pack metadata to disk."""
        try:
            os.makedirs(self._packs_dir, exist_ok=True)
            data = [pack.to_dict() for pack in self._packs.values()]
            with open(self._metadata_file, "w") as f:
                json.dump(data, f, indent=2)
        except OSError as exc:
            logger.error(
                "Failed to save detection packs to %s: %s",
                self._metadata_file,
                exc,
            )
            raise

    def list_packs(self) -> list[DetectionPack]:
        """List all installed detection packs."""
        return list(self._packs.values())

    def get_pack(self, pack_id: str) -> DetectionPack | None:
        """Get a specific pack by ID."""
        return self._packs.get(pack_id)

    def install_pack(self, pack_id: str) -> DetectionPack:
        """Install a builtin pack by ID.

        Raises ValueError if pack_id is not found in BUILTIN_PACK_DEFS
        or is already installed.
        """
        if pack_id in self._packs:
            raise ValueError(f"Pack '{pack_id}' is already installed")

        # Find the builtin definition
        builtin_def = None
        for bdef in BUILTIN_PACK_DEFS:
            if bdef["id"] == pack_id:
                builtin_def = bdef
                break

        if builtin_def is None:
            raise ValueError(
                f"Unknown pack ID: '{pack_id}'. "
                f"Available: {[d['id'] for d in BUILTIN_PACK_DEFS]}"
            )

        now = datetime.now(timezone.utc).isoformat()
        pack = DetectionPack(
            id=builtin_def["id"],
            name=builtin_def["name"],
            description=builtin_def["description"],
            version=builtin_def["version"],
            author=builtin_def["author"],
            rule_count=builtin_def["rule_count"],
            enabled=True,
            installed_at=now,
            updated_at=now,
            category=builtin_def["category"],
            tags=list(builtin_def["tags"]),
            source_url=builtin_def.get("source_url", ""),
        )

        self._packs[pack.id] = pack
        self._save()
        logger.info("Installed detection pack: %s (%s)", pack.name, pack.id)
        return pack

    def uninstall_pack(self, pack_id: str) -> bool:
        """Remove a detection pack. Returns True if found and removed."""
        if pack_id in self._packs:
            name = self._packs[pack_id].name
            del self._packs[pack_id]
            self._save()
            logger.info("Uninstalled detection pack: %s (%s)", name, pack_id)
            return True
        return False

    def enable_pack(self, pack_id: str) -> bool:
        """Enable a pack (rules will be loaded by Suricata).

        Returns True if the pack was found and enabled.
        """
        pack = self._packs.get(pack_id)
        if pack is None:
            return False

        pack.enabled = True
        pack.updated_at = datetime.now(timezone.utc).isoformat()
        self._save()
        logger.info("Enabled detection pack: %s", pack.name)
        return True

    def disable_pack(self, pack_id: str) -> bool:
        """Disable a pack without uninstalling.

        Returns True if the pack was found and disabled.
        """
        pack = self._packs.get(pack_id)
        if pack is None:
            return False

        pack.enabled = False
        pack.updated_at = datetime.now(timezone.utc).isoformat()
        self._save()
        logger.info("Disabled detection pack: %s", pack.name)
        return True

    def check_updates(self) -> list[dict]:
        """Check which packs have updates available.

        Returns list of {pack_id, current_version, available_version}.
        For now, returns empty list (future: check source URLs).
        """
        # Placeholder for future update check logic.
        # Would check source_url for each installed pack.
        return []

    def get_stats(self) -> dict:
        """Return pack statistics: total packs, enabled, total rules, by category."""
        total = len(self._packs)
        enabled = sum(1 for p in self._packs.values() if p.enabled)
        disabled = total - enabled
        total_rules = sum(p.rule_count for p in self._packs.values())
        enabled_rules = sum(
            p.rule_count for p in self._packs.values() if p.enabled
        )

        by_category: dict[str, int] = {}
        for pack in self._packs.values():
            by_category[pack.category] = by_category.get(pack.category, 0) + 1

        return {
            "total_packs": total,
            "enabled_packs": enabled,
            "disabled_packs": disabled,
            "total_rules": total_rules,
            "enabled_rules": enabled_rules,
            "by_category": by_category,
        }

    def get_available_packs(self) -> list[dict]:
        """Return list of builtin packs that are not yet installed.

        Each dict has: id, name, description, category, rule_count, installed.
        """
        available = []
        for bdef in BUILTIN_PACK_DEFS:
            available.append({
                "id": bdef["id"],
                "name": bdef["name"],
                "description": bdef["description"],
                "category": bdef["category"],
                "rule_count": bdef["rule_count"],
                "installed": bdef["id"] in self._packs,
            })
        return available
