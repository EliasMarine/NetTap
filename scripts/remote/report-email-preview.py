"""NET-381 deploy check: compose the weekly report email inside the daemon container, send nothing.

Piped in by deploy-weekly-email.sh:
    sudo docker exec -i nettap-storage-daemon python3 - < scripts/remote/report-email-preview.py

1. A synthetic report goes through render_email, render_html and compose_report_message (the
   same composer the sender uses) with example.invalid headers. There is no SMTP here at all.
   Exits 1 unless the HTML part was kept and its cid: resolves to the packaged logo's bytes.
2. The newest stored report (through the daemon's own history API) is composed in memory the
   same way, and only its MIME tree, size and drop reason are printed: never content or
   addresses. A size fallback there is legitimate, so this part only reports.
Nothing is written to disk.
"""

import json
import sys
import urllib.request
from email import message_from_string, policy

from services.notification_hub import compose_report_message
from services.report_html import LOGO_PATH, logo_png, render_html
from services.report_text import render_email

CID = "deploy-check.1@nettap.local"
HEADERS = ("NetTap <nettap@example.invalid>", ["owner@example.invalid"])


def synthetic() -> dict:
    ok = {"status": "ok", "coverage": "7 of 7 days counted", "note": None}
    return {
        "id": "20261123T080000Z-abc123",
        "schedule_id": "00000000-0000-4000-8000-000000000000",
        "frequency": "weekly",
        "period": {"first": "2026-11-16", "last": "2026-11-22", "tz": "UTC"},
        "sections": {
            "traffic": {
                **ok,
                "download": 3 * 10**11,
                "upload": 10**11,
                "total": 4 * 10**11,
                "local": 0,
                "counted_total": 4 * 10**11,
                "provisional": False,
                "busiest": {"date": "2026-11-18", "total": 8 * 10**10},
            },
            "alerts": {
                **ok,
                "total": 12,
                "by_severity": {"1": 2, "2": 4, "3": 6, "other": 0},
                "days": [{"date": "2026-11-16", "count": 12, "stored": "full"}],
                "worst": [
                    {"rule": "ET TEST rule", "severity": 1, "count": 2, "what": "A test.", "todo": "Nothing."}
                ],
                "worst_note": None,
            },
            "new_devices": {**ok, "count": 0, "listed": [], "truncated": False},
            "offline": {**ok, "incidents": [], "watched_now": 0},
            "data_cap": {**ok, "cap_bytes": None, "crossings": []},
        },
    }


def compose(report: dict) -> tuple[str, str | None]:
    subject, text = render_email(report)
    png = logo_png()
    html = render_html(report, CID if png else None)
    return compose_report_message(subject, *HEADERS, text, html, (CID, png) if png else None)


def tree(msg, depth: int = 0) -> list[str]:
    lines = ["  " * depth + msg.get_content_type()]
    for part in msg.iter_parts() if msg.is_multipart() else []:
        lines += tree(part, depth + 1)
    return lines


def check_synthetic() -> bool:
    wire, dropped = compose(synthetic())
    msg = message_from_string(wire, policy=policy.default)
    print("synthetic:", " > ".join(t.strip() for t in tree(msg)), f"· {len(wire)} bytes · dropped: {dropped}")
    html = msg.get_body(("html",))
    images = [p for p in msg.walk() if p.get_content_type() == "image/png"]
    resolved = (
        html is not None
        and f"cid:{CID}" in html.get_content()
        and len(images) == 1
        and images[0]["Content-ID"].strip("<>") == CID
        and images[0].get_content() == LOGO_PATH.read_bytes()
    )
    return dropped is None and resolved


def call(path: str):
    token = open("/run/nettap-auth/daemon-token").read().strip()
    req = urllib.request.Request("http://localhost:8880" + path, headers={"X-NetTap-Daemon-Token": token})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def report_stored() -> None:
    try:
        reports = call("/api/reports/history").get("reports") or []
        if not reports:
            print("stored: no stored report yet (skipped)")
            return
        newest = reports[0]
        report = call(f"/api/reports/history/{newest['schedule_id']}/{newest['id']}")
        wire, dropped = compose(report)
        msg = message_from_string(wire, policy=policy.default)
        print("stored:", " > ".join(t.strip() for t in tree(msg)), f"· {len(wire)} bytes · dropped: {dropped}")
    except Exception as exc:  # report only: the synthetic check is the gate
        print(f"stored: couldn't compose ({type(exc).__name__})")


if __name__ == "__main__":
    ok = check_synthetic()
    report_stored()
    print("OK html part kept and logo resolves" if ok else "FAIL the HTML part or its logo is broken")
    sys.exit(0 if ok else 1)
