"""Excluded IPs tidy device views only; they must never hide search results,
investigation alerts or LAN detections (an excluded router IP would otherwise
hide ARP spoofing of the router)."""

import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api import lan_security  # noqa: E402
from api.search import handle_search  # noqa: E402
from services.investigation import generate_threat_report  # noqa: E402
from services.nl_search import NLSearchParser  # noqa: E402

EXCLUDED = "192.168.1.50"


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["", "?q=connections+from+10.0.0.1"])
async def test_log_search_does_not_filter_excluded_ips(query):
    storage = MagicMock()
    storage._client.search.return_value = {"hits": {"hits": [], "total": {"value": 0}}}
    app = web.Application()
    app["storage"] = storage
    app["nl_search_parser"] = NLSearchParser()
    app["excluded_ips"] = [EXCLUDED]

    resp = await handle_search(
        make_mocked_request("GET", f"/api/search{query}", app=app)
    )

    assert resp.status == 200
    body = storage._client.search.call_args.kwargs["body"]
    assert EXCLUDED not in json.dumps(body)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler, method",
    [
        (lan_security.handle_all_anomalies, "get_all_anomalies"),
        (lan_security.handle_arp_spoofing, "detect_arp_spoofing"),
        (lan_security.handle_rogue_dhcp, "detect_rogue_dhcp"),
    ],
)
async def test_lan_detections_ignore_excluded_ips(handler, method):
    detector = MagicMock()
    getattr(detector, method).return_value = []
    app = web.Application()
    app["lan_anomaly_detector"] = detector
    app["excluded_ips"] = [EXCLUDED]

    resp = await handler(make_mocked_request("GET", "/api/lan/x", app=app))

    assert resp.status == 200
    call = getattr(detector, method).call_args
    assert "excluded_ips" not in call.kwargs
    assert EXCLUDED not in json.dumps([str(a) for a in call.args])


@pytest.mark.asyncio
async def test_threat_report_alerts_ignore_excluded_ips():
    smart_alerts = AsyncMock(return_value=[])
    summary = AsyncMock(return_value={})
    with (
        patch("services.alert_intelligence.get_smart_alerts", smart_alerts),
        patch("services.alert_intelligence.get_smart_alert_summary", summary),
        patch("services.threat_detection.detect_beaconing", return_value=[]),
        patch("services.threat_detection.detect_lateral_movement", return_value=[]),
        patch("services.threat_detection.analyze_dns_anomalies", return_value={}),
    ):
        await generate_threat_report(MagicMock(), "now-1h", "now", [EXCLUDED])

    for mock in (smart_alerts, summary):
        assert mock.call_args.kwargs.get("excluded_ips") is None
