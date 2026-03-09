"""
NetTap PcapSearchService — Search and filter captured PCAP files.

Provides PCAP file listing, BPF filter search, packet preview (via tshark),
and filtered PCAP download (via mergecap + tshark).

PCAP directory is configurable via PCAP_DIR env var (default: /data/pcap/).
"""

import asyncio
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("nettap.services.pcap_search")

_DEFAULT_PCAP_DIR = os.environ.get("PCAP_DIR", "/data/pcap")

# BPF filter validation — reject obviously dangerous patterns
_BPF_FORBIDDEN = re.compile(r"[;&|`$]")

# Supported PCAP file extensions
_PCAP_EXTENSIONS = {".pcap", ".pcapng", ".cap"}


class PcapSearchService:
    """Search and filter captured PCAP files."""

    def __init__(self, pcap_dir: str | None = None) -> None:
        self._pcap_dir = Path(pcap_dir or _DEFAULT_PCAP_DIR)

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

        if _BPF_FORBIDDEN.search(bpf_filter):
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
            raise ValueError(f"Invalid BPF filter: {err}")

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

        Uses asyncio.create_subprocess_exec (not shell) to avoid injection.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "tshark",
                "-r", pcap_file,
                "-Y", bpf_filter,
                "-T", "fields",
                "-e", "frame.number",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=30
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
            logger.error("tshark not found in PATH")
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

        Uses asyncio.create_subprocess_exec (not shell) to avoid injection.
        Returns a list of packet summaries with frame number, timestamp,
        source, destination, protocol, length, and info.
        """
        # Security: ensure file is within pcap directory
        pcap_path = Path(pcap_file)
        if not str(pcap_path).startswith(str(self._pcap_dir)):
            raise ValueError("PCAP file must be within the configured PCAP directory")
        if not pcap_path.exists():
            raise FileNotFoundError(f"PCAP file not found: {pcap_file}")

        cmd = [
            "tshark",
            "-r", pcap_file,
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
                raise ValueError(f"Invalid BPF filter: {err}")
            cmd.extend(["-Y", bpf_filter])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=30
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
            logger.error("tshark not found in PATH")
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

        Uses asyncio.create_subprocess_exec (not shell) to avoid injection.
        Returns the path to the temporary filtered PCAP file, or None on
        failure. Caller is responsible for cleanup.
        """
        valid, err = self.validate_bpf_filter(bpf_filter)
        if not valid:
            raise ValueError(f"Invalid BPF filter: {err}")

        pcaps = self.get_available_pcaps(from_ts, to_ts)
        if not pcaps:
            return None

        pcap_files = [p["file"] for p in pcaps]

        # Create temp output file
        tmp = tempfile.NamedTemporaryFile(
            suffix=".pcap", prefix="nettap_filtered_", delete=False
        )
        tmp_path = tmp.name
        tmp.close()

        try:
            if len(pcap_files) == 1:
                # Single file — just filter directly
                merged_path = pcap_files[0]
            else:
                # Merge multiple PCAPs first
                merged_tmp = tempfile.NamedTemporaryFile(
                    suffix=".pcap", prefix="nettap_merged_", delete=False
                )
                merged_path = merged_tmp.name
                merged_tmp.close()

                merge_cmd = ["mergecap", "-w", merged_path] + pcap_files
                proc = await asyncio.create_subprocess_exec(
                    *merge_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=120
                )

                if proc.returncode != 0:
                    logger.error(
                        "mergecap failed: %s",
                        stderr.decode(errors="replace").strip(),
                    )
                    os.unlink(merged_path)
                    os.unlink(tmp_path)
                    return None

            # Filter the merged file
            filter_cmd = [
                "tshark",
                "-r", merged_path,
                "-Y", bpf_filter,
                "-w", tmp_path,
            ]
            proc = await asyncio.create_subprocess_exec(
                *filter_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=120
            )

            # Clean up merged temp file if we created one
            if len(pcap_files) > 1:
                os.unlink(merged_path)

            if proc.returncode != 0:
                logger.error(
                    "tshark filter failed: %s",
                    stderr.decode(errors="replace").strip(),
                )
                os.unlink(tmp_path)
                return None

            return tmp_path

        except asyncio.TimeoutError:
            logger.error("PCAP download operation timed out")
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            return None
        except FileNotFoundError as exc:
            logger.error("Required tool not found: %s", exc)
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_iso(ts: str) -> datetime | None:
    """Parse an ISO timestamp string, returning None on failure."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
