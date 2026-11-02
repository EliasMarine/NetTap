"""/devices "New (24h)" counts devices NetTap first saw in the period, not every device in it."""

import asyncio
import json
from unittest.mock import MagicMock

from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from opensearchpy import OpenSearchException

from api.devices_v2 import handle_registry_new_count
from services.device_registry import DeviceRegistry


def _get(query: str, client: MagicMock) -> tuple[int, dict]:
    registry = DeviceRegistry.__new__(DeviceRegistry)
    registry._client = client
    app = web.Application()
    app["device_registry"] = registry
    resp = asyncio.run(handle_registry_new_count(make_mocked_request("GET", "/api/devices/registry/new-count" + query, app=app)))
    return resp.status, json.loads(resp.text)


def test_counts_devices_first_seen_since():
    client = MagicMock()
    client.count.return_value = {"count": 3}
    status, body = _get("?since=2026-11-01T21:00:00Z", client)
    assert (status, body["count"], body["since"]) == (200, 3, "2026-11-01T21:00:00+00:00")
    assert client.count.call_args.kwargs["body"] == {"query": {"range": {"first_seen": {"gte": "2026-11-01T21:00:00+00:00"}}}}


def test_a_bad_since_is_a_400():
    assert _get("?since=yesterday", MagicMock())[0] == 400


def test_a_failed_count_is_an_error_not_zero():
    client = MagicMock()
    client.count.side_effect = OpenSearchException("down")
    status, body = _get("", client)
    assert status == 502 and "error" in body
