"""Packet analysis: search a time window of the saved captures with TShark (NET-188).

Every job cuts the window out of the capture files first (mergecap | editcap) and
dissects only that, so each packet is read with the context of the whole window.
A search says exactly how it ended: it reached the end of the window, stopped at
the row limit, or ran out of time. Detail and download read the window again and
check every packet against the identity the search returned.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import re
import time
from collections.abc import Awaitable, Callable
from decimal import Decimal

from services.capture_index import (
    RECENT_SECONDS,
    CaptureIndex,
    Selection,
    StillIndexing,
    epoch_iso,
)
from services.container_exec import (
    ExecResult,
    JobOutputTooLarge,
    ReaderBusy,
    reader_slot,
    run_in_tshark,
)
from services.packet_manifest import (
    CHANGED,
    MAX_BYTES,
    MAX_FILES,
    MAX_FILTER,
    MAX_WINDOW_NS,
    Manifest,
    PacketError,
    admit,
    parse_manifest,
)
from services.packet_parse import (
    ALL_FIELDS,
    EPOCH,
    ParseError,
    PcapVerifier,
    StreamMismatch,
    epoch_ns,
    mark_bytes,
    ns_epoch,
    parse_hex,
    parse_pdml,
    parse_rows,
    pdml_identity,
)

logger = logging.getLogger("nettap.packet_search")

LIMITS = (100, 250, 1000)
SEARCH_SECONDS = 40
REQUEST_SECONDS = 48  # the web proxy waits 55 s
MIN_JOB_SECONDS = 5
SLOT_WAIT_SECONDS = 5
FIELDS_SECONDS = 10
CHECK_SECONDS = 10
VERSION_SECONDS = 2
DOWNLOAD_MAX_BYTES = 70 * 1024 * 1024
FIELD_PREFIX = re.compile(r"^[a-z0-9_.-]{3,80}\Z")
FIELD_SUGGESTIONS = 20
BUSY = "The packet reader is busy; try again in a moment."
OOM = (
    "The packet reader ran out of memory on this window. "
    "Try a shorter window or a narrower filter."
)

# The window cut shared by every job: `cut <stage suffix> <files…>` writes the packets
# in ["$from", "$to") as one stream. TShark 4.0.17's mergecap stops merging EVERY file
# at the first partly written packet, exiting 2: on the G11 a crashed file plus the
# next one gave the crashed file's packets only. So a file marked "cut:" (it may end
# in a partly written packet) reaches mergecap through editcap and a FIFO: editcap
# stops at the cut and exits 0. Each such editcap reports "pre<suffix>-<i>". After
# mergecap ends, opening each FIFO read-write frees a writer mergecap never opened.
_CUT = r"""cut() {
  s=$1; shift; i=0
  for f do
    shift
    case $f in
      cut:*)
        p=/tmp/nt-$$-$s-$i
        mkfifo "$p" || exit 1
        { editcap "${f#cut:}" - > "$p"; echo "$NT status pre$s-$i $?" >&2; } &
        set -- "$@" "$p" ;;
      *) set -- "$@" "$f" ;;
    esac
    i=$((i+1))
  done
  { mergecap -w - "$@"; echo "$NT status mergecap$s $?" >&2
    for p in /tmp/nt-$$-$s-*; do [ -p "$p" ] && : <> "$p"; done; } |
  { editcap -A "$from" -B "$to" - -; echo "$NT status editcap$s $?" >&2; }
  wait
  rm -f /tmp/nt-$$-$s-*
}
"""
_FIELD_ARGS = " ".join(f"-e {f}" for f in ALL_FIELDS)
SEARCH_JOB = (
    _CUT
    + 'from="$1"; to="$2"; filter="$3"; rows="$4"; shift 4\n'
    + 'cut "" "$@" | { tshark -o frame.generate_md5_hash:TRUE -l -r - -Y "$filter" -T fields'
    " -E separator=/t -E occurrence=a -E aggregator=\"$(printf '\\037')\" "
    + _FIELD_ARGS
    + '; echo "$NT status tshark $?" >&2; }'
    ' | { head -n "$rows"; echo "$NT status head $?" >&2; }\n'
)
DETAIL_JOB = (
    _CUT
    + 'from="$1"; to="$2"; n="$3"; shift 3\n'
    + 'cut 1 "$@" | { tshark -o frame.generate_md5_hash:TRUE -r - -c "$n" -Y "frame.number == $n"'
    ' -T pdml; echo "$NT status tshark1 $?" >&2; }\n'
    'echo "#nt-hex"\n'
    'cut 2 "$@" | { tshark -r - -c "$n" -Y "frame.number == $n" -x --hexdump frames'
    ' --hexdump noascii; echo "$NT status tshark2 $?" >&2; }\n'
)
DOWNLOAD_JOB = (
    _CUT
    + 'from="$1"; to="$2"; last="$3"; set="$4"; shift 4\n'
    + 'cut "" "$@" | { tshark -r - -c "$last" -Y "frame.number in {$set}" -F nsecpcap -w -;'
    ' echo "$NT status tshark $?" >&2; }\n'
)
FIELDS_JOB = (
    '{ tshark -G fields; echo "$NT status tshark $?" >&2; } | '
    '{ awk -F \'\\t\' -v p="$1" -v ROWS="$2" \'($1 == "F" || $1 == "P") && index($3, p) == 1 '
    '{ print $1 "\\t" $3 "\\t" $2 "\\t" $4 "\\t" $8; if (++n == ROWS + 0) exit }\'; '
    'echo "$NT status awk $?" >&2; }\n'
)
# An empty pcap (header only) on stdin: TShark compiles the filter and reads nothing.
CHECK_JOB = (
    "printf '\\324\\303\\262\\241\\002\\000\\004\\000\\000\\000\\000\\000\\000\\000"
    "\\000\\000\\377\\377\\000\\000\\001\\000\\000\\000' | "
    'tshark -r - -Y "$1" -T fields -e frame.number; echo "$NT status tshark $?" >&2\n'
)


def _check_filter_text(text: object) -> str:
    if not isinstance(text, str):
        raise PacketError(400, "The filter must be text.")
    if len(text) > MAX_FILTER:
        raise PacketError(400, f"The filter is longer than {MAX_FILTER} characters.")
    if any(c in text for c in "\x00\r\n"):
        raise PacketError(400, "The filter can't contain line breaks.")
    return text.strip() or "frame"


def job_path(path: str, may_be_cut: bool) -> str:
    """A file for _CUT: through editcap when its last packet may be partly written."""
    return f"cut:{path}" if may_be_cut else path


def _cuts(paths: list[str]) -> int:
    return sum(p.startswith("cut:") for p in paths)


def cut_ok(result: ExecResult, cuts: int, suffix: str = "") -> bool:
    """The window cut ended cleanly, or was stopped by its reader having enough.

    Every stage must report: `cuts` editcaps in front of mergecap (one per "cut:"
    file), mergecap and the window's editcap. 141 is a stage stopped by SIGPIPE
    because the reader had enough; mergecap's own exit 2 is a real failure, since no
    partly written packet reaches it.
    """
    pre = [v for k, v in result.statuses.items() if k.startswith(f"pre{suffix}-")]
    stages = [
        *pre,
        result.status(f"mergecap{suffix}"),
        result.status(f"editcap{suffix}"),
    ]
    return len(pre) == cuts and all(v in (0, 141) for v in stages)


def _raise_unfinished(result: ExecResult, what: str) -> None:
    """For a job whose predicate didn't hold: raise the right failure."""
    if result.killed_for_memory():
        raise PacketError(507, OOM)
    if result.deadline:
        raise PacketError(504, f"{what} took longer than the time allowed. Try again.")
    raise PacketError(
        502,
        f"{what} failed.",
        detail=result.stderr[-2000:] or f"statuses {result.statuses}",
    )


class PacketSearchService:
    def __init__(
        self,
        root: str,
        index: CaptureIndex,
        slot: asyncio.Semaphore,
        version: Callable[[], Awaitable[str]],
    ) -> None:
        self.root = root
        self.index = index
        self._slot = slot
        self._version = version

    async def _tshark_version(self) -> str:
        """TShark's version (cached by TSharkService); a slow lookup never holds up
        an answer that is already done."""
        try:
            return await asyncio.wait_for(self._version(), VERSION_SECONDS)
        except TimeoutError:
            return "unknown"

    @contextlib.asynccontextmanager
    async def _reader(self):
        """Hold a reader slot; a busy reader or a runaway job becomes a PacketError."""
        try:
            async with reader_slot(self._slot, SLOT_WAIT_SECONDS):
                yield
        except ReaderBusy:
            raise PacketError(503, BUSY) from None
        except JobOutputTooLarge as exc:
            raise PacketError(
                502, "The packet reader printed too much.", str(exc)
            ) from None
        except TimeoutError:
            raise PacketError(502, "The packet reader didn't stop in time.") from None

    # --- filters and fields ------------------------------------------------

    async def _check_filter(self, filt: str) -> None:
        """400 with TShark's own message when it refuses the filter. Holds a slot."""
        result = await run_in_tshark(
            CHECK_JOB, [filt], deadline_s=CHECK_SECONDS, max_stdout=64 * 1024
        )
        rc = result.status("tshark")
        if rc == 0:
            return
        if rc is not None and result.stderr.startswith("tshark:"):
            raise PacketError(400, result.stderr.strip())
        _raise_unfinished(result, "Checking the filter")

    async def check_filter(self, filt: object) -> dict:
        text = _check_filter_text(filt)
        async with self._reader():
            await self._check_filter(text)
        return {"ok": True, "filter": text}

    async def fields(self, prefix: str) -> dict:
        if not FIELD_PREFIX.match(prefix):
            raise PacketError(400, "Type at least 3 letters of a field name.")
        async with self._reader():
            result = await run_in_tshark(
                FIELDS_JOB,
                [prefix, str(FIELD_SUGGESTIONS + 1)],
                deadline_s=FIELDS_SECONDS,
                max_stdout=256 * 1024,
            )
        # awk stops one row past the list, so "more" is only said when true
        lines = result.stdout.decode("utf-8", "replace").splitlines()
        if len(lines) != FIELD_SUGGESTIONS + 1 and not result.all_zero(
            ("tshark", "awk")
        ):
            _raise_unfinished(result, "Listing fields")
        out = []
        for line in lines[:FIELD_SUGGESTIONS]:
            kind, abbrev, name, ftype, blurb = (line.split("\t") + [""] * 5)[:5]
            out.append(
                {
                    "field": abbrev,
                    "name": name,
                    "type": "protocol" if kind == "P" else ftype,
                    "description": blurb,
                }
            )
        return {"prefix": prefix, "fields": out, "more": len(lines) > FIELD_SUGGESTIONS}

    # --- search ------------------------------------------------------------

    @staticmethod
    def _window(start: object, end: object, now_ns: int) -> tuple[int, int, int]:
        """(from, to as asked, to used). The window is never shortened, only `to`
        is held at now."""
        if not (isinstance(start, str) and isinstance(end, str)):
            raise PacketError(400, "Give the window as epoch seconds.")
        if not (EPOCH.match(start) and EPOCH.match(end)):
            raise PacketError(400, "Give the window as epoch seconds.")
        a, b = epoch_ns(start), epoch_ns(end)
        if a >= b:
            raise PacketError(400, "The window must end after it starts.")
        if b - a > MAX_WINDOW_NS:
            raise PacketError(400, "The window can be at most 30 minutes long.")
        if a >= now_ns:
            raise PacketError(400, "That time hasn't happened yet.")
        return a, b, min(b, now_ns)

    async def search(self, body: dict) -> dict:
        started = time.monotonic()
        filt = _check_filter_text(body.get("filter", ""))
        limit = body.get("limit", 100)
        if type(limit) is not int or limit not in LIMITS:  # 100.0 would reach head -n
            raise PacketError(400, "Show 100, 250 or 1000 packets.")
        now_ns = time.time_ns()
        a, b_asked, b = self._window(body.get("from"), body.get("to"), now_ns)
        start, end = ns_epoch(a), ns_epoch(b)
        try:
            async with self._reader():
                await self._check_filter(filt)
                sel = await self.index.select(Decimal(start), Decimal(end))
                self._check_budget(sel)
                result = None
                cuts = 0
                deadline = int(
                    min(SEARCH_SECONDS, REQUEST_SECONDS - (time.monotonic() - started))
                )
                if sel.files:
                    if deadline < MIN_JOB_SECONDS:
                        raise PacketError(503, BUSY)
                    recent_ns = now_ns - RECENT_SECONDS * 1_000_000_000
                    paths = [
                        job_path(
                            f.container_path, e.cut_short or f.mtime_ns >= recent_ns
                        )
                        for f, e in sel.files
                    ]
                    cuts = _cuts(paths)
                    result = await run_in_tshark(
                        SEARCH_JOB,
                        [start, end, filt, str(limit + 1), *paths],
                        deadline_s=deadline,
                        max_stdout=16 * 1024 * 1024,
                    )
        except StillIndexing as exc:
            raise PacketError(503, str(exc)) from None
        out = self._search_result(result, sel, limit, deadline, cuts)
        out.update(
            filter=filt,
            limit=limit,
            window={
                "requested": {"from": start, "to": ns_epoch(b_asked)},
                "effective": {"from": start, "to": end},
                "from_iso": epoch_iso(start),
                "to_iso": epoch_iso(end),
            },
            provisional=b > now_ns - RECENT_SECONDS * 1_000_000_000,
            tshark_version=await self._tshark_version(),
            seconds=round(time.monotonic() - started, 3),
        )
        out["manifest"] = self._manifest(start, end, filt, sel, out["rows"], now_ns)
        logger.info(
            "packet search window=%s..%s files=%d bytes=%d filter_len=%d limit=%d "
            "rows=%d termination=%s statuses=%s pgid=%s seconds=%.2f",
            start,
            end,
            len(sel.files),
            sum(f.size for f, _ in sel.files),
            len(filt),
            limit,
            len(out["rows"]),
            out["termination"],
            result.statuses if result else {},
            result.pgid if result else None,
            out["seconds"],
        )
        return out

    @staticmethod
    def _check_budget(sel: Selection) -> None:
        size = sum(f.size for f, _ in sel.files)
        if len(sel.files) > MAX_FILES or size > MAX_BYTES:
            raise PacketError(
                400,
                f"This window covers {len(sel.files)} capture files "
                f"({size / 1e9:.1f} GB). NetTap reads at most {MAX_FILES} files or "
                f"{MAX_BYTES / 1e9:.0f} GB at once; pick a shorter window.",
            )

    def _search_result(
        self,
        result: ExecResult | None,
        sel: Selection,
        limit: int,
        deadline: int,
        cuts: int,
    ) -> dict:
        skipped = [
            {
                "id": f.id,
                "error": e.error,
                "modified": epoch_iso(Decimal(f.mtime_ns) / 10**9),
            }
            for f, e in sel.failed
        ]
        files = [
            {
                "id": f.id,
                "size_bytes": f.size,
                "first": e.first,
                "last": e.last,
                "cut_short": e.cut_short,
            }
            for f, e in sel.files
        ]
        base = {"files": files, "skipped_files": skipped}
        if result is None:
            return {
                **base,
                "rows": [],
                "termination": "eof",
                "complete": not skipped,
                "message": "No saved capture holds packets from this window.",
            }
        try:
            rows = parse_rows(result.stdout, partial_tail_ok=result.deadline)
        except ParseError as exc:
            raise PacketError(502, "The search failed.", detail=str(exc)) from None
        if len(rows) == limit + 1:
            termination, message = (
                "limit",
                f"Showing the first {limit} matches; more exist.",
            )
            rows = rows[:limit]
        elif result.all_zero(("tshark", "head")) and cut_ok(result, cuts):
            termination, message = "eof", None
        elif result.deadline:
            termination = "deadline"
            message = (
                f"The search stopped after {deadline} s. These are the matches it "
                "returned before stopping; more may exist in this window."
                if rows
                else f"The search stopped after {deadline} s before finding a match; "
                "matches may still exist in this window."
            )
        else:
            _raise_unfinished(result, "The search")
        return {
            **base,
            "rows": rows,
            "termination": termination,
            "complete": termination == "eof" and not skipped,
            "message": message,
        }

    @staticmethod
    def _manifest(
        start: str, end: str, filt: str, sel: Selection, rows: list[dict], now_ns: int
    ) -> dict:
        recent_ns = now_ns - RECENT_SECONDS * 1_000_000_000
        return {
            "from": start,
            "to": end,
            "filter": filt,
            "files": [
                {
                    "id": f.id,
                    "size": f.size,
                    "mtime_ns": str(f.mtime_ns),
                    "recent": f.mtime_ns >= recent_ns,
                }
                for f, _ in sel.files
            ],
            "frames": [
                {"n": r["n"], "t": r["t"], "cap_len": r["cap_len"], "md5": r["md5"]}
                for r in rows
            ],
        }

    def _admitted_paths(self, manifest: Manifest) -> list[str]:
        """admit()'s paths, each marked for _CUT. A file still being written, or one
        whose index entry isn't for this exact file, may end in a partial packet."""
        marked = []
        for path, f in zip(admit(manifest, self.root), manifest.files, strict=True):
            e = self.index.entry(f.id)
            whole = (
                e is not None
                and (e.size, e.mtime_ns) == (f.size, f.mtime_ns)
                and not e.cut_short
            )
            marked.append(job_path(path, f.recent or not whole))
        return marked

    # --- one packet ----------------------------------------------------------

    async def packet(self, body: dict) -> dict:
        manifest = parse_manifest(body.get("manifest"))
        n = body.get("frame")
        if not isinstance(n, int) or isinstance(n, bool):
            raise PacketError(400, "Say which packet to show.")
        want = manifest.frame(n)
        async with self._reader():
            paths = self._admitted_paths(manifest)
            result = await run_in_tshark(
                DETAIL_JOB,
                [manifest.start, manifest.end, str(n), *paths],
                deadline_s=SEARCH_SECONDS,
                max_stdout=4 * 1024 * 1024,
            )
        if not (
            result.status("tshark1") == 0
            and result.status("tshark2") == 0
            and cut_ok(result, _cuts(paths), "1")
            and cut_ok(result, _cuts(paths), "2")
        ):
            _raise_unfinished(result, "Reading this packet")
        pdml, sep, hexdump = result.stdout.partition(b"\n#nt-hex\n")
        if not sep or pdml.count(b"<packet>") != 1:
            raise PacketError(409, CHANGED)
        try:
            layers = parse_pdml(pdml)
            t, cap_len, length, md5 = pdml_identity(layers)
            frame = parse_hex(hexdump.decode("ascii", "replace"))
            same_tree = (epoch_ns(t), cap_len, md5) == (
                epoch_ns(want.t),
                want.cap_len,
                want.md5,
            )
        except ParseError as exc:
            raise PacketError(
                502, "Reading this packet failed.", detail=str(exc)
            ) from None
        same_bytes = (
            len(frame) == want.cap_len
            and hashlib.md5(frame, usedforsecurity=False).hexdigest() == want.md5
        )
        if not (same_tree and same_bytes):
            raise PacketError(409, CHANGED)
        marking = mark_bytes(layers, frame)
        return {
            "n": n,
            "t": want.t,
            "len": length,
            "cap_len": cap_len,
            "md5": md5,
            "layers": layers,
            "bytes_hex": frame.hex(),
            "marking": marking,
        }

    # --- download ------------------------------------------------------------

    def prepare_download(self, body_manifest: object) -> Manifest:
        """Everything that can fail before a byte is sent, apart from the read itself."""
        manifest = parse_manifest(body_manifest)
        admit(manifest, self.root)
        kinds = set()
        for f in manifest.files:
            entry = self.index.entry(f.id)
            if entry is None or entry.encapsulation is None:
                raise PacketError(409, CHANGED)
            kinds.add(entry.encapsulation)
        if len(kinds) != 1 or kinds & {"per-packet", "unknown"}:
            raise PacketError(
                422,
                "Download isn't available for this search: its captures mix link "
                f"types ({', '.join(sorted(kinds))}). Download the capture files instead.",
            )
        return manifest

    async def download(
        self, manifest: Manifest, write: Callable[[bytes], Awaitable[None]]
    ) -> int:
        """Stream the search's packets as pcap; only verified records reach `write`.

        Raises PacketError if anything differs; the caller must then abort the
        response rather than end it, so a partial file is never complete-looking.
        """
        verifier = PcapVerifier(list(manifest.frames))

        async def sink(chunk: bytes) -> None:
            ready = verifier.feed(chunk)
            if ready:
                await write(ready)

        frames = ",".join(str(f.n) for f in manifest.frames)
        try:
            async with self._reader():
                paths = self._admitted_paths(manifest)
                result = await run_in_tshark(
                    DOWNLOAD_JOB,
                    [
                        manifest.start,
                        manifest.end,
                        str(manifest.frames[-1].n),
                        frames,
                        *paths,
                    ],
                    deadline_s=SEARCH_SECONDS,
                    max_stdout=DOWNLOAD_MAX_BYTES,
                    sink=sink,
                )
        except StreamMismatch as exc:
            raise PacketError(409, CHANGED, detail=str(exc)) from None
        if not (result.status("tshark") == 0 and cut_ok(result, _cuts(paths))):
            _raise_unfinished(result, "The download")
        try:
            verifier.finish()
        except StreamMismatch as exc:
            raise PacketError(409, CHANGED, detail=str(exc)) from None
        logger.info(
            "packet download frames=%d files=%d seconds=%.2f",
            len(manifest.frames),
            len(manifest.files),
            result.seconds,
        )
        return verifier.verified
