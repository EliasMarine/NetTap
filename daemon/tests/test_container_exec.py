"""The supervised runner for jobs in the nettap-tshark container (NET-188).

The Python side is tested with docker exec replaced by a local shell that prints what
the supervisor would. The supervisor script itself runs for real where setsid exists
(Linux CI); on the G11 it was checked through /proc (see the deploy script).
"""

import asyncio
import os
import shutil
import subprocess
import time

import pytest

from services import container_exec as ce
from services.container_exec import (
    KILL_GROUP,
    SUPERVISOR,
    JobOutputTooLarge,
    ReaderBusy,
    reader_slot,
    run_in_tshark,
)


@pytest.fixture
def fake_docker(monkeypatch):
    """docker exec → `sh -c <fake>`; returns the argv of every call."""
    calls: list[tuple] = []
    real = asyncio.create_subprocess_exec
    scripts: dict[str, str] = {}

    jobs: list = []

    async def fake(*argv, **kw):
        calls.append(argv)
        if KILL_GROUP in argv:  # the group kill reaches the fake job too
            for proc in jobs:
                if proc.returncode is None:
                    proc.kill()
            return await real("true", stdout=kw.get("stdout"), stderr=kw.get("stderr"))
        job = argv[argv.index(SUPERVISOR) + 3]
        proc = await real("sh", "-c", scripts[job], **kw)
        jobs.append(proc)
        return proc

    monkeypatch.setattr(ce.asyncio, "create_subprocess_exec", fake)
    return calls, scripts


@pytest.mark.asyncio
async def test_markers_are_parsed_and_removed(fake_docker):
    calls, scripts = fake_docker
    scripts["job"] = (
        'echo "#nt-pgid 4242" >&2; echo row1; echo row2; '
        'echo "Running as user \\"root\\" and group \\"root\\"." >&2; '
        'echo "tshark: a note" >&2; echo "#nt-status tshark 0" >&2; '
        'echo "#nt-status head 0" >&2; echo "#nt-pgid 1" >&2'
    )
    r = await run_in_tshark("job", ["a b", "$(id)"], deadline_s=5, max_stdout=1000)
    assert r.stdout == b"row1\nrow2\n"
    assert r.statuses == {"tshark": 0, "head": 0}
    assert r.pgid == 4242 and not r.deadline
    assert r.stderr == "tshark: a note\n#nt-pgid 1"  # only the first pgid line counts
    # every input is its own argv element after the fixed scripts
    assert calls[0][-2:] == ("a b", "$(id)")
    assert calls[0][:5] == ("docker", "exec", "nettap-tshark", "sh", "-c")


@pytest.mark.asyncio
async def test_deadline_marker_wins_over_exit_code(fake_docker):
    _, scripts = fake_docker
    scripts["job"] = 'echo "#nt-pgid 7" >&2; echo "#nt-deadline" >&2; exit 143'
    r = await run_in_tshark("job", [], deadline_s=5, max_stdout=1000)
    assert r.deadline and r.returncode == 143 and not r.killed_for_memory()


@pytest.mark.asyncio
async def test_oom_is_a_kill_before_any_deadline(fake_docker):
    _, scripts = fake_docker
    scripts["job"] = 'echo "#nt-pgid 7" >&2; echo "#nt-status tshark 137" >&2'
    r = await run_in_tshark("job", [], deadline_s=5, max_stdout=1000)
    assert r.killed_for_memory()


@pytest.mark.asyncio
async def test_stdout_cap_kills_the_group(fake_docker):
    calls, scripts = fake_docker
    scripts["job"] = 'echo "#nt-pgid 99" >&2; sleep 0.2; yes | head -c 100000; sleep 5'
    started = time.monotonic()
    with pytest.raises(JobOutputTooLarge):
        await run_in_tshark("job", [], deadline_s=20, max_stdout=1000)
    assert time.monotonic() - started < 15
    kill = [c for c in calls if KILL_GROUP in c]
    assert kill and kill[0][-1] == "99"


@pytest.mark.asyncio
async def test_sink_failure_kills_the_group(fake_docker):
    calls, scripts = fake_docker
    scripts["job"] = 'echo "#nt-pgid 5" >&2; sleep 0.2; echo data; sleep 5'

    async def sink(_chunk):
        raise ConnectionResetError("client went away")

    with pytest.raises(ConnectionResetError):
        await run_in_tshark("job", [], deadline_s=20, max_stdout=1000, sink=sink)
    assert any(KILL_GROUP in c and c[-1] == "5" for c in calls)


@pytest.mark.asyncio
async def test_cancellation_kills_the_group(fake_docker):
    calls, scripts = fake_docker
    scripts["job"] = 'echo "#nt-pgid 11" >&2; sleep 5'
    task = asyncio.create_task(run_in_tshark("job", [], deadline_s=20, max_stdout=1000))
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert any(KILL_GROUP in c and c[-1] == "11" for c in calls)


@pytest.mark.asyncio
async def test_silent_death_reports_no_statuses(fake_docker):
    _, scripts = fake_docker
    scripts["job"] = 'echo "#nt-pgid 3" >&2; kill -9 $$'
    r = await run_in_tshark("job", [], deadline_s=5, max_stdout=1000)
    assert r.statuses == {} and not r.deadline


@pytest.mark.asyncio
async def test_slot_wait_runs_out():
    slot = asyncio.Semaphore(1)
    async with reader_slot(slot, 1):
        with pytest.raises(ReaderBusy):
            async with reader_slot(slot, 0.05):
                pass
    async with reader_slot(slot, 0.05):  # released again
        pass


needs_setsid = pytest.mark.skipif(shutil.which("setsid") is None, reason="needs setsid")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@needs_setsid
def test_supervisor_kills_a_job_that_ignores_term():
    job = 'trap "" TERM; sleep 30 & echo "#nt-child $!" >&2; wait'
    started = time.monotonic()
    p = subprocess.run(
        ["sh", "-c", SUPERVISOR, "_", "1", job],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert time.monotonic() - started < 8
    assert "#nt-deadline" in p.stderr
    child = int(p.stderr.split("#nt-child ")[1].split()[0])
    assert not _alive(child)


@needs_setsid
def test_supervisor_reaps_a_leftover_child_after_early_exit():
    job = 'sleep 30 & echo "#nt-child $!" >&2; echo "#nt-status job 0" >&2'
    p = subprocess.run(
        ["sh", "-c", SUPERVISOR, "_", "20", job],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert "#nt-deadline" not in p.stderr and p.returncode == 0
    child = int(p.stderr.split("#nt-child ")[1].split()[0])
    time.sleep(0.2)
    assert not _alive(child)
