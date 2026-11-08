"""NET-209: which device each alert concerns, whether it was its own traffic, and kill chains.

The rules are in Debugging/THREAT-SCORING.md. 91.92.40.12 (an internet scanner on Spamhaus DROP
probing the port-forwarded 192.168.1.24) was shown as a LAN device with a kill chain and a High
risk score; none of that survives these rules.
"""

from unittest.mock import MagicMock, patch

import pytest

from services import alert_findings as af
from services import alert_intelligence
from services.alert_intelligence import (
    KILL_CHAIN_STAGES,
    get_smart_alert_summary,
    get_smart_alerts,
)

_FROM, _TO = "2026-11-03T00:00:00Z", "2026-11-08T00:00:00Z"
_HOUR = 3_600_000
_MON = 1_762_128_000_000  # 2025-11-03T00:00:00Z, a Monday
is_lan = af.lan_test(None)

SERVER, PC, PROXY = "192.168.1.24", "192.168.1.148", "192.168.1.2"
SCANNER, C2 = "91.92.40.12", "203.0.113.9"


# ---------------------------------------------------------------------------
# charge(): one device per alert, own traffic or an attempt
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "src, dst, opener, client_target, expected",
    [
        (PC, C2, None, False, (PC, True)),  # its request out
        (
            SERVER,
            SCANNER,
            SCANNER,
            False,
            (SERVER, True),
        ),  # its response on an inbound conn
        (C2, PC, PC, False, (PC, True)),  # a reply to a connection it opened
        (SCANNER, SERVER, SCANNER, False, (SERVER, False)),  # an attempt against it
        (
            SCANNER,
            SERVER,
            None,
            False,
            (SERVER, False),
        ),  # opener unknown: never its own
        (
            PROXY,
            PC,
            PC,
            True,
            (PC, True),
        ),  # proxy relays a client-side alert to the client
        (PC, PROXY, PC, True, (PC, True)),
        (PROXY, PC, None, True, (None, False)),  # client-side alert, opener unknown
        (
            PC,
            SERVER,
            None,
            False,
            (PC, True),
        ),  # LAN to LAN otherwise: the packet's source
        (SCANNER, C2, None, False, (None, False)),  # no LAN party
    ],
)
def test_charge(src, dst, opener, client_target, expected):
    assert af.charge(src, dst, opener, client_target, is_lan) == expected


def test_opener_needs_one_answer_within_the_slack():
    spans = [(PC, 1_000_000, 2_000_000)]
    assert af.opener_at(spans, 2_000_000 + af.CONN_SLACK_MS) == PC
    assert af.opener_at(spans, 2_000_001 + af.CONN_SLACK_MS) is None
    # the same community ID reused by two conns opened from different ends
    assert af.opener_at([*spans, (SCANNER, 1_500_000, 1_600_000)], 1_550_000) is None


def test_a_reused_tuple_splits_into_own_traffic_and_an_attempt():
    """Community ID has no time in it: each alert instant takes the conn open at that moment."""
    cid = "1:reused"
    spans = {cid: [(PC, _MON, _MON + _HOUR), (C2, _MON + 5 * _HOUR, _MON + 6 * _HOUR)]}
    instants = [
        {"sig": "S", "src": C2, "dst": PC, "cid": cid, "ts": _MON + 10_000, "count": 2},
        {
            "sig": "S",
            "src": C2,
            "dst": PC,
            "cid": cid,
            "ts": _MON + 5 * _HOUR + 1,
            "count": 3,
        },
    ]
    found = af.findings_by_group(instants, spans, {}, is_lan)[("S", C2, PC)]
    by_own = {f["own"]: f["count"] for f in found}
    assert by_own == {True: 2, False: 3}


def test_dates_come_as_epoch_ms_or_iso():
    instants = [
        {
            "sig": "S",
            "src": PC,
            "dst": C2,
            "cid": None,
            "ts": "2025-11-03T00:00:00Z",
            "count": 1,
        }
    ]
    (finding,) = af.findings_by_group(instants, {}, {}, is_lan)[("S", PC, C2)]
    assert finding["times"] == [(_MON, 1)]


# ---------------------------------------------------------------------------
# Reputation lists (rules 8-10)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "signature",
    [
        "ET DROP Spamhaus DROP Listed Traffic Inbound group 12",
        "ET DSHIELD Block Listed Source group 1",
        "ET CINS Active Threat Intelligence Poor Reputation IP group 40",
        "ET COMPROMISED Known Compromised or Hostile Host Traffic group 7",
        "ET TOR Known Tor Exit Node Traffic group 3",
        "ET 3CORESEC Poor Reputation IP group 2",
    ],
)
def test_reputation_families(signature):
    assert af.is_reputation(signature)
    assert af.finding_severity(2, {"own": True}, True) == 3  # at most medium
    assert af.finding_severity(2, {"own": False}, True) == 5  # not counted


def test_other_rules_are_not_reputation_hits():
    assert not af.is_reputation("ET EXPLOIT Apache log4j RCE Attempt")
    assert af.finding_severity(1, {"own": False}, False) == 1


# ---------------------------------------------------------------------------
# Kill chains (rules in the brief: per device, real instants, stage and time order)
# ---------------------------------------------------------------------------


def _group(signature, category, findings):
    return {"signature": signature, "category": category, "findings": findings}


def _finding(device, own, *times, severity=2):
    return {
        "device": device,
        "own": own,
        "count": len(times),
        "severity": severity,
        "times": [(t, 1) for t in times],
    }


def _chains(groups):
    return af.kill_chains(groups, KILL_CHAIN_STAGES.get, str)


def test_recon_exploit_c2_within_a_day_is_a_chain():
    chains = _chains(
        [
            _group("scan", "reconnaissance", [_finding(PC, True, _MON)]),
            _group("exploit", "exploit", [_finding(PC, True, _MON + 2 * _HOUR)]),
            _group("c2", "malware_c2", [_finding(PC, True, _MON + 20 * _HOUR)]),
        ]
    )
    assert [c["stages"] for c in chains] == [[1, 2, 3]]
    assert chains[0]["source_ip"] == PC
    assert "active intrusion" in chains[0]["assessment"]


def test_monday_wednesday_friday_is_not_a_chain():
    days = 24 * _HOUR
    assert not _chains(
        [
            _group("scan", "reconnaissance", [_finding(PC, True, _MON)]),
            _group("exploit", "exploit", [_finding(PC, True, _MON + 2 * days)]),
            _group("c2", "malware_c2", [_finding(PC, True, _MON + 4 * days)]),
        ]
    )


def test_stages_in_reverse_order_are_not_a_chain():
    assert not _chains(
        [
            _group("c2", "malware_c2", [_finding(PC, True, _MON)]),
            _group("exploit", "exploit", [_finding(PC, True, _MON + _HOUR)]),
            _group("scan", "reconnaissance", [_finding(PC, True, _MON + 2 * _HOUR)]),
        ]
    )


def test_a_30_hour_gap_breaks_the_chain():
    assert not _chains(
        [
            _group("exploit", "exploit", [_finding(PC, True, _MON)]),
            _group("c2", "malware_c2", [_finding(PC, True, _MON + 30 * _HOUR)]),
        ]
    )


def test_attempts_alone_are_not_a_chain():
    """91.92.40.12 scanning then trying exploits on 192.168.1.24: nothing came from the server."""
    assert not _chains(
        [
            _group("scan", "reconnaissance", [_finding(SERVER, False, _MON)]),
            _group("exploit", "exploit", [_finding(SERVER, False, _MON + _HOUR)]),
        ]
    )


def test_attempts_then_its_own_c2_is_a_chain():
    chains = _chains(
        [
            _group("scan", "reconnaissance", [_finding(SERVER, False, _MON)]),
            _group("exploit", "exploit", [_finding(SERVER, False, _MON + _HOUR)]),
            _group("c2", "malware_c2", [_finding(SERVER, True, _MON + 3 * _HOUR)]),
        ]
    )
    assert [c["stages"] for c in chains] == [[1, 2, 3]]
    assert all("times" not in f for a in chains[0]["alerts"] for f in a["findings"])


def test_a_c2_attempt_or_a_blocklist_hit_makes_no_stage():
    assert not _chains(
        [
            _group("scan", "reconnaissance", [_finding(PC, True, _MON)]),
            _group("c2", "malware_c2", [_finding(PC, False, _MON + _HOUR)]),
            _group(
                "ET DROP Spamhaus DROP Listed Traffic Inbound group 1",
                "malware_c2",
                [_finding(PC, True, _MON + 2 * _HOUR)],
            ),
        ]
    )


def test_informational_findings_make_no_stage():
    assert not _chains(
        [
            _group("scan", "reconnaissance", [_finding(PC, True, _MON)]),
            _group(
                "exploit", "exploit", [_finding(PC, True, _MON + _HOUR, severity=5)]
            ),
        ]
    )


# ---------------------------------------------------------------------------
# End to end: the smart alerts and the summary for 91.92.40.12
# ---------------------------------------------------------------------------


def _bucket(sig, src, dst, count, severity_meta, attack_target="Server", sid=1):
    return {
        "key": {"sig_name": sig, "src_ip": src, "dst_ip": dst},
        "doc_count": count,
        "first_seen": {"value_as_string": "2026-11-07T10:00:00Z"},
        "last_seen": {"value_as_string": "2026-11-07T11:00:00Z"},
        "sample": {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "alert": {
                                "signature": sig,
                                "signature_id": sid,
                                "severity": 2,
                                "category": "Attempted Administrator Privilege Gain",
                            },
                            "suricata": {
                                "alert": {
                                    "metadata": {
                                        "signature_severity": [severity_meta],
                                        "attack_target": [attack_target],
                                    }
                                }
                            },
                            "destination": {"port": 443},
                        }
                    }
                ]
            }
        },
    }


def _client(groups, instants, spans):
    """Answers the grouped alerts, the activity alerts (none), alert instants and conn spans."""
    from api.alerts import ET_ACTIVITY_CLAUSE

    def search(index, body):
        aggs = body["aggs"]
        if "grouped" in aggs:
            activity = ET_ACTIVITY_CLAUSE in body["query"]["bool"]["filter"]
            return {
                "aggregations": {"grouped": {"buckets": [] if activity else groups}}
            }
        names = [next(iter(s)) for s in aggs["all"]["composite"]["sources"]]
        return {
            "aggregations": {"all": {"buckets": instants if "ts" in names else spans}}
        }

    client = MagicMock()
    client.search.side_effect = search
    return client


_DROP = "ET DROP Spamhaus DROP Listed Traffic Inbound group 12"
_EXPLOIT = "ET EXPLOIT Apache log4j RCE Attempt"
_T = 1_762_509_600_000  # 2025-11-07T10:00:00Z


def _instant(sig, src, dst, cid, ts, count=1):
    return {
        "key": {"sig": sig, "src": src, "dst": dst, "cid": cid, "ts": ts},
        "doc_count": count,
    }


def _scanner_client():
    """91.92.40.12 opens every conn to the server; the server only answers (405 / reset)."""
    groups = [
        _bucket(_DROP, SCANNER, SERVER, 26, "Minor", sid=2400011),
        _bucket(_EXPLOIT, SCANNER, SERVER, 9, "Critical", sid=2034647),
    ]
    instants = [
        _instant(_DROP, SCANNER, SERVER, "1:a", _T, 26),
        _instant(_EXPLOIT, SCANNER, SERVER, "1:b", _T + _HOUR, 9),
    ]
    spans = [
        {
            "key": {"cid": cid, "orig": SCANNER, "start": t - 1_000, "end": t + 1_000},
            "doc_count": 1,
        }
        for cid, t in (("1:a", _T), ("1:b", _T + _HOUR))
    ]
    return _client(groups, instants, spans)


@pytest.fixture
def quiet():
    with (
        patch.object(alert_intelligence, "is_suppressed", return_value=False),
        patch.object(alert_intelligence, "update_baseline", return_value=None),
    ):
        yield


def test_the_scanner_is_never_a_device_and_its_attempts_barely_score(quiet):
    summary = get_smart_alert_summary(_scanner_client(), _FROM, _TO)

    assert summary["kill_chains"] == []
    # the exploit attempt weighs at most low (0.5); the blocklist hit it started weighs nothing
    assert summary["threat_score"] == 0
    assert summary["total_events"] == 9
    assert summary["informational_events"] == 26
    (top,) = summary["top_threats"]
    assert top["signature"] == _EXPLOIT
    assert top["lan_device"] == SERVER and top["own_traffic"] is False
    assert [(f["device"], f["own"], f["count"]) for f in top["findings"]] == [
        (SERVER, False, 9)
    ]
    assert "times" not in top["findings"][0]


def test_the_blocklist_hit_is_activity_when_nobody_on_the_lan_started_it(quiet):
    groups = get_smart_alerts(
        _scanner_client(), _FROM, _TO, include_info=True, limit=None
    )
    drop = next(g for g in groups if g["signature"] == _DROP)
    assert drop["reputation"] is True
    assert drop["severity"] == 5
    assert drop["counted_events"] == 0


def test_a_device_that_contacts_a_listed_host_counts_at_medium(quiet):
    """192.168.1.148 opened connections to a DROP-listed network: its own traffic, Minor at most."""
    groups = [_bucket(_DROP.replace("Inbound", "Outbound"), PC, C2, 4, "Major")]
    instants = [_instant(groups[0]["key"]["sig_name"], PC, C2, "1:c", _T, 4)]
    summary = get_smart_alert_summary(_client(groups, instants, []), _FROM, _TO)
    (top,) = summary["top_threats"]
    assert top["severity"] == 3 and top["own_traffic"] is True
    assert summary["threat_score"] == 2
    assert summary["threat_level"] == "low"


def test_one_signature_on_one_device_scores_once(quiet):
    """Rule 5: one malware check-in to 40 addresses is one finding, not 40."""
    sig = "ET MALWARE Win32 Agent CnC Checkin"
    groups = [_bucket(sig, PC, f"203.0.113.{n}", 1, "Critical") for n in range(40)]
    instants = [_instant(sig, PC, f"203.0.113.{n}", None, _T + n) for n in range(40)]
    summary = get_smart_alert_summary(_client(groups, instants, []), _FROM, _TO)
    assert summary["threat_score"] == 10
    assert summary["total_events"] == 40
    assert summary["threat_level"] == "low"


def test_attempts_from_many_scanners_weigh_low_once_per_signature(quiet):
    groups = [
        _bucket(_EXPLOIT, f"198.51.100.{n}", SERVER, 1, "Critical") for n in range(30)
    ]
    instants = [
        _instant(_EXPLOIT, f"198.51.100.{n}", SERVER, None, _T + n) for n in range(30)
    ]
    summary = get_smart_alert_summary(_client(groups, instants, []), _FROM, _TO)
    assert summary["threat_score"] == 0  # 0.5, rounded down
    assert summary["total_events"] == 30


def test_a_device_suppression_hides_the_attempts_against_it():
    def suppressed(sig_id, ip=None):
        return ip == SERVER

    with (
        patch.object(alert_intelligence, "is_suppressed", side_effect=suppressed),
        patch.object(alert_intelligence, "update_baseline", return_value=None),
    ):
        groups = get_smart_alerts(
            _scanner_client(), _FROM, _TO, include_info=True, limit=None
        )
    assert groups == []


def test_a_blocklist_hit_on_a_still_open_connection_stays_listed(quiet):
    """No Zeek record yet (the C2 keeps the session open): unknown is not an attempt; never hidden."""
    groups = [_bucket(_DROP, C2, PC, 12, "Minor", sid=2400011)]
    instants = [_instant(_DROP, C2, PC, "1:open", _T, 12)]
    listed = get_smart_alerts(_client(groups, instants, []), _FROM, _TO, limit=None)
    (group,) = listed
    assert group["severity"] == 3
    assert group["counted_events"] == 12
    (finding,) = group["findings"]
    assert (finding["own"], finding["opener_known"]) == (False, False)

    summary = get_smart_alert_summary(_client(groups, instants, []), _FROM, _TO)
    assert summary["total_events"] == 12
    assert summary["threat_score"] == 0  # attempt weight: 0.5, rounded down


def test_unknown_and_known_attempts_are_separate_findings():
    cid = "1:mixed"
    spans = {cid: [(SCANNER, _MON, _MON + _HOUR)]}
    instants = [
        {
            "sig": "S",
            "src": SCANNER,
            "dst": SERVER,
            "cid": cid,
            "ts": _MON + 1,
            "count": 2,
        },
        {
            "sig": "S",
            "src": SCANNER,
            "dst": SERVER,
            "cid": cid,
            "ts": _MON + 5 * _HOUR,
            "count": 3,
        },
    ]
    found = af.findings_by_group(instants, spans, {}, is_lan)[("S", SCANNER, SERVER)]
    assert sorted((f["opener_known"], f["count"]) for f in found) == [
        (False, 3),
        (True, 2),
    ]
    assert af.finding_severity(2, {"own": False, "opener_known": False}, True) == 3
