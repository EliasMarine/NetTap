"""Fakes for PCAP Search's streamed "Download filtered" (NET-189): the capture index and the
supervised job in the nettap-tshark container. The service's own logic runs for real."""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal

from services import packet_search as ps
from services.capture_index import (
    CaptureFile,
    IndexEntry,
    Selection,
    StillIndexing,
)
from services.container_exec import ExecResult

OLD_NS = 1_600_000_000 * 1_000_000_000  # long settled, so never "recent"
PCAP_HEADER = b"\x0a\x0d\x0d\x0a" + b"\x00" * 28


def capture(
    name: str,
    first: str,
    last: str,
    *,
    packets: int = 1000,
    size: int = 1_000_000,
    mtime_ns: int = OLD_NS,
    cut_short: bool = False,
) -> tuple[CaptureFile, IndexEntry]:
    """A capture file and its index entry; only the entry's packet times say what it holds."""
    f = CaptureFile(name, f"/opt/nettap/pcap/{name}", size, mtime_ns)
    entry = IndexEntry(
        size, mtime_ns, "indexed", first, last, packets, "Ethernet", cut_short
    )
    return f, entry


def failed(name: str, mtime_ns: int = OLD_NS) -> tuple[CaptureFile, IndexEntry]:
    f = CaptureFile(name, f"/opt/nettap/pcap/{name}", 500, mtime_ns)
    return f, IndexEntry(500, mtime_ns, "failed", error="capinfos took too long")


class FakeIndex:
    """CaptureIndex.select over fixed entries, by their packet times."""

    def __init__(self, files=(), failed_files=(), pending: int = 0) -> None:
        self.files = list(files)
        self.failed = list(failed_files)
        self.pending = pending
        self.asked: list[tuple[Decimal, Decimal]] = []

    async def select(self, start: Decimal, end: Decimal) -> Selection:
        self.asked.append((start, end))
        if self.pending:
            raise StillIndexing(self.pending)
        chosen = [fe for fe in self.files if fe[1].overlaps(start, end)]
        return Selection(chosen, list(self.failed))


class FakeTshark:
    """run_in_tshark: the filter check, then the download job feeding `chunks` to its sink.

    Set `statuses` / `deadline` / `stderr` for how the download job ends, `check` for the
    filter check's (status, stderr), and `hold` to keep the job running until it is set.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.chunks = [PCAP_HEADER, b"packet-1", b"packet-2"]
        self.statuses = {"mergecap": 0, "editcap": 0, "tshark": 0}
        self.deadline = False
        self.stderr = ""
        self.check = (0, "")
        self.hold: asyncio.Event | None = None
        self.started = asyncio.Event()
        self.sink_error: BaseException | None = None
        self.stopped = asyncio.Event()  # set when the job saw a failure

    def jobs(self, job: str) -> list[dict]:
        return [c for c in self.calls if c["job"] == job]

    async def __call__(self, job, args, *, deadline_s, max_stdout, sink=None):
        started = time.monotonic()
        self.calls.append(
            {
                "job": job,
                "args": list(args),
                "deadline_s": deadline_s,
                "max": max_stdout,
            }
        )
        if job == ps.CHECK_JOB:
            rc, err = self.check
            return ExecResult(b"", err, {"tshark": rc}, 0, False, 1, 0.01)
        self.started.set()
        try:
            for chunk in self.chunks:
                await sink(chunk)
            if self.hold is not None:
                await self.hold.wait()
        except (
            BaseException
        ) as exc:  # what run_in_tshark sees: it kills the job's group
            self.sink_error = exc
            self.stopped.set()
            raise
        cuts = sum(str(a).startswith("cut:") for a in args)
        statuses = {**{f"pre-{i}": 0 for i in range(cuts)}, **self.statuses}
        seconds = time.monotonic() - started
        return ExecResult(b"", self.stderr, statuses, 0, self.deadline, 1, seconds)
