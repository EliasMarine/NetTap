"""Batch 46 checks: System → Updates can update Malcolm from the UI (#123-#128).

- the status the page polls has the new shape, and nothing is running
- every version row is its own; Zeek/Suricata/TShark/Docker are read where they run
- the update check offers the tested Malcolm release as one "malcolm" update, and the
  Malcolm image and package rows point at it
- the OS row matches Ubuntu's own update-notifier file
- the Malcolm update's own preflight works on this box: compose project from the daemon's
  labels, disk space for the data copy, and docker compose in the helper container

Runs inside nettap-storage-daemon (deploy-data-accuracy-batch46.sh passes it with `python3 -c`).
Read-only: the update check re-reads sources; the preflight only reads; nothing is applied.
"""

import asyncio
import json
import os
import sys
import urllib.error
import urllib.request

PROBLEMS: list[str] = []
STATUS_KEYS = {"state", "components", "current_component", "current_step", "progress_percent",
               "started_at", "completed_at", "results"}
PACKAGES = ("zeek", "suricata", "tshark", "docker", "docker-compose")


def call(path: str, method: str = "GET", body: dict | None = None) -> tuple[int, dict]:
    with open("/run/nettap-auth/daemon-token") as fh:
        token = fh.read().strip()
    data = json.dumps(body if body is not None else {}).encode() if method == "POST" else None
    req = urllib.request.Request("http://localhost:8880" + path, method=method, data=data,
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


def check_status() -> None:
    code, status = call("/api/system/updates/status")
    missing = sorted(STATUS_KEYS - set(status))
    check("status has the shape the page polls", code == 200 and not missing,
          f"HTTP {code}, state {status.get('state')!r}, missing {missing or 'nothing'}")
    check("no update is running", status.get("state") != "in_progress", f"state {status.get('state')!r}")
    code, _ = call("/api/system/updates/apply", "POST", {"components": [123]})
    check("apply refuses a component that isn't a name", code == 400, f"HTTP {code}")


def check_rows() -> dict:
    call("/api/system/versions/scan", "POST")
    listed = call("/api/system/versions")[1].get("versions", [])
    names = [v["name"] for v in listed]
    dupes = sorted({n for n in names if names.count(n) > 1})
    check("every version row is its own", bool(names) and not dupes, f"{len(names)} rows, duplicates {dupes or 'none'}")
    rows = {v["name"]: v for v in listed}
    gone = sorted({"python3", "node"} & set(rows))
    check("the daemon container's own python3/node rows are gone", not gone, f"still listed {gone or 'none'}")
    for pkg in PACKAGES:
        row = rows.get(pkg, {})
        check(f"{pkg} version read where it runs", row.get("status") == "ok",
              f"{row.get('current_version')!r} ({row.get('status')}) {row.get('details', {}).get('error', '')}".strip())
    malcolm = rows.get("malcolm", {})
    images = {n: v["current_version"] for n, v in rows.items()
              if v.get("details", {}).get("image", "").startswith(("ghcr.io/idaholab/malcolm/", "nettap/zeek-live:"))}
    same = bool(images) and set(images.values()) == {malcolm.get("current_version")}
    check("malcolm row = the tag every Malcolm container runs", malcolm.get("status") == "ok" and same,
          f"row {malcolm.get('current_version')!r} ({malcolm.get('status')}); {len(images)} containers on "
          f"{sorted(set(images.values()))}")
    return {"running": malcolm.get("current_version", ""), "images": sorted(images), "rows": rows}


def check_offer(mu, seen: dict) -> None:
    from services.os_updates import UPDATE_NOTIFIER, read_os_updates

    _, upd = call("/api/system/updates/check", "POST")
    listed = {u["component"]: u for u in upd.get("updates", [])}
    checked, failed = set(upd.get("checked") or []), upd.get("failed_checks") or []
    offer = listed.get("malcolm")
    if mu.newer(mu.TESTED_MALCOLM_TAG, seen["running"]):
        ok = bool(offer) and offer.get("latest_version") == mu.TESTED_MALCOLM_TAG and offer.get("applies_with") is None
        check("the tested Malcolm release is offered as one update", ok,
              f"running {seen['running']}, offered {offer and offer.get('latest_version')!r} "
              f"(applies_with {offer and offer.get('applies_with')!r})")
    else:
        ok = offer is None or offer.get("applies_with") is not None
        check("no Malcolm update is offered past the tested release", ok,
              f"running {seen['running']}, tested {mu.TESTED_MALCOLM_TAG}, offered {offer and offer.get('latest_version')!r}")
    followers = [n for n in (*seen["images"], "zeek", "suricata") if n in listed]
    wrong = [n for n in followers if listed[n].get("applies_with") != mu.MALCOLM_ROW_APPLIES_WITH]
    check("Malcolm's image and package rows point at the Malcolm row", bool(followers) == bool(offer) and not wrong,
          f"{len(followers)} rows follow it, wrong {wrong or 'none'}")
    try:
        found = read_os_updates(UPDATE_NOTIFIER)
    except ValueError as exc:
        found = exc
    row = listed.get("os")
    if found is None or isinstance(found, ValueError):
        check("OS row isn't counted as checked without Ubuntu's file", "os" not in checked and "os" in failed,
              f"file: {found or 'not mounted'}; checked {'os' in checked}, failed {'os' in failed}")
    elif found[0] == 0:
        check("OS row: nothing pending, as Ubuntu's file says", row is None and "os" in checked,
              f"file says 0 pending; row {row and row.get('latest_version')!r}, checked {'os' in checked}")
    else:
        want = f"{found[0]} package update{'s' if found[0] != 1 else ''}"
        ok = bool(row) and row.get("latest_version") == want and "apt upgrade" in (row.get("applies_with") or "")
        check("OS row = Ubuntu's own pending count, with the command", ok,
              f"file {found[0]} pending ({found[1]} security); row {row and row.get('latest_version')!r}")


async def check_preflight(mu) -> None:
    up = mu.MalcolmUpgrade()
    try:
        p = await up._project()
    except mu.UpgradeError as exc:
        check("update preflight: compose project", False, str(exc))
        return
    check("update preflight: compose project", True,
          f"project {p['project']}, {len(p['services'])} Malcolm services on {p['tag']}, data volume {p['data_volume']}")
    try:
        await up._check_disk(p)
        check("update preflight: disk space for the data copy", True, "enough free")
    except mu.UpgradeError as exc:
        check("update preflight: disk space for the data copy", False, str(exc))
    out, rc = await up._run(up._compose(p, mu.TESTED_MALCOLM_TAG, "config", "--images"), 300)
    tags = {line.rsplit(":", 1)[-1] for line in out.split() if "malcolm/" in line or "zeek-live" in line}
    check("update preflight: docker compose runs in the helper with the new tag", rc == 0 and tags == {mu.TESTED_MALCOLM_TAG},
          f"exit {rc}, Malcolm images resolve to {sorted(tags) or out.strip()[-200:]}")
    # take_unfinished() would delete the file; only look
    check("no unfinished update left behind", not os.path.exists(mu.STATE_FILE), f"{mu.STATE_FILE} absent")


def main() -> int:
    sys.path.insert(0, "/opt/nettap/daemon")
    import services.malcolm_upgrade as mu  # only inside the daemon container

    check_status()
    seen = check_rows()
    check_offer(mu, seen)
    asyncio.run(check_preflight(mu))
    print(f"\n{len(PROBLEMS)} problem(s)" + (f": {', '.join(PROBLEMS)}" if PROBLEMS else ""))
    return 1 if PROBLEMS else 0


sys.exit(main())
