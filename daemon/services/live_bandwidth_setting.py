"""
Live bandwidth opt-in setting (NET-205).

Live bandwidth per device costs CPU while a device page is open, so it is off until the
user turns it on in Settings › Capture. One small JSON file on the daemon's data volume,
{"enabled": true|false}. Missing or unreadable means off.
"""

import json
import logging
import os
import tempfile

logger = logging.getLogger("nettap.services.live_bandwidth_setting")

DEFAULT_FILE = "/opt/nettap/data/live_bandwidth.json"


def _get_file_path() -> str:
    return os.environ.get("LIVE_BANDWIDTH_FILE", DEFAULT_FILE)


def parse_enabled(body: object) -> bool:
    """The `enabled` flag from untrusted JSON, or ValueError with a message for the user."""
    if not isinstance(body, dict) or "enabled" not in body:
        raise ValueError("Body must be a JSON object with 'enabled'")
    enabled = body["enabled"]
    if not isinstance(enabled, bool):
        raise ValueError("'enabled' must be true or false")
    return enabled


def load_enabled(file_path: str | None = None) -> bool:
    """The saved setting; off when never saved or when the file doesn't parse (logged)."""
    path = file_path or _get_file_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return parse_enabled(json.load(f))
    except FileNotFoundError:
        return False
    except (OSError, ValueError) as exc:  # JSONDecodeError is a ValueError
        logger.warning("Ignoring the live bandwidth setting file %s: %s", path, exc)
        return False


def save_enabled(enabled: bool, file_path: str | None = None) -> None:
    """Write atomically, so a crash mid-write never leaves half a file."""
    path = file_path or _get_file_path()
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".live_bandwidth.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"enabled": enabled}, f)
            f.flush()
            os.fsync(f.fileno())  # on disk before the rename
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
