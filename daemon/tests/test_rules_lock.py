"""NET-191 slice 2: the daemon side of Suricata's rules lock, and capture restarts of suricata-live."""

import asyncio
import fcntl
import os
import sys
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

        def cmd(action, container):
            seen.append(_held(state / "rules.lock"))
            return 0, ""

        assert self._restart("nettap-suricata-live", cmd) == (True, "")
        assert seen == [True]
        assert not _held(state / "rules.lock")

    def test_released_when_the_restart_fails(self, state):
        def cmd(action, container):
            raise OSError("docker socket gone")

        restarted, error = self._restart("nettap-suricata-live", cmd)
        assert restarted is False and "docker socket gone" in error
        assert not _held(state / "rules.lock")

    def test_busy_lock_is_an_error_not_a_restart(self, state, monkeypatch):
        monkeypatch.setattr(rules_lock, "LOCK_WAIT_S", 0.3)
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
                    "nettap-suricata-live", lambda a, c: calls.append(c) or (0, "")
                )
        finally:
            os.close(holder)
        assert restarted is False and "rule update is running" in error
        assert calls == []

    def test_other_containers_do_not_take_it(self, state):
        (state / "rules.lock").touch()
        seen = []

        def cmd(action, container):
            seen.append(_held(state / "rules.lock"))
            return 0, ""

        assert self._restart("nettap-zeek-live", cmd) == (True, "")
        assert seen == [False]
