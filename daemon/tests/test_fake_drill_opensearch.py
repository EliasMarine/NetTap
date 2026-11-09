"""The evaluator fake's own checks (NET-160 slice 2b-1): each piece the alert list, smart
alerts, traffic summary and log search lean on, against answers worked out by hand."""

import pytest

from tests.fake_drill_opensearch import (
    DrillOpenSearch,
    aggregate,
    alert,
    matches,
    nested,
)

INDEX = "arkime_sessions3-*"
INDEX_NAME = "arkime_sessions3-261105"


def _docs():
    return [
        {"_id": "a", "@timestamp": "2026-11-05T10:00:00Z", "source.ip": "10.0.0.1"},
        {"_id": "b", "@timestamp": "2026-11-05T12:00:00Z", "source.ip": "10.0.0.2"},
        {"_id": "c", "@timestamp": "2026-11-05T11:00:00Z", "source.ip": "10.0.0.1"},
        {"_id": "d", "@timestamp": "2026-11-05T09:00:00Z"},
    ]


def _ids(reply):
    return [h["_id"] for h in reply["hits"]["hits"]]


def test_a_search_without_a_snapshot_names_its_index_and_reads_the_documents_now():
    client = DrillOpenSearch(_docs())
    with pytest.raises(AssertionError):
        client.search(body={"query": {"match_all": {}}})
    client.docs.append({"_id": "e", "@timestamp": "2026-11-05T08:00:00Z"})
    reply = client.search(index=INDEX, body={"size": 0, "track_total_hits": True})
    assert reply["hits"]["total"] == {"value": 5, "relation": "eq"}
    assert "pit_id" not in reply


def test_hits_follow_sort_from_and_size_with_the_total_of_every_match():
    client = DrillOpenSearch(_docs())
    body = {
        "query": {"exists": {"field": "@timestamp"}},
        "sort": [{"@timestamp": {"order": "desc"}}],
        "from": 1,
        "size": 2,
        "track_total_hits": True,
    }
    reply = client.search(index=INDEX, body=body)
    # newest first: b (12:00), c (11:00), a (10:00), d (09:00); page 2 of size 2 skips b
    assert _ids(reply) == ["c", "a"]
    assert reply["hits"]["total"]["value"] == 4
    # the default size is 10, and a field's missing values sort last both ways
    up = client.search(index=INDEX, body={"sort": [{"source.ip": {"order": "asc"}}]})
    down = client.search(index=INDEX, body={"sort": [{"source.ip": {"order": "desc"}}]})
    assert _ids(up) == ["a", "c", "b", "d"]
    assert _ids(down) == ["b", "a", "c", "d"]


def test_a_hit_is_its_document_nested_without_the_id_and_projected():
    client = DrillOpenSearch([alert("10.0.0.1", "8.8.8.8", rule="R", _id="x")])
    whole = client.search(index=INDEX, body={})["hits"]["hits"][0]
    assert whole["_id"] == "x"
    assert whole["_source"] == {
        "@timestamp": "2026-11-05T10:00:00.000Z",
        "event": {"provider": "suricata", "dataset": "alert"},
        "rule": {"name": "R"},
        "source": {"ip": "10.0.0.1"},
        "destination": {"ip": "8.8.8.8"},
    }
    only = client.search(index=INDEX, body={"_source": ["rule", "source.ip"]})
    assert only["hits"]["hits"][0]["_source"] == {
        "rule": {"name": "R"},
        "source": {"ip": "10.0.0.1"},
    }
    assert nested({"a.b.c": 1, "a.d": 2}) == {"a": {"b": {"c": 1}, "d": 2}}


def test_top_hits_takes_its_size_sort_and_source_per_bucket():
    newest = {
        "top_hits": {
            "size": 1,
            "sort": [{"@timestamp": {"order": "desc"}}],
            "_source": ["@timestamp"],
        }
    }
    composite = {
        "composite": {
            "size": 10,
            "sources": [{"src": {"terms": {"field": "source.ip"}}}],
        },
        "aggs": {"newest": newest, "default": {"top_hits": {}}},
    }
    buckets = aggregate(_docs(), {"g": composite})["g"]["buckets"]
    # 10.0.0.1 holds a (10:00) and c (11:00); 10.0.0.2 holds b; d has no source.ip
    assert [
        (
            b["key"]["src"],
            b["newest"]["hits"]["total"]["value"],
            b["newest"]["hits"]["hits"],
        )
        for b in buckets
    ] == [
        (
            "10.0.0.1",
            2,
            [
                {
                    "_id": "c",
                    "_index": INDEX_NAME,
                    "_source": {"@timestamp": "2026-11-05T11:00:00Z"},
                }
            ],
        ),
        (
            "10.0.0.2",
            1,
            [
                {
                    "_id": "b",
                    "_index": INDEX_NAME,
                    "_source": {"@timestamp": "2026-11-05T12:00:00Z"},
                }
            ],
        ),
    ]
    # OpenSearch's default size is 3, with the whole document
    three = aggregate(_docs(), {"t": {"top_hits": {}}})["t"]["hits"]["hits"]
    assert [h["_id"] for h in three] == ["a", "b", "c"]
    assert three[0]["_source"] == {
        "@timestamp": "2026-11-05T10:00:00Z",
        "source": {"ip": "10.0.0.1"},
    }


def test_match_none_matches_nothing():
    client = DrillOpenSearch(_docs())
    reply = client.search(
        index=INDEX, body={"query": {"match_none": {}}, "track_total_hits": True}
    )
    assert reply["hits"]["total"]["value"] == 0
    assert _ids(reply) == []


def test_a_term_with_a_slash_is_text_unless_it_is_a_cidr():
    rule = {"rule.name": "ET MALWARE Win32/Foo CnC", "source.ip": "10.0.0.1"}
    assert matches(rule, {"term": {"rule.name": "ET MALWARE Win32/Foo CnC"}})
    assert not matches(rule, {"term": {"rule.name": "ET MALWARE Win32/Bar CnC"}})
    assert matches(rule, {"term": {"source.ip": "10.0.0.0/24"}})
    assert not matches(rule, {"term": {"source.ip": "10.0.1.0/24"}})


def test_a_wildcard_folds_case_only_when_asked():
    doc = {"rule.name": "ET POLICY Password in Cleartext"}
    assert matches(doc, {"wildcard": {"rule.name": "*Cleartext*"}})
    assert not matches(doc, {"wildcard": {"rule.name": "*cleartext*"}})
    folded = {"value": "*cleartext*", "case_insensitive": True}
    assert matches(doc, {"wildcard": {"rule.name": folded}})


def test_missing_buckets_the_documents_without_the_field():
    reply = aggregate(_docs(), {"m": {"missing": {"field": "source.ip"}}})
    assert reply["m"]["doc_count"] == 1
