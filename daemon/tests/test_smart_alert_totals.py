"""#96: the smart alert summary counts every (signature, source, destination) group.

Composite pages come in key order, so a cap on pages drops the signatures that sort last:
25 pages of 200 left "ET TROJAN" out of a network with 5,000 "ET POLICY" groups.
"""

from unittest.mock import MagicMock, patch

from services import alert_intelligence
from services.alert_intelligence import get_smart_alert_summary

_FROM, _TO = "2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z"


def _group(sig: str, n: int) -> dict:
    return {
        "key": {
            "sig_name": sig,
            "src_ip": "192.168.1.10",
            "dst_ip": f"10.{n // 65536}.{n // 256 % 256}.{n % 256}",
        },
        "doc_count": 3,
        "first_seen": {"value_as_string": "2026-11-01T01:00:00Z"},
        "last_seen": {"value_as_string": "2026-11-01T02:00:00Z"},
        "sample": {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "alert": {
                                "signature": sig,
                                "signature_id": 1,
                                "severity": 2,
                            }
                        }
                    }
                ]
            }
        },
    }


def _client(groups: list[dict]) -> MagicMock:
    """Answers each composite page with as many groups as it asks for, after the last one."""

    def search(index, body):
        comp = body["aggs"]["grouped"]["composite"]
        start = comp.get("after", {}).get("n", -1) + 1
        page = groups[start : start + comp["size"]]
        grouped: dict = {"buckets": page}
        if page:
            grouped["after_key"] = {"n": start + len(page) - 1}
        return {"aggregations": {"grouped": grouped}}

    client = MagicMock()
    client.search.side_effect = search
    return client


def test_summary_counts_the_signatures_that_sort_last():
    groups = [_group("ET POLICY Outdated Browser", n) for n in range(5_000)] + [
        _group("ET TROJAN Zeus Checkin", n) for n in range(200)
    ]
    with (
        patch.object(alert_intelligence, "is_suppressed", return_value=False),
        patch.object(alert_intelligence, "update_baseline", return_value=None),
    ):
        summary = get_smart_alert_summary(_client(groups), _FROM, _TO)

    assert summary["total_groups"] == 5_200
    assert summary["total_events"] == 15_600
    assert summary["categories"]["malware_c2"] == {
        "label": "Malware & C2",
        "groups": 200,
        "events": 600,
    }
    assert summary["threat_level"] == "critical"


def test_the_sample_fetches_only_the_fields_it_reads():
    client = _client([])
    alert_intelligence.get_smart_alerts(client, _FROM, _TO)
    top_hits = client.search.call_args.kwargs["body"]["aggs"]["grouped"]["aggs"][
        "sample"
    ]["top_hits"]
    assert "alert" in top_hits["_source"] and "suricata.alert" in top_hits["_source"]
