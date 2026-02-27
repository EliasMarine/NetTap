"""
Investigation Bookmarks & Notes Store for NetTap.

Lightweight case management that lets users bookmark alerts, create
investigation notes, and track findings. All data is persisted to a
local JSON file so it survives daemon restarts without requiring
an external database.
"""

import json
import logging
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

logger = logging.getLogger("nettap.investigation_store")


@dataclass
class InvestigationNote:
    """A single note within an investigation."""

    id: str
    content: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Investigation:
    """A bookmarked investigation with notes and linked alerts."""

    id: str
    title: str
    description: str
    status: str  # 'open', 'in_progress', 'resolved', 'closed'
    severity: str  # 'low', 'medium', 'high', 'critical'
    created_at: str
    updated_at: str
    alert_ids: list[str] = field(default_factory=list)
    device_ips: list[str] = field(default_factory=list)
    notes: list[InvestigationNote] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["notes"] = [
            n.to_dict() if isinstance(n, InvestigationNote) else n
            for n in self.notes
        ]
        return d


class InvestigationStore:
    """File-backed store for investigation bookmarks and notes.

    All mutations are immediately persisted to disk. The store file
    is created (including parent directories) on first write if it
    does not already exist.
    """

    VALID_STATUSES = ("open", "in_progress", "resolved", "closed")
    VALID_SEVERITIES = ("low", "medium", "high", "critical")

    def __init__(self, store_file: str = "/opt/nettap/data/investigations.json"):
        self._store_file = store_file
        self._investigations: dict[str, Investigation] = {}
        self._load()

    def _load(self) -> None:
        """Load investigations from disk. Silently starts empty if missing."""
        try:
            if os.path.exists(self._store_file):
                with open(self._store_file, "r") as f:
                    raw = json.load(f)
                for inv_data in raw:
                    notes = [
                        InvestigationNote(**n) for n in inv_data.get("notes", [])
                    ]
                    inv = Investigation(
                        id=inv_data["id"],
                        title=inv_data["title"],
                        description=inv_data.get("description", ""),
                        status=inv_data.get("status", "open"),
                        severity=inv_data.get("severity", "medium"),
                        created_at=inv_data.get("created_at", ""),
                        updated_at=inv_data.get("updated_at", ""),
                        alert_ids=inv_data.get("alert_ids", []),
                        device_ips=inv_data.get("device_ips", []),
                        notes=notes,
                        tags=inv_data.get("tags", []),
                    )
                    self._investigations[inv.id] = inv
                logger.info(
                    "Loaded %d investigations from %s",
                    len(self._investigations),
                    self._store_file,
                )
        except (json.JSONDecodeError, OSError, KeyError) as exc:
            logger.warning(
                "Failed to load investigations from %s: %s", self._store_file, exc
            )
            self._investigations = {}

    def _save(self) -> None:
        """Persist all investigations to disk."""
        try:
            os.makedirs(os.path.dirname(self._store_file), exist_ok=True)
            data = [inv.to_dict() for inv in self._investigations.values()]
            with open(self._store_file, "w") as f:
                json.dump(data, f, indent=2)
        except OSError as exc:
            logger.error("Failed to save investigations to %s: %s", self._store_file, exc)
            raise

    def create(
        self,
        title: str,
        description: str = "",
        severity: str = "medium",
        alert_ids: list[str] | None = None,
        device_ips: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> Investigation:
        """Create a new investigation.

        Raises ValueError if severity is not in VALID_SEVERITIES.
        """
        if severity not in self.VALID_SEVERITIES:
            raise ValueError(
                f"Invalid severity: {severity}. Must be one of {self.VALID_SEVERITIES}"
            )

        now = datetime.now(timezone.utc).isoformat()
        inv = Investigation(
            id=str(uuid.uuid4()),
            title=title,
            description=description,
            status="open",
            severity=severity,
            created_at=now,
            updated_at=now,
            alert_ids=alert_ids or [],
            device_ips=device_ips or [],
            notes=[],
            tags=tags or [],
        )
        self._investigations[inv.id] = inv
        self._save()
        return inv

    def get(self, investigation_id: str) -> Investigation | None:
        """Get investigation by ID. Returns None if not found."""
        return self._investigations.get(investigation_id)

    def list_all(
        self,
        status: str | None = None,
        severity: str | None = None,
    ) -> list[Investigation]:
        """List investigations with optional status and severity filters.

        Returns all investigations (newest first by updated_at) that match
        the given filters. If no filters are provided, returns all.
        """
        results = list(self._investigations.values())

        if status is not None:
            results = [inv for inv in results if inv.status == status]
        if severity is not None:
            results = [inv for inv in results if inv.severity == severity]

        # Sort newest first
        results.sort(key=lambda i: i.updated_at, reverse=True)
        return results

    def update(self, investigation_id: str, **kwargs) -> Investigation | None:
        """Update investigation fields (title, description, status, severity, tags).

        Returns the updated Investigation, or None if not found.
        Raises ValueError for invalid status or severity values.
        """
        inv = self._investigations.get(investigation_id)
        if inv is None:
            return None

        allowed_fields = {"title", "description", "status", "severity", "tags"}
        for key, value in kwargs.items():
            if key not in allowed_fields:
                continue
            if key == "status" and value not in self.VALID_STATUSES:
                raise ValueError(
                    f"Invalid status: {value}. Must be one of {self.VALID_STATUSES}"
                )
            if key == "severity" and value not in self.VALID_SEVERITIES:
                raise ValueError(
                    f"Invalid severity: {value}. Must be one of {self.VALID_SEVERITIES}"
                )
            setattr(inv, key, value)

        inv.updated_at = datetime.now(timezone.utc).isoformat()
        self._save()
        return inv

    def delete(self, investigation_id: str) -> bool:
        """Delete an investigation. Returns True if found and deleted."""
        if investigation_id in self._investigations:
            del self._investigations[investigation_id]
            self._save()
            return True
        return False

    def add_note(self, investigation_id: str, content: str) -> InvestigationNote | None:
        """Add a note to an investigation. Returns None if investigation not found."""
        inv = self._investigations.get(investigation_id)
        if inv is None:
            return None

        now = datetime.now(timezone.utc).isoformat()
        note = InvestigationNote(
            id=str(uuid.uuid4()),
            content=content,
            created_at=now,
            updated_at=now,
        )
        inv.notes.append(note)
        inv.updated_at = now
        self._save()
        return note

    def update_note(
        self, investigation_id: str, note_id: str, content: str
    ) -> InvestigationNote | None:
        """Update an existing note. Returns None if not found."""
        inv = self._investigations.get(investigation_id)
        if inv is None:
            return None

        for note in inv.notes:
            if note.id == note_id:
                note.content = content
                note.updated_at = datetime.now(timezone.utc).isoformat()
                inv.updated_at = note.updated_at
                self._save()
                return note
        return None

    def delete_note(self, investigation_id: str, note_id: str) -> bool:
        """Delete a note from an investigation. Returns True if found."""
        inv = self._investigations.get(investigation_id)
        if inv is None:
            return False

        original_len = len(inv.notes)
        inv.notes = [n for n in inv.notes if n.id != note_id]
        if len(inv.notes) < original_len:
            inv.updated_at = datetime.now(timezone.utc).isoformat()
            self._save()
            return True
        return False

    def link_alert(self, investigation_id: str, alert_id: str) -> bool:
        """Link an alert to an investigation. Returns True on success."""
        inv = self._investigations.get(investigation_id)
        if inv is None:
            return False

        if alert_id not in inv.alert_ids:
            inv.alert_ids.append(alert_id)
            inv.updated_at = datetime.now(timezone.utc).isoformat()
            self._save()
        return True

    def unlink_alert(self, investigation_id: str, alert_id: str) -> bool:
        """Unlink an alert from an investigation. Returns True if found."""
        inv = self._investigations.get(investigation_id)
        if inv is None:
            return False

        if alert_id in inv.alert_ids:
            inv.alert_ids.remove(alert_id)
            inv.updated_at = datetime.now(timezone.utc).isoformat()
            self._save()
            return True
        return False

    def link_device(self, investigation_id: str, device_ip: str) -> bool:
        """Link a device IP to an investigation. Returns True on success."""
        inv = self._investigations.get(investigation_id)
        if inv is None:
            return False

        if device_ip not in inv.device_ips:
            inv.device_ips.append(device_ip)
            inv.updated_at = datetime.now(timezone.utc).isoformat()
            self._save()
        return True

    def get_stats(self) -> dict:
        """Return investigation statistics: counts by status and severity."""
        status_counts = {s: 0 for s in self.VALID_STATUSES}
        severity_counts = {s: 0 for s in self.VALID_SEVERITIES}

        for inv in self._investigations.values():
            if inv.status in status_counts:
                status_counts[inv.status] += 1
            if inv.severity in severity_counts:
                severity_counts[inv.severity] += 1

        return {
            "total": len(self._investigations),
            "by_status": status_counts,
            "by_severity": severity_counts,
        }
