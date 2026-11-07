"""Owner rules: save, test with Suricata, load (NET-191 slice 3).

The rules live in owner.rules on the suricata-custom-rules volume: rw here, ro in suricata-live at
Malcolm's custom rules dir, whose *.rules files Suricata loads at start. The volume holds only
owner.rules and owner.rules.prev; a save writes a temp file (".owner.rules.<random>") and renames
it, so an interrupted save never leaves a second *.rules file.

A save holds the rules lock (and the daemon's rule-operation lock) from start to end:
  1. snapshot Suricata's config into nettap-rules-staging/<uuid>/ with the candidate as the only
     custom rule file (staging is never mounted in suricata-live, so nothing there is ever loaded)
  2. in a throwaway container of the live image (live UID/GID, no network, 1 GiB, 1 CPU, 180 s):
     Suricata's own test (-T) of the installed rules plus the candidate (exit 0, "0 rules failed"),
     then an engine analysis of the candidate alone with Lua off: every rule must load and no
     keyword Suricata parsed may be a forbidden one
  3. keep owner.rules.prev, rename the candidate into place, blocking reload, 0 failed rules
  4. any failure after the rename puts the previous rules back and reloads them
Logs carry counts and results, never rule text.
"""

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import time
import uuid
from typing import Any, NoReturn

from api.offload import run_blocking
from services import rules_lock
from services.capture_config import write_file_atomic
from services.etpro import _run
from services.malcolm_upgrade import DAEMON_CONTAINER
from services.owner_rules_validator import FORBIDDEN, MAX_BYTES, MAX_RULES, validate
from services.rules_lock import RulesBusyError
from services.suricata_rules import SuricataRuleManager, _engine_answer

logger = logging.getLogger("nettap.services.owner_rules")

CUSTOM_DIR = os.environ.get(
    "NETTAP_CUSTOM_RULES_DIR", "/var/lib/nettap-suricata-custom"
)
STAGING_DIR = os.environ.get(
    "NETTAP_RULES_STAGING_DIR", "/var/lib/nettap-rules-staging"
)
OWNER, PREV = "owner.rules", "owner.rules.prev"
LIVE_CUSTOM_DIR = "/opt/suricata/rules/custom"  # where suricata-live mounts the volume
LIVE_RULES_DIR = "/var/lib/suricata/rules"
SNAPSHOT_DIRS = (
    ("/etc/suricata", "etc-suricata"),
    ("/opt/suricata/include-configs", "include-configs"),
)
SOCKET = "/var/run/suricata/suricata-command.socket"
THRESHOLD_FILE = "/etc/nettap/suricata-threshold.config"
ANALYSIS_DIR = "/tmp/owner-analysis"  # a tmpfs in the test container
# The web proxy waits 290 s. On the G11 (65k rules) the test loads in ~20 s at 1 CPU and a reload
# takes 24-53 s, so a save is about a minute; only stacked worst cases outlast the proxy, and then
# the daemon still finishes and the live status shows the outcome
LOCK_WAIT_S = 30
TEST_TIMEOUT_S = 180
RELOAD_TIMEOUT_S = 120
RELOAD_RETRY_S = 5
INSPECT_TIMEOUT_S = 20
COPY_TIMEOUT_S = 60
REMOVE_TIMEOUT_S = 30
STATS_TIMEOUT_S = 20
STALE_AFTER_S = 3600
YAML_MAX_BYTES = 4 * 1024 * 1024
TEST_MEMORY, TEST_CPUS, ANALYSIS_TMPFS = "1g", "1", "size=64m"
# "$@" is the config and its overrides. The analysis exits 0 even when a rule fails to load, so a
# missing rule shows as a count short
TEST_SH = (
    '/usr/bin/suricata -T -v -l /tmp "$@" || exit "$?"\n'
    f'/usr/bin/suricata --engine-analysis -S {LIVE_CUSTOM_DIR}/{OWNER} -l {ANALYSIS_DIR} "$@" '
    '--set security.lua.allow-rules=false >/dev/null 2>&1 || exit "$?"\n'
    f"cat {ANALYSIS_DIR}/rules.json 2>/dev/null\n"
    "exit 0\n"
)
_FAILED_RE = re.compile(r"\b0 rules failed\b")
_AT_LINE_RE = re.compile(r"from file \S*/" + re.escape(OWNER) + r" at line (\d+)")


class OwnerRulesError(Exception):
    """A save that changed nothing (or was put back): the message and status for the API."""

    def __init__(self, message: str, status: int, errors: list | None = None):
        super().__init__(message)
        self.status = status
        self.errors = errors or []


def summary(errors: list[dict[str, Any]], lead: str = "Nothing was saved") -> str:
    more = f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""
    return f"{lead}: {errors[0]['message']}{more}"


def _error_lines(output: str) -> list[str]:
    """Suricata's error lines ("E: module: reason" or "Error: module: reason")."""
    return [line for line in output.splitlines() if line.startswith(("Error: ", "E: "))]


def suricata_errors(output: str) -> list[dict[str, Any]]:
    """Suricata's -T complaints about owner.rules as [{"line", "message"}]: the reason line it
    prints just before 'error parsing signature … at line N'."""
    errors: list[dict[str, Any]] = []
    reason = ""
    for line in _error_lines(output):
        text = line.split(": ", 2)[-1].strip()
        found = _AT_LINE_RE.search(line)
        if found:
            errors.append({"line": int(found.group(1)), "message": reason or text})
            reason = ""
        elif "error parsing signature" not in line:
            reason = text
    return errors


def _keywords(node: Any) -> set[str]:
    """Every "name" (a keyword or buffer) and "flags" value in an engine analysis entry."""
    if isinstance(node, list):
        return set().union(*map(_keywords, node))
    if not isinstance(node, dict):
        return set()
    found = {node["name"]} if isinstance(node.get("name"), str) else set()
    flags = node.get("flags")
    if isinstance(flags, list):
        found |= {flag for flag in flags if isinstance(flag, str)}
    return found.union(*map(_keywords, node.values()))


def analysis_problem(output: str, count: int) -> str | None:
    """Why Suricata's own reading of the owner rules (alone, Lua off) refuses them, or None.
    rules.json has one JSON object per rule; Suricata's log lines never start with "{"."""
    rules = []
    for line in output.splitlines():
        if line.startswith("{"):
            with contextlib.suppress(ValueError):
                rule = json.loads(line)
                if isinstance(rule, dict) and "id" in rule:
                    rules.append(rule)
    used = _keywords(rules) & FORBIDDEN
    if used:
        return f'Suricata reads "{min(used)}" in your rules, and it can\'t be used.'
    if len(rules) != count:
        return (
            f"Only {len(rules)} of your {count} rules load on their own in Suricata. "
            "Lua rules can't be used."
        )
    return None


def _answer(output: str) -> dict[str, Any]:
    try:
        answer = json.loads(output.replace("\n", ""))
    except ValueError:
        return {}
    return answer if isinstance(answer, dict) else {}


def _inside(path: str, parent: str) -> bool:
    path, parent = os.path.realpath(path), os.path.realpath(parent)
    return path == parent or path.startswith(parent + os.sep)


class OwnerRules:
    """The owner's own Suricata rules: read, check, and save through Suricata's test."""

    def __init__(
        self,
        rules: SuricataRuleManager,
        custom_dir: str | None = None,
        staging_dir: str | None = None,
    ):
        self._rules = rules
        self._custom = custom_dir or CUSTOM_DIR
        self._staging = staging_dir or STAGING_DIR
        if _inside(self._staging, self._custom):
            raise ValueError("The staging dir must not be inside the custom rules dir")

    # --- files (blocking: called through run_blocking) -------------------------------------

    def _path(self, name: str) -> str:
        return os.path.join(self._custom, name)

    def _read(self, name: str) -> str:
        try:
            fd = rules_lock.open_regular(self._path(name))
        except FileNotFoundError:
            return ""
        with os.fdopen(fd, "rb") as fh:
            # only this daemon writes the volume, after validate()
            return fh.read().decode("utf-8", errors="replace")

    def _clean_stale(self) -> None:
        if not os.path.isdir(self._staging):
            return
        cutoff = time.time() - STALE_AFTER_S
        with os.scandir(self._staging) as entries:
            for entry in entries:
                if entry.stat(follow_symlinks=False).st_mtime >= cutoff:
                    continue
                if entry.is_dir(follow_symlinks=False):
                    shutil.rmtree(entry.path, ignore_errors=True)
                else:
                    os.unlink(entry.path)

    def _make_stage(self, stage: str, content: str) -> None:
        for _, name in SNAPSHOT_DIRS:
            os.makedirs(os.path.join(stage, name))
        os.makedirs(os.path.join(stage, "custom"))
        write_file_atomic(os.path.join(stage, "custom", OWNER), content)

    @staticmethod
    def _lists_owner(stage: str) -> bool:
        fd = rules_lock.open_regular(
            os.path.join(stage, "etc-suricata", "suricata.yaml")
        )
        with os.fdopen(fd, "rb") as fh:
            return f"{LIVE_CUSTOM_DIR}/{OWNER}".encode() in fh.read(YAML_MAX_BYTES)

    def prepare(self) -> None:
        """At daemon start: an empty owner.rules (suricata-live starts after the daemon is healthy, so
        Malcolm lists it in Suricata's rule files), and no staging dirs older than an hour."""
        if not os.path.isdir(self._custom):
            logger.warning(
                "No custom rules volume at %s; owner rules are off", self._custom
            )
            return
        try:
            with contextlib.suppress(FileExistsError):
                os.close(
                    os.open(
                        self._path(OWNER), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644
                    )
                )
                os.chmod(self._path(OWNER), 0o644)
            self._clean_stale()
        except OSError as exc:
            logger.warning("Owner rules: couldn't prepare (%s)", type(exc).__name__)

    def read(self) -> dict[str, Any]:
        content = self._read(OWNER)
        return {
            "content": content,
            "rule_count": validate(content)[1],
            "max_rules": MAX_RULES,
            "max_bytes": MAX_BYTES,
        }

    # --- locks and Suricata ----------------------------------------------------------------

    @contextlib.asynccontextmanager
    async def _locks(self):
        try:
            await asyncio.wait_for(self._rules.op_lock.acquire(), LOCK_WAIT_S)
        except asyncio.TimeoutError:
            raise RulesBusyError(
                "A Suricata rule update is running. Try again in a few minutes."
            ) from None
        try:
            async with rules_lock.rules_lock(LOCK_WAIT_S):
                yield
        finally:
            self._rules.op_lock.release()

    async def _inspect(self) -> dict[str, str]:
        live_name = self._rules.container_name
        rc, out = await _run(
            "docker", "inspect", live_name, DAEMON_CONTAINER, timeout=INSPECT_TIMEOUT_S
        )
        try:
            live, daemon = json.loads(out) if rc == 0 else (None, None)
            env = dict(e.partition("=")[::2] for e in live["Config"]["Env"])
            uid, gid = env.get("PUID", "1000"), env.get("PGID", "1000")
            if not (uid.isdigit() and gid.isdigit()):
                raise ValueError("PUID/PGID")
            return {
                "image": live["Config"]["Image"],
                "user": f"{uid}:{gid}",
                "rules_volume": next(
                    m["Name"]
                    for m in live["Mounts"]
                    if m["Destination"] == LIVE_RULES_DIR
                ),
                "staging_source": next(
                    m["Source"]
                    for m in daemon["Mounts"]
                    if m["Destination"] == self._staging
                ),
            }
        except (TypeError, ValueError, KeyError, StopIteration):
            raise OwnerRulesError(
                "Couldn't read Suricata's container. Is it running?", 502
            ) from None

    async def _snapshot(self, stage: str, content: str) -> None:
        await run_blocking(self._make_stage, stage, content)
        for src, name in SNAPSHOT_DIRS:
            rc, _ = await _run(
                "docker", "cp", f"{self._rules.container_name}:{src}/.",
                os.path.join(stage, name), timeout=COPY_TIMEOUT_S,
            )  # fmt: skip
            if rc != 0:
                raise OwnerRulesError(
                    "Couldn't copy Suricata's settings to test the rules.", 502
                )
        # Malcolm lists the custom rule files when Suricata starts: without owner.rules in that list a
        # reload would never load the rules
        if not await run_blocking(self._lists_owner, stage):
            raise OwnerRulesError(
                "Suricata was started before your own rules were set up. Restart it "
                "(scripts/remote/deploy-detection-slice3.sh), then save again.",
                409,
            )

    async def _test(self, stage: str, live: dict[str, str], count: int) -> None:
        name = f"nettap-sv-{os.path.basename(stage)}"
        src = os.path.join(live["staging_source"], os.path.basename(stage))
        mounts = [
            f"{src}/etc-suricata:/etc/suricata:ro",
            f"{src}/include-configs:/opt/suricata/include-configs:ro",
            f"{live['rules_volume']}:{LIVE_RULES_DIR}:ro",
            f"{src}/custom:{LIVE_CUSTOM_DIR}:ro",
        ]
        if os.path.isfile(THRESHOLD_FILE) and not os.path.islink(THRESHOLD_FILE):
            mounts.append(f"{THRESHOLD_FILE}:{THRESHOLD_FILE}:ro")
        # /usr/bin/suricata carries file capabilities: exec needs them in the bounding set;
        # no-new-privileges means the process never gets them. -T quotes rule text: no container log
        cmd = ["docker", "run", "--rm", "--name", name, "--network", "none", "--log-driver", "none",
               "--memory", TEST_MEMORY, "--memory-swap", TEST_MEMORY, "--cpus", TEST_CPUS,
               "--user", live["user"], "--tmpfs", f"{ANALYSIS_DIR}:{ANALYSIS_TMPFS}",
               "--cap-drop", "ALL", "--cap-add", "NET_ADMIN", "--cap-add", "NET_RAW",
               "--cap-add", "IPC_LOCK", "--security-opt", "no-new-privileges",
               *[arg for m in mounts for arg in ("-v", m)],
               "--entrypoint", "/bin/sh", live["image"], "-c", TEST_SH, "nettap-test",
               "-c", "/etc/suricata/suricata.yaml",
               # as the replay runner (verify-detection.sh): no socket, no Hyperscan cache dir here
               "--set", "unix-command.enabled=no", "--set", "detect.sgh-mpm-caching=no"]  # fmt: skip
        try:
            rc, out = await _run(*cmd, timeout=TEST_TIMEOUT_S)
        finally:
            # --rm removes it when it exits; after a timeout or a cancel it is still running
            await _run("docker", "rm", "-f", name, timeout=REMOVE_TIMEOUT_S)
        if rc is None:
            raise OwnerRulesError(
                f"Suricata's test didn't finish within {TEST_TIMEOUT_S} s. Nothing was changed.",
                500,
            )
        if rc == 0 and _FAILED_RE.search(out):
            problem = analysis_problem(out, count)
            if problem:
                raise OwnerRulesError(problem, 422)
            return
        errors = suricata_errors(out)
        last = _error_lines(out)[-1:]
        reason = errors[0]["message"] if errors else "".join(last).split(": ", 2)[-1]
        if rc == 1 and reason:
            raise OwnerRulesError(f"Suricata refused the rules: {reason}", 422, errors)
        # docker (125-127), out of memory (137), a crash (139): not about the rules
        raise OwnerRulesError(
            f"Suricata's test couldn't run (exit {rc}). Nothing was changed.", 502
        )

    async def _reload(self) -> tuple[bool, str, dict[str, Any]]:
        """Blocking reload-rules, waiting out one in progress (as nettap-rules-update.sh), then
        0 failed rules."""
        live_name = self._rules.container_name
        deadline = time.monotonic() + RELOAD_TIMEOUT_S
        while True:
            rc, out = await _run(
                "docker", "exec", live_name, "suricatasc", SOCKET, "-c", "reload-rules",
                timeout=RELOAD_TIMEOUT_S,
            )  # fmt: skip
            if rc == 0 and _answer(out).get("return") == "OK":
                break
            if "in progress" not in out or time.monotonic() >= deadline:
                return False, "the reload didn't finish", {}
            await asyncio.sleep(RELOAD_RETRY_S)
        rc, out = await _run(
            "docker", "exec", live_name, "suricatasc", SOCKET, "-c", "ruleset-stats",
            timeout=STATS_TIMEOUT_S,
        )  # fmt: skip
        stats = _engine_answer(out.replace("\n", "")) or {}
        if stats.get("rules_failed") != 0:
            return False, f"{stats.get('rules_failed', '?')} rules failed to load", {}
        return True, "", stats

    async def _put_back(self, previous: str, why: str) -> NoReturn:
        await run_blocking(write_file_atomic, self._path(OWNER), previous)
        try:
            put_back = (await self._reload())[0]
        except Exception:
            put_back = False
        logger.error(
            "Owner rules: load failed (%s); previous rules restored, reload %s",
            why,
            "confirmed" if put_back else "not confirmed",
        )
        raise OwnerRulesError(
            f"Suricata couldn't load the rules ({why}). The previous rules were put back"
            + ("." if put_back else ", but Suricata didn't confirm loading them."),
            502,
        )

    # --- save --------------------------------------------------------------------------------

    async def save(self, content: Any) -> dict[str, Any]:
        if not isinstance(content, str):
            raise OwnerRulesError('Send {"content": "<rules>"}.', 400)
        errors, count = await run_blocking(validate, content)
        if errors:
            raise OwnerRulesError(summary(errors), 400, errors)
        async with self._locks():
            await run_blocking(self._clean_stale)
            live = await self._inspect()
            stage = os.path.join(self._staging, uuid.uuid4().hex)
            try:
                await self._snapshot(stage, content)
                await self._test(stage, live, count)
                logger.info("Owner rules: %d rules passed Suricata's test", count)
                previous = await run_blocking(self._read, OWNER)
                await run_blocking(write_file_atomic, self._path(PREV), previous)
                await run_blocking(write_file_atomic, self._path(OWNER), content)
                try:
                    loaded, why, stats = await self._reload()
                except Exception:
                    loaded, why, stats = False, "the reload failed", {}
                if not loaded:
                    await self._put_back(previous, why)
            finally:
                await run_blocking(shutil.rmtree, stage, True)
        logger.info(
            "Owner rules saved: %d rules; Suricata loaded %s, 0 failed",
            count,
            stats.get("rules_loaded"),
        )
        return {
            "saved": True,
            "rule_count": count,
            "engine": {"loaded": stats.get("rules_loaded"), "failed": 0},
        }
