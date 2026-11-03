"""
Pending Ubuntu package updates, as Ubuntu's own update-notifier counted them.

update-notifier rewrites /var/lib/update-notifier/updates-available after every apt update
(apt-daily runs that twice a day); docker-compose.yml mounts it read-only for the daemon.
NetTap only shows the count: installing OS updates stays on the box (owner decision
2026-11-02), and Ubuntu's unattended-upgrades already installs the security ones.
"""

import os
import re
from datetime import datetime, timezone

UPDATE_NOTIFIER = os.environ.get(
    "HOST_UPDATE_NOTIFIER", "/host/var/lib/update-notifier/updates-available"
)
OS_APPLIES_WITH = (
    "Install them on the box itself: run sudo apt update, then sudo apt upgrade."
)

_PENDING = re.compile(r"(\d+) updates? can be applied immediately")
_SECURITY = re.compile(
    r"(\d+) of these updates? (?:is|are) (?:a )?(?:standard )?security updates?"
)


def read_os_updates(path: str = UPDATE_NOTIFIER) -> tuple[int, int, float] | None:
    """(pending, security, as-of epoch seconds), or None if the file isn't there.

    Raises ValueError when the file is there but doesn't say how many are pending.
    """
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        text = fh.read()
    pending = _PENDING.search(text)
    if pending is None:
        raise ValueError(f"{path} doesn't say how many updates are pending")
    security = _SECURITY.search(text)
    return (
        int(pending.group(1)),
        int(security.group(1)) if security else 0,
        os.path.getmtime(path),
    )


def os_update_fields(os_version: str, path: str = UPDATE_NOTIFIER) -> dict | None:
    """AvailableUpdate fields for the "os" row: {} when nothing is pending, None if not mounted."""
    found = read_os_updates(path)
    if found is None:
        return None
    pending, security, as_of = found
    if pending == 0:
        return {}
    stamp = datetime.fromtimestamp(as_of, tz=timezone.utc)
    plural = pending != 1
    return {
        "component": "os",
        "current_version": os_version,
        "latest_version": f"{pending} package update{'s' if plural else ''}",
        "update_type": "unknown",
        "release_url": "https://ubuntu.com/security/notices",
        "release_date": stamp.isoformat(),
        "changelog": (
            f"{pending} Ubuntu package update{'s are' if plural else ' is'} ready to install, "
            f"{security} of them security update{'s' if security != 1 else ''} "
            f"(as of {stamp.strftime('%Y-%m-%d %H:%M UTC')})."
        ),
        "size_mb": None,
        "requires_restart": False,
        "applies_with": OS_APPLIES_WITH,
    }
