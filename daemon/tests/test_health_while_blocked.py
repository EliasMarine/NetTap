"""PR 2 (reliability): a slow route never holds up /api/health or any other request.

The real app (create_app) runs on its own loop in a thread. For each route that was moved
off the request loop, the route's blocking step (an OpenSearch call, a file walk, the SMTP
connect) waits on a threading.Event; while it waits, GET /api/health must answer within
200 ms. A handler that still blocks the request loop can't answer health at all, so on
main these fail (health times out). Only the first blocking call of a request waits.
"""

import asyncio
import contextlib
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

import pytest
from aiohttp import web

from api.daemon_auth import TOKEN_HEADER

HEALTH_BUDGET_S = 0.2
_WAIT_S = 5


class Blocker:
    """The first call after arm() waits until the health probe has run."""

    def __init__(self) -> None:
        self._armed = False
        self._lock = threading.Lock()
        self.entered = threading.Event()
        self.release = threading.Event()

    def arm(self) -> None:
        self.entered.clear()
        self.release.clear()
        self._armed = True

    def disarm(self) -> None:
        self._armed = False
        self.release.set()

    def returning(self, make):
        """A stand-in for a blocking call; it answers make() (a fresh reply each time)."""

        def call(*_args, **_kwargs):
            with self._lock:
                first = self._armed and not self.entered.is_set()
                if first:
                    self.entered.set()
            if first:
                self.release.wait(_WAIT_S)
            return make()

        return call


def _client(blocker: Blocker) -> MagicMock:
    client = MagicMock()
    for method, make in {
        "search": dict,
        "count": lambda: {"count": 0},
        "msearch": lambda: {"responses": []},
        "mget": lambda: {"docs": []},
        "get": lambda: {"found": False},
    }.items():
        getattr(client, method).side_effect = blocker.returning(make)
    client.cat.indices.side_effect = blocker.returning(list)
    return client


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """The real app on 127.0.0.1, served from a loop in its own thread."""
    from api import alerts as alerts_api
    from api.server import create_app
    from services import alert_intelligence, threat_intel
    from services.pcap_search import PcapSearchService
    from services.tshark_service import TSharkService
    from storage.manager import RetentionConfig, StorageManager

    tmp = tmp_path_factory.mktemp("daemon")
    blocker = Blocker()
    with pytest.MonkeyPatch.context() as mp:
        # nothing the routes write lands outside the test's directory
        mp.setattr(alert_intelligence, "_SUPPRESS_PATH", tmp / "suppress.json")
        mp.setattr(alert_intelligence, "_BASELINE_PATH", tmp / "baselines.json")
        mp.setattr(threat_intel, "_TI_CACHE_PATH", tmp / "ti.json")
        mp.setattr(alerts_api, "_ACK_FILE", str(tmp / "acks.json"))
        # the file walks block like a slow disk
        mp.setattr(PcapSearchService, "get_available_pcaps", blocker.returning(list))
        mp.setattr(TSharkService, "list_pcap_files", blocker.returning(list))
        for name, value in {
            "DAEMON_TOKEN_FILE": str(tmp / "auth" / "daemon-token"),
            "EXCLUDED_IPS_FILE": str(tmp / "excluded_ips.json"),
            "NOTIFICATION_CONFIG": str(tmp / "notifications.json"),
            "PCAP_DIR": str(tmp / "pcap"),
            "GEOIP_DB_PATH": str(tmp / "no.mmdb"),
        }.items():
            mp.setenv(name, value)

        with patch.object(
            StorageManager, "_create_client", return_value=_client(blocker)
        ):
            storage = StorageManager(
                RetentionConfig(check_path=str(tmp)), "http://os:9200"
            )
        with patch("api.server.detect_appliance_ip", return_value=None):
            app = create_app(storage, MagicMock(), "http://os:9200")
        app["notification_hub"].configure(
            "email", {"id": "mail", "smtp_host": "smtp.test", "recipients": ["a@b.c"]}
        )

        loop = asyncio.new_event_loop()
        runner = web.AppRunner(app)
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()

        async def start() -> str:
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            host, port = runner.addresses[0][:2]
            return f"http://{host}:{port}"

        base = asyncio.run_coroutine_threadsafe(start(), loop).result(_WAIT_S)
        with open(tmp / "auth" / "daemon-token") as f:
            token = f.read().strip()
        yield {"base": base, "token": token, "blocker": blocker}

        blocker.disarm()
        asyncio.run_coroutine_threadsafe(runner.cleanup(), loop).result(_WAIT_S)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(_WAIT_S)


def _health_seconds(base: str) -> float:
    start = time.monotonic()
    try:
        with urllib.request.urlopen(f"{base}/api/health", timeout=1.0) as resp:
            resp.read()
    except OSError:
        return float("inf")  # no answer: the request loop is held
    return time.monotonic() - start


def _health_while_blocked(server, method: str, path: str) -> float:
    """Health's answer time while `path` waits in its blocking step."""
    blocker: Blocker = server["blocker"]
    blocker.arm()
    request = urllib.request.Request(
        f"{server['base']}{path}",
        method=method,
        headers={TOKEN_HEADER: server["token"]},
        data=b"{}" if method == "POST" else None,
    )

    def send():
        try:
            urllib.request.urlopen(request, timeout=10).read()
        except OSError:
            pass  # the status doesn't matter, only that health answered meanwhile

    sender = threading.Thread(target=send)
    sender.start()
    try:
        assert blocker.entered.wait(_WAIT_S), f"{path} never reached its blocking step"
        return _health_seconds(server["base"])
    finally:
        blocker.disarm()
        sender.join(10)


# (method, path, patches applied for this route only: target -> value)
_IP = "192.168.1.66"
_ROUTES = [
    ("GET", "/api/storage/status", {}),
    ("GET", "/api/storage/retention", {}),
    # run_cycle was already in a thread; its get_status() wasn't
    (
        "POST",
        "/api/storage/prune",
        {"storage.manager.StorageManager.run_cycle": MagicMock()},
    ),
    ("GET", "/api/traffic/summary", {}),
    ("GET", "/api/traffic/top-talkers", {}),
    ("GET", "/api/traffic/top-destinations", {}),
    ("GET", "/api/traffic/protocols", {}),
    ("GET", "/api/traffic/bandwidth", {}),
    ("GET", "/api/traffic/connections", {}),
    ("GET", "/api/traffic/connections/sankey", {}),
    ("GET", f"/api/traffic/connections/timeline?src_ip={_IP}&dst_ip=1.1.1.1", {}),
    ("GET", f"/api/traffic/connections/related?src_ip={_IP}&dst_ip=1.1.1.1", {}),
    ("GET", "/api/traffic/categories", {}),
    ("GET", "/api/traffic/categories/streaming", {}),
    ("GET", "/api/traffic/categories/streaming/bandwidth", {}),
    ("GET", "/api/alerts", {}),
    ("GET", "/api/alerts/count", {}),
    ("GET", "/api/alerts/timeline", {}),
    ("GET", "/api/alerts/top-signatures", {}),
    ("GET", "/api/alerts/top-ips", {}),
    ("GET", "/api/alerts/categories", {}),
    ("GET", "/api/alerts/categories/exploit", {}),
    ("GET", "/api/alerts/categories/exploit/timeline", {}),
    ("GET", "/api/alerts/smart", {}),
    ("GET", "/api/alerts/smart/summary", {}),
    ("GET", "/api/alerts/some-alert-id", {}),
    # the device read was already in a thread; the alert counts after it weren't
    (
        "GET",
        "/api/devices",
        {"api.devices._lan_device_buckets": MagicMock(return_value=[{"key": _IP}])},
    ),
    ("GET", f"/api/devices/{_IP}", {}),
    ("GET", f"/api/devices/{_IP}/connections", {}),
    ("GET", f"/api/devices/{_IP}/categories", {}),
    ("GET", f"/api/devices/{_IP}/alerts", {}),
    ("GET", f"/api/devices/{_IP}/ports", {}),
    ("GET", f"/api/risk/scores/{_IP}", {}),
    ("GET", "/api/dns/top-domains", {}),
    ("GET", f"/api/dns/device/{_IP}", {}),
    ("GET", "/api/dns/nxdomain", {}),
    ("GET", "/api/dns/types", {}),
    ("GET", "/api/dns/timeline?interval=1h", {}),
    ("GET", "/api/dns/suspicious", {}),
    ("GET", "/api/dns/stats", {}),
    ("GET", "/api/threats/lateral", {}),
    ("GET", "/api/threats/dns-anomalies", {}),
    ("GET", "/api/threats/intel", {}),
    ("GET", "/api/lan/anomalies", {}),
    ("GET", "/api/lan/arp-spoofing", {}),
    ("GET", "/api/lan/rogue-dhcp", {}),
    ("GET", "/api/search?q=dns+traffic", {}),
    ("GET", "/api/live/connections", {}),
    # the fetches were already in a thread; the GeoIP fallback after them wasn't
    (
        "GET",
        "/api/live/dashboard?device=x",
        {
            "services.live_connections.LiveConnectionTracker.fetch_dashboard_data": MagicMock(
                return_value={"connections": [{"dest_ip": "9.9.9.1"}]}
            )
        },
    ),
    (
        "GET",
        "/api/live/connection/detail?src=192.168.1.66&dst=9.9.9.2",
        {
            "services.live_connections.LiveConnectionTracker.fetch_connection_detail": MagicMock(
                return_value={"geo": {"ip": "9.9.9.2"}}
            )
        },
    ),
    ("GET", "/api/geoip/9.9.9.3", {}),
    ("GET", "/api/geoip/batch?ips=9.9.9.4", {}),
    ("GET", "/api/tools/mac-lookup/fc:ff:01:00:00:01", {}),
    ("GET", "/api/devices/registry", {}),
    ("GET", "/api/devices/registry/search?q=phone", {}),
    ("GET", "/api/devices/registry/new-count", {}),
    ("GET", "/api/devices/registry/aa:bb:cc:dd:ee:ff", {}),
    ("GET", "/api/devices/registry/aa:bb:cc:dd:ee:ff/traffic", {}),
    ("GET", "/api/bandwidth/monthly", {}),
    ("GET", "/api/bandwidth/daily", {}),
    ("GET", "/api/bandwidth/devices", {}),
    ("GET", "/api/bandwidth/heatmap", {}),
    ("GET", "/api/bandwidth/cap", {}),
    ("GET", "/api/mac/randomized", {}),
    ("GET", "/api/mac/fingerprint/aa:bb:cc:dd:ee:ff", {}),
    ("GET", "/api/mac/merge-suggestions", {}),
    ("GET", "/api/changelog", {}),
    ("GET", "/api/pcap/files", {}),
    ("GET", "/api/pcap/search?filter=dns", {}),
    ("GET", "/api/pcap/download?filter=dns", {}),
    ("GET", "/api/tshark/pcaps", {}),
]


@pytest.mark.parametrize(
    "method,path,patches", _ROUTES, ids=[f"{m} {p}" for m, p, _ in _ROUTES]
)
def test_health_answers_while_a_route_waits(server, method, path, patches):
    with contextlib.ExitStack() as stack:
        for target, value in patches.items():
            stack.enter_context(patch(target, value))
        seconds = _health_while_blocked(server, method, path)
    assert seconds < HEALTH_BUDGET_S, f"/api/health took {seconds:.2f} s"


def test_health_answers_while_an_smtp_server_hangs(server):
    """Both the channel test and real alerts send through this path."""
    blocker: Blocker = server["blocker"]
    smtp = MagicMock(side_effect=blocker.returning(MagicMock))
    with patch("services.notification_hub.smtplib.SMTP", smtp):
        seconds = _health_while_blocked(
            server, "POST", "/api/notifications/channels/mail/test"
        )
    assert seconds < HEALTH_BUDGET_S, f"/api/health took {seconds:.2f} s"
    assert smtp.call_args.kwargs["timeout"] == 10  # a dead server gives up


def test_the_smart_check_leaves_the_loop_free():
    """smart_loop ran nvme/smartctl (up to 30 s) on the request loop."""
    from main import smart_loop

    loop_ran = threading.Event()
    waited: list[bool] = []
    smart = MagicMock()
    smart.check_health.side_effect = lambda: waited.append(loop_ran.wait(1))

    async def main():
        shutdown = asyncio.Event()
        task = asyncio.create_task(smart_loop(smart, 3600, shutdown))
        await asyncio.sleep(
            0.05
        )  # reached while the check runs only if it left the loop
        loop_ran.set()
        shutdown.set()
        await asyncio.wait_for(task, _WAIT_S)

    asyncio.run(main())
    assert waited == [True]


def test_a_full_route_pool_leaves_the_default_pool_free():
    """PR #200 review: routes shared asyncio's default pool (8 threads on the N100) with the
    drill-downs, the certificate pass and the health checks, which then queued behind them."""
    from concurrent.futures import ThreadPoolExecutor

    from api.offload import in_thread

    release = threading.Event()
    slow_route = in_thread(lambda _request: release.wait(_WAIT_S))

    async def main():
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=8))  # as on the N100
        routes = [asyncio.ensure_future(slow_route(None)) for _ in range(8)]
        try:
            # a drill-down or health check on the default pool doesn't queue behind them
            return await asyncio.wait_for(asyncio.to_thread(lambda: "ran"), 1)
        finally:
            release.set()
            await asyncio.gather(*routes)

    assert asyncio.run(main()) == "ran"


def _get(server, path: str) -> tuple[int, dict, float]:
    """(status, JSON body, seconds) for one authenticated GET."""
    request = urllib.request.Request(
        f"{server['base']}{path}", headers={TOKEN_HEADER: server["token"]}
    )
    start = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            status, body = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        status, body = exc.code, exc.read()
    return status, json.loads(body), time.monotonic() - start


def test_a_fifth_public_lookup_is_turned_away_at_once(server):
    """PR #200 review: the public lookups (no login) ran uncapped on the shared pool."""
    from api import offload

    release = threading.Event()
    running: list[str] = []

    def slow_reverse_dns(ip):
        running.append(ip)
        release.wait(_WAIT_S)
        raise socket.herror("no record")

    answers: list[int] = []

    def look_up(n: int) -> None:
        answers.append(_get(server, f"/api/lookup/dns/9.9.8.{n}")[0])

    with patch("api.lookup.socket.gethostbyaddr", slow_reverse_dns):
        senders = [threading.Thread(target=look_up, args=(n,)) for n in range(4)]
        for t in senders:
            t.start()
        try:
            deadline = time.monotonic() + _WAIT_S
            while not (len(running) == 2 and offload._LOOKUP_SLOTS.locked()):
                assert time.monotonic() < deadline, "the lookups never filled up"
                time.sleep(0.01)

            status, body, seconds = _get(server, "/api/lookup/dns/9.9.8.9")
            assert (status, body) == (503, {"error": offload.LOOKUPS_BUSY})
            assert seconds < 1
            assert _get(server, "/api/tools/mac-lookup/fc:ff:01:00:00:02")[0] == 503
            # everything else still answers: health, and a route on the route pool
            assert _health_seconds(server["base"]) < HEALTH_BUDGET_S
            assert _get(server, "/api/dns/stats")[0] == 200
            assert len(running) == 2  # two run, two wait
        finally:
            release.set()
            for t in senders:
                t.join(_WAIT_S)
    assert answers == [200] * 4
