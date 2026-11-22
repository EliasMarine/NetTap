"""
The weekly report's pure rules (NET-340, plan §3.1-§3.2, §3.7): periods and send times, the
consent digest and token, what a stored or restored schedule must look like, and the durable
write. No state here: report_generator.py holds the schedules and does the sending.
"""

import hashlib
import json
import logging
import os
import re
import secrets
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from services import notification_config
from services.capture_config import write_file_atomic

# the generator's logger, as when this ran there, so the log reads the same
logger = logging.getLogger("nettap.services.report_generator")

VALID_FREQUENCIES = ("daily", "weekly", "monthly")
UUID4 = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
REPORT_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{6}")
KEEP_REPORTS = 12
MAX_SCHEDULES = 50
MAX_RECIPIENTS = 10
CONTENTS = "v1"  # names the five sections; new contents need a fresh confirmation
# what an older daemon expects in the legacy field
LEGACY_SECTIONS = ["traffic_summary", "alerts", "devices"]
DEFAULT_WEEKDAY, DEFAULT_HOUR = 0, 8
SEND_MARGIN_S, GENERATE_MAX_S, MANUAL_S = 30, 180, 45
TERMINAL = ("sent", "partly_sent", "failed", "not_configured", "not_emailed")

SENDING = "A report is being sent. Try again in a minute."
CARD_ONLY = "Only the weekly report on Settings › Notifications can send email. Turn it on there."
RESTORE_SENDING = "A report is being sent. Try the restore again in a minute."
STALE = "These settings changed in another window. Reload and check them."
GENERATING = (
    "A report is being generated. It will appear in the history when it's done."
)
CHANGED = "The schedule changed while the report was being made"
UNAVAILABLE = (
    "The saved report schedules can't be read, so nothing can be changed or sent. "
    "The daemon log has the reason."
)
NOT_FOUND = "Schedule not found"
REPORT_NOT_FOUND = "Report not found"
UNKNOWN_SEND = "Unknown: NetTap stopped while sending"
RESTORED_PAUSED = (
    "Report schedules restored paused. Check the recipients in Settings › Notifications "
    "and save to turn them on."
)


class ReportRefused(Exception):
    """A request the state refuses, with its HTTP status (404, 409 or 503)."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class ReportSchedule:
    """A scheduled report configuration."""

    id: str
    name: str
    frequency: str  # 'daily', 'weekly', 'monthly'
    format: str  # 'json', 'csv', 'html'
    recipients: list[str] = field(default_factory=list)  # email addresses
    sections: list[str] = field(default_factory=list)
    enabled: bool = True
    last_run: str | None = None
    next_run: str | None = None
    created_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# --- periods (§3.1) ------------------------------------------------------------------


def send_instant(day: date, hour: int, tz: ZoneInfo) -> datetime:
    """The local day's send hour in UTC. fold=0: a repeated hour's first occurrence, and an hour
    a daylight-saving change skips maps to the change itself, the first valid instant after it."""
    # shortcut: exact for gaps that start on the hour (every zone in use today); a gap starting
    # mid-hour would send up to its length late
    return datetime.combine(day, dtime(hour), tzinfo=tz).astimezone(timezone.utc)


def _send_day(frequency: str, weekday: int, day: date) -> bool:
    if frequency == "weekly":
        return day.weekday() == weekday
    return frequency == "daily" or day.day == 1


def latest_boundary(
    frequency: str, weekday: int, hour: int, tz: ZoneInfo, now: datetime
) -> date:
    """The local date of the latest send time at or before `now`."""
    today = now.astimezone(tz).date()
    days = (today - timedelta(days=i) for i in range(63))
    return next(
        d
        for d in days
        if _send_day(frequency, weekday, d) and send_instant(d, hour, tz) <= now
    )


def next_send(
    frequency: str, weekday: int, hour: int, tz: ZoneInfo, now: datetime
) -> datetime:
    """The first send time after `now`."""
    today = now.astimezone(tz).date()
    days = (today + timedelta(days=i) for i in range(63))
    return next(
        send_instant(d, hour, tz)
        for d in days
        if _send_day(frequency, weekday, d) and send_instant(d, hour, tz) > now
    )


def period_for(frequency: str, boundary_date: date, tz: str):
    """The completed whole local days a send on `boundary_date` reports, as a Period."""
    # loaded on first use: the contents module imports api.alerts, too heavy for a backup check
    from services.report_sections import Period

    last = boundary_date - timedelta(days=1)
    if frequency == "daily":
        first = last
    elif frequency == "weekly":
        first = boundary_date - timedelta(days=7)
    else:
        first = last.replace(day=1)
    return Period.of(first, last, tz)


# --- consent (§3.2) ---------------------------------------------------------------


def _weekday(meta: dict) -> int:
    return meta.get("weekday", DEFAULT_WEEKDAY)


def _hour(meta: dict) -> int:
    return meta.get("hour", DEFAULT_HOUR)


def consent_digest(s: ReportSchedule, meta: dict) -> str:
    """What the owner confirms: recipients exactly as stored (a local part can be case-sensitive),
    the legacy sections field, cadence, on/off and the contents version."""
    canon = {
        "recipients": sorted(s.recipients),
        "sections": s.sections,
        "frequency": s.frequency,
        "weekday": _weekday(meta),
        "hour": _hour(meta),
        "enabled": s.enabled,
        "contents": CONTENTS,
    }
    raw = json.dumps(canon, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def confirm_token(sid: str, meta: dict, digest: str) -> str:
    """Names exactly what a reply showed: the id, the rev and the settings as stored."""
    return hashlib.sha256(f"{sid}|{meta.get('rev', 0)}|{digest}".encode()).hexdigest()


def _confirmed(s: ReportSchedule, meta: dict) -> bool:
    return meta.get("confirmed_digest") == consent_digest(s, meta)


def _destination(s: ReportSchedule, meta: dict) -> tuple:
    """What a claim fixes: who gets it, whether it runs, and when."""
    return (s.recipients, s.enabled, s.frequency, _weekday(meta), _hour(meta))


# --- files -----------------------------------------------------------------------


def _int_in(value: Any, low: int, high: int) -> bool:
    return (
        isinstance(value, int) and not isinstance(value, bool) and low <= value <= high
    )


def address_ok(value: Any) -> bool:
    """One email address with no CR, LF or comma (each would split a mail header)."""
    return (
        isinstance(value, str)
        and notification_config.is_address(value)
        and not any(c in value for c in "\r\n,")
    )


_LEGACY_TYPES: dict[str, tuple] = {
    "id": (str,),
    "name": (str,),
    "frequency": (str,),
    "format": (str,),
    "recipients": (list,),
    "sections": (list,),
    "enabled": (bool,),
    "last_run": (str, type(None)),
    "next_run": (str, type(None)),
    "created_at": (str,),
}
_META_KEYS = (
    "weekday",
    "hour",
    "card",
    "rev",
    "confirmed_digest",
    "last_period",
    "claim",
    "last_delivery",
)


def _schedule_from(raw: Any) -> ReportSchedule:
    """A stored schedule, known fields only; ValueError or TypeError when it can't be trusted."""
    if not isinstance(raw, dict):
        raise ValueError("a schedule isn't an object")
    known = {k: raw[k] for k in _LEGACY_TYPES if k in raw}
    bad = [k for k, v in known.items() if not isinstance(v, _LEGACY_TYPES[k])]
    if bad:
        raise ValueError(f"a schedule's {bad[0]} has the wrong type")
    if not UUID4.fullmatch(known.get("id", "")):
        raise ValueError("a schedule's id isn't a uuid4")
    if known.get("frequency") not in VALID_FREQUENCIES:
        raise ValueError("a schedule's frequency isn't daily, weekly or monthly")
    lists = known.get("recipients", []) + known.get("sections", [])
    if not all(isinstance(x, str) for x in lists):
        raise ValueError("a schedule's recipients or sections aren't text")
    return ReportSchedule(**known)


def _meta_from(raw: Any) -> dict:
    """A stored sidecar entry, known keys only; ValueError (or Type/KeyError) when untrustworthy."""
    if not isinstance(raw, dict):
        raise ValueError("a schedule's state isn't an object")
    m = {k: raw[k] for k in _META_KEYS if k in raw}
    ok = (
        _int_in(m.get("weekday", 0), 0, 6)
        and _int_in(m.get("hour", 0), 0, 23)
        and _int_in(m.get("rev", 0), 0, 2**53)
        and isinstance(m.get("card", False), bool)
        and isinstance(m.get("confirmed_digest"), (str, type(None)))
        and all(
            isinstance(m.get(k), (dict, type(None)))
            for k in ("last_period", "claim", "last_delivery")
        )
    )
    if not ok:
        raise ValueError("a schedule's state has the wrong type")
    if m.get("last_period"):
        date.fromisoformat(m["last_period"]["first"])
        date.fromisoformat(m["last_period"]["last"])
    claim = m.get("claim")
    if claim and not (
        isinstance(claim.get("claim_id"), str)
        and isinstance(claim.get("report_id"), str)
        and REPORT_ID.fullmatch(claim["report_id"])
        and isinstance(claim.get("recipients"), list)
        and isinstance(claim.get("at"), str)
    ):
        raise ValueError("a schedule's claim isn't valid")
    return m


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _replace_file(path: Path, data: Any) -> None:
    """Temp file fsynced, then os.replace; mode 600, new dirs 700. The directory isn't synced."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    write_file_atomic(
        str(path), json.dumps(data, indent=2), mode=0o600, encoding="utf-8"
    )


def _write_durable(path: Path, data: Any) -> None:
    """Temp file fsynced, os.replace, then the directory fsynced; mode 600, new dirs 700."""
    _replace_file(path, data)
    _fsync_dir(path.parent)


# --- report files ------------------------------------------------------------------


def new_report_id(d: Path, now: datetime) -> str:
    """YYYYMMDDTHHMMSSZ-<6 hex>, not yet used in `d` (staged files included)."""
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    while True:
        rid = f"{stamp}-{secrets.token_hex(3)}"
        if not (d / f"{rid}.json").exists() and not (d / f"{rid}.json.staged").exists():
            return rid


def prune(d: Path) -> None:
    """The newest KEEP_REPORTS reports kept (an id sorts by its time); staged files don't count."""
    reports = sorted(p for p in d.glob("*.json") if REPORT_ID.fullmatch(p.stem))
    for old in reports[:-KEEP_REPORTS]:
        old.unlink(missing_ok=True)


def _summary(r: dict) -> dict:
    period = r.get("period") or {}
    return {
        "id": r.get("id"),
        "schedule_id": r.get("schedule_id"),
        "trigger": r.get("trigger"),
        "period": {"first": period.get("first"), "last": period.get("last")},
        "generated_at": r.get("generated_at"),
        "delivery": {"result": (r.get("delivery") or {}).get("result")},
        "status": {
            name: sec.get("status")
            for name, sec in (r.get("sections") or {}).items()
            if isinstance(sec, dict)
        },
    }


def summaries(dirs: list[Path]) -> list[dict]:
    """Every readable report's summary in `dirs`, newest first."""
    found = []
    for d in dirs:
        for path in d.glob("*.json") if d.is_dir() else []:
            if not REPORT_ID.fullmatch(path.stem):
                continue
            try:
                r = _read_json(path, None)
            except (OSError, ValueError) as exc:
                logger.warning("Skipping unreadable report %s: %s", path.name, exc)
                continue
            if isinstance(r, dict):
                found.append(_summary(r))
    return sorted(found, key=lambda r: str(r["id"]), reverse=True)


# --- backups (§3.7) ----------------------------------------------------------------


def _restored(item: Any) -> tuple[ReportSchedule, dict]:
    """One backup entry as (schedule, sidecar fields); ValueError with the reason."""
    try:
        s = _schedule_from(item)
    except (ValueError, TypeError) as exc:
        raise ValueError(str(exc)) from exc
    if not 1 <= len(s.name.strip()) <= 100:
        raise ValueError("a schedule's name isn't 1 to 100 characters")
    if len(s.recipients) > MAX_RECIPIENTS or not all(map(address_ok, s.recipients)):
        raise ValueError("a schedule's recipients aren't up to 10 email addresses")
    weekday, hour, card = item.get("weekday"), item.get("hour"), item.get("card", False)
    if not (_int_in(weekday, 0, 6) and _int_in(hour, 0, 23) and isinstance(card, bool)):
        raise ValueError("a schedule's weekday, hour or card isn't valid")
    return s, {"weekday": weekday, "hour": hour, "card": card}


def backup_problems(items: Any) -> list[str]:
    """Why a backup's report_schedules section wouldn't restore; [] when it would. No side effects."""
    prefix = "Report schedules not restored: "
    if not isinstance(items, list) or len(items) > MAX_SCHEDULES:
        return [f"{prefix}this backup's copy isn't a list of up to {MAX_SCHEDULES}"]
    problems, ids = [], set()
    for item in items:
        try:
            s, _ = _restored(item)
        except ValueError as exc:
            problems.append(f"{prefix}{exc}")
            continue
        if s.id in ids:
            problems.append(f"{prefix}a schedule's id appears twice")
        ids.add(s.id)
    return problems
