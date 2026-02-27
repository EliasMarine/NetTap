"""
Tests for daemon/services/investigation_store.py

All tests use mocks for file I/O. Tests cover CRUD operations, notes
management, alert/device linking, filtering, persistence, validation,
and statistics computation.
"""

import json
import os
import tempfile
import unittest

import sys

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.investigation_store import (
    Investigation,
    InvestigationNote,
    InvestigationStore,
)


class TestInvestigationNoteDataclass(unittest.TestCase):
    """Tests for InvestigationNote dataclass."""

    def test_to_dict(self):
        """to_dict() should return all expected fields."""
        note = InvestigationNote(
            id="note-1",
            content="Test note",
            created_at="2026-02-26T00:00:00+00:00",
            updated_at="2026-02-26T00:00:00+00:00",
        )
        d = note.to_dict()
        self.assertEqual(d["id"], "note-1")
        self.assertEqual(d["content"], "Test note")
        self.assertIn("created_at", d)
        self.assertIn("updated_at", d)


class TestInvestigationDataclass(unittest.TestCase):
    """Tests for Investigation dataclass."""

    def test_to_dict(self):
        """to_dict() should return all expected fields."""
        inv = Investigation(
            id="inv-1",
            title="Test Investigation",
            description="desc",
            status="open",
            severity="high",
            created_at="2026-02-26T00:00:00+00:00",
            updated_at="2026-02-26T00:00:00+00:00",
            alert_ids=["alert-1"],
            device_ips=["192.168.1.1"],
            notes=[],
            tags=["malware"],
        )
        d = inv.to_dict()
        self.assertEqual(d["id"], "inv-1")
        self.assertEqual(d["title"], "Test Investigation")
        self.assertEqual(d["status"], "open")
        self.assertEqual(d["severity"], "high")
        self.assertEqual(d["alert_ids"], ["alert-1"])
        self.assertEqual(d["device_ips"], ["192.168.1.1"])
        self.assertEqual(d["tags"], ["malware"])
        self.assertIsInstance(d["notes"], list)

    def test_to_dict_with_notes(self):
        """to_dict() should serialize notes correctly."""
        note = InvestigationNote("n1", "content", "ts1", "ts1")
        inv = Investigation(
            id="inv-1", title="T", description="", status="open",
            severity="low", created_at="ts", updated_at="ts",
            notes=[note],
        )
        d = inv.to_dict()
        self.assertEqual(len(d["notes"]), 1)
        self.assertEqual(d["notes"][0]["id"], "n1")


class TestInvestigationStoreCreate(unittest.TestCase):
    """Tests for InvestigationStore.create()."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)  # Start with no file
        self.store = InvestigationStore(store_file=self.tmp.name)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_create_basic(self):
        """create() should return an Investigation with correct fields."""
        inv = self.store.create(title="Test Case")
        self.assertIsInstance(inv, Investigation)
        self.assertEqual(inv.title, "Test Case")
        self.assertEqual(inv.status, "open")
        self.assertEqual(inv.severity, "medium")
        self.assertIsNotNone(inv.id)
        self.assertIsNotNone(inv.created_at)

    def test_create_with_all_params(self):
        """create() should accept all optional parameters."""
        inv = self.store.create(
            title="Full Case",
            description="Details here",
            severity="critical",
            alert_ids=["a1", "a2"],
            device_ips=["10.0.0.1"],
            tags=["phishing", "urgent"],
        )
        self.assertEqual(inv.description, "Details here")
        self.assertEqual(inv.severity, "critical")
        self.assertEqual(inv.alert_ids, ["a1", "a2"])
        self.assertEqual(inv.device_ips, ["10.0.0.1"])
        self.assertEqual(inv.tags, ["phishing", "urgent"])

    def test_create_invalid_severity(self):
        """create() should raise ValueError for invalid severity."""
        with self.assertRaises(ValueError):
            self.store.create(title="Bad", severity="extreme")

    def test_create_persists_to_disk(self):
        """create() should save to the store file."""
        self.store.create(title="Persisted")
        self.assertTrue(os.path.exists(self.tmp.name))
        with open(self.tmp.name) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "Persisted")


class TestInvestigationStoreGet(unittest.TestCase):
    """Tests for InvestigationStore.get()."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.store = InvestigationStore(store_file=self.tmp.name)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_get_existing(self):
        """get() should return the investigation by ID."""
        inv = self.store.create(title="Find Me")
        found = self.store.get(inv.id)
        self.assertIsNotNone(found)
        self.assertEqual(found.title, "Find Me")

    def test_get_nonexistent(self):
        """get() should return None for unknown ID."""
        found = self.store.get("no-such-id")
        self.assertIsNone(found)


class TestInvestigationStoreListAll(unittest.TestCase):
    """Tests for InvestigationStore.list_all()."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.store = InvestigationStore(store_file=self.tmp.name)
        self.store.create(title="Case 1", severity="high")
        self.store.create(title="Case 2", severity="low")
        self.store.create(title="Case 3", severity="high")

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_list_all_returns_all(self):
        """list_all() with no filters should return all investigations."""
        results = self.store.list_all()
        self.assertEqual(len(results), 3)

    def test_filter_by_severity(self):
        """list_all(severity='high') should return only high severity."""
        results = self.store.list_all(severity="high")
        self.assertEqual(len(results), 2)
        for inv in results:
            self.assertEqual(inv.severity, "high")

    def test_filter_by_status(self):
        """list_all(status='open') should return only open investigations."""
        results = self.store.list_all(status="open")
        self.assertEqual(len(results), 3)  # All are open by default

    def test_filter_empty_result(self):
        """list_all() with non-matching filter should return empty."""
        results = self.store.list_all(status="closed")
        self.assertEqual(len(results), 0)


class TestInvestigationStoreUpdate(unittest.TestCase):
    """Tests for InvestigationStore.update()."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.store = InvestigationStore(store_file=self.tmp.name)
        self.inv = self.store.create(title="Original Title")

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_update_title(self):
        """update() should change the title."""
        updated = self.store.update(self.inv.id, title="New Title")
        self.assertEqual(updated.title, "New Title")

    def test_update_status(self):
        """update() should change the status."""
        updated = self.store.update(self.inv.id, status="in_progress")
        self.assertEqual(updated.status, "in_progress")

    def test_update_severity(self):
        """update() should change the severity."""
        updated = self.store.update(self.inv.id, severity="critical")
        self.assertEqual(updated.severity, "critical")

    def test_update_invalid_status(self):
        """update() should raise ValueError for invalid status."""
        with self.assertRaises(ValueError):
            self.store.update(self.inv.id, status="invalid_status")

    def test_update_invalid_severity(self):
        """update() should raise ValueError for invalid severity."""
        with self.assertRaises(ValueError):
            self.store.update(self.inv.id, severity="extreme")

    def test_update_nonexistent(self):
        """update() should return None for unknown ID."""
        result = self.store.update("no-such-id", title="Nope")
        self.assertIsNone(result)

    def test_update_updates_timestamp(self):
        """update() should update the updated_at timestamp."""
        old_ts = self.inv.updated_at
        import time
        time.sleep(0.01)  # Ensure time difference
        updated = self.store.update(self.inv.id, title="Changed")
        self.assertNotEqual(updated.updated_at, old_ts)

    def test_update_tags(self):
        """update() should change tags."""
        updated = self.store.update(self.inv.id, tags=["new-tag"])
        self.assertEqual(updated.tags, ["new-tag"])


class TestInvestigationStoreDelete(unittest.TestCase):
    """Tests for InvestigationStore.delete()."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.store = InvestigationStore(store_file=self.tmp.name)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_delete_existing(self):
        """delete() should return True and remove the investigation."""
        inv = self.store.create(title="Delete Me")
        self.assertTrue(self.store.delete(inv.id))
        self.assertIsNone(self.store.get(inv.id))

    def test_delete_nonexistent(self):
        """delete() should return False for unknown ID."""
        self.assertFalse(self.store.delete("no-such-id"))


class TestNotes(unittest.TestCase):
    """Tests for note management."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.store = InvestigationStore(store_file=self.tmp.name)
        self.inv = self.store.create(title="Notes Test")

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_add_note(self):
        """add_note() should add a note to the investigation."""
        note = self.store.add_note(self.inv.id, "First note")
        self.assertIsNotNone(note)
        self.assertEqual(note.content, "First note")
        self.assertIsNotNone(note.id)

        inv = self.store.get(self.inv.id)
        self.assertEqual(len(inv.notes), 1)

    def test_add_note_nonexistent_investigation(self):
        """add_note() should return None for unknown investigation."""
        result = self.store.add_note("no-such-id", "content")
        self.assertIsNone(result)

    def test_update_note(self):
        """update_note() should change the note content."""
        note = self.store.add_note(self.inv.id, "Original")
        updated = self.store.update_note(self.inv.id, note.id, "Updated content")
        self.assertIsNotNone(updated)
        self.assertEqual(updated.content, "Updated content")

    def test_update_note_nonexistent_note(self):
        """update_note() should return None for unknown note ID."""
        result = self.store.update_note(self.inv.id, "bad-note-id", "content")
        self.assertIsNone(result)

    def test_update_note_nonexistent_investigation(self):
        """update_note() should return None for unknown investigation."""
        result = self.store.update_note("bad-inv-id", "bad-note-id", "content")
        self.assertIsNone(result)

    def test_delete_note(self):
        """delete_note() should remove the note."""
        note = self.store.add_note(self.inv.id, "Delete me")
        self.assertTrue(self.store.delete_note(self.inv.id, note.id))
        inv = self.store.get(self.inv.id)
        self.assertEqual(len(inv.notes), 0)

    def test_delete_note_nonexistent(self):
        """delete_note() should return False for unknown note."""
        self.assertFalse(self.store.delete_note(self.inv.id, "bad-id"))

    def test_delete_note_nonexistent_investigation(self):
        """delete_note() should return False for unknown investigation."""
        self.assertFalse(self.store.delete_note("bad-inv", "bad-note"))

    def test_multiple_notes(self):
        """Multiple notes should be stored independently."""
        self.store.add_note(self.inv.id, "Note 1")
        self.store.add_note(self.inv.id, "Note 2")
        self.store.add_note(self.inv.id, "Note 3")
        inv = self.store.get(self.inv.id)
        self.assertEqual(len(inv.notes), 3)


class TestAlertLinking(unittest.TestCase):
    """Tests for alert linking/unlinking."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.store = InvestigationStore(store_file=self.tmp.name)
        self.inv = self.store.create(title="Alert Test")

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_link_alert(self):
        """link_alert() should add alert ID to the investigation."""
        self.assertTrue(self.store.link_alert(self.inv.id, "alert-1"))
        inv = self.store.get(self.inv.id)
        self.assertIn("alert-1", inv.alert_ids)

    def test_link_alert_duplicate(self):
        """link_alert() should not duplicate alert IDs."""
        self.store.link_alert(self.inv.id, "alert-1")
        self.store.link_alert(self.inv.id, "alert-1")
        inv = self.store.get(self.inv.id)
        self.assertEqual(inv.alert_ids.count("alert-1"), 1)

    def test_link_alert_nonexistent(self):
        """link_alert() should return False for unknown investigation."""
        self.assertFalse(self.store.link_alert("bad-id", "alert-1"))

    def test_unlink_alert(self):
        """unlink_alert() should remove the alert ID."""
        self.store.link_alert(self.inv.id, "alert-1")
        self.assertTrue(self.store.unlink_alert(self.inv.id, "alert-1"))
        inv = self.store.get(self.inv.id)
        self.assertNotIn("alert-1", inv.alert_ids)

    def test_unlink_alert_not_linked(self):
        """unlink_alert() should return False if alert not linked."""
        self.assertFalse(self.store.unlink_alert(self.inv.id, "not-linked"))

    def test_unlink_alert_nonexistent_investigation(self):
        """unlink_alert() should return False for unknown investigation."""
        self.assertFalse(self.store.unlink_alert("bad-id", "alert-1"))


class TestDeviceLinking(unittest.TestCase):
    """Tests for device IP linking."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.store = InvestigationStore(store_file=self.tmp.name)
        self.inv = self.store.create(title="Device Test")

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_link_device(self):
        """link_device() should add device IP."""
        self.assertTrue(self.store.link_device(self.inv.id, "192.168.1.1"))
        inv = self.store.get(self.inv.id)
        self.assertIn("192.168.1.1", inv.device_ips)

    def test_link_device_duplicate(self):
        """link_device() should not duplicate IPs."""
        self.store.link_device(self.inv.id, "10.0.0.1")
        self.store.link_device(self.inv.id, "10.0.0.1")
        inv = self.store.get(self.inv.id)
        self.assertEqual(inv.device_ips.count("10.0.0.1"), 1)

    def test_link_device_nonexistent(self):
        """link_device() should return False for unknown investigation."""
        self.assertFalse(self.store.link_device("bad-id", "10.0.0.1"))


class TestPersistence(unittest.TestCase):
    """Tests for file persistence (load/save)."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_save_and_reload(self):
        """Data should survive a store reload."""
        store1 = InvestigationStore(store_file=self.tmp.name)
        inv = store1.create(title="Persist Test", severity="high")
        store1.add_note(inv.id, "A note")
        store1.link_alert(inv.id, "alert-99")

        # Create a new store instance from the same file
        store2 = InvestigationStore(store_file=self.tmp.name)
        loaded = store2.get(inv.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.title, "Persist Test")
        self.assertEqual(loaded.severity, "high")
        self.assertEqual(len(loaded.notes), 1)
        self.assertEqual(loaded.notes[0].content, "A note")
        self.assertIn("alert-99", loaded.alert_ids)

    def test_load_missing_file(self):
        """Loading from a missing file should start empty."""
        store = InvestigationStore(store_file="/tmp/nonexistent_inv_test.json")
        self.assertEqual(len(store.list_all()), 0)

    def test_load_corrupt_file(self):
        """Loading from a corrupt file should start empty."""
        with open(self.tmp.name, "w") as f:
            f.write("not valid json{{{")
        store = InvestigationStore(store_file=self.tmp.name)
        self.assertEqual(len(store.list_all()), 0)

    def test_save_creates_parent_dirs(self):
        """_save() should create parent directories if needed."""
        nested_path = os.path.join(
            tempfile.mkdtemp(), "subdir", "investigations.json"
        )
        store = InvestigationStore(store_file=nested_path)
        store.create(title="Nested")
        self.assertTrue(os.path.exists(nested_path))
        # Cleanup
        os.unlink(nested_path)
        os.rmdir(os.path.dirname(nested_path))


class TestGetStats(unittest.TestCase):
    """Tests for InvestigationStore.get_stats()."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.store = InvestigationStore(store_file=self.tmp.name)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_empty_stats(self):
        """get_stats() with no investigations should return zero counts."""
        stats = self.store.get_stats()
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["by_status"]["open"], 0)

    def test_stats_counts(self):
        """get_stats() should count by status and severity correctly."""
        self.store.create(title="A", severity="high")
        self.store.create(title="B", severity="high")
        self.store.create(title="C", severity="low")
        inv = self.store.create(title="D", severity="critical")
        self.store.update(inv.id, status="resolved")

        stats = self.store.get_stats()
        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["by_severity"]["high"], 2)
        self.assertEqual(stats["by_severity"]["low"], 1)
        self.assertEqual(stats["by_severity"]["critical"], 1)
        self.assertEqual(stats["by_status"]["open"], 3)
        self.assertEqual(stats["by_status"]["resolved"], 1)


class TestValidation(unittest.TestCase):
    """Tests for validation edge cases."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.store = InvestigationStore(store_file=self.tmp.name)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_valid_statuses(self):
        """All valid statuses should be accepted in update()."""
        inv = self.store.create(title="Status Test")
        for status in InvestigationStore.VALID_STATUSES:
            updated = self.store.update(inv.id, status=status)
            self.assertEqual(updated.status, status)

    def test_valid_severities(self):
        """All valid severities should be accepted in create()."""
        for sev in InvestigationStore.VALID_SEVERITIES:
            inv = self.store.create(title=f"Sev {sev}", severity=sev)
            self.assertEqual(inv.severity, sev)

    def test_update_ignores_unknown_fields(self):
        """update() should ignore fields not in the allowed set."""
        inv = self.store.create(title="Ignore Test")
        updated = self.store.update(inv.id, unknown_field="value", title="Changed")
        self.assertEqual(updated.title, "Changed")


if __name__ == "__main__":
    unittest.main()
