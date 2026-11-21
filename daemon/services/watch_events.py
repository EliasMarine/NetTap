"""
Watched devices' journal events as notifications (F5, NET-331; plans/2026-11-20-f5-watched-devices.md §2.5).

The watched-devices job journals device_offline and device_online, keyed by the upper-case MAC.
The dispatcher turns each into one queued item here and keeps at most one per device, the
newest, on every channel. Only the owner's own name goes into a message (D7), never a name a
device announced, and it is checked again here: the journal is a file anyone with the volume
could edit.
"""

import unicodedata
from typing import Any

from services.device_custom import NAME_MAX
from services.device_details import _BAD_CATEGORIES, strict_mac
from services.notification_hub import _clip
from services.watched_rules import OFFLINE, ONLINE

EVENT = "watched_device"  # the hub event type both route under
_SEVERITY = {OFFLINE: 2, ONLINE: 4}


def _positive(raw: Any) -> bool:
    return type(raw) is int and raw > 0  # type(), not isinstance(): True is an int


def _label(name: str | None, mac: str) -> str:
    """The owner's name and the MAC; the MAC alone when there is no name, or it isn't one line
    of plain text (no control, bidi or line-separator characters)."""
    name = unicodedata.normalize("NFC", name).strip() if name else ""
    if not name or any(unicodedata.category(ch) in _BAD_CATEGORIES for ch in name):
        return mac
    return f"{_clip(name, NAME_MAX)} ({mac})"


def _limit(minutes: int) -> str:
    """The watch time as the owner picked it: 15 → "15-minute", 60 → "1-hour"."""
    return f"{minutes // 60}-hour" if minutes % 60 == 0 else f"{minutes}-minute"


def _away(minutes: int) -> str:
    """Time away as a reader says it: "119 minutes", "3 hours 5 minutes", "3 days"."""
    if minutes < 120:
        parts = [(minutes, "minute")]
    elif minutes < 48 * 60:
        parts = [(minutes // 60, "hour"), (minutes % 60, "minute")]
    else:
        parts = [(minutes // 1440, "day"), (minutes % 1440 // 60, "hour")]
    return " ".join(f"{n:,} {unit}{'' if n == 1 else 's'}" for n, unit in parts if n)


def watch_item(entry: dict) -> dict | None:
    """A device_offline or device_online entry as a queued item; None when its data has the
    wrong shape (a hand-edited journal), so one bad line can't fail every poll."""
    # the dispatcher imports this module, so its helpers are imported when first needed
    from services.notification_dispatcher import EVENT_LINE_CHARS, _short_time, _when

    kind, data = entry.get("type"), entry.get("data")
    if kind not in _SEVERITY or not isinstance(data, dict):
        return None
    times = ("seen_at",) if kind == OFFLINE else ("seen_at", "back_at")
    name = data.get("name")
    if (
        not _positive(data.get("after_min"))
        or not (name is None or isinstance(name, str))
        or not all(isinstance(data.get(t), str) and _when(data[t]) for t in times)
        or (kind == ONLINE and not _positive(data.get("away_min")))
    ):
        return None
    try:
        mac = strict_mac(data.get("mac"))
    except ValueError:
        return None
    label = _label(name, mac)
    if kind == OFFLINE:
        title = f"Offline: {label}"
        line = (
            f"{label}: no sighting since {_short_time(data['seen_at'])}, "
            f"longer than its {_limit(data['after_min'])} limit"
        )
    else:
        title = f"Back online: {label}"
        line = (
            f"{label}: seen again at {_short_time(data['back_at'])}, "
            f"{_away(data['away_min'])} after the last confirmed sighting"
        )
    return {
        "sig": f"event:{entry.get('id')}",
        "event": EVENT,
        "severity": _SEVERITY[kind],
        "title": title,
        "line": _clip(line, EVENT_LINE_CHARS),
        "count": 1,
        "attempts": 0,
        "watch_mac": mac,
    }


def without_device(queues: dict, mac: str) -> dict:
    """Every channel's event queue without its watch item for `mac`, before a newer one is routed:
    so a channel that takes only high items can't keep an "Offline" whose "Back online" went
    elsewhere (round 4 #6), and no message reports one device's transitions out of order."""
    return {
        cid: {
            **q,
            "events": [e for e in q.get("events") or [] if e.get("watch_mac") != mac],
        }
        for cid, q in queues.items()
    }
