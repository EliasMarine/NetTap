"""
Tests for daemon/services/cert_findings.py (NET-154).

build() is pure: exact session tallies + certificate details + now → every figure the
Certificates page shows. Each test states one rule from PLAN.md §3/§5.
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import cert_findings
from services.cert_findings import build, failed, scope_of, weaknesses

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
T1, T2, T3 = (
    "2026-11-05T09:00:00.000Z",
    "2026-11-05T10:00:00.000Z",
    "2026-11-05T11:00:00.000Z",
)
PUBLIC, PUBLIC2, LAN = "93.184.216.34", "93.184.216.35", "192.168.1.20"


def use(
    fp, sni, server, status="ok", n=1, port=443, version="TLSv12", first=T1, last=T2
):
    return (fp, sni, server, port, status, version), [n, first, last]


def detail(issuer_org="Let's Encrypt", not_after="2027-01-01T00:00:00.000Z", **extra):
    return {
        "issuer_org": issuer_org,
        "issuer": "R3",
        "not_after": not_after,
        "subject_cn": "x",
        **extra,
    }


def run(rows, details=None, clients=None, expired=None):
    return build(
        dict(rows), clients or {}, details or {}, NOW, (dict(expired or []), {})
    )


def kinds(out):
    return sorted(
        (f["kind"], f["severity"], f["site_id"], f["fingerprint"])
        for f in out["findings"]
    )


# ---------------------------------------------------------------------------
# Small facts
# ---------------------------------------------------------------------------


def test_unchecked_and_ok_are_never_failures():
    assert (
        not failed(None)
        and not failed("")
        and not failed("ok")
        and not failed("unchecked")
    )
    assert failed("unable to get local issuer certificate")


def test_scope_of_covers_private_link_local_and_ipv6():
    assert [
        scope_of(ip)
        for ip in ("10.1.2.3", "172.31.0.1", "169.254.1.1", "fd00::1", "fe80::1")
    ] == ["local"] * 5
    assert (
        scope_of("8.8.8.8") == "public"
        and scope_of(None) == "unknown"
        and scope_of("nope") == "unknown"
    )


def test_weaknesses_name_sha1_md5_and_short_keys_only():
    assert weaknesses(
        {"sig_alg": "sha1WithRSAEncryption", "key_type": "rsa", "key_length": 1024}
    ) == [
        "SHA-1 signature",
        "1024-bit RSA key",
    ]
    assert weaknesses({"sig_alg": "md5WithRSAEncryption"}) == ["MD5 signature"]
    assert (
        weaknesses(
            {"sig_alg": "ecdsa-with-SHA256", "key_type": "ecdsa", "key_length": 256}
        )
        == []
    )
    assert weaknesses(None) == []


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


def test_sessions_reconcile_with_and_without_details():
    out = run(
        [
            use("A", "a.com", PUBLIC, n=3),
            use("B", "b.com", PUBLIC, n=2),
            use("C", "c.com", PUBLIC, n=4),
        ],
        details={"A": detail(), "B": detail()},
    )
    s = out["summary"]
    assert (
        s["sessions"],
        s["sessions_with_details"],
        s["sessions_without_details"],
    ) == (9, 5, 4)
    assert (s["certificates"], s["certificates_without_details"], s["sites"]) == (
        3,
        1,
        3,
    )
    unknown = next(c for c in out["certificates"] if c["fingerprint"] == "C")
    assert unknown["details_available"] is False and unknown["issuer_org"] == ""


def test_a_certificate_is_counted_once_across_sites_with_every_status():
    out = run(
        [
            use("A", "a.com", PUBLIC, n=3),
            use(
                "A",
                "www.a.com",
                PUBLIC,
                n=1,
                status="unable to get local issuer certificate",
                last=T3,
            ),
            use("A", "a.com", PUBLIC, n=2, status=None),
        ],
        details={"A": detail()},
    )
    (cert,) = out["certificates"]
    assert cert["sessions"] == 6 and cert["sites"] == ["a.com", "www.a.com"]
    assert cert["statuses"] == {
        "ok": 3,
        "unable to get local issuer certificate": 1,
        "unchecked": 2,
    }
    assert cert["verified"] is False and cert["last_seen"] == T3
    a = next(s for s in out["sites"] if s["id"] == "a.com")
    assert (
        a["sessions"] == 5
        and a["statuses"] == {"ok": 3, "unchecked": 2}
        and a["verified"] is False
    )


def test_sessions_without_a_server_name_group_per_server_address():
    out = run([use("A", None, PUBLIC), use("B", None, PUBLIC2)])
    assert {s["id"] for s in out["sites"]} == {f"no-sni:{PUBLIC}", f"no-sni:{PUBLIC2}"}
    assert all(s["name"] is None and s["server"] for s in out["sites"])


def test_clients_are_counted_per_certificate_and_site_and_capped_with_totals():
    clients = {
        ("A", "a.com", PUBLIC, 443, f"10.0.{i // 250}.{i % 250}", "ok"): 1
        for i in range(260)
    }
    out = run(
        [use("A", "a.com", PUBLIC, n=260)], details={"A": detail()}, clients=clients
    )
    (cert,), (site,) = out["certificates"], out["sites"]
    assert (
        cert["clients_total"] == 260
        and len(cert["clients"]) == cert_findings.NESTED_CAP
    )
    assert (
        site["clients_total"] == 260
        and len(site["clients"]) == cert_findings.NESTED_CAP
    )


def test_site_scope_is_mixed_when_it_resolves_to_local_and_public_servers():
    out = run([use("A", "nas.home", LAN), use("A", "nas.home", PUBLIC)])
    assert out["sites"][0]["scope"] == "mixed"


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def test_unverified_is_medium_when_no_other_certificate_verified():
    out = run(
        [use("A", "a.com", PUBLIC, status="unable to get local issuer certificate")],
        details={"A": detail()},
    )
    assert kinds(out) == [("unverified", "medium", "a.com", "A")]
    assert out["findings"][0]["failed"] == {"unable to get local issuer certificate": 1}


def test_unverified_is_high_only_beside_a_verified_certificate_from_another_authority():
    bad = "self-signed certificate in certificate chain"
    rows = [
        use("A", "bank.com", PUBLIC, status=bad),
        use("B", "bank.com", PUBLIC, n=40),
    ]
    out = run(
        rows,
        details={
            "A": detail(issuer_org="Corp Proxy CA"),
            "B": detail(issuer_org="DigiCert"),
        },
    )
    (f,) = out["findings"]
    assert (f["kind"], f["severity"], f["other_authority"]) == (
        "unverified-alongside-verified",
        "high",
        "DigiCert",
    )
    assert out["sites"][0]["worst"] == "high"


def test_same_authority_or_unknown_authority_never_escalates_to_high():
    bad = "unable to get local issuer certificate"
    same = run(
        [use("A", "a.com", PUBLIC, status=bad), use("B", "a.com", PUBLIC)],
        details={"A": detail(), "B": detail()},
    )
    unknown_mine = run(
        [use("A", "a.com", PUBLIC, status=bad), use("B", "a.com", PUBLIC)],
        details={"B": detail(issuer_org="DigiCert")},
    )
    other_not_fully_verified = run(
        [
            use("A", "a.com", PUBLIC, status=bad),
            use("B", "a.com", PUBLIC),
            use("B", "a.com", PUBLIC, status=None),
        ],
        details={"A": detail(), "B": detail(issuer_org="DigiCert")},
    )
    for out in (same, unknown_mine, other_not_fully_verified):
        assert [f["severity"] for f in out["findings"]] == ["medium"]


def test_unchecked_sessions_and_local_servers_raise_no_verification_finding():
    out = run(
        [
            use("A", "a.com", PUBLIC, status=None),
            use("L", "router.lan", LAN, status="self-signed certificate"),
        ],
        details={"A": detail(), "L": detail(not_after="2030-01-01T00:00:00.000Z")},
    )
    assert out["findings"] == []


def test_chain_expired_comes_from_the_status_even_without_details():
    out = run([use("A", "old.com", PUBLIC, status="certificate has expired")])
    (f,) = out["findings"]
    assert (f["kind"], f["severity"], f["failed"]) == (
        "chain-expired",
        "medium",
        {"certificate has expired": 1},
    )


def test_expired_at_use_replaces_chain_expired_when_the_dates_prove_it():
    after = use("A", "old.com", PUBLIC, status="certificate has expired", last=T3)
    out = run(
        [after],
        details={"A": detail(not_after="2026-11-05T10:30:00.000Z")},
        expired=[after],
    )
    assert kinds(out) == [("expired-at-use", "medium", "old.com", "A")]
    assert out["findings"][0]["not_after"] == "2026-11-05T10:30:00.000Z"


def test_a_certificate_that_expired_after_its_last_use_is_not_expired_at_use():
    out = run(
        [use("A", "a.com", PUBLIC, last=T1)],
        details={"A": detail(not_after="2026-11-05T09:30:00.000Z")},
    )
    assert out["findings"] == []


def test_weak_is_reported_once_per_certificate_at_its_busiest_site():
    weak = detail(sig_alg="sha1WithRSAEncryption")
    out = run(
        [use("A", "a.com", PUBLIC, n=1), use("A", "b.com", PUBLIC, n=5)],
        details={"A": weak},
    )
    assert kinds(out) == [("weak", "low", "b.com", "A")]
    assert out["findings"][0]["weaknesses"] == ["SHA-1 signature"]


def test_findings_sort_by_severity_then_site():
    bad = "unable to get local issuer certificate"
    out = run(
        [
            use("W", "a.com", PUBLIC),
            use("U", "z.com", PUBLIC, status=bad),
            use("H", "m.com", PUBLIC, status=bad),
            use("V", "m.com", PUBLIC),
        ],
        details={
            "W": detail(sig_alg="md5WithRSAEncryption"),
            "U": detail(),
            "H": detail(issuer_org="Proxy"),
            "V": detail(issuer_org="DigiCert"),
        },
    )
    assert [(f["severity"], f["site"]) for f in out["findings"]] == [
        ("high", "m.com"),
        ("medium", "z.com"),
        ("low", "a.com"),
    ]
    assert out["summary"]["findings"] == {"high": 1, "medium": 1, "low": 1, "total": 3}


# ---------------------------------------------------------------------------
# Your network's endpoints
# ---------------------------------------------------------------------------


def test_device_rows_use_the_latest_certificate_per_endpoint():
    out = run(
        [
            use("OLD", "nas.home", LAN, port=5001, last=T1),
            use("NEW", "nas.home", LAN, port=5001, last=T3),
        ],
        details={
            "OLD": detail(not_after="2026-11-10T00:00:00.000Z"),
            "NEW": detail(not_after="2027-11-10T00:00:00.000Z"),
        },
    )
    (row,) = out["devices"]
    assert (row["fingerprint"], row["certificates_total"], row["sessions"]) == (
        "NEW",
        2,
        2,
    )
    assert out["findings"] == []  # the replaced certificate's expiry no longer matters
    assert (
        out["summary"]["local_certificates"] == 2
        and out["summary"]["local_endpoints"] == 1
    )


def test_device_expiry_is_per_endpoint_so_two_ports_get_two_findings():
    soon = detail(not_after="2026-11-20T00:00:00.000Z")
    out = run(
        [use("A", "nas.home", LAN, port=443), use("A", "nas.home", LAN, port=5001)],
        details={"A": soon},
    )
    found = [f for f in out["findings"] if f["kind"] == "device-expiry"]
    assert sorted(f["port"] for f in found) == [443, 5001]
    assert len({f["id"] for f in found}) == 2
    assert all(f["days_left"] == 14 and f["severity"] == "low" for f in found)
    assert out["summary"]["soonest_local_expiry_days"] == 14


def test_device_with_unknown_details_has_no_expiry_finding_and_sorts_last():
    out = run(
        [use("A", "nas.home", LAN), use("B", "cam.home", "192.168.1.30")],
        details={"B": detail(not_after="2027-06-01T00:00:00.000Z")},
    )
    assert out["findings"] == []
    assert [r["fingerprint"] for r in out["devices"]] == ["B", "A"]
    assert (
        out["devices"][1]["days_left"] is None
        and out["devices"][1]["details_available"] is False
    )


def test_device_expiry_is_skipped_when_expired_at_use_already_covers_it():
    out = run(
        [use("A", "nas.home", LAN, last=T3)],
        details={"A": detail(not_after="2026-11-05T10:00:00.000Z")},
        expired=[use("A", "nas.home", LAN, first=T3, last=T3)],
    )
    assert kinds(out) == [("expired-at-use", "medium", "nas.home", "A")]


# ---------------------------------------------------------------------------
# Quiet switches
# ---------------------------------------------------------------------------


def test_quiet_switch_needs_two_known_authorities_all_verified():
    rows = [use("A", "cdn.com", PUBLIC), use("B", "cdn.com", PUBLIC2)]
    switched = run(rows, details={"A": detail(), "B": detail(issuer_org="DigiCert")})
    assert switched["quiet_switches"][0]["authorities"] == ["DigiCert", "Let's Encrypt"]
    assert switched["findings"] == []
    assert run(rows, details={"A": detail()})["quiet_switches"] == []
    one_unchecked = run(
        [*rows, use("B", "cdn.com", PUBLIC2, status=None)],
        details={"A": detail(), "B": detail(issuer_org="DigiCert")},
    )
    assert one_unchecked["quiet_switches"] == []


# ---------------------------------------------------------------------------
# Plan §7 cases
# ---------------------------------------------------------------------------


def test_a_public_failure_is_a_finding_even_when_the_site_is_also_served_locally():
    out = run(
        [
            use("A", "nas.example", LAN, status="self-signed certificate"),
            use("A", "nas.example", PUBLIC, status="self-signed certificate"),
        ],
        details={"A": detail(not_after="2030-01-01T00:00:00.000Z")},
    )
    (f,) = out["findings"]
    assert (f["kind"], f["server"], f["sessions"]) == ("unverified", PUBLIC, 1)


def test_sites_without_a_server_name_keep_their_own_clients():
    clients = {
        ("A", None, PUBLIC, 443, "192.168.1.10", "ok"): 1,
        ("B", None, PUBLIC2, 443, "192.168.1.11", "ok"): 1,
    }
    out = run([use("A", None, PUBLIC), use("B", None, PUBLIC2)], clients=clients)
    assert {s["id"]: s["clients"] for s in out["sites"]} == {
        f"no-sni:{PUBLIC}": ["192.168.1.10"],
        f"no-sni:{PUBLIC2}": ["192.168.1.11"],
    }


def test_a_renewed_device_certificate_without_details_reads_unknown_and_reminds_nothing():
    out = run(
        [use("OLD", "nas.home", LAN, last=T1), use("NEW", "nas.home", LAN, last=T3)],
        details={"OLD": detail(not_after="2026-11-10T00:00:00.000Z")},
    )
    (row,) = out["devices"]
    assert (row["fingerprint"], row["days_left"], row["details_available"]) == (
        "NEW",
        None,
        False,
    )
    assert out["findings"] == []


def test_one_site_with_many_certificates_is_capped_with_its_total():
    out = run([use(f"C{i}", "cdn.com", PUBLIC) for i in range(300)])
    (site,) = out["sites"]
    assert (len(site["certificates"]), site["certificates_total"]) == (
        cert_findings.NESTED_CAP,
        300,
    )
    assert out["summary"]["certificates"] == 300


def test_findings_and_device_rows_name_the_devices_whose_sessions_they_count():
    bad = "unable to get local issuer certificate"
    clients = {
        ("A", "a.com", PUBLIC, 443, "192.168.1.10", bad): 3,
        ("A", "a.com", PUBLIC, 443, "192.168.1.11", bad): 5,
        # a local server's session never counts toward a verification finding
        ("A", "a.com", LAN, 443, "192.168.1.12", bad): 9,
        ("N", "nas.home", LAN, 5001, "192.168.1.10", "ok"): 2,
        ("N", "nas.home", LAN, 443, "192.168.1.13", "ok"): 1,
    }
    out = run(
        [
            use("A", "a.com", PUBLIC, status=bad, n=8),
            use("A", "a.com", LAN, status=bad, n=9),
            use("N", "nas.home", LAN, port=5001, n=2),
            use("N", "nas.home", LAN, port=443),
        ],
        details={"A": detail(), "N": detail(not_after="2026-11-20T00:00:00.000Z")},
        clients=clients,
    )
    unverified = next(f for f in out["findings"] if f["kind"] == "unverified")
    assert (unverified["clients"], unverified["clients_total"]) == (
        ["192.168.1.11", "192.168.1.10"],
        2,
    )
    expiry = {
        f["port"]: f["clients"] for f in out["findings"] if f["kind"] == "device-expiry"
    }
    assert expiry == {5001: ["192.168.1.10"], 443: ["192.168.1.13"]}
    assert {
        d["port"]: d["clients"] for d in out["devices"] if d["site_id"] == "nas.home"
    } == expiry


def test_a_verification_finding_counts_dates_and_names_only_its_failing_sessions():
    bad = "unable to get local issuer certificate"
    clients = {
        ("A", "a.com", PUBLIC, 443, "192.168.1.10", "ok"): 86,
        ("A", "a.com", PUBLIC2, 443, "192.168.1.11", bad): 14,
    }
    out = run(
        [
            use("A", "a.com", PUBLIC, n=86, last=T3),
            use("A", "a.com", PUBLIC2, status=bad, n=14, last=T2),
        ],
        details={"A": detail()},
        clients=clients,
    )
    (f,) = out["findings"]
    assert (f["sessions"], f["failed"], f["last_seen"]) == (14, {bad: 14}, T2)
    assert (f["clients"], f["servers"]) == (["192.168.1.11"], [PUBLIC2])
    assert out["sites"][0]["sessions"] == 100


def test_expired_at_use_counts_and_names_only_the_sessions_after_expiry():
    gone = "certificate has expired"
    out = run(
        [
            use("A", "old.com", PUBLIC, n=30, first=T1, last=T1),
            use("A", "old.com", PUBLIC, status=gone, n=2, first=T3, last=T3),
        ],
        details={"A": detail(not_after="2026-11-05T10:30:00.000Z")},
        clients={
            ("A", "old.com", PUBLIC, 443, "192.168.1.10", "ok"): 30,
            ("A", "old.com", PUBLIC, 443, "192.168.1.11", gone): 2,
        },
        expired=[use("A", "old.com", PUBLIC, status=gone, n=2, first=T3, last=T3)],
    )
    (f,) = out["findings"]
    assert (f["kind"], f["sessions"], f["last_seen"]) == ("expired-at-use", 2, T3)
    assert f["clients"] == [] and f["clients_total"] == 0  # no client tally passed in


def test_device_expiry_names_only_the_devices_that_got_that_certificate():
    out = build(
        dict(
            [
                use("OLD", "nas.home", LAN, last=T1),
                use("NEW", "nas.home", LAN, last=T3),
            ]
        ),
        {
            ("OLD", "nas.home", LAN, 443, "192.168.1.10", "ok"): 1,
            ("NEW", "nas.home", LAN, 443, "192.168.1.11", "ok"): 1,
        },
        {"NEW": detail(not_after="2026-11-20T00:00:00.000Z")},
        NOW,
    )
    (f,) = out["findings"]
    assert (f["kind"], f["fingerprint"], f["clients"]) == (
        "device-expiry",
        "NEW",
        ["192.168.1.11"],
    )
    assert out["devices"][0]["clients_total"] == 2  # the row covers both certificates
