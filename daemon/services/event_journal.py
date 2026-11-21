"""
NetTap's durable record of what happened on the network (NET-319, roadmap F1).

One JSON object a line in events.jsonl: new devices today; offline and online transitions, data
cap crossings and report deliveries in later slices. A producer appends its event before it
advances its own state, so the journal is the commit point: notifications are read from here
(the dispatcher's event intake) and weekly reports will count from here.

One lock covers every write: an append, compaction and the start-up repair, so a compaction
can never lose an append that lands while it runs.
"""

import contextlib
import hashlib
import json
import logging
import os
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from services.capture_config import write_file_atomic

logger = logging.getLogger("nettap.services.event_journal")

DEFAULT_PATH = os.environ.get("EVENT_JOURNAL_FILE", "/opt/nettap/data/events.jsonl")
KEEP_DAYS = 120
MAX_LINES = 50_000
# NET-339: data cap warnings recorded this long ago stay even past MAX_LINES (at most 3 per cap
# per month), so a month's ids can't be evicted and the warning sent again
CAP_KEEP = timedelta(days=62)
WINDOW = (
    1_000  # the newest entries, kept in memory so a normal poll never reads the file
)


def event_id(event_type: str, key: str, instance: str) -> str:
    """Stable id: the same event appended twice (a producer's retry) is recognised."""
    return hashlib.sha256(f"{event_type}|{key}|{instance}".encode()).hexdigest()[:32]


def _when(raw: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


class EventJournal:
    """Append-only events.jsonl with a monotonic seq per line."""

    def __init__(
        self,
        path: str = DEFAULT_PATH,
        keep_days: int = KEEP_DAYS,
        max_lines: int = MAX_LINES,
        window: int = WINDOW,
    ) -> None:
        self._path = Path(path)
        self._keep = timedelta(days=keep_days)
        self._max_lines = max_lines
        self._lock = threading.Lock()
        self._recent: deque[dict] = deque(maxlen=window)
        self._ids: set[str] = set()
        self._next_seq = 1
        # F5 (NET-331): False while the file can't be read; append and after then retry the load
        self._available = True
        # a first start (no file yet) and a lost dispatcher state look alike without this
        self.existed_at_start = self._path.exists()
        with self._lock:
            self._load()

    # --- start-up ----------------------------------------------------------

    def _load(self) -> None:
        """Read the file into memory (called with the lock held). F5 (NET-331, round 4 #9): one
        that can't be read leaves the journal unavailable, never empty, so no append reuses an
        existing journal's sequence numbers or misses its ids."""
        # OLD CODE START — F5: an unreadable file started at seq 1 with no ids, so the next append
        # reused an existing journal's numbers and could repeat an event already in it
        # try:
        #     raw = self._path.read_bytes()
        # except FileNotFoundError:
        #     return
        # except OSError as exc:
        #     logger.error("Event journal unreadable (%s): starting with no history", exc)
        #     return
        # OLD CODE END
        try:
            raw = self._path.read_bytes()
            if raw and not raw.endswith(b"\n"):
                # a crash mid-append: cut the torn line before anything is appended after it
                keep = raw.rfind(b"\n") + 1
                logger.warning(
                    "Event journal: dropping a torn last line (%d bytes)",
                    len(raw) - keep,
                )
                with open(self._path, "r+b") as f:
                    f.truncate(keep)
                    f.flush()
                    os.fsync(f.fileno())
                raw = raw[:keep]
        except FileNotFoundError:
            raw = b""
        except OSError as exc:
            # ERROR once, as it becomes unavailable; the retries (every poll and append) at DEBUG
            log = logger.error if self._available else logger.debug
            log("Event journal unreadable (%s): unavailable until it can be read", exc)
            self._available = False
            return
        entries = self._parse(raw.decode("utf-8", errors="replace"))
        self._ids = {e["id"] for e in entries}
        self._recent.clear()
        self._recent.extend(entries)
        self._next_seq = entries[-1]["seq"] + 1 if entries else 1
        self._available = True

    def _require(self) -> None:
        """Called with the lock held: an unavailable journal tries its load again, else OSError."""
        if not self._available:
            self._load()
        if not self._available:
            raise OSError("the event journal can't be read")

    @property
    def available(self) -> bool:
        """False while the file can't be read: nothing is appended or read until it loads."""
        return self._available

    def reload(self) -> bool:
        """Try an unavailable journal's load again (a no-op once loaded); whether it is available.
        The dispatcher calls it, so recovery doesn't wait for a producer's append (round 6 #3)."""
        with self._lock:
            if not self._available:
                self._load()
            return self._available

    @staticmethod
    def _parse(text: str) -> list[dict]:
        entries, bad = [], 0
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if isinstance(entry, dict) and isinstance(entry.get("seq"), int):
                entries.append(entry)
            else:
                bad += 1
        if bad:
            logger.warning("Event journal: skipped %d unreadable line(s)", bad)
        return entries

    def _read_all(self) -> list[dict]:
        try:
            return self._parse(self._path.read_text(errors="replace"))
        except FileNotFoundError:
            return []

    # --- writing -----------------------------------------------------------

    def append(
        self,
        event_type: str,
        key: str,
        observed_at: str,
        data: dict[str, Any],
        instance: str | None = None,
    ) -> dict | None:
        """Write one event durably (fsync). None when it is already in the journal.

        Raises OSError when it couldn't be written; the file is then exactly as before, so a
        partial line never sits in front of the next append. Also while the journal is unavailable.
        """
        eid = event_id(event_type, key, observed_at if instance is None else instance)
        with self._lock:
            self._require()  # F5: never seq 1 over a journal that couldn't be read
            if eid in self._ids:
                return None
            entry = {
                "seq": self._next_seq,
                "id": eid,
                "type": event_type,
                "key": key,
                "observed_at": observed_at,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "data": data,
            }
            line = (json.dumps(entry, separators=(",", ":")) + "\n").encode()
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self._path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                size = os.fstat(fd).st_size
                try:
                    view = memoryview(line)
                    while view:
                        view = view[os.write(fd, view) :]
                    os.fsync(fd)
                except BaseException:
                    with contextlib.suppress(OSError):
                        os.ftruncate(fd, size)
                        os.fsync(fd)
                    raise
            finally:
                os.close(fd)
            self._ids.add(eid)
            self._recent.append(entry)
            self._next_seq += 1
            return entry

    def compact(self, now: datetime, keep_from_seq: int | None) -> int:
        """Drop lines older than the keep period or past the line cap; returns how many went.

        Never drops a line after `keep_from_seq` (the dispatcher's saved cursor: not yet taken
        for delivery) nor the newest line (it carries the seq the next append continues from),
        nor a data cap warning recorded in the last CAP_KEEP (NET-339).
        With no saved cursor yet, nothing is dropped.
        """
        if keep_from_seq is None:
            return 0
        with self._lock:
            entries = self._read_all()
            if not entries:
                return 0
            cutoff = now - self._keep
            recent_enough = [
                e
                for e in entries
                if (t := _when(e.get("recorded_at"))) is None or t >= cutoff
            ][-self._max_lines :]
            # OLD CODE START — NET-339: the line cap could evict this month's data cap ids
            # kept_seqs = (
            #     {e["seq"] for e in recent_enough}
            #     | {e["seq"] for e in entries if e["seq"] > keep_from_seq}
            #     | {entries[-1]["seq"]}
            # )
            # OLD CODE END
            cap_floor = now - CAP_KEEP
            kept_seqs = (
                {e["seq"] for e in recent_enough}
                | {e["seq"] for e in entries if e["seq"] > keep_from_seq}
                | {entries[-1]["seq"]}
                # a data cap warning's id is its once-a-month record: kept past the line cap
                | {
                    e["seq"]
                    for e in entries
                    if e.get("type") == "data_cap"
                    and ((t := _when(e.get("recorded_at"))) is None or t >= cap_floor)
                }
            )
            kept = [e for e in entries if e["seq"] in kept_seqs]
            dropped = len(entries) - len(kept)
            if not dropped:
                return 0
            text = "".join(json.dumps(e, separators=(",", ":")) + "\n" for e in kept)
            write_file_atomic(str(self._path), text, mode=0o600)
            self._ids = {e["id"] for e in kept}
            return dropped

    # --- reading -----------------------------------------------------------

    @property
    def last_seq(self) -> int:
        return self._next_seq - 1

    def after(self, seq: int, limit: int) -> list[dict]:
        """Up to `limit` entries after `seq`, oldest first; read from the file when the
        backlog is older than the in-memory window, so nothing unread is ever skipped.
        OSError while the journal is unavailable (F5): an unread journal is never an empty one."""
        with self._lock:
            self._require()
            if not self._recent or self._recent[0]["seq"] <= seq + 1:
                return [e for e in self._recent if e["seq"] > seq][:limit]
            return [e for e in self._read_all() if e["seq"] > seq][:limit]
