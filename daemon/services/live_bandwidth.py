"""
Live per-device bandwidth from kernel byte counters on the capture interface (NET-205).

A watch counts one device, keyed by its MAC (the MAC device page) or by an IPv4 address (the IP
device page), with tc flower filters on the capture interface's ingress hook (see
live_bandwidth_tc.py). Every 2 s one counter dump turns into a download and upload rate per watch.

Mirror mode only: in bridge mode NetTap sits in front of the router and sees only its public
address, and in DHCP gateway mode NetTap's own NAT readdresses replies before tc can see them.

Opt-in (NET-205): the meter does nothing until the user turns it on in Settings › Capture. Turning
it off ends every watch and removes every NetTap filter in the background; an interface whose
filters couldn't be removed stays "dirty" and is retried, and no watch starts while any is dirty.

Lifecycle: a poll is the keepalive. The first poll for a device starts a watch (admission); the
watch is shared by every viewer and ends 15 s after the last poll. At most MAX_WATCHED watches run.

Everything runs on the daemon's one asyncio loop. One lock covers admission, every tc change,
sample publication and removal; a keepalive for an active watch never waits on it. Every tc call
has its own deadline, and admission has an overall one, so a request always answers before the
web proxy's 10 s limit.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from services.capture_manager import CaptureMode
from services.dhcp_gateway_net import validate_interface_name
from services.live_bandwidth_tc import (
    COUNTERS,
    OWNED_PREFS,
    PREFS,
    FilterEntry,
    Key,
    TcError,
    build_filter_lines,
    delete_args,
    foreign_filters,
    handle_for,
    has_ingress_qdisc,
    parse_cookie,
    parse_filter_dump,
    parse_offloads,
    run_tool,
)

logger = logging.getLogger("nettap.live_bandwidth")

TICK_S = 2.0
HISTORY_TICKS = 150  # 5 minutes
IDLE_TIMEOUT_S = 15.0
FRESH_S = 5.0
MAX_WATCHED = 8
INTERVAL_RANGE_S = (1.5, 4.0)
TIMING_BUDGET = 0.02  # both read brackets together, as a share of the interval
ADMISSION_DEADLINE_S = 6.0
LOCK_WAIT_CAP_S = 1.5
DUMP_TIMEOUT_S = 1.0
BATCH_TIMEOUT_S = 4.0
LAYER = "ethernet-payload"
# The host's sysfs, as every other daemon reader of interfaces (docker-compose mounts /sys there)
SYS_NET = os.environ.get("HOST_SYS_NET", "/host/sys/class/net")

AT_CAPACITY = "Too many live views are open. Close one and try again."
BUSY = "Live bandwidth is busy. Try again in a moment."
STARTING = "Starting…"
CAPTURE_CHANGING = "Capture settings are changing."
CLEANING = "Removing earlier counters; trying again in a moment."
OFF_REASON = "Live bandwidth is off. Turn it on in Settings › Capture."
CLEANUP_RETRY_S = 10.0
CLEANUP_RETRY_SLOW_S = 60.0
CLEANUP_FAST_TRIES = 30
FOREIGN_RULE = (
    "Another traffic rule on {iface} runs first, so NetTap can't count reliably."
)
UNSUPPORTED = {
    CaptureMode.BRIDGE: (
        "In bridge mode NetTap sits in front of your router and sees only its public address, "
        "so it can't split the rate by device."
    ),
    CaptureMode.DHCP_GATEWAY: (
        "In gateway mode NetTap translates addresses itself, so live rates per device "
        "aren't available yet."
    ),
}


class LiveBandwidthBusyError(Exception):
    """Admission refused for now (busy, at capacity, starting, capture changing): HTTP 503."""


class LiveBandwidthError(Exception):
    """tc failed while starting a watch: HTTP 500."""


class _Unsupported(Exception):
    """This capture setup can't measure per device; the message is the reason."""


@dataclass(frozen=True)
class _Reading:
    down: int
    up: int
    mid: float
    bracket: float


@dataclass(frozen=True)
class _Tick:
    mono: float
    bracket_ms: float
    wall_ms: int


@dataclass
class _Watch:
    key: Key
    slot: int
    gen: int
    last_seen: float
    since_ms: int
    start_tick: int
    state: str = "active"  # active -> retiring (removal decided, before any await)
    broken: bool = False
    prev: _Reading | None = None
    samples: dict[int, dict[str, Any]] = field(default_factory=dict)


def owned_entries(entries: list[FilterEntry]) -> list[FilterEntry]:
    """The filters NetTap owns: a NetTap cookie on one of its prefs."""
    return [e for e in entries if parse_cookie(e.cookie) and e.pref in OWNED_PREFS]


def _null(reason: str) -> dict[str, Any]:
    return {"down_bps": None, "up_bps": None, "reason": reason}


class LiveBandwidthMeter:
    """Owns NetTap's tc filters on the capture interface and the per-device rate history."""

    def __init__(
        self,
        get_manager: Callable[[], Any],
        get_capture_lock: Callable[[], asyncio.Lock | None],
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        net_dir: str = SYS_NET,
        autostart: bool = True,
        enabled: bool = False,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._get_manager = get_manager
        self._get_capture_lock = get_capture_lock
        self._clock = clock
        self._wall = wall
        self._net_dir = net_dir
        self._autostart = autostart  # tests drive tick_once() by hand
        self._epoch = clock()
        self._lock = asyncio.Lock()
        self._waiters = 0
        self._watches: dict[Key, _Watch] = {}
        self._pending: set[int] = set()  # slots whose filters couldn't be removed yet
        self._gen = 0
        self._identity: tuple | None = None
        self._iface: str | None = None
        self._offloads: dict[str, bool | None] = {"gro": None, "lro": None}
        self._ticks: dict[int, _Tick] = {}
        self._last_tick: int | None = None
        self._reconciled = False
        self._task: asyncio.Task | None = None
        # Opt-in state. _transition counts on/off changes, so an admission that awaited across
        # one can tell; _dirty maps interface -> why its NetTap filters couldn't be removed.
        self._enabled = enabled
        self._transition = 0
        self._dirty: dict[str, str] = {}
        self._cleanup_task: asyncio.Task | None = None
        self._cleanup_again = False
        self._sleep = sleep

    # ------------------------------------------------------------------ support and identity

    def support(self) -> tuple[CaptureMode | None, str | None, str | None]:
        """(mode, interface, reason it can't measure, or None)."""
        manager = self._get_manager()
        if manager is None:
            return None, None, "Capture isn't set up yet."
        mode, iface = manager.mode, manager.get_capture_interface()
        if mode in UNSUPPORTED:
            return mode, iface, UNSUPPORTED[mode]
        try:
            validate_interface_name(iface)
        except ValueError:
            return mode, iface, "The capture interface name isn't valid."
        try:
            with open(os.path.join(self._net_dir, iface, "operstate")) as handle:
                state = handle.read().strip()
        except OSError:
            return mode, iface, f"The capture interface {iface} isn't there."
        if state == "down":
            return mode, iface, f"The capture interface {iface} is down."
        return mode, iface, None

    def _identity_now(self) -> tuple | None:
        manager = self._get_manager()
        if manager is None:
            return None
        return (id(manager), manager.mode, manager.get_capture_interface())

    def _capture_changing(self) -> bool:
        lock = self._get_capture_lock()
        return bool(lock is not None and lock.locked())

    def _tick_index(self, now: float) -> int:
        return int((now - self._epoch) // TICK_S)

    def _cleaning(self) -> bool:
        """A clean-up is queued or running, or an interface still holds NetTap filters."""
        running = self._cleanup_task is not None and not self._cleanup_task.done()
        return running or bool(self._dirty)

    def _current(self, transition: int) -> bool:
        return self._enabled and self._transition == transition

    # ------------------------------------------------------------------ public API

    @property
    def enabled(self) -> bool:
        return self._enabled

    def cleanup_status(self) -> dict[str, Any]:
        """idle, running (a clean-up is under way) or retrying (an interface failed), and why."""
        if self._dirty:
            state = "retrying"
        elif self._cleanup_task is not None and not self._cleanup_task.done():
            state = "running"
        else:
            state = "idle"
        return {"state": state, "failed": dict(self._dirty)}

    def set_enabled(self, on: bool) -> None:
        """Turn the meter on or off at once; turning off removes every filter in the background."""
        if on == self._enabled:
            return
        self._enabled = on
        self._transition += 1
        if not on:
            self._schedule_cleanup(everything=True)

    async def watch(self, key: Key) -> dict[str, Any]:
        """Keep a watch alive (starting it if needed) and return its snapshot."""
        if not self._enabled:
            return self._off(key)
        current = self._watches.get(key)
        if current is not None and current.state == "active" and not current.broken:
            current.last_seen = self._clock()
            self._ensure_sampler()
            return self._snapshot(current)
        mode, iface, reason = self.support()
        if reason:
            return self._unsupported(key, mode, iface, reason)
        return await self._admit(key)

    async def reconcile(self, retry: bool = True) -> None:
        """Delete every NetTap filter on every interface (startup, shutdown), on or off."""
        async with self._lock:
            await self._clear_locked(self._interfaces())
            self._reconciled = True
        if retry and self._dirty:
            self._schedule_cleanup(everything=False)

    async def shutdown(self, _app: Any = None) -> None:
        """Stop sampling and remove NetTap's filters (aiohttp on_cleanup)."""
        for task in (self._task, self._cleanup_task):
            if task is not None:
                task.cancel()
                # a task that died with an error must not skip the final clean-up (py review B)
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        self._task = self._cleanup_task = None
        await self.reconcile(retry=False)

    # ------------------------------------------------------------------ clean-up

    def _schedule_cleanup(self, everything: bool) -> None:
        """One clean-up task at a time; a request while it runs makes it go round again."""
        if self._cleanup_task is not None and not self._cleanup_task.done():
            self._cleanup_again = self._cleanup_again or everything
            return
        self._cleanup_task = asyncio.create_task(
            self._cleanup_loop(everything), name="live-bandwidth-cleanup"
        )

    async def _cleanup_loop(self, everything: bool) -> None:
        """Clear every interface (or the dirty ones), then retry the dirty ones until clean."""
        tries = 0
        while True:
            async with self._lock:
                names = self._interfaces() if everything else sorted(self._dirty)
                try:
                    await self._clear_locked(names)
                # e.g. a dump we can't read: stay dirty and keep retrying (py review B)
                except Exception as exc:
                    logger.exception("Live bandwidth clean-up failed")
                    for name in names:
                        self._dirty.setdefault(name, f"Unexpected error: {exc}")
            everything, self._cleanup_again = self._cleanup_again, False
            if everything:
                continue
            if not self._dirty:
                return
            tries += 1
            delay = (
                CLEANUP_RETRY_S if tries <= CLEANUP_FAST_TRIES else CLEANUP_RETRY_SLOW_S
            )
            await self._sleep(delay)

    async def _clear_locked(self, names: list[str]) -> None:
        """Remove NetTap's filters on these interfaces and forget every watch. Caller holds the lock.

        An interface is clean only after a dump shows none of NetTap's filters, or when it no
        longer exists (kernel filters go with their device). Any other failure leaves it dirty.
        """
        for iface in names:
            try:
                removed = await self._delete(
                    iface, await self._dump(iface), DUMP_TIMEOUT_S * 2
                )
                if removed and owned_entries(await self._dump(iface)):
                    raise TcError("NetTap filters are still there after removal")
                if removed:
                    logger.info("Removed %d NetTap filter(s) from %s", removed, iface)
                if self._dirty.pop(iface, None) is not None:
                    logger.info("NetTap filters on %s are gone now", iface)
            except TcError as exc:
                if not os.path.exists(os.path.join(self._net_dir, iface)):
                    if self._dirty.pop(iface, None) is not None:
                        logger.info(
                            "%s no longer exists, so its filters are gone", iface
                        )
                    continue
                if iface not in self._dirty:
                    logger.warning(
                        "Couldn't remove NetTap filters on %s: %s", iface, exc
                    )
                self._dirty[iface] = str(exc)
        self._watches.clear()
        self._pending.clear()
        self._identity = None

    # ------------------------------------------------------------------ admission

    async def _admit(self, key: Key) -> dict[str, Any]:
        if not self._reconciled:
            raise LiveBandwidthBusyError(STARTING)
        if self._cleaning():
            raise LiveBandwidthBusyError(CLEANING)
        transition = self._transition
        if self._capture_changing():
            raise LiveBandwidthBusyError(CAPTURE_CHANGING)
        if self._lock.locked() and self._waiters >= 1:
            raise LiveBandwidthBusyError(BUSY)
        deadline = self._clock() + ADMISSION_DEADLINE_S
        self._waiters += 1
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=LOCK_WAIT_CAP_S)
        except asyncio.TimeoutError as exc:
            raise LiveBandwidthBusyError(BUSY) from exc
        finally:
            self._waiters -= 1
        try:
            return await self._admit_locked(key, deadline, transition)
        finally:
            self._lock.release()

    def _crossed(self, key: Key) -> dict[str, Any]:
        """An admission that awaited across an on/off change: off if off now, else retry."""
        if not self._enabled:
            return self._off(key)
        raise LiveBandwidthBusyError(CLEANING)

    async def _admit_locked(
        self, key: Key, deadline: float, transition: int
    ) -> dict[str, Any]:
        if not self._current(transition):
            return self._crossed(key)
        if self._cleaning():
            raise LiveBandwidthBusyError(CLEANING)
        current = self._watches.get(key)
        if current is not None and current.state == "active" and not current.broken:
            current.last_seen = self._clock()
            return self._snapshot(current)
        if current is not None:  # broken: remove its filters before a fresh install
            current.state = "retiring"
            await self._remove(current)
        mode, iface, reason = self.support()
        if reason:
            return self._unsupported(key, mode, iface, reason)
        if self._capture_changing():
            raise LiveBandwidthBusyError(CAPTURE_CHANGING)
        slot = self._free_slot()
        try:
            await self._prepare(iface, deadline)
        except _Unsupported as exc:
            return self._unsupported(key, mode, iface, str(exc))
        except TcError as exc:
            raise LiveBandwidthError(f"Couldn't start measuring: {exc}") from exc
        if not self._current(transition):
            return self._crossed(key)
        self._gen += 1
        watch = await self._install(key, iface, slot, self._gen, deadline)
        if not self._current(transition):  # turned off (and maybe on) while installing
            del self._watches[key]
            await self._rollback(iface, slot, watch.gen, deadline)
            return self._crossed(key)
        self._ensure_sampler()
        logger.info("Live bandwidth watch started: %s %s on %s (slot %d)",
                    key.kind, key.value, iface, slot)  # fmt: skip
        return self._snapshot(watch)

    def _free_slot(self) -> int:
        used = {w.slot for w in self._watches.values()} | self._pending
        for slot in range(MAX_WATCHED):
            if slot not in used:
                return slot
        raise LiveBandwidthBusyError(AT_CAPACITY)

    async def _prepare(self, iface: str, deadline: float) -> None:
        """clsact present, no foreign rule, offloads read for this capture identity."""
        if self._watches and self._identity_now() != self._identity:
            # the capture interface changed: the next tick removes the old interface's watches
            # there first; moving _iface now would strand their filters (py review A)
            raise LiveBandwidthBusyError(CAPTURE_CHANGING)
        qdiscs = await run_tool(
            ["tc", "-j", "qdisc", "show", "dev", iface], self._left(deadline)
        )
        clsact, plain_ingress = has_ingress_qdisc(qdiscs)
        if plain_ingress:
            raise _Unsupported(FOREIGN_RULE.format(iface=iface))
        if not clsact:
            await run_tool(
                ["tc", "qdisc", "add", "dev", iface, "clsact"], self._left(deadline)
            )
        if foreign_filters(await self._dump(iface, self._left(deadline))):
            raise _Unsupported(FOREIGN_RULE.format(iface=iface))
        identity = self._identity_now()
        if identity != self._identity:
            try:
                text = await run_tool(["ethtool", "-k", iface], self._left(deadline))
                self._offloads = parse_offloads(text)
            except TcError as exc:
                logger.warning("Couldn't read offloads on %s: %s", iface, exc)
                self._offloads = {"gro": None, "lro": None}
            if self._offloads.get("gro"):
                logger.warning("GRO is on for %s; live rates read about 3%% low", iface)
            self._identity, self._iface = identity, iface

    async def _install(
        self, key: Key, iface: str, slot: int, gen: int, deadline: float
    ) -> _Watch:
        lines = "\n".join(build_filter_lines(iface, key, slot, gen)) + "\n"
        try:
            await run_tool(
                ["tc", "-batch", "-"], min(BATCH_TIMEOUT_S, self._left(deadline)), lines
            )
        except TcError as exc:
            await self._rollback(iface, slot, gen, deadline)
            raise LiveBandwidthError(f"Couldn't start measuring: {exc}") from exc
        if self._capture_changing() or self._identity_now() != self._identity:
            await self._rollback(iface, slot, gen, deadline)
            raise LiveBandwidthBusyError(CAPTURE_CHANGING)
        now = self._clock()
        watch = _Watch(
            key=key,
            slot=slot,
            gen=gen,
            last_seen=now,
            since_ms=int(self._wall() * 1000),
            start_tick=self._tick_index(now),
        )
        self._watches[key] = watch
        return watch

    async def _rollback(self, iface: str, slot: int, gen: int, deadline: float) -> None:
        """Remove what one admission added; if that fails, park the slot for the supervisor."""
        try:
            entries = await self._dump(iface, max(0.2, self._left(deadline)))
            mine = [e for e in entries if parse_cookie(e.cookie) == (slot, gen)]
            await self._delete(iface, mine, max(0.2, self._left(deadline)))
        except TcError as exc:
            logger.warning("Couldn't roll back slot %d on %s: %s", slot, iface, exc)
            self._pending.add(slot)
            self._ensure_sampler()  # with no other watch, nothing else would retry it (py review #1)

    def _left(self, deadline: float) -> float:
        return deadline - self._clock()

    # ------------------------------------------------------------------ tc helpers

    def _interfaces(self) -> list[str]:
        try:
            names = sorted(os.listdir(self._net_dir))
        except OSError:
            return []
        valid = []
        for name in names:
            # bonding_masters is a plain file there, and tc can never clean it (ponytail #1)
            if not os.path.isdir(os.path.join(self._net_dir, name)):
                continue
            try:
                valid.append(validate_interface_name(name))
            except ValueError:
                continue
        return valid

    async def _dump(
        self, iface: str, timeout: float = DUMP_TIMEOUT_S
    ) -> list[FilterEntry]:
        args = ["tc", "-s", "-j", "filter", "show", "dev", iface, "ingress"]
        return parse_filter_dump(await run_tool(args, timeout))

    async def _delete(
        self, iface: str, entries: list[FilterEntry], timeout: float
    ) -> int:
        """Delete the owned ones among entries by exact identity, in one tc call; how many."""
        owned = owned_entries(entries)
        if owned:
            lines = "".join(
                " ".join(delete_args(iface, e.pref, e.handle)) + "\n" for e in owned
            )
            await run_tool(["tc", "-batch", "-"], timeout, lines)
        return len(owned)

    # ------------------------------------------------------------------ sampling

    def _ensure_sampler(self) -> None:
        """Start the sampler, or restart it if it died (the supervisor)."""
        if self._autostart and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self._run_sampler(), name="live-bandwidth")

    async def _run_sampler(self) -> None:
        while self._watches or self._pending:
            now = self._clock()
            next_at = self._epoch + (self._tick_index(now) + 1) * TICK_S
            await self._sleep(max(0.0, next_at - now))
            try:
                await self.tick_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Live bandwidth tick failed")

    async def tick_once(self) -> None:
        """One sampler tick: sample, then reap idle or broken watches and retry parked slots."""
        async with self._lock:
            tick = self._tick_index(self._clock())
            try:
                await self._sample(tick)
            except TcError as exc:
                logger.warning("Live bandwidth sample failed: %s", exc)
                self._mark_all(tick, f"Couldn't read the counters: {exc}")
            finally:
                self._last_tick = tick
                self._prune(tick)
                await self._reap()
                await self._retry_pending()

    async def _sample(self, tick: int) -> None:
        if not self._watches:
            return
        if self._capture_changing():
            self._mark_all(tick, CAPTURE_CHANGING)
            return
        if self._identity_now() != self._identity:
            logger.warning("Capture interface changed; live bandwidth watches restart")
            for watch in self._watches.values():
                watch.broken = True
            return
        iface = self._iface
        start = self._clock()
        entries = await self._dump(iface)
        end = self._clock()
        if foreign_filters(entries):
            self._mark_all(tick, FOREIGN_RULE.format(iface=iface))
            return
        mid, bracket = (start + end) / 2, end - start
        self._ticks[tick] = _Tick(mid, bracket * 1000, int(self._wall() * 1000))
        by_id = {(e.pref, e.handle): e for e in entries}
        for watch in self._watches.values():
            if watch.state == "active":
                watch.samples[tick] = self._rate(watch, by_id, mid, bracket)

    def _rate(
        self, watch: _Watch, by_id: dict, mid: float, bracket: float
    ) -> dict[str, Any]:
        totals = {}
        for direction in ("down", "up"):
            total = 0
            for part in COUNTERS[watch.key.kind][direction]:
                entry = by_id.get((PREFS[part][0], handle_for(watch.slot)))
                if (
                    entry is None
                    or parse_cookie(entry.cookie) != (watch.slot, watch.gen)
                    or entry.bytes is None
                ):
                    watch.prev, watch.broken = None, True
                    return _null("A counter for this device is missing; restarting it.")
                total += entry.bytes
            totals[direction] = total
        reading = _Reading(totals["down"], totals["up"], mid, bracket)
        prev, watch.prev = watch.prev, reading
        if prev is None:
            return _null("Measuring…")
        interval = mid - prev.mid
        if not INTERVAL_RANGE_S[0] <= interval <= INTERVAL_RANGE_S[1]:
            return _null("The counters were read at the wrong time.")
        if (prev.bracket + bracket) / interval > TIMING_BUDGET:
            return _null("Reading the counters took too long.")
        if reading.down < prev.down or reading.up < prev.up:
            return _null("A counter was reset.")
        return {
            "down_bps": (reading.down - prev.down) * 8 / interval,
            "up_bps": (reading.up - prev.up) * 8 / interval,
            "reason": None,
        }

    def _mark_all(self, tick: int, reason: str) -> None:
        for watch in self._watches.values():
            watch.samples[tick] = _null(reason)
            watch.prev = None

    def _prune(self, tick: int) -> None:
        oldest = tick - HISTORY_TICKS + 1
        self._ticks = {t: v for t, v in self._ticks.items() if t >= oldest}
        for watch in self._watches.values():
            watch.samples = {t: v for t, v in watch.samples.items() if t >= oldest}

    async def _reap(self) -> None:
        now = self._clock()
        for watch in list(self._watches.values()):
            if watch.state != "active":
                continue
            if watch.broken or now - watch.last_seen > IDLE_TIMEOUT_S:
                watch.state = (
                    "retiring"  # before any await: keepalives now go through admission
                )
                await self._remove(watch)

    async def _remove(self, watch: _Watch) -> None:
        iface = self._iface
        try:
            if iface:
                entries = await self._dump(iface)
                mine = [
                    e
                    for e in entries
                    if parse_cookie(e.cookie) == (watch.slot, watch.gen)
                ]
                await self._delete(iface, mine, DUMP_TIMEOUT_S * 2)
        except TcError as exc:
            logger.warning("Couldn't remove slot %d; retrying: %s", watch.slot, exc)
            self._pending.add(watch.slot)
            self._ensure_sampler()
        self._watches.pop(watch.key, None)
        logger.info(
            "Live bandwidth watch ended: %s %s", watch.key.kind, watch.key.value
        )

    async def _retry_pending(self) -> None:
        if not self._pending or not self._iface:
            return
        try:
            entries = await self._dump(self._iface)
            stale = [
                e
                for e in entries
                if (parse_cookie(e.cookie) or (-1, 0))[0] in self._pending
            ]
            await self._delete(self._iface, stale, DUMP_TIMEOUT_S * 2)
            self._pending.clear()
        except TcError as exc:
            logger.warning("Parked live bandwidth slots still not removed: %s", exc)

    # ------------------------------------------------------------------ responses

    def _off(self, key: Key) -> dict[str, Any]:
        manager = self._get_manager()
        mode = manager.mode if manager is not None else None
        iface = manager.get_capture_interface() if manager is not None else None
        return {**self._unsupported(key, mode, iface, OFF_REASON), "off": True}

    def _unsupported(
        self, key: Key, mode: CaptureMode | None, iface: str | None, reason: str
    ):
        return {
            "supported": False,
            "reason": reason,
            "mode": mode.value if mode else None,
            "interface": iface,
            "key": key.as_dict(),
        }

    def _snapshot(self, watch: _Watch) -> dict[str, Any]:
        now = self._clock()
        end = (
            self._last_tick
            if self._last_tick is not None
            else self._tick_index(now) - 1
        )
        samples = [
            self._entry(watch, t) for t in range(end - HISTORY_TICKS + 1, end + 1)
        ]
        latest = dict(samples[-1])
        info = self._ticks.get(end)
        age = now - info.mono if info else None
        # OLD CODE START — NET-205 review: a failed tick has no time, so its own reason
        # (a foreign rule, capture changing, a failed read) was replaced by "late"
        # if age is None or age > FRESH_S:
        # OLD CODE END
        stalled = (
            self._tick_index(now) - end
        ) * TICK_S > FRESH_S  # no tick for over 5 s
        if stalled or (age is not None and age > FRESH_S):
            latest.update(_null("Not measured just now: the counters are late."))
        valid = [t for t in range(end, end - HISTORY_TICKS, -1)
                 if watch.samples.get(t, {}).get("down_bps") is not None and t in self._ticks]  # fmt: skip
        return {
            "supported": True,
            "reason": None,
            "mode": CaptureMode.MIRROR.value,
            "interface": self._iface,
            "key": watch.key.as_dict(),
            "layer": LAYER,
            "offloads": dict(self._offloads),
            "interval_s": TICK_S,
            "latest": latest,
            "latest_age_s": round(age, 3) if age is not None else None,
            "last_valid_age_s": round(now - self._ticks[valid[0]].mono, 3)
            if valid
            else None,
            "measuring_since": watch.since_ms,
            "samples": samples,
        }

    def _entry(self, watch: _Watch, tick: int) -> dict[str, Any]:
        info = self._ticks.get(tick)
        if tick <= watch.start_tick:
            body = _null("Not measuring yet.")
        else:
            body = watch.samples.get(tick) or _null("Missed.")
        return {
            "tick": tick,
            "t": info.wall_ms if info else None,
            "mono": info.mono if info else None,
            "bracket_ms": round(info.bracket_ms, 3) if info else None,
            **body,
        }
