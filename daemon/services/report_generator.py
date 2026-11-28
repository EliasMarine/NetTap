"""
NetTap scheduled reports (NET-340, plan §3.1-§3.3): schedules, consent, the claim and the files.

- `report_schedules.json` keeps exactly the fields an older daemon reads (ReportSchedule); the new
  state sits beside it in `report_schedule_meta.json`, keyed by id: weekday, hour, card, rev,
  confirmed_digest, last_period (the watermark), claim and last_delivery.
- A schedule sends only while the digest of its current settings equals the one the owner
  confirmed, so an edit made any other way (an older daemon, a restore, a hand edit) pauses it.
- A send is claimed durably before SMTP and never retried: a crash reads "unknown", never twice.
- The contents come from report_sections.build_sections; this module only frames them.
"""

import logging
import os
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta, timezone
from email.utils import make_msgid
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from services import owner_tz

# The pure rules live in report_schedule; the names callers use are re-exported here (`as`)
from services.report_schedule import (
    CARD_ONLY,
    CHANGED,
    DEFAULT_HOUR,
    DEFAULT_WEEKDAY,
    GENERATE_MAX_S,
    GENERATING,
    LEGACY_SECTIONS,
    MANUAL_S,
    MAX_SCHEDULES,
    NOT_FOUND,
    REPORT_ID,
    REPORT_NOT_FOUND,
    RESTORE_SENDING,
    RESTORED_PAUSED,
    SEND_MARGIN_S,
    SENDING,
    STALE,
    TERMINAL,
    UNAVAILABLE,
    UNKNOWN_SEND,
    UUID4,
    VALID_FREQUENCIES,
    ReportRefused as ReportRefused,
    ReportSchedule as ReportSchedule,
    _confirmed,
    _destination,
    _hour,
    _meta_from,
    _read_json,
    _restored,
    _schedule_from,
    _weekday,
    _fsync_dir,
    _replace_file,
    _write_durable,
    backup_problems,
    confirm_token,
    consent_digest,
    latest_boundary,
    next_send,
    new_report_id,
    period_for,
    prune,
    summaries,
)
from services.usage_days import utc_iso

logger = logging.getLogger("nettap.services.report_generator")

CLAIM_RETRY = timedelta(
    hours=1
)  # after a failed claim write (a full disk), before rebuilding


def _html_part(report: dict) -> tuple[str | None, tuple[str, bytes] | None]:
    """NET-381: the branded HTML part and its logo, (html, (cid, png)); (None, None) when
    rendering fails, so the week's email still goes as plain text (the claim already stands)."""
    try:
        from services.report_html import logo_png, render_html

        png = logo_png()
        cid = make_msgid(domain="nettap.local")[1:-1] if png else None
        return render_html(report, cid), ((cid, png) if png else None)
    except Exception as exc:
        logger.error(
            "Report %s: HTML part not rendered, sending plain text: %s",
            report.get("id"),
            type(exc).__name__,
        )
        return None, None


class ReportGenerator:
    """Report schedules, their consent and watermark, the send claim and the report files.

    `_state_lock` is short and guards the in-memory schedules and sidecar and every file write;
    `_gen_lock` allows one generation (scheduled or manual) at a time and is never waited for.
    """

    VALID_FREQUENCIES = VALID_FREQUENCIES
    VALID_FORMATS = ("json", "csv", "html")
    VALID_SECTIONS = (
        "traffic_summary",
        "alerts",
        "devices",
        "compliance",
        "risk",
    )

    # OLD CODE: def __init__(self, reports_dir=..., schedules_file=...) (NET-340: the report
    # contents' dependencies, the email hub and a clock; the sidecar sits beside the schedules)
    def __init__(
        self,
        reports_dir: str = "/opt/nettap/data/reports",
        schedules_file: str = "/opt/nettap/data/report_schedules.json",
        deps: Any = None,
        hub: Any = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self._reports_dir = Path(reports_dir)
        self._schedules_file = Path(schedules_file)
        self._meta_file = self._schedules_file.with_name("report_schedule_meta.json")
        self._deps = deps  # report_sections.ReportDeps
        self._hub = hub  # NotificationHub
        self._now = now
        # (schedule id) -> (period's last day, retry at): a claim write that failed, so a full
        # disk doesn't rebuild the report every tick. Memory only
        self._held: dict[str, tuple[date, datetime]] = {}
        self._state_lock = threading.Lock()
        self._gen_lock = threading.Lock()
        self._schedules: dict[str, ReportSchedule] = {}
        self._meta: dict[str, dict] = {}
        self._available = True
        self._load()
        if self._available:
            try:
                with self._state_lock:
                    self._recover()
            except OSError as exc:
                logger.error("Report recovery failed; retried at the next run: %s", exc)

    # --- loading and saving -----------------------------------------------------

    def _load(self) -> None:
        """Both files, or the store unavailable (writes refused, files untouched)."""
        try:
            raw = _read_json(self._schedules_file, [])
            if not isinstance(raw, list):
                raise ValueError("the schedules file isn't a list")
            schedules: dict[str, ReportSchedule] = {}
            for item in raw:
                s = _schedule_from(item)
                if s.id in schedules:
                    raise ValueError("a schedule id appears twice")
                schedules[s.id] = s
            meta_raw = _read_json(self._meta_file, {})
            if not isinstance(meta_raw, dict) or not all(
                UUID4.fullmatch(k) for k in meta_raw
            ):
                raise ValueError("the schedule state file isn't keyed by schedule id")
            meta = {k: _meta_from(v) for k, v in meta_raw.items()}
        except (OSError, ValueError, TypeError, KeyError) as exc:
            logger.error(
                "Report schedules unavailable, nothing is changed or sent: %s", exc
            )
            self._available = False
            return
        self._schedules, self._meta = schedules, meta
        logger.info("Loaded %d report schedules", len(schedules))

    def _commit(self, schedules: dict, meta: dict) -> None:
        """Under _state_lock: the sidecar first, then the schedules file, each only if changed.
        Memory follows the disk, so a failed second write leaves the first one in force."""
        # OLD CODE START — Python review: a directory fsync failing after os.replace left memory
        # without the state the file already held (memory "no claim", disk a claim)
        # if meta != self._meta:
        #     _write_durable(self._meta_file, meta)
        #     self._meta = meta
        # if schedules != self._schedules:
        #     _write_durable(
        #         self._schedules_file, [asdict(s) for s in schedules.values()]
        #     )
        #     self._schedules = schedules
        # OLD CODE END
        if meta != self._meta:
            _replace_file(self._meta_file, meta)
            self._meta = meta
            self._fsync_parent(self._meta_file)
        if schedules != self._schedules:
            _replace_file(self._schedules_file, [asdict(s) for s in schedules.values()])
            self._schedules = schedules
            self._fsync_parent(self._schedules_file)

    @staticmethod
    def _fsync_parent(path: Path) -> None:
        """The rename made durable. Memory already holds the file's new state; a failure still
        raises, so a claim whose write isn't durable is never sent (plan §3.3)."""
        try:
            _fsync_dir(path.parent)
        except OSError as exc:
            logger.warning(
                "%s replaced but its directory not synced: %s", path.name, exc
            )
            raise

    def _check_available(self) -> None:
        if not self._available:
            raise ReportRefused(503, UNAVAILABLE)

    def _get(self, sid: str) -> tuple[ReportSchedule, dict]:
        s = self._schedules.get(sid)
        if s is None:
            raise ReportRefused(404, NOT_FOUND)
        return s, self._meta.get(sid, {})

    def schedule_dir(self, sid: str) -> Path:
        """The one resolver for a schedule's report directory; ValueError for a non-uuid4 id."""
        if not isinstance(sid, str) or not UUID4.fullmatch(sid):
            raise ValueError("Not a schedule id")
        # OLD CODE: return self._reports_dir / sid (CodeQL py/path-injection: the uuid4 check
        # makes it safe, but a regex isn't a sanitiser it recognises; normalise + prefix is)
        # abspath, not realpath: the reports directory may sit behind a symlink (macOS tmp)
        root = os.path.normpath(os.path.abspath(self._reports_dir))
        path = os.path.normpath(os.path.join(root, sid))
        if not path.startswith(root + os.sep):
            raise ValueError("Not a schedule id")
        return Path(path)

    def _schedule_dirs(self) -> list[Path]:
        if not self._reports_dir.is_dir():
            return []
        return [
            p
            for p in self._reports_dir.iterdir()
            if p.is_dir() and UUID4.fullmatch(p.name)
        ]

    # --- time --------------------------------------------------------------------

    def tz_name(self) -> str:
        """The ledger's zone (one for every schedule); the owner's before the first ledger pass."""
        snap = self._deps.ledger.snapshot() if self._deps is not None else None
        return snap["tz"] if snap else owner_tz.read()["tz"]

    def _latest_period(self, s: ReportSchedule, meta: dict, now: datetime, tz: str):
        boundary = latest_boundary(
            s.frequency, _weekday(meta), _hour(meta), ZoneInfo(tz), now
        )
        return period_for(s.frequency, boundary, tz)

    def _next_run(
        self, s: ReportSchedule, meta: dict, now: datetime, tz: str
    ) -> str | None:
        if not (s.enabled and _confirmed(s, meta)):
            return None
        return utc_iso(
            next_send(s.frequency, _weekday(meta), _hour(meta), ZoneInfo(tz), now)
        )

    # --- views -------------------------------------------------------------------

    def _view(self, s: ReportSchedule, now: datetime, tz: str) -> dict:
        m = self._meta.get(s.id, {})
        digest = consent_digest(s, m)
        confirmed = m.get("confirmed_digest") == digest
        return {
            **asdict(s),
            "rev": m.get("rev", 0),
            "confirm_token": confirm_token(s.id, m, digest),
            "weekday": _weekday(m),
            "hour": _hour(m),
            "tz": tz,
            "next_send": self._next_run(s, m, now, tz),
            "confirmed": confirmed,
            # paused: it would run, but what it would do now wasn't confirmed
            "needs_review": s.enabled and not confirmed,
            "card": m.get("card", False),
            "sending": bool(m.get("claim")),
            "last_period": m.get("last_period"),
            "last_delivery": m.get("last_delivery"),
        }

    def list_views(self) -> list[dict]:
        now, tz = self._now(), self.tz_name()
        with self._state_lock:
            self._check_available()
            return [self._view(s, now, tz) for s in self._schedules.values()]

    def view(self, sid: str) -> dict:
        now, tz = self._now(), self.tz_name()
        with self._state_lock:
            self._check_available()
            return self._view(self._get(sid)[0], now, tz)

    def list_schedules(self) -> list[ReportSchedule]:
        """List all report schedules."""
        return list(self._schedules.values())

    def get_schedule(self, schedule_id: str) -> ReportSchedule | None:
        """Get a specific schedule by ID."""
        return self._schedules.get(schedule_id)

    # --- changes -----------------------------------------------------------------

    def _watermark(
        self,
        before: ReportSchedule | None,
        before_m: dict,
        after: ReportSchedule,
        m: dict,
        now: datetime,
        tz: str,
    ) -> dict | None:
        """last_period, moved only by a real transition (confirmed, turned on, cadence changed) to
        the later of itself and the latest boundary's period; never backwards."""
        moved = (
            before is None
            or (_confirmed(after, m) and not _confirmed(before, before_m))
            or (after.enabled and not before.enabled)
            or (before.frequency, _weekday(before_m), _hour(before_m))
            != (after.frequency, _weekday(m), _hour(m))
        )
        current = m.get("last_period")
        if not moved:
            return current
        period = self._latest_period(after, m, now, tz)
        if current and date.fromisoformat(current["last"]) >= period.last:
            return current
        return {"first": period.first.isoformat(), "last": period.last.isoformat()}

    def _save_one(
        self,
        before: ReportSchedule | None,
        before_m: dict,
        after: ReportSchedule,
        fields: dict,
        confirm: bool,
    ) -> dict:
        """Under _state_lock: one schedule's new settings, rev bumped, confirmed only on request."""
        now, tz = self._now(), self.tz_name()
        m = {**before_m, **fields, "rev": before_m.get("rev", 0) + 1}
        if confirm:
            m = {**m, "confirmed_digest": consent_digest(after, m)}
        m = {**m, "last_period": self._watermark(before, before_m, after, m, now, tz)}
        s = replace(after, next_run=self._next_run(after, m, now, tz))
        self._commit({**self._schedules, s.id: s}, {**self._meta, s.id: m})
        return self._view(s, now, tz)

    def _check_fresh(self, s: ReportSchedule, m: dict, fields: dict) -> None:
        """409 when the caller's rev, or the token it confirms with, isn't the stored one."""
        if "rev" in fields and fields["rev"] != m.get("rev", 0):
            raise ReportRefused(409, STALE)
        if fields.get("confirm") is True and fields.get(
            "confirm_token"
        ) != confirm_token(s.id, m, consent_digest(s, m)):
            raise ReportRefused(409, STALE)

    def create(self, fields: dict, card: bool = False) -> dict:
        """A new schedule from validated fields, never confirmed: only the card sends email."""
        # OLD CODE START — security review: an API-only schedule could be confirmed for email,
        # and no page shows it (a hidden forwarding rule); the cap moved to _create_locked
        # """A new schedule from validated fields; confirmed only with confirm: true."""
        # with self._state_lock:
        #     self._check_available()
        #     if len(self._schedules) >= MAX_SCHEDULES:
        #         raise ValueError(f"NetTap keeps up to {MAX_SCHEDULES} report schedules")
        #     return self._create_locked(fields, card)
        # OLD CODE END
        if fields.get("confirm") is True and not card:
            raise ValueError(CARD_ONLY)
        with self._state_lock:
            self._check_available()
            return self._create_locked(fields, card)

    def _create_locked(self, fields: dict, card: bool) -> dict:
        # review: here, so the card's first save counts too (50 API schedules + a card made 51)
        if len(self._schedules) >= MAX_SCHEDULES:
            raise ValueError(f"NetTap keeps up to {MAX_SCHEDULES} report schedules")
        s = ReportSchedule(
            id=str(uuid.uuid4()),
            name=fields.get("name", "Weekly report"),
            frequency=fields.get("frequency", "weekly"),
            format="json",
            recipients=list(fields.get("recipients", [])),
            sections=list(LEGACY_SECTIONS),
            enabled=fields.get("enabled", True),
            created_at=utc_iso(self._now()),
        )
        meta = {
            "weekday": fields.get("weekday", DEFAULT_WEEKDAY),
            "hour": fields.get("hour", DEFAULT_HOUR),
            "card": card,
            "confirmed_digest": None,
            "claim": None,
            "last_delivery": None,
        }
        return self._save_one(None, {}, s, meta, fields.get("confirm") is True)

    def update(self, sid: str, fields: dict) -> dict:
        """A partial update from validated fields, swapped in whole; 409 on a stale rev or token,
        or on a destination change while a report is being sent."""
        with self._state_lock:
            self._check_available()
            # security review: only the card confirms, so no hidden schedule sends email
            if fields.get("confirm") is True and not self._get(sid)[1].get("card"):
                raise ValueError(CARD_ONLY)
            return self._update_locked(sid, fields)

    def _update_locked(self, sid: str, fields: dict) -> dict:
        s, m = self._get(sid)
        self._check_fresh(s, m, fields)
        after = replace(
            s,
            **{
                k: fields[k]
                for k in ("name", "frequency", "recipients", "enabled")
                if k in fields
            },
        )
        cadence = {k: fields[k] for k in ("weekday", "hour") if k in fields}
        if m.get("claim") and _destination(s, m) != _destination(
            after, {**m, **cadence}
        ):
            raise ReportRefused(409, SENDING)
        return self._save_one(s, m, after, cadence, fields.get("confirm") is True)

    def upsert_card(self, fields: dict) -> tuple[dict, bool]:
        """The Settings card's one schedule, found by card: true or created (weekly); the reply
        and whether it was created."""
        # security review: the card shows a weekly report, so it never confirms another frequency
        # (a restored or API-edited card schedule could be daily)
        fields = {**fields, "frequency": "weekly"}
        with self._state_lock:
            self._check_available()
            sid = next(
                (
                    i
                    for i, m in self._meta.items()
                    if m.get("card") and i in self._schedules
                ),
                None,
            )
            if sid is not None:
                return self._update_locked(sid, fields), False
            if "confirm_token" in fields:  # it confirmed a card that is gone
                raise ReportRefused(409, STALE)
            return self._create_locked(fields, card=True), True

    def set_enabled(self, sid: str, enabled: bool) -> dict:
        """The enable and disable routes; never confirms."""
        with self._state_lock:
            self._check_available()
            s, m = self._get(sid)
            after = replace(s, enabled=enabled)
            if m.get("claim") and after.enabled != s.enabled:
                raise ReportRefused(409, SENDING)
            return self._save_one(s, m, after, {}, False)

    def delete(self, sid: str) -> None:
        """The schedule, its state and its reports; 409 while a report is being sent."""
        with self._state_lock:
            self._check_available()
            _, m = self._get(sid)
            if m.get("claim"):
                raise ReportRefused(409, SENDING)
            self._commit(
                {k: v for k, v in self._schedules.items() if k != sid},
                {k: v for k, v in self._meta.items() if k != sid},
            )
            shutil.rmtree(self.schedule_dir(sid), ignore_errors=True)
        logger.info("Deleted report schedule %s", sid)

    # --- reports ------------------------------------------------------------------

    def _build(self, s: ReportSchedule, period, trigger: str, deadline: float) -> dict:
        """The report around build_sections (contract "Report"), without id or delivery yet."""
        from services.report_sections import build_sections

        started = time.monotonic()
        sections = build_sections(period, self._deps, deadline)
        report = {
            "id": None,
            "schedule_id": s.id,
            "schedule_name": s.name,
            "trigger": trigger,
            "frequency": s.frequency,
            "period": {
                "first": period.first.isoformat(),
                "last": period.last.isoformat(),
                "start": utc_iso(period.start),
                "end": utc_iso(period.end),
                "tz": period.tz,
                "days": (period.last - period.first).days + 1,
            },
            "generated_at": utc_iso(self._now()),
            "duration_s": round(time.monotonic() - started, 1),
            "delivery": None,
            "sections": sections,
        }
        logger.info(
            "Report for %s (%s to %s, %s) made in %.1f s: %s",
            s.id,
            period.first,
            period.last,
            trigger,
            report["duration_s"],
            {name: sec.get("status") for name, sec in sections.items()},
        )
        return report

    @staticmethod
    def _prune_quietly(d: Path) -> None:
        """The newest 12 kept; a failure is logged, never fails a stored or sent report."""
        try:
            prune(d)
        except OSError as exc:
            logger.warning("Old reports in %s not pruned: %s", d.name, exc)

    def generate_now(self, sid: str) -> dict:
        """A manual report of the latest completed period: never waits, emails or moves state."""
        if not self._gen_lock.acquire(blocking=False):
            raise ReportRefused(409, GENERATING)
        try:
            with self._state_lock:
                self._check_available()
                s, m = self._get(sid)
            rev = m.get("rev", 0)
            period = self._latest_period(s, m, self._now(), self.tz_name())
            report = self._build(s, period, "manual", time.monotonic() + MANUAL_S)
            with self._state_lock:
                if (
                    sid not in self._schedules
                    or self._meta.get(sid, {}).get("rev", 0) != rev
                ):
                    raise ReportRefused(409, CHANGED)
                d = self.schedule_dir(sid)
                rid = new_report_id(d, self._now())
                delivery = {
                    "result": "not_emailed",
                    "at": None,
                    "recipients": 0,
                    "refused": 0,
                    "error": None,
                }
                report = {**report, "id": rid, "delivery": delivery}
                _write_durable(d / f"{rid}.json", report)
                # OLD CODE: prune(d) (review: best-effort, the report is already stored)
                self._prune_quietly(d)
            return report
        finally:
            self._gen_lock.release()

    def run_due(self, deadline: float) -> dict | None:
        """The F1 job: recover, then at most one due schedule's report, claimed and sent."""
        if not self._gen_lock.acquire(blocking=False):
            return None  # a manual report is being made; the next tick looks again
        try:
            if not self._state_lock.acquire(
                timeout=max(0.0, deadline - time.monotonic())
            ):
                return None
            try:
                if not self._available:
                    return None
                self._recover()
                now, tz = self._now(), self.tz_name()
                due = self._pick_due(now, tz)
            finally:
                self._state_lock.release()
            if due is None:
                return None
            s, rev, period = due
            gen_deadline = min(
                deadline - SEND_MARGIN_S, time.monotonic() + GENERATE_MAX_S
            )
            report = self._build(s, period, "scheduled", gen_deadline)
            try:
                claimed = self._claim(s.id, rev, period, report, gen_deadline)
            except OSError:
                retry = self._now() + CLAIM_RETRY
                self._held = {**self._held, s.id: (period.last, retry)}
                raise
            if claimed is None:
                return None
            claim, report = claimed
            delivery = self._send(claim, report)
            with self._state_lock:
                self._finish(s.id, claim, delivery, report)
                self._prune_quietly(self.schedule_dir(s.id))
            return None
        finally:
            self._gen_lock.release()

    def _pick_due(self, now: datetime, tz: str) -> tuple | None:
        """Under _state_lock: the first schedule that is on, confirmed as it stands, not being
        sent, and whose latest completed period is past its watermark and not held back after
        a failed claim write."""
        for s in self._schedules.values():
            m = self._meta.get(s.id, {})
            if not s.enabled or m.get("claim") or not _confirmed(s, m):
                continue
            period = self._latest_period(s, m, now, tz)
            done = m.get("last_period")
            if done and date.fromisoformat(done["last"]) >= period.last:
                continue
            held = self._held.get(s.id)
            if held and held[0] == period.last and now < held[1]:
                continue
            return s, m.get("rev", 0), period
        return None

    def _claim(
        self, sid: str, rev: int, period, report: dict, deadline: float
    ) -> tuple[dict, dict] | None:
        """Recheck, stage the report, then claim the send and move the watermark in one durable
        sidecar write; any failure up to there means no SMTP attempt. None: discarded."""
        if not self._state_lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
            logger.warning("Report for %s discarded: the schedule store was busy", sid)
            return None
        try:
            s, m = self._schedules.get(sid), self._meta.get(sid, {})
            if (
                s is None
                or not s.enabled
                or m.get("rev", 0) != rev
                or not _confirmed(s, m)
            ):
                logger.info(
                    "Report for %s discarded: the schedule changed meanwhile", sid
                )
                return None
            d = self.schedule_dir(sid)
            rid = new_report_id(d, self._now())
            delivery = {
                "result": "pending",
                "at": None,
                "recipients": len(s.recipients),
                "refused": 0,
                "error": None,
            }
            report = {**report, "id": rid, "delivery": delivery}
            staged = d / f"{rid}.json.staged"
            _write_durable(staged, report)
            claim = {
                "claim_id": uuid.uuid4().hex,
                "first": period.first.isoformat(),
                "last": period.last.isoformat(),
                "report_id": rid,
                "recipients": list(s.recipients),
                "at": utc_iso(self._now()),
            }
            done = {"first": claim["first"], "last": claim["last"]}
            # a failure raises before any send; recovery deletes a staged file with no claim
            self._commit(
                self._schedules,
                {**self._meta, sid: {**m, "claim": claim, "last_period": done}},
            )
            # OLD CODE START — Python review: an error here, after the claim was committed, lost
            # the period with no send and recovery called it "NetTap stopped while sending"
            # os.replace(staged, d / f"{rid}.json")
            # _fsync_dir(d)
            # prune(d)
            # OLD CODE END
            # the claim stands, so the send goes ahead: _finish writes the report in place, and
            # recovery would rename a staged file that matches a claim
            try:
                os.replace(staged, d / f"{rid}.json")
                _fsync_dir(d)
            except OSError as exc:
                logger.error("Report %s: staged file not published: %s", rid, exc)
            return claim, report
        finally:
            self._state_lock.release()

    def _send(self, claim: dict, report: dict) -> dict:
        """The email to the claimed recipients, once; the delivery record (no addresses)."""
        out = {"result": "not_emailed", "refused": [], "error": None}
        if claim["recipients"] and self._hub is None:
            out = {**out, "result": "not_configured"}
        elif claim["recipients"]:
            try:
                from services.report_text import render_email

                subject, text = render_email(report)
                # OLD CODE START — NET-381: plain text only
                # out = self._hub.send_report_email(
                #     list(claim["recipients"]), subject, text
                # )
                # OLD CODE END
                html, logo = _html_part(report)
                out = self._hub.send_report_email(
                    list(claim["recipients"]), subject, text, html, logo
                )
            except Exception as exc:  # never retried: the claim already stands
                logger.error(
                    "Report email for %s failed: %s", report["schedule_id"], exc
                )
                out = {**out, "result": "failed", "error": type(exc).__name__}
        logger.info(
            "Report %s: %s (%d recipients, %d refused)",
            claim["report_id"],
            out["result"],
            len(claim["recipients"]),
            len(out.get("refused") or []),
        )
        return {
            "result": out["result"],
            "at": utc_iso(self._now()),
            "recipients": len(claim["recipients"]),
            "refused": len(out.get("refused") or []),
            "error": out.get("error"),
            "claim_id": claim["claim_id"],
        }

    def _finish(
        self, sid: str, claim: dict, delivery: dict, report: dict | None = None
    ) -> None:
        """Under _state_lock, for the matching claim only: (1) the result into the report file,
        (2) last_delivery with the claim cleared, (3) last_run and next_run."""
        m = self._meta.get(sid)
        if not m or (m.get("claim") or {}).get("claim_id") != claim["claim_id"]:
            return
        if report is not None:
            path = self.schedule_dir(sid) / f"{claim['report_id']}.json"
            _write_durable(path, {**report, "delivery": delivery})
        last = {
            "result": delivery["result"],
            "at": delivery["at"],
            "report_id": claim["report_id"],
        }
        meta = {**self._meta, sid: {**m, "claim": None, "last_delivery": last}}
        s = self._schedules.get(sid)
        schedules = self._schedules
        if s is not None:
            stamp = (report or {}).get("generated_at") or claim["at"]
            next_run = self._next_run(s, meta[sid], self._now(), self.tz_name())
            schedules = {
                **schedules,
                sid: replace(s, last_run=stamp, next_run=next_run),
            }
        self._commit(schedules, meta)

    def _recover(self) -> None:
        """Under _state_lock. Staged files: the active claim's goes into place, any other (a crash
        before its claim) is deleted. Then each leftover claim takes the result its report file
        holds, or "unknown". Never re-sent."""
        claims = {sid: m["claim"] for sid, m in self._meta.items() if m.get("claim")}
        for d in self._schedule_dirs():
            claim = claims.get(d.name)
            for staged in d.glob("*.json.staged"):
                if claim and staged.name == f"{claim['report_id']}.json.staged":
                    os.replace(staged, staged.with_suffix(""))
                    _fsync_dir(d)
                else:
                    staged.unlink(missing_ok=True)
        for sid, claim in claims.items():
            path = self.schedule_dir(sid) / f"{claim['report_id']}.json"
            try:
                report = _read_json(path, None)
            except (OSError, ValueError) as exc:
                logger.warning("Report %s unreadable in recovery: %s", path.name, exc)
                report = None
            delivery = report.get("delivery") if isinstance(report, dict) else None
            if (
                isinstance(delivery, dict)
                and delivery.get("claim_id") == claim["claim_id"]
                and delivery.get("result") in TERMINAL
            ):
                self._finish(sid, claim, delivery)
                continue
            unknown = {
                "result": "unknown",
                "at": claim["at"],
                "recipients": len(claim["recipients"]),
                "refused": 0,
                "error": UNKNOWN_SEND,
                "claim_id": claim["claim_id"],
            }
            logger.warning(
                "Report %s: delivery unknown (NetTap stopped)", claim["report_id"]
            )
            try:
                self._finish(
                    sid, claim, unknown, report if isinstance(report, dict) else None
                )
            # the report file couldn't be written; the sidecar still records "unknown"
            except OSError as exc:
                logger.error(
                    "Couldn't mark report %s unknown: %s", claim["report_id"], exc
                )
                self._finish(sid, claim, unknown)

    # --- history ----------------------------------------------------------------

    def history(self, sid: str | None = None) -> list[dict]:
        """Report summaries, newest first, for one schedule or all; staged files never show."""
        try:
            dirs = self._schedule_dirs() if sid is None else [self.schedule_dir(sid)]
        except ValueError:
            raise ReportRefused(404, NOT_FOUND) from None
        return summaries(dirs)

    def report(self, sid: str, report_id: str) -> dict:
        """One stored report; 404 for a bad id or a path outside the reports directory."""
        if not isinstance(report_id, str) or not REPORT_ID.fullmatch(report_id):
            raise ReportRefused(404, REPORT_NOT_FOUND)
        try:
            path = self.schedule_dir(sid) / f"{report_id}.json"
        except ValueError:
            raise ReportRefused(404, REPORT_NOT_FOUND) from None
        if not path.resolve().is_relative_to(self._reports_dir.resolve()):
            raise ReportRefused(404, REPORT_NOT_FOUND)
        try:
            r = _read_json(path, None)
        except (OSError, ValueError):
            r = None
        if not isinstance(r, dict):
            raise ReportRefused(404, REPORT_NOT_FOUND)
        return r

    # --- backups ------------------------------------------------------------------

    def export_backup(self) -> list[dict]:
        """The schedules with their weekday, hour and card; never digests, claims or deliveries."""
        with self._state_lock:
            self._check_available()
            items = [
                {
                    **{
                        k: v
                        for k, v in asdict(s).items()
                        if k not in ("last_run", "next_run")
                    },
                    "weekday": _weekday(self._meta.get(s.id, {})),
                    "hour": _hour(self._meta.get(s.id, {})),
                    "card": self._meta.get(s.id, {}).get("card", False),
                }
                for s in self._schedules.values()
            ]
        # Python review: an older daemon stored what a restore refuses (a comma in a recipient,
        # a 101-character name), and one such schedule refused the whole download
        kept = [i for i in items if not backup_problems([i])]
        left = [i["id"] for i in items if backup_problems([i])]
        if left:
            logger.warning(
                "Backup leaves out %d report schedule(s) a restore would refuse: %s",
                len(left),
                ", ".join(left),
            )
        return kept

    def restore_backup(self, items: Any) -> list[str]:
        """The backup's schedules replace these, unconfirmed (paused); the warnings to show.

        The sidecar goes first, every affected schedule's digest cleared and rev bumped (so an
        in-flight report's recheck fails), then the schedules file: a restore stopped between
        the two leaves schedules paused, never confirmed against new data.
        """
        problems = backup_problems(items)
        if problems:
            raise ValueError("; ".join(problems))
        parsed = [_restored(item) for item in items]
        with self._state_lock:
            self._check_available()
            if any(m.get("claim") for m in self._meta.values()):
                raise ReportRefused(409, RESTORE_SENDING)
            meta: dict[str, dict] = {}
            schedules: dict[str, ReportSchedule] = {}
            card_taken = False
            for s, fields in parsed:
                old_s, old = self._schedules.get(s.id), self._meta.get(s.id, {})
                card = fields["card"] and not card_taken
                card_taken = card_taken or card
                meta[s.id] = {
                    **old,
                    **fields,
                    "card": card,
                    "rev": old.get("rev", 0) + 1,
                    "confirmed_digest": None,
                    "claim": None,
                }
                schedules[s.id] = replace(
                    s, last_run=old_s.last_run if old_s else None, next_run=None
                )
            gone = [sid for sid in self._schedules if sid not in schedules]
            self._commit(self._schedules, meta)
            self._commit(schedules, meta)
            for sid in gone:
                shutil.rmtree(self.schedule_dir(sid), ignore_errors=True)
        logger.info("Restored %d report schedules, paused", len(schedules))
        return [RESTORED_PAUSED] if schedules else []

    # OLD CODE START — NET-340: _load emptied every schedule on an unknown field and _save
    # wasn't atomic or 600 (the next save then overwrote the file); next_run drifted; a new
    # schedule ran at once with unchecked recipients and no consent
    # def _load(self) -> None:
    #     """Load schedules from disk. Starts empty if missing."""
    #     try:
    #         if os.path.exists(self._schedules_file):
    #             with open(self._schedules_file, "r") as f:
    #                 raw = json.load(f)
    #             for sched_data in raw:
    #                 sched = ReportSchedule(**sched_data)
    #                 self._schedules[sched.id] = sched
    #             logger.info(
    #                 "Loaded %d report schedules from %s",
    #                 len(self._schedules),
    #                 self._schedules_file,
    #             )
    #     except (json.JSONDecodeError, OSError, TypeError) as exc:
    #         logger.warning(
    #             "Failed to load report schedules from %s: %s",
    #             self._schedules_file,
    #             exc,
    #         )
    #         self._schedules = {}
    #
    # def _save(self) -> None:
    #     """Persist all schedules to disk."""
    #     try:
    #         parent = os.path.dirname(self._schedules_file)
    #         if parent:
    #             os.makedirs(parent, exist_ok=True)
    #         data = [sched.to_dict() for sched in self._schedules.values()]
    #         with open(self._schedules_file, "w") as f:
    #             json.dump(data, f, indent=2)
    #     except OSError as exc:
    #         logger.error(
    #             "Failed to save report schedules to %s: %s",
    #             self._schedules_file,
    #             exc,
    #         )
    #         raise
    #
    # def _compute_next_run(self, frequency: str) -> str:
    #     """Compute the next run time based on frequency."""
    #     now = datetime.now(timezone.utc)
    #     if frequency == "daily":
    #         next_dt = now + timedelta(days=1)
    #     elif frequency == "weekly":
    #         next_dt = now + timedelta(weeks=1)
    #     elif frequency == "monthly":
    #         next_dt = now + timedelta(days=30)
    #     else:
    #         next_dt = now + timedelta(days=1)
    #     return next_dt.replace(hour=6, minute=0, second=0, microsecond=0).isoformat()
    #
    # def create_schedule(
    #     self,
    #     name: str,
    #     frequency: str,
    #     format: str,
    #     sections: list[str],
    #     recipients: list[str] | None = None,
    # ) -> ReportSchedule:
    #     """Create a new report schedule.
    #
    #     Raises ValueError for invalid frequency, format, or sections.
    #     """
    #     if not name or not name.strip():
    #         raise ValueError("Schedule name is required")
    #
    #     if frequency not in self.VALID_FREQUENCIES:
    #         raise ValueError(
    #             f"Invalid frequency: {frequency}. "
    #             f"Must be one of {self.VALID_FREQUENCIES}"
    #         )
    #
    #     if format not in self.VALID_FORMATS:
    #         raise ValueError(
    #             f"Invalid format: {format}. Must be one of {self.VALID_FORMATS}"
    #         )
    #
    #     if not sections:
    #         raise ValueError("At least one section is required")
    #
    #     for section in sections:
    #         if section not in self.VALID_SECTIONS:
    #             raise ValueError(
    #                 f"Invalid section: {section}. Must be one of {self.VALID_SECTIONS}"
    #             )
    #
    #     now = datetime.now(timezone.utc).isoformat()
    #     sched = ReportSchedule(
    #         id=str(uuid.uuid4()),
    #         name=name.strip(),
    #         frequency=frequency,
    #         format=format,
    #         recipients=recipients or [],
    #         sections=list(sections),
    #         enabled=True,
    #         last_run=None,
    #         next_run=self._compute_next_run(frequency),
    #         created_at=now,
    #     )
    #
    #     self._schedules[sched.id] = sched
    #     self._save()
    #     logger.info("Created report schedule: %s (%s)", sched.name, sched.id)
    #     return sched
    # OLD CODE END

    # OLD CODE START — NET-340: update mutated the live schedule before saving and took any
    # section; enable needed no consent; generate_report ran on the event loop, returned
    # placeholders and stored nothing
    # def update_schedule(self, schedule_id: str, **kwargs) -> ReportSchedule | None:
    #     """Update schedule fields.
    #
    #     Allowed fields: name, frequency, format, sections, recipients, enabled.
    #     Returns updated schedule or None if not found.
    #     Raises ValueError for invalid values.
    #     """
    #     sched = self._schedules.get(schedule_id)
    #     if sched is None:
    #         return None
    #
    #     allowed_fields = {
    #         "name",
    #         "frequency",
    #         "format",
    #         "sections",
    #         "recipients",
    #         "enabled",
    #     }
    #
    #     for key, value in kwargs.items():
    #         if key not in allowed_fields:
    #             continue
    #
    #         if key == "frequency":
    #             if value not in self.VALID_FREQUENCIES:
    #                 raise ValueError(
    #                     f"Invalid frequency: {value}. "
    #                     f"Must be one of {self.VALID_FREQUENCIES}"
    #                 )
    #         elif key == "format":
    #             if value not in self.VALID_FORMATS:
    #                 raise ValueError(
    #                     f"Invalid format: {value}. Must be one of {self.VALID_FORMATS}"
    #                 )
    #         elif key == "sections":
    #             if not value:
    #                 raise ValueError("At least one section is required")
    #             for section in value:
    #                 if section not in self.VALID_SECTIONS:
    #                     raise ValueError(
    #                         f"Invalid section: {section}. "
    #                         f"Must be one of {self.VALID_SECTIONS}"
    #                     )
    #         elif key == "name":
    #             if not value or not str(value).strip():
    #                 raise ValueError("Schedule name is required")
    #             value = str(value).strip()
    #
    #         setattr(sched, key, value)
    #
    #     # Recompute next_run if frequency changed
    #     if "frequency" in kwargs:
    #         sched.next_run = self._compute_next_run(sched.frequency)
    #
    #     self._save()
    #     return sched
    #
    # def delete_schedule(self, schedule_id: str) -> bool:
    #     """Delete a report schedule. Returns True if found and deleted."""
    #     if schedule_id in self._schedules:
    #         name = self._schedules[schedule_id].name
    #         del self._schedules[schedule_id]
    #         self._save()
    #         logger.info("Deleted report schedule: %s (%s)", name, schedule_id)
    #         return True
    #     return False
    #
    # def enable_schedule(self, schedule_id: str) -> bool:
    #     """Enable a report schedule. Returns True if found."""
    #     sched = self._schedules.get(schedule_id)
    #     if sched is None:
    #         return False
    #
    #     sched.enabled = True
    #     sched.next_run = self._compute_next_run(sched.frequency)
    #     self._save()
    #     return True
    #
    # def disable_schedule(self, schedule_id: str) -> bool:
    #     """Disable a report schedule. Returns True if found."""
    #     sched = self._schedules.get(schedule_id)
    #     if sched is None:
    #         return False
    #
    #     sched.enabled = False
    #     self._save()
    #     return True
    #
    # def generate_report(self, schedule_id: str) -> dict:
    #     """Generate a report for the given schedule.
    #
    #     Returns the report data as a dict with requested sections.
    #     Raises ValueError if schedule not found.
    #     """
    #     sched = self._schedules.get(schedule_id)
    #     if sched is None:
    #         raise ValueError(f"Schedule not found: {schedule_id}")
    #
    #     now = datetime.now(timezone.utc)
    #     report: dict = {
    #         "schedule_id": sched.id,
    #         "schedule_name": sched.name,
    #         "generated_at": now.isoformat(),
    #         "format": sched.format,
    #         "sections": {},
    #     }
    #
    #     section_generators = {
    #         "traffic_summary": self.generate_section_traffic,
    #         "alerts": self.generate_section_alerts,
    #         "devices": self.generate_section_devices,
    #         "compliance": self.generate_section_compliance,
    #         "risk": self.generate_section_risk,
    #     }
    #
    #     for section_name in sched.sections:
    #         generator = section_generators.get(section_name)
    #         if generator:
    #             report["sections"][section_name] = generator()
    #
    #     # Update schedule metadata
    #     sched.last_run = now.isoformat()
    #     sched.next_run = self._compute_next_run(sched.frequency)
    #     self._save()
    #
    #     return report
    # OLD CODE END

    # OLD CODE START — NET-340: placeholder sections (zeros, a made-up compliance 100 and risk
    # low); report_sections builds the five real ones
    # def generate_section_traffic(self) -> dict:
    #     """Generate traffic summary section.
    #
    #     Returns placeholder data. In production, this would query
    #     OpenSearch for traffic statistics.
    #     """
    #     now = datetime.now(timezone.utc)
    #     return {
    #         "title": "Traffic Summary",
    #         "period": {
    #             "from": (now - timedelta(hours=24)).isoformat(),
    #             "to": now.isoformat(),
    #         },
    #         "total_connections": 0,
    #         "total_bytes_in": 0,
    #         "total_bytes_out": 0,
    #         "top_protocols": [],
    #         "top_destinations": [],
    #         "bandwidth_trend": [],
    #     }
    #
    # def generate_section_alerts(self) -> dict:
    #     """Generate alerts section.
    #
    #     Returns placeholder data. In production, this would query
    #     OpenSearch for Suricata alert statistics.
    #     """
    #     return {
    #         "title": "Alert Summary",
    #         "total_alerts": 0,
    #         "by_severity": {
    #             "critical": 0,
    #             "high": 0,
    #             "medium": 0,
    #             "low": 0,
    #         },
    #         "top_signatures": [],
    #         "top_source_ips": [],
    #     }
    #
    # def generate_section_devices(self) -> dict:
    #     """Generate devices section.
    #
    #     Returns placeholder data. In production, this would query
    #     OpenSearch for device inventory data.
    #     """
    #     return {
    #         "title": "Device Inventory",
    #         "total_devices": 0,
    #         "new_devices": 0,
    #         "devices": [],
    #     }
    #
    # def generate_section_compliance(self) -> dict:
    #     """Generate compliance section.
    #
    #     Returns placeholder data. In production, this would check
    #     security policy compliance metrics.
    #     """
    #     return {
    #         "title": "Compliance Status",
    #         "overall_score": 100,
    #         "checks": [
    #             {
    #                 "name": "IDS Rules Updated",
    #                 "status": "pass",
    #                 "details": "Rules are current",
    #             },
    #             {
    #                 "name": "Log Retention Policy",
    #                 "status": "pass",
    #                 "details": "Within configured limits",
    #             },
    #             {
    #                 "name": "Storage Utilization",
    #                 "status": "pass",
    #                 "details": "Below threshold",
    #             },
    #         ],
    #     }
    #
    # def generate_section_risk(self) -> dict:
    #     """Generate risk section.
    #
    #     Returns placeholder data. In production, this would aggregate
    #     risk scores from the risk scoring service.
    #     """
    #     return {
    #         "title": "Risk Assessment",
    #         "overall_risk_level": "low",
    #         "high_risk_devices": 0,
    #         "medium_risk_devices": 0,
    #         "low_risk_devices": 0,
    #         "top_risk_factors": [],
    #     }
    # OLD CODE END


def restore_report_schedules(
    sections: dict, generator: Any, applied: list, errors: list, notes: list
) -> None:
    """config_backup's restore of the report_schedules section, when the backup has one."""
    if "report_schedules" not in sections:
        return
    if generator is None:
        errors.append("Report schedules can't be restored here")
        return
    try:
        notes.extend(generator.restore_backup(sections["report_schedules"]))
        applied.append("report_schedules")
    except ReportRefused as exc:  # a send under way, or an unreadable store
        errors.append(str(exc))
    except (ValueError, OSError) as exc:
        logger.error("Report schedules not restored: %s", exc)
        errors.append(f"Report schedules not restored: {exc}")
