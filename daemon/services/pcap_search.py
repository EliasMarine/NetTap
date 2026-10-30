"""
NetTap PcapSearchService — Search and filter captured PCAP files.

Provides PCAP file listing, BPF filter search, packet preview (via tshark),
and filtered PCAP download (via mergecap + tshark).

All TShark/mergecap operations run inside the nettap-tshark container via
``docker exec``, matching the pattern used in TSharkService. TShark is NOT
installed in the daemon container.

PCAP directory is configurable via PCAP_DIR env var (default: /opt/nettap/pcap).
"""

import asyncio
import logging
import os
import re
import shlex
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("nettap.services.pcap_search")

_DEFAULT_PCAP_DIR = os.environ.get("PCAP_DIR", "/opt/nettap/pcap")

# TShark container name and mount path — must match docker-compose.yml
_TSHARK_CONTAINER = "nettap-tshark"
_CONTAINER_PCAP_MOUNT = "/pcap"

# Display filter validation — reject shell metacharacters.
# We allow & and | because Wireshark display filters use && (AND) and || (OR).
# Commands use asyncio.create_subprocess_exec (no shell), so pipes aren't dangerous.
_FILTER_FORBIDDEN = re.compile(r"[;`$]")

# Supported PCAP file extensions
_PCAP_EXTENSIONS = {".pcap", ".pcapng", ".cap"}

# Max concurrent TShark docker exec operations.  Shares the same
# nettap-tshark container (cpus: 0.5) as TSharkService, so keep this
# low to avoid thrashing the CPU budget and hitting timeouts.
_MAX_CONCURRENT_TSHARK = 2


class PcapSearchService:
    """Search and filter captured PCAP files."""

    def __init__(self, pcap_dir: str | None = None) -> None:
        self._pcap_dir = Path(pcap_dir or _DEFAULT_PCAP_DIR)
        self._semaphore = asyncio.Semaphore(_MAX_CONCURRENT_TSHARK)

    def _to_container_path(self, daemon_path: str) -> str:
        """Translate a daemon-side PCAP path to the tshark container path.

        The daemon mounts pcap-data at ``self._pcap_dir`` (e.g. /opt/nettap/pcap).
        The tshark container mounts the same volume at ``/pcap``.
        """
        try:
            relative = Path(daemon_path).relative_to(self._pcap_dir)
        except ValueError:
            # Path is not under our pcap dir — return as-is and let
            # tshark report the error (security validation happens elsewhere).
            return daemon_path
        return f"{_CONTAINER_PCAP_MOUNT}/{relative}"

    # ------------------------------------------------------------------
    # File listing
    # ------------------------------------------------------------------

    def get_available_pcaps(
        self,
        from_ts: str | None = None,
        to_ts: str | None = None,
    ) -> list[dict[str, Any]]:
        """List stored PCAP files with metadata.

        Returns list of dicts with: file, size_bytes, modified, name.
        Optionally filtered by time range based on file modification time.
        """
        if not self._pcap_dir.exists():
            logger.warning("PCAP directory does not exist: %s", self._pcap_dir)
            return []

        from_dt = _parse_iso(from_ts) if from_ts else None
        to_dt = _parse_iso(to_ts) if to_ts else None

        results = []
        for path in self._pcap_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in _PCAP_EXTENSIONS:
                continue

            stat = path.stat()
            modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

            # Time range filter
            if from_dt and modified < from_dt:
                continue
            if to_dt and modified > to_dt:
                continue

            results.append({
                "file": str(path),
                "name": path.name,
                "size_bytes": stat.st_size,
                "modified": modified.isoformat(),
                "relative_path": str(path.relative_to(self._pcap_dir)),
            })

        # Sort by modification time, newest first
        results.sort(key=lambda r: r["modified"], reverse=True)
        return results

    # ------------------------------------------------------------------
    # BPF filter search
    # ------------------------------------------------------------------

    def validate_bpf_filter(self, bpf_filter: str) -> tuple[bool, str]:
        """Validate a BPF filter string for safety and basic syntax.

        Returns (is_valid, error_message).
        """
        if not bpf_filter or not bpf_filter.strip():
            return False, "Empty filter"

        bpf_filter = bpf_filter.strip()

        if _FILTER_FORBIDDEN.search(bpf_filter):
            return False, "Filter contains forbidden characters"

        if len(bpf_filter) > 1000:
            return False, "Filter too long (max 1000 characters)"

        return True, ""

    async def search(
        self,
        bpf_filter: str,
        from_ts: str | None = None,
        to_ts: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find PCAP files matching a BPF filter within time range.

        Uses tshark to check each file for matching packets. Returns
        files that contain at least one matching packet.
        """
        valid, err = self.validate_bpf_filter(bpf_filter)
        if not valid:
            raise ValueError(f"Invalid display filter: {err}")

        pcaps = self.get_available_pcaps(from_ts, to_ts)
        if not pcaps:
            return []

        matching = []
        for pcap in pcaps:
            count = await self._count_matching_packets(
                pcap["file"], bpf_filter
            )
            if count > 0:
                matching.append({
                    **pcap,
                    "matching_packets": count,
                })

        return matching

    async def _count_matching_packets(
        self, pcap_file: str, bpf_filter: str
    ) -> int:
        """Count packets matching BPF filter in a PCAP file.

        Runs tshark inside the nettap-tshark container via docker exec.
        Uses asyncio.create_subprocess_exec (argument-list form, no shell).
        A semaphore limits concurrent docker exec operations.
        """
        container_path = self._to_container_path(pcap_file)
        cmd = [
            "docker", "exec", _TSHARK_CONTAINER,
            "tshark",
            "-r", container_path,
            "-Y", bpf_filter,
            "-T", "fields",
            "-e", "frame.number",
        ]
        try:
            async with self._semaphore:
                logger.debug("Running: %s", " ".join(shlex.quote(c) for c in cmd))
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=45
                )

            if proc.returncode != 0:
                logger.debug(
                    "tshark filter count failed for %s: %s",
                    pcap_file,
                    stderr.decode(errors="replace").strip(),
                )
                return 0

            lines = stdout.decode(errors="replace").strip().split("\n")
            return len([line for line in lines if line.strip()])

        except asyncio.TimeoutError:
            logger.warning("tshark timed out counting packets in %s", pcap_file)
            return 0
        except FileNotFoundError:
            logger.error("docker not found in PATH")
            return 0
        except Exception as exc:
            logger.error("Error counting packets in %s: %s", pcap_file, exc)
            return 0

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    async def preview(
        self,
        pcap_file: str,
        bpf_filter: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Extract matching packets for preview.

        Runs tshark inside the nettap-tshark container via docker exec.
        Uses asyncio.create_subprocess_exec (argument-list form, no shell).
        Returns a list of packet summaries with frame number, timestamp,
        source, destination, protocol, length, and info.
        """
        # Security: ensure file is within pcap directory
        pcap_path = Path(pcap_file)
        if not str(pcap_path).startswith(str(self._pcap_dir)):
            raise ValueError("PCAP file must be within the configured PCAP directory")
        if not pcap_path.exists():
            raise FileNotFoundError(f"PCAP file not found: {pcap_file}")

        container_path = self._to_container_path(pcap_file)
        cmd = [
            "docker", "exec", _TSHARK_CONTAINER,
            "tshark",
            "-r", container_path,
            "-T", "fields",
            "-e", "frame.number",
            "-e", "frame.time",
            "-e", "ip.src",
            "-e", "ip.dst",
            "-e", "frame.protocols",
            "-e", "frame.len",
            "-e", "_ws.col.Info",
            "-E", "separator=|",
            "-c", str(limit),
        ]

        if bpf_filter:
            valid, err = self.validate_bpf_filter(bpf_filter)
            if not valid:
                raise ValueError(f"Invalid display filter: {err}")
            cmd.extend(["-Y", bpf_filter])

        try:
            async with self._semaphore:
                logger.debug("Running: %s", " ".join(shlex.quote(c) for c in cmd))
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=45
                )

            if proc.returncode != 0:
                err_msg = stderr.decode(errors="replace").strip()
                logger.error("tshark preview failed: %s", err_msg)
                return []

            packets = []
            for line in stdout.decode(errors="replace").strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split("|", 6)
                if len(parts) >= 6:
                    packets.append({
                        "frame_number": parts[0].strip(),
                        "timestamp": parts[1].strip(),
                        "source": parts[2].strip(),
                        "destination": parts[3].strip(),
                        "protocol": parts[4].strip(),
                        "length": parts[5].strip(),
                        "info": parts[6].strip() if len(parts) > 6 else "",
                    })

            return packets

        except asyncio.TimeoutError:
            logger.warning("tshark preview timed out for %s", pcap_file)
            return []
        except FileNotFoundError:
            logger.error("docker not found in PATH")
            return []

    # ------------------------------------------------------------------
    # Download (merge + filter)
    # ------------------------------------------------------------------

    async def download_filtered(
        self,
        bpf_filter: str,
        from_ts: str | None = None,
        to_ts: str | None = None,
    ) -> str | None:
        """Merge and filter PCAPs into a single temporary download file.

        Runs mergecap and tshark inside the nettap-tshark container via
        docker exec.  Intermediate files live in the container's /tmp
        (tmpfs, 100M).  The final filtered output is written to stdout
        (``-w -``) and captured on the daemon side.

        Uses asyncio.create_subprocess_exec (argument-list form, no shell).
        Returns the path to the temporary filtered PCAP file on the daemon,
        or None on failure.  Caller is responsible for cleanup.
        """
        valid, err = self.validate_bpf_filter(bpf_filter)
        if not valid:
            raise ValueError(f"Invalid display filter: {err}")

        pcaps = self.get_available_pcaps(from_ts, to_ts)
        if not pcaps:
            return None

        pcap_files = [p["file"] for p in pcaps]
        container_pcap_files = [self._to_container_path(f) for f in pcap_files]

        # Create daemon-side temp file for final output
        tmp = tempfile.NamedTemporaryFile(
            suffix=".pcap", prefix="nettap_filtered_", delete=False
        )
        tmp_path = tmp.name
        tmp.close()

        # If merging multiple files, use a temp path inside the container
        container_merged_path = "/tmp/nettap_merged.pcap"

        try:
            async with self._semaphore:
                if len(container_pcap_files) == 1:
                    # Single file — filter directly from the PCAP volume
                    source_path = container_pcap_files[0]
                else:
                    # Merge multiple PCAPs inside the container
                    merge_cmd = [
                        "docker", "exec", _TSHARK_CONTAINER,
                        "mergecap", "-w", container_merged_path,
                    ] + container_pcap_files

                    logger.debug("Running: %s", " ".join(shlex.quote(c) for c in merge_cmd))
                    proc = await asyncio.create_subprocess_exec(
                        *merge_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    _, stderr_bytes = await asyncio.wait_for(
                        proc.communicate(), timeout=150
                    )

                    if proc.returncode != 0:
                        logger.error(
                            "mergecap failed: %s",
                            stderr_bytes.decode(errors="replace").strip(),
                        )
                        os.unlink(tmp_path)
                        return None

                    source_path = container_merged_path

                # Filter inside the container, write to stdout (``-w -``)
                # and capture the binary output on the daemon side.
                filter_cmd = [
                    "docker", "exec", _TSHARK_CONTAINER,
                    "tshark",
                    "-r", source_path,
                    "-Y", bpf_filter,
                    "-w", "-",
                ]
                logger.debug("Running: %s", " ".join(shlex.quote(c) for c in filter_cmd))
                proc = await asyncio.create_subprocess_exec(
                    *filter_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=150
                )

                if proc.returncode != 0:
                    logger.error(
                        "tshark filter failed: %s",
                        stderr_bytes.decode(errors="replace").strip(),
                    )
                    os.unlink(tmp_path)
                    await self._cleanup_container_tmp(container_merged_path, pcap_files)
                    return None

            # Write captured binary PCAP data to daemon-side temp file
            # (outside semaphore -- no docker exec needed)
            with open(tmp_path, "wb") as f:
                f.write(stdout_bytes)

            # Clean up merged temp file inside the container
            await self._cleanup_container_tmp(container_merged_path, pcap_files)

            return tmp_path

        except asyncio.TimeoutError:
            logger.error("PCAP download operation timed out")
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            await self._cleanup_container_tmp(container_merged_path, pcap_files)
            return None
        except FileNotFoundError as exc:
            logger.error("docker not found: %s", exc)
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            return None

    async def _cleanup_container_tmp(
        self, container_path: str, pcap_files: list[str]
    ) -> None:
        """Remove a temp file inside the tshark container (best-effort)."""
        if len(pcap_files) <= 1:
            return  # No merged file was created
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "exec", _TSHARK_CONTAINER,
                "rm", "-f", container_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.communicate(), timeout=5)
        except Exception:
            logger.debug("Failed to clean up container temp file %s", container_path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_iso(ts: str) -> datetime | None:
    """Parse an ISO timestamp string, returning None on failure."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
