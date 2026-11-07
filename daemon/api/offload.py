"""Run a blocking route handler in a worker thread, so the request loop stays free (PR 2).

The OpenSearch client, file walks and subprocess calls block. On the loop, one slow call
stalled every other request and /api/health with it.
"""

import asyncio
import functools
from concurrent.futures import ThreadPoolExecutor

from aiohttp import web

# Route work gets its own threads. On asyncio's default pool (8 threads on the N100) a cold
# Home load (~14 jobs of 6-14 s) queued ahead of the drill-downs, the certificate pass, the
# bridge and Internet health checks and aiohttp's own name lookups, which stay on that pool.
_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="route")


async def run_blocking(fn, *args):
    """Run ``fn(*args)`` on the route pool and wait for it."""
    return await asyncio.get_running_loop().run_in_executor(_POOL, fn, *args)


def in_thread(handler):
    """Make a sync ``def handler(request)`` an aiohttp handler that runs on the route pool.

    The handler may read the query, match info and ``request.app``; it must not read the
    body (that needs the loop) or touch loop-only objects.
    """

    @functools.wraps(handler)
    async def run(request):
        return await run_blocking(handler, request)

    return run


# The IP and MAC lookups are public (no login, NET-193), so they get two threads of their own
# and at most two more waiting; past that a lookup is turned away at once, before it queues
# behind (or holds up) anything else.
_LOOKUP_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="lookup")
_LOOKUP_SLOTS = asyncio.Semaphore(4)
LOOKUPS_BUSY = "Lookups are busy. Try again in a moment."


def lookup_slot(handler):
    """Admit at most 4 lookups at a time (2 running, 2 waiting); answer 503 past that."""

    @functools.wraps(handler)
    async def run(request):
        if _LOOKUP_SLOTS.locked():  # checked first, so acquiring below never waits
            return web.json_response({"error": LOOKUPS_BUSY}, status=503)
        async with _LOOKUP_SLOTS:
            return await handler(request)

    return run


async def run_lookup(fn, *args):
    """Run ``fn(*args)`` on the lookup pool and wait for it."""
    return await asyncio.get_running_loop().run_in_executor(_LOOKUP_POOL, fn, *args)
