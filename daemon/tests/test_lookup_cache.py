"""NET-192 PR 3: reverse DNS and WHOIS answer within a bound, once per IP, from a cache.

On the G11 a cold reverse lookup took 20 s (the container's resolver lost first queries),
past the web proxy's 10 s, and every visit asked again.
"""

import asyncio
import socket
import threading
import time
import types

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from api import lookup
from services.ttl_cache import TTLCache

BOUND_S = 0.3  # DNS_TIMEOUT_S in these tests (6 s on the device)
HANG_S = 10  # how long a closed fake resolver hangs


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class Resolver:
    """Answers PTR queries from `names`. While closed it hangs, like a blackholed server."""

    def __init__(self, names: dict[str, str]) -> None:
        self.names = names
        self.calls: list[tuple[str, str]] = []
        self._lock = threading.Lock()
        self.ptr_open = threading.Event()
        self.ptr_open.set()
        self.forward_open = threading.Event()
        self.forward_open.set()
        self.forward_fails = False
        self.ptr_error: Exception | None = (
            None  # raised by the next PTR query, once open
        )

    def gethostbyaddr(self, ip):
        with self._lock:
            self.calls.append(("ptr", ip))
        self.ptr_open.wait(HANG_S)
        with self._lock:
            error, self.ptr_error = self.ptr_error, None
        if error is not None:
            raise error
        if ip not in self.names:
            raise socket.herror(1, "Unknown host")
        return self.names[ip], [], [ip]

    def getaddrinfo(self, host, port):
        with self._lock:
            self.calls.append(("forward", host))
        self.forward_open.wait(HANG_S)
        if self.forward_fails:
            raise socket.gaierror(-2, "Name or service not known")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.9", 0))]

    def ptr_calls(self) -> list[str]:
        return [ip for kind, ip in self.calls if kind == "ptr"]


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(lookup, "_dns_cache", TTLCache(lookup.CACHE_SIZE, clock))
    monkeypatch.setattr(lookup, "_whois_cache", TTLCache(lookup.CACHE_SIZE, clock))
    monkeypatch.setattr(lookup, "_in_flight", {})
    monkeypatch.setattr(lookup, "DNS_TIMEOUT_S", BOUND_S)
    return clock


@pytest.fixture
def resolver(monkeypatch):
    resolver = Resolver({"8.8.8.8": "dns.google", "1.1.1.1": "one.one.one.one"})
    fake = types.SimpleNamespace(
        gethostbyaddr=resolver.gethostbyaddr,
        getaddrinfo=resolver.getaddrinfo,
        herror=socket.herror,
        gaierror=socket.gaierror,
    )
    monkeypatch.setattr(lookup, "socket", fake)
    yield resolver
    resolver.ptr_open.set()  # never leave a lookup thread stuck for the next test
    resolver.forward_open.set()


def _app() -> web.Application:
    app = web.Application()
    lookup.register_lookup_routes(app)

    async def health(_request):
        return web.json_response({"status": "ok"})

    app.router.add_get("/api/health", health)
    return app


def _run(scenario):
    """Run `scenario(client)` against the lookup routes on a fresh loop."""

    async def main():
        async with TestClient(TestServer(_app())) as client:
            return await scenario(client)

    return asyncio.run(main())


async def _json(client, path):
    resp = await client.get(path)
    return resp.status, await resp.json()


# --- cache ------------------------------------------------------------------------------------


def test_a_name_is_kept_for_an_hour(clock, resolver):
    async def scenario(client):
        first = await _json(client, "/api/lookup/dns/8.8.8.8")
        again = await _json(client, "/api/lookup/dns/8.8.8.8")
        clock.t += lookup.HIT_TTL_S - 1
        still = await _json(client, "/api/lookup/dns/8.8.8.8")
        clock.t += 2
        await _json(client, "/api/lookup/dns/8.8.8.8")
        return first, again, still

    first, again, still = _run(scenario)
    assert first == (
        200,
        {
            "ip": "8.8.8.8",
            "hostname": "dns.google",
            "aliases": [],
            "addresses": ["203.0.113.9"],
            "error": None,
            "timed_out": False,
        },
    )
    assert again == first and still == first
    assert resolver.ptr_calls() == [
        "8.8.8.8",
        "8.8.8.8",
    ]  # asked again only after the hour


def test_no_name_is_kept_for_five_minutes(clock, resolver):
    async def scenario(client):
        first = await _json(client, "/api/lookup/dns/192.0.2.1")
        clock.t += lookup.MISS_TTL_S - 1
        await _json(client, "/api/lookup/dns/192.0.2.1")
        clock.t += 2
        await _json(client, "/api/lookup/dns/192.0.2.1")
        return first

    status, body = _run(scenario)
    assert status == 200
    assert body["hostname"] is None and body["error"] == "No reverse DNS record found"
    assert body["timed_out"] is False
    assert resolver.ptr_calls() == ["192.0.2.1", "192.0.2.1"]


def test_one_lookup_per_ip_at_a_time(clock, resolver):
    resolver.ptr_open.clear()

    async def scenario(client):
        asks = [
            asyncio.create_task(_json(client, "/api/lookup/dns/8.8.8.8"))
            for _ in range(3)
        ]
        while not resolver.ptr_calls():
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)  # the other two have arrived and are waiting
        resolver.ptr_open.set()
        return await asyncio.gather(*asks)

    answers = _run(scenario)
    assert resolver.ptr_calls() == ["8.8.8.8"]
    assert all(
        status == 200 and body["hostname"] == "dns.google" for status, body in answers
    )


# --- a resolver that doesn't answer ---------------------------------------------------------


def test_a_blackholed_resolver_times_out_fast_and_health_answers(clock, resolver):
    resolver.ptr_open.clear()
    ips = ["8.8.8.8", "1.1.1.1", "9.9.9.9"]  # one more than the lookup threads

    async def scenario(client):
        started = time.monotonic()
        asks = [
            asyncio.create_task(_json(client, f"/api/lookup/dns/{ip}")) for ip in ips
        ]
        await asyncio.sleep(0.05)
        health = await client.get("/api/health")
        blocked = not any(ask.done() for ask in asks)  # health answered mid-lookup
        answers = await asyncio.gather(*asks)
        took = time.monotonic() - started

        # the resolver comes back: a new address gets its name, a timed-out one is kept 5 min
        resolver.ptr_open.set()
        await asyncio.sleep(0.05)  # the stuck lookup threads finish
        recovered = await _json(client, "/api/lookup/dns/1.1.1.1")
        clock.t += lookup.MISS_TTL_S + 1
        retried = await _json(client, "/api/lookup/dns/8.8.8.8")
        return health.status, blocked, answers, took, recovered, retried

    health_status, blocked, answers, took, recovered, retried = _run(scenario)
    assert health_status == 200 and blocked
    assert took < HANG_S / 2  # the bound answered, not the resolver
    for status, body in answers:
        assert status == 200
        assert body["hostname"] is None and body["timed_out"] is True
        assert body["error"] is None
    assert (
        recovered[1]["timed_out"] is True
    )  # 1.1.1.1 timed out a moment ago: kept 5 min
    assert retried == (
        200,
        {
            "ip": "8.8.8.8",
            "hostname": "dns.google",
            "aliases": [],
            "addresses": ["203.0.113.9"],
            "error": None,
            "timed_out": False,
        },
    )


def test_after_a_blackhole_a_new_address_resolves(clock, resolver):
    resolver.ptr_open.clear()

    async def scenario(client):
        stuck = await _json(client, "/api/lookup/dns/8.8.8.8")
        resolver.ptr_open.set()
        await asyncio.sleep(0.05)
        return stuck, await _json(client, "/api/lookup/dns/1.1.1.1")

    stuck, fresh = _run(scenario)
    assert stuck[1]["timed_out"] is True
    assert fresh[1]["hostname"] == "one.one.one.one"


def test_the_name_stands_when_the_forward_check_times_out(clock, resolver):
    resolver.forward_open.clear()

    async def scenario(client):
        t0 = time.monotonic()
        answer = await _json(client, "/api/lookup/dns/8.8.8.8")
        return answer, time.monotonic() - t0

    (status, body), took = _run(scenario)
    assert took < HANG_S / 2  # the bound answered, not the hung forward check
    assert status == 200
    assert body["hostname"] == "dns.google" and body["timed_out"] is False
    assert body["addresses"] == ["8.8.8.8"]  # the reverse answer's own addresses


def test_the_name_stands_when_the_forward_check_fails(clock, resolver):
    resolver.forward_fails = True
    status, body = _run(lambda client: _json(client, "/api/lookup/dns/8.8.8.8"))
    assert status == 200
    assert body["hostname"] == "dns.google" and body["addresses"] == ["8.8.8.8"]


def test_a_bad_address_is_a_400_and_asks_nobody(clock, resolver):
    status, body = _run(lambda client: _json(client, "/api/lookup/dns/not-an-ip"))
    assert status == 400 and "Invalid IP address" in body["error"]
    assert resolver.calls == []


# --- WHOIS --------------------------------------------------------------------------------------

WHOIS_TEXT = (
    b"NetRange: 1.1.1.0 - 1.1.1.255\nCIDR: 1.1.1.0/24\nOrgName: APNIC and Cloudflare\n"
)


class FakeWhois:
    """Stands in for asyncio.create_subprocess_exec("whois", ip); answers once `gate` opens."""

    def __init__(self) -> None:
        self.runs: list[str] = []
        self.gate: asyncio.Event | None = None
        self.killed = 0
        self.output = WHOIS_TEXT
        self.returncode = 0
        self.error: Exception | None = (
            None  # raised by the next run, once its gate opens
        )

    async def exec(self, program, ip, **_kwargs):
        assert program == "whois"
        self.runs.append(ip)
        fake = self

        class Proc:
            returncode = None  # set when the process ends, like asyncio's

            async def communicate(self):
                if fake.gate is not None:
                    await fake.gate.wait()
                error, fake.error = fake.error, None
                if error is not None:
                    raise error
                self.returncode = fake.returncode
                return fake.output, b""

            def kill(self):
                fake.killed += 1

        return Proc()


@pytest.fixture
def whois(monkeypatch):
    fake = FakeWhois()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake.exec)
    return fake


def test_whois_runs_once_per_ip_and_is_kept_a_day(clock, whois):
    async def scenario(client):
        whois.gate = asyncio.Event()
        asks = [
            asyncio.create_task(_json(client, "/api/lookup/whois/1.1.1.1"))
            for _ in range(2)
        ]
        while not whois.runs:
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        whois.gate.set()
        both = await asyncio.gather(*asks)
        clock.t += lookup.WHOIS_TTL_S - 1
        cached = await _json(client, "/api/lookup/whois/1.1.1.1")
        clock.t += 2
        await _json(client, "/api/lookup/whois/1.1.1.1")
        return both, cached

    both, cached = _run(scenario)
    assert whois.runs == ["1.1.1.1", "1.1.1.1"]  # once for the pair, again after a day
    for status, body in [*both, cached]:
        assert status == 200
        assert body["parsed"]["orgname"] == "APNIC and Cloudflare"
        assert body["parsed"]["cidr"] == "1.1.1.0/24"


def test_a_whois_timeout_is_kept_five_minutes(clock, whois, monkeypatch):
    monkeypatch.setattr(lookup, "WHOIS_TIMEOUT_S", 0.1)

    async def scenario(client):
        whois.gate = asyncio.Event()  # never opens
        first = await _json(client, "/api/lookup/whois/1.1.1.1")
        again = await _json(client, "/api/lookup/whois/1.1.1.1")
        clock.t += lookup.MISS_TTL_S + 1
        whois.gate.set()
        later = await _json(client, "/api/lookup/whois/1.1.1.1")
        return first, again, later

    first, again, later = _run(scenario)
    assert first == (
        200,
        {"ip": "1.1.1.1", "raw": "", "parsed": {}, "error": "WHOIS lookup timed out"},
    )
    assert again == first and whois.killed == 1
    assert later[1]["error"] is None
    assert whois.runs == ["1.1.1.1", "1.1.1.1"]


@pytest.mark.parametrize(
    "output, returncode",
    [
        (WHOIS_TEXT, 2),  # whois exited with an error
        (b"", 0),  # printed nothing
        (b"% connect: Connection timed out\n", 0),  # printed nothing we can read
    ],
)
def test_a_whois_that_fails_says_so_and_is_kept_five_minutes(
    clock, whois, output, returncode
):
    whois.output, whois.returncode = output, returncode

    async def scenario(client):
        first = await _json(client, "/api/lookup/whois/1.1.1.1")
        clock.t += lookup.MISS_TTL_S - 1
        await _json(client, "/api/lookup/whois/1.1.1.1")
        clock.t += 2
        await _json(client, "/api/lookup/whois/1.1.1.1")
        return first

    status, body = _run(scenario)
    assert status == 200 and body["error"] == "WHOIS lookup failed"
    assert whois.runs == [
        "1.1.1.1",
        "1.1.1.1",
    ]  # asked again after 5 minutes, not a day


def test_whois_output_is_cut_at_64_kib(clock, whois):
    whois.output = WHOIS_TEXT + b"x" * (2 * lookup.WHOIS_MAX_BYTES)
    status, body = _run(lambda client: _json(client, "/api/lookup/whois/1.1.1.1"))
    assert status == 200 and body["error"] is None
    assert len(body["raw"]) == lookup.WHOIS_MAX_BYTES == 64 * 1024
    assert body["parsed"]["orgname"] == "APNIC and Cloudflare"


def test_a_resolver_that_gives_up_is_a_timeout_not_no_record(clock, resolver):
    # glibc raises herror TRY_AGAIN (2) when RES_OPTIONS' tries run out
    resolver.ptr_error = socket.herror(2, "Host name lookup failure")
    status, body = _run(lambda client: _json(client, "/api/lookup/dns/8.8.8.8"))
    assert status == 200
    assert body["timed_out"] is True
    assert body["hostname"] is None and body["error"] is None


@pytest.mark.parametrize("kind", ["dns", "whois"])
@pytest.mark.parametrize("raw", ["::1%25%0Ax", "fe80::1%25eth0", "::1%0Ax"])
def test_an_ipv6_scope_id_is_a_400_and_asks_nobody(clock, resolver, whois, kind, raw):
    """Security review L1: ip_address keeps any scope id, newlines included (a forged log line)."""
    status, body = _run(lambda client: _json(client, f"/api/lookup/{kind}/{raw}"))
    assert status == 400 and "Invalid IP address" in body["error"]
    assert resolver.calls == [] and whois.runs == []


async def _three_asks_one_failing_lookup(client, path, started, release):
    """Three requests for one IP while its lookup is held, then the lookup is let go to fail."""
    asks = [asyncio.create_task(_json(client, path)) for _ in range(3)]
    while not started():
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)  # the other two have arrived and are waiting on it
    release()
    failed = await asyncio.gather(*asks)
    return failed, dict(lookup._in_flight), await _json(client, path)


def test_a_reverse_lookup_that_raises_is_a_500_for_every_waiter_then_runs_again(
    clock, resolver
):
    resolver.ptr_open.clear()
    resolver.ptr_error = RuntimeError("resolver crashed")
    failed, in_flight, after = _run(
        lambda client: _three_asks_one_failing_lookup(
            client,
            "/api/lookup/dns/8.8.8.8",
            resolver.ptr_calls,
            resolver.ptr_open.set,
        )
    )
    assert [status for status, _ in failed] == [500, 500, 500]
    assert in_flight == {}
    assert after[0] == 200 and after[1]["hostname"] == "dns.google"
    assert resolver.ptr_calls() == [
        "8.8.8.8",
        "8.8.8.8",
    ]  # one for the three, one after


def test_a_whois_that_raises_is_a_500_for_every_waiter_then_runs_again(clock, whois):
    whois.error = RuntimeError("whois crashed")

    async def scenario(client):
        whois.gate = asyncio.Event()
        return await _three_asks_one_failing_lookup(
            client, "/api/lookup/whois/1.1.1.1", lambda: whois.runs, whois.gate.set
        )

    failed, in_flight, after = _run(scenario)
    assert [status for status, _ in failed] == [500, 500, 500]
    assert in_flight == {}
    assert after[0] == 200 and after[1]["parsed"]["orgname"] == "APNIC and Cloudflare"
    assert whois.runs == ["1.1.1.1", "1.1.1.1"]
