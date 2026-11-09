"""5xx replies without internals (api/error_replies.py, release audit B-p, NET-229).

Covers: exception text, Docker stderr and unknown plain-English exceptions become the generic line
on a 5xx and are logged; non-scalar fields (``detail``, ``output``, nested objects) are dropped; the
hand-written messages pass; 4xx and non-JSON pass untouched; the real create_app() wiring for a
storage, a packets and a Suricata rule-update failure; and a guard that every hand-written 5xx
message in daemon/api is on the allowlist.
"""

import ast
import json
import os
import pathlib
import tempfile
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.daemon_auth import TOKEN_HEADER
from api.error_replies import GENERIC, PLAIN_5XX, is_plain, safe_error_middleware
from services.packet_manifest import PacketError

from tests.test_daemon_auth import _make_full_app

API_DIR = pathlib.Path(__file__).resolve().parent.parent / "api"

# Each (status, body) is answered at /r/<index>
REPLIES = [
    (
        502,
        {
            "error": "OpenSearch query failed: ConnectionError(<urllib3.connection.HTTPSConnection object>: [Errno 111] Connection refused) https://localhost:9200/_search"
        },
    ),
    (500, {"error": "Error response from daemon: No such container: nettap-tshark"}),
    (500, {"error": "The thing broke"}),  # plain English, but not a known message
    (
        502,
        {
            "error": "The search failed.",
            "detail": "tshark: /pcap/x.pcap appears to be damaged",
        },
    ),
    (
        500,
        {
            "success": False,
            "output": "Could not start the rule update: [Errno 2]",
            "available": False,
            "count": 3,
            "status": {"reason": "x"},
        },
    ),
    (502, {"error": "The alert search was incomplete", "available": False}),
    (
        502,
        {
            "error": "Couldn't look up your WAN location: the lookup service didn't answer within 6 seconds. Enter the coordinates by hand."
        },
    ),
    (
        502,
        {
            "error": "Couldn't look up your WAN location: invalid literal for int() with base 10: 'x'. Enter the coordinates by hand."
        },
    ),
    (
        400,
        {"error": "Invalid ip: 'x' at https://example.net", "detail": "kept on a 4xx"},
    ),
    (500, None),  # plain text, not JSON
]


def _handler(index: int):
    status, body = REPLIES[index]

    async def handle(request: web.Request) -> web.Response:
        if body is None:
            return web.Response(
                text="ConnectionError at https://localhost:9200", status=status
            )
        return web.json_response(body, status=status)

    return handle


class TestSafeErrorMiddleware(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application(middlewares=[safe_error_middleware])
        for i in range(len(REPLIES)):
            app.router.add_get(f"/r/{i}", _handler(i))
        return app

    async def _get(self, index: int):
        resp = await self.client.get(f"/r/{index}")
        return resp.status, await resp.text()

    async def test_exception_text_is_generic_and_logged(self):
        with self.assertLogs("nettap.api", level="WARNING") as logs:
            status, text = await self._get(0)
        self.assertEqual(status, 502)
        self.assertEqual(json.loads(text), {"error": GENERIC})
        self.assertIn("Errno 111", logs.output[0])
        self.assertIn("/r/0", logs.output[0])

    async def test_docker_stderr_and_unknown_plain_messages_are_generic(self):
        for index in (1, 2):
            status, text = await self._get(index)
            self.assertEqual(json.loads(text), {"error": GENERIC})
            self.assertNotIn("nettap-tshark", text)

    async def test_detail_is_dropped_and_known_message_kept(self):
        _, text = await self._get(3)
        self.assertEqual(json.loads(text), {"error": "The search failed."})

    async def test_only_scalar_fields_survive(self):
        status, text = await self._get(4)
        self.assertEqual(status, 500)
        self.assertEqual(
            json.loads(text),
            {"success": False, "available": False, "count": 3, "error": GENERIC},
        )

    async def test_known_messages_and_template_pass(self):
        for index in (5, 6):
            _, text = await self._get(index)
            self.assertEqual(json.loads(text), REPLIES[index][1])

    async def test_template_refuses_other_text(self):
        _, text = await self._get(7)
        self.assertEqual(json.loads(text), {"error": GENERIC})

    async def test_4xx_and_non_json_untouched(self):
        status, text = await self._get(8)
        self.assertEqual((status, json.loads(text)), (400, REPLIES[8][1]))
        status, text = await self._get(9)
        self.assertEqual(
            (status, text), (500, "ConnectionError at https://localhost:9200")
        )


class TestRealAppReplies(AioHTTPTestCase):
    """create_app() runs the middleware: real handlers' 5xx bodies reach the client cut."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self._tmp.cleanup()

    async def get_application(self):
        return _make_full_app(self._tmp.name)

    def _headers(self) -> dict:
        with open(os.path.join(self._tmp.name, "auth", "daemon-token")) as f:
            return {TOKEN_HEADER: f.read()}

    async def test_storage_status_500_hides_the_exception(self):
        boom = ConnectionError(
            "HTTPSConnectionPool(host='localhost', port=9200): refused"
        )
        with patch.object(self.app["storage"], "get_status", side_effect=boom):
            resp = await self.client.get("/api/storage/status", headers=self._headers())
        self.assertEqual(resp.status, 500)
        self.assertEqual(await resp.json(), {"error": GENERIC})

    async def test_packets_502_drops_stderr_detail(self):
        failure = PacketError(
            502, "The search failed.", detail="tshark: /pcap/a.pcap: cut short"
        )
        service = self.app["packet_search"]
        with (
            patch.object(service, "fields", AsyncMock(side_effect=failure)),
            self.assertLogs("nettap.api", level="WARNING") as logs,
        ):
            resp = await self.client.get("/api/packets/fields", headers=self._headers())
        self.assertEqual(resp.status, 502)
        text = await resp.text()
        self.assertEqual(json.loads(text), {"error": "The search failed."})
        self.assertNotIn("/pcap/a.pcap", text)
        self.assertTrue(any("/pcap/a.pcap" in line for line in logs.output))

    async def test_geoip_lookup_failure_keeps_its_message(self):
        """NET-237: the plain lookup-failed message was cut to GENERIC on its way out."""
        from api.geoip import LOOKUP_FAILED
        from services.geoip_service import GeoLookupFailed

        with patch.object(
            self.app["geoip"], "lookup", side_effect=GeoLookupFailed("timed out")
        ):
            resp = await self.client.get("/api/geoip/8.8.4.4", headers=self._headers())
        self.assertEqual(resp.status, 502)
        self.assertEqual(await resp.json(), LOOKUP_FAILED)

    async def test_rule_update_oserror_reaches_no_client(self):
        oserror = OSError(2, "No such file or directory", "/usr/bin/docker")
        with patch(
            "services.suricata_rules.asyncio.create_subprocess_exec",
            AsyncMock(side_effect=oserror),
        ):
            resp = await self.client.post(
                "/api/suricata/rules/update", headers=self._headers()
            )
        self.assertEqual(resp.status, 500)
        text = await resp.text()
        self.assertNotIn("No such file", text)
        self.assertNotIn("output", json.loads(text))
        self.assertEqual(json.loads(text)["error"], GENERIC)


def _string_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level NAME = "text" (and parenthesised implicit concatenations)."""
    found = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            found[node.targets[0].id] = node.value.value
    return found


def _hand_written_5xx_messages() -> set[tuple[str, int, str]]:
    """Every json_response({"error": <text>}, status=5xx) and json_error/_error(<text>, 5xx) in daemon/api."""
    found = set()
    for path in sorted(API_DIR.glob("*.py")):
        tree = ast.parse(path.read_text())
        consts = _string_constants(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", "")
            status = next((k.value for k in node.keywords if k.arg == "status"), None)
            if name in ("json_error", "_error") and len(node.args) > 1:
                status, message = node.args[1], node.args[0]
            elif (
                name == "json_response"
                and node.args
                and isinstance(node.args[0], ast.Dict)
            ):
                body = node.args[0]
                message = next(
                    (
                        v
                        for k, v in zip(body.keys, body.values)
                        if isinstance(k, ast.Constant) and k.value == "error"
                    ),
                    None,
                )
            else:
                continue
            if not (
                isinstance(status, ast.Constant)
                and isinstance(status.value, int)
                and status.value >= 500
            ):
                continue
            if isinstance(message, ast.Constant) and isinstance(message.value, str):
                found.add((path.name, node.lineno, message.value))
            elif isinstance(message, ast.Name) and message.id in consts:
                found.add((path.name, node.lineno, consts[message.id]))
    return found


def test_every_hand_written_5xx_message_is_allowed():
    """A new plain-English 5xx message must join PLAIN_5XX, or it reaches users as GENERIC."""
    missing = sorted(m for m in _hand_written_5xx_messages() if not is_plain(m[2]))
    assert not missing, f"add these to api/error_replies.py PLAIN_5XX: {missing}"


def test_the_guard_finds_the_messages_it_checks():
    messages = {m[2] for m in _hand_written_5xx_messages()}
    assert "The alert search was incomplete" in messages
    assert "Couldn't save the change: the device's storage failed." in messages
    assert len(PLAIN_5XX) > len(messages) > 10
