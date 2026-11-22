# NET-340 weekly report: the build contract

`plans/2026-11-21-weekly-report.md` (the approved plan) is the spec. This file pins the parts the three builders share: the module boundaries, who owns which file, and the JSON shapes. If a shape here and the plan disagree, the plan wins for behaviour and this file wins for field names. Raise any change with the lead first; don't change a shape on your own.

## Who owns which files

Each file has one owner. Don't edit a file you don't own; ask its owner or the lead.

| Owner | Files |
|---|---|
| **state** (daemon state machine) | `daemon/services/report_generator.py`, `daemon/services/report_schedule.py` (pure rules), `daemon/api/reports.py`, `daemon/api/server.py` (job + wiring only), `daemon/services/config_backup.py`, `daemon/services/backup_checks.py`, tests `daemon/tests/test_report_generator.py`, `test_reports_api.py`, backup tests |
| **sections** (report contents) | new `daemon/services/report_sections.py`, new `daemon/services/report_text.py`, `daemon/services/event_journal.py` (`scan()`), `daemon/services/device_registry.py` (`get_devices` `fields`/`timeout`), `daemon/services/usage_report.py` (`lower_bound` public), `daemon/services/usage_ledger.py` (inventory extraction), `daemon/services/notification_hub.py` (`send_report_email`), `daemon/services/notification_config.py` (`is_address` public), `daemon/api/alerts.py` only if a helper must be extracted (OLD CODE kept), tests `test_report_sections.py`, `test_report_text.py`, `test_event_journal.py`, `test_report_email.py` |
| **web** | `web/src/lib/api/reports.ts`, `web/src/routes/api/reports/**`, new `web/src/routes/reports/**`, new `web/src/lib/components/settings/ReportScheduleCard.svelte` (or beside `DataCapCard.svelte`, wherever it lives), `web/src/routes/settings/tabs/NotificationsTab.svelte`, `web/src/lib/components/shell/nav.ts`, `web/src/routes/settings/tabs/BackupTab.svelte` (label only), their tests, `web/e2e/visual/**` additions and the visual fixture daemon's report routes |
| **lead** | `plans/**`, `scripts/remote/deploy-weekly-report.sh`, `scripts/remote/rollback-weekly-report.sh`, `tracking-fixes/**`, `Debugging/**`, the roadmap amendment |

## The boundary between state and sections

`report_sections.py` exposes:

```python
@dataclass(frozen=True)
class Period:
    first: date          # local dates, inclusive
    last: date
    start: datetime      # aware UTC, = day_bounds(first)[0]
    end: datetime        # aware UTC, = day_bounds(last)[1]  (exclusive)
    tz: str              # the ledger zone

@dataclass(frozen=True)
class ReportDeps:
    ledger: Any                 # UsageLedger (snapshot/now/current_rules/owner zone read once)
    journal: Any                # EventJournal
    registry: Any               # DeviceRegistry
    watched: Any                # WatchedDevices
    tracker: Any                # bandwidth tracker (get_cap)
    client_factory: Callable[[], Any]   # returns the no-retry OpenSearch client
    network_index: str

def build_sections(period: Period, deps: ReportDeps, deadline: float) -> dict:
    """The five sections below, keyed by name. Never raises: a failing section is `unavailable`.
    `deadline` is an absolute time.monotonic() value; nothing runs past it."""
```

`report_text.py` exposes:

```python
def render_email(report: dict) -> tuple[str, str]:
    """(subject, plain-text body) for a full report dict (shape below). Pure, no I/O."""
```

`NotificationHub.send_report_email(recipients: list[str], subject: str, text: str) -> dict` returns
`{"result": "sent"|"partly_sent"|"failed"|"not_configured", "refused": [str], "error": str|None}`. It's sync; the state module calls it from the job thread.

`report_generator.py` (state) owns: periods and boundaries (`period_for(frequency, boundary_date, tz)`, `latest_boundary(...)`), schedules, sidecar, consent, claims, recovery, files, `run_due(deadline)`, `generate_now(id)`, and assembling the report dict around `build_sections()`.

## JSON shapes

Errors: `{"error": "<plain-English message>"}` with 400, 404, 409 or 503, as today.

### Schedule (every schedule reply and list item)

```json
{
  "id": "uuid4", "name": "Weekly report",
  "frequency": "weekly", "format": "json",
  "recipients": ["owner@example.com"],
  "sections": ["traffic_summary", "alerts", "devices"],
  "enabled": true,
  "last_run": "ISO UTC | null", "next_run": "ISO UTC | null", "created_at": "ISO UTC",
  "rev": 3,
  "confirm_token": "hex sha256",
  "weekday": 0,
  "hour": 8,
  "tz": "Europe/London",
  "next_send": "ISO UTC | null",
  "confirmed": true,
  "needs_review": false,
  "card": true,
  "sending": false,
  "last_period": {"first": "2026-11-10", "last": "2026-11-16"},
  "last_delivery": {"result": "sent", "at": "ISO UTC", "report_id": "20261117T080012Z-a1b2c3"}
}
```

- `weekday`: 0 = Monday … 6 = Sunday (Python `date.weekday()`).
- `last_period` and `last_delivery` can be `null`.
- `last_delivery.result`: `sent | partly_sent | failed | not_configured | not_emailed | unknown`.
- `GET /api/reports/schedules` returns `{"schedules": [ … ], "count": 1, "tz": "Europe/London"}`. The top-level `tz` is the ledger zone, so the card can name it before any schedule exists.
- `PUT /api/reports/card` returns the upserted schedule (this shape): 201 when it created the card schedule, 200 when it updated it.

### Report summary (`GET /api/reports/history?schedule=<uuid>`)

```json
{"reports": [{
  "id": "20261117T080012Z-a1b2c3",
  "schedule_id": "uuid4",
  "trigger": "scheduled",
  "period": {"first": "2026-11-10", "last": "2026-11-16"},
  "generated_at": "ISO UTC",
  "delivery": {"result": "sent"},
  "status": {"traffic": "ok", "alerts": "partial", "new_devices": "ok", "offline": "ok", "data_cap": "ok"}
}]}
```

Newest first. `trigger`: `scheduled | manual`. A manual report's `delivery.result` is `not_emailed`. Without `?schedule=`, it lists every schedule's reports, newest first.

### Report (`GET /api/reports/history/{id}/{report_id}`, and the `POST /api/reports/generate/{id}` reply)

```json
{
  "id": "20261117T080012Z-a1b2c3",
  "schedule_id": "uuid4",
  "schedule_name": "Weekly report",
  "trigger": "scheduled",
  "frequency": "weekly",
  "period": {"first": "2026-11-10", "last": "2026-11-16", "start": "ISO UTC", "end": "ISO UTC", "tz": "Europe/London", "days": 7},
  "generated_at": "ISO UTC",
  "duration_s": 12.4,
  "delivery": {"result": "sent", "at": "ISO UTC | null", "recipients": 2, "refused": 0, "error": null},
  "sections": { "traffic": {}, "alerts": {}, "new_devices": {}, "offline": {}, "data_cap": {} }
}
```

`delivery.result` adds `pending` (claimed, not finished yet) to the schedule's list. `recipients` and `refused` are counts; addresses are never in a report file.

Every section has:

```json
{"status": "ok | partial | unavailable", "coverage": "plain-English line", "note": "reason when partial or unavailable | null"}
```

plus its own fields. Byte figures are integers.

**`traffic`**

```json
{
  "download": 0, "upload": 0, "total": 0, "local": 0,
  "counted_total": 0,
  "provisional": false,
  "days_covered": 7, "days_total": 7,
  "busiest": {"date": "2026-11-12", "total": 0},
  "days": [{"date": "2026-11-10", "download": 0, "upload": 0, "total": 0, "covered": true}]
}
```

`busiest` is `null` when no day has figures. `counted_total` is the current-rules lower bound.

**`alerts`**

```json
{
  "total": 0,
  "by_severity": {"1": 0, "2": 0, "3": 0, "other": 0},
  "days": [{"date": "2026-11-10", "count": 0, "stored": "full | partial | absent | unknown"}],
  "worst": [{"rule": "ET …", "severity": 1, "count": 0, "family": "…", "what": "…", "risk": "…", "todo": "…"}],
  "worst_note": null
}
```

`worst` is `null`, with `worst_note` saying why, when the ranking didn't finish. `severity` is `null` for unknown. An unnamed rule has `"rule": "Unnamed rule"`.

**`new_devices`**

```json
{
  "count": 0,
  "listed": [{"mac": "aa:bb:…", "name": "… | null", "vendor": "… | null", "ip": "… | null", "first_seen": "ISO UTC"}],
  "examined_from": "ISO UTC | null",
  "truncated": false
}
```

At most 50 listed; `count` is the full number.

**`offline`**

```json
{
  "incidents": [{
    "mac": "aa:bb:…", "name": "…",
    "from": "ISO UTC", "to": "ISO UTC | null",
    "minutes": 42,
    "state": "returned | returned_unrecorded | still_offline | return_unrecorded",
    "detail": "plain-English line, e.g. 'returned before 14 Nov 09:12, time not recorded' | null"
  }],
  "watched_now": 3
}
```

`from`/`to` are clipped to the period. `minutes` is `null` when `to` is `null`.

**`data_cap`**

```json
{
  "cap_bytes": 1000000000000,
  "month": "2026-11",
  "used_counted": 0, "used_provisional": 0,
  "percent": 41.2,
  "days_counted": 14, "days_so_far": 16,
  "crossings": [{"month": "2026-11", "threshold": 80, "cap": 1000000000000, "at": "ISO UTC"}]
}
```

`cap_bytes` and `percent` are `null` with no cap. `percent` uses `used_counted`.

## Routes (all under `/api/reports`, daemon token required as today)

| Method | Path | Notes |
|---|---|---|
| GET | `/schedules` | list (shape above) |
| POST | `/schedules` | create; `confirm: true` confirms |
| GET | `/schedules/{id}` | one |
| PUT | `/schedules/{id}` | partial update; `confirm` + `confirm_token` to confirm; `rev` for conflicts |
| DELETE | `/schedules/{id}` | 409 during a claim |
| POST | `/schedules/{id}/enable`, `/disable` | never confirm |
| PUT | `/card` | singleton upsert; body `{enabled, weekday, hour, recipients, confirm: true, confirm_token?, rev?}` |
| POST | `/generate/{id}` | manual report (60 s web proxy) |
| GET | `/history` | `?schedule=` optional |
| GET | `/history/{id}/{report_id}` | one report |

Keep any existing route paths that the old web helpers call working, unless the plan retires them.
