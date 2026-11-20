"""NET-330 deploy check: quiet hours hold data cap warnings overnight and release them once.

Runs inside a throwaway copy of the just-built daemon image (deploy-quiet-hours.sh):
    docker run --rm -i --network none --entrypoint python3 <image id> - < verify_quiet_hours.py
No mounts and no network, so nothing live is read or touched: a temp hub with one webhook channel
to a loopback sink, a temp journal, a temp owner zone file (Europe/London) and a dispatcher on
an injected clock. Prints QUIET-HOURS-OK only after the last check (plan §8 step 4).
"""

import asyncio
import json
import os
import sys
import tempfile
import threading
from datetime import datetime, time, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from zoneinfo import ZoneInfo

sys.path.insert(0, "/opt/nettap/daemon")

from services import quiet_hours
from services.event_journal import EventJournal
from services.notification_dispatcher import (
    QUIET_PREAMBLE,
    AlertDispatcher,
)
from services.notification_hub import NotificationHub

LONDON = ZoneInfo("Europe/London")
QUIET = {"enabled": True, "start": "22:00", "end": "07:00", "critical_through": True}
CAP = 1_234_567_000  # a cap no owner would type
POSTS: list[dict] = []


class Sink(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        size = int(self.headers.get("Content-Length") or 0)
        POSTS.append(json.loads(self.rfile.read(size) or b"{}"))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *_args) -> None:
        pass


def fail(why: str) -> None:
    print("FAIL", why)
    sys.exit(1)


def london(day, hhmm: str, seconds: int = 0) -> datetime:
    hours, minutes = map(int, hhmm.split(":"))
    local = datetime.combine(day, time(hours, minutes, seconds), tzinfo=LONDON)
    return local.astimezone(timezone.utc)


def main() -> None:
    server = HTTPServer(("127.0.0.1", 0), Sink)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    tmp = tempfile.mkdtemp()
    config = os.path.join(tmp, "notifications.json")
    env = os.path.join(tmp, ".env")
    tz_path = os.path.join(tmp, "owner-timezone.json")
    with open(
        config, "w"
    ) as f:  # written first, so the hub never seeds from the environment
        json.dump({"channels": {}, "rules": {}, "quiet": QUIET}, f)
    with open(env, "w"):
        pass
    with open(tz_path, "w") as f:
        json.dump({"tz": "Europe/London"}, f)

    hub = NotificationHub(config_path=config, env_file=env)
    if hub.quiet() != QUIET:
        fail(f"the hub read quiet hours as {hub.quiet()}")
    url = f"http://127.0.0.1:{server.server_address[1]}/sink"
    cid = hub.configure("webhook", {"url": url})["id"]
    hub.add_rule("data_cap", [cid], 4)

    today = datetime.now(LONDON).date()
    month = today.strftime("%Y-%m")
    journal = EventJournal(os.path.join(tmp, "events.jsonl"))
    for key, used in (("80", 1_000_000_000), ("100", 1_300_000_000)):
        journal.append(
            "data_cap",
            key,
            datetime.now(timezone.utc).isoformat(),
            {
                "month": month,
                "month_label": today.strftime("%B"),
                "used": used,
                "cap": CAP,
                "projected": 1_500_000_000,
                "tz": "Europe/London",
                "since": f"{month}-01",
                "complete": True,
                "threshold": key,
            },
            instance=f"{month}|{CAP}",
        )

    clock = [london(today, "23:00")]
    dispatcher = AlertDispatcher(
        hub,
        client=None,  # no alert rule, so OpenSearch is never asked
        lan_cidrs=lambda: [],
        state_path=os.path.join(tmp, "dispatch.json"),
        journal=journal,
        data_cap_now=lambda: (month, CAP),
        quiet=quiet_hours.source(hub, tz_path),
        clock=lambda: clock[0],
    )

    def poll(at: datetime) -> None:
        clock[0] = at
        asyncio.run(dispatcher.poll_once(at))

    tomorrow = today + timedelta(days=1)
    poll(london(today, "23:00"))
    poll(london(tomorrow, "06:59"))
    if POSTS:
        fail(f"{len(POSTS)} POST(s) inside quiet hours")
    queued = dispatcher._events["channels"].get(cid, {}).get("events", [])
    if len(queued) != 2 or not all(e.get("held") for e in queued):
        fail(f"expected 2 held warnings, queue is {queued}")
    print("   held at 23:00 and 06:59: 0 POSTs, 2 warnings queued as held")

    poll(london(tomorrow, "07:00", 30))
    if len(POSTS) != 1:
        fail(f"{len(POSTS)} POSTs at 07:00:30, expected 1")
    message = POSTS[0].get("message", "")
    if not message.startswith(QUIET_PREAMBLE) or message.count("cap used") != 2:
        fail(f"the release doesn't carry the heading and both lines: {message[:300]!r}")
    print("   released at 07:00:30: 1 POST with the heading and both cap lines")

    poll(london(tomorrow, "07:01", 30))
    if len(POSTS) != 1:
        fail(f"{len(POSTS)} POSTs after 07:01:30, expected still 1")
    print("   07:01:30: no second POST")
    server.shutdown()
    print("QUIET-HOURS-OK")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # the deploy script passes only on QUIET-HOURS-OK
        fail(f"{type(exc).__name__}: {exc}")
