"""The device check deploy-live-audit-fixes.sh runs for PCAP search (NET-347)."""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "remote" / "verify_pcap_search.py"
)
_spec = importlib.util.spec_from_file_location("verify_pcap_search", _PATH)
vp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vp)

_OLD = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
_FILES = [
    {"file": "/opt/nettap/pcap/b.pcap", "relative_path": "b.pcap", "modified": _OLD},
    {"file": "/opt/nettap/pcap/a.pcap", "relative_path": "a.pcap", "modified": _OLD},
]


def _search(**over) -> dict:
    return {
        "complete": True,
        "files_checked": 2,
        "files_full": 2,
        "files_total": 2,
        "failed": 0,
        "timed_out": 0,
        "error": None,
        "results": [{"file": "/opt/nettap/pcap/b.pcap", "matching_packets": 5}],
        **over,
    }


@pytest.fixture
def device(monkeypatch):
    state = {"search": _search(), "counts": {"b.pcap": 5, "a.pcap": 0}}

    def call(method, path, body=None):
        if path.startswith("/api/pcap/files"):
            return 200, {"files": _FILES}
        if path.startswith("/api/pcap/search"):
            return 200, state["search"]
        raise AssertionError(path)

    monkeypatch.setattr(vp, "call", call)
    monkeypatch.setattr(vp, "reference_count", lambda rel, flt: state["counts"][rel])
    monkeypatch.setattr(vp, "FAILED", [])
    return state


def test_passes_when_the_search_matches_tsharks_counts(device):
    vp.known_answer()
    assert vp.FAILED == []


@pytest.mark.parametrize(
    "over, failed",
    [
        (
            {"results": [{"file": "/opt/nettap/pcap/b.pcap", "matching_packets": 7}]},
            "Counts match TShark's own",
        ),
        ({"files_full": 1, "failed": 1}, "Every file read in full"),
        ({"complete": False}, "Search finished"),
    ],
)
def test_fails_on_a_wrong_count_an_unread_file_or_an_unfinished_search(
    device, monkeypatch, over, failed
):
    monkeypatch.setattr(vp, "SEARCH_DEADLINE_S", 0)
    device["search"] = _search(**over)
    vp.known_answer()
    assert failed in vp.FAILED


def test_a_window_with_an_unreadable_file_is_not_used(device):
    device["counts"] = {"b.pcap": None, "a.pcap": 3}
    vp.known_answer()
    assert vp.FAILED == ["A usable window"]
