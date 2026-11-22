"""
Tests for daemon/services/report_generator.py

Covers schedule creation, listing, updating, deletion, enable/disable,
report generation with all section types, validation, and edge cases.
All tests are self-contained with no external dependencies.
"""

import os
import unittest
import tempfile
import shutil

import sys

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from unittest.mock import patch

from api.reports import clean_fields
from services.report_generator import ReportGenerator, ReportRefused, ReportSchedule

# NET-340: the sections module's output shape, so these tests don't query anything
FAKE_SECTIONS = {
    name: {"status": "ok", "coverage": "7 of 7 days", "note": None}
    for name in ("traffic", "alerts", "new_devices", "offline", "data_cap")
}


class TestReportScheduleDataclass(unittest.TestCase):
    """Tests for the ReportSchedule dataclass."""

    def test_schedule_creation(self):
        """A ReportSchedule can be created with all fields."""
        sched = ReportSchedule(
            id="test-id",
            name="Daily Report",
            frequency="daily",
            format="json",
            recipients=["admin@example.com"],
            sections=["traffic_summary", "alerts"],
            enabled=True,
            last_run=None,
            next_run="2026-03-01T06:00:00",
            created_at="2026-02-26T00:00:00",
        )
        self.assertEqual(sched.id, "test-id")
        self.assertEqual(sched.name, "Daily Report")

    def test_schedule_to_dict(self):
        """to_dict() returns a serializable dictionary."""
        sched = ReportSchedule(
            id="test",
            name="Test",
            frequency="daily",
            format="json",
            recipients=[],
            sections=["alerts"],
            enabled=True,
            last_run=None,
            next_run=None,
            created_at="2026-01-01",
        )
        d = sched.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["id"], "test")
        self.assertIsNone(d["last_run"])

    def test_schedule_default_values(self):
        """Default field values are sensible."""
        sched = ReportSchedule(
            id="t",
            name="T",
            frequency="daily",
            format="json",
            created_at="2026-01-01",
        )
        self.assertEqual(sched.recipients, [])
        self.assertEqual(sched.sections, [])
        self.assertTrue(sched.enabled)
        self.assertIsNone(sched.last_run)
        self.assertIsNone(sched.next_run)


class TestReportGeneratorInit(unittest.TestCase):
    """Tests for ReportGenerator initialization."""

    def test_init_with_missing_dir(self):
        """Generator starts empty when directory does not exist."""
        gen = ReportGenerator(
            reports_dir="/tmp/nonexistent-reports-test",
            schedules_file="/tmp/nonexistent-reports-test/schedules.json",
        )
        self.assertEqual(len(gen.list_schedules()), 0)

    def test_persistence_round_trip(self):
        """Created schedules survive reload from disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sfile = os.path.join(tmpdir, "schedules.json")
            gen = ReportGenerator(reports_dir=tmpdir, schedules_file=sfile)
            # OLD CODE START — NET-340: create() takes validated fields; sections are fixed
            # gen.create_schedule(
            #     name="Test",
            #     frequency="daily",
            #     format="json",
            #     sections=["alerts"],
            # )
            # OLD CODE END
            gen.create({"name": "Test", "frequency": "daily"})

            gen2 = ReportGenerator(reports_dir=tmpdir, schedules_file=sfile)
            self.assertEqual(len(gen2.list_schedules()), 1)


class _WithGenerator(unittest.TestCase):
    """NET-340: a generator in a temp dir, and create() returning the stored ReportSchedule."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sfile = os.path.join(self.tmpdir, "schedules.json")
        self.gen = ReportGenerator(reports_dir=self.tmpdir, schedules_file=self.sfile)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make(self, name="Test", frequency="daily", **fields):
        view = self.gen.create({"name": name, "frequency": frequency, **fields})
        return self.gen.get_schedule(view["id"])


# OLD CODE: class TestCreateSchedule(unittest.TestCase): (NET-340: setUp shared in _WithGenerator)
class TestCreateSchedule(_WithGenerator):
    """Tests for create_schedule()."""

    # OLD CODE START — NET-340: setUp and tearDown moved to _WithGenerator
    # def setUp(self):
    #     self.tmpdir = tempfile.mkdtemp()
    #     self.sfile = os.path.join(self.tmpdir, "schedules.json")
    #     self.gen = ReportGenerator(reports_dir=self.tmpdir, schedules_file=self.sfile)
    #
    # def tearDown(self):
    #     shutil.rmtree(self.tmpdir, ignore_errors=True)
    # OLD CODE END

    def test_create_daily_schedule(self):
        """Create a daily report schedule."""
        # OLD CODE START — NET-340: create() takes validated fields; next_run is set only
        # once the schedule is confirmed
        # sched = self.gen.create_schedule(
        #     name="Daily Summary",
        #     frequency="daily",
        #     format="json",
        #     sections=["traffic_summary", "alerts"],
        # )
        # OLD CODE END
        # OLD CODE: sched = self._make("Daily Summary", "daily", confirm=True) (security
        # review: only the card confirms, so a daily schedule is never confirmed)
        sched = self._make("Daily Summary", "daily")
        self.assertEqual(sched.name, "Daily Summary")
        self.assertEqual(sched.frequency, "daily")
        self.assertEqual(sched.format, "json")
        self.assertTrue(sched.enabled)
        # OLD CODE: self.assertIsNotNone(sched.next_run) (no next run until confirmed)
        self.assertIsNone(sched.next_run)

    def test_create_weekly_schedule(self):
        """Create a weekly report schedule."""
        # OLD CODE START — NET-340: the format is always stored as json (plain-text email)
        # sched = self.gen.create_schedule(
        #     name="Weekly Report",
        #     frequency="weekly",
        #     format="html",
        #     sections=["traffic_summary", "devices", "risk"],
        # )
        # self.assertEqual(sched.frequency, "weekly")
        # self.assertEqual(sched.format, "html")
        # OLD CODE END
        sched = self._make("Weekly Report", "weekly")
        self.assertEqual(sched.frequency, "weekly")
        self.assertEqual(sched.format, "json")

    def test_create_monthly_schedule(self):
        """Create a monthly report schedule."""
        # OLD CODE START — NET-340: create() takes validated fields
        # sched = self.gen.create_schedule(
        #     name="Monthly Report",
        #     frequency="monthly",
        #     format="csv",
        #     sections=["compliance"],
        # )
        # OLD CODE END
        sched = self._make("Monthly Report", "monthly")
        self.assertEqual(sched.frequency, "monthly")

    def test_create_with_recipients(self):
        """Create schedule with email recipients."""
        # OLD CODE START — NET-340: create() takes validated fields
        # sched = self.gen.create_schedule(
        #     name="Alert Report",
        #     frequency="daily",
        #     format="json",
        #     sections=["alerts"],
        #     recipients=["admin@example.com", "ops@example.com"],
        # )
        # OLD CODE END
        sched = self._make(recipients=["admin@example.com", "ops@example.com"])
        self.assertEqual(len(sched.recipients), 2)

    # NET-340: the API validates bodies now (clean_fields); the generator takes clean fields
    def test_create_invalid_frequency_raises(self):
        """Invalid frequency raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            # OLD CODE START — NET-340: checked by the API's clean_fields
            # self.gen.create_schedule(
            #     name="Bad",
            #     frequency="hourly",
            #     format="json",
            #     sections=["alerts"],
            # )
            # OLD CODE END
            clean_fields({"name": "Bad", "frequency": "hourly"}, creating=True)
        # OLD CODE: self.assertIn("Invalid frequency", str(ctx.exception))
        self.assertIn("frequency", str(ctx.exception))

    def test_create_invalid_format_raises(self):
        """NET-340: format is accepted and ignored (it was refused when not json/csv/html)."""
        # OLD CODE START — NET-340: format is ignored, json is stored
        # with self.assertRaises(ValueError) as ctx:
        #     self.gen.create_schedule(
        #         name="Bad",
        #         frequency="daily",
        #         format="pdf",
        #         sections=["alerts"],
        #     )
        # self.assertIn("Invalid format", str(ctx.exception))
        # OLD CODE END
        fields = clean_fields({"name": "Fine", "format": "pdf"}, creating=True)
        self.assertNotIn("format", fields)

    def test_create_invalid_section_raises(self):
        """Invalid section raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            # OLD CODE START — NET-340: any explicit sections field is refused
            # self.gen.create_schedule(
            #     name="Bad",
            #     frequency="daily",
            #     format="json",
            #     sections=["nonexistent_section"],
            # )
            # OLD CODE END
            clean_fields({"name": "Bad", "sections": ["nonexistent_section"]}, True)
        # OLD CODE: self.assertIn("Invalid section", str(ctx.exception))
        self.assertIn("all five sections", str(ctx.exception))

    def test_create_empty_sections_raises(self):
        """Empty sections list raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            # OLD CODE START — NET-340: any explicit sections field is refused
            # self.gen.create_schedule(
            #     name="Bad",
            #     frequency="daily",
            #     format="json",
            #     sections=[],
            # )
            # OLD CODE END
            clean_fields({"name": "Bad", "sections": []}, creating=True)
        # OLD CODE: self.assertIn("At least one section", str(ctx.exception))
        self.assertIn("all five sections", str(ctx.exception))

    def test_create_empty_name_raises(self):
        """Empty name raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            # OLD CODE START — NET-340: checked by the API's clean_fields
            # self.gen.create_schedule(
            #     name="",
            #     frequency="daily",
            #     format="json",
            #     sections=["alerts"],
            # )
            # OLD CODE END
            clean_fields({"name": "", "frequency": "daily"}, creating=True)
        # OLD CODE: self.assertIn("name is required", str(ctx.exception))
        self.assertIn("name", str(ctx.exception))

    def test_create_schedule_has_id(self):
        """Created schedule has a UUID id."""
        # OLD CODE START — NET-340: create() takes validated fields
        # sched = self.gen.create_schedule(
        #     name="Test",
        #     frequency="daily",
        #     format="json",
        #     sections=["alerts"],
        # )
        # self.assertTrue(len(sched.id) > 0)
        # OLD CODE END
        sched = self._make()
        self.assertEqual(uuid.UUID(sched.id).version, 4)


# OLD CODE: class TestListAndGetSchedule(unittest.TestCase): (NET-340: setUp in _WithGenerator)
class TestListAndGetSchedule(_WithGenerator):
    """Tests for list_schedules() and get_schedule()."""

    def test_list_empty(self):
        """list_schedules() returns empty list when no schedules exist."""
        self.assertEqual(self.gen.list_schedules(), [])

    def test_list_after_create(self):
        """list_schedules() returns created schedules."""
        # OLD CODE START — NET-340: create() takes validated fields
        # self.gen.create_schedule(
        #     name="R1",
        #     frequency="daily",
        #     format="json",
        #     sections=["alerts"],
        # )
        # self.gen.create_schedule(
        #     name="R2",
        #     frequency="weekly",
        #     format="html",
        #     sections=["devices"],
        # )
        # OLD CODE END
        self._make("R1", "daily")
        self._make("R2", "weekly")
        schedules = self.gen.list_schedules()
        self.assertEqual(len(schedules), 2)

    def test_get_existing_schedule(self):
        """get_schedule() returns the schedule if it exists."""
        # OLD CODE START — NET-340: create() takes validated fields
        # sched = self.gen.create_schedule(
        #     name="Test",
        #     frequency="daily",
        #     format="json",
        #     sections=["alerts"],
        # )
        # OLD CODE END
        sched = self._make()
        found = self.gen.get_schedule(sched.id)
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "Test")

    def test_get_nonexistent_schedule(self):
        """get_schedule() returns None for unknown ID."""
        self.assertIsNone(self.gen.get_schedule("nonexistent"))


# OLD CODE: class TestUpdateSchedule(unittest.TestCase): (NET-340: setUp in _WithGenerator)
class TestUpdateSchedule(_WithGenerator):
    """Tests for update_schedule()."""

    def setUp(self):
        super().setUp()
        # OLD CODE START — NET-340: create() takes validated fields
        # self.sched = self.gen.create_schedule(
        #     name="Original",
        #     frequency="daily",
        #     format="json",
        #     sections=["alerts"],
        # )
        # OLD CODE END
        self.sched = self._make("Original")

    # OLD CODE: update_schedule(id, **kwargs) returned the mutated schedule (NET-340: update(id,
    # fields) swaps in a validated copy and returns the schedule reply)
    def test_update_name(self):
        """Update schedule name."""
        # OLD CODE: updated = self.gen.update_schedule(self.sched.id, name="Updated Name")
        # OLD CODE: self.assertEqual(updated.name, "Updated Name")
        updated = self.gen.update(self.sched.id, {"name": "Updated Name"})
        self.assertEqual(updated["name"], "Updated Name")

    def test_update_frequency(self):
        """Update schedule frequency."""
        # OLD CODE: updated = self.gen.update_schedule(self.sched.id, frequency="weekly")
        # OLD CODE: self.assertEqual(updated.frequency, "weekly")
        updated = self.gen.update(self.sched.id, {"frequency": "weekly"})
        self.assertEqual(updated["frequency"], "weekly")

    def test_update_invalid_frequency_raises(self):
        """Invalid frequency update raises ValueError."""
        with self.assertRaises(ValueError):
            # OLD CODE: self.gen.update_schedule(self.sched.id, frequency="hourly")
            clean_fields({"frequency": "hourly"})

    def test_update_invalid_format_raises(self):
        """NET-340: format is accepted and ignored."""
        # OLD CODE START — NET-340: format is ignored
        # with self.assertRaises(ValueError):
        #     self.gen.update_schedule(self.sched.id, format="pdf")
        # OLD CODE END
        self.assertEqual(clean_fields({"format": "pdf"}), {})

    def test_update_nonexistent_returns_none(self):
        """NET-340: updating a nonexistent schedule is a 404 (it returned None)."""
        # OLD CODE START — NET-340: a ReportRefused with status 404
        # result = self.gen.update_schedule("nonexistent", name="Test")
        # self.assertIsNone(result)
        # OLD CODE END
        with self.assertRaises(ReportRefused) as ctx:
            self.gen.update("nonexistent", {"name": "Test"})
        self.assertEqual(ctx.exception.status, 404)

    def test_update_sections(self):
        """NET-340: an explicit sections field is refused (it replaced the sections)."""
        # OLD CODE START — NET-340: emails always carry all five sections
        # updated = self.gen.update_schedule(
        #     self.sched.id, sections=["traffic_summary", "risk"]
        # )
        # self.assertEqual(updated.sections, ["traffic_summary", "risk"])
        # OLD CODE END
        with self.assertRaises(ValueError):
            clean_fields({"sections": ["traffic_summary", "risk"]})
        self.assertEqual(
            self.gen.get_schedule(self.sched.id).sections,
            ["traffic_summary", "alerts", "devices"],
        )


# OLD CODE: class TestDeleteSchedule(unittest.TestCase): (NET-340: setUp in _WithGenerator)
class TestDeleteSchedule(_WithGenerator):
    """Tests for delete_schedule()."""

    def setUp(self):
        super().setUp()
        # OLD CODE START — NET-340: create() takes validated fields
        # self.sched = self.gen.create_schedule(
        #     name="To Delete",
        #     frequency="daily",
        #     format="json",
        #     sections=["alerts"],
        # )
        # OLD CODE END
        self.sched = self._make("To Delete")

    def test_delete_existing(self):
        """Delete an existing schedule."""
        # OLD CODE: result = self.gen.delete_schedule(self.sched.id)
        # OLD CODE: self.assertTrue(result)
        self.gen.delete(self.sched.id)
        self.assertEqual(len(self.gen.list_schedules()), 0)

    def test_delete_nonexistent(self):
        """NET-340: deleting a nonexistent schedule is a 404 (it returned False)."""
        # OLD CODE: result = self.gen.delete_schedule("nonexistent")
        # OLD CODE: self.assertFalse(result)
        with self.assertRaises(ReportRefused) as ctx:
            self.gen.delete("nonexistent")
        self.assertEqual(ctx.exception.status, 404)


# OLD CODE: class TestEnableDisableSchedule(unittest.TestCase): (NET-340: setUp in _WithGenerator)
class TestEnableDisableSchedule(_WithGenerator):
    """Tests for enable_schedule() and disable_schedule()."""

    def setUp(self):
        super().setUp()
        # OLD CODE START — NET-340: create() takes validated fields
        # self.sched = self.gen.create_schedule(
        #     name="Test",
        #     frequency="daily",
        #     format="json",
        #     sections=["alerts"],
        # )
        # OLD CODE END
        self.sched = self._make()

    # OLD CODE: enable_schedule/disable_schedule returned a bool (NET-340: set_enabled returns
    # the schedule reply, or raises a 404 or 409)
    def test_disable_schedule(self):
        """Disable a schedule."""
        # OLD CODE: result = self.gen.disable_schedule(self.sched.id)
        # OLD CODE: self.assertTrue(result)
        self.assertFalse(self.gen.set_enabled(self.sched.id, False)["enabled"])
        sched = self.gen.get_schedule(self.sched.id)
        self.assertFalse(sched.enabled)

    def test_enable_schedule(self):
        """Enable a disabled schedule."""
        # OLD CODE: self.gen.disable_schedule(self.sched.id)
        # OLD CODE: result = self.gen.enable_schedule(self.sched.id)
        # OLD CODE: self.assertTrue(result)
        self.gen.set_enabled(self.sched.id, False)
        self.assertTrue(self.gen.set_enabled(self.sched.id, True)["enabled"])
        sched = self.gen.get_schedule(self.sched.id)
        self.assertTrue(sched.enabled)

    def test_disable_nonexistent(self):
        """Disable nonexistent schedule is a 404."""
        # OLD CODE: self.assertFalse(self.gen.disable_schedule("nonexistent"))
        with self.assertRaises(ReportRefused):
            self.gen.set_enabled("nonexistent", False)

    def test_enable_nonexistent(self):
        """Enable nonexistent schedule is a 404."""
        # OLD CODE: self.assertFalse(self.gen.enable_schedule("nonexistent"))
        with self.assertRaises(ReportRefused):
            self.gen.set_enabled("nonexistent", True)


# OLD CODE: class TestGenerateReport(unittest.TestCase): (NET-340: setUp in _WithGenerator)
class TestGenerateReport(_WithGenerator):
    """Tests for generate_now() (it was generate_report() and the placeholder sections)."""

    def setUp(self):
        super().setUp()
        # NET-340: the contents come from report_sections; these tests check the frame
        patcher = patch(
            "services.report_sections.build_sections", lambda *_a: dict(FAKE_SECTIONS)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        # OLD CODE START — NET-340: create() takes validated fields; sections are fixed
        # self.sched = self.gen.create_schedule(
        #     name="Full Report",
        #     frequency="daily",
        #     format="json",
        #     sections=["traffic_summary", "alerts", "devices", "compliance", "risk"],
        # )
        # OLD CODE END
        self.sched = self._make("Full Report")

    def test_generate_report_all_sections(self):
        """Generate report with all sections."""
        # OLD CODE START — NET-340: the five real sections replaced the placeholders
        # report = self.gen.generate_report(self.sched.id)
        # self.assertIn("sections", report)
        # self.assertIn("traffic_summary", report["sections"])
        # self.assertIn("alerts", report["sections"])
        # self.assertIn("devices", report["sections"])
        # self.assertIn("compliance", report["sections"])
        # self.assertIn("risk", report["sections"])
        # OLD CODE END
        report = self.gen.generate_now(self.sched.id)
        self.assertEqual(set(report["sections"]), set(FAKE_SECTIONS))

    def test_generate_report_updates_last_run(self):
        """NET-340: a manual report leaves last_run alone (it set it)."""
        self.assertIsNone(self.sched.last_run)
        # OLD CODE: self.gen.generate_report(self.sched.id)
        self.gen.generate_now(self.sched.id)
        sched = self.gen.get_schedule(self.sched.id)
        # OLD CODE: self.assertIsNotNone(sched.last_run)
        self.assertIsNone(sched.last_run)

    def test_generate_report_updates_next_run(self):
        """NET-340: a manual report leaves next_run alone (it moved it)."""
        # OLD CODE START — old_next was assigned but never used (F841)
        # old_next = self.sched.next_run
        # OLD CODE END
        # OLD CODE: self.gen.generate_report(self.sched.id)
        self.gen.generate_now(self.sched.id)
        sched = self.gen.get_schedule(self.sched.id)
        # OLD CODE START — NET-340: unchanged, and None until the schedule is confirmed
        # # next_run should be updated (may or may not differ depending on timing)
        # self.assertIsNotNone(sched.next_run)
        # OLD CODE END
        self.assertEqual(sched.next_run, self.sched.next_run)

    def test_generate_nonexistent_raises(self):
        """Generating report for unknown schedule is a 404."""
        # OLD CODE START — NET-340: a ReportRefused with status 404
        # with self.assertRaises(ValueError):
        #     self.gen.generate_report("nonexistent")
        # OLD CODE END
        with self.assertRaises(ReportRefused) as ctx:
            self.gen.generate_now("nonexistent")
        self.assertEqual(ctx.exception.status, 404)

    def test_generate_report_has_metadata(self):
        """Report includes schedule metadata."""
        # OLD CODE: report = self.gen.generate_report(self.sched.id)
        report = self.gen.generate_now(self.sched.id)
        self.assertEqual(report["schedule_id"], self.sched.id)
        self.assertEqual(report["schedule_name"], "Full Report")
        self.assertIn("generated_at", report)
        # OLD CODE: self.assertEqual(report["format"], "json") (NET-340: no format; a trigger)
        self.assertEqual(report["trigger"], "manual")

    # OLD CODE START — NET-340: the placeholder section generators are gone (report_sections
    # builds the five real sections; its own tests cover them), and sections are fixed
    # def test_traffic_section_structure(self):
    #     """Traffic summary section has expected keys."""
    #     section = self.gen.generate_section_traffic()
    #     self.assertEqual(section["title"], "Traffic Summary")
    #     self.assertIn("total_connections", section)
    #     self.assertIn("period", section)
    #
    # def test_alerts_section_structure(self):
    #     """Alerts section has expected keys."""
    #     section = self.gen.generate_section_alerts()
    #     self.assertEqual(section["title"], "Alert Summary")
    #     self.assertIn("by_severity", section)
    #
    # def test_devices_section_structure(self):
    #     """Devices section has expected keys."""
    #     section = self.gen.generate_section_devices()
    #     self.assertEqual(section["title"], "Device Inventory")
    #     self.assertIn("total_devices", section)
    #
    # def test_compliance_section_structure(self):
    #     """Compliance section has expected keys."""
    #     section = self.gen.generate_section_compliance()
    #     self.assertEqual(section["title"], "Compliance Status")
    #     self.assertIn("overall_score", section)
    #     self.assertIn("checks", section)
    #
    # def test_risk_section_structure(self):
    #     """Risk section has expected keys."""
    #     section = self.gen.generate_section_risk()
    #     self.assertEqual(section["title"], "Risk Assessment")
    #     self.assertIn("overall_risk_level", section)
    #
    # def test_generate_single_section_report(self):
    #     """Generate report with a single section."""
    #     sched = self.gen.create_schedule(
    #         name="Alerts Only",
    #         frequency="daily",
    #         format="json",
    #         sections=["alerts"],
    #     )
    #     report = self.gen.generate_report(sched.id)
    #     self.assertEqual(len(report["sections"]), 1)
    #     self.assertIn("alerts", report["sections"])
    # OLD CODE END


class TestValidConstants(unittest.TestCase):
    """Tests for validation constants."""

    def test_valid_frequencies(self):
        """All expected frequencies are listed."""
        self.assertIn("daily", ReportGenerator.VALID_FREQUENCIES)
        self.assertIn("weekly", ReportGenerator.VALID_FREQUENCIES)
        self.assertIn("monthly", ReportGenerator.VALID_FREQUENCIES)

    def test_valid_formats(self):
        """All expected formats are listed."""
        self.assertIn("json", ReportGenerator.VALID_FORMATS)
        self.assertIn("csv", ReportGenerator.VALID_FORMATS)
        self.assertIn("html", ReportGenerator.VALID_FORMATS)

    def test_valid_sections(self):
        """All expected sections are listed."""
        self.assertIn("traffic_summary", ReportGenerator.VALID_SECTIONS)
        self.assertIn("alerts", ReportGenerator.VALID_SECTIONS)
        self.assertIn("devices", ReportGenerator.VALID_SECTIONS)
        self.assertIn("compliance", ReportGenerator.VALID_SECTIONS)
        self.assertIn("risk", ReportGenerator.VALID_SECTIONS)


if __name__ == "__main__":
    unittest.main()
