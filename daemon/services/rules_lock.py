"""Suricata's rules lock (NET-191 slice 2).

One flock on rules.lock in the nettap-rules-state volume, shared with nettap-rules-update.sh in
suricata-live (startup, nightly and manual rule updates) and the deploy scripts. The daemon takes it
before it restarts or reloads Suricata, so it never does so in the middle of a rule update. It never
holds it while running the update itself (the update takes it).

Python's fcntl.flock is flock(2), the same lock as flock(1) in the shell script.
"""

import asyncio
import contextlib
import fcntl
import logging
import os
import stat

logger = logging.getLogger("nettap.services.rules_lock")

# The daemon mounts the volume at /var/run/nettap-rules (/var/run is /run, a tmpfs, as for daemon-auth)
RULES_STATE_DIR = os.environ.get("NETTAP_RULES_STATE", "/run/nettap-rules")
# Interactive requests must answer before the web proxy's 290 s limit; a nightly update with every
# source takes one to two minutes (the plan's 900 s is the shell side's wait)
LOCK_WAIT_S = 240.0


def open_regular(path: str, flags: int = os.O_RDONLY) -> int:
    """Open a file in the rules state volume, which Malcolm's user owns: no link is followed (nothing is
    created through one), a FIFO can't block the event loop, and only a regular file is accepted."""
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o644)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise OSError(f"{path} is not a regular file")
    return fd


class RulesBusyError(Exception):
    """A rule update or another rule change kept the lock for the whole wait."""


@contextlib.asynccontextmanager
async def rules_lock(wait_s: float = LOCK_WAIT_S):
    """Hold Suricata's rules lock for the block. Raises RulesBusyError after wait_s.

    Without the volume (an install before slice 2) nothing else takes the lock either, so the
    block runs unlocked.
    """
    if not os.path.isdir(RULES_STATE_DIR):
        logger.warning("No %s: running without the rules lock", RULES_STATE_DIR)
        yield
        return
    # OLD CODE START — review round 2: root followed a planted link (creating its target) or blocked on a FIFO
    # fd = os.open(
    #     os.path.join(RULES_STATE_DIR, "rules.lock"), os.O_RDONLY | os.O_CREAT, 0o644
    # )
    # OLD CODE END
    fd = open_regular(
        os.path.join(RULES_STATE_DIR, "rules.lock"), os.O_RDONLY | os.O_CREAT
    )
    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if loop.time() >= deadline:
                    raise RulesBusyError(
                        "A Suricata rule update is running. Try again in a few minutes."
                    ) from None
                await asyncio.sleep(1)
        yield
    finally:
        os.close(fd)  # releases the lock
