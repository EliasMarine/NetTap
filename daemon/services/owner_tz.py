"""
The owner's time zone (NET-329, roadmap F4 §4.1): the zone the usage ledger counts days in.

One small JSON file on the daemon's data volume, {"tz": "<IANA name>", "set_at": iso}. Until the
owner picks a zone it is UTC. A file that can't be read is reported (`ok` False) so the ledger
keeps its own zone instead of taking UTC as a choice.
"""

import functools
import json
import logging
import os
import zoneinfo
from datetime import datetime, timezone
from pathlib import Path

from services.capture_config import write_file_atomic

logger = logging.getLogger("nettap.services.owner_tz")

DEFAULT_FILE = "/opt/nettap/data/owner-timezone.json"
UTC = "UTC"


def _path(path: str | None) -> str:
    return path or os.environ.get("OWNER_TZ_FILE", DEFAULT_FILE)


@functools.cache
def _known() -> frozenset[str]:
    # available_timezones() walks the zone database on every call
    return frozenset(zoneinfo.available_timezones())


def known(name: object) -> bool:
    """True for an IANA zone name this system's zone database has."""
    return isinstance(name, str) and name in _known()


def read(path: str | None = None) -> dict:
    """{"tz", "set", "ok"}: UTC and not set when there is no file; ok False when it is unreadable."""
    where = _path(path)
    try:
        data = json.loads(Path(where).read_text(encoding="utf-8"))
        name = data.get("tz") if isinstance(data, dict) else None
        if not known(name):
            raise ValueError(f"{name!r} isn't a known time zone")
    except FileNotFoundError:
        return {"tz": UTC, "set": False, "ok": True}
    # JSONDecodeError and UnicodeDecodeError are ValueErrors
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring the time zone file %s: %s", where, exc)
        return {"tz": UTC, "set": False, "ok": False}
    return {"tz": name, "set": True, "ok": True}


def write(name: str, path: str | None = None) -> dict:
    """Save the owner's zone; ValueError if the name isn't one the zone database has."""
    if not known(name):
        raise ValueError("That isn't a time zone NetTap knows")
    where = _path(path)
    Path(where).parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()
    write_file_atomic(where, json.dumps({"tz": name, "set_at": stamp}), mode=0o644)
    return {"tz": name, "set": True}
