"""
NetTap alert notifications without a browser (NET-224).

Every minute the new Suricata alerts, grouped as the Alerts page groups them (get_smart_alerts),
go to the channels the routing rules pick. Each channel gets at most one message a poll: a digest
of the alerts that are new for it. A channel whose send fails keeps those alerts and tries again
after a back-off, so a short outage loses nothing; the state survives restarts.

A channel gets DAILY_BUDGET messages a UTC day (failed sends don't count); past it, one digest an
hour until midnight UTC, worst alerts first, so a flood can't hold a critical alert back.

New for a channel means: never handled, more severe than when it was, or a newer occurrence once
the hour's cooldown is over. Re-reading the same occurrences (the poll windows overlap, and a
failed query keeps the cursor) never sends them again.

Other events (NET-319: new devices; offline, data cap and report in later slices) come from the
event journal, the commit point. Each poll admits what is new there into per-channel event
queues kept in their own file, notification-events.json (the pre-NET-319 dispatcher rewrites
the alert state, so after a rollback it would erase queues kept there). An event rides in the
channel's next message with its alerts, under the same budget, and is never given up: it stays
queued until a send works. A crash between a send and the saves repeats that message; nothing
committed to the journal is lost.

Quiet hours (NET-330): inside the owner's overnight window only critical alerts go (when the
owner lets them through); everything else stays queued, flagged "held", and the first send after
the window carries it all under one heading. The clock decides at each send decision, so nothing
per window is saved (plans/2026-11-20-f8-quiet-hours.md).
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from services.capture_config import write_file_atomic
from services.notification_hub import (
    SEVERITY_LEVELS,
    NotificationHub,
    _clip,
    body_limit,
)

if TYPE_CHECKING:
    from services.event_journal import EventJournal
    from services.quiet_hours import Hold

logger = logging.getLogger("nettap.services.notification_dispatcher")

POLL_S = 60
OVERLAP = timedelta(minutes=5)  # Logstash indexes some alerts late
MAX_CATCH_UP = timedelta(hours=1)  # after an outage, older alerts are history, not news
COOLDOWN = timedelta(hours=1)  # a signature's newer occurrences wait this long
# done records outlive the longest window (catch-up + overlap), so a re-read is always recognised
KEEP_DONE = timedelta(hours=2)
RETRY_AFTER = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15))
MAX_PENDING = 50
DIGEST_LINES = 10
# Messages a channel gets per UTC day, failed sends not counted (a server outage mustn't use up
# the day): alerts an attacker can trip must not use up Gmail's ~500 a day or Pushover's ~330 (review M2)
DAILY_BUDGET = 100
# Past the budget, one digest this often, so a flood can't hold a critical alert back (security delta D3)
SLOW_EVERY = timedelta(hours=1)
_EMPTY: dict = {"done": {}, "pending": [], "retry_at": None}
# NET-319: journal events, read in pages and queued per channel
INTAKE = 200  # journal entries admitted a poll; a bigger backlog takes the next polls
MAX_EVENTS = (
    500  # queued events a channel; older ones become a count, never silently lost
)
REPLAY = timedelta(hours=24)  # a lost event state re-reads this much of the journal
_NO_EVENTS: dict = {"events": [], "overflow": 0}
# NET-339: every journal event's line fits a message on its own (Codex r4 #3)
EVENT_LINE_CHARS = 300
# a title's longest, where a service clips: body_limit's Telegram reserve counts on it
TITLE_CHARS = 256
DATA_CAP_LINE_CHARS = 140
# data cap warnings a channel queue keeps; past it the oldest held one goes (plan §4.3)
MAX_DATA_CAP = 12
_CAP_SEVERITY = {"80": 3, "100": 2, "projected": 3}
_CAP_TITLE = {
    "80": "Data cap: 80% used",
    "100": "Data cap reached",
    "projected": "Data cap: on track to go over",
}
# NET-330: the heading of the first send after quiet hours, and its line when the queue was full
QUIET_PREAMBLE = "Notifications held by your quiet hours setting:\n\n"
QUIET_FULL = (
    f"Quiet hours keep at most {MAX_PENDING} alert types; see the Alerts page for all."
)
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _iso(t: datetime) -> str:
    return t.isoformat()


def _when(raw: Any) -> datetime | None:
    """An ISO time as an aware datetime; None when missing or unreadable."""
    try:
        t = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _next_digest_at(now: datetime) -> datetime:
    """Past the budget, when the next digest may go: an hour on, but never past midnight UTC,
    when the budget renews."""
    midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return min(now + SLOW_EVERY, midnight)


def _worst_first(item: dict) -> tuple[int, int]:
    return item["severity"], -item["count"]


def merge_groups(groups: list[dict]) -> list[dict]:
    """Smart-alert groups (signature, source, destination) merged per signature, worst first."""
    items: dict[str, dict] = {}
    for g in groups:
        severity = g.get("severity")
        if severity not in SEVERITY_LEVELS:
            continue  # informational (5) never notifies
        signature = g.get("signature") or "Unknown"
        sig = str(g.get("signature_id") or signature)
        count = g.get("count") or 0
        last_seen = g.get("last_seen") or ""
        old = items.get(sig)
        if old is None:
            pair = f"{g.get('source_ip') or '?'} → {g.get('destination_ip') or '?'}"
            items[sig] = {
                "sig": sig,
                "signature": signature,
                "severity": severity,
                "count": count,
                "pairs": 1,
                "example": pair,
                "last_seen": last_seen,
            }
        else:
            newest = max(
                old["last_seen"],
                last_seen,
                key=lambda t: _when(t) or datetime.min.replace(tzinfo=timezone.utc),
            )
            items[sig] = {
                **old,
                "severity": min(old["severity"], severity),
                "count": old["count"] + count,
                "pairs": old["pairs"] + 1,
                "last_seen": newest,
            }
    return sorted(items.values(), key=_worst_first)


def is_new(done: dict, item: dict, now: datetime) -> bool:
    """Whether a channel should hear about `item`, given what it already handled."""
    last = done.get(item["sig"])
    if last is None or item["severity"] < last.get("severity", 5):
        return True  # never handled, or escalated
    seen, before = _when(item.get("last_seen")), _when(last.get("last_seen"))
    newer = seen is not None and (before is None or seen > before)
    handled_at = _when(last.get("at"))
    return newer and (handled_at is None or now - handled_at > COOLDOWN)


# OLD CODE START — NET-319: alerts only; journal events (with their own title and line) join them
# def digest(items: list[dict]) -> tuple[str, str, int]:
#     """(title, body, worst severity) of one channel's message."""
#     worst = min(i["severity"] for i in items)
#     level = SEVERITY_LEVELS[worst]
#     if len(items) == 1:
#         title = f"{level.capitalize()} alert: {items[0]['signature']}"
#     else:
#         title = f"{len(items)} new alerts (worst: {level})"
#     lines = []
#     for i in items[:DIGEST_LINES]:
#         where = (
#             i["example"]
#             if i["pairs"] == 1
#             else f"{i['example']} and {i['pairs'] - 1} more"
#         )
#         events = f"{i['count']} event{'' if i['count'] == 1 else 's'}"
#         lines.append(
#             f"- [{SEVERITY_LEVELS[i['severity']]}] {i['signature']}: {events}, {where}"
#         )
#     if len(items) > DIGEST_LINES:
#         lines.append(f"and {len(items) - DIGEST_LINES} more")
#     lines.extend(["", "Open NetTap's Alerts page for details."])
#     return title, "\n".join(lines), worst
# OLD CODE END
def _digest_line(i: dict) -> str:
    level = SEVERITY_LEVELS[i["severity"]]
    if "line" in i:  # a journal event says itself
        return f"- [{level}] {i['line']}"
    where = (
        i["example"] if i["pairs"] == 1 else f"{i['example']} and {i['pairs'] - 1} more"
    )
    events = f"{i['count']} event{'' if i['count'] == 1 else 's'}"
    return f"- [{level}] {i['signature']}: {events}, {where}"


# OLD CODE START — NET-339: rendered the first 10 lines whatever their length, and a service's
# clip could cut one; the caller couldn't tell which events were shown (Codex r2 #1, r4 #2)
# def digest(items: list[dict], overflow: int = 0) -> tuple[str, str, int]:
#     """(title, body, worst severity) of one channel's message.
#
#     All alerts: the wording alerts have always had. With journal events: their own title when
#     alone, else "N new notifications"; `overflow` events past the queue's cap are counted.
#     """
#     worst = min(i["severity"] for i in items)
#     level = SEVERITY_LEVELS[worst]
#     alerts_only = not overflow and all("line" not in i for i in items)
#     if len(items) == 1 and not overflow:
#         title = (
#             f"{level.capitalize()} alert: {items[0]['signature']}"
#             if alerts_only
#             else items[0]["title"]
#         )
#     elif alerts_only:
#         title = f"{len(items)} new alerts (worst: {level})"
#     else:
#         title = f"{len(items) + overflow} new notifications (worst: {level})"
#     lines = [_digest_line(i) for i in items[:DIGEST_LINES]]
#     if len(items) > DIGEST_LINES:
#         lines.append(f"and {len(items) - DIGEST_LINES} more")
#     if overflow:
#         lines.append(f"and {overflow} more events not listed; see NetTap")
#     footer = (
#         "Open NetTap's Alerts page for details."
#         if alerts_only
#         else "Open NetTap for details."
#     )
#     lines.extend(["", footer])
#     return title, "\n".join(lines), worst
# OLD CODE END
def _fit(lines: list[str], room: int | None) -> list[int]:
    """The indexes of the lines that go in, in order: at most DIGEST_LINES, together within
    `room` characters (None: no limit). One that doesn't fit is skipped and the next tried."""
    picked: list[int] = []
    used = 0
    for n, line in enumerate(lines):
        if len(picked) == DIGEST_LINES:
            break
        if room is not None and used + len(line) + 1 > room:
            continue
        picked.append(n)
        used += len(line) + 1  # with its line break
    return picked


def digest(
    items: list[dict],
    overflow: int = 0,
    max_chars: int | None = None,
    extra: tuple[str, ...] = (),
) -> tuple[str, str, int, list[dict]]:
    """(title, body, worst severity, the items it rendered) of one channel's message.

    All alerts: the wording alerts have always had. With journal events: their own title when
    alone, else "N new notifications"; `overflow` events past the queue's cap are counted.
    NET-339: lines go in the given order while the body stays within `max_chars` (the channel's
    body_limit; None for no limit), so a service's clip never cuts a line that was rendered.
    NET-330: `extra` lines go before the footer and are measured with it.
    """
    worst = min(i["severity"] for i in items)
    level = SEVERITY_LEVELS[worst]
    alerts_only = not overflow and all("line" not in i for i in items)
    if len(items) == 1 and not overflow:
        title = (
            f"{level.capitalize()} alert: {items[0]['signature']}"
            if alerts_only
            else items[0]["title"]
        )
    elif alerts_only:
        title = f"{len(items)} new alerts (worst: {level})"
    else:
        title = f"{len(items) + overflow} new notifications (worst: {level})"
    footer = (
        "Open NetTap's Alerts page for details."
        if alerts_only
        else "Open NetTap for details."
    )
    # OLD CODE: tail = [*([f"and {overflow} more …"] if overflow else []), "", footer] (NET-330: + extra)
    tail = [
        *([f"and {overflow} more events not listed; see NetTap"] if overflow else []),
        *extra,
        "",
        footer,
    ]
    room = None
    if max_chars is not None:
        title = _clip(title, TITLE_CHARS)
        # the "and N more" line is counted at its longest
        room = max_chars - len("\n".join([f"and {len(items)} more", *tail]))
    lines = [_digest_line(i) for i in items]
    picked = _fit(lines, room)
    more = len(items) - len(picked)
    body = [lines[n] for n in picked] + ([f"and {more} more"] if more else []) + tail
    return title, "\n".join(body), worst, [items[n] for n in picked]


def _short_time(raw: Any) -> str:
    t = _when(raw)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if t else "?"


def _gb(n: int) -> str:
    """Decimal GB, one decimal place (NET-166)."""
    return f"{n / 1e9:,.1f} GB"


def _cap_gb(n: int) -> str:
    """A cap as the owner typed it: "100 GB", "1.2 GB"."""
    return f"{n / 1e9:,.1f}".removesuffix(".0") + " GB"


def _is_bytes(raw: Any) -> bool:
    return isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0


def _cap_line(key: str, data: dict) -> str:
    month, cap = data.get("month_label") or "this month", _cap_gb(data["cap"])
    if key == "projected":
        return f"On track for {_gb(data['projected'])} in {month}, over your {cap} cap"
    # OLD CODE: line = f"{_gb(data['used'])} of your {cap} cap used in {month} ({data.get('tz')})"
    # (review: rounding half up made an "at least" 82.46 GB read 82.5)
    complete = data.get("complete")
    # an "at least" figure floors to 0.1 GB, so it is never above what was counted
    used = data["used"] if complete else data["used"] // 10**8 * 10**8
    line = f"{_gb(used)} of your {cap} cap used in {month} ({data.get('tz')})"
    if complete:
        return line
    since = data.get("since")
    # "counted since" only for a ledger that started after the month's first day (as the card's
    # usage-words rule); otherwise gaps make it partial
    # OLD CODE: if isinstance(since, str) and since[:7] == data.get("month"): (review: "since 1 Nov")
    month_key = data.get("month")
    if isinstance(since, str) and since[:7] == month_key and since > f"{month_key}-01":
        start = date.fromisoformat(since)
        return f"{line}, at least: counted since {start.day} {start.strftime('%b')}"
    return f"{line}, at least"


def _data_cap_item(entry: dict) -> dict | None:
    """NET-339: a data cap warning; None when its data isn't one (a hand-edited journal)."""
    key, data = entry.get("key"), entry.get("data") or {}
    if not isinstance(
        data, dict
    ):  # review: a list or string here raised, failing every poll
        return None
    figures = ("cap", "projected" if key == "projected" else "used")
    if key not in _CAP_SEVERITY or not all(_is_bytes(data.get(f)) for f in figures):
        return None
    try:
        line = _cap_line(key, data)
    except ValueError:  # an unreadable since
        return None
    return {
        "sig": f"event:{entry.get('id')}",
        "event": "data_cap",
        "severity": _CAP_SEVERITY[key],
        "title": _CAP_TITLE[key],
        "line": _clip(line, DATA_CAP_LINE_CHARS),
        "count": 1,
        "attempts": 0,
        # what the dispatcher checks against the cap in force before sending (Codex r4 #1)
        "month": data.get("month"),
        "cap": data["cap"],
    }


def event_item(entry: dict) -> dict | None:
    """A journal entry as a queued notification; None for a type nothing sends yet."""
    # OLD CODE: if entry.get("type") != "new_device": (NET-339: data cap warnings too)
    if entry.get("type") == "data_cap":
        return _data_cap_item(entry)
    if entry.get("type") != "new_device":
        return None
    data = entry.get("data") or {}
    mac = entry.get("key") or "?"
    vendor, ip = data.get("vendor"), data.get("ip")
    line = (
        f"New device {mac}"
        + (f" ({vendor})" if vendor else "")
        + (f" at {ip}" if ip else "")
        + f", first seen {_short_time(entry.get('observed_at'))}"
    )
    return {
        "sig": f"event:{entry.get('id')}",
        "event": "new_device",
        "severity": 3,
        "title": f"New device: {vendor or mac}",
        # OLD CODE: "line": line, (NET-339: a long vendor name could outgrow a whole message)
        "line": _clip(line, EVENT_LINE_CHARS),
        "count": 1,
        "attempts": 0,
    }


def _trim(queue: list[dict]) -> tuple[list[dict], int]:
    """The queue within MAX_EVENTS, oldest out first, and how many went. Never a data cap
    warning: cap_queue bounds those, and dropping one would lose it for good."""
    over = max(0, len(queue) - MAX_EVENTS)
    gone = set([n for n, e in enumerate(queue) if e.get("event") != "data_cap"][:over])
    return [e for n, e in enumerate(queue) if n not in gone], len(gone)


def _cap_state(e: dict, now_cap: tuple[str, int] | None) -> str:
    """ "send", "hold" or "drop" for one queued item under the cap in force (None: unknown)."""
    if e.get("event") != "data_cap":
        return "send"
    if now_cap is None:
        return "hold"
    month, cap = now_cap
    if str(e.get("month")) < month:
        return "drop"  # that month is over (§3.5)
    return "send" if (e.get("month"), e.get("cap")) == (month, cap) else "hold"


def cap_queue(
    events: list[dict], now_cap: tuple[str, int] | None, cid: str
) -> tuple[list[dict], list[dict]]:
    """(the queue to keep, what of it may be sent now): NET-339, Codex r4 #1.

    A data cap warning for an earlier month is dropped. One for another cap this month (a cap
    since raised, lowered or removed) is held: sent if the owner returns to that cap this month,
    never for a cap they left. Past MAX_DATA_CAP the oldest held ones go.
    """
    states = [_cap_state(e, now_cap) for e in events]
    held = [n for n, s in enumerate(states) if s == "hold"]
    kept_caps = sum(1 for e in events if e.get("event") == "data_cap") - states.count(
        "drop"
    )
    # only held ones: the current cap has at most 3 warnings a month
    evicted = set(held[: max(0, kept_caps - MAX_DATA_CAP)])
    if states.count("drop") or evicted:
        logger.warning(
            "Data cap warnings for channel %s: dropped %d for a month that is over and %d "
            "held for a cap no longer set",
            cid,
            states.count("drop"),
            len(evicted),
        )
    kept = [n for n, s in enumerate(states) if s != "drop" and n not in evicted]
    return [events[n] for n in kept], [events[n] for n in kept if states[n] == "send"]


# OLD CODE START — security review: every unshown event waited for the next message, so a burst
# of 500 new MACs became 50 messages and spent the channel's day (it used to be one "and N more")
# def _unshown(events: list[dict], rendered: list[dict]) -> list[dict]:
#     """The queued events a sent message didn't show: they go in the next one (Codex r2 #1)."""
#     shown = {i.get("sig") for i in rendered}
#     return [e for e in events if e.get("sig") not in shown]
# OLD CODE END
# OLD CODE START — NET-330: replaced by _after_send, which also keeps quiet-held events
# def _unshown(events: list[dict], rendered: list[dict]) -> list[dict]:
#     """The data cap warnings a sent message didn't show: they go in the next one (Codex r2 #1).
#     Other events it didn't show were counted in its "and N more", as before NET-339."""
#     shown = {i.get("sig") for i in rendered}
#     return [
#         e for e in events if e.get("event") == "data_cap" and e.get("sig") not in shown
#     ]
# OLD CODE END


def _record(items: list[dict], now: datetime, ok: bool) -> dict:
    return {
        i["sig"]: {
            "at": _iso(now),
            "severity": i["severity"],
            "last_seen": i.get("last_seen"),
            "ok": ok,
        }
        for i in items
    }


# --- quiet hours (NET-330) ---------------------------------------------------


def _due(item: dict, hold: "Hold | None") -> bool:
    """Whether `item` may go now: outside quiet hours anything; inside, a critical alert when the
    owner lets them through (only an alert can be critical; events have an "event" key)."""
    if hold is None:
        return True
    return hold.critical_through and "event" not in item and item.get("severity") == 1


def _merge(old: dict | None, new: dict) -> dict:
    """A fresh copy of a queued alert: it keeps the queued attempts and held flag. If the queued
    copy was worse, that whole observation stays (severity, example, count together) and only
    last_seen moves on, so a critical held overnight isn't reported as the medium that followed."""
    if old is None:
        return new
    kept = {
        "attempts": old.get("attempts", 0),
        **({"held": True} if old.get("held") else {}),
    }
    newest = max(
        old.get("last_seen") or "",
        new.get("last_seen") or "",
        key=lambda t: _when(t) or _EPOCH,
    )
    # OLD CODE: {**i, "attempts": by_sig.get(i["sig"], i)["attempts"]} (a milder copy downgraded it)
    base = old if old.get("severity", 5) < new["severity"] else new
    return {**base, **kept, "last_seen": newest}


def _rank(item: dict, hold: "Hold | None") -> tuple:
    """The 50-alert cut's order: criticals that may go now, then worst first as before, a held
    item ahead of a fresh one of the same severity. So a release keeps what was held over equally
    mild arrivals, which come back on the next poll's overlapping read, and a worse fresh alert
    still beats the mildest held one (its 5-minute overlap ends; the held one is on the Alerts
    page, and the release's full line says so)."""
    # OLD CODE START — security review: held items ranked as a group ahead of every fresh
    # non-critical alert, so after a full night a fresh high alert was cut while the release was
    # blocked, until it left the query's overlap
    # # OLD CODE: if hold is not None and _due(item, hold): (ponytail review: after a window a fresh
    # # critical ranked behind 50 held alerts, and a blocked release cut it until it left the overlap)
    # if _due(item, hold) and item.get("severity") == 1:
    #     group = 0
    # elif item.get("held"):
    #     group = 1
    # else:
    #     group = 2
    # return (group, *_worst_first(item))
    # OLD CODE END
    urgent = _due(item, hold) and item.get("severity") == 1
    severity, fewer = _worst_first(item)
    return (not urgent, severity, not item.get("held"), fewer)


def _cap_first(item: dict) -> tuple:
    """A release's order: data cap warnings first, so none is left past the cut for a second send."""
    return (item.get("event") != "data_cap", *_worst_first(item))


def _after_send(
    events: list[dict], due: list[dict], rendered: list[dict]
) -> list[dict]:
    """The event queue after a send that worked: what it didn't carry stays (held by quiet hours
    or kept by cap_queue), and so do the due data cap warnings it couldn't show. Other due events
    it didn't show were counted in its "and N more" (NET-339's rule)."""
    shown = {i.get("sig") for i in rendered}
    sent = {
        e.get("sig")
        for e in due
        if e.get("event") != "data_cap" or e.get("sig") in shown
    }
    return [e for e in events if e.get("sig") not in sent]


class AlertDispatcher:
    """Sends new alerts to the channels the routing rules pick, from a background task."""

    def __init__(
        self,
        hub: NotificationHub,
        client: Any,
        lan_cidrs: Callable[[], list[str]],
        state_path: str,
        journal: "EventJournal | None" = None,
        data_cap_now: Callable[[], tuple[str, int]] | None = None,
        quiet: "Callable[[datetime], Hold | None] | None" = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._hub = hub
        # NET-330: the quiet hours window at a time (quiet_hours.source), asked at each send
        # decision with a fresh clock reading; None holds nothing
        self._quiet = quiet
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        # NET-339: (owner month "YYYY-MM", cap bytes) at send time; None sends cap warnings as queued
        self._data_cap_now = data_cap_now
        self._client = client
        self._lan_cidrs = lan_cidrs
        self._state_path = Path(state_path)
        self._state = self._load()
        # NET-319: journal events, with their own state file next to the alert state
        self._journal = journal
        self._events_path = self._state_path.with_name("notification-events.json")
        self._replay_floor: datetime | None = None
        self._events = self._load_events()
        # the journal_seq last saved: compaction keeps everything after it
        self.committed_seq: int | None = (
            self._events["journal_seq"] if self._events_path.exists() else None
        )

    # --- state -------------------------------------------------------------

    def _load(self) -> dict:
        try:
            data = json.loads(self._state_path.read_text())
            if isinstance(data, dict) and isinstance(data.get("channels"), dict):
                return data
            logger.warning(
                "Notification dispatch state has the wrong shape, starting fresh"
            )
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            logger.warning(
                "Notification dispatch state unreadable, starting fresh (%s)", exc
            )
        return {"cursor": None, "channels": {}}

    def _save(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            write_file_atomic(
                str(self._state_path), json.dumps(self._state), mode=0o600
            )
        except OSError as exc:
            logger.warning("Couldn't save the notification dispatch state: %s", exc)

    def _load_events(self) -> dict:
        """The event queues and journal cursor. Without them: a first start reads the journal
        from its beginning; a lost file (the journal already existed) re-reads 24 hours."""
        try:
            data = json.loads(self._events_path.read_text())
            if (
                isinstance(data, dict)
                and isinstance(data.get("journal_seq"), int)
                and isinstance(data.get("channels"), dict)
            ):
                return data
            logger.warning("Notification event state has the wrong shape")
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            logger.warning("Notification event state unreadable (%s)", exc)
        if self._journal is not None and self._journal.existed_at_start:
            self._replay_floor = datetime.now(timezone.utc) - REPLAY
            logger.warning(
                "Notification event state missing: re-reading the last %d hours of events, "
                "which may repeat",
                REPLAY.total_seconds() // 3600,
            )
        return {"journal_seq": 0, "channels": {}}

    def _save_events(self) -> bool:
        try:
            write_file_atomic(
                str(self._events_path), json.dumps(self._events), mode=0o600
            )
        except OSError as exc:
            logger.warning("Couldn't save the notification event state: %s", exc)
            return False
        return True

    async def _take_events(self, queues: dict, now: datetime) -> tuple[dict, int]:
        """The channels' event queues with this poll's journal page admitted, and the seq read up to."""
        seq = self._events["journal_seq"]
        if self._journal is None:
            return queues, seq
        if self._journal.last_seq < seq:
            # the journal restarted its numbering (deleted or unreadable): `seq > N` would skip
            # the next N events, so read it from the start, a day back, as after a lost state
            logger.warning(
                "Notification events: the journal ends at %d, before the saved %d; re-reading it",
                self._journal.last_seq,
                seq,
            )
            seq = 0
            self._replay_floor = now - REPLAY
        try:
            entries = await asyncio.to_thread(self._journal.after, seq, INTAKE)
        except OSError as exc:
            logger.warning(
                "Notification events: the journal read failed, will retry (%s)", exc
            )
            return queues, seq
        for entry in entries:
            item = event_item(entry)
            recorded = _when(entry.get("recorded_at"))
            if item is None or (
                self._replay_floor and recorded and recorded < self._replay_floor
            ):
                continue
            for cid in self._hub.channels_for(item["event"], item["severity"]):
                old = queues.get(cid, _NO_EVENTS)
                # OLD CODE START — NET-339: the oldest went first, a data cap warning too
                # queue = [*old.get("events", []), item]
                # over = max(0, len(queue) - MAX_EVENTS)
                # queues = {
                #     **queues,
                #     cid: {
                #         "events": queue[over:],
                #         "overflow": old.get("overflow", 0) + over,
                #     },
                # }
                # OLD CODE END
                queue, over = _trim([*old.get("events", []), item])
                queues = {
                    **queues,
                    cid: {"events": queue, "overflow": old.get("overflow", 0) + over},
                }
        return queues, entries[-1]["seq"] if entries else seq

    # --- one poll ----------------------------------------------------------

    def compact_journal(self, _deadline: float) -> dict:
        """The journal-compact job: drops only what this dispatcher has saved as taken."""
        if self._journal is None:
            return {"dropped": 0}
        dropped = self._journal.compact(datetime.now(timezone.utc), self.committed_seq)
        return {"dropped": dropped}

    def _cap_now(self) -> tuple[str, int] | None:
        """(owner month, cap) now; None holds every cap warning, so alerts still go out."""
        try:
            return self._data_cap_now()
        except Exception as exc:
            logger.warning(
                "Data cap warnings held: the current cap can't be read (%s)", exc
            )
            return None

    def _hold_now(self) -> "Hold | None":
        """The quiet hours window holding now, or None. Fails open: a message at night beats a
        held critical alert."""
        if self._quiet is None:
            return None
        try:
            return self._quiet(self._clock())
        except Exception as exc:
            logger.warning(
                "Quiet hours can't be read, so notifications go as usual: %s", exc
            )
            return None

    def _routed(self, severity: int) -> set[str]:
        return set(self._hub.channels_for("alert", severity))

    async def _new_items(self, now: datetime, waiting: bool) -> list[dict] | None:
        """This window's alerts per signature; [] when nobody would hear them; None on failure."""
        if not waiting and not any(self._routed(sev) for sev in SEVERITY_LEVELS):
            return []
        cursor = _when(self._state.get("cursor")) or now - timedelta(seconds=POLL_S)
        start = max(cursor, now - MAX_CATCH_UP) - OVERLAP
        from services.alert_intelligence import get_smart_alerts

        try:
            groups = await asyncio.to_thread(
                get_smart_alerts,
                self._client,
                _iso(start),
                _iso(now),
                None,
                False,
                None,
                lan_cidrs=self._lan_cidrs(),
            )
        except Exception as exc:
            logger.warning(
                "Alert notifications: the alert query failed, will retry (%s)", exc
            )
            return None
        return merge_groups(groups)

    async def poll_once(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        live = {ch["id"] for ch in self._hub.get_channels()}
        # a deleted channel's queue goes with it
        old = {
            cid: st
            for cid, st in self._state.get("channels", {}).items()
            if cid in live and isinstance(st, dict)
        }
        items = await self._new_items(
            now, any(st.get("pending") for st in old.values())
        )
        # NET-319: this poll's journal events join their channels' queues
        queues, seq = await self._take_events(
            {
                cid: st
                for cid, st in self._events.get("channels", {}).items()
                if cid in live and isinstance(st, dict)
            },
            now,
        )
        targets = {cid for i in items or [] for cid in self._routed(i["severity"])}
        targets |= {cid for cid, st in old.items() if st.get("pending")}
        # OLD CODE: targets = sorted(targets) (NET-319: channels with queued events too)
        targets |= {
            cid for cid, q in queues.items() if q.get("events") or q.get("overflow")
        }
        targets = sorted(targets)
        # channels at once: a slow mail server never holds up another channel
        # OLD CODE START — NET-319: _deliver also takes and returns the channel's event queue
        # states = await asyncio.gather(
        #     *(
        #         self._deliver(cid, old.get(cid, _EMPTY), items or [], now)
        #         for cid in targets
        #     )
        # )
        # OLD CODE END
        results = await asyncio.gather(
            *(
                self._deliver(
                    cid,
                    old.get(cid, _EMPTY),
                    items or [],
                    now,
                    queues.get(cid, _NO_EVENTS),
                )
                for cid in targets
            )
        )
        states = [state for state, _ in results]
        self._state = {
            # a failed query keeps the cursor, so the next poll reads this window too
            "cursor": self._state.get("cursor") if items is None else _iso(now),
            "channels": {**old, **dict(zip(targets, states))},
        }
        self._save()
        if self._journal is None:
            return
        # after the alert state: a crash between the two saves repeats events, never loses them
        merged = {**queues, **{cid: q for cid, (_, q) in zip(targets, results)}}
        self._events = {
            "journal_seq": seq,
            "channels": {
                cid: q
                for cid, q in merged.items()
                if q.get("events") or q.get("overflow")
            },
        }
        if self._save_events():
            self.committed_seq = seq

    # OLD CODE START — NET-319: alerts only, returning the alert state
    # async def _deliver(
    #     self, cid: str, st: dict, items: list[dict], now: datetime
    # ) -> dict:
    # OLD CODE END
    async def _deliver(
        self,
        cid: str,
        st: dict,
        items: list[dict],
        now: datetime,
        ev: dict = _NO_EVENTS,
    ) -> tuple[dict, dict]:
        """The channel's next (alert state, event queue) after sending it what is new for it,
        or queueing it. Events ride in the same message as alerts and are never given up."""
        # a rule turned off since the event was queued takes it out, as for alerts
        events = [
            e
            for e in ev.get("events") or []
            if cid in self._hub.channels_for(e.get("event", ""), e.get("severity", 3))
        ]
        # NET-339: `events` stays queued; only `offered` may go now (held cap warnings wait)
        offered = events
        if self._data_cap_now and any(e.get("event") == "data_cap" for e in events):
            events, offered = cap_queue(events, self._cap_now(), cid)
        overflow = ev.get("overflow", 0) if events else 0
        # NET-330: inside quiet hours no event goes (none is critical); held ones stay queued,
        # flagged, for the release. The window is read now, after the slow reads (Codex r1 #6)
        hold = self._hold_now()
        due_events = [e for e in offered if _due(e, hold)]
        # every queued event, also one cap_queue keeps for another cap: it waited the night too
        held_sigs = {e.get("sig") for e in events if not _due(e, hold)}
        # OLD CODE: events = [{**e, "held": True} if e.get("sig") in held_sigs else e for e in events]
        # (Python review: after the window, a cap warning kept for another cap kept its flag, so a
        # send days later carried the quiet hours heading; outside a window only what goes keeps it)
        on_offer = {e.get("sig") for e in offered}
        events = [
            {**e, "held": True}
            if e.get("sig") in held_sigs
            else {k: v for k, v in e.items() if k != "held"}
            if hold is None and e.get("sig") not in on_offer
            else e
            for e in events
        ]
        done = {
            sig: v
            for sig, v in (st.get("done") or {}).items()
            if (at := _when(v.get("at"))) and now - at <= KEEP_DONE
        }
        routed = {sev: cid in self._routed(sev) for sev in SEVERITY_LEVELS}
        fresh = [
            {**i, "attempts": 0}
            for i in items
            if routed[i["severity"]] and is_new(done, i, now)
        ]
        queued = [i for i in st.get("pending") or [] if routed.get(i.get("severity"))]
        by_sig = {i["sig"]: i for i in queued}
        # OLD CODE START — NET-330: a milder fresh copy downgraded a queued critical (review r4 #3)
        # # a fresh item replaces its queued copy (newer figures) but keeps the queued attempts
        # by_sig.update(
        #     {
        #         i["sig"]: {**i, "attempts": by_sig.get(i["sig"], i)["attempts"]}
        #         for i in fresh
        #     }
        # )
        # OLD CODE END
        # a fresh item replaces its queued copy (newer figures), keeping the queued attempts and
        # held flag, and the queued observation when that was worse
        by_sig.update({i["sig"]: _merge(by_sig.get(i["sig"]), i) for i in fresh})
        # OLD CODE START — review M2: no daily budget, so a channel could get a digest every minute
        # candidates = sorted(by_sig.values(), key=_worst_first)[:MAX_PENDING]
        # retry_at = _when(st.get("retry_at")) if st.get("retry_at") else None
        # if not candidates or (retry_at and retry_at > now):
        #     return {
        #         "done": done,
        #         "pending": candidates,
        #         "retry_at": st.get("retry_at") if candidates else None,
        #     }
        #
        # title, body, worst = digest(candidates)
        # if await self._hub.send(cid, title, body, worst):
        #     return {
        #         "done": {**done, **_record(candidates, now, True)},
        #         "pending": [],
        #         "retry_at": None,
        #     }
        #
        # tried = [{**i, "attempts": i["attempts"] + 1} for i in candidates]
        # kept = [i for i in tried if i["attempts"] <= len(RETRY_AFTER)]
        # gave_up = [i for i in tried if i["attempts"] > len(RETRY_AFTER)]
        # if gave_up:
        #     logger.warning(
        #         "Alert notifications: gave up on %d alert(s) for channel %s after %d failed sends",
        #         len(gave_up),
        #         cid,
        #         len(RETRY_AFTER) + 1,
        #     )
        # # the item with the fewest tries sets the pace, so a new alert keeps its quick retry
        # delay = RETRY_AFTER[min(i["attempts"] for i in kept) - 1] if kept else None
        # return {
        #     # given-up items are recorded too, so re-reading the same alerts never restarts them
        #     "done": {**done, **_record(gave_up, now, False)},
        #     "pending": kept,
        #     "retry_at": _iso(now + delay) if delay else None,
        # }
        # OLD CODE END
        # OLD CODE: candidates = sorted(by_sig.values(), key=_worst_first)[:MAX_PENDING]
        # (NET-330: held items are flagged, and the cut keeps them ahead of fresh arrivals)
        kept = sorted(
            [i if _due(i, hold) else {**i, "held": True} for i in by_sig.values()],
            key=lambda i: _rank(i, hold),
        )[:MAX_PENDING]
        candidates = [i for i in kept if _due(i, hold)]
        held_alerts = [i for i in kept if not _due(i, hold)]
        day = now.date().isoformat()
        # OLD CODE START — security delta D3: past the budget nothing went out until midnight, so a flood an attacker trips held a critical alert back
        # today = {
        #     "day": day,
        #     "sent": st.get("sent", 0) if st.get("day") == day else 0,
        #     "held": st.get("held", 0) if st.get("day") == day else 0,
        # }
        # retry_at = _when(st.get("retry_at")) if st.get("retry_at") else None
        # if not candidates or (retry_at and retry_at > now):
        #     return {
        #         "done": done,
        #         "pending": candidates,
        #         "retry_at": st.get("retry_at") if candidates else None,
        #         **today,
        #     }
        #
        # if today["sent"] >= DAILY_BUDGET:
        #     # handled, not sent: they're on the Alerts page, and tomorrow doesn't bring them back
        #     held = today["held"] + len(candidates)
        #     if not today["held"]:
        #         logger.warning(
        #             "Alert notifications: channel %s reached its daily limit of %d messages",
        #             cid,
        #             DAILY_BUDGET,
        #         )
        #     self._hub.record_held(
        #         cid,
        #         f"Daily limit of {DAILY_BUDGET} messages reached: {held} alert"
        #         f"{'' if held == 1 else 's'} not sent today (UTC); they're on the Alerts page",
        #     )
        #     return {
        #         "done": {**done, **_record(candidates, now, False)},
        #         "pending": [],
        #         "retry_at": None,
        #         **today,
        #         "held": held,
        #     }
        # OLD CODE END
        today = {"day": day, "sent": st.get("sent", 0) if st.get("day") == day else 0}
        slow = today["sent"] >= DAILY_BUDGET
        retry_at = _when(st.get("retry_at")) if st.get("retry_at") else None
        waiting = {"events": events, "overflow": overflow}
        # OLD CODE: if not candidates or (retry_at and retry_at > now): (NET-319: queued events send too)
        # OLD CODE: if (not candidates and not events) or (retry_at and retry_at > now): (NET-339: held cap warnings don't send)
        # OLD CODE: if (not candidates and not offered) or (retry_at and retry_at > now): (NET-330: quiet-held ones don't either)
        if (not candidates and not due_events) or (retry_at and retry_at > now):
            # the queue waits for the hourly digest; the hub keeps a failed send's error over this
            # OLD CODE: if slow and candidates and not any(i["attempts"] for i in candidates): (security delta: the hub decides, so a given-up queue can't hide a wrong password)
            # OLD CODE: if slow and candidates: (NET-319: queued events wait for the digest too)
            # OLD CODE: if slow and (candidates or events): (NET-339: offered, not held)
            # OLD CODE: if slow and (candidates or offered): (NET-330: due, not quiet-held)
            if slow and (candidates or due_events):
                n = len(candidates)
                # NET-319: queued events are named after the alerts, so alert-only wording is unchanged
                # OLD CODE: others = len(events) + overflow (NET-339)
                # OLD CODE: others = len(offered) + overflow (NET-330)
                others = len(due_events) + overflow
                also = (
                    f" and {others} other event{'' if others == 1 else 's'}"
                    if others
                    else ""
                )
                self._hub.record_held(
                    cid,
                    f"Daily limit of {DAILY_BUDGET} messages reached: until 00:00 UTC, one "
                    f"digest an hour, worst alerts first. {n} alert{'' if n == 1 else 's'}"
                    f"{also} waiting for the next one",
                )
            # OLD CODE START — NET-319: the event queue is returned with the alert state
            # return {
            #     "done": done,
            #     "pending": candidates,
            #     # past the budget the hourly slot holds even with nothing queued
            #     "retry_at": st.get("retry_at") if candidates or slow else None,
            #     **today,
            # }
            # OLD CODE END
            return {
                "done": done,
                # OLD CODE: "pending": candidates, (NET-330: held alerts wait here too)
                "pending": [*candidates, *held_alerts],
                # past the budget the hourly slot holds even with nothing queued
                # OLD CODE: if candidates or events or slow (NET-339: offered, not held)
                # OLD CODE: if candidates or offered or slow (NET-330: a held-only poll cleared a
                # refusal throttle, so a critical at 22:01 retried the refused password; Codex r3 #4)
                "retry_at": st.get("retry_at")
                if candidates or due_events or held_alerts or held_sigs or slow
                else None,
                **today,
            }, waiting

        # OLD CODE START — NET-339: the notice is fitted with the digest, so a clip cuts neither
        # # OLD CODE: title, body, worst = digest(candidates) (NET-319: with the queued events)
        # title, body, worst = digest(
        #     sorted([*candidates, *events], key=_worst_first), overflow
        # )
        # # OLD CODE START — delta review: at the end, Pushover's 1024-character clip dropped the notice
        # # if today["sent"] == DAILY_BUDGET - 1:
        # #     body += (
        # #         f"\n\nThis is the last notification today on this channel (limit "
        # #         f"{DAILY_BUDGET} a day, UTC). Later alerts are on NetTap's Alerts page."
        # #     )
        # # OLD CODE END
        # if today["sent"] == DAILY_BUDGET - 1:
        #     # first, so a service's length clip never drops it
        #     body = (
        #         f"This channel has reached its limit of {DAILY_BUDGET} messages today (UTC). "
        #         "Until 00:00 UTC it gets one digest an hour, worst alerts first.\n\n"
        #         f"{body}"
        #     )
        # OLD CODE END
        # first, so a service's length clip never drops it
        notice = (
            f"This channel has reached its limit of {DAILY_BUDGET} messages today (UTC). "
            "Until 00:00 UTC it gets one digest an hour, worst alerts first.\n\n"
            if today["sent"] == DAILY_BUDGET - 1
            else ""
        )
        limit = body_limit((self._hub.get_channel(cid) or {}).get("type", ""))
        # OLD CODE START — NET-330: quiet hours add a release heading, cap-first order and held items
        # title, body, worst, rendered = digest(
        #     sorted([*candidates, *offered], key=_worst_first),
        #     overflow,
        #     None if limit is None else limit - len(notice),
        # )
        # body = notice + body
        # OLD CODE END
        # the first send after quiet hours carries what they held, under one heading; decided
        # from everything due, before any line is fitted (Codex r4 #1)
        # OLD CODE: release = hold is None and any(i.get("held") for i in [*candidates, *due_events])
        # (security review: held alerts that worse fresh ones cut still make it a release)
        held_total = sum(1 for i in by_sig.values() if i.get("held"))
        release = hold is None and (
            held_total > 0 or any(e.get("held") for e in due_events)
        )
        preamble = QUIET_PREAMBLE if release else ""
        # a full queue of held alerts, or held alerts cut now, left some out: say where they are
        # OLD CODE: full = release and sum(1 for i in candidates if i.get("held")) >= MAX_PENDING
        # (ponytail review: criticals now take slots first, so count the held ones before the cut)
        # OLD CODE: full = release and held_total >= MAX_PENDING (security review: + cut now)
        held_kept = sum(1 for i in candidates if i.get("held"))
        full = release and (held_total >= MAX_PENDING or held_kept < held_total)
        # held events' overflow count waits for the release that shows them
        shown_overflow = overflow if hold is None else 0
        title, body, worst, rendered = digest(
            sorted(
                [*candidates, *due_events], key=_cap_first if release else _worst_first
            ),
            shown_overflow,
            None if limit is None else limit - len(notice) - len(preamble),
            (QUIET_FULL,) if full else (),
        )
        body = notice + preamble + body
        # OLD CODE START — delta review: a failed send used the budget, so a server outage spent the day
        # today = {**today, "sent": today["sent"] + 1}
        # OLD CODE END
        # OLD CODE: if await self._hub.send(cid, title, body, worst): (security delta: a refused send counts)
        outcome = await self._hub.deliver(cid, title, body, worst)
        # partly: the mail went out, so a retry would resend it to the recipients who got it
        # OLD CODE: if outcome == "sent": (rev-security: a partial refusal was retried)
        if outcome in ("sent", "partly"):
            sent = today["sent"] + 1
            if sent == DAILY_BUDGET:
                logger.warning(
                    "Alert notifications: channel %s reached its daily limit of %d messages; "
                    "one digest an hour until 00:00 UTC",
                    cid,
                    DAILY_BUDGET,
                )
            # OLD CODE START — security delta: moved to _next_digest_at, which a refused send uses too
            # # the next UTC day brings a new budget, so the hourly wait never runs past midnight
            # midnight = (now + timedelta(days=1)).replace(
            #     hour=0, minute=0, second=0, microsecond=0
            # )
            # OLD CODE END
            return {
                "done": {**done, **_record(candidates, now, True)},
                # OLD CODE: "pending": [], (NET-330: held alerts wait for the release)
                "pending": held_alerts,
                # OLD CODE: "retry_at": None, (security delta D3: past the budget, one digest an hour)
                "retry_at": _iso(_next_digest_at(now))
                if sent >= DAILY_BUDGET
                else None,
                **today,
                "sent": sent,
                # OLD CODE: }, _NO_EVENTS (NET-339: an event not shown waited for nothing; it stays queued)
                # OLD CODE: }, {"events": _unshown(events, rendered), "overflow": 0}
                # (NET-330: events held by quiet hours stay, and so does a count not yet shown)
            }, {
                "events": _after_send(events, due_events, rendered),
                "overflow": overflow - shown_overflow,
            }

        # The service turned it down: that counts, since a wrong password tried every minute gets
        # the account locked. A send that never reached it doesn't (an outage mustn't use the day)
        if outcome == "refused":
            today = {**today, "sent": today["sent"] + 1}
        tried = [{**i, "attempts": i["attempts"] + 1} for i in candidates]
        kept = [i for i in tried if i["attempts"] <= len(RETRY_AFTER)]
        gave_up = [i for i in tried if i["attempts"] > len(RETRY_AFTER)]
        if gave_up:
            logger.warning(
                "Alert notifications: gave up on %d alert(s) for channel %s after %d failed sends",
                len(gave_up),
                cid,
                len(RETRY_AFTER) + 1,
            )
        # NET-319: events never give up; past the last back-off they retry at its pace
        # OLD CODE: tried_events = [{**e, "attempts": e.get("attempts", 0) + 1} for e in events]
        # (NET-339: a held cap warning wasn't tried, so it keeps its count and its queue place)
        # OLD CODE: offered_sigs = {e.get("sig") for e in offered} (NET-330: quiet-held ones weren't tried)
        offered_sigs = {e.get("sig") for e in due_events}
        queue = [
            {**e, "attempts": e.get("attempts", 0) + 1}
            if e.get("sig") in offered_sigs
            else e
            for e in events
        ]
        tried_events = [e for e in queue if e.get("sig") in offered_sigs]
        # the item with the fewest tries sets the pace, so a new alert keeps its quick retry
        # OLD CODE: delay = RETRY_AFTER[min(i["attempts"] for i in kept) - 1] if kept else None
        paces = [min(i["attempts"], len(RETRY_AFTER)) for i in [*kept, *tried_events]]
        delay = RETRY_AFTER[min(paces) - 1] if paces else None
        # past the budget a refusal waits for the hourly slot, like a digest
        # OLD CODE: if outcome == "refused" and today["sent"] >= DAILY_BUDGET:
        # (NET-319 review: events never give up, so a wrong password would be tried every 15
        # minutes for ever, under the budget; once only events past the back-off are left, a
        # refusal waits for the hourly slot too)
        events_only_past_backoff = (
            not kept
            and tried_events
            and all(e["attempts"] > len(RETRY_AFTER) for e in tried_events)
        )
        if outcome == "refused" and (
            today["sent"] >= DAILY_BUDGET or events_only_past_backoff
        ):
            retry = _next_digest_at(now)
        else:
            retry = now + delay if delay else None
        return {
            # given-up items are recorded too, so re-reading the same alerts never restarts them
            "done": {**done, **_record(gave_up, now, False)},
            # OLD CODE: "pending": kept, (NET-330: held alerts weren't tried; they wait as they were)
            "pending": [*kept, *held_alerts],
            # OLD CODE: "retry_at": _iso(now + delay) if delay else None, (security delta: see retry)
            "retry_at": _iso(retry) if retry else None,
            **today,
            # OLD CODE: }, {"events": tried_events, "overflow": overflow} (NET-339: held ones too)
        }, {"events": queue, "overflow": overflow}

    # --- background task ---------------------------------------------------

    async def ctx(self, _app: Any) -> AsyncIterator[None]:
        """aiohttp cleanup_ctx: one poll a minute for the app's lifetime."""

        async def run() -> None:
            while True:
                await asyncio.sleep(POLL_S)
                try:
                    await self.poll_once()
                except Exception:
                    logger.exception("Alert notification poll failed")

        task = asyncio.create_task(run(), name="alert-notifications")
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
