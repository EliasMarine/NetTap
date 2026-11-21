"""NET-344: the backup encoding and fit() (plan §2.1, §2.3, §5 "Encoder" and "fit").

A download must restore, so fit() keeps the body under RESTORE_LIMIT_BYTES by leaving out the
oldest alert acknowledgements, never an owner setting. The combinatorial cases run against a small
patched limit and are checked against a brute-force search; the cutoff, the 413s and the memory
bound run at the real 16 MiB.
"""

import copy
import json
import re
import time
import tracemalloc

import pytest

import services.backup_fit as bf
from services.backup_checks import _LABELS
from services.config_backup import (
    LEFT_OUT,
    RESTORE_LIMIT_BYTES,
    BackupRefused,
    BackupTooLarge,
    encode,
    fit,
    section_errors,
)

ACKS = "alert_acknowledgements"
META = {"nettap_version": "0.4.0", "schema_version": 2, "exported_at": "2026-11-20"}


def _config(acks: dict | None = None, **sections) -> dict:
    return {
        "metadata": dict(META),
        "sections": {**sections, ACKS: {} if acks is None else acks},
    }


def _acks(n: int, by: str = "admin") -> dict:
    """n acknowledgements, a1 the oldest; times in UTC, one second apart."""
    return {
        f"a{i}": {
            "acknowledged_at": f"2026-11-20T00:{i // 60:02d}:{i % 60:02d}+00:00",
            "acknowledged_by": by,
        }
        for i in range(1, n + 1)
    }


def _padded(config: dict, target: int) -> dict:
    """config with an ASCII rule note sized so the whole document encodes to `target` bytes."""
    probe = copy.deepcopy(config)
    probe["sections"]["notification_rules"] = {"r": {"note": ""}}
    pad = target - len(encode(probe))
    assert pad >= 0
    probe["sections"]["notification_rules"]["r"]["note"] = "x" * pad
    assert len(encode(probe)) == target
    return probe


def _candidate(config: dict, order: list[str], kept: int) -> dict:
    """What fit() should answer when it keeps the `kept` newest of `order`."""
    left = len(order) - kept
    meta = {**config["metadata"], **({LEFT_OUT: left} if left else {})}
    acks = config["sections"][ACKS]
    sections = {**config["sections"], ACKS: {k: acks[k] for k in order[:kept]}}
    return {**config, "metadata": meta, "sections": sections}


@pytest.fixture
def small_limit(monkeypatch):
    def set_limit(limit: int) -> int:
        monkeypatch.setattr(bf, "RESTORE_LIMIT_BYTES", limit)
        return limit

    return set_limit


# ---------------------------------------------------------------------------- encoder


def test_a_lone_surrogate_is_escaped_and_emoji_stay_raw_utf8():
    body = encode({"a": "x\ud800y", "b": "😀 café"})
    assert body == b'{"a":"x\\ud800y","b":"' + "😀 café".encode() + b'"}'
    body.decode("utf-8")  # strict: no surrogate left
    assert json.loads(body) == {"a": "x\ud800y", "b": "😀 café"}


def test_nan_is_refused_with_the_section_named():
    with pytest.raises(ValueError):
        encode({"x": float("nan")})
    config = _config(bandwidth_cap={"monthly_cap_bytes": float("inf")})
    with pytest.raises(BackupRefused) as refused:
        fit(config)
    assert refused.value.code == "invalid_section"
    assert str(refused.value).startswith(
        "No backup was made: the bandwidth cap on this"
    )


def test_each_sections_streamed_size_is_its_share_of_the_body():
    config = _config(
        _acks(3, by="管理者 😀"),
        device_aliases={"AA:BB:CC:DD:EE:01": "Kid\ud83d's 📱"},
        excluded_ips=["192.0.2.1"],
        notification_rules={"r": {"note": "x\udfff"}},
    )
    body, left = fit(config)
    assert left == 0 and bytes(body) == encode(config)
    for name, value in config["sections"].items():
        share = encode(value)
        assert bf._size(value) == len(share)  # streamed == one-shot
        assert encode(name) + b":" + share in body


# ---------------------------------------------------------------------------- the cutoff


def test_under_the_limit_nothing_is_trimmed():
    config = _config(_acks(5))
    body, left = fit(config)
    assert (bytes(body), left) == (encode(config), 0)
    assert LEFT_OUT not in json.loads(body)["metadata"]


def test_a_body_of_limit_minus_one_is_kept_whole():
    config = _padded(_config(_acks(5)), RESTORE_LIMIT_BYTES - 1)
    body, left = fit(config)
    assert left == 0 and len(body) == RESTORE_LIMIT_BYTES - 1
    assert bytes(body) == encode(config)


def test_a_body_of_exactly_the_limit_leaves_out_the_oldest_acknowledgement():
    config = _padded(_config(_acks(5)), RESTORE_LIMIT_BYTES)
    body, left = fit(config)
    doc = json.loads(body)
    assert left == 1 and doc["metadata"][LEFT_OUT] == 1
    assert sorted(doc["sections"][ACKS]) == ["a2", "a3", "a4", "a5"]
    assert len(body) < RESTORE_LIMIT_BYTES
    # maximal: keeping the one left out reaches the cutoff
    order = ["a5", "a4", "a3", "a2", "a1"]
    assert len(encode(_candidate(config, order, 5))) >= RESTORE_LIMIT_BYTES


def test_the_input_is_never_changed():
    config = _padded(
        _config(
            _acks(5), alert_suppressions={"global": [{"signature_id": 1, "reason": 5}]}
        ),
        RESTORE_LIMIT_BYTES,
    )
    before = copy.deepcopy(config)
    fit(config)
    assert config == before


# ---------------------------------------------------------------------------- the prefix


@pytest.mark.parametrize("n,boundary", [(12, 10), (105, 100)])
def test_the_count_digits_and_maximality_match_brute_force(small_limit, n, boundary):
    """Where the left-out count goes 9→10 and 99→100, every limit keeps exactly the prefix a
    brute-force search keeps, byte for byte: the largest that fits (so one more doesn't)."""
    config = _config(_acks(n))
    order = [f"a{i}" for i in range(n, 0, -1)]
    # every candidate's real size, by encoding it (sizes[k]: the k newest kept)
    sizes = [len(encode(_candidate(config, order, k))) for k in range(n + 1)]
    assert sizes == sorted(sizes)
    seen = set()
    for limit in range(sizes[n - boundary - 1] - 2, sizes[n - boundary + 2] + 2):
        small_limit(limit)
        kept = max(k for k in range(n + 1) if sizes[k] < limit)
        body, left = fit(config)
        assert left == n - kept, limit
        assert bytes(body) == encode(_candidate(config, order, kept))
        seen.add(left)
    assert {boundary - 1, boundary, boundary + 1} <= seen


def test_newest_first_by_instant_with_naive_times_oldest_and_ties_by_id(small_limit):
    """String order isn't instant order with mixed offsets; the expected order is by hand."""
    acks = {
        "a": {"acknowledged_at": "2026-11-20T10:00:00+01:00"},  # 09:00Z
        "b": {"acknowledged_at": "2026-11-20T09:30:00Z"},  # 09:30Z
        "c": {"acknowledged_at": "2026-11-20T12:00:00"},  # no zone: oldest
        "d": {"acknowledged_at": "2026-11-20T08:00:00-02:00"},  # 10:00Z, the newest
        "e": {"acknowledged_at": "2026-11-20T09:30:00+00:00"},  # ties b: after b by ID
        "f": {},  # no time: oldest
        "g": {"acknowledged_at": "soon"},  # unparsable: oldest
    }
    expected = ["d", "b", "e", "a", "c", "f", "g"]
    config = _config(acks)
    full = len(encode(config))
    seen = {}
    for limit in range(full - 500, full + 2):
        small_limit(limit)
        try:
            body, left = fit(config)
        except BackupTooLarge:
            continue
        seen[left] = set(json.loads(body)["sections"][ACKS])
    assert set(range(7)) <= set(seen)
    for left, kept in seen.items():
        assert kept == set(expected[: len(expected) - left]), left


def test_a_lone_surrogate_in_a_kept_and_a_dropped_entry_matches_the_total(small_limit):
    acks = _acks(6, by="admin 😀")
    acks["a1"]["acknowledged_by"] = "old\udc00"  # dropped
    acks["a6"]["acknowledged_by"] = "new\ud800"  # kept
    config = _config(acks, device_aliases={"AA:BB:CC:DD:EE:01": "Telly 📺"})
    small_limit(len(encode(config)) - 40)
    body, left = fit(config)  # fit raises if its total and the body disagree
    doc = json.loads(body.decode("utf-8"))
    assert left >= 1 and "a1" not in doc["sections"][ACKS]
    assert doc["sections"][ACKS]["a6"]["acknowledged_by"] == "new\ud800"


# ---------------------------------------------------------------------------- refusals


def many_rules() -> dict:
    return {f"r{i}": {"note": "n" * 1000} for i in range(17_000)}


def many_suppressions() -> dict:
    """Short entries, as the Alerts page writes them (one per signature, no reason)."""
    entry = {
        "reason": "",
        "suppressed_at": "2026-11-20T00:00:00+00:00",
        "expires_at": "2026-12-20T00:00:00+00:00",
    }
    return {"global": [{"signature_id": i, **entry} for i in range(140_000)]}


def long_reasons() -> dict:
    """A few very long reasons, which only a hand-written request or file can store."""
    return {
        "global": [{"signature_id": i, "reason": "r" * 6_000_000} for i in range(3)]
    }


def many_ips() -> list:
    return [f"10.{i >> 16}.{(i >> 8) & 255}.{i & 255}" for i in range(1_200_000)]


@pytest.mark.parametrize(
    "section,make,advice",
    [
        ("notification_rules", many_rules, "Settings › Notifications"),
        ("alert_suppressions", many_suppressions, "NET-346"),
        ("alert_suppressions", long_reasons, "NET-346"),
        # unreachable once capped at 10,000 (a stored list over the cap is a 422), but measured
        ("excluded_ips", many_ips, "daemon log"),
    ],
)
def test_owner_settings_over_the_limit_are_a_413_naming_the_largest(
    section, make, advice
):
    value = make()
    config = _config(_acks(50), **{section: value})
    with pytest.raises(BackupTooLarge) as refused:
        fit(config)
    text = str(refused.value)
    assert float(re.search(r"would be ([\d.]+) MB", text).group(1)) >= 16.8
    # decimal MB (NET-166), the largest part named with its own size
    largest = f"{len(encode(value)) / 1_000_000:.1f} MB"
    assert f"The largest part is {_LABELS[section]} ({largest})." in text
    assert (
        text.startswith("This backup would be ")
        and "over the 16 MB restore limit" in text
    )
    assert _LABELS[section] in text and advice in text


def test_sizes_read_in_decimal_mb_and_the_smallest_refusal_is_16_8():
    assert bf._mb(RESTORE_LIMIT_BYTES) == "16.8 MB"
    assert bf._mb(9_050_000) == "9.1 MB"


# ---------------------------------------------------------------------------- normalisation


def test_reasons_that_arent_text_become_text_only_in_the_copy():
    supp = {
        "global": [{"signature_id": 1, "reason": 5}, {"signature_id": 2}],
        "per_device": {"192.0.2.5": [{"signature_id": 3, "reason": None}]},
        "false_positives": [{"signature_id": 4, "reason": "kept"}],
    }
    body, _ = fit(_config(alert_suppressions=supp))
    out = json.loads(body)["sections"]["alert_suppressions"]
    assert out["global"] == [{"signature_id": 1, "reason": "5"}, {"signature_id": 2}]
    assert out["per_device"]["192.0.2.5"] == [{"signature_id": 3, "reason": ""}]
    assert out["false_positives"] == supp["false_positives"]
    assert supp["global"][0]["reason"] == 5  # the input is untouched
    assert section_errors(json.loads(body)["sections"]) == {}


def test_a_stale_left_out_count_is_replaced():
    config = _config(_acks(2))
    config["metadata"][LEFT_OUT] = 7
    body, left = fit(config)
    assert left == 0 and LEFT_OUT not in json.loads(body)["metadata"]


# ---------------------------------------------------------------------------- memory


def ack_file_32mib() -> dict:
    """About 32 MiB of acknowledgements in mixed ASCII and emoji text."""
    acks, size, i = {}, 0, 0
    while size < 32 * 1024 * 1024:
        i += 1
        entry = {
            "acknowledged_at": f"2026-{1 + i % 12:02d}-{1 + i % 28:02d}T{i % 24:02d}:"
            f"{i % 60:02d}:{(i // 60) % 60:02d}.{i % 1_000_000:06d}+00:00",
            "acknowledged_by": "admin" if i % 2 else "管理者 😀",
        }
        acks[f"{i:020d}"] = entry
        size += 26 + len(encode(entry))
    return acks


def test_fits_workspace_stays_under_twice_the_cutoff():
    config = _config(ack_file_32mib())
    tracemalloc.start()
    try:
        before, _ = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        start = time.monotonic()
        body, left = fit(config)
        seconds = time.monotonic() - start
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    workspace = peak - before
    print(f"fit: {workspace / 2**20:.1f} MiB extra workspace, {seconds:.1f} s traced")
    assert left > 0 and len(body) < RESTORE_LIMIT_BYTES
    assert workspace < 2 * RESTORE_LIMIT_BYTES
