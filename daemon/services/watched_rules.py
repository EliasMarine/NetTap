"""
The watched-devices rules (NET-331, plan §2.2-§2.4): pure functions and the state file's shape.

The job that runs them, saves the state and journals each transition is
services/watched_devices.py. Every time here is a conn record's event.end (the last packet) or
@timestamp (the connection's start), compared at OpenSearch's millisecond precision.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from services.device_details import WATCH_CHOICES, strict_mac
from services.excluded_ips import CONN_ACCOUNTING, CONN_RECORDS, ESTABLISHED_STATES
from services.usage_days import parse_iso

OFFLINE, ONLINE = "device_offline", "device_online"
# Zeek writes an open connection by its first conn_long checkpoint, 10 minutes in (§2.2)
LOG_DELAY = timedelta(seconds=600)
CONFIRM = timedelta(seconds=240)  # a silence must hold across checks this far apart
PRESENCE_WINDOW = timedelta(hours=48)
CAPTURE_WINDOW = timedelta(hours=1)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

EMPTY_CHECK: dict[str, str | None] = dict.fromkeys(
    (
        "attempt_at",
        "success_at",
        "capture_at",
        "coverage_since",
        "scope",
        "skipped",
        "reason",
        "error",
    )
)
_CHECK_TIMES = ("attempt_at", "success_at", "capture_at", "coverage_since")
DEVICE_KEYS = frozenset(
    {
        "enrolled_at",
        "after_min",
        "state",
        "since",
        "seen_at",
        "silent_from",
        "incident",
        "pending",
    }
)
_DEVICE_TIMES = ("since", "seen_at", "silent_from")
_PENDING_KEYS = frozenset({"type", "key", "instance", "observed_at", "data"})

# check.reason for skipped "mode": the card's "capture isn't ready: {reason}"
_STATUS_REASON = {
    "degraded": "capture is degraded",
    "down": "capture is down",
    "not_configured": "capture isn't set up",
}

# a record its responder answered (§2.3 step 6, `answered`); S0 and A→B with no reply aren't
REPLIED: dict = {
    "bool": {
        "should": [
            {"range": {"destination.packets": {"gt": 0}}},
            {"range": {"destination.bytes": {"gt": 0}}},
            {"terms": {"zeek.conn.conn_state": ESTABLISHED_STATES}},
        ],
        "minimum_should_match": 1,
    }
}


# ---------------------------------------------------------------------------
# Times
# ---------------------------------------------------------------------------


def iso(t: datetime) -> str:
    """Milliseconds, the precision of OpenSearch dates, so a boundary compares exactly."""
    text = t.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    return text.replace("+00:00", "Z")


def floor_ms(t: datetime) -> datetime:
    return t.replace(microsecond=t.microsecond // 1000 * 1000)


def from_ms(value: Any) -> datetime | None:
    """An aggregation's epoch-ms value; None when there was nothing to aggregate."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"not an epoch-ms value: {value!r}")
    return _EPOCH + timedelta(milliseconds=round(value))


def _end_range(lo: datetime, hi: datetime) -> dict:
    return {
        "range": {
            "event.end": {
                "gte": iso(lo),
                "lte": iso(hi),
                "format": "strict_date_optional_time",
            }
        }
    }


# ---------------------------------------------------------------------------
# Capture readiness (§2.3 step 3)
# ---------------------------------------------------------------------------


def capture_scope(health: dict) -> tuple[str | None, str | None]:
    """(scope, None) when capture sees each device's own frames, else (None, reason).

    `health` is CaptureHealth.to_dict(). Mirror: link up, promiscuous, status neither down nor
    not_configured (the G11's ring-buffer warnings read degraded). DHCP gateway: link up,
    routing active and status normal. Bridge, the start-up stub and anything else: not ready.
    """
    mode, status = health.get("mode"), health.get("status")
    if health.get("stub"):
        return None, "capture is still starting"
    if mode == "mirror":
        checks = [
            (health.get("link_up") is True, "the capture link is down"),
            (health.get("promisc_enabled") is True, "promiscuous mode is off"),
            (status not in ("down", "not_configured"), None),
        ]
        scope = f"mirror|{health.get('capture_interface')}"
    elif mode == "dhcp_gateway":
        checks = [
            (health.get("routing_active") is True, "DHCP gateway routing is off"),
            (health.get("link_up") is True, "the capture link is down"),
            (status == "normal", None),
        ]
        scope = f"dhcp_gateway|{health.get('capture_interface')}|{health.get('subnet')}"
    elif mode == "bridge":
        return None, "bridge mode can't tell devices apart"
    else:
        return None, "this capture mode can't tell devices apart"
    for ok, reason in checks:
        if not ok:
            return None, reason or _STATUS_REASON.get(
                status, "capture status is unknown"
            )
    return scope, None


# ---------------------------------------------------------------------------
# The state file
# ---------------------------------------------------------------------------


def _times_ok(entry: dict, keys: tuple[str, ...], required: bool = False) -> bool:
    return all(
        (entry.get(k) is None and not required) or parse_iso(entry.get(k)) is not None
        for k in keys
    )


def _canonical(mac: Any) -> bool:
    try:
        return strict_mac(mac) == mac
    except ValueError:
        return False


def _pending_ok(p: Any) -> bool:
    return (
        isinstance(p, dict)
        and set(p) == _PENDING_KEYS
        and p["type"] in (OFFLINE, ONLINE)
        and all(isinstance(p[k], str) for k in ("key", "instance"))
        and parse_iso(p["observed_at"]) is not None
        and isinstance(p["data"], dict)
    )


def _device_ok(mac: Any, dev: Any) -> bool:
    if not _canonical(mac) or not isinstance(dev, dict) or set(dev) != DEVICE_KEYS:
        return False
    incident = dev["incident"]
    return (
        dev["state"] in ("unknown", "up", "down")
        and type(dev["after_min"]) is int
        and dev["after_min"] in WATCH_CHOICES
        and _times_ok(dev, ("enrolled_at",), required=True)
        and _times_ok(dev, _DEVICE_TIMES)
        and (dev["state"] != "up" or dev["seen_at"] is not None)
        and (dev["state"] != "down" or incident is not None)
        and (
            incident is None
            or (
                isinstance(incident, dict)
                and set(incident) == {"seen_at", "declared_at"}
                and _times_ok(incident, ("seen_at", "declared_at"), required=True)
            )
        )
        and (dev["pending"] is None or _pending_ok(dev["pending"]))
    )


def state_ok(raw: Any) -> bool:
    if not isinstance(raw, dict) or set(raw) != {"version", "check", "devices"}:
        return False
    check, devices = raw["check"], raw["devices"]
    return (
        raw["version"] == 1
        and isinstance(check, dict)
        and set(check) <= set(EMPTY_CHECK)
        and all(v is None or isinstance(v, str) for v in check.values())
        and _times_ok(check, _CHECK_TIMES)
        and isinstance(devices, dict)
        and all(_device_ok(mac, dev) for mac, dev in devices.items())
    )


def empty_state() -> dict:
    return {"version": 1, "check": dict(EMPTY_CHECK), "devices": {}}


def enrolled(after_min: int, now: datetime) -> dict:
    return {
        "enrolled_at": iso(now),
        "after_min": after_min,
        "state": "unknown",
        "since": None,
        "seen_at": None,
        "silent_from": None,
        "incident": None,
        "pending": None,
    }


def with_device(state: dict, mac: str, dev: dict) -> dict:
    return {**state, "devices": {**state["devices"], mac: dev}}


def without_streaks(devices: dict[str, dict]) -> dict[str, dict]:
    return {mac: {**dev, "silent_from": None} for mac, dev in devices.items()}


# ---------------------------------------------------------------------------
# The state machine (§2.4)
# ---------------------------------------------------------------------------


def _threshold(after_min: int) -> timedelta:
    return timedelta(minutes=after_min) + LOG_DELAY


def _online(dev: dict, back_at: datetime) -> dict:
    seen_at = dev["incident"]["seen_at"]
    away = back_at - parse_iso(seen_at)
    return {
        "type": ONLINE,
        "instance": "up|" + seen_at,
        "data": {
            "after_min": dev["after_min"],
            "seen_at": seen_at,
            "back_at": iso(back_at),
            "away_min": int(away.total_seconds() // 60),
        },
    }


def step(
    dev: dict,
    seen_new: datetime | None,
    started_new: datetime | None,
    capture_at: datetime,
    coverage_since: datetime,
    now: datetime,
) -> tuple[dict, dict | None]:
    """One device's next state and its event ({type, instance, data}) or None. Pure.

    seen_new / started_new: the newest event.end / @timestamp of the device's evidence this
    run (None when it had none). Silence counts only covered time, plus Zeek's writing delay.
    """
    since = iso(now)
    if dev["state"] in ("unknown", "down"):
        incident = dev["incident"]
        if dev["state"] == "unknown":
            # a connection that started at or after enrollment
            qualifies = started_new is not None and started_new >= parse_iso(
                dev["enrolled_at"]
            )
        else:
            # a connection that started after the declaration: a peer's late packet on an
            # older connection moves event.end, not the start
            qualifies = started_new is not None and started_new > parse_iso(
                incident["declared_at"]
            )
        if not qualifies or seen_new is None:
            return dev, None
        up = {
            **dev,
            "state": "up",
            "since": since,
            "seen_at": iso(seen_new),
            "silent_from": None,
            "incident": None,
        }
        # unknown with an incident: one carried through a capture scope reset (§2.3 step 4a)
        return up, (_online(dev, started_new) if incident else None)

    seen_at = parse_iso(dev["seen_at"])
    if seen_new is not None and seen_new > seen_at:
        seen_at = seen_new
    dev = {**dev, "seen_at": iso(seen_at)}
    silence = capture_at - max(seen_at, coverage_since)
    if silence <= _threshold(dev["after_min"]):
        return {**dev, "silent_from": None}, None
    silent_from = parse_iso(dev["silent_from"])
    if silent_from is None or silent_from < coverage_since:
        return {**dev, "silent_from": iso(capture_at)}, None
    if capture_at - silent_from < CONFIRM:
        return dev, None
    incident = {"seen_at": dev["seen_at"], "declared_at": since}
    down = {
        **dev,
        "state": "down",
        "since": since,
        "silent_from": None,
        "incident": incident,
    }
    event = {
        "type": OFFLINE,
        "instance": "down|" + incident["seen_at"],
        "data": {"after_min": dev["after_min"], "seen_at": incident["seen_at"]},
    }
    return down, event


# ---------------------------------------------------------------------------
# The two searches (§2.3 step 6)
# ---------------------------------------------------------------------------


def presence_body(macs: list[str], now: datetime) -> dict:
    """One search for the newest event.end and @timestamp per MAC, sent and answered.

    `macs` lower case, as on the wire. `size` and `include` on both sides: a record with two
    MACs on a side can't make a bucket for one not asked about.
    """
    maxima = {
        "seen": {"max": {"field": "event.end"}},
        "started": {"max": {"field": "@timestamp"}},
    }

    def side(field: str) -> dict:
        terms = {"field": field, "size": len(macs), "include": macs}
        return {"terms": terms, "aggs": maxima}

    sent = {"terms": {"source.mac": macs}}
    answered = {"bool": {"filter": [{"terms": {"destination.mac": macs}}, REPLIED]}}
    return {
        "size": 0,
        "query": {
            "bool": {
                "filter": [CONN_RECORDS, _end_range(now - PRESENCE_WINDOW, now)],
                "should": [sent, answered],
                "minimum_should_match": 1,
            }
        },
        "aggs": {
            "sent": {"filter": sent, "aggs": {"macs": side("source.mac")}},
            "answered": {"filter": answered, "aggs": {"macs": side("destination.mac")}},
        },
    }


def capture_body(now: datetime) -> dict:
    """The newest packet capture has made searchable: final conn records only (§2.2)."""
    return {
        "size": 0,
        "query": {
            "bool": {"filter": [CONN_ACCOUNTING, _end_range(now - CAPTURE_WINDOW, now)]}
        },
        "aggs": {"capture_at": {"max": {"field": "event.end"}}},
    }


def sightings(reply: dict) -> dict[str, tuple[datetime, datetime]]:
    """{MAC: (newest event.end, newest @timestamp)} over both sides."""
    found: dict[str, tuple[datetime, datetime]] = {}
    for side in ("sent", "answered"):
        for bucket in reply["aggregations"][side]["macs"]["buckets"]:
            mac = strict_mac(bucket["key"])
            seen = from_ms(bucket["seen"]["value"])
            started = from_ms(bucket["started"]["value"])
            if seen is None or started is None:
                continue
            old = found.get(mac)
            found[mac] = (
                (seen, started)
                if old is None
                else (max(old[0], seen), max(old[1], started))
            )
    return found
