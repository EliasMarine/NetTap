"""Batch 43 checks: System → Updates reads Suricata's rules date in the Suricata container and
applies a rules update there (the daemon container has neither the file nor suricata-update);
a NetTap release says how to get it instead of offering a button that can only fail.

Runs inside nettap-storage-daemon (deploy-data-accuracy-batch43.sh passes it with `python3 -c`).
Writes one thing: it applies the Suricata rules update, the same download and reload Suricata's
own job runs every night.
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

PROBLEMS: list[str] = []
SURICATA = os.environ.get("SURICATA_CONTAINER_NAME", "nettap-suricata-live")
RULES = "/var/lib/suricata/rules/suricata.rules"
QUIET_SIDS = ("2200121", "2231001")  # decoder-noise rules NetTap switches off (#57)


def call(path: str, method: str = "GET", body: dict | None = None) -> tuple[int, dict]:
    with open("/run/nettap-auth/daemon-token") as fh:
        token = fh.read().strip()
    data = json.dumps(body or {}).encode() if method == "POST" else None
    req = urllib.request.Request("http://localhost:8880" + path, method=method, data=data,
                                 headers={"X-NetTap-Daemon-Token": token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def docker(*args: str) -> str:
    return subprocess.run(["docker", *args], check=False, capture_output=True, text=True, timeout=60).stdout.strip()


def check(label: str, ok: bool, detail: str) -> None:
    print(f"{'✓' if ok else '✗'} {label}: {detail}")
    if not ok:
        PROBLEMS.append(label)


def main() -> int:
    before = call("/api/suricata/rules/live")[1].get("last_updated") or ""
    started = docker("inspect", "--format", "{{.State.StartedAt}}", SURICATA)
    _, upd = call("/api/system/updates/check", "POST")
    checked, failed = set(upd.get("checked") or []), upd.get("failed_checks") or []
    listed = {u["component"]: u for u in upd.get("updates", [])}
    rules = listed.get("suricata-rules")
    age = (datetime.now(UTC) - datetime.fromisoformat(before)).days if before else None
    right = bool(before) and (rules is None) == (age < 1) and (rules is None or rules["current_version"] == before[:10])
    check("the rules check reads Suricata's rules file", "suricata-rules" in checked and "suricata-rules" not in failed and right,
          f"file {before or 'unreadable'} ({age} day(s) old); update listed: {rules['current_version'] if rules else 'none'}; failed {failed or 'none'}")
    nettap = listed.get("nettap-daemon")
    check("a NetTap release says how to get it, not an Update button", nettap is None or bool(nettap.get("applies_with")),
          f"{nettap['latest_version']}: {nettap['applies_with']}" if nettap else "no newer NetTap release published")

    status, applied = call("/api/system/updates/apply", "POST", {"components": ["suricata-rules"]})
    res = (applied.get("results") or [{}])[0]
    after = call("/api/suricata/rules/live")[1]
    ok = (status == 200 and res.get("success") is True and res.get("old_version") == before[:10]
          and res.get("new_version") == (after.get("last_updated") or "")[:10] and (after.get("last_updated") or "") >= before)
    check("Updates → Suricata rules applies in the Suricata container", ok,
          f"HTTP {status}, success {res.get('success')}, {res.get('old_version')} → {res.get('new_version')}; "
          f"file {before} → {after.get('last_updated')}; error {res.get('error')}")
    running = docker("inspect", "--format", "{{.State.Running}} {{.State.StartedAt}}", SURICATA)
    check("Suricata reloaded the rules without a restart", running == f"true {started}" and (after.get("enabled_rules") or 0) > 0,
          f"{after.get('enabled_rules')} rules enabled; container {running!r} (started {started})")
    loud = [sid for sid in QUIET_SIDS if docker("exec", SURICATA, "grep", "-c", f"^alert .*sid:{sid};", RULES) not in ("", "0")]
    check("the decoder-noise rules stay off after the update", not loud, f"switched back on: {loud or 'none'}")
    print(f"RESULT {len(PROBLEMS)}")
    return 1 if PROBLEMS else 0


if __name__ == "__main__":
    sys.exit(main())
