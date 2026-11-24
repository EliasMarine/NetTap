"""NET-361: the HTTPS server speaks HTTP/2, on an nginx build that has the 2026 HTTP/2 fixes.

Over HTTP/1.1 the browser opens at most six connections to NetTap for all tabs together, and each
tab's notification stream holds one for good, so with a few tabs open every other request waited in
the browser (QA 2026-11-23: an investigation create sat 41.5 s before it was sent). nginx up to
1.30.6 / 1.31.8 has CVE-2026-123007 and CVE-2026-123633 in its HTTP/2 code, so the image must be a
pinned patch release past them: compose never re-pulls a cached floating tag.
"""

import re

from tests.test_backup_limits import COMPOSE, NGINX


def test_https_server_turns_on_http2() -> None:
    text = re.sub(r"#[^\n]*", "", NGINX)
    # among the 443 server's own directives: after its listen line, before any nested block
    assert re.search(r"listen\s+443\s+ssl\b[^{}]*?^\s*http2\s+on;", text, re.MULTILINE)


def test_nginx_image_is_a_patch_release_with_the_http2_fixes() -> None:
    services = re.split(r"^  (\S+):\s*$", COMPOSE, flags=re.MULTILINE)
    block = services[services.index("nettap-nginx") + 1]
    (tag,) = re.findall(r"^\s*image:\s*nginx:(\S+)\s*$", block, re.MULTILINE)
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)-alpine", tag)
    assert match, f"nginx:{tag} is not a pinned patch release"
    version = tuple(int(part) for part in match.groups())
    fixed = (1, 30, 7) if version[:2] == (1, 30) else (1, 31, 9)
    assert version >= fixed, f"nginx {tag} predates the HTTP/2 fixes ({fixed})"
