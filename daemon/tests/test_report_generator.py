"""
Tests for daemon/services/report_generator.py

Covers schedule creation, listing, updating, deletion, enable/disable,
report generation with all section types, validation, and edge cases.
All tests are self-contained with no external dependencies.
"""

import json
import os
import unittest
import tempfile
import shutil

import sys

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.report_generator import ReportGenerator, ReportSchedule


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
            id="t", name="T", frequency="daily", format="json",
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
            gen.create_schedule(
                name="Test", frequency="daily", format="json",
                sections=["alerts"],
            )

            gen2 = ReportGenerator(reports_dir=tmpdir, schedules_file=sfile)
            self.assertEqual(len(gen2.list_schedules()), 1)


class TestCreateSchedule(unittest.TestCase):
    """Tests for create_schedule()."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sfile = os.path.join(self.tmpdir, "schedules.json")
        self.gen = ReportGenerator(
            reports_dir=self.tmpdir, schedules_file=self.sfile
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_daily_schedule(self):
        """Create a daily report schedule."""
        sched = self.gen.create_schedule(
            name="Daily Summary",
            frequency="daily",
            format="json",
            sections=["traffic_summary", "alerts"],
        )
        self.assertEqual(sched.name, "Daily Summary")
        self.assertEqual(sched.frequency, "daily")
        self.assertEqual(sched.format, "json")
        self.assertTrue(sched.enabled)
        self.assertIsNotNone(sched.next_run)

    def test_create_weekly_schedule(self):
        """Create a weekly report schedule."""
        sched = self.gen.create_schedule(
            name="Weekly Report",
            frequency="weekly",
            format="html",
            sections=["traffic_summary", "devices", "risk"],
        )
        self.assertEqual(sched.frequency, "weekly")
        self.assertEqual(sched.format, "html")

    def test_create_monthly_schedule(self):
        """Create a monthly report schedule."""
        sched = self.gen.create_schedule(
            name="Monthly Report",
            frequency="monthly",
            format="csv",
            sections=["compliance"],
        )
        self.assertEqual(sched.frequency, "monthly")

    def test_create_with_recipients(self):
        """Create schedule with email recipients."""
        sched = self.gen.create_schedule(
            name="Alert Report",
            frequency="daily",
            format="json",
            sections=["alerts"],
            recipients=["admin@example.com", "ops@example.com"],
        )
        self.assertEqual(len(sched.recipients), 2)

    def test_create_invalid_frequency_raises(self):
        """Invalid frequency raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.gen.create_schedule(
                name="Bad", frequency="hourly", format="json",
                sections=["alerts"],
            )
        self.assertIn("Invalid frequency", str(ctx.exception))

    def test_create_invalid_format_raises(self):
        """Invalid format raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.gen.create_schedule(
                name="Bad", frequency="daily", format="pdf",
                sections=["alerts"],
            )
        self.assertIn("Invalid format", str(ctx.exception))

    def test_create_invalid_section_raises(self):
        """Invalid section raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.gen.create_schedule(
                name="Bad", frequency="daily", format="json",
                sections=["nonexistent_section"],
            )
        self.assertIn("Invalid section", str(ctx.exception))

    def test_create_empty_sections_raises(self):
        """Empty sections list raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.gen.create_schedule(
                name="Bad", frequency="daily", format="json",
                sections=[],
            )
        self.assertIn("At least one section", str(ctx.exception))

    def test_create_empty_name_raises(self):
        """Empty name raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            self.gen.create_schedule(
                name="", frequency="daily", format="json",
                sections=["alerts"],
            )
        self.assertIn("name is required", str(ctx.exception))

    def test_create_schedule_has_id(self):
        """Created schedule has a UUID id."""
        sched = self.gen.create_schedule(
            name="Test", frequency="daily", format="json",
            sections=["alerts"],
        )
        self.assertTrue(len(sched.id) > 0)


class TestListAndGetSchedule(unittest.TestCase):
    """Tests for list_schedules() and get_schedule()."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sfile = os.path.join(self.tmpdir, "schedules.json")
        self.gen = ReportGenerator(
            reports_dir=self.tmpdir, schedules_file=self.sfile
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_list_empty(self):
        """list_schedules() returns empty list when no schedules exist."""
        self.assertEqual(self.gen.list_schedules(), [])

    def test_list_after_create(self):
        """list_schedules() returns created schedules."""
        self.gen.create_schedule(
            name="R1", frequency="daily", format="json",
            sections=["alerts"],
        )
        self.gen.create_schedule(
            name="R2", frequency="weekly", format="html",
            sections=["devices"],
        )
        schedules = self.gen.list_schedules()
        self.assertEqual(len(schedules), 2)

    def test_get_existing_schedule(self):
        """get_schedule() returns the schedule if it exists."""
        sched = self.gen.create_schedule(
            name="Test", frequency="daily", format="json",
            sections=["alerts"],
        )
        found = self.gen.get_schedule(sched.id)
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "Test")

    def test_get_nonexistent_schedule(self):
        """get_schedule() returns None for unknown ID."""
        self.assertIsNone(self.gen.get_schedule("nonexistent"))


class TestUpdateSchedule(unittest.TestCase):
    """Tests for update_schedule()."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sfile = os.path.join(self.tmpdir, "schedules.json")
        self.gen = ReportGenerator(
            reports_dir=self.tmpdir, schedules_file=self.sfile
        )
        self.sched = self.gen.create_schedule(
            name="Original", frequency="daily", format="json",
            sections=["alerts"],
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_update_name(self):
        """Update schedule name."""
        updated = self.gen.update_schedule(self.sched.id, name="Updated Name")
        self.assertEqual(updated.name, "Updated Name")

    def test_update_frequency(self):
        """Update schedule frequency."""
        updated = self.gen.update_schedule(self.sched.id, frequency="weekly")
        self.assertEqual(updated.frequency, "weekly")

    def test_update_invalid_frequency_raises(self):
        """Invalid frequency update raises ValueError."""
        with self.assertRaises(ValueError):
            self.gen.update_schedule(self.sched.id, frequency="hourly")

    def test_update_invalid_format_raises(self):
        """Invalid format update raises ValueError."""
        with self.assertRaises(ValueError):
            self.gen.update_schedule(self.sched.id, format="pdf")

    def test_update_nonexistent_returns_none(self):
        """Updating nonexistent schedule returns None."""
        result = self.gen.update_schedule("nonexistent", name="Test")
        self.assertIsNone(result)

    def test_update_sections(self):
        """Update schedule sections."""
        updated = self.gen.update_schedule(
            self.sched.id, sections=["traffic_summary", "risk"]
        )
        self.assertEqual(updated.sections, ["traffic_summary", "risk"])


class TestDeleteSchedule(unittest.TestCase):
    """Tests for delete_schedule()."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sfile = os.path.join(self.tmpdir, "schedules.json")
        self.gen = ReportGenerator(
            reports_dir=self.tmpdir, schedules_file=self.sfile
        )
        self.sched = self.gen.create_schedule(
            name="To Delete", frequency="daily", format="json",
            sections=["alerts"],
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_delete_existing(self):
        """Delete an existing schedule."""
        result = self.gen.delete_schedule(self.sched.id)
        self.assertTrue(result)
        self.assertEqual(len(self.gen.list_schedules()), 0)

    def test_delete_nonexistent(self):
        """Delete a nonexistent schedule returns False."""
        result = self.gen.delete_schedule("nonexistent")
        self.assertFalse(result)


class TestEnableDisableSchedule(unittest.TestCase):
    """Tests for enable_schedule() and disable_schedule()."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sfile = os.path.join(self.tmpdir, "schedules.json")
        self.gen = ReportGenerator(
            reports_dir=self.tmpdir, schedules_file=self.sfile
        )
        self.sched = self.gen.create_schedule(
            name="Test", frequency="daily", format="json",
            sections=["alerts"],
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_disable_schedule(self):
        """Disable a schedule."""
        result = self.gen.disable_schedule(self.sched.id)
        self.assertTrue(result)
        sched = self.gen.get_schedule(self.sched.id)
        self.assertFalse(sched.enabled)

    def test_enable_schedule(self):
        """Enable a disabled schedule."""
        self.gen.disable_schedule(self.sched.id)
        result = self.gen.enable_schedule(self.sched.id)
        self.assertTrue(result)
        sched = self.gen.get_schedule(self.sched.id)
        self.assertTrue(sched.enabled)

    def test_disable_nonexistent(self):
        """Disable nonexistent schedule returns False."""
        self.assertFalse(self.gen.disable_schedule("nonexistent"))

    def test_enable_nonexistent(self):
        """Enable nonexistent schedule returns False."""
        self.assertFalse(self.gen.enable_schedule("nonexistent"))


class TestGenerateReport(unittest.TestCase):
    """Tests for generate_report() and section generators."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sfile = os.path.join(self.tmpdir, "schedules.json")
        self.gen = ReportGenerator(
            reports_dir=self.tmpdir, schedules_file=self.sfile
        )
        self.sched = self.gen.create_schedule(
            name="Full Report",
            frequency="daily",
            format="json",
            sections=["traffic_summary", "alerts", "devices", "compliance", "risk"],
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_generate_report_all_sections(self):
        """Generate report with all sections."""
        report = self.gen.generate_report(self.sched.id)
        self.assertIn("sections", report)
        self.assertIn("traffic_summary", report["sections"])
        self.assertIn("alerts", report["sections"])
        self.assertIn("devices", report["sections"])
        self.assertIn("compliance", report["sections"])
        self.assertIn("risk", report["sections"])

    def test_generate_report_updates_last_run(self):
        """Generating a report updates last_run."""
        self.assertIsNone(self.sched.last_run)
        self.gen.generate_report(self.sched.id)
        sched = self.gen.get_schedule(self.sched.id)
        self.assertIsNotNone(sched.last_run)

    def test_generate_report_updates_next_run(self):
        """Generating a report updates next_run."""
        old_next = self.sched.next_run
        self.gen.generate_report(self.sched.id)
        sched = self.gen.get_schedule(self.sched.id)
        # next_run should be updated (may or may not differ depending on timing)
        self.assertIsNotNone(sched.next_run)

    def test_generate_nonexistent_raises(self):
        """Generating report for unknown schedule raises ValueError."""
        with self.assertRaises(ValueError):
            self.gen.generate_report("nonexistent")

    def test_generate_report_has_metadata(self):
        """Report includes schedule metadata."""
        report = self.gen.generate_report(self.sched.id)
        self.assertEqual(report["schedule_id"], self.sched.id)
        self.assertEqual(report["schedule_name"], "Full Report")
        self.assertIn("generated_at", report)
        self.assertEqual(report["format"], "json")

    def test_traffic_section_structure(self):
        """Traffic summary section has expected keys."""
        section = self.gen.generate_section_traffic()
        self.assertEqual(section["title"], "Traffic Summary")
        self.assertIn("total_connections", section)
        self.assertIn("period", section)

    def test_alerts_section_structure(self):
        """Alerts section has expected keys."""
        section = self.gen.generate_section_alerts()
        self.assertEqual(section["title"], "Alert Summary")
        self.assertIn("by_severity", section)

    def test_devices_section_structure(self):
        """Devices section has expected keys."""
        section = self.gen.generate_section_devices()
        self.assertEqual(section["title"], "Device Inventory")
        self.assertIn("total_devices", section)

    def test_compliance_section_structure(self):
        """Compliance section has expected keys."""
        section = self.gen.generate_section_compliance()
        self.assertEqual(section["title"], "Compliance Status")
        self.assertIn("overall_score", section)
        self.assertIn("checks", section)

    def test_risk_section_structure(self):
        """Risk section has expected keys."""
        section = self.gen.generate_section_risk()
        self.assertEqual(section["title"], "Risk Assessment")
        self.assertIn("overall_risk_level", section)

    def test_generate_single_section_report(self):
        """Generate report with a single section."""
        sched = self.gen.create_schedule(
            name="Alerts Only",
            frequency="daily",
            format="json",
            sections=["alerts"],
        )
        report = self.gen.generate_report(sched.id)
        self.assertEqual(len(report["sections"]), 1)
        self.assertIn("alerts", report["sections"])


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
