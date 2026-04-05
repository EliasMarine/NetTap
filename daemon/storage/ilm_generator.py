"""
NetTap ILM Policy Generator

Generates OpenSearch ISM policy bodies dynamically from ``RetentionConfig``
values, replacing the static ``config/opensearch/ilm-policy.json`` approach.

When a user changes retention days via the setup wizard or the API, this
module produces policy dicts with the correct ``min_index_age`` values
instead of the hardcoded 90d/180d/30d in the JSON file.

Usage:
    from storage.ilm_generator import generate_ilm_policies
    from storage.manager import RetentionConfig

    config = RetentionConfig(hot_days=60, warm_days=120, cold_days=14)
    policies = generate_ilm_policies(config)
    # policies is a dict[str, dict] ready for apply_ilm_policies()
"""

import logging

from storage.manager import RetentionConfig

logger = logging.getLogger("nettap.storage.ilm_generator")


def _retry_config() -> dict:
    """Return the standard retry configuration used in all ISM policy actions.

    All NetTap ISM actions use exponential backoff with 3 retries and a
    10-minute initial delay.  Centralised here to avoid repetition and
    ensure consistency across policies.
    """
    return {"count": 3, "backoff": "exponential", "delay": "10m"}


def generate_ilm_policies(config: RetentionConfig) -> dict[str, dict]:
    """Generate all three ISM policies from retention configuration.

    Produces the same policy structure as ``config/opensearch/ilm-policy.json``
    but with retention days sourced from *config* instead of hardcoded values.

    Args:
        config: A ``RetentionConfig`` instance with ``hot_days``, ``warm_days``,
            and ``cold_days`` fields.

    Returns:
        Dict mapping policy_name to policy_body.  Each value has the outer
        ``{"policy": {...}}`` wrapper that ``apply_ilm_policies()`` in
        ``daemon/storage/ilm.py`` expects.

    Example:
        >>> cfg = RetentionConfig(hot_days=60, warm_days=120, cold_days=14)
        >>> policies = generate_ilm_policies(cfg)
        >>> sorted(policies.keys())
        ['nettap-cold-policy', 'nettap-hot-policy', 'nettap-warm-policy']
    """
    logger.info(
        "Generating ILM policies (hot=%dd, warm=%dd, cold=%dd)",
        config.hot_days,
        config.warm_days,
        config.cold_days,
    )

    policies: dict[str, dict] = {}

    # -----------------------------------------------------------------------
    # HOT tier -- Zeek metadata logs
    # -----------------------------------------------------------------------
    policies["nettap-hot-policy"] = {
        "policy": {
            "description": (
                f"NetTap HOT tier -- Zeek metadata logs. "
                f"Rollover at 10GB or 1 day, delete after {config.hot_days} days. "
                f"Zeek generates 300-800MB/day of structured conn, DNS, HTTP, TLS, "
                f"DHCP, SMTP, and file metadata logs compressed ~8:1 with zstd."
            ),
            "default_state": "hot",
            "states": [
                {
                    "name": "hot",
                    "actions": [
                        {
                            "retry": _retry_config(),
                            "rollover": {
                                "min_primary_shard_size": "10gb",
                                "min_index_age": "1d",
                            },
                        }
                    ],
                    "transitions": [
                        {
                            "state_name": "delete",
                            "conditions": {
                                "min_index_age": f"{config.hot_days}d"
                            },
                        }
                    ],
                },
                {
                    "name": "delete",
                    "actions": [
                        {
                            "retry": _retry_config(),
                            "delete": {},
                        }
                    ],
                    "transitions": [],
                },
            ],
            "ism_template": [
                {"index_patterns": ["zeek-*"], "priority": 100}
            ],
        }
    }

    # -----------------------------------------------------------------------
    # WARM tier -- Suricata IDS alerts
    # -----------------------------------------------------------------------
    policies["nettap-warm-policy"] = {
        "policy": {
            "description": (
                f"NetTap WARM tier -- Suricata IDS alerts. "
                f"Rollover at 5GB or 1 day, force merge to 1 segment and set "
                f"read-only after 7 days, delete after {config.warm_days} days. "
                f"Suricata generates 10-50MB/day of alert, DNS, TLS, HTTP, file, "
                f"and flow logs compressed ~6:1 with zstd."
            ),
            "default_state": "hot",
            "states": [
                {
                    "name": "hot",
                    "actions": [
                        {
                            "retry": _retry_config(),
                            "rollover": {
                                "min_primary_shard_size": "5gb",
                                "min_index_age": "1d",
                            },
                        }
                    ],
                    "transitions": [
                        {
                            "state_name": "warm",
                            "conditions": {
                                "min_index_age": "7d",
                            },
                        }
                    ],
                },
                {
                    "name": "warm",
                    "actions": [
                        {
                            "retry": _retry_config(),
                            "force_merge": {
                                "max_num_segments": 1,
                            },
                        },
                        {
                            "retry": _retry_config(),
                            "read_only": {},
                        },
                    ],
                    "transitions": [
                        {
                            "state_name": "delete",
                            "conditions": {
                                "min_index_age": f"{config.warm_days}d",
                            },
                        }
                    ],
                },
                {
                    "name": "delete",
                    "actions": [
                        {
                            "retry": _retry_config(),
                            "delete": {},
                        }
                    ],
                    "transitions": [],
                },
            ],
            "ism_template": [
                {"index_patterns": ["suricata-*"], "priority": 100}
            ],
        }
    }

    # -----------------------------------------------------------------------
    # COLD tier -- Arkime/PCAP indices
    # -----------------------------------------------------------------------
    policies["nettap-cold-policy"] = {
        "policy": {
            "description": (
                f"NetTap COLD tier -- Arkime/PCAP indices for alert-triggered "
                f"raw packet captures. Rollover at 20GB or 1 day, delete after "
                f"{config.cold_days} days. PCAP size is variable and depends on "
                f"alert volume; compressed ~3:1 with zstd."
            ),
            "default_state": "hot",
            "states": [
                {
                    "name": "hot",
                    "actions": [
                        {
                            "retry": _retry_config(),
                            "rollover": {
                                "min_primary_shard_size": "20gb",
                                "min_index_age": "1d",
                            },
                        }
                    ],
                    "transitions": [
                        {
                            "state_name": "delete",
                            "conditions": {
                                "min_index_age": f"{config.cold_days}d",
                            },
                        }
                    ],
                },
                {
                    "name": "delete",
                    "actions": [
                        {
                            "retry": _retry_config(),
                            "delete": {},
                        }
                    ],
                    "transitions": [],
                },
            ],
            "ism_template": [
                {"index_patterns": ["arkime-*", "pcap-*"], "priority": 100}
            ],
        }
    }

    logger.info(
        "Generated %d ILM policies: %s",
        len(policies),
        ", ".join(sorted(policies.keys())),
    )

    return policies
