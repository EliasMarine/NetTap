"""5xx replies without internals (api/error_replies.py, release audit B-p, NET-229 follow-up).

Covers: an unmarked 5xx built from an exception becomes the generic line plus its scalar fields and
is logged; a reply marked with public_json passes untouched; 4xx and non-JSON pass untouched; an
unhandled exception is a logged JSON 500; HTTP exceptions pass; the real create_app() wiring for a
storage, a packets, a rule-update and a notification-test failure; and guards that every
hand-written 5xx in daemon/api is marked and no marked reply carries a caught exception's text.
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
from api.error_replies import GENERIC, public_json, safe_error_middleware
from services.packet_manifest import PacketError

from tests.test_daemon_auth import _make_full_app

API_DIR = pathlib.Path(__file__).resolve().parent.parent / "api"
LEAK = "ConnectionError(<HTTPSConnection>: [Errno 111]) https://localhost:9200/_search"


async def _exception_text(request):
    return web.json_response(
        {
            "error": f"OpenSearch query failed: {LEAK}",
            "detail": LEAK,
            "available": False,
            "count": 3,
        },
        status=502,
    )


async def _public(request):
    return public_json(
        {"error": "The test didn't go through: Bad (HTTP 500).", "results": [1]},
        status=502,
    )


async def _client_error(request):
    return web.json_response({"error": "Invalid ip: 'x'", "detail": "kept"}, status=400)


async def _plain_text(request):
    return web.Response(text=LEAK, status=500)


async def _raises(request):
    raise RuntimeError(LEAK)


async def _not_found(request):
    raise web.HTTPNotFound(text="no such thing")


class TestSafeErrorMiddleware(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application(middlewares=[safe_error_middleware])
        for name, handler in {
            "exc": _exception_text,
            "public": _public,
            "client": _client_error,
            "text": _plain_text,
            "raises": _raises,
            "missing": _not_found,
        }.items():
            app.router.add_get(f"/{name}", handler)
        return app

    async def test_exception_text_is_generic_with_scalars_and_logged(self):
        with self.assertLogs("nettap.api", level="WARNING") as logs:
            resp = await self.client.get("/exc")
        self.assertEqual(resp.status, 502)
        self.assertEqual(
            await resp.json(), {"available": False, "count": 3, "error": GENERIC}
        )
        self.assertIn("Errno 111", logs.output[0])
        self.assertIn("/exc", logs.output[0])

    async def test_public_reply_passes_untouched(self):
        resp = await self.client.get("/public")
        self.assertEqual(resp.status, 502)
        self.assertEqual(
            await resp.json(),
            {"error": "The test didn't go through: Bad (HTTP 500).", "results": [1]},
        )

    async def test_4xx_and_non_json_untouched(self):
        resp = await self.client.get("/client")
        self.assertEqual(
            (resp.status, await resp.json()),
            (400, {"error": "Invalid ip: 'x'", "detail": "kept"}),
        )
        resp = await self.client.get("/text")
        self.assertEqual((resp.status, await resp.text()), (500, LEAK))

    async def test_unhandled_exception_is_a_logged_json_500(self):
        with self.assertLogs("nettap.api", level="ERROR") as logs:
            resp = await self.client.get("/raises")
        self.assertEqual(resp.status, 500)
        self.assertEqual(await resp.json(), {"error": GENERIC})
        self.assertIn("Errno 111", "\n".join(logs.output))

    async def test_http_exceptions_pass(self):
        resp = await self.client.get("/missing")
        self.assertEqual((resp.status, await resp.text()), (404, "no such thing"))


class TestRealAppReplies(AioHTTPTestCase):
    """create_app() runs the middleware: real handlers' 5xx bodies reach the client as intended."""

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

    async def test_system_health_200_hides_the_storage_exception(self):
        boom = ConnectionError("HTTPSConnectionPool(host='localhost', port=9200)")
        self.app["smart"].get_status.side_effect = OSError("/dev/private-nvme0: busy")
        with patch.object(self.app["storage"], "get_status", side_effect=boom):
            resp = await self.client.get("/api/system/health", headers=self._headers())
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["storage"], {"error": "Storage status couldn't be read."})
        self.assertEqual(body["smart"], {"error": "Drive health couldn't be read."})
        self.assertNotIn("port=9200", json.dumps(body))

    async def test_packets_502_keeps_its_message_and_drops_stderr_detail(self):
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

    async def test_rule_update_oserror_shows_the_reason_not_the_path(self):
        oserror = OSError(2, "No such file or directory", "/opt/private/bin/docker")
        with patch(
            "services.suricata_rules.asyncio.create_subprocess_exec",
            AsyncMock(side_effect=oserror),
        ):
            resp = await self.client.post(
                "/api/suricata/rules/update", headers=self._headers()
            )
        self.assertEqual(resp.status, 500)
        text = await resp.text()
        self.assertIn("No such file or directory", json.loads(text)["output"])
        self.assertNotIn("/opt/private", text)

    async def test_notification_test_502_names_the_failed_channel(self):
        hub = self.app["notification_hub"]
        hub._config_path = pathlib.Path(self._tmp.name, "notifications.json")
        hub._env_file = os.path.join(self._tmp.name, ".env")
        hub.configure("webhook", {"url": "https://hooks.example.net/b", "name": "Bad"})
        with patch("services.notification_hub._post", return_value="HTTP 500"):
            resp = await self.client.post(
                "/api/notifications/test", headers=self._headers()
            )
        self.assertEqual(resp.status, 502)
        body = await resp.json()
        self.assertEqual(body["error"], "The test didn't go through: Bad (HTTP 500).")
        self.assertEqual([r["ok"] for r in body["results"]], [False])


# --- Guards over daemon/api --------------------------------------------------------------------

# Exceptions whose text NetTap writes for the owner (it may reach the reply)
CURATED = {
    "OwnerRulesError",
    "EtProError",
    "QueryFailed",
    "PacketError",
    "DnsReconBusyError",
    "LiveBandwidthBusyError",
}
PUBLIC_CALLS = {"public_json", "json_error", "_error"}


def _string_constants(tree: ast.Module) -> set[str]:
    """Module-level NAME = "text", and NAME = {"error": "text", ...} (a whole reply)."""
    return {
        node.targets[0].id
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and (
            (isinstance(node.value, ast.Constant) and isinstance(node.value.value, str))
            or (
                isinstance(node.value, ast.Dict)
                and _error_value_of(node.value) is not None
            )
        )
    }


def _call_name(node: ast.Call) -> str:
    return getattr(node.func, "attr", None) or getattr(node.func, "id", "")


def _status(node: ast.Call):
    status = next((k.value for k in node.keywords if k.arg == "status"), None)
    if _call_name(node) in ("json_error", "_error") and len(node.args) > 1:
        status = node.args[1]
    return status.value if isinstance(status, ast.Constant) else None


def _error_value_of(body: ast.Dict):
    return next(
        (
            v
            for k, v in zip(body.keys, body.values)
            if isinstance(k, ast.Constant) and k.value == "error"
        ),
        None,
    )


def _error_value(node: ast.Call):
    """The reply's "error": from a dict literal, or a module constant holding a whole reply."""
    if node.args and isinstance(node.args[0], ast.Dict):
        return _error_value_of(node.args[0])
    if node.args and isinstance(node.args[0], ast.Name):
        return node.args[0]
    return None


def _unmarked_hand_written_5xx() -> list[tuple[str, int]]:
    """web.json_response({"error": <literal or constant>}, status=5xx): the middleware hides it."""
    found = []
    for path in sorted(API_DIR.glob("*.py")):
        if path.name == "error_replies.py":  # the middleware's own GENERIC reply
            continue
        tree = ast.parse(path.read_text())
        consts = _string_constants(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and _call_name(node) == "json_response"):
                continue
            status, message = _status(node), _error_value(node)
            if not (isinstance(status, int) and status >= 500):
                continue
            if (
                isinstance(message, ast.Constant) and isinstance(message.value, str)
            ) or (isinstance(message, ast.Name) and message.id in consts):
                found.append((path.name, node.lineno))
    return found


def _uses_name(node: ast.AST, name: str) -> bool:
    """{name} in an f-string, str(name) or repr(name) anywhere under node."""
    for sub in ast.walk(node):
        if (
            isinstance(sub, ast.FormattedValue)
            and isinstance(sub.value, ast.Name)
            and sub.value.id == name
        ):
            return True
        if (
            isinstance(sub, ast.Call)
            and getattr(sub.func, "id", "") in ("str", "repr")
            and sub.args
            and isinstance(sub.args[0], ast.Name)
            and sub.args[0].id == name
        ):
            return True
    return False


def _handler_types(handler: ast.ExceptHandler) -> set[str]:
    kinds = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return {getattr(k, "id", None) or getattr(k, "attr", "") for k in kinds if k}


def _public_replies_with_exception_text() -> list[tuple[str, int]]:
    """A 5xx (or computed-status) public reply inside `except X as exc` that shows exc, unless
    X is curated. A 4xx shows validation text on purpose."""
    found = []
    for path in sorted(API_DIR.glob("*.py")):
        for handler in ast.walk(ast.parse(path.read_text())):
            if not (isinstance(handler, ast.ExceptHandler) and handler.name):
                continue
            if _handler_types(handler) <= CURATED:
                continue
            for node in ast.walk(ast.Module(body=handler.body, type_ignores=[])):
                if (
                    isinstance(node, ast.Call)
                    and _call_name(node) in PUBLIC_CALLS
                    and not (isinstance(_status(node), int) and _status(node) < 500)
                    and _uses_name(node, handler.name)
                ):
                    found.append((path.name, node.lineno))
    return found


def _curated_5xx_sent_unmarked() -> list[tuple[str, int]]:
    """web.json_response(..., status=5xx) inside `except <curated> as exc`: its text is written
    for the owner, but unmarked the middleware turns it into GENERIC."""
    found = []
    for path in sorted(API_DIR.glob("*.py")):
        for handler in ast.walk(ast.parse(path.read_text())):
            if not (
                isinstance(handler, ast.ExceptHandler)
                and handler.name
                and _handler_types(handler) & CURATED
            ):
                continue
            for node in ast.walk(ast.Module(body=handler.body, type_ignores=[])):
                if (
                    isinstance(node, ast.Call)
                    and _call_name(node) == "json_response"
                    and isinstance(_status(node), int)
                    and _status(node) >= 500
                ):
                    found.append((path.name, node.lineno))
    return found


def test_curated_exceptions_are_marked_public():
    assert not _curated_5xx_sent_unmarked(), "use api.error_replies.public_json"


def test_every_hand_written_5xx_is_marked_public():
    """A plain-English 5xx sent with web.json_response reaches users as GENERIC."""
    assert not _unmarked_hand_written_5xx(), "use api.error_replies.public_json"


def test_no_public_reply_shows_a_caught_exception():
    """public_json skips the middleware, so exception text in it would reach the browser."""
    assert not _public_replies_with_exception_text()


def test_the_guards_find_what_they_check():
    sample = ast.parse(
        "from aiohttp import web\n"
        "def f():\n"
        "    try:\n"
        "        pass\n"
        "    except OSError as exc:\n"
        "        public_json({'error': f'failed: {exc}'}, status=500)\n"
        "    return web.json_response({'error': 'Plain words.'}, status=503)\n"
    )
    handler = next(n for n in ast.walk(sample) if isinstance(n, ast.ExceptHandler))
    call = next(n for n in ast.walk(handler) if isinstance(n, ast.Call))
    assert _uses_name(call, "exc")
    last = sample.body[1].body[-1].value
    assert _status(last) == 503
    assert isinstance(_error_value(last), ast.Constant)
