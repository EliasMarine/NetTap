"""NETTAP_QUERY_TIMING=1: one INFO line per OpenSearch request (NET-192 PR 3, measurement).

Every daemon client takes its settings from StorageManager._client_kwargs, so the transport
there is the one place every request passes, whichever client or service sends it. Wall time
includes the transport's own retries (connection errors, 502/503/504); an exact-terms re-send
(storage/exact_terms.py) is a request of its own, so it logs its own line under the same caller.
"""

import logging
import os
import sys
import time

import opensearchpy
from opensearchpy import Transport

logger = logging.getLogger("nettap.query_timing")

PREFIX = "query-timing"
# Frames to skip when naming the caller: opensearch-py itself and the daemon's storage plumbing
_PLUMBING = tuple(
    os.path.dirname(os.path.abspath(f)) + os.sep
    for f in (opensearchpy.__file__, __file__)
)


def enabled() -> bool:
    return os.environ.get("NETTAP_QUERY_TIMING", "0") == "1"


def _caller() -> str:
    """'module.function:line' of the first frame outside the plumbing (where the query is built)."""
    frame = sys._getframe(2)
    while frame is not None and frame.f_code.co_filename.startswith(_PLUMBING):
        frame = frame.f_back
    if frame is None:
        return "?"
    module = os.path.splitext(os.path.basename(frame.f_code.co_filename))[0]
    return f"{module}.{frame.f_code.co_name}:{frame.f_lineno}"


def _target(url: str) -> tuple[str, str]:
    """(index, endpoint) of a request path. Other segments (document ids) are never logged."""
    parts = url.split("?", 1)[0].strip("/").split("/")
    index = parts[0] if parts and not parts[0].startswith("_") else "-"
    endpoint = "/".join(p for p in parts if p.startswith("_")) or "/"
    return index, endpoint


class TimedTransport(Transport):
    """A Transport that logs each request's caller, OpenSearch's `took` and the wall time."""

    def perform_request(self, method, url, *args, **kwargs):
        # *args: opensearch-py 2.x and 3.x order the remaining parameters differently
        caller = _caller()
        index, endpoint = _target(url)
        started = time.perf_counter()
        outcome, took = "error", "-"
        try:
            reply = super().perform_request(method, url, *args, **kwargs)
            outcome = "ok"
            if isinstance(reply, dict) and "took" in reply:
                took = reply["took"]
            return reply
        finally:
            logger.info(
                "%s caller=%s %s %s index=%s took_ms=%s wall_ms=%d outcome=%s",
                PREFIX,
                caller,
                method,
                endpoint,
                index,
                took,
                (time.perf_counter() - started) * 1000,
                outcome,
            )
