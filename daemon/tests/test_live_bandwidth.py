"""NET-205: the live bandwidth meter's lifecycle, rate math and failure paths, against a fake tc."""

import asyncio
from types import SimpleNamespace

import pytest

import services.live_bandwidth as lb
from services.capture_manager import CaptureMode
from services.live_bandwidth import (
    AT_CAPACITY,
    BUSY,
    CAPTURE_CHANGING,
    FOREIGN_RULE,
    STARTING,
    UNSUPPORTED,
    LiveBandwidthBusyError,
    LiveBandwidthError,
    LiveBandwidthMeter,
)
from services.live_bandwidth_tc import Key, cookie_for, parse_cookie
from tests.live_bandwidth_fake import Clock, FakeTc, Manager

MAC_A = Key("mac", "02:00:00:00:00:0a")
MAC_B = Key("mac", "02:00:00:00:00:0b")
IP_A = Key("ip", "192.168.1.5")
WALL = 1_700_000_000.0
# pref per counter, as live_bandwidth_tc.PREFS
MAC_DOWN, MAC_UP, IP_DOWN, IP_UP, VLAN_DOWN, VLAN_UP = range(49152, 49158)


def _iface(net_dir, name, state="up"):
    (net_dir / name).mkdir(exist_ok=True)
    (net_dir / name / "operstate").write_text(state + "\n")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A meter wired to a fake tc on enp4s0 (eth9 exists too), driven by a hand clock."""
    net_dir = tmp_path / "net"
    net_dir.mkdir()
    _iface(net_dir, "enp4s0")
    _iface(net_dir, "eth9")
    clock = Clock()
    holder = SimpleNamespace(manager=Manager(), capture_lock=None)
    fake = FakeTc(clock, ifaces=("enp4s0", "eth9"))
    monkeypatch.setattr(lb, "run_tool", fake.run)

    # Clean-up retries record their delay and don't wait, unless a test sets retry.gate:
    # then each gate.set() lets exactly one retry through.
    retry = SimpleNamespace(sleeps=[], gate=None)

    async def sleep(delay):
        retry.sleeps.append(delay)
        if retry.gate is not None:
            await retry.gate.wait()
            retry.gate.clear()
        await asyncio.sleep(0)

    def make(autostart=False, enabled=True):
        return LiveBandwidthMeter(
            get_manager=lambda: holder.manager,
            get_capture_lock=lambda: holder.capture_lock,
            clock=clock,
            wall=lambda: WALL,
            net_dir=str(net_dir),
            autostart=autostart,
            enabled=enabled,
            sleep=sleep,
        )

    return SimpleNamespace(
        meter=make(),
        make=make,
        fake=fake,
        clock=clock,
        holder=holder,
        net_dir=net_dir,
        retry=retry,
    )


def run(coro):
    return asyncio.run(coro)


async def _start(env, key=MAC_A):
    await env.meter.reconcile()
    return await env.meter.watch(key)


async def _tick(env, dt=2.0):
    env.clock.t += dt
    await env.meter.tick_once()


def _cookies(fake, iface="enp4s0"):
    return {parse_cookie(f["cookie"]) for f in fake.owned(iface).values()}


class TestAdmission:
    def test_refused_until_startup_cleanup_ran(self, env):
        with pytest.raises(LiveBandwidthBusyError, match=STARTING):
            run(env.meter.watch(MAC_A))
        assert env.fake.calls == []

    def test_first_poll_adds_clsact_and_two_mac_filters(self, env):
        snap = run(_start(env))
        assert env.fake.qdiscs["enp4s0"] == {"clsact"}
        assert set(env.fake.owned()) == {(MAC_DOWN, 1), (MAC_UP, 1)}
        assert _cookies(env.fake) == {(0, 1)}
        assert snap["supported"] is True and snap["interface"] == "enp4s0"
        assert snap["key"] == {"kind": "mac", "value": MAC_A.value}
        assert snap["layer"] == "ethernet-payload"
        assert snap["offloads"] == {"gro": False, "lro": False}
        assert snap["measuring_since"] == int(WALL * 1000)
        assert len(snap["samples"]) == 150
        assert snap["latest"]["down_bps"] is None

    def test_existing_clsact_is_reused(self, env):
        env.fake.qdiscs["enp4s0"].add("clsact")
        run(_start(env))
        assert "qdisc-add" not in env.fake.verbs()

    def test_viewers_share_a_watch_and_a_new_device_takes_the_next_slot(self, env):
        async def body():
            await _start(env)
            await env.meter.watch(MAC_A)
            await env.meter.watch(MAC_B)

        run(body())
        assert env.fake.verbs().count("add-batch") == 2
        assert set(env.fake.owned()) == {
            (MAC_DOWN, 1),
            (MAC_UP, 1),
            (MAC_DOWN, 2),
            (MAC_UP, 2),
        }

    def test_ip_watch_counts_plain_and_tagged_frames(self, env):
        run(_start(env, IP_A))
        assert set(env.fake.owned()) == {
            (p, 1) for p in (IP_DOWN, IP_UP, VLAN_DOWN, VLAN_UP)
        }

    def test_at_most_eight_watches(self, env):
        async def body():
            await env.meter.reconcile()
            for n in range(lb.MAX_WATCHED):
                await env.meter.watch(Key("mac", f"02:00:00:00:01:{n:02x}"))
            with pytest.raises(LiveBandwidthBusyError, match=AT_CAPACITY):
                await env.meter.watch(MAC_A)

        run(body())
        assert env.fake.verbs().count("add-batch") == lb.MAX_WATCHED

    def test_one_waiter_at_most_and_the_rest_are_told_busy(self, env):
        async def body():
            await env.meter.reconcile()
            await env.meter._lock.acquire()
            first = asyncio.create_task(env.meter.watch(MAC_A))
            await asyncio.sleep(0)
            with pytest.raises(LiveBandwidthBusyError, match=BUSY):
                await env.meter.watch(MAC_B)
            env.meter._lock.release()
            return await first

        assert run(body())["supported"] is True

    def test_lock_wait_is_capped(self, env, monkeypatch):
        monkeypatch.setattr(lb, "LOCK_WAIT_CAP_S", 0.05)

        async def body():
            await env.meter.reconcile()
            await env.meter._lock.acquire()
            with pytest.raises(LiveBandwidthBusyError, match=BUSY):
                await env.meter.watch(MAC_A)
            assert env.meter._waiters == 0

        run(body())

    def test_admission_deadline_bounds_every_tc_call(self, env):
        env.fake.call_cost["qdisc-show"] = lb.ADMISSION_DEADLINE_S + 1
        with pytest.raises(LiveBandwidthError, match="no time left"):
            run(_start(env))
        assert "add-batch" not in env.fake.verbs()

    def test_refused_while_capture_settings_change(self, env):
        async def body():
            await env.meter.reconcile()
            env.holder.capture_lock = asyncio.Lock()
            await env.holder.capture_lock.acquire()
            with pytest.raises(LiveBandwidthBusyError, match=CAPTURE_CHANGING):
                await env.meter.watch(MAC_A)

        run(body())
        assert env.fake.owned() == {}

    def test_capture_switch_during_install_rolls_back(self, env):
        original = env.fake._add_batch

        def add_then_switch(argv, stdin):
            out = original(argv, stdin)
            env.holder.manager.iface = "eth9"
            return out

        env.fake._add_batch = add_then_switch
        with pytest.raises(LiveBandwidthBusyError, match=CAPTURE_CHANGING):
            run(_start(env))
        assert (
            env.fake.owned() == {}
            and env.meter._watches == {}
            and not env.meter._pending
        )

    def test_failed_install_removes_its_partial_filters(self, env):
        async def body():
            await env.meter.reconcile()
            env.fake.add_lines_before_failing = 1
            with pytest.raises(LiveBandwidthError, match="Invalid argument"):
                await env.meter.watch(MAC_A)
            assert env.fake.owned() == {} and not env.meter._pending
            env.fake.add_lines_before_failing = None
            await env.meter.watch(MAC_A)

        run(body())
        assert set(env.fake.owned()) == {(MAC_DOWN, 1), (MAC_UP, 1)}  # slot 0 came back

    def test_failed_rollback_parks_the_slot_until_a_tick_removes_it(self, env):
        async def body():
            await env.meter.reconcile()
            env.fake.add_lines_before_failing = 1
            env.fake.fail(
                "dump", nth=2
            )  # the foreign check passes, the rollback's read fails
            with pytest.raises(LiveBandwidthError):
                await env.meter.watch(MAC_A)
            assert env.meter._pending == {0}
            env.fake.add_lines_before_failing = None
            await env.meter.watch(MAC_B)
            assert (MAC_DOWN, 2) in env.fake.owned()  # slot 0 stays parked
            await _tick(env)

        run(body())
        assert set(env.fake.owned()) == {(MAC_DOWN, 2), (MAC_UP, 2)}
        assert not env.meter._pending

    def test_admission_removes_nettap_filters_no_watch_owns(self, env):
        # sec review LOW-1: a stranded filter in a free slot made every install fail (File exists)
        async def body():
            await _start(env)
            env.meter._watches.clear()  # still installed, no owner
            return await env.meter.watch(MAC_B)

        run(body())
        assert _cookies(env.fake) == {(0, 2)}
        assert len(env.fake.owned()) == 2

    def test_broken_watch_is_removed_before_a_fresh_install(self, env):
        async def body():
            await _start(env)
            env.meter._watches[MAC_A].broken = True
            await env.meter.watch(MAC_A)

        run(body())
        assert _cookies(env.fake) == {(0, 2)}
        assert len(env.fake.owned()) == 2


class TestUnsupported:
    @pytest.mark.parametrize("mode", [CaptureMode.BRIDGE, CaptureMode.DHCP_GATEWAY])
    def test_bridge_and_gateway_modes_say_why(self, env, mode):
        env.holder.manager.mode = mode
        snap = run(env.meter.watch(MAC_A))
        assert snap == {
            "supported": False,
            "reason": UNSUPPORTED[mode],
            "mode": mode.value,
            "interface": "enp4s0",
            "key": MAC_A.as_dict(),
        }
        assert env.fake.calls == []

    def test_no_capture_manager_yet(self, env):
        env.holder.manager = None
        snap = run(env.meter.watch(MAC_A))
        assert snap["supported"] is False and snap["mode"] is None

    @pytest.mark.parametrize(
        "iface, expected",
        [("down", "is down"), ("eth7", "isn't there"), ("bad name", "isn't valid")],
    )
    def test_capture_interface_problems(self, env, iface, expected):
        if iface == "down":
            _iface(env.net_dir, "enp4s0", "down")
        else:
            env.holder.manager.iface = iface
        snap = run(env.meter.watch(MAC_A))
        assert snap["supported"] is False and expected in snap["reason"]
        assert env.fake.calls == []

    def test_a_plain_ingress_qdisc_is_someone_elses(self, env):
        env.fake.qdiscs["enp4s0"].add("ingress")
        snap = run(_start(env))
        assert snap["reason"] == FOREIGN_RULE.format(iface="enp4s0")
        assert "add-batch" not in env.fake.verbs()

    def test_a_foreign_filter_is_left_alone_and_nothing_is_added(self, env):
        env.fake.add_foreign("enp4s0")
        snap = run(_start(env))
        assert snap["supported"] is False and "Another traffic rule" in snap["reason"]
        assert env.fake.filters["enp4s0"] == {
            (1, 1): env.fake.filters["enp4s0"][(1, 1)]
        }
        assert "add-batch" not in env.fake.verbs()


class TestSampling:
    def test_rate_is_the_counter_delta_over_the_interval(self, env):
        async def body():
            await _start(env)
            await _tick(env)
            env.fake.bump("enp4s0", MAC_DOWN, 1, 1000)
            env.fake.bump("enp4s0", MAC_UP, 1, 250)
            await _tick(env)
            return await env.meter.watch(MAC_A)

        snap = run(body())
        assert snap["latest"] == {
            "tick": 2,
            "t": int(WALL * 1000),
            "mono": 1004.0,
            "bracket_ms": 0.0,
            "down_bps": 4000.0,
            "up_bps": 1000.0,
            "reason": None,
        }
        assert snap["latest_age_s"] == 0 and snap["last_valid_age_s"] == 0
        assert snap["samples"][-2]["reason"] == "Measuring…"
        assert snap["samples"][-3]["reason"] == "Not measuring yet."

    def test_ip_rate_adds_plain_and_tagged_counters(self, env):
        async def body():
            await _start(env, IP_A)
            await _tick(env)
            env.fake.bump("enp4s0", IP_DOWN, 1, 600)
            env.fake.bump("enp4s0", VLAN_DOWN, 1, 400)
            env.fake.bump("enp4s0", VLAN_UP, 1, 100)
            await _tick(env)
            return await env.meter.watch(IP_A)

        latest = run(body())["latest"]
        assert (latest["down_bps"], latest["up_bps"]) == (4000.0, 400.0)

    def test_a_late_tick_is_refused_and_the_gap_shows_as_missed(self, env):
        async def body():
            await _start(env)
            await _tick(env)
            await _tick(env, 6.0)
            return await env.meter.watch(MAC_A)

        samples = run(body())["samples"]
        assert samples[-1]["reason"] == "The counters were read at the wrong time."
        assert [s["reason"] for s in samples[-3:-1]] == ["Missed.", "Missed."]

    def test_slow_counter_reads_are_refused(self, env):
        env.fake.dump_cost = (
            0.03  # 30 ms per read: both brackets are 3 % of the interval
        )

        async def body():
            await _start(env)
            await _tick(env)
            await _tick(env)
            return await env.meter.watch(MAC_A)

        assert (
            run(body())["samples"][-1]["reason"]
            == "Reading the counters took too long."
        )

    def test_a_counter_that_goes_backwards_is_a_reset(self, env):
        async def body():
            await _start(env)
            env.fake.bump("enp4s0", MAC_DOWN, 1, 1000)
            await _tick(env)
            env.fake.filters["enp4s0"][(MAC_DOWN, 1)]["bytes"] = 10
            await _tick(env)
            return await env.meter.watch(MAC_A)

        assert run(body())["samples"][-1]["reason"] == "A counter was reset."

    @pytest.mark.parametrize("change", ["deleted", "other generation"])
    def test_a_missing_counter_restarts_the_watch(self, env, change):
        async def body():
            await _start(env)
            await _tick(env)
            if change == "deleted":
                del env.fake.filters["enp4s0"][(MAC_UP, 1)]
            else:
                env.fake.filters["enp4s0"][(MAC_UP, 1)]["cookie"] = cookie_for(0, 99)
            await _tick(env)

        run(body())
        assert MAC_A not in env.meter._watches  # broken, then reaped in the same tick
        assert (MAC_DOWN, 1) not in env.fake.owned()

    def test_a_foreign_rule_appearing_marks_every_watch(self, env):
        async def body():
            await _start(env)
            await _tick(env)
            env.fake.add_foreign("enp4s0")
            await _tick(env)
            return await env.meter.watch(MAC_A)

        snap = run(body())
        reason = FOREIGN_RULE.format(iface="enp4s0")
        assert snap["samples"][-1]["reason"] == reason
        assert snap["latest"]["reason"] == reason  # its own reason, not "late"

    def test_a_stalled_sampler_reads_as_late_whatever_the_last_reason(self, env):
        async def body():
            await _start(env)
            await _tick(env)  # "Measuring…", then no tick for 6 s
            env.clock.t += 6
            return await env.meter.watch(MAC_A)

        assert "late" in run(body())["latest"]["reason"]

    def test_capture_change_during_a_tick_marks_every_watch(self, env):
        async def body():
            await _start(env)
            env.holder.capture_lock = asyncio.Lock()
            await env.holder.capture_lock.acquire()
            await _tick(env)
            return env.meter._snapshot(env.meter._watches[MAC_A])

        assert run(body())["samples"][-1]["reason"] == CAPTURE_CHANGING

    def test_a_failed_read_marks_every_watch(self, env):
        async def body():
            await _start(env)
            env.fake.fail("dump")
            await _tick(env)
            return await env.meter.watch(MAC_A)

        reason = run(body())["samples"][-1]["reason"]
        assert reason.startswith("Couldn't read the counters")

    def test_new_capture_interface_retires_watches_on_the_old_one(self, env):
        async def body():
            await _start(env)
            env.holder.manager.iface = "eth9"
            await _tick(env)
            assert env.meter._watches == {}
            return await env.meter.watch(MAC_A)

        snap = run(body())
        assert env.fake.owned("enp4s0") == {}
        assert set(env.fake.owned("eth9")) == {(MAC_DOWN, 1), (MAC_UP, 1)}
        assert snap["interface"] == "eth9"
        assert env.fake.verbs().count("ethtool") == 2

    def test_admission_waits_until_the_old_interface_is_cleared(self, env):
        # py review A: a new interface must not replace the old one while a watch sits there
        async def body():
            await _start(env)
            env.holder.manager.iface = "eth9"
            with pytest.raises(LiveBandwidthBusyError, match=CAPTURE_CHANGING):
                await env.meter.watch(MAC_B)
            await _tick(env)  # retires MAC_A on enp4s0
            return await env.meter.watch(MAC_B)

        snap = run(body())
        assert env.fake.owned("enp4s0") == {}
        assert snap["interface"] == "eth9"

    def test_headline_goes_blank_when_the_counters_are_late(self, env):
        async def body():
            await _start(env)
            await _tick(env)
            env.fake.bump("enp4s0", MAC_DOWN, 1, 1000)
            await _tick(env)
            env.clock.t += 6
            return await env.meter.watch(MAC_A)

        snap = run(body())
        assert snap["latest"]["down_bps"] is None and "late" in snap["latest"]["reason"]
        assert (
            snap["samples"][-1]["down_bps"] == 4000.0
        )  # the chart keeps the last point
        assert snap["latest_age_s"] == 6.0 and snap["last_valid_age_s"] == 6.0

    def test_history_keeps_five_minutes(self, env):
        async def body():
            await _start(env)
            for _ in range(160):
                await env.meter.watch(MAC_A)
                await _tick(env)
            return await env.meter.watch(MAC_A)

        snap = run(body())
        ticks = [s["tick"] for s in snap["samples"]]
        assert len(ticks) == 150 and ticks[-1] - ticks[0] == 149
        assert len(env.meter._ticks) == 150
        assert len(env.meter._watches[MAC_A].samples) == 150


class TestLifecycle:
    def test_an_unwatched_device_stops_after_fifteen_seconds(self, env):
        async def body():
            await _start(env)
            await _tick(env, 14)
            assert MAC_A in env.meter._watches
            await _tick(env, 2)

        run(body())
        assert env.meter._watches == {} and env.fake.owned() == {}

    def test_a_poll_during_removal_starts_a_fresh_watch(self, env):
        async def body():
            await _start(env)
            env.clock.t += 16
            env.fake.gate = asyncio.Event()
            ticking = asyncio.create_task(env.meter.tick_once())
            await env.fake.at_gate.wait()  # the reaper is mid-delete, holding the lock
            assert env.meter._watches[MAC_A].state == "retiring"
            poll = asyncio.create_task(env.meter.watch(MAC_A))
            for _ in range(5):
                await asyncio.sleep(0)
            assert not poll.done()  # a retiring watch takes no keepalive
            env.fake.gate.set()
            await ticking
            return await poll

        assert run(body())["supported"] is True
        assert env.meter._watches[MAC_A].gen == 2
        assert _cookies(env.fake) == {(0, 2)} and len(env.fake.owned()) == 2

    def test_startup_cleanup_removes_only_netTap_filters_on_every_interface(self, env):
        env.fake.add_foreign("eth9")
        env.fake.filters["eth9"][(MAC_DOWN, 4)] = {
            "protocol": "all", "cookie": cookie_for(3, 42), "bytes": 9, "packets": 1,
        }  # fmt: skip
        env.fake.qdiscs["enp4s0"].add("clsact")
        env.fake.filters["enp4s0"][(IP_DOWN, 1)] = {
            "protocol": "ip", "cookie": cookie_for(0, 7), "bytes": 9, "packets": 1,
        }  # fmt: skip
        (env.net_dir / "bad name").mkdir()  # never handed to tc
        run(env.meter.reconcile())
        assert env.fake.owned("eth9") == {} and env.fake.owned("enp4s0") == {}
        assert (1, 1) in env.fake.filters["eth9"]  # someone else's rule stays
        assert env.fake.qdiscs == {"enp4s0": {"clsact"}, "eth9": {"clsact"}}

    def test_delete_never_touches_a_filter_without_our_cookie(self, env):
        env.fake.add_foreign(
            "enp4s0", pref=MAC_DOWN, handle=1
        )  # in our pref, but not ours
        env.fake.filters["enp4s0"][(MAC_UP, 1)] = {
            "protocol": "all", "cookie": cookie_for(0, 1), "bytes": 0, "packets": 0,
        }  # fmt: skip

        async def body():
            entries = await env.meter._dump("enp4s0")
            await env.meter._delete("enp4s0", entries, 1.0)

        run(body())
        assert set(env.fake.filters["enp4s0"]) == {(MAC_DOWN, 1)}

    def test_shutdown_stops_the_sampler_and_removes_filters(self, env):
        env.meter = env.make(autostart=True)

        async def body():
            await _start(env)
            assert env.meter._task is not None and not env.meter._task.done()
            await env.meter.shutdown()
            assert env.meter._task is None

        run(body())
        assert env.fake.owned() == {}

    def test_a_slot_parked_with_no_other_watch_is_still_retried(self, env):
        # py review #1: nothing else would start the sampler that retries it
        env.meter = env.make(autostart=True)
        env.retry.gate = asyncio.Event()

        async def body():
            await env.meter.reconcile()
            env.fake.add_lines_before_failing = 1
            env.fake.fail("dump", nth=2)  # the rollback's read fails
            with pytest.raises(LiveBandwidthError):
                await env.meter.watch(MAC_A)
            assert env.meter._pending == {0} and env.meter._watches == {}
            assert env.fake.owned() != {}  # half an install, still counting
            task = env.meter._task
            assert task is not None and not task.done()
            env.fake.add_lines_before_failing = None
            env.clock.t += 2.0
            env.retry.gate.set()
            # one tick removes it; with nothing left, the sampler ends
            await asyncio.wait_for(task, 1)

        run(body())
        assert env.fake.owned() == {} and not env.meter._pending

    def test_the_sampler_survives_a_tick_that_raises(self, env):
        env.meter = env.make(autostart=True)
        env.retry.gate = asyncio.Event()

        async def body():
            await _start(env)
            real, calls = env.meter.tick_once, []

            async def flaky():
                calls.append(1)
                if len(calls) == 1:
                    raise RuntimeError("boom")
                await real()

            env.meter.tick_once = flaky
            for _ in range(2):
                env.clock.t += 2.0
                env.retry.gate.set()
                for _ in range(20):
                    await asyncio.sleep(0)
            assert len(calls) == 2 and not env.meter._task.done()
            await env.meter.shutdown()

        run(body())

    def test_a_dead_sampler_is_restarted_by_the_next_poll(self, env):
        env.meter = env.make(autostart=True)

        async def body():
            await _start(env)
            dead = env.meter._task
            dead.cancel()
            with pytest.raises(asyncio.CancelledError):
                await dead
            await env.meter.watch(MAC_A)
            assert env.meter._task is not dead and not env.meter._task.done()
            await env.meter.shutdown()

        run(body())
