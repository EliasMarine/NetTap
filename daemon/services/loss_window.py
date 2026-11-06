"""Capture packet loss over a recent window, not since the counters reset (NET-167).

The interface counters in sysfs only reset when the interface is created (boot, driver
reload, a re-created bridge), so a loss rate built from them alone keeps an old burst forever
and dilutes loss happening now. LossWindow keeps validated readings for up to an hour and
reports the loss between the oldest one inside the hour and the newest, with its real span.

Counter semantics follow the kernel's rtnl_link_stats64: rx_packets already includes the
packets the host dropped (rx_dropped); rx_missed_errors are packets the device dropped before
the host saw them. So arrived = rx_packets + rx_missed_errors, lost = rx_dropped +
rx_missed_errors.
"""

import logging
import os
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger("nettap.services.loss_window")

MAX_AGE_S = 3600.0
MIN_SPAN_S = 60.0
SAMPLE_INTERVAL_S = 60.0
MIN_GAP_S = 5.0  # newest reading kept is at most this old; caps an hour at 721 readings
SYS_NET = os.environ.get("HOST_SYS_NET", "/host/sys/class/net")
_COUNTERS = ("rx_packets", "rx_dropped", "rx_missed_errors")


@dataclass(frozen=True)
class Counters:
    """One validated reading of an interface's loss counters."""

    ifindex: int
    rx_packets: int
    rx_dropped: int
    rx_missed_errors: int

    @property
    def arrived(self) -> int:
        return self.rx_packets + self.rx_missed_errors

    @property
    def lost(self) -> int:
        return self.rx_dropped + self.rx_missed_errors


def _read_count(path: str) -> int | None:
    try:
        with open(path) as f:
            value = int(f.read().strip())
    except (OSError, ValueError):
        return None
    return value if value >= 0 else None


def read_loss_counters(sys_net: str, iface: str) -> Counters | None:
    """The interface's counters, or None when any read fails or the interface was replaced
    mid-read (ifindex differs before and after). A failed read is never a 0."""
    base = os.path.join(sys_net, iface)
    before = _read_count(os.path.join(base, "ifindex"))
    counts = [_read_count(os.path.join(base, "statistics", name)) for name in _COUNTERS]
    after = _read_count(os.path.join(base, "ifindex"))
    if before is None or before != after or any(c is None for c in counts):
        return None
    return Counters(before, *counts)  # type: ignore[arg-type]


def _figures(arrived: int, lost: int) -> dict:
    """Counts and their rate; the rate is None with nothing arrived or inconsistent counters."""
    rate = lost / arrived * 100 if arrived and lost <= arrived else None
    return {"arrived": arrived, "lost": lost, "drop_rate_pct": rate}


@dataclass(frozen=True)
class _Sample:
    at: float
    iface: str
    counters: Counters


class LossWindow:
    """Readings for up to `max_age_s`; `over()` reports the loss across them."""

    def __init__(self, max_age_s: float = MAX_AGE_S, min_span_s: float = MIN_SPAN_S):
        self._max_age = max_age_s
        self._min_span = min_span_s
        self._samples: deque[_Sample] = deque()
        self._iface: str | None = None
        self._unreadable = False
        self._inconsistent = False

    def add(self, at: float, iface: str, counters: Counters | None) -> None:
        """One reading at monotonic time `at`; None when the counters couldn't be read."""
        self._iface = iface
        if counters is None:
            if not self._unreadable:
                logger.warning(
                    "Loss counters on %s are unreadable", iface or "no interface"
                )
            self._unreadable = True
            self._samples.clear()
            return
        if self._unreadable:
            logger.info("Loss counters on %s are readable again", iface)
        self._unreadable = False
        reason = self._restart_reason(iface, counters)
        if reason:
            logger.info("Loss window on %s restarts: %s", iface, reason)
            self._samples.clear()
        elif self._samples and at - self._samples[-1].at < MIN_GAP_S:
            # every stats request takes a reading; keeping them all would grow with request
            # rate, so the window holds at most one per MIN_GAP_S (reset checks still run)
            return
        self._samples.append(_Sample(at, iface, counters))
        while self._samples[0].at < at - self._max_age:
            self._samples.popleft()

    def _restart_reason(self, iface: str, new: Counters) -> str | None:
        if not self._samples:
            return None
        last = self._samples[-1]
        if last.iface != iface:
            return f"the capture interface changed from {last.iface}"
        old = last.counters
        if old.ifindex != new.ifindex:
            return "the interface was re-created"
        if any(getattr(new, n) < getattr(old, n) for n in _COUNTERS):
            return "a counter went down (reset or wrap)"
        return None

    def over(self) -> dict:
        """{state, interface, window, cumulative}: state is ok, measuring or unavailable."""
        if self._unreadable or not self._samples:
            state = "unavailable" if self._unreadable else "measuring"
            return {
                "state": state,
                "interface": self._iface,
                "window": None,
                "cumulative": None,
            }
        oldest, newest = self._samples[0], self._samples[-1]
        cumulative = _figures(newest.counters.arrived, newest.counters.lost)
        span = newest.at - oldest.at
        if len(self._samples) < 2 or span < self._min_span:
            return {
                "state": "measuring",
                "interface": self._iface,
                "window": None,
                "cumulative": cumulative,
            }
        arrived = newest.counters.arrived - oldest.counters.arrived
        lost = newest.counters.lost - oldest.counters.lost
        if lost > arrived:
            if not self._inconsistent:
                logger.warning(
                    "Loss counters on %s are inconsistent (%d lost of %d arrived)",
                    self._iface,
                    lost,
                    arrived,
                )
            self._inconsistent = True
            return {
                "state": "unavailable",
                "interface": self._iface,
                "window": None,
                "cumulative": cumulative,
            }
        self._inconsistent = False
        window = {"seconds": int(span), **_figures(arrived, lost)}
        return {
            "state": "ok",
            "interface": self._iface,
            "window": window,
            "cumulative": cumulative,
        }
