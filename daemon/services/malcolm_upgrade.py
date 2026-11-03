"""
Update Malcolm's containers to the release NetTap has tested, with a backup and rollback.

All of Malcolm's images carry one tag (MALCOLM_IMAGE_TAG in the compose project's .env), so
they move together. The update:
  1. reads the compose project from the daemon's own container labels, checks disk space,
     then pulls the new images and builds zeek-live on them (nothing has stopped yet)
  2. stops OpenSearch and the services that write to it (capture keeps running: Zeek's and
     Suricata's logs wait on disk), and copies OpenSearch's data volume to a backup volume
  3. writes the new tag to .env and recreates Malcolm's containers, OpenSearch first
  4. checks OpenSearch's login, every container, and that Zeek/Suricata records and PCAP
     arrive again (each only if it was arriving before)
A failure from step 2 on restores the old tag and the data copy and restarts the old images:
a newer OpenSearch's data can't be opened by the older one.

Compose runs in a throwaway container of the daemon's own image (which carries the compose
plugin), with the project directory mounted at its host path, so relative paths resolve as
they do on the host. Every `up` is --no-deps: zeek-live, suricata-live and pcap-capture
depend on the daemon, which must not be recreated while it runs the update.
"""

import asyncio
import json
import logging
import os
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("nettap.services.malcolm_upgrade")

# The Malcolm release this NetTap version was tested with (docker/docker-compose.yml defaults,
# scripts/install/malcolm-versions.conf and malcolm-config.sh say the same; a test checks it).
TESTED_MALCOLM_TAG = "26.10.0"

# compose services that run on MALCOLM_IMAGE_TAG; zeek-live is built from Malcolm's Zeek image
MALCOLM_SERVICES = (
    "opensearch",
    "dashboards-helper",
    "dashboards",
    "logstash",
    "filebeat",
    "zeek-live",
    "suricata-live",
    "pcap-capture",
    "arkime-live",
    "redis",
    "api",
)
BUILT_SERVICES = ("zeek-live",)
# what a single Malcolm container's row says: they all move with the "malcolm" row
MALCOLM_ROW_APPLIES_WITH = (
    "Updates with the Malcolm row: Malcolm's images move together."
)
# stopped for the data copy, in this order; Zeek, Suricata and pcap-capture keep capturing
STOPPED_FOR_BACKUP = (
    "filebeat",
    "logstash",
    "arkime-live",
    "dashboards",
    "dashboards-helper",
    "api",
    "opensearch",
)

DAEMON_CONTAINER = os.environ.get("DAEMON_CONTAINER_NAME", "nettap-storage-daemon")
OPENSEARCH_DATA = "/usr/share/opensearch/data"
CURLRC = "/var/local/curlrc/.opensearch.primary.curlrc"
SESSIONS_INDEX = "arkime_sessions3-*"
PCAP_DIR = os.environ.get("PCAP_DIR", "/opt/nettap/pcap")
STATE_FILE = os.environ.get(
    "MALCOLM_UPGRADE_STATE", "/opt/nettap/data/malcolm-upgrade.json"
)

IMAGE_HEADROOM_KB = 20 * 1024 * 1024  # new images (~9 GB) plus the zeek-live build
RECENT_S = (
    15 * 60
)  # "was arriving before": a record in the 15 minutes before the update
PCAP_RECENT_S = 5 * 60
PULL_TIMEOUT_S = 3600
BUILD_TIMEOUT_S = 1800
COPY_TIMEOUT_S = 3600
STEP_TIMEOUT_S = 600
LOGIN_TIMEOUT_S = 600
HEALTHY_TIMEOUT_S = 900
ARRIVAL_TIMEOUT_S = 600
POLL_S = 10

_TAG_RE = re.compile(r"^\d+\.\d+\.\d+$")
# sets MALCOLM_IMAGE_TAG in an env file, adding the line if it's missing; keeps the file's mode
_SET_TAG = (
    "import os,re,sys\n"
    "p,t=sys.argv[1],sys.argv[2]\n"
    "s=open(p).read() if os.path.exists(p) else ''\n"
    "n,c=re.subn(r'(?m)^MALCOLM_IMAGE_TAG=.*$','MALCOLM_IMAGE_TAG='+t,s)\n"
    "s=n if c else (s.rstrip('\\n')+'\\n' if s else '')+'MALCOLM_IMAGE_TAG='+t+'\\n'\n"
    "m=os.stat(p).st_mode if os.path.exists(p) else 0o600\n"
    "open(p,'w').write(s)\n"
    "os.chmod(p,m)\n"
)

Runner = Callable[[list[str], float], Awaitable[tuple[str, int]]]
OnStep = Callable[[str, int, int], None]


class UpgradeError(Exception):
    """A step failed; the message says which and why, in plain English."""


async def run_command(cmd: list[str], timeout: float) -> tuple[str, int]:
    """Run a command without a shell; (stdout+stderr, returncode). 124 on timeout."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
    except (FileNotFoundError, OSError) as exc:
        return (str(exc), 127)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return (f"timed out after {int(timeout)} s", 124)
    return (out.decode("utf-8", errors="replace"), proc.returncode or 0)


def tag_of(image: str) -> str:
    """The tag of an image reference, "" if it has none."""
    name = image.rsplit("/", 1)[-1]
    return name.split(":", 1)[1] if ":" in name else ""


def newer(a: str, b: str) -> bool:
    """True when release tag a is newer than b (both like 26.10.0)."""
    if not (_TAG_RE.match(a) and _TAG_RE.match(b)):
        return False
    return tuple(map(int, a.split("."))) > tuple(map(int, b.split(".")))


def malcolm_changelog(offered: str, latest: str, tested: bool) -> str:
    """What the Malcolm row's update does, in plain English."""
    if not tested:
        return f"Malcolm {offered} is out, but NetTap hasn't been tested with it yet."
    text = (
        f"Updates all of Malcolm's containers to {offered}, the release this NetTap was tested with. "
        "OpenSearch's data is backed up first, capture and ingest pause for a few minutes, and the "
        "update rolls itself back if capture doesn't resume."
    )
    if newer(latest, offered):
        text += f" Malcolm {latest} is also out, not yet tested with NetTap."
    return text


def _tail(text: str, limit: int = 400) -> str:
    return text.strip()[-limit:]


def newest_pcap_mtime(root: str = PCAP_DIR) -> float | None:
    """Modified time of the newest file under root (pcap-capture rewrites its current file)."""
    newest = None
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            try:
                mtime = os.path.getmtime(os.path.join(dirpath, name))
            except OSError:
                continue  # rotated away while walking
            newest = mtime if newest is None or mtime > newest else newest
    return newest


class MalcolmUpgrade:
    """Moves every running Malcolm container to a newer tag, or back if that fails."""

    def __init__(
        self,
        client: Any = None,
        run: Runner = run_command,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        pcap_mtime: Callable[[], float | None] = newest_pcap_mtime,
        state_file: str = STATE_FILE,
    ) -> None:
        self._client = client  # OpenSearch client: are records arriving?
        self._run = run
        self._sleep = sleep
        self._now = now
        self._pcap_mtime = pcap_mtime
        self._state_file = state_file

    # -- public ------------------------------------------------------------

    async def running_tag(self) -> str:
        """The Malcolm release the running containers carry (UpgradeError if they disagree)."""
        return (await self._project())["tag"]

    async def apply(self, target: str, on_step: OnStep | None = None) -> dict:
        """Update to target. Returns {success, old_version, new_version, error, rolled_back}."""
        if not _TAG_RE.match(target):
            raise ValueError(f"not a Malcolm release tag: {target!r}")
        step = _Steps(on_step, total=9)
        try:
            p = await self._project()
        except UpgradeError as exc:
            return _result(False, "unknown", target, str(exc))
        old = p["tag"]
        if not newer(target, old):
            return _result(
                False, old, target, f"Malcolm {old} is already at or past {target}."
            )
        try:
            step(f"Checking there's disk space for Malcolm {target}")
            await self._check_disk(p)
            step(f"Downloading Malcolm {target}'s images")
            await self._pull(p, target)
            step(f"Building NetTap's Zeek image on Malcolm {target}")
            await self._build(p, target)
            expected = await asyncio.to_thread(self._arriving_now)
        except UpgradeError as exc:  # nothing has stopped yet
            return _result(
                False,
                old,
                old,
                f"{exc} Nothing was changed: Malcolm {old} is still running.",
            )
        copied = False
        try:
            self._save_state(old, target, p, "stopping")
            step("Stopping OpenSearch and its log pipeline (capture keeps running)")
            await self._stop(p, STOPPED_FOR_BACKUP)
            step("Backing up OpenSearch's data")
            await self._copy(p, p["data_volume"], p["backup_volume"])
            copied = True
            self._save_state(old, target, p, "starting")
            step(f"Starting OpenSearch {target}")
            await self._set_tag(p, target)
            await self._up(p, target, ["opensearch"])
            await self._wait_login(p)
            step("Starting Malcolm's other containers")
            await self._up(p, target, [s for s in p["services"] if s != "opensearch"])
            since = self._now()
            step("Checking every container is running")
            await self._wait_healthy(p, target)
            step("Checking new records and PCAP arrive")
            await self._wait_arrivals(expected, since)
        except UpgradeError as exc:
            note = await self._rollback(p, old, target, copied, step)
            return {**_result(False, old, old, f"{exc} {note}"), "rolled_back": True}
        step("Removing the backup copy")
        await self._remove_volume(p["backup_volume"])
        self._clear_state()
        return _result(True, old, target, None)

    def take_unfinished(self) -> dict | None:
        """An update the daemon didn't see finish (it restarted mid-way), read once."""
        try:
            with open(self._state_file) as fh:
                state = json.load(fh)
        except (OSError, ValueError):
            return None
        self._clear_state()
        return state

    # -- project and commands ------------------------------------------------

    async def _must(self, cmd: list[str], timeout: float, what: str) -> str:
        out, rc = await self._run(cmd, timeout)
        if rc != 0:
            raise UpgradeError(f"{what} failed: {_tail(out) or f'exit {rc}'}.")
        return out

    async def _project(self) -> dict:
        """Compose project, paths and running Malcolm containers, from the daemon's labels."""
        fmt = "{{json .Config.Labels}}\t{{.Image}}"
        out = await self._must(
            ["docker", "inspect", DAEMON_CONTAINER, "--format", fmt],
            60,
            "Reading the daemon's container",
        )
        labels_json, image = out.strip().rsplit("\t", 1)
        labels = json.loads(labels_json)
        try:
            project = labels["com.docker.compose.project"]
            workdir = labels["com.docker.compose.project.working_dir"]
            configs = labels["com.docker.compose.project.config_files"].split(",")
        except KeyError as exc:
            raise UpgradeError(
                f"The daemon wasn't started by docker compose (no {exc} label)."
            ) from exc
        fmt = '{{.Label "com.docker.compose.service"}}\t{{.Names}}\t{{.State}}\t{{.Image}}'
        ps = await self._must(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--format",
                fmt,
            ],
            60,
            "Listing Malcolm's containers",
        )
        services: dict[str, str] = {}
        tags: set[str] = set()
        for line in ps.splitlines():
            svc, name, state, img = (line.split("\t") + ["", "", "", ""])[:4]
            if svc in MALCOLM_SERVICES and state == "running":
                services[svc] = name
                tags.add(tag_of(img))
        if "opensearch" not in services:
            raise UpgradeError(
                "OpenSearch isn't running, so there's nothing safe to update from."
            )
        if len(tags) != 1 or not _TAG_RE.match(next(iter(tags))):
            raise UpgradeError(
                f"Malcolm's containers run different releases ({', '.join(sorted(tags))})."
            )
        fmt = (
            '{{range .Mounts}}{{if eq .Destination "'
            + OPENSEARCH_DATA
            + '"}}{{.Name}}{{end}}{{end}}'
        )
        volume = (
            await self._must(
                ["docker", "inspect", services["opensearch"], "--format", fmt],
                60,
                "Reading OpenSearch's data volume",
            )
        ).strip()
        if not volume:
            raise UpgradeError(
                "OpenSearch's data isn't on a Docker volume, so it can't be backed up here."
            )
        ordered = {s: services[s] for s in MALCOLM_SERVICES if s in services}
        return {
            "project": project,
            "workdir": workdir,
            "configs": configs,
            "image": image,
            "repo": os.path.dirname(workdir.rstrip("/")),
            "services": ordered,
            "tag": next(iter(tags)),
            "data_volume": volume,
            "backup_volume": f"{volume}-before-update",
        }

    def _compose(self, p: dict, tag: str, *args: str) -> list[str]:
        files = [arg for f in p["configs"] for arg in ("-f", f)]
        return [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "docker",
            "-v",
            "/var/run/docker.sock:/var/run/docker.sock",
            "-v",
            f"{p['repo']}:{p['repo']}",
            "-w",
            p["workdir"],
            "-e",
            f"MALCOLM_IMAGE_TAG={tag}",
            p["image"],
            "compose",
            "-p",
            p["project"],
            *files,
            *args,
        ]

    def _in_helper(
        self, p: dict, mounts: list[str], entrypoint: str, *args: str
    ) -> list[str]:
        vols = [arg for m in mounts for arg in ("-v", m)]
        return [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            entrypoint,
            *vols,
            p["image"],
            *args,
        ]

    # -- steps -----------------------------------------------------------------

    async def _check_disk(self, p: dict) -> None:
        script = "du -sk /d | cut -f1; df -Pk /d | awk 'NR==2{print $4}'"
        out = await self._must(
            self._in_helper(p, [f"{p['data_volume']}:/d:ro"], "sh", "-c", script),
            STEP_TIMEOUT_S,
            "Measuring OpenSearch's data",
        )
        used_kb, free_kb = (int(n) for n in out.split()[:2])
        need_kb = used_kb + IMAGE_HEADROOM_KB
        if free_kb < need_kb:
            raise UpgradeError(
                f"Not enough disk space: the update needs {need_kb // 1048576} GB free (a copy of "
                f"OpenSearch's {used_kb // 1048576} GB of data plus the new images), and {free_kb // 1048576} GB is."
            )

    async def _pull(self, p: dict, tag: str) -> None:
        pulled = [s for s in p["services"] if s not in BUILT_SERVICES]
        await self._must(
            self._compose(p, tag, "pull", *pulled),
            PULL_TIMEOUT_S,
            f"Downloading Malcolm {tag}",
        )

    async def _build(self, p: dict, tag: str) -> None:
        built = [s for s in p["services"] if s in BUILT_SERVICES]
        if built:
            await self._must(
                self._compose(p, tag, "build", *built),
                BUILD_TIMEOUT_S,
                f"Building zeek-live on Malcolm {tag}",
            )

    async def _stop(self, p: dict, services: tuple[str, ...]) -> None:
        names = [p["services"][s] for s in services if s in p["services"]]
        await self._must(
            ["docker", "stop", "-t", "120", *names],
            STEP_TIMEOUT_S,
            "Stopping OpenSearch and its log pipeline",
        )

    async def _copy(self, p: dict, src: str, dst: str) -> None:
        await self._must(
            ["docker", "volume", "create", dst], 60, f"Creating volume {dst}"
        )
        script = "find /to -mindepth 1 -delete && cp -a /from/. /to/"
        mounts = [f"{src}:/from:ro", f"{dst}:/to"]
        await self._must(
            self._in_helper(p, mounts, "sh", "-c", script),
            COPY_TIMEOUT_S,
            f"Copying OpenSearch's data to {dst}",
        )

    async def _set_tag(self, p: dict, tag: str) -> None:
        env = os.path.join(p["workdir"], ".env")
        cmd = self._in_helper(
            p, [f"{p['workdir']}:{p['workdir']}"], "python3", "-c", _SET_TAG, env, tag
        )
        await self._must(cmd, 60, f"Writing MALCOLM_IMAGE_TAG={tag} to {env}")

    async def _up(self, p: dict, tag: str, services: list[str]) -> None:
        if services:
            await self._must(
                self._compose(p, tag, "up", "-d", "--no-deps", "--no-build", *services),
                STEP_TIMEOUT_S,
                f"Starting {', '.join(services)}",
            )

    async def _remove_volume(self, volume: str) -> None:
        out, rc = await self._run(["docker", "volume", "rm", volume], 120)
        if rc != 0:  # the update itself is done; say so in the log, not as a failure
            logger.warning("Couldn't remove backup volume %s: %s", volume, _tail(out))

    # -- checks ------------------------------------------------------------------

    async def _poll(
        self, check: Callable[[], Awaitable[str | None]], timeout: float
    ) -> str | None:
        """Run check every POLL_S s until it reports no problem (None) or timeout passes."""
        waited = 0.0
        while True:
            problem = await check()
            if problem is None or waited >= timeout:
                return problem
            await self._sleep(POLL_S)
            waited += POLL_S

    async def _wait_login(self, p: dict) -> None:
        cmd = [
            "docker",
            "exec",
            p["services"]["opensearch"],
            "curl",
            "--config",
            CURLRC,
            "--insecure",
            "--silent",
            "--fail",
            "--max-time",
            "10",
            "https://localhost:9200/_cluster/health",
        ]

        async def check() -> str | None:
            out, rc = await self._run(cmd, 30)
            if rc != 0:
                return "OpenSearch didn't accept NetTap's login"
            try:
                status = json.loads(out).get("status")
            except ValueError:
                return "OpenSearch's health answer wasn't readable"
            return (
                None
                if status in ("green", "yellow")
                else f"OpenSearch's cluster is {status}"
            )

        problem = await self._poll(check, LOGIN_TIMEOUT_S)
        if problem:
            raise UpgradeError(
                f"{problem} within {LOGIN_TIMEOUT_S // 60} minutes of starting."
            )

    async def _wait_healthy(self, p: dict, tag: str) -> None:
        fmt = "{{.Name}}\t{{.State.Status}}\t{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}\t{{.Config.Image}}"
        cmd = ["docker", "inspect", "--format", fmt, *p["services"].values()]

        async def check() -> str | None:
            out, rc = await self._run(cmd, 60)
            if rc != 0:
                return f"docker inspect failed ({_tail(out, 200)})"
            bad = []
            for line in out.splitlines():
                name, state, health, image = (line.split("\t") + ["", "", "", ""])[:4]
                if (
                    state != "running"
                    or health not in ("healthy", "none")
                    or tag_of(image) != tag
                ):
                    bad.append(
                        f"{name.lstrip('/')} {state}/{health} on {tag_of(image) or '?'}"
                    )
            return "; ".join(bad) or None

        problem = await self._poll(check, HEALTHY_TIMEOUT_S)
        if problem:
            raise UpgradeError(
                f"Not every container was running and healthy on {tag} after {HEALTHY_TIMEOUT_S // 60} minutes: {problem}."
            )

    def _count(self, provider: str, since_iso: str) -> int:
        query = {
            "bool": {
                "filter": [
                    {"term": {"event.provider": provider}},
                    {"range": {"@timestamp": {"gte": since_iso}}},
                ]
            }
        }
        return int(
            self._client.count(index=SESSIONS_INDEX, body={"query": query})["count"]
        )

    def _arriving_now(self) -> set[str]:
        """What arrived in the minutes before the update: the checks after it ask for the same."""
        expected: set[str] = set()
        if self._client is not None:
            since = (self._now() - timedelta(seconds=RECENT_S)).isoformat()
            for provider in _PROVIDERS:
                try:
                    if self._count(provider, since) > 0:
                        expected.add(provider)
                except Exception as exc:
                    raise UpgradeError(
                        f"Couldn't count the {_PROVIDERS[provider]} records arriving now ({exc})."
                    ) from exc
        mtime = self._pcap_mtime()
        if mtime is not None and self._now().timestamp() - mtime < PCAP_RECENT_S:
            expected.add("pcap")
        return expected

    async def _wait_arrivals(self, expected: set[str], since: datetime) -> None:
        async def check() -> str | None:
            missing = []
            for provider, label in _PROVIDERS.items():
                if provider in expected:
                    try:
                        count = await asyncio.to_thread(
                            self._count, provider, since.isoformat()
                        )
                    except Exception as exc:
                        return f"couldn't count {label} records ({exc})"
                    if count == 0:
                        missing.append(f"no new {label} records")
            if "pcap" in expected:
                mtime = self._pcap_mtime()
                if mtime is None or mtime <= since.timestamp():
                    missing.append("no new PCAP")
            return ", ".join(missing) or None

        problem = await self._poll(check, ARRIVAL_TIMEOUT_S)
        if problem:
            raise UpgradeError(
                f"Capture didn't resume within {ARRIVAL_TIMEOUT_S // 60} minutes of the restart: "
                f"{problem} (they were arriving before the update)."
            )

    # -- rollback and state --------------------------------------------------------

    async def _rollback(
        self, p: dict, old: str, target: str, copied: bool, step: "_Steps"
    ) -> str:
        names = [p["services"][s] for s in STOPPED_FOR_BACKUP if s in p["services"]]
        try:
            step(f"Rolling back to Malcolm {old}", advance=False)
            await self._run(
                ["docker", "stop", "-t", "120", *names], STEP_TIMEOUT_S
            )  # some may be gone
            await self._set_tag(p, old)
            if copied:
                await self._copy(p, p["backup_volume"], p["data_volume"])
            await self._up(p, old, ["opensearch"])
            await self._wait_login(p)
            await self._up(p, old, [s for s in p["services"] if s != "opensearch"])
            await self._wait_healthy(p, old)
        except UpgradeError as exc:
            self._save_state(old, target, p, "rollback_failed", str(exc))
            kept = (
                f" OpenSearch's data from before the update is in Docker volume {p['backup_volume']}."
                if copied
                else ""
            )
            return f"Rolling back to Malcolm {old} failed too: {exc}{kept}"
        if copied:
            await self._remove_volume(p["backup_volume"])
        self._clear_state()
        if copied:
            return (
                f"NetTap rolled back to Malcolm {old} and restored OpenSearch's data from before the "
                "update (records that arrived during the attempt weren't kept)."
            )
        return f"NetTap restarted Malcolm {old}."

    def _save_state(
        self, old: str, target: str, p: dict, step: str, error: str | None = None
    ) -> None:
        state = {
            "old_version": old,
            "new_version": target,
            "step": step,
            "error": error,
            "backup_volume": p["backup_volume"],
            "at": self._now().isoformat(),
        }
        try:
            os.makedirs(os.path.dirname(self._state_file), exist_ok=True)
            with open(self._state_file, "w") as fh:
                json.dump(state, fh)
        except OSError as exc:
            logger.warning(
                "Couldn't save the Malcolm update's state to %s: %s",
                self._state_file,
                exc,
            )

    def _clear_state(self) -> None:
        try:
            os.remove(self._state_file)
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("Couldn't remove %s: %s", self._state_file, exc)


_PROVIDERS = {"zeek": "Zeek", "suricata": "Suricata"}


class _Steps:
    """Reports each step's name with how many steps came before it."""

    def __init__(self, on_step: OnStep | None, total: int) -> None:
        self._on_step, self._total, self._done = on_step, total, 0

    def __call__(self, name: str, advance: bool = True) -> None:
        logger.info("Malcolm update: %s", name)
        if self._on_step is not None:
            self._on_step(name, min(self._done, self._total), self._total)
        if advance:
            self._done += 1


def _result(success: bool, old: str, new: str, error: str | None) -> dict:
    return {
        "success": success,
        "old_version": old,
        "new_version": new,
        "error": error,
        "rolled_back": False,
    }
