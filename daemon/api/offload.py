"""Run a blocking route handler in a worker thread, so the request loop stays free (PR 2).

The OpenSearch client, file walks and subprocess calls block. On the loop, one slow call
stalled every other request and /api/health with it.
"""

import asyncio
import functools


def in_thread(handler):
    """Make a sync ``def handler(request)`` an aiohttp handler that runs in a worker thread.

    The handler may read the query, match info and ``request.app``; it must not read the
    body (that needs the loop) or touch loop-only objects.
    """

    @functools.wraps(handler)
    async def run(request):
        return await asyncio.to_thread(handler, request)

    return run
