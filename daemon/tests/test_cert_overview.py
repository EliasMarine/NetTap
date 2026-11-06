"""
Tests for daemon/services/cert_overview.py (NET-154).

RawOpenSearch holds raw ssl and x509 documents and answers the three calls the pass makes:
create_pit / delete_pit, a session page (sorted by _shard_doc, paged with search_after) and
the x509 details aggregation. Every count the page shows must match the raw documents.
"""

import json
import os
import sys

import pytest
from opensearchpy import OpenSearchException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import cert_overview
from services.cert_overview import (
    Budget,
    CertOverview,
    CertQueryFailed,
    CertTooBig,
    CertTooSlow,
    encode_bounded,
    paginate,
    x509_fields,
)
from tests.fake_cert_opensearch import FROM, NOW, TO, RawOpenSearch, ssl, x509


def overview(client, **kw):
    return CertOverview(client).overview(FROM, TO, now=NOW, **kw)


@pytest.fixture(autouse=True)
def small_pages(monkeypatch):
    """Two sessions per page and one fingerprint per details chunk, so paging is exercised."""
    monkeypatch.setattr(cert_overview, "PAGE_SIZE", 2)
    monkeypatch.setattr(cert_overview, "DETAIL_CHUNK", 1)


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


def test_every_session_is_counted_once_across_pages_and_credited_to_its_leaf():
    sessions = [ssl(["LEAF", "INTERMEDIATE", "ROOT"]) for _ in range(5)] + [
        ssl(["OTHER", "INTERMEDIATE"], sni="b.com")
    ]
    out = overview(RawOpenSearch(sessions, [x509("LEAF"), x509("OTHER")]))
    by_fp = {c["fingerprint"]: c["sessions"] for c in out["certificates"]}
    assert by_fp == {
        "LEAF": 5,
        "OTHER": 1,
    }  # intermediates and roots are never certificates
    assert (
        out["summary"]["sessions"] == 6
        and out["summary"]["sessions_without_details"] == 0
    )


def test_a_certificate_used_in_the_window_but_logged_by_x509_days_earlier_still_has_details():
    out = overview(
        RawOpenSearch([ssl(["A"])], [x509("A", t="2026-10-01T00:00:00.000Z")])
    )
    assert out["certificates"][0]["details_available"] is True
    assert out["certificates"][0]["issuer_org"] == "Let's Encrypt"


def test_details_come_from_the_newest_x509_record_and_missing_ones_are_counted():
    certs = [
        x509("A", t="2026-11-01T00:00:00.000Z", org="Old CA"),
        x509("A", t="2026-11-04T00:00:00.000Z"),
    ]
    out = overview(RawOpenSearch([ssl(["A"]), ssl(["B"], sni="b.com")], certs))
    rows = {c["fingerprint"]: c for c in out["certificates"]}
    assert rows["A"]["issuer_org"] == "Let's Encrypt"
    assert rows["B"]["details_available"] is False
    assert out["summary"]["certificates_without_details"] == 1


def test_excluded_ips_are_left_out_of_every_count():
    sessions = [ssl(["A"], client="192.168.1.10"), ssl(["A"], client="192.168.1.99")]
    out = overview(RawOpenSearch(sessions, [x509("A")]), excluded_ips=["192.168.1.99"])
    assert out["summary"]["sessions"] == 1 and out["certificates"][0]["clients"] == [
        "192.168.1.10"
    ]


def test_the_scan_reads_the_chain_in_order_and_the_rest_from_doc_values():
    client = RawOpenSearch([ssl(["A"])], [x509("A")])
    overview(client)
    scan = client.bodies[0]
    assert scan["_source"] == ["zeek.ssl.cert_chain_fps"]
    assert scan["sort"] == [{"_shard_doc": "asc"}] and scan["track_total_hits"] is False
    assert {"exists": {"field": "zeek.ssl.cert_chain_fps"}} in scan["query"]["bool"][
        "filter"
    ]


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def test_the_snapshot_refuses_partial_shards_and_is_closed_after_use():
    client = RawOpenSearch([ssl(["A"])], [x509("A")])
    overview(client)
    assert client.pit_params["allow_partial_pit_creation"] == "false"
    assert client.open_pits == set() and client.closed == ["pit-0"]


def test_the_snapshot_is_closed_when_the_pass_fails():
    def fail(kind, reply):
        if kind == "sessions":
            raise OpenSearchException("boom")
        return reply

    client = RawOpenSearch([ssl(["A"])], [], tamper=fail)
    with pytest.raises(CertQueryFailed):
        overview(client)
    assert client.open_pits == set()


def test_a_snapshot_passed_in_is_left_open_for_its_owner():
    client = RawOpenSearch([ssl(["A"])], [x509("A")])
    client.open_pits.add("mine")
    CertOverview(client).overview(FROM, TO, pit_id="mine", now=NOW)
    assert client.open_pits == {"mine"} and client.closed == []


# ---------------------------------------------------------------------------
# Incomplete replies are failures, never smaller counts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind, change",
    [
        ("pit", lambda r: {**r, "_shards": {"failed": 1}}),
        ("pit", lambda r: {"_shards": {"failed": 0}}),
        ("sessions", lambda r: {**r, "timed_out": True}),
        ("sessions", lambda r: {**r, "_shards": {"failed": 2}}),
        ("sessions", lambda r: {**r, "hits": {}}),
        (
            "sessions",
            lambda r: {
                **r,
                "hits": {
                    "hits": [
                        {k: v for k, v in h.items() if k != "sort"}
                        for h in r["hits"]["hits"]
                    ]
                },
            },
        ),
        ("sessions", lambda r: None),
        ("details", lambda r: {**r, "aggregations": {}}),
        (
            "details",
            lambda r: {
                **r,
                "aggregations": {"fps": {"sum_other_doc_count": 3, "buckets": []}},
            },
        ),
        ("details", lambda r: {**r, "timed_out": True}),
    ],
)
def test_incomplete_or_malformed_replies_fail_the_pass(kind, change):
    def tamper(k, reply):
        return change(reply) if k == kind else reply

    with pytest.raises(CertQueryFailed):
        overview(RawOpenSearch([ssl(["A"])], [x509("A")], tamper=tamper))


# ---------------------------------------------------------------------------
# Budget and size
# ---------------------------------------------------------------------------


def test_every_search_gets_the_remaining_budget_as_its_timeout():
    clock = iter(range(0, 1000, 5))  # each read of the clock moves 5 s on
    budget = Budget(50, clock=lambda: next(clock))
    client = RawOpenSearch([ssl(["A"])], [x509("A")])
    overview(client, budget=budget)
    assert (
        client.timeouts == sorted(client.timeouts, reverse=True)
        and client.timeouts[0] < 50
    )
    assert all(b["timeout"].endswith("ms") for b in client.bodies)


def test_a_pass_past_its_budget_fails_as_too_slow():
    clock = iter(range(0, 1000, 20))
    with pytest.raises(CertTooSlow):
        overview(
            RawOpenSearch([ssl(["A"])] * 6, [x509("A")]),
            budget=Budget(50, clock=lambda: next(clock)),
        )


def test_too_many_distinct_uses_fail_instead_of_growing_without_bound(monkeypatch):
    monkeypatch.setattr(cert_overview, "MAX_KEYS", 3)
    sessions = [ssl(["A"], client=f"192.168.1.{i}") for i in range(4)]
    with pytest.raises(CertTooBig):
        overview(RawOpenSearch(sessions, [x509("A")]))


def test_encoding_stops_before_a_reply_too_large_to_send():
    with pytest.raises(CertTooBig):
        encode_bounded({"rows": ["x" * 100] * 100}, Budget(), max_bytes=1_000)
    assert json.loads(encode_bounded({"rows": [1, 2]}, Budget())) == {"rows": [1, 2]}


def test_encoding_past_the_deadline_fails_as_too_slow():
    clock = iter([0, 100, 100, 100])
    with pytest.raises(CertTooSlow):
        encode_bounded({"rows": [1]}, Budget(50, clock=lambda: next(clock)))


# ---------------------------------------------------------------------------
# Reply shaping
# ---------------------------------------------------------------------------


def test_lists_are_capped_with_totals_and_details_cover_every_referenced_certificate():
    sessions = [ssl([f"C{i}"], sni=f"s{i}.com") for i in range(4)]
    out = paginate(
        overview(RawOpenSearch(sessions, [x509(f"C{i}") for i in range(4)])), cap=2
    )
    assert (out["sites_total"], len(out["sites"])) == (4, 2)
    assert out["sites_truncated"] and not out["findings_truncated"]
    referenced = {fp for s in out["sites"] for fp in s["certificates"]}
    assert referenced == set(out["details"])


def test_certificates_are_sent_once_as_details_covering_findings_past_the_cap():
    bad = "unable to get local issuer certificate"
    sessions = [
        ssl(["NEW"], sni="new.com", t="2026-11-05T11:00:00.000Z"),
        ssl(["OLD"], sni="old.com", status=bad),
    ]
    out = paginate(overview(RawOpenSearch(sessions, [x509("NEW"), x509("OLD")])), cap=1)
    assert "certificates" not in out and "certificates_total" not in out
    assert [s["id"] for s in out["sites"]] == ["new.com"]
    assert out["findings"][0]["fingerprint"] == "OLD"
    assert set(out["details"]) == {"NEW", "OLD"}


def test_x509_fields_flag_self_issued_certificates():
    same = x509_fields(
        {"certificate_subject_full": "CN=nas", "certificate_issuer_full": "CN=nas"}
    )
    other = x509_fields(
        {"certificate_subject_full": "CN=nas", "certificate_issuer_full": "CN=CA"}
    )
    assert same["self_issued"] is True and other["self_issued"] is False


def test_a_session_goes_to_its_first_certificate_even_when_only_a_later_one_has_details():
    out = overview(RawOpenSearch([ssl(["A", "B"])], [x509("B")]))
    (cert,) = out["certificates"]
    assert (cert["fingerprint"], cert["details_available"]) == ("A", False)
    assert out["summary"]["sessions_without_details"] == 1


def test_every_search_uses_one_snapshot_and_reads_every_session_field():
    client = RawOpenSearch([ssl(["A"]), ssl(["A"]), ssl(["A"])], [x509("A")])
    overview(client)
    assert {b["pit"]["id"] for b in client.bodies} == {"pit-0"}
    fields = [
        f if isinstance(f, str) else f["field"]
        for f in client.bodies[0]["docvalue_fields"]
    ]
    assert set(fields) == {
        "zeek.ssl.server_name",
        "destination.ip",
        "destination.port",
        "source.ip",
        "zeek.ssl.validation_status",
        "zeek.ssl.ssl_version",
        "@timestamp",
    }


def test_a_missing_field_is_kept_as_none_not_dropped():
    out = overview(RawOpenSearch([ssl(["A"], sni=None, status=None)], [x509("A")]))
    (site,) = out["sites"]
    assert site["id"] == "no-sni:93.184.216.34" and site["statuses"] == {"unchecked": 1}


def test_a_finding_and_a_device_beyond_the_row_cap_stay_in_the_figures():
    sessions = [  # two sessions each, so these five sites fill the capped list
        ssl([f"C{i}"], sni=f"s{i}.com", t="2026-11-05T11:00:00.000Z")
        for i in range(5)
        for _ in range(2)
    ]
    sessions.append(
        ssl(
            ["BAD"],
            sni="bad.com",
            status="unable to get local issuer certificate",
            t="2026-11-05T01:00:00.000Z",
        )
    )
    sessions.append(
        ssl(["NAS"], sni="nas.home", server="192.168.1.5", t="2026-11-05T01:00:00.000Z")
    )
    certs = [x509(f"C{i}") for i in range(5)] + [
        x509("BAD"),
        x509("NAS", not_after="2026-11-20T00:00:00"),
    ]
    out = paginate(overview(RawOpenSearch(sessions, certs)), cap=5)
    assert not {"bad.com", "nas.home"} & {s["id"] for s in out["sites"]}
    assert {f["fingerprint"] for f in out["findings"]} == {"BAD", "NAS"}
    assert (
        out["devices"][0]["fingerprint"] == "NAS"
        and out["summary"]["local_certificates"] == 1
    )
    assert {"BAD", "NAS"} <= set(out["details"]) and out["details"]["BAD"][
        "issuer_org"
    ] == "Let's Encrypt"


def test_expired_at_use_recounts_only_sessions_after_expiry_credited_to_that_certificate():
    gone = "certificate has expired"
    sessions = [
        ssl(
            ["OLD"], sni="old.com", client="192.168.1.10", t="2026-11-05T09:00:00.000Z"
        ),
        ssl(
            ["OLD"], sni="old.com", client="192.168.1.10", t="2026-11-05T10:00:00.000Z"
        ),
        ssl(
            ["OLD"],
            sni="old.com",
            client="192.168.1.11",
            status=gone,
            t="2026-11-05T11:00:00.000Z",
        ),
        ssl(
            ["OLD"],
            sni="old.com",
            client="192.168.1.11",
            status=gone,
            t="2026-11-05T11:30:00.000Z",
        ),
        # after expiry, but OLD is only later in the chain: not this certificate's session
        ssl(
            ["X", "OLD"],
            sni="old.com",
            client="192.168.1.12",
            t="2026-11-05T11:45:00.000Z",
        ),
    ]
    certs = [x509("OLD", not_after="2026-11-05T10:30:00"), x509("X")]
    client = RawOpenSearch(sessions, certs)
    out = overview(client)
    (f,) = [f for f in out["findings"] if f["kind"] == "expired-at-use"]
    assert (f["sessions"], f["clients"], f["clients_total"]) == (2, ["192.168.1.11"], 1)
    assert f["last_seen"].startswith("2026-11-05T11:30")
    assert {b["pit"]["id"] for b in client.bodies} == {"pit-0"}  # the same snapshot
    assert not client.open_pits


def test_no_recount_runs_when_nothing_was_used_after_expiry():
    client = RawOpenSearch([ssl(["A"]), ssl(["A"])], [x509("A")])
    overview(client)
    assert not any(
        "gt" in c.get("range", {}).get("@timestamp", {})
        for b in client.bodies
        if "query" in b
        for c in b["query"]["bool"]["filter"]
    )
