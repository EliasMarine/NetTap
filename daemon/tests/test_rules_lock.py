"""NET-191 slice 2: the daemon side of Suricata's rules lock, and capture restarts of suricata-live."""

import asyncio
import fcntl
import inspect
import os
import sys
import threading
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services import rules_lock
from services.rules_lock import RulesBusyError


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(rules_lock, "RULES_STATE_DIR", str(tmp_path))
    return tmp_path


def _held(path) -> bool:
    """True when another open file description holds the flock (what the shell side would see)."""
    fd = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return False
    except BlockingIOError:
        return True
    finally:
        os.close(fd)


class TestRulesLock:
    def test_held_inside_released_after(self, state):
        async def run():
            async with rules_lock.rules_lock():
                assert _held(state / "rules.lock")
            assert not _held(state / "rules.lock")

        asyncio.run(run())

    def test_released_when_the_block_raises(self, state):
        async def run():
            with pytest.raises(RuntimeError):
                async with rules_lock.rules_lock():
                    raise RuntimeError("restart failed")

        asyncio.run(run())
        assert not _held(state / "rules.lock")

    def test_waits_for_the_holder_then_takes_it(self, state):
        lock = state / "rules.lock"
        lock.touch()
        holder = os.open(lock, os.O_RDONLY)
        fcntl.flock(holder, fcntl.LOCK_EX)

        async def run():
            loop = asyncio.get_running_loop()
            loop.call_later(1.5, os.close, holder)  # the update finishes
            start = loop.time()
            async with rules_lock.rules_lock(wait_s=10):
                return loop.time() - start

        assert asyncio.run(run()) >= 1.0

    def test_gives_up_with_a_plain_message(self, state):
        lock = state / "rules.lock"
        lock.touch()
        holder = os.open(lock, os.O_RDONLY)
        fcntl.flock(holder, fcntl.LOCK_EX)
        try:

            async def run():
                async with rules_lock.rules_lock(wait_s=0.5):
                    pass

            with pytest.raises(RulesBusyError, match="rule update is running"):
                asyncio.run(run())
        finally:
            os.close(holder)

    def test_no_volume_runs_unlocked(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rules_lock, "RULES_STATE_DIR", str(tmp_path / "missing"))

        async def run():
            async with rules_lock.rules_lock():
                return "ran"

        assert asyncio.run(run()) == "ran"


class TestLockFileIsOpenedSafely:
    """The volume is writable by Malcolm's user; the daemon opens rules.lock as root."""

    def test_the_default_wait_is_240_s(self):
        # pins the daemon-to-proxy timing contract: 240 s lock + restart must fit the web's 290 s
        assert rules_lock.LOCK_WAIT_S == 240
        default = inspect.signature(rules_lock.rules_lock).parameters["wait_s"].default
        assert default == 240

    def test_a_planted_link_is_refused_and_nothing_is_created(
        self, state, tmp_path_factory
    ):
        target = tmp_path_factory.mktemp("elsewhere") / "created-by-root"
        (state / "rules.lock").symlink_to(target)

        async def run():
            async with rules_lock.rules_lock(0.1):
                pass

        with pytest.raises(OSError):
            asyncio.run(run())
        assert not target.exists()

    def test_a_planted_fifo_is_refused_without_blocking(self, state):
        os.mkfifo(state / "rules.lock")
        outcome = []

        def run():
            async def take():
                async with rules_lock.rules_lock(0.1):
                    pass

            try:
                asyncio.run(take())
                outcome.append("taken")
            except OSError:
                outcome.append("refused")

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(2)
        assert outcome == ["refused"]


MODULE = "api.capture_control"


class TestCaptureRestartTakesTheLock:
    def _restart(self, container, cmd):
        from api.capture_control import _restart_if_running

        with (
            patch(
                f"{MODULE}._get_container_status",
                AsyncMock(return_value={"running": True, "status": "running"}),
            ),
            patch(f"{MODULE}._docker_cmd", AsyncMock(side_effect=cmd)),
        ):
            return asyncio.run(_restart_if_running(container))

    def test_suricata_restarts_while_holding_it_and_releases_it(self, state):
        seen = []

        def cmd(action, container, **kw):
            seen.append((_held(state / "rules.lock"), kw))
            return 0, ""

        assert self._restart("nettap-suricata-live", cmd) == (True, "")
        # a hung docker restart must not keep the rules lock
        assert seen == [(True, {"timeout": 120})]
        assert not _held(state / "rules.lock")

    def test_docker_cmd_gives_up_after_its_timeout(self):
        from api import capture_control

        class Proc:
            returncode = None
            killed = False

            async def communicate(self):
                await asyncio.sleep(10)

            def kill(self):
                Proc.killed = True

            async def wait(self):
                return -9

        with patch.object(
            capture_control.asyncio,
            "create_subprocess_exec",
            AsyncMock(return_value=Proc()),
        ):
            rc, out = asyncio.run(
                capture_control._docker_cmd("restart", "live", timeout=0.1)
            )
        assert rc == -1 and "did not finish within" in out and Proc.killed

    def test_docker_cmd_survives_a_process_gone_at_the_deadline(self):
        from api import capture_control

        class Proc:
            returncode = 0

            async def communicate(self):
                await asyncio.sleep(10)

            def kill(self):
                raise ProcessLookupError

            async def wait(self):
                return 0

        with patch.object(
            capture_control.asyncio,
            "create_subprocess_exec",
            AsyncMock(return_value=Proc()),
        ):
            rc, out = asyncio.run(
                capture_control._docker_cmd("restart", "live", timeout=0.1)
            )
        assert rc == -1 and "did not finish within" in out

    def test_released_when_the_restart_fails(self, state):
        def cmd(action, container, **kw):
            raise OSError("docker socket gone")

        restarted, error = self._restart("nettap-suricata-live", cmd)
        assert restarted is False and "docker socket gone" in error
        assert not _held(state / "rules.lock")

    def test_busy_lock_is_an_error_not_a_restart(self, state):
        lock = state / "rules.lock"
        lock.touch()
        holder = os.open(lock, os.O_RDONLY)
        fcntl.flock(holder, fcntl.LOCK_EX)
        calls = []
        try:
            from api import capture_control

            with patch.object(
                capture_control, "rules_lock", lambda: rules_lock.rules_lock(0.3)
            ):
                restarted, error = self._restart(
                    "nettap-suricata-live",
                    lambda a, c, **kw: calls.append(c) or (0, ""),
                )
        finally:
            os.close(holder)
        assert restarted is False and "rule update is running" in error
        assert calls == []

    def test_other_containers_do_not_take_it(self, state):
        (state / "rules.lock").touch()
        seen = []

        def cmd(action, container, **kw):
            seen.append(_held(state / "rules.lock"))
            return 0, ""

        assert self._restart("nettap-zeek-live", cmd) == (True, "")
        assert seen == [False]
