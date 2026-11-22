"""NET-340: report schedules in a config backup (plan §3.2 "Restore order", §3.7 "Backups").

A restore brings schedules back unconfirmed (paused) with a warning, never with digests, claims
or deliveries; it is refused while a report is being sent; a restore stopped between its two
writes leaves schedules paused; and an older daemon skips the section and applies the rest.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import backup_checks, config_backup, report_schedule  # noqa: E402
from services.backup_checks import section_errors  # noqa: E402
from services.config_backup import ConfigBackup  # noqa: E402
from services.report_generator import ReportGenerator  # noqa: E402
from services.report_schedule import RESTORE_SENDING, RESTORED_PAUSED  # noqa: E402


def _generator(root) -> ReportGenerator:
    return ReportGenerator(
        reports_dir=str(root / "reports"),
        schedules_file=str(root / "report_schedules.json"),
    )


@pytest.fixture
def box(tmp_path):
    root = tmp_path / "box"
    root.mkdir()
    paths = {k: str(root / f"{k}.json") for k in config_backup._DEFAULT_PATHS}
    gen = _generator(root)
    backup = ConfigBackup(paths, report_generator=gen)
    return backup, gen, root


def _backup_of(gen: ReportGenerator) -> dict:
    """A real export's metadata and report section, plus one other section to apply."""
    data = ConfigBackup(
        {k: f"/nonexistent/{k}" for k in config_backup._DEFAULT_PATHS},
        report_generator=gen,
    ).export_config()
    sections = {
        "report_schedules": data["sections"]["report_schedules"],
        "excluded_ips": ["192.0.2.7"],
    }
    return {**data, "sections": sections}


def test_a_backup_round_trip_restores_schedules_paused(box, tmp_path):
    source = _generator(tmp_path)
    card, _ = source.upsert_card(
        {"recipients": ["a@example.com"], "weekday": 3, "hour": 19, "confirm": True}
    )
    data = _backup_of(source)
    (entry,) = data["sections"]["report_schedules"]
    assert (entry["weekday"], entry["hour"], entry["card"]) == (3, 19, True)
    assert not {"confirmed_digest", "claim", "last_delivery", "rev"} & set(entry)
    assert section_errors(data["sections"]) == {}

    backup, gen, _ = box
    result = backup.import_config(data)
    assert result["success"], result
    assert "report_schedules" in result["applied"]
    assert RESTORED_PAUSED in result["warnings"]
    (view,) = gen.list_views()
    assert view["id"] == card["id"] and view["recipients"] == ["a@example.com"]
    assert (view["weekday"], view["hour"], view["card"]) == (3, 19, True)
    assert not view["confirmed"] and view["needs_review"]


def test_restore_keeps_only_the_first_card(box):
    backup, gen, _ = box
    entries = [
        {
            "id": sid,
            "name": "W",
            "frequency": "weekly",
            "format": "json",
            "recipients": [],
            "sections": ["traffic_summary", "alerts", "devices"],
            "enabled": True,
            "created_at": "2026-11-01T00:00:00Z",
            "weekday": 0,
            "hour": 8,
            "card": True,
        }
        for sid in (
            "11111111-1111-4111-8111-111111111111",
            "22222222-2222-4222-8222-222222222222",
        )
    ]
    assert gen.restore_backup(entries) == [RESTORED_PAUSED]
    assert [v["card"] for v in gen.list_views()] == [True, False]


def test_a_restore_while_a_report_is_sent_is_a_section_error(box):
    backup, gen, _ = box
    sid = gen.create({"name": "W"})["id"]
    gen._meta = {**gen._meta, sid: {**gen._meta[sid], "claim": {"claim_id": "x"}}}
    data = _backup_of(gen)
    result = backup.import_config(data)
    assert RESTORE_SENDING in result["errors"]
    assert "excluded_ips" in result["applied"]  # the other sections still apply


def test_a_same_settings_restore_stopped_between_its_writes_leaves_it_paused(
    box, monkeypatch
):
    backup, gen, root = box
    sid = gen.upsert_card({"recipients": ["a@example.com"], "confirm": True})[0]["id"]
    items = gen.export_backup()  # the very same settings
    real = report_schedule._replace_file

    def stop_at_schedules(path, data):
        if path.name == "report_schedules.json":
            raise OSError("stopped")
        return real(path, data)

    monkeypatch.setattr("services.report_generator._replace_file", stop_at_schedules)
    with pytest.raises(OSError):
        gen.restore_backup(items)
    monkeypatch.setattr("services.report_generator._replace_file", real)
    restarted = _generator(root)
    assert restarted.view(sid)["needs_review"]
    meta = json.loads((root / "report_schedule_meta.json").read_text())
    assert meta[sid]["confirmed_digest"] is None and meta[sid]["rev"] == 2


def test_an_older_daemon_skips_the_section_and_applies_the_rest(box, monkeypatch):
    backup, gen, _ = box
    source = ReportGenerator(
        reports_dir=str(box[2] / "src-reports"),
        schedules_file=str(box[2] / "src" / "report_schedules.json"),
    )
    source.create({"name": "W", "recipients": ["a@example.com"]})
    data = _backup_of(source)
    # as an older daemon sees it: no such section, no check and no restore code
    monkeypatch.setattr(
        config_backup,
        "_VALID_SECTIONS",
        config_backup._VALID_SECTIONS - {"report_schedules"},
    )
    monkeypatch.setattr(
        backup_checks,
        "_SECTION_CHECKS",
        {
            k: v
            for k, v in backup_checks._SECTION_CHECKS.items()
            if k != "report_schedules"
        },
    )
    monkeypatch.setattr(config_backup, "restore_report_schedules", lambda *_a: None)
    validation = backup.validate_import(data)
    assert validation["is_valid"]
    assert (
        "Unknown section 'report_schedules' will be skipped" in validation["warnings"]
    )
    result = backup.import_config(data, validation)
    assert result["success"] and "excluded_ips" in result["applied"]
    assert gen.list_views() == []


def test_a_bad_section_refuses_the_whole_import(box):
    backup, gen, _ = box
    data = _backup_of(gen)
    data["sections"]["report_schedules"] = [{"id": "nope"}]
    validation = backup.validate_import(data)
    assert not validation["is_valid"]
    assert any(
        e.startswith("Report schedules not restored") for e in validation["errors"]
    )
    assert backup.import_config(data)["applied"] == []


def test_create_app_wires_the_job_the_routes_and_the_backup(tmp_path):
    """Wiring (plan §6): the F1 job, the generator on the app, and the backup's generator."""
    from tests.test_devices_watched_api import _real_app

    app = _real_app(tmp_path)
    (job,) = [r for r in app["scheduler"].view() if r["name"] == "weekly-report"]
    assert (job["label"], job["every_s"]) == ("Scheduled reports", 300)
    assert app["scheduler"]._jobs["weekly-report"].deadline_s == 240
    gen = app["report_generator"]
    assert app["scheduler"]._jobs["weekly-report"].run == gen.run_due
    assert gen._hub is not None and gen._deps.ledger is not None
    assert app["config_backup"]._report_generator is gen
    paths = {r.canonical for r in app.router.resources()}
    assert {"/api/reports/card", "/api/reports/history/{id}/{report_id}"} <= paths


@pytest.mark.asyncio
async def test_an_export_with_unreadable_schedules_is_a_503_that_says_why(tmp_path):
    """Review: it was the generic 500, so the owner saw "Something went wrong"."""
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from api.backup import register_backup_routes
    from api.error_replies import safe_error_middleware
    from services.report_schedule import UNAVAILABLE

    (tmp_path / "report_schedules.json").write_text("not json")
    paths = {k: str(tmp_path / f"{k}.json") for k in config_backup._DEFAULT_PATHS}
    app = web.Application(middlewares=[safe_error_middleware])
    register_backup_routes(
        app, ConfigBackup(paths, report_generator=_generator(tmp_path))
    )
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/api/backup/export")
        assert resp.status == 503
        assert (await resp.json())["error"] == UNAVAILABLE


@pytest.mark.parametrize(
    "bad",
    [
        {"recipients": ["a@example.com,b@example.com"]},  # the old API took any string
        {"recipients": ["owner"]},
        {"name": "x" * 101},
    ],
)
def test_a_stored_schedule_a_restore_refuses_is_left_out_not_fatal(
    tmp_path, bad, caplog
):
    """Python review: one such schedule refused the whole backup download."""
    legacy = {
        "id": "5f0d0f6e-7b8a-4c3d-9e2f-1a2b3c4d5e6f",
        "name": "Old",
        "frequency": "weekly",
        "format": "html",
        "recipients": [],
        "sections": ["traffic_summary"],
        "enabled": True,
        "last_run": None,
        "next_run": None,
        "created_at": "2026-01-01T00:00:00+00:00",
        **bad,
    }
    (tmp_path / "report_schedules.json").write_text(json.dumps([legacy]))
    gen = _generator(tmp_path)
    good = gen.create({"name": "Fine", "recipients": ["a@example.com"]})
    paths = {k: str(tmp_path / f"{k}.json") for k in config_backup._DEFAULT_PATHS}
    body, _ = ConfigBackup(paths, report_generator=gen).export_file()
    exported = json.loads(bytes(body))["sections"]["report_schedules"]
    assert [e["id"] for e in exported] == [good["id"]]
    assert legacy["id"] in caplog.text and "a@example.com" not in caplog.text
