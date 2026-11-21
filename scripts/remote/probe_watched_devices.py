"""NET-331 deploy check: the watched-devices job on the real index, in memory (plan §2.8 step 4).

Runs inside the live daemon container (deploy-watched-devices.sh):
    docker exec -i nettap-storage-daemon python3 - < probe_watched_devices.py
Read only. It searches the real OpenSearch with the daemon's own credentials through a client
that never retries, as the job's own client does. The details store, journal and state file
are temporary and removed at the end. There is no dispatcher, so nothing is sent. The capture
health is the live one (GET /api/capture/health, the dict the job's own reader returns), so the
scope is the box's; its readiness flags are forced on and the live readiness is only printed:
this checks the searches and the state machine on real records, not the capture manager.

Samples come from raw final conn records (CONN_ACCOUNTING) that ended in the last 5 minutes and
started at or after the probe's enrolment, 15 minutes back: up to 3 originators (source.mac) and
3 responders (destination.mac on a record with replies). Each must come out "up". A random
unused locally administered MAC, and a device whose only recent record started before the
enrolment (the negative case), must stay "unknown". A side with no sample is inconclusive, not
a failure. Prints WATCHED-PROBE-OK only after the last check; never prints a credential.
"""

import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/opt/nettap/daemon")

TMP = tempfile.mkdtemp(prefix="watched-probe-")
NOW = datetime.now(timezone.utc).replace(microsecond=0)
ENROLLED = NOW - timedelta(minutes=15)
RECENT = NOW - timedelta(minutes=5)
SEEN_WITHIN = timedelta(minutes=10)
PER_SIDE = 3
CANDIDATES = 5  # negative-case devices tried
HITS = 500
# the readiness flags capture_scope checks, forced on over the live health
READY = {
    "status": "normal",
    "link_up": True,
    "promisc_enabled": True,
    "routing_active": True,
}
SIX_OCTETS = re.compile(r"[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}")


def fail(why: str) -> None:
    print("FAIL", why, flush=True)
    sys.exit(1)


def say(line: str) -> None:
    print(f"   {line}", flush=True)


def hhmmss(raw) -> str:
    try:
        when = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return "?"
    return when.astimezone(timezone.utc).strftime("%H:%M:%S")


def field(source: dict, dotted: str):
    """A field from _source, nested ({"source": {"mac": …}}) or flat ({"source.mac": …})."""
    if dotted in source:
        return source[dotted]
    value = source
    for part in dotted.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def unicast_mac(raw) -> str | None:
    """A device's six-octet MAC, upper case; None for a list, a broadcast or a multicast."""
    if not isinstance(raw, str) or not SIX_OCTETS.fullmatch(raw):
        return None
    return None if int(raw[:2], 16) & 1 else raw.upper()


def unused_mac() -> str:
    """A random locally administered unicast MAC: no vendor hands these out."""
    first = secrets.randbelow(64) << 2 | 0x02
    return ":".join(f"{b:02X}" for b in (first, *secrets.token_bytes(5)))


class Recording:
    """The real client, keeping each search body with its reply."""

    def __init__(self, client) -> None:
        self.client = client
        self.calls: list[tuple[dict, dict]] = []

    def search(self, **kwargs) -> dict:
        reply = self.client.search(**kwargs)
        self.calls.append((kwargs["body"], reply))
        return reply


def raw_hits(client, index: str, extra: list) -> list[dict]:
    """Final conn records that ended in the last 5 minutes, newest first."""
    from services.excluded_ips import CONN_ACCOUNTING
    from services.watched_rules import iso

    ended = {"gte": iso(RECENT), "lte": iso(NOW), "format": "strict_date_optional_time"}
    body = {
        "size": HITS,
        "sort": [{"event.end": "desc"}],
        "_source": [
            "source.mac",
            "destination.mac",
            "event.dataset",
            "event.end",
            "@timestamp",
        ],
        "query": {
            "bool": {
                "filter": [CONN_ACCOUNTING, {"range": {"event.end": ended}}, *extra]
            }
        },
        "timeout": "20s",
    }
    reply = client.search(index=index, body=body, request_timeout=25)
    if reply.get("timed_out") or (reply.get("_shards") or {}).get("failed"):
        fail("the sample search came back incomplete")
    return reply["hits"]["hits"]


def pick(hits: list[dict], side: str, limit: int, taken: set[str]) -> dict[str, dict]:
    """Up to `limit` distinct MACs from one side of the hits: {MAC: what the record said}."""
    found: dict[str, dict] = {}
    for hit in hits:
        source = hit.get("_source") or {}
        raw = field(source, f"{side}.mac")
        mac = unicast_mac(raw)
        if mac and mac not in taken and mac not in found:
            found[mac] = {
                "raw": raw,  # as the index holds it: the presence search asks in lower case
                "dataset": field(source, "event.dataset") or "?",
                "started": field(source, "@timestamp"),
                "ended": field(source, "event.end"),
            }
        if len(found) == limit:
            break
    return found


def samples(client, index: str) -> tuple[dict, dict, dict]:
    """(originators, responders, negative candidates), each {MAC: record facts}."""
    from services.watched_rules import REPLIED, iso

    def since(op: str) -> dict:
        return {
            "range": {
                "@timestamp": {op: iso(ENROLLED), "format": "strict_date_optional_time"}
            }
        }

    def has(name: str) -> dict:
        return {"exists": {"field": name}}

    originators = pick(
        raw_hits(client, index, [since("gte"), has("source.mac")]),
        "source",
        PER_SIDE,
        set(),
    )
    replied = raw_hits(client, index, [since("gte"), has("destination.mac"), REPLIED])
    responders = pick(replied, "destination", PER_SIDE, set(originators))
    early = raw_hits(client, index, [since("lt"), has("source.mac")])
    candidates = pick(early, "source", CANDIDATES, set(originators) | set(responders))
    return originators, responders, candidates


def live_health() -> dict:
    """The live capture health, read with the daemon token (never printed)."""
    with open("/run/nettap-auth/daemon-token") as fh:
        token = fh.read().strip()
    req = urllib.request.Request(
        "http://localhost:8880/api/capture/health",
        headers={"X-NetTap-Daemon-Token": token},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def probe_health() -> dict:
    """The live health with readiness forced on; fails in a mode that can't tell devices apart."""
    from services.watched_rules import capture_scope

    health = live_health()
    forced = {**health, **READY}
    where = f"{health.get('mode')} on {health.get('capture_interface')}"
    if capture_scope(forced)[0] is None:
        fail(f"capture is {where}: watched devices don't run in this mode")
    live_scope, why = capture_scope(health)
    say(
        f"live capture: {where}, "
        + ("ready" if live_scope else f"not ready ({why}), forced for the probe")
    )
    return forced


def run_job(client, index: str, watched: list[str], health: dict):
    """One run of the real job on temp files: (state, journal entries, presence reply)."""
    from services.device_details import DeviceDetailsStore
    from services.event_journal import EventJournal
    from services.watched_devices import WatchedDevices
    from services.watched_rules import EMPTY_CHECK, capture_scope, enrolled

    details = DeviceDetailsStore(root=TMP)
    for mac in watched:
        details.update(mac, {"watch_after_min": 15})
    scope, _reason = capture_scope(health)
    path = os.path.join(TMP, "watched-devices.json")
    state = {
        "version": 1,
        "check": {**EMPTY_CHECK, "scope": scope},  # the same scope: no re-baseline
        "devices": {mac: enrolled(15, ENROLLED) for mac in watched},
    }
    with open(path, "w") as fh:
        json.dump(state, fh)
    journal = EventJournal(os.path.join(TMP, "events.jsonl"))
    recorder = Recording(client)
    job = WatchedDevices(
        details=details,
        journal=journal,
        name_for=lambda _mac: None,
        client=recorder,
        index=index,
        capture_health=lambda: dict(health),
        path=path,
        now=lambda: NOW,
    )
    try:
        job.run(time.monotonic() + 60)
    except Exception as exc:
        fail(f"the job's run raised {type(exc).__name__}: {str(exc)[:160]}")
    with open(path) as fh:
        after = json.load(fh)
    presence = next(
        (reply for body, reply in recorder.calls if "sent" in body.get("aggs", {})),
        None,
    )
    return after, journal.after(0, 10), presence


def bucket_starts(presence: dict) -> tuple[list[str], dict[str, int]]:
    """(every bucket key as sent, {MAC: newest @timestamp in epoch ms over both sides})."""
    keys, starts = [], {}
    for side in ("sent", "answered"):
        for bucket in presence["aggregations"][side]["macs"]["buckets"]:
            keys.append(bucket["key"])
            value = (bucket.get("started") or {}).get("value")
            if isinstance(value, (int, float)):
                mac = str(bucket["key"]).upper()
                starts[mac] = max(starts.get(mac, value), value)
    return keys, starts


def check_positives(kind: str, found: dict, devices: dict) -> None:
    if not found:
        say(
            f"{kind}s: inconclusive, no final conn record{' with replies' if kind == 'responder' else ''} "
            "started in the last 15 minutes and ended in the last 5"
        )
        return
    for mac, rec in found.items():
        dev = devices.get(mac) or {}
        seen = (
            datetime.fromisoformat(str(dev.get("seen_at")).replace("Z", "+00:00"))
            if dev.get("seen_at")
            else None
        )
        if dev.get("state") != "up" or seen is None or NOW - seen > SEEN_WITHIN:
            fail(
                f"{kind} {mac} (indexed as {rec['raw']}) is {dev.get('state')}, seen "
                f"{dev.get('seen_at')}, expected up within 10 minutes"
            )
        say(
            f"{kind} {mac} from {rec['dataset']}: started {hhmmss(rec['started'])}, "
            f"ended {hhmmss(rec['ended'])} -> up, seen {hhmmss(dev['seen_at'])}"
        )


def check_negative(candidates: dict, starts: dict, devices: dict) -> None:
    enrolled_ms = ENROLLED.timestamp() * 1000
    shown = False
    for mac, rec in candidates.items():
        if mac not in starts or starts[mac] >= enrolled_ms:
            continue  # it has a newer connection too, or the presence search didn't see it
        state = (devices.get(mac) or {}).get("state")
        if state != "unknown":
            fail(
                f"negative case {mac} (started {hhmmss(rec['started'])}, ended {hhmmss(rec['ended'])}) is {state}"
            )
        if not shown:
            say(
                f"negative case {mac} from {rec['dataset']}: started {hhmmss(rec['started'])}, "
                f"ended {hhmmss(rec['ended'])}, nothing newer -> unknown"
            )
            shown = True
    if not shown:
        say(
            "negative case: inconclusive, no device whose only recent record started before 15 minutes back"
        )


def main() -> None:
    from main import _parse_curlrc_credentials
    from opensearchpy import OpenSearch
    from services.pipeline_health import NETWORK_INDEX
    from storage.manager import StorageManager

    auth = _parse_curlrc_credentials(os.environ.get("OPENSEARCH_CREDS_CONFIG_FILE", ""))
    url = os.environ.get("OPENSEARCH_URL", "http://localhost:9200")
    # the job's own client settings (server.py): no retries, so nothing outlives a deadline
    kwargs = StorageManager._client_kwargs(url, auth)
    client = OpenSearch(**{**kwargs, "max_retries": 0, "retry_on_timeout": False})

    health = probe_health()
    originators, responders, candidates = samples(client, NETWORK_INDEX)
    unused = unused_mac()
    watched = sorted({*originators, *responders, *candidates, unused})
    state, entries, presence = run_job(client, NETWORK_INDEX, watched, health)
    check = state["check"]
    if check.get("skipped") or check.get("error"):
        fail(
            f"the check didn't run: skipped {check.get('skipped')} ({check.get('reason')}), error {check.get('error')}"
        )
    if presence is None:
        fail("the job ran no presence search")
    keys, starts = bucket_starts(presence)
    shards = presence.get("_shards", {})
    say(
        f"real search: capture time {hhmmss(check.get('capture_at'))}, presence over "
        f"{len(watched)} watches on {shards.get('successful')}/{shards.get('total')} shards"
    )
    devices = state["devices"]
    check_positives("originator", originators, devices)
    check_positives("responder", responders, devices)
    if any(k != str(k).lower() for k in keys):
        fail(
            f"bucket keys aren't lower case: {[k for k in keys if k != str(k).lower()][:3]}"
        )
    say(
        f"bucket keys lower case ({len(keys)})"
        if keys
        else "bucket keys: inconclusive, none came back"
    )
    if devices.get(unused, {}).get("state") != "unknown" or unused in starts:
        fail(f"the unused MAC {unused} is {devices.get(unused, {}).get('state')}")
    say(f"unused locally administered {unused}: unknown")
    check_negative(candidates, starts, devices)
    if entries:
        fail(f"the probe journalled {len(entries)} event(s); it should journal none")
    datasets = sorted(
        {rec["dataset"] for rec in (*originators.values(), *responders.values())}
    )
    say(f"datasets carrying the samples: {', '.join(datasets) or 'none'}")
    print("WATCHED-PROBE-OK", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # the deploy script passes only on WATCHED-PROBE-OK
        fail(f"{type(exc).__name__}: {str(exc)[:200]}")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
