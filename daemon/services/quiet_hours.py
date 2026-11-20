"""
Quiet hours (NET-330, roadmap #8): the owner's overnight window in which notifications wait.

The setting is `quiet` in notifications.json, kept by the hub. The window is read in the owner's
time zone (F4, owner_tz). The dispatcher asks `source(hub)(now)` at each send decision whether a
window holds now: inside it only critical alerts go (when the owner lets them), and the first
poll after it sends everything held as one message (plans/2026-11-20-f8-quiet-hours.md §4.1).
"""

import re
from collections.abc import Callable
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo

from services import owner_tz

DEFAULT: dict[str, Any] = {
    "enabled": False,
    "start": "22:00",
    "end": "07:00",
    "critical_through": True,  # decision D3
}
# ASCII digits only: \d would take other scripts' digits, which time.fromisoformat refuses
_HHMM = re.compile(r"[0-2][0-9]:[0-5][0-9]", re.ASCII)


class Hold(NamedTuple):
    """A window holding now: when it ends (UTC) and whether critical alerts still go."""

    end: datetime
    critical_through: bool


def _time(raw: Any) -> time | None:
    if not isinstance(raw, str) or not _HHMM.fullmatch(raw):
        return None
    try:
        return time.fromisoformat(raw)  # refuses 24:00 and 29:00
    except ValueError:
        return None


def problem(raw: Any) -> str | None:
    """Why `raw` can't be the quiet hours setting, or None. A backup's `tz` is allowed beside it."""
    if not isinstance(raw, dict):
        return "Quiet hours must be an object"
    if "tz" in raw and not isinstance(raw["tz"], str):
        return "Quiet hours' time zone must be a name"
    if set(raw) - {"tz"} != set(DEFAULT):
        return "Quiet hours need enabled, start, end and critical_through, and nothing else"
    for key in ("enabled", "critical_through"):
        if not isinstance(raw[key], bool):
            return f"Quiet hours' {key} must be true or false"
    start, end = _time(raw["start"]), _time(raw["end"])
    if start is None or end is None:
        return "Quiet hours' start and end must be times such as 22:00"
    if start == end:
        return "Quiet hours can't start and end at the same time"
    return None


def of(raw: Any) -> dict[str, Any]:
    """The four fields of a valid setting, else the default (off)."""
    if problem(raw) is not None:
        return dict(DEFAULT)
    return {key: raw[key] for key in DEFAULT}


def _at(day: date, at: time, zone: ZoneInfo) -> datetime:
    # fold=0: a skipped time lands an hour later, a repeated one on its first occurrence. In UTC,
    # because two datetimes sharing one ZoneInfo compare as wall times
    return datetime.combine(day, at, tzinfo=zone).astimezone(timezone.utc)


def hold(now: datetime, quiet: Any, tz: str) -> Hold | None:
    """The window holding at `now` in zone `tz`, or None (off, or outside it)."""
    quiet = of(quiet)
    if not quiet["enabled"]:
        return None
    start, end = _time(quiet["start"]), _time(quiet["end"])
    zone = ZoneInfo(tz)
    now = now.astimezone(timezone.utc)
    today = now.astimezone(zone).date()
    # yesterday's window may still be running after midnight
    for day in (today - timedelta(days=1), today):
        begins = _at(day, start, zone)
        ends = _at(day if end > start else day + timedelta(days=1), end, zone)
        if begins <= now < ends:
            return Hold(ends, quiet["critical_through"])
    return None


def source(hub: Any, tz_path: str | None = None) -> Callable[[datetime], Hold | None]:
    """What the dispatcher asks: the hub's setting in the owner's zone, read at each call."""
    return lambda now: hold(now, hub.quiet(), owner_tz.read(tz_path)["tz"])
