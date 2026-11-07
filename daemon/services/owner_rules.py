"""Owner rules: save, test with Suricata, load (NET-191 slice 3).

The rules live in owner.rules on the suricata-custom-rules volume: rw here, ro in suricata-live at
Malcolm's custom rules dir, whose *.rules files Suricata loads at start. The volume holds only
owner.rules and owner.rules.prev; a save writes .owner.rules.tmp-<uuid> and renames it, so an
interrupted save never leaves a second *.rules file.

A save holds the rules lock (and the daemon's rule-operation lock) from start to end:
  1. snapshot Suricata's config into nettap-rules-staging/<uuid>/ with the candidate as the only
     custom rule file (staging is never mounted in suricata-live, so nothing there is ever loaded)
  2. Suricata's own test (-T) in a throwaway container of the live image: the installed rules plus
     the candidate, live UID/GID, no network, 1 GiB, 1 CPU, 180 s; exit 0 and "0 rules failed"
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
from typing import Any

from services import rules_lock
from services.etpro import _run
from services.owner_rules_validator import MAX_BYTES, MAX_RULES, validate
from services.rules_lock import RulesBusyError
from services.suricata_rules import SuricataRuleManager

logger = logging.getLogger("nettap.services.owner_rules")

CUSTOM_DIR = os.environ.get(
    "NETTAP_CUSTOM_RULES_DIR", "/var/lib/nettap-suricata-custom"
)
STAGING_DIR = os.environ.get(
    "NETTAP_RULES_STAGING_DIR", "/var/lib/nettap-rules-staging"
)
DAEMON_CONTAINER = os.environ.get("NETTAP_DAEMON_CONTAINER", "nettap-storage-daemon")
OWNER, PREV = "owner.rules", "owner.rules.prev"
LIVE_CUSTOM_DIR = "/opt/suricata/rules/custom"  # where suricata-live mounts the volume
LIVE_RULES_DIR = "/var/lib/suricata/rules"
SOCKET = "/var/run/suricata/suricata-command.socket"
THRESHOLD_FILE = "/etc/nettap/suricata-threshold.config"
# The web proxy waits 290 s. On the G11 (65k rules) the test loads in ~20 s at 1 CPU and a reload
# takes 24-53 s, so a save is about a minute; only stacked worst cases outlast the proxy, and then
# the daemon still finishes and the live status shows the outcome
LOCK_WAIT_S = 30
TEST_TIMEOUT_S = 180
RELOAD_TIMEOUT_S = 120
STALE_AFTER_S = 3600
_FAILED_RE = re.compile(r"\b0 rules failed\b")
_AT_LINE_RE = re.compile(r"from file \S*/" + re.escape(OWNER) + r" at line (\d+)")


class OwnerRulesError(Exception):
    """A save that changed nothing (or was put back): the message and status for the API."""

    def __init__(self, message: str, status: int, errors: list | None = None):
        super().__init__(message)
        self.status = status
        self.errors = errors or []


def summary(errors: list[dict[str, Any]]) -> str:
    more = f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""
    return f"Nothing was saved: {errors[0]['message']}{more}"


def suricata_errors(output: str) -> list[dict[str, Any]]:
    """Suricata's -T complaints about owner.rules as [{"line", "message"}]: the reason line it
    prints just before 'error parsing signature … at line N'."""
    errors: list[dict[str, Any]] = []
    reason = ""
    for line in output.splitlines():
        if not line.startswith(("Error: ", "E: ")):
            continue
        text = line.split(": ", 2)[-1].strip()
        found = _AT_LINE_RE.search(line)
        if found:
            errors.append({"line": int(found.group(1)), "message": reason or text})
            reason = ""
        elif "error parsing signature" not in line:
            reason = text
    return errors


def _json_answer(output: str) -> dict[str, Any]:
    for line in output.splitlines():
        with contextlib.suppress(ValueError):
            answer = json.loads(line)
            if isinstance(answer, dict):
                return answer
    return {}


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

    # --- files -----------------------------------------------------------------------------

    def _path(self, name: str) -> str:
        return os.path.join(self._custom, name)

    def _read(self, name: str) -> bytes:
        try:
            fd = rules_lock.open_regular(self._path(name))
        except FileNotFoundError:
            return b""
        with os.fdopen(fd, "rb") as fh:
            return fh.read()  # only this daemon writes the volume, after validate()

    def _write(self, name: str, data: bytes) -> None:
        """Replace name atomically; the temp name never matches *.rules."""
        tmp = self._path(f".{OWNER}.tmp-{uuid.uuid4().hex}")
        try:
            fd = os.open(
                tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644
            )
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, 0o644)  # Suricata reads it as its own user
            os.replace(tmp, self._path(name))
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)

    def _clean_stale(self) -> None:
        cutoff = time.time() - STALE_AFTER_S
        with os.scandir(self._staging) as entries:
            for entry in entries:
                if entry.stat(follow_symlinks=False).st_mtime >= cutoff:
                    continue
                if entry.is_dir(follow_symlinks=False):
                    shutil.rmtree(entry.path, ignore_errors=True)
                else:
                    os.unlink(entry.path)

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
            if os.path.isdir(self._staging):
                self._clean_stale()
        except OSError as exc:
            logger.warning("Owner rules: couldn't prepare (%s)", type(exc).__name__)

    def read(self) -> dict[str, Any]:
        content = self._read(OWNER).decode("utf-8", errors="replace")
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
            "docker", "inspect", live_name, DAEMON_CONTAINER, timeout=20
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

    async def _snapshot(self, stage: str, data: bytes) -> None:
        live_name = self._rules.container_name
        for src, name in (
            ("/etc/suricata", "etc-suricata"),
            ("/opt/suricata/include-configs", "include-configs"),
        ):
            os.makedirs(os.path.join(stage, name))
            rc, _ = await _run(
                "docker",
                "cp",
                f"{live_name}:{src}/.",
                os.path.join(stage, name),
                timeout=60,
            )
            if rc != 0:
                raise OwnerRulesError(
                    "Couldn't copy Suricata's settings to test the rules.", 502
                )
        os.makedirs(os.path.join(stage, "custom"))
        with open(os.path.join(stage, "custom", OWNER), "wb") as fh:
            fh.write(data)
        os.chmod(os.path.join(stage, "custom", OWNER), 0o644)
        # Malcolm lists the custom rule files when Suricata starts: without owner.rules in that list a
        # reload would never load the rules
        fd = rules_lock.open_regular(
            os.path.join(stage, "etc-suricata", "suricata.yaml")
        )
        with os.fdopen(fd, "rb") as fh:
            listed = f"{LIVE_CUSTOM_DIR}/{OWNER}".encode() in fh.read(4 * 1024 * 1024)
        if not listed:
            raise OwnerRulesError(
                "Suricata was started before your own rules were set up. Restart it "
                "(scripts/remote/deploy-detection-slice3.sh), then save again.",
                409,
            )

    async def _test(self, stage: str, live: dict[str, str]) -> None:
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
        # no-new-privileges means the process never gets them
        cmd = ["docker", "run", "--rm", "--name", name, "--network", "none",
               "--memory", "1g", "--memory-swap", "1g", "--cpus", "1", "--user", live["user"],
               "--cap-drop", "ALL", "--cap-add", "NET_ADMIN", "--cap-add", "NET_RAW",
               "--cap-add", "IPC_LOCK", "--security-opt", "no-new-privileges",
               *[arg for m in mounts for arg in ("-v", m)],
               "--entrypoint", "/usr/bin/suricata", live["image"],
               "-T", "-v", "-c", "/etc/suricata/suricata.yaml", "-l", "/tmp",
               # as the replay runner (verify-detection.sh): no socket, no Hyperscan cache dir here
               "--set", "unix-command.enabled=no", "--set", "detect.sgh-mpm-caching=no"]  # fmt: skip
        try:
            rc, out = await _run(*cmd, timeout=TEST_TIMEOUT_S)
        finally:
            # --rm removes it when it exits; after a timeout or a cancel it is still running
            await _run("docker", "rm", "-f", name, timeout=30)
        if rc == -1 and out.startswith("no answer"):
            raise OwnerRulesError(
                f"Suricata's test didn't finish within {TEST_TIMEOUT_S} s. Nothing was changed.",
                500,
            )
        if rc == 0 and _FAILED_RE.search(out):
            return
        errors = suricata_errors(out)
        reason = errors[0]["message"] if errors else f"its test exited {rc}"
        raise OwnerRulesError(f"Suricata refused the rules: {reason}", 422, errors)

    async def _reload(self) -> tuple[bool, str, dict[str, Any]]:
        live_name = self._rules.container_name
        rc, out = await _run(
            "docker", "exec", live_name, "suricatasc", SOCKET, "-c", "reload-rules",
            timeout=RELOAD_TIMEOUT_S,
        )  # fmt: skip
        if rc != 0 or _json_answer(out).get("return") != "OK":
            return False, "the reload didn't finish", {}
        rc, out = await _run(
            "docker", "exec", live_name, "suricatasc", SOCKET, "-c", "ruleset-stats",
            timeout=20,
        )  # fmt: skip
        message = _json_answer(out).get("message")
        stats = (message[0] if isinstance(message, list) and message else message) or {}
        if not isinstance(stats, dict) or stats.get("rules_failed") != 0:
            failed = stats.get("rules_failed", "?") if isinstance(stats, dict) else "?"
            return False, f"{failed} rules failed to load", {}
        return True, "", stats

    # --- save --------------------------------------------------------------------------------

    async def save(self, content: Any) -> dict[str, Any]:
        if not isinstance(content, str):
            raise OwnerRulesError('Send {"content": "<rules>"}.', 400)
        errors, count = validate(content)
        if errors:
            raise OwnerRulesError(summary(errors), 400, errors)
        data = content.encode("utf-8")
        async with self._locks():
            if os.path.isdir(self._staging):
                self._clean_stale()
            live = await self._inspect()
            stage = os.path.join(self._staging, uuid.uuid4().hex)
            try:
                await self._snapshot(stage, data)
                await self._test(stage, live)
                logger.info("Owner rules: %d rules passed Suricata's test", count)
                previous = self._read(OWNER)
                self._write(PREV, previous)
                self._write(OWNER, data)
                try:
                    loaded, why, stats = await self._reload()
                except Exception:
                    loaded, why, stats = False, "the reload failed", {}
                if not loaded:
                    self._write(OWNER, previous)
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
                        + (
                            "."
                            if put_back
                            else ", but Suricata didn't confirm loading them."
                        ),
                        502,
                    )
            finally:
                shutil.rmtree(stage, ignore_errors=True)
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
