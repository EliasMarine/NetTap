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
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from services.capture_config import write_file_atomic
from services.notification_hub import SEVERITY_LEVELS, NotificationHub

if TYPE_CHECKING:
    from services.event_journal import EventJournal

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


def digest(items: list[dict], overflow: int = 0) -> tuple[str, str, int]:
    """(title, body, worst severity) of one channel's message.

    All alerts: the wording alerts have always had. With journal events: their own title when
    alone, else "N new notifications"; `overflow` events past the queue's cap are counted.
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
    lines = [_digest_line(i) for i in items[:DIGEST_LINES]]
    if len(items) > DIGEST_LINES:
        lines.append(f"and {len(items) - DIGEST_LINES} more")
    if overflow:
        lines.append(f"and {overflow} more events not listed; see NetTap")
    footer = (
        "Open NetTap's Alerts page for details."
        if alerts_only
        else "Open NetTap for details."
    )
    lines.extend(["", footer])
    return title, "\n".join(lines), worst


def _short_time(raw: Any) -> str:
    t = _when(raw)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if t else "?"


def event_item(entry: dict) -> dict | None:
    """A journal entry as a queued notification; None for a type nothing sends yet."""
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
        "line": line,
        "count": 1,
        "attempts": 0,
    }


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


class AlertDispatcher:
    """Sends new alerts to the channels the routing rules pick, from a background task."""

    def __init__(
        self,
        hub: NotificationHub,
        client: Any,
        lan_cidrs: Callable[[], list[str]],
        state_path: str,
        journal: "EventJournal | None" = None,
    ) -> None:
        self._hub = hub
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
                queue = [*old.get("events", []), item]
                over = max(0, len(queue) - MAX_EVENTS)
                queues = {
                    **queues,
                    cid: {
                        "events": queue[over:],
                        "overflow": old.get("overflow", 0) + over,
                    },
                }
        return queues, entries[-1]["seq"] if entries else seq

    # --- one poll ----------------------------------------------------------

    def compact_journal(self, _deadline: float) -> dict:
        """The journal-compact job: drops only what this dispatcher has saved as taken."""
        if self._journal is None:
            return {"dropped": 0}
        dropped = self._journal.compact(datetime.now(timezone.utc), self.committed_seq)
        return {"dropped": dropped}

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
        overflow = ev.get("overflow", 0) if events else 0
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
        # a fresh item replaces its queued copy (newer figures) but keeps the queued attempts
        by_sig.update(
            {
                i["sig"]: {**i, "attempts": by_sig.get(i["sig"], i)["attempts"]}
                for i in fresh
            }
        )
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
        candidates = sorted(by_sig.values(), key=_worst_first)[:MAX_PENDING]
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
        if (not candidates and not events) or (retry_at and retry_at > now):
            # the queue waits for the hourly digest; the hub keeps a failed send's error over this
            # OLD CODE: if slow and candidates and not any(i["attempts"] for i in candidates): (security delta: the hub decides, so a given-up queue can't hide a wrong password)
            # OLD CODE: if slow and candidates: (NET-319: queued events wait for the digest too)
            if slow and (candidates or events):
                n = len(candidates)
                # NET-319: queued events are named after the alerts, so alert-only wording is unchanged
                others = len(events) + overflow
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
                "pending": candidates,
                # past the budget the hourly slot holds even with nothing queued
                "retry_at": st.get("retry_at")
                if candidates or events or slow
                else None,
                **today,
            }, waiting

        # OLD CODE: title, body, worst = digest(candidates) (NET-319: with the queued events)
        title, body, worst = digest(
            sorted([*candidates, *events], key=_worst_first), overflow
        )
        # OLD CODE START — delta review: at the end, Pushover's 1024-character clip dropped the notice
        # if today["sent"] == DAILY_BUDGET - 1:
        #     body += (
        #         f"\n\nThis is the last notification today on this channel (limit "
        #         f"{DAILY_BUDGET} a day, UTC). Later alerts are on NetTap's Alerts page."
        #     )
        # OLD CODE END
        if today["sent"] == DAILY_BUDGET - 1:
            # first, so a service's length clip never drops it
            body = (
                f"This channel has reached its limit of {DAILY_BUDGET} messages today (UTC). "
                "Until 00:00 UTC it gets one digest an hour, worst alerts first.\n\n"
                f"{body}"
            )
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
                "pending": [],
                # OLD CODE: "retry_at": None, (security delta D3: past the budget, one digest an hour)
                "retry_at": _iso(_next_digest_at(now))
                if sent >= DAILY_BUDGET
                else None,
                **today,
                "sent": sent,
            }, _NO_EVENTS

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
        tried_events = [{**e, "attempts": e.get("attempts", 0) + 1} for e in events]
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
            "pending": kept,
            # OLD CODE: "retry_at": _iso(now + delay) if delay else None, (security delta: see retry)
            "retry_at": _iso(retry) if retry else None,
            **today,
        }, {"events": tried_events, "overflow": overflow}

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
