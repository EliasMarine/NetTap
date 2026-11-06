"""S5: one aggregate health status — a known failure is a problem, an unknown check is incomplete."""

import asyncio
import json
from unittest.mock import MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from api.server import handle_system_health


def _health(smart_healthy, opensearch_up=True, storage_ok=True) -> dict:
    app = web.Application()
    app["start_time"] = 0.0
    app["storage"] = MagicMock()
    if storage_ok:
        app["storage"].get_status.return_value = {"disk_usage_percent": 10.0}
    else:
        app["storage"].get_status.side_effect = OSError("disk unreadable")
    if not opensearch_up:
        app["storage"]._client.info.side_effect = ConnectionError("down")
    app["smart"] = MagicMock()
    app["smart"].get_status.return_value = {"healthy": smart_healthy}
    req = make_mocked_request("GET", "/api/system/health", app=app)
    return json.loads(asyncio.run(handle_system_health(req)).body)


@pytest.mark.parametrize(
    ("smart", "opensearch_up", "storage_ok", "status", "healthy"),
    [
        (True, True, True, "healthy", True),
        # an unreadable drive beside healthy checks: incomplete, never "Degraded"
        (None, True, True, "incomplete", None),
        (True, True, False, "incomplete", None),
        # a known failure wins over an unknown check
        (None, False, True, "problem", False),
        (False, True, True, "problem", False),
        (False, True, False, "problem", False),
    ],
)
def test_aggregate_status_precedence(smart, opensearch_up, storage_ok, status, healthy):
    body = _health(smart, opensearch_up, storage_ok)
    assert (body["status"], body["healthy"]) == (status, healthy)
