"""Smart alerts read every composite page (dashboard accuracy #19).

One 200-group page saw only the first 200 (signature, src, dst) groups in key
order, so the home Alert Summary said 394 while the Alerts card said 2.2K.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import alert_intelligence
from services.alert_intelligence import get_smart_alert_summary, get_smart_alerts

_FROM, _TO = "2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z"


@pytest.fixture(autouse=True)
def _pages_of_200(monkeypatch):
    """The fake pages below hold 200 groups; a shorter page than asked for ends the paging."""
    monkeypatch.setattr(alert_intelligence, "_GROUP_PAGE_SIZE", 200)


def _bucket(n: int) -> dict:
    sig = f"ET POLICY Test signature {n:04d}"
    return {
        "key": {
            "sig_name": sig,
            "src_ip": "192.168.1.10",
            "dst_ip": f"8.8.{n // 250}.{n % 250}",
        },
        "doc_count": 2,
        "first_seen": {"value_as_string": "2026-11-01T01:00:00Z"},
        "last_seen": {"value_as_string": "2026-11-01T02:00:00Z"},
        "sample": {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "alert": {
                                "signature": sig,
                                "signature_id": 2000000 + n,
                                "severity": 2,
                                "category": "Potential Corporate Privacy Violation",
                            },
                            "destination": {"port": 443},
                        }
                    }
                ]
            }
        },
    }


def _page(buckets: list[dict], after: dict | None) -> dict:
    grouped: dict = {"buckets": buckets}
    if after:
        grouped["after_key"] = after
    return {"aggregations": {"grouped": grouped}}


def _two_page_client() -> MagicMock:
    client = MagicMock()
    client.search.side_effect = [
        _page(
            [_bucket(n) for n in range(200)],
            {"sig_name": "x", "src_ip": "y", "dst_ip": "z"},
        ),
        _page([_bucket(n) for n in range(200, 203)], None),
    ]
    return client


def test_every_page_is_read():
    client = _two_page_client()
    with patch.object(alert_intelligence, "is_suppressed", return_value=False):
        groups = asyncio.run(
            get_smart_alerts(client, _FROM, _TO, limit=None, include_info=True)
        )

    assert len(groups) == 203
    first, second = (c.kwargs["body"] for c in client.search.call_args_list)
    assert "after" not in first["aggs"]["grouped"]["composite"]
    assert second["aggs"]["grouped"]["composite"]["after"] == {
        "sig_name": "x",
        "src_ip": "y",
        "dst_ip": "z",
    }


def test_summary_totals_cover_every_group():
    client = _two_page_client()
    with (
        patch.object(alert_intelligence, "is_suppressed", return_value=False),
        patch.object(alert_intelligence, "update_baseline", return_value=None),
        patch.object(alert_intelligence, "reclassify_severity", return_value=3),
    ):
        summary = asyncio.run(get_smart_alert_summary(client, _FROM, _TO))

    assert summary["total_groups"] == 203
    assert summary["total_events"] == 406


def test_a_device_summary_has_no_network_baseline():
    """#95: one device's alerts were compared with, and added to, the network's history."""
    client = _two_page_client()
    with (
        patch.object(alert_intelligence, "is_suppressed", return_value=False),
        patch.object(alert_intelligence, "update_baseline") as update,
        patch.object(alert_intelligence, "reclassify_severity", return_value=3),
    ):
        summary = asyncio.run(
            get_smart_alert_summary(client, _FROM, _TO, "192.168.1.44")
        )
    update.assert_not_called()
    assert summary["baseline"] is None


def test_first_page_failure_raises():
    """#96: it returned [], and the summary read threat level "none" with 0 events."""
    client = MagicMock()
    client.search.side_effect = RuntimeError("opensearch down")
    with pytest.raises(RuntimeError):
        asyncio.run(get_smart_alerts(client, _FROM, _TO))
    with pytest.raises(RuntimeError):
        asyncio.run(get_smart_alert_summary(client, _FROM, _TO))


def test_later_page_failure_raises():
    """#96: it kept the pages read so far, so totals read low with no sign of it."""
    client = MagicMock()
    client.search.side_effect = [
        _page([_bucket(n) for n in range(1_000)], {"sig_name": "x"}),
        RuntimeError("timeout"),
    ]
    with (
        patch.object(alert_intelligence, "is_suppressed", return_value=False),
        pytest.raises(RuntimeError),
    ):
        asyncio.run(get_smart_alerts(client, _FROM, _TO, limit=None, include_info=True))


def test_summary_reports_the_informational_alerts_it_hides():
    """The home card read "394 total" next to "2.2K alerts" with no hint why."""
    client = _two_page_client()

    def every_other_is_info(signature, *_args):
        return 5 if int(signature[-4:]) % 2 == 0 else 3

    with (
        patch.object(alert_intelligence, "is_suppressed", return_value=False),
        patch.object(alert_intelligence, "update_baseline", return_value=None),
        patch.object(
            alert_intelligence, "reclassify_severity", side_effect=every_other_is_info
        ),
    ):
        summary = asyncio.run(get_smart_alert_summary(client, _FROM, _TO))

    # 203 groups of 2 events: 102 even (informational), 101 odd
    assert summary["total_groups"] == 101
    assert summary["total_events"] == 202
    assert summary["informational_events"] == 204
    assert all(t["severity"] < 5 for t in summary["top_threats"])


def test_engine_events_are_left_out_like_the_alerts_page():
    """SURICATA decoder/stream events are not alerts on the Alerts page either."""
    from api.alerts import _SURICATA_NOISE_EXCLUSION

    client = MagicMock()
    client.search.return_value = _page([], None)
    asyncio.run(get_smart_alerts(client, _FROM, _TO))
    must_not = client.search.call_args.kwargs["body"]["query"]["bool"]["must_not"]
    for clause in _SURICATA_NOISE_EXCLUSION:
        assert clause in must_not


def test_threat_level_never_exceeds_the_worst_alert():
    """Many medium alerts can push the score to 100, but that is not 'critical'."""
    from services.alert_intelligence import _cap_level

    assert _cap_level("critical", 3) == "medium"
    assert _cap_level("critical", 2) == "high"
    assert _cap_level("critical", 1) == "critical"
    assert _cap_level("low", 1) == "low"


def test_summary_level_capped_for_medium_only_alerts():
    client = _two_page_client()
    with (
        patch.object(alert_intelligence, "is_suppressed", return_value=False),
        patch.object(alert_intelligence, "update_baseline", return_value=None),
        patch.object(alert_intelligence, "reclassify_severity", return_value=3),
    ):
        summary = asyncio.run(get_smart_alert_summary(client, _FROM, _TO))

    assert summary["threat_score"] == 100  # 203 medium groups
    assert summary["threat_level"] == "medium"


# ---------------------------------------------------------------------------
# NET-164: every rule the page's "how it's worked out" sentence states
# ---------------------------------------------------------------------------


def _score(severities, anomalous=False):
    """The summary's score and level for one alert group per severity given."""
    groups = [
        {"severity": s, "count": 1, "category": "policy", "signature": f"sig {i}"}
        for i, s in enumerate(severities)
    ]
    baseline = {"is_anomalous": anomalous} if anomalous else None
    with (
        patch.object(
            alert_intelligence, "get_smart_alerts", AsyncMock(return_value=groups)
        ),
        patch.object(alert_intelligence, "update_baseline", return_value=baseline),
        patch.object(alert_intelligence, "detect_kill_chains", return_value=[]),
    ):
        summary = asyncio.run(get_smart_alert_summary(object(), _FROM, _TO))
    return summary["threat_score"], summary["threat_level"]


def test_threat_score_weights_round_down():
    assert _score([4])[0] == 0  # one low group is 0.5, rounded down
    assert _score([4, 4])[0] == 1
    assert _score([1, 2, 3])[0] == 17  # 10 + 5 + 2


def test_threat_score_caps_at_100():
    assert _score([1] * 11)[0] == 100


def test_busier_than_usual_adds_15_only_under_75():
    # 7 critical + 2 medium = 74 before the bonus; 7 critical + 1 high = 75
    assert _score([1] * 7 + [3, 3], anomalous=True)[0] == 89
    assert _score([1] * 7 + [2], anomalous=True)[0] == 75
    assert _score([1] * 7 + [3, 3])[0] == 74


def test_level_never_exceeds_the_worst_alert():
    # 38 medium groups score 76, which alone would read "critical"
    assert _score([3] * 38) == (76, "medium")
