"""
NetTap Capture Manager Stub

A minimal CaptureManager implementation used as the default in the API
server when the full BridgeCaptureAdapter or MirrorManager has not yet
been initialised (e.g., during early startup or in development).

The stub reads the capture mode from the config file / environment
(via ``load_capture_config``), so the ``/api/capture/mode`` endpoint
returns the correct mode even before the real manager takes over.
Health and stats return safe defaults indicating the stub is active.

When the daemon's ``run()`` coroutine finishes initialising the real
CaptureManager, it can replace ``app["capture_manager"]`` at runtime.
"""

import logging

from services.capture_config import load_capture_config
from services.capture_manager import (
    CaptureHealth,
    CaptureManager,
    CaptureMode,
    CaptureStats,
)

logger = logging.getLogger("nettap.services.capture_mode_stub")


class CaptureManagerStub(CaptureManager):
    """Lightweight stub that satisfies the CaptureManager interface.

    Returns the configured capture mode (from config file or env vars)
    and safe defaults for everything else. All mutating operations
    (setup / teardown) are no-ops.
    """

    def __init__(self) -> None:
        cfg = load_capture_config()
        self._mode = cfg.mode
        # In bridge mode the capture interface is the bridge; in mirror
        # mode it is the mirror NIC.
        if self._mode == CaptureMode.MIRROR:
            self._interface = cfg.interface
        else:
            self._interface = cfg.bridge_name

        logger.info(
            "CaptureManagerStub initialised: mode=%s, interface=%s",
            self._mode.value,
            self._interface,
        )

    # -------------------------------------------------------------------
    # CaptureManager interface
    # -------------------------------------------------------------------

    async def setup(self) -> dict:
        """No-op — the stub does not configure interfaces."""
        logger.debug("CaptureManagerStub.setup() called (no-op)")
        return {"success": True, "stub": True}

    async def teardown(self) -> dict:
        """No-op — the stub does not deconfigure interfaces."""
        logger.debug("CaptureManagerStub.teardown() called (no-op)")
        return {"success": True, "stub": True}

    async def get_health(self) -> CaptureHealth:
        """Return a not-yet-configured health status."""
        return CaptureHealth(
            mode=self._mode.value,
            status="not_configured",
            capture_interface=self._interface,
            link_up=False,
            promisc_enabled=False,
            issues=["Capture manager stub active — real manager not yet initialised"],
            extra={"stub": True},
        )

    def get_capture_interface(self) -> str:
        """Return the configured capture interface name."""
        return self._interface

    async def get_stats(self) -> CaptureStats:
        """Return zeroed-out stats (stub has no live counters)."""
        return CaptureStats(capture_interface=self._interface)

    @property
    def mode(self) -> CaptureMode:
        """The capture mode read from config / environment."""
        return self._mode
