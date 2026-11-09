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
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from services.capture_config import write_file_atomic
from services.notification_hub import SEVERITY_LEVELS, NotificationHub

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


def digest(items: list[dict]) -> tuple[str, str, int]:
    """(title, body, worst severity) of one channel's message."""
    worst = min(i["severity"] for i in items)
    level = SEVERITY_LEVELS[worst]
    if len(items) == 1:
        title = f"{level.capitalize()} alert: {items[0]['signature']}"
    else:
        title = f"{len(items)} new alerts (worst: {level})"
    lines = []
    for i in items[:DIGEST_LINES]:
        where = (
            i["example"]
            if i["pairs"] == 1
            else f"{i['example']} and {i['pairs'] - 1} more"
        )
        events = f"{i['count']} event{'' if i['count'] == 1 else 's'}"
        lines.append(
            f"- [{SEVERITY_LEVELS[i['severity']]}] {i['signature']}: {events}, {where}"
        )
    if len(items) > DIGEST_LINES:
        lines.append(f"and {len(items) - DIGEST_LINES} more")
    lines.extend(["", "Open NetTap's Alerts page for details."])
    return title, "\n".join(lines), worst


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
    ) -> None:
        self._hub = hub
        self._client = client
        self._lan_cidrs = lan_cidrs
        self._state_path = Path(state_path)
        self._state = self._load()

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

    # --- one poll ----------------------------------------------------------

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
        targets = {cid for i in items or [] for cid in self._routed(i["severity"])}
        targets |= {cid for cid, st in old.items() if st.get("pending")}
        targets = sorted(targets)
        # channels at once: a slow mail server never holds up another channel
        states = await asyncio.gather(
            *(
                self._deliver(cid, old.get(cid, _EMPTY), items or [], now)
                for cid in targets
            )
        )
        self._state = {
            # a failed query keeps the cursor, so the next poll reads this window too
            "cursor": self._state.get("cursor") if items is None else _iso(now),
            "channels": {**old, **dict(zip(targets, states))},
        }
        self._save()

    async def _deliver(
        self, cid: str, st: dict, items: list[dict], now: datetime
    ) -> dict:
        """The channel's next state after sending it what is new for it, or queueing it."""
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
        if not candidates or (retry_at and retry_at > now):
            # the queue waits for the hourly digest; the hub keeps a failed send's error over this
            # OLD CODE: if slow and candidates and not any(i["attempts"] for i in candidates): (security delta: the hub decides, so a given-up queue can't hide a wrong password)
            if slow and candidates:
                n = len(candidates)
                self._hub.record_held(
                    cid,
                    f"Daily limit of {DAILY_BUDGET} messages reached: until 00:00 UTC, one "
                    f"digest an hour, worst alerts first. {n} alert{'' if n == 1 else 's'} "
                    "waiting for the next one",
                )
            return {
                "done": done,
                "pending": candidates,
                # past the budget the hourly slot holds even with nothing queued
                "retry_at": st.get("retry_at") if candidates or slow else None,
                **today,
            }

        title, body, worst = digest(candidates)
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
        if outcome == "sent":
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
        # the item with the fewest tries sets the pace, so a new alert keeps its quick retry
        delay = RETRY_AFTER[min(i["attempts"] for i in kept) - 1] if kept else None
        # past the budget a refusal waits for the hourly slot, like a digest
        if outcome == "refused" and today["sent"] >= DAILY_BUDGET:
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
        }

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
