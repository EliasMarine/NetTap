"""The checks behind scripts/remote/verify_protocols.py (the NET-219 device check)."""

import importlib.util
from pathlib import Path

_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "remote" / "verify_protocols.py"
)
_spec = importlib.util.spec_from_file_location("verify_protocols", _PATH)
vp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vp)


def _terms(buckets: dict, other: int = 0, error: int = 0) -> dict:
    return {
        "buckets": [{"key": k, "doc_count": n} for k, n in buckets.items()],
        "sum_other_doc_count": other,
        "doc_count_error_upper_bound": error,
    }


def _reference(**overrides) -> dict:
    ref = {
        "total": 1000,
        "quic": 40,
        "ssl": 300,
        "unknown": 200,
        "icmp": 20,
        "one_way": 120,
        "counters": 990,
        "ics": 0,
        "ics_names": {},
        "ayiya": 0,
        "terms": _terms({"ssl": 340, "unknown": 200, "dns": 400, "quic": 40}),
    }
    return {**ref, **overrides}


def _reply(**unidentified) -> dict:
    split = {"conversations": 60, "one_way": 120, "icmp": 20, **unidentified}
    return {
        "services": [
            {"name": "dns", "count": 400},
            {"name": "ssl", "count": 300},
            {"name": "unknown", "count": 200},
            {"name": "quic", "count": 40},
        ],
        "unidentified": split,
    }


def _verdicts(results: list) -> dict:
    return {label: verdict for verdict, label, _ in results}


def test_bounded_allows_growth_between_reads_only():
    assert vp.bounded(10, 10, 10)
    assert vp.bounded(10, 11, 12)
    assert not vp.bounded(10, 9, 12)
    assert not vp.bounded(10, 13, 12)
    assert not vp.bounded(10, None, 12)


def test_terms_complete_needs_both_counters_at_zero():
    assert vp.terms_complete(_terms({"dns": 1}))
    assert not vp.terms_complete(_terms({"dns": 1}, other=5))
    assert not vp.terms_complete(_terms({"dns": 1}, error=2))
    assert not vp.terms_complete({"buckets": []})  # unknown counts as incomplete


def test_partition_is_exact_inside_one_reply():
    assert vp.partition_ok({"conversations": 60, "one_way": 120, "icmp": 20}, 200)
    assert not vp.partition_ok({"conversations": 61, "one_way": 120, "icmp": 20}, 200)
    assert not vp.partition_ok({"one_way": 120, "icmp": 20}, 140)


def test_everything_passes_on_a_consistent_reply():
    results = vp.evaluate(_reference(), _reply(), _reference(), ["udp"])
    assert {v for v, _, _ in results} <= {"PASS", "INFO"}


def test_a_record_arriving_between_the_reads_passes():
    # a QUIC connection and a one-way connection indexed after the API answered
    before = _reference()
    after = _reference(
        total=1002,
        quic=41,
        unknown=201,
        one_way=121,
        counters=992,
        terms=_terms({"ssl": 341, "unknown": 201, "dns": 400, "quic": 41}),
    )
    results = vp.evaluate(before, _reply(), after, ["udp"])
    assert "FAIL" not in {v for v, _, _ in results}


def test_api_outside_the_bounds_fails():
    # the API counted a QUIC connection under ssl as well: ssl above the direct count
    reply = _reply()
    reply["services"][1] = {"name": "ssl", "count": 340}
    verdicts = _verdicts(vp.evaluate(_reference(), reply, _reference(), ["udp"]))
    assert verdicts["API services ssl (not QUIC)"] == "FAIL"


def test_a_broken_split_fails_and_a_missing_one_too():
    verdicts = _verdicts(
        vp.evaluate(_reference(), _reply(conversations=70), _reference(), ["udp"])
    )
    assert verdicts["conversations + one way + ICMP = unknown (one reply)"] == "FAIL"
    old = {"services": _reply()["services"]}  # a daemon without the split
    verdicts = _verdicts(vp.evaluate(_reference(), old, _reference(), ["udp"]))
    assert verdicts["API unidentified.icmp"] == "FAIL"
    assert verdicts["conversations + one way + ICMP = unknown (one reply)"] == "FAIL"


def test_a_truncated_terms_aggregation_is_inconclusive_not_a_failure():
    truncated = _terms({"ssl": 340, "unknown": 200, "dns": 400}, other=40)
    results = vp.evaluate(
        _reference(terms=truncated), _reply(), _reference(terms=truncated), ["udp"]
    )
    assert _verdicts(results)["other service labels"] == "INCONCLUSIVE"
    assert "FAIL" not in {v for v, _, _ in results}


def test_other_labels_are_compared_when_the_terms_read_is_complete():
    verdict, detail = vp.other_buckets(
        {"dns": 450, "quic": 40}, _terms({"dns": 400}), _terms({"dns": 420})
    )
    assert verdict == "FAIL" and detail.startswith("dns")


def test_no_quic_no_server_names_and_ics_labels_fail():
    after = _reference(quic=0, ics=3, ics_names={"bacnet": 3})
    verdicts = _verdicts(vp.evaluate(_reference(quic=0), _reply(), after, []))
    assert verdicts["QUIC conn records indexed"] == "FAIL"
    assert verdicts["server names on QUIC connections"] == "FAIL"
    assert verdicts["ICS-labelled conn records"] == "FAIL"


def test_sni_join_matches_on_addresses_and_port_not_on_transport():
    def hit(src, port, dst, transport=None):
        fields = {"source.ip": [src], "source.port": [port], "destination.ip": [dst]}
        if transport:
            fields["network.transport"] = [transport]
        return {"fields": fields}

    quic = [hit("192.168.1.5", 50000, "142.250.1.1")]
    ssl = [
        hit(
            "192.168.1.5", 50000, "142.250.1.1", "tcp"
        ),  # Malcolm's label, same connection
        hit("192.168.1.5", 50001, "142.250.1.1", "tcp"),  # a TLS connection, other port
    ]
    assert vp.sni_on_quic(quic, ssl) == ["tcp"]
    assert vp.sni_on_quic([], ssl) == []


def test_parse_reference_reads_one_search_reply():
    def count(n, **aggs):
        return {"doc_count": n, **aggs}

    reply = {
        "hits": {"total": {"value": 1000}},
        "aggregations": {
            "quic": count(40),
            "ssl": count(300),
            "unknown": count(200, icmp=count(20), one_way=count(120)),
            "counters": count(990),
            "ics": count(0, names=_terms({})),
            "ayiya": count(2),
            "terms": _terms({"dns": 400}),
        },
    }
    ref = vp.parse_reference(reply)
    assert (ref["total"], ref["unknown"], ref["one_way"], ref["ayiya"]) == (
        1000,
        200,
        120,
        2,
    )


def test_reference_counts_unidentified_with_the_api_rule(monkeypatch):
    """The device check builds the API's own unidentified split, so the two can't drift (NET-222)."""
    from api.traffic import _UNLABELLED_AGG
    from services.iot_monitor import ICMP_TRANSPORTS

    class Client:
        def search(self, index, body):
            return body

    monkeypatch.setattr(vp, "parse_reference", lambda body: body)
    unknown = vp.reference(Client(), "index", {}, ICMP_TRANSPORTS)["aggs"]["unknown"]
    assert unknown["filter"] == _UNLABELLED_AGG["filter"]
    assert unknown["aggs"] == _UNLABELLED_AGG["aggs"]
