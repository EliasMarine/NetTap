"""NET-205 opt-in: the meter off, turning it off and on, background clean-up and its retries."""

# ruff: noqa: F401, F811 (the env fixture is imported from test_live_bandwidth, and tests take it by name)

import asyncio
import shutil

import pytest

import services.live_bandwidth as lb
from services.live_bandwidth import (
    CLEANING,
    CLEANUP_RETRY_S,
    CLEANUP_RETRY_SLOW_S,
    OFF_REASON,
    LiveBandwidthBusyError,
)
from tests.test_live_bandwidth import (
    MAC_A,
    MAC_B,
    MAC_DOWN,
    MAC_UP,
    _cookies,
    _start,
    env,
    run,
)

IDLE = {"state": "idle", "failed": {}}


async def _until(cond, what="condition"):
    for _ in range(1000):
        if cond():
            return
        await asyncio.sleep(0)
    raise AssertionError(f"timed out waiting for {what}")


def _block(env, monkeypatch, verb):
    """Make the first tc call of this verb wait until the returned gate is set."""
    gate, reached = asyncio.Event(), asyncio.Event()
    real = env.fake.run

    async def run_tool(argv, timeout, stdin=None):
        if env.fake._verb(argv, stdin) == verb and not gate.is_set():
            reached.set()
            await gate.wait()
        return await real(argv, timeout, stdin)

    monkeypatch.setattr(lb, "run_tool", run_tool)
    return gate, reached


async def _dirty_after_turn_off(env, msg="denied"):
    """One watch, then a turn-off whose first removal fails; returns once the retry waits."""
    await _start(env)
    env.retry.gate = asyncio.Event()
    env.fake.fail("del-batch", msg=msg)
    env.meter.set_enabled(False)
    await _until(lambda: env.retry.sleeps, "the first retry")
    assert env.meter.cleanup_status() == {
        "state": "retrying",
        "failed": {"enp4s0": msg},
    }


def _assert_off(snap):
    assert snap["off"] is True and snap["supported"] is False
    assert snap["reason"] == OFF_REASON
    assert snap["key"] == {"kind": "mac", "value": MAC_A.value}


class TestOff:
    def test_off_answers_without_running_tc(self, env):
        meter = env.make(enabled=False)
        _assert_off(run(meter.watch(MAC_A)))
        assert env.fake.calls == []
        assert meter.enabled is False and meter.cleanup_status() == IDLE

    def test_turning_off_removes_every_filter_and_a_keepalive_then_gets_off(self, env):
        async def body():
            await _start(env)
            await env.meter.watch(MAC_B)
            env.meter.set_enabled(False)
            assert env.meter.cleanup_status()["state"] == "running"
            await env.meter._cleanup_task
            return await env.meter.watch(MAC_A)

        _assert_off(run(body()))
        assert env.fake.owned() == {} and env.meter._watches == {}
        assert env.meter.cleanup_status() == IDLE
        assert env.fake.verbs().count("add-batch") == 2  # the keepalive added nothing

    def test_turning_on_again_measures_with_a_new_generation(self, env):
        async def body():
            await _start(env)
            env.meter.set_enabled(False)
            await env.meter._cleanup_task
            env.meter.set_enabled(True)
            return await env.meter.watch(MAC_A)

        assert run(body())["supported"] is True
        assert _cookies(env.fake) == {(0, 2)}

    def test_setting_the_same_value_changes_nothing(self, env):
        env.meter.set_enabled(True)
        assert env.meter._transition == 0 and env.meter._cleanup_task is None


class TestTurnOffRaces:
    def test_turn_off_while_an_admission_waits_on_the_lock(self, env):
        async def body():
            await env.meter.reconcile()
            await env.meter._lock.acquire()
            task = asyncio.create_task(env.meter.watch(MAC_A))
            await _until(lambda: env.meter._waiters == 1, "the admission to wait")
            env.meter.set_enabled(False)
            env.meter._lock.release()
            snap = await task
            await env.meter._cleanup_task
            return snap

        _assert_off(run(body()))
        assert env.fake.owned() == {} and "add-batch" not in env.fake.verbs()

    def test_turn_off_while_preparing(self, env, monkeypatch):
        gate, reached = _block(env, monkeypatch, "qdisc-show")

        async def body():
            await env.meter.reconcile()
            task = asyncio.create_task(env.meter.watch(MAC_A))
            await reached.wait()
            env.meter.set_enabled(False)
            gate.set()
            snap = await task
            await env.meter._cleanup_task
            return snap

        _assert_off(run(body()))
        assert env.fake.owned() == {} and "add-batch" not in env.fake.verbs()

    def test_turn_off_while_installing_rolls_back(self, env, monkeypatch):
        gate, reached = _block(env, monkeypatch, "add-batch")

        async def body():
            await env.meter.reconcile()
            task = asyncio.create_task(env.meter.watch(MAC_A))
            await reached.wait()
            env.meter.set_enabled(False)
            gate.set()
            snap = await task
            await env.meter._cleanup_task
            return snap

        _assert_off(run(body()))
        assert env.fake.owned() == {} and env.meter._watches == {}
        assert env.meter.cleanup_status() == IDLE

    def test_off_then_on_during_an_admission_is_retried_not_off(self, env):
        async def body():
            await env.meter.reconcile()
            await env.meter._lock.acquire()
            task = asyncio.create_task(env.meter.watch(MAC_A))
            await _until(lambda: env.meter._waiters == 1, "the admission to wait")
            env.meter.set_enabled(False)
            env.meter.set_enabled(True)
            env.meter._lock.release()
            with pytest.raises(LiveBandwidthBusyError, match=CLEANING):
                await task
            await env.meter._cleanup_task
            return await env.meter.watch(MAC_A)

        assert run(body())["supported"] is True
        assert set(env.fake.owned()) == {(MAC_DOWN, 1), (MAC_UP, 1)}

    def test_a_second_turn_off_reuses_the_running_cleanup(self, env):
        async def body():
            await _start(env)
            await env.meter._lock.acquire()  # the clean-up can't start yet
            env.meter.set_enabled(False)
            first = env.meter._cleanup_task
            env.meter.set_enabled(True)
            env.meter.set_enabled(False)
            assert env.meter._cleanup_task is first
            env.meter._lock.release()
            await first

        run(body())
        assert env.fake.owned() == {} and env.meter.cleanup_status() == IDLE


class TestCleanupRetries:
    def test_dirty_refuses_admission_until_the_retry_succeeds(self, env):
        async def body():
            await _dirty_after_turn_off(env)
            env.meter.set_enabled(True)
            with pytest.raises(LiveBandwidthBusyError, match=CLEANING):
                await env.meter.watch(MAC_A)
            env.retry.gate.set()
            await env.meter._cleanup_task
            assert env.meter.cleanup_status() == IDLE
            return await env.meter.watch(MAC_A)

        assert run(body())["supported"] is True
        assert _cookies(env.fake) == {(0, 2)}  # exactly one watch, the new one
        assert env.retry.sleeps == [CLEANUP_RETRY_S]

    def test_a_dump_timeout_stays_dirty(self, env):
        async def body():
            await _dirty_after_turn_off(env)
            env.fake.fail("dump", msg="tc timed out")
            env.retry.gate.set()
            await _until(lambda: len(env.retry.sleeps) == 2, "the second retry")
            status = env.meter.cleanup_status()
            env.retry.gate.set()
            await env.meter._cleanup_task
            return status

        assert run(body()) == {
            "state": "retrying",
            "failed": {"enp4s0": "tc timed out"},
        }
        assert env.fake.owned() == {} and env.meter.cleanup_status() == IDLE

    def test_a_vanished_interface_counts_as_clean(self, env):
        async def body():
            await _dirty_after_turn_off(env)
            shutil.rmtree(env.net_dir / "enp4s0")
            env.fake.fail("dump", msg='Cannot find device "enp4s0"')
            env.retry.gate.set()
            await env.meter._cleanup_task

        run(body())
        assert env.meter.cleanup_status() == IDLE

    def test_a_recreated_interface_without_our_filters_counts_as_clean(self, env):
        async def body():
            await _dirty_after_turn_off(env)
            env.fake.filters["enp4s0"].clear()
            env.retry.gate.set()
            await env.meter._cleanup_task

        run(body())
        assert env.meter.cleanup_status() == IDLE

    def test_retries_slow_down_after_the_fast_ones(self, env, monkeypatch):
        monkeypatch.setattr(lb, "CLEANUP_FAST_TRIES", 1)

        async def body():
            await _dirty_after_turn_off(env)
            env.fake.fail("del-batch", msg="denied")
            env.retry.gate.set()
            await _until(lambda: len(env.retry.sleeps) == 2, "the second retry")
            env.retry.gate.set()
            await env.meter._cleanup_task

        run(body())
        assert env.retry.sleeps == [CLEANUP_RETRY_S, CLEANUP_RETRY_SLOW_S]
        assert env.fake.owned() == {}

    def test_startup_cleanup_while_off_retries_a_failure(self, env):
        async def body():
            await _start(env)  # filters left behind by an earlier daemon
            meter = env.make(enabled=False)
            env.fake.fail("del-batch", msg="denied")
            await meter.reconcile()
            assert meter.cleanup_status()["state"] == "retrying"
            await meter._cleanup_task
            return meter

        meter = run(body())
        assert env.fake.owned() == {} and meter.cleanup_status() == IDLE
        assert env.retry.sleeps == []  # the first retry goes at once

    def test_a_file_in_sys_class_net_is_not_an_interface(self, env):
        # bonding_masters is a plain file when the bonding module is loaded
        (env.net_dir / "bonding_masters").write_text("")

        async def body():
            await _start(env)
            env.meter.set_enabled(False)
            await env.meter._cleanup_task

        run(body())
        assert env.meter.cleanup_status() == IDLE
        assert not any("bonding_masters" in " ".join(a) for a, _ in env.fake.calls)

    def test_shutdown_cancels_a_waiting_retry(self, env):
        async def body():
            await _dirty_after_turn_off(env)
            task = env.meter._cleanup_task
            await env.meter.shutdown()  # its own final clean-up succeeds
            return task

        task = run(body())
        assert task.cancelled() and env.meter._cleanup_task is None
        assert env.fake.owned() == {} and env.meter.cleanup_status() == IDLE

    def test_an_unexpected_error_keeps_the_clean_up_retrying(self, env):
        # py review B: e.g. a dump shape we can't read must not end the task with _dirty set
        calls = []

        async def body():
            await _start(env)
            real = env.meter._clear_locked

            async def once(names):
                calls.append(names)
                if len(calls) == 1:
                    raise RuntimeError("odd dump")
                await real(names)

            env.meter._clear_locked = once
            env.meter.set_enabled(False)
            await env.meter._cleanup_task

        run(body())
        assert len(calls) == 2
        assert env.fake.owned() == {} and env.meter.cleanup_status() == IDLE

    def test_shutdown_still_cleans_up_after_a_clean_up_task_died(self, env):
        async def body():
            await _start(env)

            async def died():
                raise RuntimeError("died")

            env.meter._cleanup_task = asyncio.create_task(died())
            await asyncio.sleep(0)
            await env.meter.shutdown()

        run(body())
        assert env.fake.owned() == {}
