"""Index of the saved capture files: each file's real first and last packet time (NET-188).

The times come from ``capinfos`` in the nettap-tshark container, which tracks the
earliest and latest packet over the whole file, so a clock jump inside a file is
covered. Names and modification times are never used to decide which files hold a
window's packets; they only label files on the page.

An entry is keyed by the file's size and mtime. A file that changes (the one being
written, or a replaced one) is indexed again. A file capinfos can't read is kept as
``failed`` and counts as possibly holding any window, so every search reports it.

A record stamped before 2000 is not a packet NetTap captured: it is the zero-filled
tail a crash can leave (the file's size was saved, its last blocks were not). On the
G11 one such file read 74 records of time 0 and length 0 after its real packets, and
capinfos called its first packet 1970. A file like that is read again from 2000 on.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import stat
import time
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from api.offload import run_blocking
from services.container_exec import ExecResult, reader_slot, run_in_tshark

logger = logging.getLogger("nettap.capture_index")

CAPTURE_EXTENSIONS = (".pcap", ".pcapng", ".cap")
CONTAINER_ROOT = "/pcap"  # the capture directory inside nettap-tshark
# A window reaching into the last 2 minutes may still gain packets: on the G11 the
# writer ran 0.13-6.6 s behind real time (8 samples), and it writes in bursts.
RECENT_SECONDS = 120
# The background pass leaves a file alone while it is still being written to;
# a search indexes such a file itself, at the moment it needs it.
SETTLE_SECONDS = 10
POLL_SECONDS = 10
# The index is ~300 KB on the G11; saving after every batch would write ~1.7 GB a day.
# A lost minute of entries after a crash is just indexed again.
SAVE_SECONDS = 60
BATCH_FILES = 8
BATCH_DEADLINE_SECONDS = 30
# One file's own limit, below the batch's: a file capinfos can't read in time is
# recorded as failed (named by every search) instead of staying pending, which
# would make every search answer "still indexing".
CAPINFOS_SECONDS = 25
INLINE_INDEX_LIMIT = 8
# A failed entry is tried again after this long: capinfos may only have run out of time on a
# busy box, and a file that stays failed refuses every PCAP Search download over its window
FAILED_RETRY_SECONDS = 600
CUT_SHORT = "appears to have been cut short in the middle of a packet"
TIME_FLOOR = 946684800  # 2000-01-01T00:00:00Z
# editcap 4.0.17 exits 0 on EVERY read error, not only a partly written last packet,
# so its exit code can't say it read a file to the end; its message can.
_EDITCAP_CUT_SHORT = re.compile(
    r'^editcap: The file "(.+)" appears to have been cut short in the middle of a packet\.$'
)
INDEX_VERSION = 2  # 2: entries no longer count records stamped before TIME_FLOOR

# For each file: a marker line, capinfos's table (and its messages), then its exit
# code (124: GNU timeout stopped it). --foreground keeps capinfos in the job's process
# group, so the watchdog's and the daemon's group kills reach it.
_CAPINFOS_JOB = rf"""
CAPINFOS_SECONDS={CAPINFOS_SECONDS}
i=0
for f in "$@"; do
  echo "#nt-file $i"
  timeout --foreground "$CAPINFOS_SECONDS" capinfos -a -e -c -E -S -M -T -- "$f" 2>&1
  echo "#nt-rc $?"
  i=$((i+1))
done
"""


# One file's packets from $1 (TIME_FLOOR) on. editcap exits 0 on a cut-short file.
_FLOOR_JOB = (
    '{ editcap -A "$1" "$2" -; echo "$NT status editcap $?" >&2; } | '
    '{ capinfos -a -e -c -E -S -M -T -; echo "$NT status capinfos $?" >&2; }\n'
)


def editcap_read_to_end(stderr: str) -> bool:
    """True unless editcap reported anything but a partly written last packet."""
    lines = (ln for ln in stderr.splitlines() if ln.startswith("editcap:"))
    return all(_EDITCAP_CUT_SHORT.match(ln) for ln in lines)


class StillIndexing(Exception):
    def __init__(self, pending: int) -> None:
        super().__init__(f"NetTap is still indexing capture files ({pending} left).")
        self.pending = pending


@dataclass(frozen=True)
class CaptureFile:
    id: str  # path relative to the capture root, with "/" separators
    path: str  # daemon-side absolute path
    size: int
    mtime_ns: int

    @property
    def container_path(self) -> str:
        return f"{CONTAINER_ROOT}/{self.id}"


@dataclass(frozen=True)
class IndexEntry:
    size: int
    mtime_ns: int
    state: str  # "indexed" or "failed"
    first: str | None = None  # epoch seconds as capinfos printed them
    last: str | None = None
    packets: int | None = None
    encapsulation: str | None = None
    cut_short: bool = False
    error: str | None = None

    def fresh_for(self, f: CaptureFile) -> bool:
        return self.size == f.size and self.mtime_ns == f.mtime_ns

    def overlaps(self, start: Decimal, end: Decimal) -> bool:
        """True when the file holds packets in [start, end)."""
        if self.state != "indexed" or self.first is None or self.last is None:
            return False
        return Decimal(self.first) < end and Decimal(self.last) >= start


@dataclass(frozen=True)
class Selection:
    files: list[tuple[CaptureFile, IndexEntry]]
    failed: list[tuple[CaptureFile, IndexEntry]]


def epoch_iso(value: str | int | float | Decimal | None) -> str | None:
    """Epoch seconds to an ISO time in UTC, keeping microseconds."""
    if value is None:
        return None
    d = Decimal(str(value))
    whole = int(d.to_integral_value(rounding="ROUND_FLOOR"))
    micros = int(((d - whole) * 1_000_000).to_integral_value(rounding="ROUND_FLOOR"))
    return (
        datetime.fromtimestamp(whole, UTC)
        .replace(microsecond=micros)
        .isoformat()
        .replace("+00:00", "Z")
    )


def scan_captures(root: str) -> list[CaptureFile]:
    """Every regular capture file under root. Symlinks are skipped, never followed."""
    real_root = os.path.realpath(root)
    found: list[CaptureFile] = []
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            if not name.lower().endswith(CAPTURE_EXTENSIONS):
                continue
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                continue
            if not os.path.realpath(full).startswith(real_root + os.sep):
                continue
            try:
                st = os.stat(full, follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            rel = Path(os.path.relpath(full, root)).as_posix()
            found.append(CaptureFile(rel, full, st.st_size, st.st_mtime_ns))
    return found


def parse_capinfos(text: str, rc: int, size: int, mtime_ns: int) -> IndexEntry:
    """One file's capinfos output to an entry.

    A cut-short file (a partly written last packet, e.g. after a power cut) still
    has a valid table for its complete packets, which is all any reader can see.
    """
    lines = text.splitlines()
    table: list[str] | None = None
    table_rows: set[int] = set()
    for i, line in enumerate(lines[:-1]):
        if line.startswith("File name\t"):
            table, table_rows = lines[i + 1].rsplit("\t", 4), {i, i + 1}
            break
    messages = [line for j, line in enumerate(lines) if j not in table_rows]
    cut_short = any(CUT_SHORT in line for line in messages)
    if table is None or len(table) != 5 or (rc != 0 and not cut_short):
        error = " ".join(m.strip() for m in messages if m.strip())[:300]
        if rc == 124:
            error = f"capinfos took longer than {CAPINFOS_SECONDS} s"
        return IndexEntry(
            size, mtime_ns, "failed", error=error or f"capinfos exited {rc}"
        )
    _path, encap, packets, start, end = table
    try:
        count = int(packets)
        first = None if start == "n/a" else str(Decimal(start))
        last = None if end == "n/a" else str(Decimal(end))
    except (ValueError, InvalidOperation):
        return IndexEntry(
            size, mtime_ns, "failed", error=f"unreadable capinfos row: {table}"
        )
    return IndexEntry(
        size, mtime_ns, "indexed", first, last, count, encap, cut_short=cut_short
    )


def parse_capinfos_batch(stdout: str) -> dict[int, tuple[int, str]]:
    """Split the batch job's stdout into {file index: (exit code, output)}."""
    out: dict[int, tuple[int, str]] = {}
    current: int | None = None
    buf: list[str] = []
    for line in stdout.splitlines():
        if line.startswith("#nt-file "):
            current, buf = int(line.split()[1]), []
        elif line.startswith("#nt-rc ") and current is not None:
            out[current] = (int(line.split()[1]), "\n".join(buf))
            current = None
        elif current is not None:
            buf.append(line)
    return out


class CaptureIndex:
    def __init__(self, root: str, index_path: str, slot: asyncio.Semaphore) -> None:
        self.root = root
        self.index_path = index_path
        self._slot = slot
        self._entries: dict[str, IndexEntry] = self._load()
        # when each failure was recorded (monotonic); one loaded from disk is tried again now
        self._failed_at: dict[str, float] = {}
        self._lock = asyncio.Lock()  # one capinfos batch at a time
        self._dirty = False
        self._saved_at = float("-inf")

    # --- persistence -------------------------------------------------------

    def _load(self) -> dict[str, IndexEntry]:
        try:
            with open(self.index_path, encoding="utf-8") as fh:
                raw = json.load(fh)
            if raw.get("version") != INDEX_VERSION:
                logger.info("Capture index format changed; indexing every file again")
                return {}
            entries = {
                k: IndexEntry(**{**v, "mtime_ns": int(v["mtime_ns"])})
                for k, v in raw["entries"].items()
            }
            logger.info("Capture index loaded: %d entries", len(entries))
            return entries
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.error("Capture index unreadable, starting again: %s", exc)
            return {}

    def _save(self, present: set[str]) -> None:
        """Write the index, dropping files no longer `present`. A failed write
        leaves it dirty, so the shutdown flush tries again."""
        self._entries = {k: v for k, v in self._entries.items() if k in present}
        self._failed_at = {k: v for k, v in self._failed_at.items() if k in present}
        payload = {
            "version": INDEX_VERSION,
            "entries": {
                k: {**asdict(v), "mtime_ns": str(v.mtime_ns)}
                for k, v in self._entries.items()
            },
        }
        self._saved_at = time.monotonic()
        tmp = f"{self.index_path}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            os.replace(tmp, self.index_path)
        except OSError as exc:
            logger.error("Could not save the capture index: %s", exc)
            return
        self._dirty = False

    def _save_soon(self) -> None:
        """Save when something changed, at most once every SAVE_SECONDS.

        The files present come from a scan taken now: a caller's own scan may be
        older than entries another caller added meanwhile.
        """
        if time.monotonic() - self._saved_at < SAVE_SECONDS:
            return
        present = {f.id for f in scan_captures(self.root)}
        if self._dirty or any(k not in present for k in self._entries):
            self._save(present)

    # --- indexing ----------------------------------------------------------

    def entry(self, file_id: str) -> IndexEntry | None:
        return self._entries.get(file_id)

    def fresh_entry(self, f: CaptureFile) -> IndexEntry | None:
        e = self._entries.get(f.id)
        # OLD CODE START — NET-189 review: a failure was kept while the file stayed the same
        # return e if e is not None and e.fresh_for(f) else None
        # OLD CODE END
        if e is None or not e.fresh_for(f):
            return None
        failed_at = self._failed_at.get(f.id, float("-inf"))
        if e.state == "failed" and time.monotonic() - failed_at > FAILED_RETRY_SECONDS:
            return None  # stale: indexed again, like a changed file
        return e

    async def index_files(self, files: list[CaptureFile]) -> None:
        """Run capinfos over `files`. The caller holds a reader slot."""
        if not files:
            return
        async with self._lock:
            # The background pass may have indexed some while this caller waited.
            files = [f for f in files if self.fresh_entry(f) is None]
            if not files:
                return
            result: ExecResult = await run_in_tshark(
                _CAPINFOS_JOB,
                [f.container_path for f in files],
                deadline_s=BATCH_DEADLINE_SECONDS,
                max_stdout=1024 * 1024,
            )
            parsed = parse_capinfos_batch(result.stdout.decode("utf-8", "replace"))
            for i, f in enumerate(files):
                if i in parsed:
                    rc, text = parsed[i]
                    entry = parse_capinfos(text, rc, f.size, f.mtime_ns)
                    if entry.first is not None and Decimal(entry.first) < TIME_FLOOR:
                        entry = await self._without_junk(f, entry)
                    self._entries[f.id] = entry
                    if entry.state == "failed":
                        self._failed_at[f.id] = time.monotonic()
                    self._dirty = True
                # A file the batch never reached stays pending and is tried again.
            if result.deadline or len(parsed) < len(files):
                logger.warning(
                    "capinfos batch read %d of %d files (deadline=%s): %s",
                    len(parsed),
                    len(files),
                    result.deadline,
                    result.stderr[:300],
                )

    async def _without_junk(self, f: CaptureFile, entry: IndexEntry) -> IndexEntry:
        """Index `f` again from TIME_FLOOR on, leaving out a crash's zeroed records."""
        result = await run_in_tshark(
            _FLOOR_JOB,
            [str(TIME_FLOOR), f.container_path],
            deadline_s=BATCH_DEADLINE_SECONDS,
            max_stdout=64 * 1024,
        )
        if (
            result.deadline
            or not result.all_zero(("editcap", "capinfos"))
            or not editcap_read_to_end(result.stderr)
        ):
            return IndexEntry(
                f.size,
                f.mtime_ns,
                "failed",
                error=(
                    "records stamped before 2000, and reading past them failed "
                    f"({result.statuses}): {result.stderr[:200]}"
                ),
            )
        real = parse_capinfos(
            result.stdout.decode("utf-8", "replace"), 0, f.size, f.mtime_ns
        )
        if real.state == "indexed":
            logger.warning(
                "%s: left out %d records stamped before 2000 (a zero-filled tail, "
                "e.g. after a crash)",
                f.id,
                (entry.packets or 0) - (real.packets or 0),
            )
            real = replace(real, cut_short=entry.cut_short)
        return real

    async def select(self, start: Decimal, end: Decimal) -> Selection:
        """The files holding packets in [start, end). The caller holds a reader slot.

        Files without a current entry are indexed first, at most INLINE_INDEX_LIMIT.
        """
        # OLD CODE START — NET-189: the walk over every capture file ran on the request
        # loop (PCAP Search's download now selects here too, and its walk was off-loop)
        # files = scan_captures(self.root)
        # OLD CODE END
        files = await run_blocking(scan_captures, self.root)
        pending = [f for f in files if self.fresh_entry(f) is None]
        if len(pending) > INLINE_INDEX_LIMIT:
            raise StillIndexing(len(pending))
        if pending:
            await self.index_files(pending)
            self._save_soon()
        chosen: list[tuple[CaptureFile, IndexEntry]] = []
        failed: list[tuple[CaptureFile, IndexEntry]] = []
        for f in files:
            e = self.fresh_entry(f)
            if e is None:
                raise StillIndexing(1)
            if e.state == "failed":
                failed.append((f, e))
            elif e.overlaps(start, end):
                chosen.append((f, e))
        chosen.sort(key=lambda fe: fe[0].id)
        return Selection(chosen, failed)

    async def run_forever(self) -> None:
        """Index new and changed files in the background, newest first, a few at a time."""
        try:
            while True:
                try:
                    await self._index_pass()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Capture index pass failed")
                await asyncio.sleep(POLL_SECONDS)
        finally:
            if self._dirty:
                self._save({f.id for f in scan_captures(self.root)})

    async def _index_pass(self) -> None:
        while True:
            files = scan_captures(self.root)
            settled = time.time_ns() - SETTLE_SECONDS * 1_000_000_000
            pending = sorted(
                (
                    f
                    for f in files
                    if self.fresh_entry(f) is None and f.mtime_ns < settled
                ),
                key=lambda f: f.mtime_ns,
                reverse=True,
            )
            if not pending:
                self._save_soon()
                return
            while self._slot.locked():  # let people's searches go first
                await asyncio.sleep(1)
            async with reader_slot(self._slot, wait_seconds=30):
                await self.index_files(pending[:BATCH_FILES])
            self._save_soon()
            await asyncio.sleep(0.2)

    # --- listing -----------------------------------------------------------

    def summary(self) -> dict:
        """Every capture file with its index state, for GET /api/packets/captures."""
        now_ns = time.time_ns()
        recent_ns = now_ns - RECENT_SECONDS * 1_000_000_000
        rows = []
        for f in sorted(
            scan_captures(self.root), key=lambda f: f.mtime_ns, reverse=True
        ):
            e = self.fresh_entry(f)
            state = "pending" if e is None else e.state
            rows.append(
                {
                    "id": f.id,
                    "name": os.path.basename(f.id),
                    "size_bytes": f.size,
                    "modified": epoch_iso(Decimal(f.mtime_ns) / 1_000_000_000),
                    "recent": f.mtime_ns >= recent_ns,
                    "state": state,
                    "first": e.first if e and state == "indexed" else None,
                    "last": e.last if e and state == "indexed" else None,
                    "packets": e.packets if e and state == "indexed" else None,
                    "encapsulation": e.encapsulation if e else None,
                    "cut_short": bool(e and e.cut_short),
                    "error": e.error if e and state == "failed" else None,
                }
            )
        firsts = [Decimal(r["first"]) for r in rows if r["first"] is not None]
        return {
            "files": rows,
            "count": len(rows),
            "bytes_total": sum(r["size_bytes"] for r in rows),
            "oldest_packet": str(min(firsts)) if firsts else None,
            "unindexed": sum(1 for r in rows if r["state"] == "pending"),
            "failed": sum(1 for r in rows if r["state"] == "failed"),
        }
