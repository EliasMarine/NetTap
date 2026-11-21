"""Classify one GET /api/backup/export answer for the deploy gates (NET-344, F2 NET-320).

Standard library only and nothing from the daemon, so any daemon image can run it, before or
after F2. The HTTP status is the first argument and the reply body comes on stdin:
    python3 classify_backup_export.py STATUS [--require-section NAME] < body.json
The host has no python, so deploy scripts hand the script to the daemon container as -c and
keep stdin for the body:
    sudo docker exec -i nettap-storage-daemon python3 -c "$(cat classify_backup_export.py)" "$STATUS" < body.json

Prints one line and exits 0 for OK or FINDING, 1 for FAIL:
    OK       a 200 under the restore limit holding a backup (and NAME, when asked for)
    FINDING  a 413 backup_too_large or a 422 legacy_excluded_ips: the owner has to act, the
             code works as designed (plan §2.3 steps 4 and 6)
    FAIL     anything else, a 422 invalid_section included
"""

import argparse
import json
import sys

# services.config_backup.RESTORE_LIMIT_BYTES, which can't be imported here; the test pins it
RESTORE_LIMIT_BYTES = 16 * 1024 * 1024
FINDINGS = {(413, "backup_too_large"), (422, "legacy_excluded_ips")}


def one_line(text: str, limit: int = 300) -> str:
    """Untrusted reply text as one short printable line."""
    return " ".join("".join(c if c.isprintable() else " " for c in text).split())[
        :limit
    ]


def no_constant(name: str) -> None:
    raise ValueError(f"{name} isn't JSON")  # the export encodes with allow_nan=False


def parse(body: bytes) -> object:
    """The JSON document, or None for anything that isn't strict UTF-8 JSON without NaN."""
    try:
        return json.loads(body.decode("utf-8"), parse_constant=no_constant)
    except ValueError:  # UnicodeDecodeError and JSONDecodeError are ValueErrors
        return None


def classify_200(doc: object, size: int, required: str | None) -> tuple[str, str]:
    if size >= RESTORE_LIMIT_BYTES:
        return (
            "FAIL",
            f"200 but {size:,} bytes, at or over the {RESTORE_LIMIT_BYTES:,}-byte restore limit",
        )
    meta = doc.get("metadata") if isinstance(doc, dict) else None
    sections = doc.get("sections") if isinstance(doc, dict) else None
    if not isinstance(meta, dict) or not isinstance(sections, dict):
        return "FAIL", f"200 but not a backup document ({size:,} bytes)"
    left = meta.get("acknowledgements_left_out", 0)
    if not isinstance(left, int) or isinstance(left, bool) or left < 0:
        return "FAIL", f"200 but acknowledgements_left_out is {one_line(repr(left))}"
    if required and required not in sections:
        return "FAIL", f"200 without the {required} section ({size:,} bytes)"
    return "OK", f"200: {size:,} bytes, acknowledgements_left_out {left}"


def classify(status: str, body: bytes, required: str | None) -> tuple[str, str]:
    doc = parse(body)
    code = int(status) if status.isascii() and status.isdigit() else 0
    if code == 200:
        return classify_200(doc, len(body), required)
    reply = doc if isinstance(doc, dict) else {}
    kind = reply.get("code") if isinstance(reply.get("code"), str) else None
    error = (
        reply.get("error")
        if isinstance(reply.get("error"), str)
        else body[:300].decode("utf-8", "replace")
    )
    detail = f"{one_line(status, 8)} {one_line(str(kind), 40)}: {one_line(error)}"
    return ("FINDING" if (code, kind) in FINDINGS else "FAIL"), detail


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("status", help="the HTTP status (curl's %%{http_code})")
    parser.add_argument("--require-section", help="a 200 must carry this section")
    args = parser.parse_args()
    verdict, detail = classify(
        args.status, sys.stdin.buffer.read(), args.require_section
    )
    print(verdict, detail)
    return 1 if verdict == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
