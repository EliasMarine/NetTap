"""Optional ET Pro code for Suricata's rules (NET-191 slice 2).

One store: SURICATA_ETPRO_CODE in /etc/nettap/suricata.env (root, 600). suricata-live's capture env
loader reads it at start and asks for et/pro instead of et/open; each start wipes the enabled sources,
so a saved, replaced or removed code takes effect exactly at the restart this module issues.

Save: check the code's shape, check it with Proofpoint (HEAD on the file suricata-update downloads;
anything but 200 = rejected, nothing changes), then under the rules lock write the file and restart
Suricata; a failed restart puts the previous file back. Readiness is watched in the background and
logged; the page polls status(). The code is never logged, returned, or put in an error message.
"""

import asyncio
import contextlib
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import aiohttp

from services.capture_config import write_file_atomic
from services.rules_lock import RulesBusyError, rules_lock
from services.suricata_rules import SuricataRuleManager

logger = logging.getLogger("nettap.services.etpro")

ETPRO_ENV_FILE = os.environ.get("NETTAP_SURICATA_ENV", "/etc/nettap/suricata.env")
CODE_RE = re.compile(
    r"^[A-Za-z0-9]{16,64}$"
)  # same rule as config/capture/nettap-capture-env.sh
PREFLIGHT_URL = (
    "https://rules.emergingthreatspro.com/{code}/suricata-{version}/etpro.rules.tar.gz"
)
PREFLIGHT_TIMEOUT_S = 10
RESTART_TIMEOUT_S = 120
# The startup update (up to 300 s) runs before Suricata loads its rules
READY_TIMEOUT_S = 900
READY_POLL_S = 10
# The page's request is cut at 290 s (web RULE_UPDATE_TIMEOUT_MS): version 20 + preflight 10 + lock 60 + restart 120
APPLY_LOCK_WAIT_S = 60
VERSION_RE = re.compile(r"version (\d+\.\d+\.\d+)")


class EtProError(Exception):
    """A plain-English reason the change was not made. Never contains the code."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def read_code(path: str | None = None) -> str | None:
    """The saved code, or None (no file, or no valid code in it)."""
    try:
        with open(path or ETPRO_ENV_FILE, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return None
    for line in lines:
        key, _, value = line.partition("=")
        if key == "SURICATA_ETPRO_CODE" and CODE_RE.fullmatch(value):
            return value
    return None


async def _run(*cmd: str, timeout: float) -> tuple[int | None, str]:
    """(exit code, output); the code is None when the command was stopped after `timeout`."""
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        # OLD CODE START — NET-191 slice 3 review: -1 is also a process killed by SIGHUP; callers
        # told a timeout apart by its text
        # return -1, f"no answer in {int(timeout)} s"
        # OLD CODE END
        return None, f"no answer in {int(timeout)} s"
    return proc.returncode or 0, (out or b"").decode("utf-8", errors="replace").strip()


async def preflight(code: str, version: str) -> int | None:
    """Proofpoint's HTTP status for the file suricata-update would download, or None if unreachable."""
    url = PREFLIGHT_URL.format(code=code, version=version)
    try:
        timeout = aiohttp.ClientTimeout(total=PREFLIGHT_TIMEOUT_S)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # OLD CODE START — NET-191 slice 2 review: a HEAD can be refused where the GET it stands for is not
            # async with session.head(url, allow_redirects=True) as resp:
            #     return resp.status
            # OLD CODE END
            # A one-byte GET: what suricata-update does (a signed redirect may allow GET only); the body is not read
            async with session.get(
                url, headers={"Range": "bytes=0-0"}, allow_redirects=True
            ) as resp:
                return resp.status
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        # exception text can carry the URL, so only its type is logged
        logger.warning(
            "ET Pro preflight: Proofpoint unreachable (%s)", type(exc).__name__
        )
        return None


def _rejection(status: int | None) -> str:
    if status is None:
        return "Couldn't reach Proofpoint to check the code. Check the internet connection and try again."
    if status in (401, 403, 404):
        return f"Proofpoint didn't accept this code (HTTP {status}). Check it and try again."
    return f"Proofpoint answered HTTP {status}, so the code was not saved. Try again later."


class EtProManager:
    """Save, replace or remove the ET Pro code and restart Suricata with it."""

    def __init__(self, rules: SuricataRuleManager, env_file: str | None = None):
        self._rules = rules
        self._env_file = env_file or ETPRO_ENV_FILE
        self._watch: asyncio.Task | None = None
        self._activation: dict[str, Any] | None = None

    async def _suricata_version(self) -> str:
        rc, out = await _run(
            "docker",
            "exec",
            self._rules.container_name,
            "suricata-offline",
            "-V",
            timeout=20,
        )
        match = VERSION_RE.search(out) if rc == 0 else None
        if not match:
            raise EtProError(
                "Couldn't read Suricata's version to check the code. Is Suricata running?",
                502,
            )
        return match.group(1)

    async def save(self, code: str) -> None:
        if not isinstance(code, str) or not CODE_RE.fullmatch(
            code
        ):  # match() takes "code\n"
            raise EtProError("An ET Pro code is 16 to 64 letters and digits.")
        status = await preflight(code, await self._suricata_version())
        logger.info(
            "ET Pro preflight: %s", f"HTTP {status}" if status else "unreachable"
        )
        # OLD CODE START — NET-191 slice 2 review: the ranged GET answers 206
        # if status != 200:
        # OLD CODE END
        if status not in (200, 206):
            raise EtProError(_rejection(status))
        await self._apply(f"SURICATA_ETPRO_CODE={code}\n")
        logger.info("ET Pro code saved; Suricata restarted to load it")

    async def clear(self) -> bool:
        """Remove the code and restart Suricata. False when no code was saved."""
        if not os.path.exists(self._env_file):
            return False
        await self._apply(None)
        logger.info("ET Pro code cleared; Suricata restarted with ET Open")
        return True

    async def _apply(self, content: str | None) -> None:
        """Write (or remove) the env file and restart Suricata, holding the rules lock; a failed
        restart restores the previous file. RulesBusyError passes through."""
        # An "Update now" can hold op_lock for 270 s: answer "busy" at once instead of outliving the page's request
        if self._rules.op_lock.locked():
            raise RulesBusyError(
                "A Suricata rule update is running. Try again in a few minutes."
            )
        async with self._rules.op_lock, rules_lock(APPLY_LOCK_WAIT_S):
            try:
                with open(self._env_file, encoding="utf-8") as fh:
                    previous: str | None = fh.read()
            except FileNotFoundError:
                previous = None
            self._set_file(content)
            started = datetime.now(timezone.utc)
            rc, out = await _run(
                "docker",
                "restart",
                self._rules.container_name,
                timeout=RESTART_TIMEOUT_S,
            )
            if rc != 0:
                self._set_file(previous)
                logger.error(
                    "ET Pro change: Suricata didn't restart (rc=%s): %s; previous setting kept",
                    rc,
                    out[:200],
                )
                # OLD CODE: f"Suricata didn't restart ({out[:200] or f'exit {rc}'}). Nothing was changed." (D4: docker's output)
                raise EtProError(
                    f"Suricata didn't restart (exit {rc}). Nothing was changed.",
                    502,
                )
        self._activation = None
        if self._watch and not self._watch.done():
            self._watch.cancel()  # it would record the earlier change's outcome over this one's
        self._watch = asyncio.create_task(self._await_activation(started))

    def _set_file(self, content: str | None) -> None:
        if content is None:
            with contextlib.suppress(FileNotFoundError):
                os.remove(self._env_file)
        else:
            write_file_atomic(self._env_file, content, mode=0o600)

    async def _await_activation(self, started: datetime) -> None:
        """Wait until the restarted engine has loaded its rules, then log and keep the result."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + READY_TIMEOUT_S
        live: dict[str, Any] = {}
        ready = False
        while loop.time() < deadline:
            await asyncio.sleep(READY_POLL_S)
            live = await self._rules.get_live_status()
            loaded_at = (live.get("engine") or {}).get("reload_time")
            if loaded_at and _after(loaded_at, started):
                ready = True
                break
        engine = live.get("engine") or {}
        update = live.get("update") or {}
        sources = live.get("enabled_sources") or []
        etpro = live.get("etpro_rules") or 0
        if not ready:
            state, message = (
                "timeout",
                "Suricata hadn't loaded its rules 15 minutes after the restart.",
            )
        elif (
            "et/pro" in sources
            and etpro
            and update.get("state") in ("active", "prepared")
        ):
            state, message = "active", f"{etpro} ET Pro rules are active."
        elif self._configured():
            state = "failed"
            message = (
                f"ET Pro isn't active: the rule update says {update.get('state', 'unknown')}"
                + (f" ({update['reason']})" if update.get("reason") else "")
                + ". Suricata keeps the last good rules."
            )
        else:
            state, message = "active", "Suricata runs without ET Pro."
        self._activation = {
            "state": state,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "rules_loaded": engine.get("loaded"),
            "rules_failed": engine.get("failed"),
            "etpro_rules": etpro,
            "enabled_sources": sources,
            "update_state": update.get("state", "unknown"),
            "message": message,
        }
        logger.info(
            "ET Pro activation result: %s; %s rules loaded, %s failed, %d ET Pro rules, sources %s, update %s",
            state,
            engine.get("loaded"),
            engine.get("failed"),
            etpro,
            ",".join(sources) or "none",
            update.get("state", "unknown"),
        )

    def _configured(self) -> bool:
        return read_code(self._env_file) is not None

    async def status(self) -> dict[str, Any]:
        live = await self._rules.get_live_status()
        update = live.get("update") or {}
        state = update.get("state", "unknown")
        return {
            "configured": self._configured(),
            "active": "et/pro" in (live.get("enabled_sources") or [])
            and bool(live.get("etpro_rules")),
            "last_update_ok": None
            if state == "unknown"
            else state in ("active", "prepared"),
            "applying": bool(self._watch and not self._watch.done()),
            "activation": self._activation,
        }


def _after(engine_time: str, started: datetime) -> bool:
    try:
        loaded = datetime.fromisoformat(engine_time)
    except ValueError:
        return False
    return (loaded if loaded.tzinfo else loaded.replace(tzinfo=timezone.utc)) >= started
