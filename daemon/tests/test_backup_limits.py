"""NET-344: the four layers a backup restore crosses agree on one 16 MiB limit.

nginx (16m) and adapter-node (BODY_SIZE_LIMIT 16M) accept a body of exactly 16 MiB. aiohttp
up to 3.13 refuses a body >= client_max_size and 3.14 refuses one > it, so only a body under
16 MiB restores on every version, and RESTORE_LIMIT_BYTES names that bound: an export always
stays under it. The files are read as text, from the repo this test sits in.
"""

import re
from pathlib import Path

from api.server import MAX_REQUEST_BYTES
from services.config_backup import RESTORE_LIMIT_BYTES

REPO = Path(__file__).resolve().parents[2]
NGINX = (REPO / "docker" / "nginx.conf").read_text()
COMPOSE = (REPO / "docker" / "docker-compose.yml").read_text()


def location(header: str) -> str:
    """The body of the nginx block opened by `header {`, comments stripped."""
    text = re.sub(r"#[^\n]*", "", NGINX)
    start = text.index(header + " {") + len(header) + 2
    depth, end = 1, start
    while depth:
        depth += {"{": 1, "}": -1}.get(text[end], 0)
        end += 1
    return text[start : end - 1]


def directive(block: str, name: str) -> list[str]:
    return re.findall(rf"^\s*{name}\s+([^;\s]+);", block, re.MULTILINE)


def test_daemon_cutoff_is_the_restore_limit() -> None:
    assert MAX_REQUEST_BYTES == RESTORE_LIMIT_BYTES == 16 * 1024 * 1024


def test_nginx_backup_location_takes_16m_and_waits_300s() -> None:
    block = location(r"location ~ ^/api/backup/(import|validate)$")
    assert directive(block, "client_max_body_size") == ["16m"]
    # the web app's import budget is 290 s (SLOW_PATH_TIMEOUT_MS['/api/backup/import'])
    assert directive(block, "proxy_read_timeout") == ["300s"]


def test_nginx_general_location_stays_1m() -> None:
    assert directive(location("location /"), "client_max_body_size") == ["1m"]


def test_compose_web_body_size_limit_is_16m() -> None:
    services = re.split(r"^  (\S+):\s*$", COMPOSE, flags=re.MULTILINE)
    web = services[services.index("nettap-web") + 1]
    assert re.findall(r'^\s*BODY_SIZE_LIMIT:\s*"([^"]*)"', web, re.MULTILINE) == ["16M"]
