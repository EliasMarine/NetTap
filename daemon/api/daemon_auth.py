"""
NetTap Daemon API — shared-token authentication.

The daemon runs with ``network_mode: host`` so it can reach LAN devices such
as the UniFi controller, which means port 8880 is reachable from the whole
LAN and from every host-networked container. Every request must therefore
carry the token in ``X-NetTap-Daemon-Token``.

The token lives in the ``daemon-auth`` volume, which only the daemon (rw)
and the web container (ro) mount. The daemon creates it on first start.
The only exemption is ``GET /api/health`` for the compose healthcheck.
There is deliberately no loopback exemption: the host-networked capture
containers parse attacker-controlled traffic and also see loopback.
"""

import hmac
import logging
import os
import secrets
import time
from collections.abc import Awaitable, Callable

from aiohttp import web

logger = logging.getLogger("nettap.api.auth")

TOKEN_HEADER = "X-NetTap-Daemon-Token"
DEFAULT_TOKEN_FILE = "/run/nettap-auth/daemon-token"

# Rejections are logged at most once per source IP per interval.
_REJECT_LOG_INTERVAL = 60.0
_REJECT_LOG_MAX_IPS = 1024

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]
Middleware = Callable[[web.Request, Handler], Awaitable[web.StreamResponse]]


def load_or_create_token(path: str = DEFAULT_TOKEN_FILE) -> str:
    """Return the token stored at *path*, creating it on first start.

    The file is 0644 inside a 0755 directory so the web container's
    non-root ``nettap`` user can read it through its read-only mount.

    Raises:
        OSError: If the token can be neither read nor created.
    """
    try:
        with open(path, encoding="utf-8") as f:
            existing = f.read().strip()
        if existing:
            return existing
    except FileNotFoundError:
        pass

    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    os.chmod(directory, 0o755)

    token = secrets.token_urlsafe(32)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(token)
    os.chmod(tmp_path, 0o644)
    # Atomic rename: the web container never sees a half-written token.
    os.replace(tmp_path, path)
    logger.info("Created daemon API token at %s", path)
    return token


def _is_exempt(request: web.Request) -> bool:
    return request.method == "GET" and request.path == "/api/health"


def _token_matches(presented: str, expected: str | None) -> bool:
    if not expected or not presented:
        return False
    return hmac.compare_digest(
        presented.encode("utf-8", "surrogateescape"),
        expected.encode("utf-8"),
    )


def make_auth_middleware(token: str | None) -> Middleware:
    """Build the middleware that rejects requests without the shared token.

    A ``None`` token (the file could not be read or created) rejects every
    request except the health check, so a provisioning failure fails closed.
    """
    last_logged: dict[str, float] = {}

    def log_rejection(request: web.Request) -> None:
        now = time.monotonic()
        source = request.remote or "unknown"
        if now - last_logged.get(source, float("-inf")) < _REJECT_LOG_INTERVAL:
            return
        if len(last_logged) >= _REJECT_LOG_MAX_IPS:
            last_logged.clear()  # bounds memory; a flood from many IPs just logs more
        last_logged[source] = now
        # Never log the presented header value: it may be a near-miss token.
        logger.warning(
            "Rejected unauthenticated daemon API request from %s: %s %s",
            source,
            request.method,
            request.path,
        )

    @web.middleware
    async def daemon_auth_middleware(
        request: web.Request, handler: Handler
    ) -> web.StreamResponse:
        if _is_exempt(request) or _token_matches(
            request.headers.get(TOKEN_HEADER, ""), token
        ):
            return await handler(request)
        log_rejection(request)
        return web.json_response({"error": "Unauthorized"}, status=401)

    return daemon_auth_middleware
