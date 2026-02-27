"""
NetTap Scheduled Report Generator

Generates periodic network summary reports in JSON, CSV, or HTML format.
Reports can include traffic summaries, alert digests, device inventories,
compliance status, and risk assessments.

All schedule metadata is persisted to a local JSON file. Report output
files are stored in a configurable directory.
"""

import json
import logging
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("nettap.services.report_generator")


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


class ReportGenerator:
    """Generates scheduled network summary reports.

    Schedule metadata is persisted to a JSON file. Reports are generated
    as dicts with the requested sections, which can be serialized to
    JSON, CSV, or HTML.
    """

    VALID_FREQUENCIES = ("daily", "weekly", "monthly")
    VALID_FORMATS = ("json", "csv", "html")
    VALID_SECTIONS = (
        "traffic_summary",
        "alerts",
        "devices",
        "compliance",
        "risk",
    )

    def __init__(
        self,
        reports_dir: str = "/opt/nettap/data/reports",
        schedules_file: str = "/opt/nettap/data/report_schedules.json",
    ):
        self._reports_dir = reports_dir
        self._schedules_file = schedules_file
        self._schedules: dict[str, ReportSchedule] = {}
        self._load()

    def _load(self) -> None:
        """Load schedules from disk. Starts empty if missing."""
        try:
            if os.path.exists(self._schedules_file):
                with open(self._schedules_file, "r") as f:
                    raw = json.load(f)
                for sched_data in raw:
                    sched = ReportSchedule(**sched_data)
                    self._schedules[sched.id] = sched
                logger.info(
                    "Loaded %d report schedules from %s",
                    len(self._schedules),
                    self._schedules_file,
                )
        except (json.JSONDecodeError, OSError, TypeError) as exc:
            logger.warning(
                "Failed to load report schedules from %s: %s",
                self._schedules_file,
                exc,
            )
            self._schedules = {}

    def _save(self) -> None:
        """Persist all schedules to disk."""
        try:
            parent = os.path.dirname(self._schedules_file)
            if parent:
                os.makedirs(parent, exist_ok=True)
            data = [sched.to_dict() for sched in self._schedules.values()]
            with open(self._schedules_file, "w") as f:
                json.dump(data, f, indent=2)
        except OSError as exc:
            logger.error(
                "Failed to save report schedules to %s: %s",
                self._schedules_file,
                exc,
            )
            raise

    def _compute_next_run(self, frequency: str) -> str:
        """Compute the next run time based on frequency."""
        now = datetime.now(timezone.utc)
        if frequency == "daily":
            next_dt = now + timedelta(days=1)
        elif frequency == "weekly":
            next_dt = now + timedelta(weeks=1)
        elif frequency == "monthly":
            next_dt = now + timedelta(days=30)
        else:
            next_dt = now + timedelta(days=1)
        return next_dt.replace(hour=6, minute=0, second=0, microsecond=0).isoformat()

    def create_schedule(
        self,
        name: str,
        frequency: str,
        format: str,
        sections: list[str],
        recipients: list[str] | None = None,
    ) -> ReportSchedule:
        """Create a new report schedule.

        Raises ValueError for invalid frequency, format, or sections.
        """
        if not name or not name.strip():
            raise ValueError("Schedule name is required")

        if frequency not in self.VALID_FREQUENCIES:
            raise ValueError(
                f"Invalid frequency: {frequency}. "
                f"Must be one of {self.VALID_FREQUENCIES}"
            )

        if format not in self.VALID_FORMATS:
            raise ValueError(
                f"Invalid format: {format}. Must be one of {self.VALID_FORMATS}"
            )

        if not sections:
            raise ValueError("At least one section is required")

        for section in sections:
            if section not in self.VALID_SECTIONS:
                raise ValueError(
                    f"Invalid section: {section}. Must be one of {self.VALID_SECTIONS}"
                )

        now = datetime.now(timezone.utc).isoformat()
        sched = ReportSchedule(
            id=str(uuid.uuid4()),
            name=name.strip(),
            frequency=frequency,
            format=format,
            recipients=recipients or [],
            sections=list(sections),
            enabled=True,
            last_run=None,
            next_run=self._compute_next_run(frequency),
            created_at=now,
        )

        self._schedules[sched.id] = sched
        self._save()
        logger.info("Created report schedule: %s (%s)", sched.name, sched.id)
        return sched

    def list_schedules(self) -> list[ReportSchedule]:
        """List all report schedules."""
        return list(self._schedules.values())

    def get_schedule(self, schedule_id: str) -> ReportSchedule | None:
        """Get a specific schedule by ID."""
        return self._schedules.get(schedule_id)

    def update_schedule(self, schedule_id: str, **kwargs) -> ReportSchedule | None:
        """Update schedule fields.

        Allowed fields: name, frequency, format, sections, recipients, enabled.
        Returns updated schedule or None if not found.
        Raises ValueError for invalid values.
        """
        sched = self._schedules.get(schedule_id)
        if sched is None:
            return None

        allowed_fields = {
            "name",
            "frequency",
            "format",
            "sections",
            "recipients",
            "enabled",
        }

        for key, value in kwargs.items():
            if key not in allowed_fields:
                continue

            if key == "frequency":
                if value not in self.VALID_FREQUENCIES:
                    raise ValueError(
                        f"Invalid frequency: {value}. "
                        f"Must be one of {self.VALID_FREQUENCIES}"
                    )
            elif key == "format":
                if value not in self.VALID_FORMATS:
                    raise ValueError(
                        f"Invalid format: {value}. Must be one of {self.VALID_FORMATS}"
                    )
            elif key == "sections":
                if not value:
                    raise ValueError("At least one section is required")
                for section in value:
                    if section not in self.VALID_SECTIONS:
                        raise ValueError(
                            f"Invalid section: {section}. "
                            f"Must be one of {self.VALID_SECTIONS}"
                        )
            elif key == "name":
                if not value or not str(value).strip():
                    raise ValueError("Schedule name is required")
                value = str(value).strip()

            setattr(sched, key, value)

        # Recompute next_run if frequency changed
        if "frequency" in kwargs:
            sched.next_run = self._compute_next_run(sched.frequency)

        self._save()
        return sched

    def delete_schedule(self, schedule_id: str) -> bool:
        """Delete a report schedule. Returns True if found and deleted."""
        if schedule_id in self._schedules:
            name = self._schedules[schedule_id].name
            del self._schedules[schedule_id]
            self._save()
            logger.info("Deleted report schedule: %s (%s)", name, schedule_id)
            return True
        return False

    def enable_schedule(self, schedule_id: str) -> bool:
        """Enable a report schedule. Returns True if found."""
        sched = self._schedules.get(schedule_id)
        if sched is None:
            return False

        sched.enabled = True
        sched.next_run = self._compute_next_run(sched.frequency)
        self._save()
        return True

    def disable_schedule(self, schedule_id: str) -> bool:
        """Disable a report schedule. Returns True if found."""
        sched = self._schedules.get(schedule_id)
        if sched is None:
            return False

        sched.enabled = False
        self._save()
        return True

    def generate_report(self, schedule_id: str) -> dict:
        """Generate a report for the given schedule.

        Returns the report data as a dict with requested sections.
        Raises ValueError if schedule not found.
        """
        sched = self._schedules.get(schedule_id)
        if sched is None:
            raise ValueError(f"Schedule not found: {schedule_id}")

        now = datetime.now(timezone.utc)
        report: dict = {
            "schedule_id": sched.id,
            "schedule_name": sched.name,
            "generated_at": now.isoformat(),
            "format": sched.format,
            "sections": {},
        }

        section_generators = {
            "traffic_summary": self.generate_section_traffic,
            "alerts": self.generate_section_alerts,
            "devices": self.generate_section_devices,
            "compliance": self.generate_section_compliance,
            "risk": self.generate_section_risk,
        }

        for section_name in sched.sections:
            generator = section_generators.get(section_name)
            if generator:
                report["sections"][section_name] = generator()

        # Update schedule metadata
        sched.last_run = now.isoformat()
        sched.next_run = self._compute_next_run(sched.frequency)
        self._save()

        return report

    def generate_section_traffic(self) -> dict:
        """Generate traffic summary section.

        Returns placeholder data. In production, this would query
        OpenSearch for traffic statistics.
        """
        now = datetime.now(timezone.utc)
        return {
            "title": "Traffic Summary",
            "period": {
                "from": (now - timedelta(hours=24)).isoformat(),
                "to": now.isoformat(),
            },
            "total_connections": 0,
            "total_bytes_in": 0,
            "total_bytes_out": 0,
            "top_protocols": [],
            "top_destinations": [],
            "bandwidth_trend": [],
        }

    def generate_section_alerts(self) -> dict:
        """Generate alerts section.

        Returns placeholder data. In production, this would query
        OpenSearch for Suricata alert statistics.
        """
        return {
            "title": "Alert Summary",
            "total_alerts": 0,
            "by_severity": {
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
            },
            "top_signatures": [],
            "top_source_ips": [],
        }

    def generate_section_devices(self) -> dict:
        """Generate devices section.

        Returns placeholder data. In production, this would query
        OpenSearch for device inventory data.
        """
        return {
            "title": "Device Inventory",
            "total_devices": 0,
            "new_devices": 0,
            "devices": [],
        }

    def generate_section_compliance(self) -> dict:
        """Generate compliance section.

        Returns placeholder data. In production, this would check
        security policy compliance metrics.
        """
        return {
            "title": "Compliance Status",
            "overall_score": 100,
            "checks": [
                {
                    "name": "IDS Rules Updated",
                    "status": "pass",
                    "details": "Rules are current",
                },
                {
                    "name": "Log Retention Policy",
                    "status": "pass",
                    "details": "Within configured limits",
                },
                {
                    "name": "Storage Utilization",
                    "status": "pass",
                    "details": "Below threshold",
                },
            ],
        }

    def generate_section_risk(self) -> dict:
        """Generate risk section.

        Returns placeholder data. In production, this would aggregate
        risk scores from the risk scoring service.
        """
        return {
            "title": "Risk Assessment",
            "overall_risk_level": "low",
            "high_risk_devices": 0,
            "medium_risk_devices": 0,
            "low_risk_devices": 0,
            "top_risk_factors": [],
        }
