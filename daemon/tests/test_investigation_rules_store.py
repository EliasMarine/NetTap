"""NET-308: the investigation store's alert_rules map and its open_during window."""

import json
import logging
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.investigation_store import (
    MAX_ALERT_LINKS,
    InvestigationStore,
    _clean_alert_rules,
)

FROM, TO = "2026-11-05T00:00:00Z", "2026-11-06T00:00:00Z"


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "inv.json")
        self.store = InvestigationStore(self.path)

    def tearDown(self):
        self.dir.cleanup()

    def make(self, title, status, created, updated):
        inv = self.store.create(title=title)
        inv.status, inv.created_at, inv.updated_at = status, created, updated
        return inv


class TestOpenDuring(StoreTestCase):
    def test_open_at_some_point_in_the_window(self):
        early, inside = "2026-11-01T00:00:00+00:00", "2026-11-05T10:00:00+00:00"
        # records made by hand have no closed_at, as before NET-308: updated_at stands in
        cases = [  # (kept, status, created_at, updated_at)
            (True, "open", early, early),  # created before the window, still open
            (True, "in_progress", inside, inside),
            (True, "closed", early, "2026-11-05T09:00:00+00:00"),  # closed inside
            (True, "resolved", "2026-11-04T00:00:00Z", "2026-11-05T00:00:00Z"),
            (True, "open", "2026-11-05T01:00:00", "2026-11-05T01:00:00"),  # naive: UTC
            (False, "open", "2026-11-06T00:00:01+00:00", "2026-11-06T00:00:01+00:00"),
            (False, "closed", early, "2026-11-04T23:59:59+00:00"),  # closed before
            (False, "open", "yesterday", inside),  # unreadable created_at
            (False, "open", 7, inside),  # not a str
            (False, "resolved", early, ""),  # closed, unreadable updated_at
        ]
        made = [
            (kept, self.make(str(i), *rest)) for i, (kept, *rest) in enumerate(cases)
        ]
        found = {inv.id for inv in self.store.open_during(FROM, TO)}
        self.assertEqual(found, {inv.id for kept, inv in made if kept})


class TestClosedAt(StoreTestCase):
    """NET-308 review: updated_at moved with any later edit, so a note added today made an
    investigation closed weeks ago count as open in today's window."""

    EARLY, CLOSED = "2026-11-01T00:00:00+00:00", "2026-11-02T00:00:00+00:00"

    def closed_early(self):
        inv = self.store.create(title="x")
        inv.created_at = self.EARLY
        self.store.update(inv.id, status="closed")
        self.assertIsNotNone(inv.closed_at)
        inv.closed_at = self.CLOSED  # closed before the window
        return inv

    def test_a_note_after_closing_doesnt_reopen_it_in_a_later_window(self):
        inv = self.closed_early()
        self.store.add_note(
            inv.id, "found the cause"
        )  # updated_at is now, after the window
        self.assertGreater(inv.updated_at, TO)
        self.assertEqual(self.store.open_during(FROM, TO), [])
        # it still counts for a window it was open in
        self.assertEqual(self.store.open_during(self.EARLY, self.CLOSED), [inv])

    def test_reopening_clears_it_and_closing_again_sets_it(self):
        inv = self.closed_early()
        self.store.update(
            inv.id, status="resolved"
        )  # done to done: still the first close
        self.assertEqual(inv.closed_at, self.CLOSED)
        self.store.update(inv.id, status="in_progress")
        self.assertIsNone(inv.closed_at)
        self.assertEqual(self.store.open_during(FROM, TO), [inv])
        self.store.update(inv.id, status="closed")
        self.assertGreater(inv.closed_at, TO)

    def test_it_survives_a_restart_and_an_old_record_has_none(self):
        inv = self.closed_early()
        old = self.make("old", "closed", self.EARLY, "2026-11-05T12:00:00+00:00")
        self.store._save()
        loaded = InvestigationStore(self.path)
        self.assertEqual(loaded.get(inv.id).closed_at, self.CLOSED)
        self.assertIsNone(loaded.get(old.id).closed_at)
        # the old record falls back to its updated_at, inside the window
        self.assertEqual([i.id for i in loaded.open_during(FROM, TO)], [old.id])


class TestAlertRules(StoreTestCase):
    def test_a_mixed_map_survives_a_restart(self):
        """R4-1: a resolved name, no name (None) and an empty name all round-trip."""
        rules = {"a1": "ET SCAN Nmap", "a2": None, "a3": ""}
        inv = self.store.create(title="x", alert_ids=list(rules), alert_rules=rules)
        loaded = InvestigationStore(self.path).get(inv.id)
        self.assertEqual(loaded.alert_rules, rules)
        self.assertEqual(loaded.alert_ids, ["a1", "a2", "a3"])

    def test_a_bad_entry_is_dropped_alone(self):
        inv = self.store.create(title="x", alert_ids=["a1", "a2", "a3"])
        with open(self.path) as f:
            raw = json.load(f)
        raw[0]["alert_rules"] = {
            "a1": "ET SCAN Nmap",
            "a2": {"nested": 1},
            "a3": 7,
            "a4": None,
        }
        with open(self.path, "w") as f:
            json.dump(raw, f)
        with self.assertLogs("nettap.investigation_store", logging.WARNING):
            loaded = InvestigationStore(self.path).get(inv.id)
        self.assertEqual(loaded.alert_rules, {"a1": "ET SCAN Nmap", "a4": None})

    def test_a_map_that_isnt_one_loads_empty(self):
        with self.assertLogs("nettap.investigation_store", logging.WARNING):
            self.assertEqual(_clean_alert_rules(["a1"]), {})
        self.assertEqual(_clean_alert_rules(None), {})  # a record from before NET-308
        self.assertEqual(_clean_alert_rules({"a": "b"}), {"a": "b"})

    def test_relinking_fills_the_rule_without_a_second_id(self):
        inv = self.store.create(title="x", alert_ids=["a1"])  # unresolved
        self.assertTrue(self.store.link_alert(inv.id, "a1", "ET SCAN Nmap"))
        self.assertEqual(inv.alert_ids, ["a1"])
        self.assertEqual(inv.alert_rules, {"a1": "ET SCAN Nmap"})

    def test_the_cap_is_checked_as_the_link_is_added(self):
        """NET-308 review: checked by the caller before its lookup, two requests could both pass."""
        inv = self.store.create(
            title="x", alert_ids=[f"a{i}" for i in range(MAX_ALERT_LINKS)]
        )
        with self.assertRaisesRegex(ValueError, "at most 100 alerts"):
            self.store.link_alert(inv.id, "one-more", None)
        self.assertTrue(
            self.store.link_alert(inv.id, "a0", "ET X")
        )  # a relink isn't capped
        self.assertEqual(len(inv.alert_ids), MAX_ALERT_LINKS)

    def test_an_unchanged_relink_leaves_updated_at(self):
        """A closed investigation counts until its last change, so a no-op mustn't extend it."""
        inv = self.store.create(title="x")
        self.store.link_alert(inv.id, "a1", None)
        inv.updated_at = "2026-11-01T00:00:00+00:00"
        self.store.link_alert(inv.id, "a1", None)
        self.assertEqual(inv.updated_at, "2026-11-01T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
