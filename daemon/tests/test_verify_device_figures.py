"""The comparisons behind scripts/remote/verify_device_figures.py (the G11 per-device figures check)."""

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "remote" / "verify_device_figures.py"
_spec = importlib.util.spec_from_file_location("verify_device_figures", _PATH)
vdf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vdf)


def test_bracket_passes_inside_and_flags_outside():
    problems: list = []
    vdf.bracket("in", 10, 10, 12, problems)
    vdf.bracket("grew", 10, 11, 12, problems)
    vdf.bracket("float sum", 9.6, 10, 10.2, problems)
    assert problems == []
    vdf.bracket("too low", 10, 9, 12, problems)
    vdf.bracket("too high", 10, 13, 12, problems)
    assert [p.split(":")[0] for p in problems] == ["too low", "too high"]


def test_check_top_flags_wrong_counts_order_and_missing_entries():
    before = {"a": 50, "b": 30, "c": 20, "d": 5}
    after = {"a": 51, "b": 30, "c": 20, "d": 5}
    ok: list = []
    vdf.check_top("top", [{"k": "a", "n": 51}, {"k": "b", "n": 30}], "k", "n", before, after, ok)
    assert ok == []

    wrong: list = []
    vdf.check_top("top", [{"k": "a", "n": 60}, {"k": "b", "n": 30}], "k", "n", before, after, wrong)
    assert any("top a" in p for p in wrong)

    unsorted: list = []
    vdf.check_top("top", [{"k": "b", "n": 30}, {"k": "a", "n": 50}], "k", "n", before, after, unsorted)
    assert any("not sorted" in p for p in unsorted)

    # b (30) was left out while c (20) is shown: not the real top 2
    missed: list = []
    vdf.check_top("top", [{"k": "a", "n": 50}, {"k": "c", "n": 20}], "k", "n", before, after, missed)
    assert any("left out" in p for p in missed)


def test_same_reply_sum_allows_float_rounding_only():
    problems: list = []
    vdf.same_reply_sum("sum", 100.4, 100, problems)
    assert problems == []
    vdf.same_reply_sum("sum", 102, 100, problems)
    assert len(problems) == 1


_SPLIT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "remote" / "verify_split_invariance.py"
_split_spec = importlib.util.spec_from_file_location("verify_split_invariance", _SPLIT_PATH)
vsi = importlib.util.module_from_spec(_split_spec)
_split_spec.loader.exec_module(vsi)


def test_first_difference_finds_the_changed_figure():
    a = {"talkers": [{"ip": "1.1.1.1", "count": 40046}], "total": 3.0}
    assert vsi.first_difference(a, {"talkers": [{"ip": "1.1.1.1", "count": 40046}], "total": 3.0 + 1e-12}) is None
    assert vsi.first_difference(a, {"talkers": [{"ip": "1.1.1.1", "count": 38678}], "total": 3.0}) == ".talkers[0].count: 40046 vs 38678"
    assert "2 vs 1 items" in vsi.first_difference({"x": [1, 2]}, {"x": [1]})
    assert "only in one" in vsi.first_difference({"x": 1}, {"y": 1})
