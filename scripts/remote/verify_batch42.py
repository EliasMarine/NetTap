"""Batch 42 checks: System → Updates rows (each row its own update, "Not checked" for what
nothing checks) and the host's OS version.

Runs inside nettap-storage-daemon (deploy-data-accuracy-batch42.sh passes it with `python3 -c`).
Read-only: the update check only re-reads sources; nothing is applied.
"""

import json
import sys
import urllib.error
import urllib.request

PROBLEMS: list[str] = []
NEVER_CHECKED = {"os", "kernel", "docker", "python3", "opensearch"}  # no update source covers these


def call(path: str, method: str = "GET") -> tuple[int, dict]:
    with open("/run/nettap-auth/daemon-token") as fh:
        token = fh.read().strip()
    req = urllib.request.Request("http://localhost:8880" + path, method=method, data=b"{}" if method == "POST" else None,
                                 headers={"X-NetTap-Daemon-Token": token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def check(label: str, ok: bool, detail: str) -> None:
    print(f"{'✓' if ok else '✗'} {label}: {detail}")
    if not ok:
        PROBLEMS.append(label)


def version_id(path: str) -> str | None:
    try:
        with open(path) as fh:
            return next((ln.split("=", 1)[1].strip().strip('"') for ln in fh if ln.startswith("VERSION_ID=")), None)
    except OSError:
        return None


def main() -> int:
    call("/api/system/versions/scan", "POST")
    _, upd = call("/api/system/updates/check", "POST")
    _, vers = call("/api/system/versions")
    rows = {v["name"]: v for v in vers.get("versions", [])}

    host, image = version_id("/host/etc/os-release"), version_id("/etc/os-release")
    os_row = rows.get("os", {})
    check("OS version is the host's, not the daemon image's", host is not None and os_row.get("current_version") == host,
          f"page {os_row.get('current_version')!r} {os_row.get('details')}, host {host!r}, daemon image {image!r}")

    names = [u["component"] for u in upd.get("updates", [])]
    unmatched = [n for n in names if n not in rows]
    check("every listed update has its own row", not unmatched, f"{len(names)} updates {names}; without a row: {unmatched or 'none'}")
    checked = set(upd.get("checked") or [])
    wrong = sorted(NEVER_CHECKED & checked)
    covered = sorted(set(names) - checked)
    check("the check says what it covered (OS, Docker, Python... not)", bool(checked) and not wrong and not covered,
          f"checked {sorted(checked)}; wrongly claimed {wrong or 'none'}; updates outside it {covered or 'none'}")
    print(f"RESULT {len(PROBLEMS)}")
    return 1 if PROBLEMS else 0


if __name__ == "__main__":
    sys.exit(main())
