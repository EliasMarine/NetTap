"""LAN security answers say when ARP checks had no ARP records to look at."""

import asyncio
import json
from unittest.mock import MagicMock

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from api.lan_security import NO_ARP_NOTE, handle_all_anomalies, handle_arp_spoofing
from services.lan_anomaly_detector import LANAnomalyDetector


def _get(handler, arp_records: int) -> dict:
    client = MagicMock()
    client.count.return_value = {"count": arp_records}
    client.search.return_value = {"aggregations": {"all": {"buckets": []}}}
    app = web.Application()
    app["lan_anomaly_detector"] = LANAnomalyDetector(client=client)
    resp = asyncio.run(handler(make_mocked_request("GET", "/api/lan/x", app=app)))
    assert resp.status == 200, resp.text
    return json.loads(resp.text)


def test_no_arp_records_reads_not_checked_not_none_found():
    """The G11 records no ARP: "0 ARP spoofing alerts" there meant nothing was looked at."""
    for handler in (handle_arp_spoofing, handle_all_anomalies):
        body = _get(handler, arp_records=0)
        assert body["count"] == 0
        assert body["arp_recorded"] is False
        assert body["note"] == NO_ARP_NOTE


def test_with_arp_records_a_zero_is_a_real_zero():
    for handler in (handle_arp_spoofing, handle_all_anomalies):
        body = _get(handler, arp_records=12)
        assert body["arp_recorded"] is True
        assert "note" not in body


def test_the_arp_count_reads_zeek_arp_records_in_the_range():
    client = MagicMock()
    client.count.return_value = {"count": 0}
    assert LANAnomalyDetector(client=client).arp_recorded("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z") is False
    flt = client.count.call_args.kwargs["body"]["query"]["bool"]["filter"]
    assert {"term": {"event.dataset": "arp"}} in flt and {"term": {"event.provider": "zeek"}} in flt
