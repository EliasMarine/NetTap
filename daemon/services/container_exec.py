"""Supervised jobs in the nettap-tshark container (NET-188).

Every packet-analysis job runs as ``docker exec nettap-tshark sh -c SUPERVISOR _
<deadline> <job script> <args…>``. Both scripts are fixed text; every input is a
positional argument, so nothing the user typed is ever parsed by a shell.

The supervisor puts the job in its own process group (``setsid``) and prints
``#nt-pgid``. A watchdog prints ``#nt-deadline`` and then sends TERM and, 2 s later,
KILL to the group. When the job leader exits, the supervisor kills the group anyway,
so no stage can outlive the job. Each stage of a job reports ``#nt-status <stage>
<code>`` on stderr. The daemon decides how a job ended from those lines and from what
it printed, never from the exit code alone (the job's own 143 can arrive while the
watchdog is still in its grace period).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

logger = logging.getLogger("nettap.container_exec")

TSHARK_CONTAINER = "nettap-tshark"

# $1 deadline seconds, $2 job script, then the job's own arguments.
SUPERVISOR = r"""
d="$1"; job="$2"; shift 2
setsid sh -c "$job" _ "$@" &
pg=$!
echo "#nt-pgid $pg" >&2
setsid sh -c 'sleep "$1"; echo "#nt-deadline" >&2; kill -TERM -"$2" 2>/dev/null; sleep 2; kill -KILL -"$2" 2>/dev/null' _ "$d" "$pg" >/dev/null &
wd=$!
wait "$pg"; rc=$?
kill -KILL -"$wd" 2>/dev/null
kill -KILL -"$pg" 2>/dev/null
exit "$rc"
"""

KILL_GROUP = 'kill -KILL -"$1" 2>/dev/null; exit 0'

_ROOT_WARNING = 'Running as user "root"'
_STATUS = re.compile(r"^#nt-status (\S+) (\d+)$")
_PGID = re.compile(r"^#nt-pgid (\d+)$")
_READ_CHUNK = 64 * 1024
# The watchdog's KILL lands 2 s after the deadline; the supervisor exits right after.
_GRACE_SECONDS = 5
_CLEANUP_SECONDS = 10
_LINE_LIMIT = 1024 * 1024  # longest stderr line accepted


class ReaderBusy(Exception):
    """No packet-reader slot came free in time."""


class JobOutputTooLarge(Exception):
    """A job printed more than its cap; it was stopped."""


@dataclass(frozen=True)
class ExecResult:
    stdout: bytes
    stderr: str
    statuses: dict[str, int]
    returncode: int | None
    deadline: bool
    pgid: int | None
    seconds: float

    def status(self, stage: str) -> int | None:
        return self.statuses.get(stage)

    def all_zero(self, stages: tuple[str, ...]) -> bool:
        return all(self.statuses.get(s) == 0 for s in stages)

    def killed_for_memory(self) -> bool:
        """A stage died of KILL (137) before any deadline: the container's OOM killer."""
        return not self.deadline and 137 in self.statuses.values()


@dataclass
class _StderrState:
    pgid: int | None = None
    deadline: bool = False
    statuses: dict[str, int] = field(default_factory=dict)
    lines: list[str] = field(default_factory=list)
    size: int = 0


@contextlib.asynccontextmanager
async def reader_slot(slot: asyncio.Semaphore, wait_seconds: float):
    """Hold one of the shared packet-reader slots, or raise ReaderBusy."""
    try:
        await asyncio.wait_for(slot.acquire(), timeout=max(wait_seconds, 0.01))
    except TimeoutError as exc:
        raise ReaderBusy("The packet reader is busy; try again in a moment.") from exc
    try:
        yield
    finally:
        slot.release()


def _note_stderr_line(state: _StderrState, line: str) -> None:
    if (
        m := _PGID.match(line)
    ) and state.pgid is None:  # the supervisor prints it first
        state.pgid = int(m.group(1))
    elif line == "#nt-deadline":
        state.deadline = True
    elif m := _STATUS.match(line):
        state.statuses[m.group(1)] = int(m.group(2))
    elif line and not line.startswith(_ROOT_WARNING):
        state.lines.append(line)


async def _pump_stderr(
    stream: asyncio.StreamReader, state: _StderrState, cap: int
) -> None:
    while raw := await stream.readline():
        state.size += len(raw)
        if state.size > cap:
            raise JobOutputTooLarge(f"stderr passed {cap} bytes")
        _note_stderr_line(state, raw.decode("utf-8", errors="replace").rstrip("\r\n"))


async def _pump_stdout(
    stream: asyncio.StreamReader,
    cap: int,
    sink: Callable[[bytes], Awaitable[None]] | None,
    chunks: list[bytes],
) -> None:
    total = 0
    while chunk := await stream.read(_READ_CHUNK):
        total += len(chunk)
        if total > cap:
            raise JobOutputTooLarge(f"stdout passed {cap} bytes")
        if sink is None:
            chunks.append(chunk)
        else:
            await sink(chunk)


async def _stop(proc: asyncio.subprocess.Process, pgid: int | None) -> None:
    """Kill the job's group inside the container, then wait for docker exec to end.

    Killing the local docker exec client would leave the job running in the
    container, so the group is killed there first.
    """
    if pgid is not None:
        killer = await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            TSHARK_CONTAINER,
            "sh",
            "-c",
            KILL_GROUP,
            "_",
            str(pgid),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(killer.wait(), timeout=_CLEANUP_SECONDS)
        except TimeoutError:
            killer.kill()
            logger.error("Could not kill job group %s in %s", pgid, TSHARK_CONTAINER)
    try:
        await asyncio.wait_for(proc.wait(), timeout=_CLEANUP_SECONDS)
    except TimeoutError:
        proc.kill()
        await proc.wait()


async def run_in_tshark(
    job: str,
    args: list[str],
    *,
    deadline_s: float,
    max_stdout: int,
    max_stderr: int = 256 * 1024,
    sink: Callable[[bytes], Awaitable[None]] | None = None,
) -> ExecResult:
    """Run `job` under the supervisor. The caller must hold a reader slot.

    `sink`, when given, receives stdout as it arrives instead of it being kept.
    Any exception (a cap, the sink failing, cancellation, or TimeoutError when the
    supervisor itself overruns) kills the job's process group in the container
    before it propagates.
    """
    started = time.monotonic()
    deadline = max(1, int(deadline_s))
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "exec",
        TSHARK_CONTAINER,
        "sh",
        "-c",
        SUPERVISOR,
        "_",
        str(deadline),
        job,
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=_LINE_LIMIT,
    )
    state = _StderrState()
    chunks: list[bytes] = []
    if proc.stdout is None or proc.stderr is None:
        raise RuntimeError("docker exec started without pipes")
    pumps = [
        asyncio.create_task(_pump_stdout(proc.stdout, max_stdout, sink, chunks)),
        asyncio.create_task(_pump_stderr(proc.stderr, state, max_stderr)),
    ]
    try:
        async with asyncio.timeout(deadline + _GRACE_SECONDS):
            done, pending = await asyncio.wait(
                pumps, return_when=asyncio.FIRST_EXCEPTION
            )
            for task in done:
                task.result()  # re-raise a pump's failure
            if pending:
                await asyncio.gather(*pending)
            returncode = await proc.wait()
    except BaseException:
        for task in pumps:
            task.cancel()
        await asyncio.shield(_stop(proc, state.pgid))
        raise
    return ExecResult(
        stdout=b"".join(chunks),
        stderr="\n".join(state.lines),
        statuses=dict(state.statuses),
        returncode=returncode,
        deadline=state.deadline,
        pgid=state.pgid,
        seconds=round(time.monotonic() - started, 3),
    )
