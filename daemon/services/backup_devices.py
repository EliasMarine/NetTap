"""The owner's device stores in a config restore: names and pictures (NET-200), then details
(NET-320). Moved out of ConfigBackup.import_config (NET-320) to keep config_backup under 800 lines.
"""

import logging
from typing import Any

from services.device_custom import StoreUnavailable

# config_backup's logger, as when this ran there, so the log reads the same
logger = logging.getLogger("nettap.services.config_backup")


def restore_devices(
    sections: dict,
    device_custom: Any,
    device_details: Any,
    applied: list,
    errors: list,
    notes: list,
) -> None:
    """Each present section replaces the owner's set; a store that is None can't restore."""
    # Device names and pictures: each present section replaces the owner's set, all or nothing
    device_parts = [s for s in ("device_aliases", "device_pictures") if s in sections]
    device_names = sections.get("device_aliases")
    # OLD CODE: notes: list[str] = [] (A9: import_config creates it, so the notification notes go first)
    if "device_aliases" in sections and "device_pictures" not in sections:
        # A backup from before NET-200: its device_aliases came from the dead baseline
        # code and is always {}, so replacing with it would wipe every owner's name
        device_parts.remove("device_aliases")
        device_names = None
        notes.append(
            "This backup was made before device names could be backed up; "
            "the current device names are kept."
        )
    if device_parts and device_custom is None:
        errors.append("Device names and pictures can't be restored here")
    elif device_parts:
        try:
            device_custom.restore(device_names, sections.get("device_pictures"))
            applied.extend(device_parts)
        # TypeError too: a malformed backup must never escape after other sections applied
        except (ValueError, TypeError, RuntimeError, OSError) as exc:
            logger.error("Device names and pictures not restored: %s", exc)
            errors.append(f"Device names and pictures not restored: {exc}")

    # NET-320: a present section replaces the set; a backup from before F2 has none, and the
    # current details are kept. No details store (older setups): skipped.
    if "device_details" in sections and device_details is not None:
        try:
            device_details.restore(sections["device_details"])
            applied.append("device_details")
        except (ValueError, StoreUnavailable, OSError) as exc:
            logger.error("Device details not restored: %s", exc)
            errors.append(f"Device details not restored: {exc}")
