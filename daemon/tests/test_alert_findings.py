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
    assert top["own_traffic"] is False
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
    """No Zeek record past the settle time (the C2 keeps the session open): the device's own."""
    groups = [_bucket(_DROP, C2, PC, 12, "Minor", sid=2400011)]
    instants = [_instant(_DROP, C2, PC, "1:open", _T, 12)]
    listed = get_smart_alerts(_client(groups, instants, []), _FROM, _TO, limit=None)
    (group,) = listed
    assert group["severity"] == 3
    assert group["counted_events"] == 12
    (finding,) = group["findings"]
    assert (finding["own"], finding["opener_known"]) == (True, False)

    summary = get_smart_alert_summary(_client(groups, instants, []), _FROM, _TO)
    assert summary["total_events"] == 12
    assert summary["threat_score"] == 2  # an own medium


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
    assert sorted((f["opener_known"], f["own"], f["count"]) for f in found) == [
        (False, True, 3),  # no record covers the later alert: held open, own
        (True, False, 2),  # the record shows the scanner opened it: an attempt
    ]
    assert af.finding_severity(2, {"own": False, "opener_known": True}, True) == 5


# ---------------------------------------------------------------------------
# NET-209 review: chain timing, the proxy case, demoted alerts, and the two new reads
# ---------------------------------------------------------------------------


def test_the_chain_uses_the_c2_after_the_attempt_not_the_one_before():
    """Own C2 at 08:00 and 11:00, an exploit attempt at 10:00: 10:00 → 11:00 is the chain."""
    chains = _chains(
        [
            _group(
                "c2",
                "malware_c2",
                [_finding(PC, True, _MON + 8 * _HOUR, _MON + 11 * _HOUR)],
            ),
            _group("exploit", "exploit", [_finding(PC, False, _MON + 10 * _HOUR)]),
        ]
    )
    assert [c["stages"] for c in chains] == [[2, 3]]
    assert chains[0]["first_seen"] == af._iso_ms(_MON + 10 * _HOUR)
    assert chains[0]["last_seen"] == af._iso_ms(_MON + 11 * _HOUR)


def test_the_chain_is_found_among_c2_check_ins_days_apart():
    day = 24 * _HOUR
    c2_times = (
        _MON + 8 * _HOUR,
        _MON + 2 * day + 11 * _HOUR,
        _MON + 4 * day + 11 * _HOUR,
    )
    chains = _chains(
        [
            _group("c2", "malware_c2", [_finding(PC, True, *c2_times)]),
            _group(
                "exploit", "exploit", [_finding(PC, False, _MON + 2 * day + 10 * _HOUR)]
            ),
        ]
    )
    assert [c["stages"] for c in chains] == [[2, 3]]
    assert chains[0]["first_seen"] == af._iso_ms(_MON + 2 * day + 10 * _HOUR)


def test_a_proxied_client_alert_is_charged_to_the_client(quiet):
    """A client-side rule seen between the proxy and the client: the client opened the connection."""
    sig = "ET MALWARE Agent CnC Checkin"
    groups = [_bucket(sig, PROXY, PC, 3, "Major", attack_target="Client_Endpoint")]
    instants = [_instant(sig, PROXY, PC, "1:p", _T, 3)]
    spans = [
        {
            "key": {"cid": "1:p", "orig": PC, "start": _T - 500, "end": _T + 500},
            "doc_count": 1,
        }
    ]
    (group,) = get_smart_alerts(
        _client(groups, instants, spans), _FROM, _TO, limit=None
    )
    assert [(f["device"], f["own"], f["count"]) for f in group["findings"]] == [
        (PC, True, 3)
    ]
    assert group["unattributed"] == 0

    (unknown,) = get_smart_alerts(_client(groups, instants, []), _FROM, _TO, limit=None)
    assert unknown["findings"] == [] and unknown["unattributed"] == 3  # nobody charged


def test_demoted_alerts_move_neither_the_score_nor_the_events(quiet):
    """C2 → PC in one group: 4 on PC's own connection, then 10,000 the C2 opened."""
    groups = [_bucket(_DROP, C2, PC, 4, "Major")]
    own = [_instant(_DROP, C2, PC, "1:own", _T, 4)]
    spans = [
        {
            "key": {"cid": "1:own", "orig": PC, "start": _T - 500, "end": _T + 500},
            "doc_count": 1,
        },
        {
            "key": {"cid": "1:in", "orig": C2, "start": _T, "end": _T + _HOUR},
            "doc_count": 1,
        },
    ]
    alone = get_smart_alert_summary(_client(groups, own, spans), _FROM, _TO)
    noisy = [{**groups[0], "doc_count": 10_004}]
    flood = [*own, _instant(_DROP, C2, PC, "1:in", _T + 60_000, 10_000)]
    mixed = get_smart_alert_summary(_client(noisy, flood, spans), _FROM, _TO)
    for key in ("threat_score", "threat_level", "total_events"):
        assert mixed[key] == alone[key]
    assert (alone["total_events"], mixed["informational_events"]) == (4, 10_000)


def test_a_fresh_alert_waits_for_its_record_as_an_attempt():
    """No record yet, under SETTLE_MS old: an attempt (left out), so the page does not flicker."""
    inst = [{"sig": _DROP, "src": C2, "dst": PC, "cid": "1:x", "ts": _T, "count": 1}]
    fresh = af.findings_by_group(inst, {}, {}, is_lan, settled_before=_T - 1)
    held = af.findings_by_group(inst, {}, {}, is_lan, settled_before=_T + 1)
    assert (
        fresh[(_DROP, C2, PC)][0]["own"] is False
    )  # its record may still be on the way
    assert held[(_DROP, C2, PC)][0]["own"] is True  # held open past the settle time
    no_cid = [
        {**inst[0], "cid": None}
    ]  # nothing to look up: packet direction, an attempt
    assert (
        af.findings_by_group(no_cid, {}, {}, is_lan)[(_DROP, C2, PC)][0]["own"] is False
    )


def test_epoch_ms_is_exact_and_reads_no_zone_as_utc():
    assert af.epoch_ms("2025-11-03T00:00:00.123Z") == _MON + 123
    assert af.epoch_ms("2025-11-03T00:00:00.123") == _MON + 123


def _page_client(buckets):
    client = MagicMock()
    client.search.return_value = {"aggregations": {"all": {"buckets": buckets}}}
    return client


def test_the_instant_read_keeps_alerts_with_a_lan_party():
    client = _page_client([])
    base = {"filter": [{"term": {"event.dataset": "alert"}}], "must_not": [{"x": 1}]}
    af.alert_instants(client, "idx", base, ["192.168.1.0/24"])
    query = client.search.call_args.kwargs["body"]["query"]["bool"]
    assert query["must_not"] == [{"x": 1}]
    lan_party = query["filter"][-1]["bool"]
    assert lan_party["minimum_should_match"] == 1
    assert lan_party["should"] == [
        {"terms": {"source.ip": ["192.168.1.0/24"]}},
        {"terms": {"destination.ip": ["192.168.1.0/24"]}},
    ]


def test_the_conn_read_spans_a_day_before_and_an_hour_after_in_chunks(monkeypatch):
    monkeypatch.setattr(af, "_CID_CHUNK", 2)
    client = _page_client([])
    af.connection_spans(client, "idx", ["a", "b", "c", "d", "e"], _FROM, _TO)
    bodies = [
        c.kwargs["body"]["query"]["bool"]["filter"]
        for c in client.search.call_args_list
    ]
    assert [f[-1]["terms"]["network.community_id"] for f in bodies] == [
        ["a", "b"],
        ["c", "d"],
        ["e"],
    ]
    window = bodies[0][0]["range"]["@timestamp"]
    assert af.epoch_ms(window["gte"]) == af.epoch_ms(_FROM) - 24 * _HOUR
    assert af.epoch_ms(window["lte"]) == af.epoch_ms(_TO) + _HOUR


@pytest.mark.parametrize("read", ["instants", "conns"])
def test_a_partial_read_raises(read):
    from storage.snapshot_search import QueryFailed

    with (
        patch.object(af, "all_buckets", return_value=([], False)),
        pytest.raises(QueryFailed),
    ):
        if read == "instants":
            af.alert_instants(MagicMock(), "idx", {"filter": []}, ["10.0.0.0/8"])
        else:
            af.connection_spans(MagicMock(), "idx", ["a"], _FROM, _TO)


# ---------------------------------------------------------------------------
# NET-209 security review: F1 held-open C2, F2 flipped records, F3 minute buckets, F4 no LAN party
# ---------------------------------------------------------------------------


def test_a_c2_alert_on_a_session_held_open_is_the_devices_own(quiet):
    """F1: a RAT's C2 certificate alert (C2 to device) with no conn record past the settle time."""
    sig = "ET MALWARE Observed Malicious SSL Cert (AsyncRAT)"
    groups = [_bucket(sig, C2, PC, 3, "Critical")]
    instants = [_instant(sig, C2, PC, "1:rat", _T, 3)]
    summary = get_smart_alert_summary(_client(groups, instants, []), _FROM, _TO)
    assert summary["threat_score"] == 10  # own critical, not an attempt's 0.5


@pytest.mark.parametrize(
    "history, transport, trusted",
    [
        ("ShADadFf", "tcp", True),
        ("Dd", "udp", True),
        ("^Dd", "udp", False),  # Zeek flipped it: UDP from a "server" port such as 5353
        ("DadA", "tcp", False),  # picked up mid-stream: no SYN first
        (None, None, True),
    ],
)
def test_the_opener_is_trusted_only_from_a_clean_record(history, transport, trusted):
    assert af._opener_trusted(history, transport) is trusted


def test_a_flipped_record_never_makes_the_c2_look_like_the_opener():
    """F2: malware sends UDP from local port 5353; Zeek records the C2 as the originator."""
    key = {
        "cid": "1:u",
        "orig": C2,
        "start": _T,
        "end": _T + 1,
        "hist": "^Dd",
        "proto": "udp",
    }
    client = _page_client([{"key": key, "doc_count": 1}])
    assert af.connection_spans(client, "idx", ["1:u"], _FROM, _TO) == {}
    sources = client.search.call_args.kwargs["body"]["aggs"]["all"]["composite"][
        "sources"
    ]
    assert {
        "hist": {"terms": {"field": "zeek.conn.history", "missing_bucket": True}}
    } in sources


def test_alert_times_are_read_per_minute():
    """F3: a flood on one connection is one bucket a minute, not one per alert."""
    client = _page_client([])
    af.alert_instants(client, "idx", {"filter": []}, ["10.0.0.0/8"])
    sources = client.search.call_args.kwargs["body"]["aggs"]["all"]["composite"][
        "sources"
    ]
    assert sources[-1] == {
        "ts": {"date_histogram": {"field": "@timestamp", "fixed_interval": "1m"}}
    }
    # a minute bucket matches a conn that overlaps that minute, and no other
    assert af.opener_at([(PC, _MON + 30_000, _MON + 40_000)], _MON) == PC
    late = _MON + af.INSTANT_MS + af.CONN_SLACK_MS
    assert af.opener_at([(PC, late, late + _HOUR)], _MON) is None


def test_a_blocklist_hit_with_no_lan_party_stays_listed(quiet):
    """F4: 172.20.0.9 is outside the LAN rule (192.168.1.0/24), so no device can be charged."""
    groups = [_bucket(_DROP, SCANNER, "172.20.0.9", 5, "Major")]
    instants = [_instant(_DROP, SCANNER, "172.20.0.9", "1:v", _T, 5)]
    (group,) = get_smart_alerts(
        _client(groups, instants, []),
        _FROM,
        _TO,
        limit=None,
        lan_cidrs=["192.168.1.0/24"],
    )
    assert (group["severity"], group["counted_events"], group["findings"]) == (3, 5, [])
