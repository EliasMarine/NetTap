"""NET-240: lateral movement sees a session while it is open, counted once.

Zeek's long-connection package writes interim records (conn_long.log, same zeek.uid, @timestamp
= the connection's start, lastPacket = when last seen) before the final conn.log record.
Lateral movement reads both, keeps connections active in the window, and counts distinct uids;
beaconing keeps final records only. The fake evaluates the real query over raw documents.
"""

from services.excluded_ips import CONN_ACCOUNTING, CONN_RECORDS
from services.threat_detection import detect_lateral_movement
from tests.fake_drill_opensearch import FROM, TO, DrillOpenSearch, conn

ADMIN, NAS = "192.168.1.66", "192.168.1.10"


def _ssh(uid=None, t="2026-11-05T10:00:00.000Z", last=None, path="conn.log", dst=NAS):
    fields = {"destination__port": 22, "log__file__path": path}
    if uid is not None:
        fields["zeek__uid"] = uid
    if last is not None:
        fields["lastPacket"] = last
    return conn(ADMIN, dst, t=t, **fields)


def _moves(docs):
    client = DrillOpenSearch(docs)
    moves, complete = detect_lateral_movement(client, FROM, TO)
    assert complete is True
    return moves, client


def test_the_query_reads_interim_records_and_selects_connections_active_in_the_window():
    _, client = _moves([_ssh("C1")])
    (body,) = client.bodies
    filters = body["query"]["bool"]["filter"]
    assert CONN_RECORDS in filters and CONN_ACCOUNTING not in filters
    assert {"range": {"@timestamp": {"lte": TO}}} in filters
    assert {
        "bool": {
            "should": [
                {"range": {"lastPacket": {"gte": FROM}}},
                {"range": {"@timestamp": {"gte": FROM}}},
            ],
            "minimum_should_match": 1,
        }
    } in filters


def test_interim_and_final_records_of_one_connection_count_once():
    (move,), _ = _moves(
        [
            _ssh("C1", last="2026-11-05T10:10:00.000Z", path="conn_long.log"),
            _ssh("C1", last="2026-11-05T10:30:00.000Z", path="conn_long.log"),
            _ssh("C1", last="2026-11-05T10:45:00.000Z"),
        ]
    )
    assert move["connection_count"] == 1
    assert move["records_without_uid"] == 0
    assert "(about 1 connections)" in move["assessment"]
    assert "no connection ID" not in move["assessment"]


def test_a_session_begun_before_the_window_shows_by_its_interim_record():
    """Started yesterday, still open: its only record in reach is an interim one."""
    (move,), _ = _moves(
        [
            _ssh(
                "C-open",
                t="2026-11-04T20:00:00.000Z",
                last="2026-11-05T08:00:00.000Z",
                path="conn_long.log",
            )
        ]
    )
    assert (move["source_ip"], move["destination_ip"]) == (ADMIN, NAS)
    assert move["first_seen"] == "2026-11-04T20:00:00.000Z"
    assert move["last_seen"] == "2026-11-05T08:00:00.000Z"


def test_a_connection_that_ended_before_the_window_is_not_listed():
    moves, _ = _moves(
        [_ssh("C-old", t="2026-11-04T20:00:00.000Z", last="2026-11-04T21:00:00.000Z")]
    )
    assert moves == []


def test_last_seen_is_the_newest_activity_of_either_field():
    with_last = _ssh(
        "C1", t="2026-11-05T09:00:00.000Z", last="2026-11-05T09:40:00.000Z"
    )
    newer_without = _ssh("C2", t="2026-11-05T11:00:00.000Z")
    (move,), _ = _moves([with_last, newer_without])
    assert move["last_seen"] == "2026-11-05T11:00:00.000Z"
    (move,), _ = _moves([with_last])
    assert move["last_seen"] == "2026-11-05T09:40:00.000Z"
    (move,), _ = _moves([newer_without])
    assert move["last_seen"] == "2026-11-05T11:00:00.000Z"


def test_records_without_a_uid_count_one_each_and_say_so():
    (move,), _ = _moves([_ssh(), _ssh(), _ssh()])
    assert (move["connection_count"], move["records_without_uid"]) == (3, 3)
    assert move["assessment"].endswith(
        "3 records had no connection ID and are counted one each."
    )
    (move,), _ = _moves([_ssh("C1"), _ssh("C2"), _ssh()])
    assert (move["connection_count"], move["records_without_uid"]) == (3, 1)


def test_beaconing_still_reads_final_records_only():
    """One open connection is one connection; its interim records would look periodic."""
    from services.threat_detection import detect_beaconing
    from tests.fake_opensearch import FakeOpenSearch

    bodies = []

    class Recording(FakeOpenSearch):
        def search(self, index=None, body=None, **kw):
            bodies.append(body)
            return super().search(index=index, body=body, **kw)

    detect_beaconing(Recording([]), FROM, TO)
    assert bodies
    for body in bodies:
        assert CONN_ACCOUNTING in body["query"]["bool"]["filter"]
