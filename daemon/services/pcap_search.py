"""
NetTap PcapSearchService — Search and filter captured PCAP files.

Provides PCAP file listing, BPF filter search, packet preview (via tshark),
and filtered PCAP download (streamed from packet analysis's window cut, NET-189).

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

# OLD CODE START — NET-189: the download streams; no daemon-side temp file
# import tempfile
# OLD CODE END
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from api.offload import run_blocking
from services.capture_index import (
    RECENT_SECONDS,
    TIME_FLOOR,
    CaptureIndex,
    Selection,
)
from services.container_exec import ReaderBusy, reader_slot, run_in_tshark
from services.packet_manifest import MAX_BYTES, MAX_FILES, PacketError
from services.packet_search import (
    CHECK_JOB,
    CHECK_SECONDS,
    FILTER_DOWNLOAD_JOB,
    _cuts,
    cut_ok,
    job_path,
)
from services.tshark_service import (
    bounded_exec,
    filter_check_cmd,
    raise_filter_check_failure,
)

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
# nettap-tshark container (cpus: 1.0) as TSharkService, so keep this
# low to avoid thrashing the CPU budget and hitting timeouts.
_MAX_CONCURRENT_TSHARK = 2

# A search reads whole files (~25 s per 576 MB at the container's 1 CPU on the G11), so it
# runs as a background job; each file gets this long before it counts as timed out.
# tshark needs ~120 MiB plus about the file's size: past the container's 1 GiB it is killed.
_SEARCH_FILE_TIMEOUT = 300
_TIMEOUT_EXIT_CODES = {124, 137}  # coreutils timeout: TERM, then KILL

# "Download filtered" (NET-189). One deadline for the whole request, below the web
# proxy's 300 s (undici's header and body timeouts).
_DOWNLOAD_SECONDS = 240
_DOWNLOAD_SLOT_WAIT_SECONDS = 5
_DOWNLOAD_MIN_JOB_SECONDS = 5
# Exact output needs one uninterrupted dissection, and TShark's memory follows the
# packet count (G11, TShark 4.0.17: 343k packets 491 MiB, 536k 728 MiB): 400k is about
# 560 MiB, which leaves room for one per-file search read in the container's 1 GiB.
_DOWNLOAD_MAX_PACKETS = 400_000
_DOWNLOAD_NAMED_FAILED = 5
# netsniff-ng names each file after the epoch it started (mnetsniff-enp4s0_<epoch>.pcap)
_NAME_EPOCH = re.compile(r"_(\d{10})\.")
# Packets written up to this long before a file's name time still land in it (the
# writer ran 0.13-6.6 s behind on the G11). Listing only: the download uses the index.
_WRITER_LAG_SECONDS = 30

# -c counts packets read, not matches, so a filtered preview pipes through head instead.
# User values reach tshark only as positional args ($1 file, $2 filter, $3 limit).
# -l flushes each line so tshark stops right after head quits, not a 4 KB buffer later (#78)
# Source, Destination and Protocol are Wireshark's own columns (#141): ip.src was blank
# for IPv6 and ARP, and frame.protocols' last entry read "DATA" where Wireshark says UDP
_FILTERED_PREVIEW_SCRIPT = (
    'tshark -l -r "$1" -Y "$2" -T fields -e frame.number -e frame.time '
    "-e _ws.col.Source -e _ws.col.Destination -e _ws.col.Protocol -e frame.len "
    "-e _ws.col.Info -E separator='|' "
    '| head -n "$3"'
)
# OLD CODE START — #141: IPv4-only addresses and the last frame.protocols entry
# _FILTERED_PREVIEW_SCRIPT = (
#     'tshark -l -r "$1" -Y "$2" -T fields -e frame.number -e frame.time -e ip.src '
#     "-e ip.dst -e frame.protocols -e frame.len -e _ws.col.Info -E separator='|' "
#     '| head -n "$3"'
# )
# OLD CODE END
# OLD CODE START — #78: without -l a rare filter read on after the limit (35 s vs 26 s)
# _FILTERED_PREVIEW_SCRIPT = (
#     'tshark -r "$1" -Y "$2" -T fields -e frame.number -e frame.time -e ip.src '
#     "-e ip.dst -e frame.protocols -e frame.len -e _ws.col.Info -E separator='|' "
#     '| head -n "$3"'
# )
# OLD CODE END


class PcapSearchService:
    """Search and filter captured PCAP files."""

    # OLD CODE START — NET-189: the download selects its files from the capture index
    # def __init__(
    #     self, pcap_dir: str | None = None, semaphore: asyncio.Semaphore | None = None
    # ) -> None:
    # OLD CODE END
    def __init__(
        self,
        pcap_dir: str | None = None,
        semaphore: asyncio.Semaphore | None = None,
        index: CaptureIndex | None = None,
    ) -> None:
        self._pcap_dir = Path(pcap_dir or _DEFAULT_PCAP_DIR)
        # NET-188: the server passes TShark's semaphore so every reader shares 2 slots
        self._semaphore = semaphore or asyncio.Semaphore(_MAX_CONCURRENT_TSHARK)
        # NET-189: the files holding each window's packets; one download at a time
        self._index = index
        self._download_lock = asyncio.Lock()
        self._search_seq = 0
        self._search_job: dict[str, Any] | None = None
        self._search_task: asyncio.Task | None = None

    def contains(self, path: str) -> bool:
        """True when path, with ".." and symlinks resolved, is inside the PCAP directory.

        A string-prefix test let "/opt/nettap/pcap/../../etc/passwd" and sibling
        directories such as "/opt/nettap/pcap-old" through.
        """
        root = os.path.realpath(self._pcap_dir)
        return os.path.commonpath([os.path.realpath(path), root]) == root

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
        Optionally filtered by time range: a file is listed when the span it can hold
        packets from (its name's start time, less the writer lag, to its modification
        time) overlaps the range (NET-189).
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
            # OLD CODE START — NET-189: a file that started inside the range but was last
            # written after it was left out (a 20 s window got one of its two files)
            # if to_dt and modified > to_dt:
            #     continue
            # OLD CODE END
            if to_dt and _span_start(path.name, stat.st_mtime) > to_dt.timestamp():
                continue

            results.append(
                {
                    "file": str(path),
                    "name": path.name,
                    "size_bytes": stat.st_size,
                    "modified": modified.isoformat(),
                    "relative_path": str(path.relative_to(self._pcap_dir)),
                }
            )

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
            count = await self._count_matching_packets(pcap["file"], bpf_filter)
            if count:
                matching.append(
                    {
                        **pcap,
                        "matching_packets": count,
                    }
                )

        return matching

    async def search_progress(
        self,
        bpf_filter: str,
        from_ts: str | None = None,
        to_ts: str | None = None,
    ) -> dict[str, Any]:
        """Start a background search for these params, or report the one running.

        A call with different params replaces the running job. Files are checked
        newest first and matches appear as they are found.
        """
        key = (bpf_filter, from_ts, to_ts)
        if self._search_job is None or self._search_job["key"] != key:
            valid, err = self.validate_bpf_filter(bpf_filter)
            if not valid:
                raise ValueError(f"Invalid display filter: {err}")
            # OLD CODE START — PR 2 (reliability): the file walk ran on the request loop
            # if self._search_task is not None:
            #     self._search_task.cancel()
            # pcaps = self.get_available_pcaps(from_ts, to_ts)
            # OLD CODE END
            pcaps = await run_blocking(self.get_available_pcaps, from_ts, to_ts)
            # Another poll may have started this search while the files were listed
            job = self._search_job
            if job is not None and job["key"] == key:
                return await self.search_progress(bpf_filter, from_ts, to_ts)
            if self._search_task is not None:
                self._search_task.cancel()
            self._search_seq += 1
            self._search_job = {
                "id": self._search_seq,
                "key": key,
                "results": (),
                "files_checked": 0,
                "files_total": len(pcaps),
                "timed_out": 0,
                "failed": 0,
                "error": None,
                "complete": not pcaps,
                # #137: sizes and time so far, for the page's estimate (no assumed rate)
                "bytes_total": sum(p["size_bytes"] for p in pcaps),
                "bytes_checked": 0,
                "started": time.monotonic(),
                "finished": None if pcaps else time.monotonic(),
            }
            self._search_task = (
                asyncio.create_task(
                    self._run_search_job(self._search_seq, pcaps, bpf_filter)
                )
                if pcaps
                else None
            )
        job = self._search_job
        return {
            "filter": bpf_filter,
            "count": len(job["results"]),
            "results": list(job["results"]),
            "files_checked": job["files_checked"],
            "files_total": job["files_total"],
            "complete": job["complete"],
            "timed_out": job["timed_out"],
            # #96: files tshark couldn't read, and the first reason, so they aren't "no match"
            "failed": job["failed"],
            "error": job["error"],
            "bytes_total": job["bytes_total"],
            "bytes_checked": job["bytes_checked"],
            "seconds_elapsed": round(
                (job["finished"] or time.monotonic()) - job["started"]
            ),
        }

    async def _run_search_job(
        self, job_id: int, pcaps: list[dict[str, Any]], bpf_filter: str
    ) -> None:
        for pcap in pcaps:
            # OLD CODE START — #96: a file tshark couldn't read counted as "no match"
            # count = await self._count_matching_packets(
            #     pcap["file"], bpf_filter, timeout=_SEARCH_FILE_TIMEOUT
            # )
            # OLD CODE END
            error = None
            try:
                count = await self._count_matching_packets(
                    pcap["file"], bpf_filter, timeout=_SEARCH_FILE_TIMEOUT
                )
            except Exception as exc:
                count, error = 0, str(exc)
            job = self._search_job
            if job is None or job["id"] != job_id:
                return  # replaced by a newer search
            found = ({**pcap, "matching_packets": count},) if count else ()
            self._search_job = {
                **job,
                "results": job["results"] + found,
                "files_checked": job["files_checked"] + 1,
                "timed_out": job["timed_out"] + (count is None),
                "failed": job["failed"] + (error is not None),
                "error": job["error"] or error,
                "bytes_checked": job["bytes_checked"] + pcap["size_bytes"],
            }
        job = self._search_job
        if job is not None and job["id"] == job_id:
            self._search_job = {**job, "complete": True, "finished": time.monotonic()}

    async def _count_matching_packets(
        self, pcap_file: str, bpf_filter: str, timeout: int = 45
    ) -> int | None:
        """Count packets matching BPF filter in a PCAP file; None if it timed out.

        Raises RuntimeError when tshark couldn't read the file (#96).

        Runs tshark inside the nettap-tshark container via docker exec.
        Uses asyncio.create_subprocess_exec (argument-list form, no shell).
        A semaphore limits concurrent docker exec operations.
        """
        container_path = self._to_container_path(pcap_file)
        cmd = [
            "docker",
            "exec",
            _TSHARK_CONTAINER,
            # background searches share the container's 1 CPU with previews and
            # analysis; lowest priority keeps those inside the web proxy's timeout
            "nice",
            "-n",
            "19",
            "tshark",
            "-r",
            container_path,
            "-Y",
            bpf_filter,
            "-T",
            "fields",
            "-e",
            "frame.number",
        ]
        try:
            async with self._semaphore:
                logger.debug("Running: %s", " ".join(shlex.quote(c) for c in cmd))
                proc = await asyncio.create_subprocess_exec(
                    *bounded_exec(cmd, timeout),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                started = time.monotonic()
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout + 10
                )

            # #137: a KILL before timeout's own deadline is the kernel's OOM killer, not a timeout
            if proc.returncode == 137 and time.monotonic() - started < timeout:
                try:
                    size = f" ({round(os.path.getsize(pcap_file) / 1_000_000)} MB)"
                except OSError:  # pruned meanwhile
                    size = ""
                logger.warning("tshark ran out of memory reading %s", pcap_file)
                raise RuntimeError(
                    f"tshark ran out of memory reading {os.path.basename(pcap_file)}{size}"
                )
            if proc.returncode in _TIMEOUT_EXIT_CODES:
                logger.warning("tshark timed out counting packets in %s", pcap_file)
                return None

            lines = stdout.decode(errors="replace").strip().split("\n")
            count = len([line for line in lines if line.strip()])
            # a file still being written can end mid-packet: keep what tshark printed
            # OLD CODE START — #96: a failed read (bad filter, container down) was "0 matches"
            # if proc.returncode != 0 and not count:
            #     logger.debug("tshark filter count failed for %s: %s", pcap_file, ...)
            # return count
            # OLD CODE END
            if proc.returncode != 0 and not count:
                err = stderr.decode(errors="replace").strip()
                logger.warning("tshark filter count failed for %s: %s", pcap_file, err)
                raise RuntimeError(err or f"tshark exited with code {proc.returncode}")
            return count

        except asyncio.TimeoutError:
            logger.warning("tshark timed out counting packets in %s", pcap_file)
            return None
        # OLD CODE START — #96: docker missing or any other error read as "0 matches"
        # except FileNotFoundError:
        #     logger.error("docker not found in PATH")
        #     return 0
        # except Exception as exc:
        #     logger.error("Error counting packets in %s: %s", pcap_file, exc)
        #     return 0
        # OLD CODE END
        except FileNotFoundError as exc:
            raise RuntimeError("docker not found in PATH") from exc

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    async def preview(
        self,
        pcap_file: str,
        bpf_filter: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Packets only; see preview_with_status()."""
        return (await self.preview_with_status(pcap_file, bpf_filter, limit))["packets"]

    async def preview_with_status(
        self,
        pcap_file: str,
        bpf_filter: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Extract matching packets for preview: {"packets": [...], "timed_out": bool}.

        timed_out means tshark ran out of time before reading the whole file or
        finding `limit` matches (a busy multi-GB file at the container's CPU), so an empty or
        short list is not proof the file has no more matches.

        Runs tshark inside the nettap-tshark container via docker exec.
        Uses asyncio.create_subprocess_exec (argument-list form, no shell).
        Returns a list of packet summaries with frame number, timestamp,
        source, destination, protocol, length, and info.
        """
        # Security: ensure file is within pcap directory
        pcap_path = Path(pcap_file)
        # OLD CODE START — string prefix: ".." and sibling directories passed
        # if not str(pcap_path).startswith(str(self._pcap_dir)):
        # OLD CODE END
        if not self.contains(pcap_file):
            raise ValueError("PCAP file must be within the configured PCAP directory")
        if not pcap_path.exists():
            raise FileNotFoundError(f"PCAP file not found: {pcap_file}")

        container_path = self._to_container_path(pcap_file)
        cmd = [
            "docker",
            "exec",
            _TSHARK_CONTAINER,
            "tshark",
            "-r",
            container_path,
            "-T",
            "fields",
            "-e",
            "frame.number",
            "-e",
            "frame.time",
            # OLD CODE START — #141: IPv4-only addresses and the last frame.protocols entry
            # "-e",
            # "ip.src",
            # "-e",
            # "ip.dst",
            # "-e",
            # "frame.protocols",
            # OLD CODE END
            "-e",
            "_ws.col.Source",
            "-e",
            "_ws.col.Destination",
            "-e",
            "_ws.col.Protocol",
            "-e",
            "frame.len",
            "-e",
            "_ws.col.Info",
            "-E",
            "separator=|",
            "-c",
            str(limit),
        ]

        if bpf_filter:
            valid, err = self.validate_bpf_filter(bpf_filter)
            if not valid:
                raise ValueError(f"Invalid display filter: {err}")
            # OLD CODE START — 2026-11-02: with -c, only matches among the first
            # `limit` packets read were shown (often none)
            # cmd.extend(["-Y", bpf_filter])
            # OLD CODE END
            cmd = [
                "docker",
                "exec",
                _TSHARK_CONTAINER,
                "sh",
                "-c",
                _FILTERED_PREVIEW_SCRIPT,
                "sh",
                container_path,
                bpf_filter,
                str(limit),
            ]

        try:
            async with self._semaphore:
                logger.debug("Running: %s", " ".join(shlex.quote(c) for c in cmd))
                proc = await asyncio.create_subprocess_exec(
                    *bounded_exec(cmd, 45),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                # the in-container timeout fires first, so partial output survives
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=55)

            timed_out = proc.returncode in _TIMEOUT_EXIT_CODES
            # a file still being written can end mid-packet: keep what tshark printed
            # OLD CODE START — #96: a failed preview (container down, unreadable file)
            # came back as "no packets"
            # if proc.returncode != 0 and not stdout.strip():
            #     err_msg = stderr.decode(errors="replace").strip()
            #     if not timed_out:
            #         logger.error("tshark preview failed: %s", err_msg)
            #     return {"packets": [], "timed_out": timed_out}
            # OLD CODE END
            if proc.returncode != 0 and not stdout.strip():
                if timed_out:
                    return {"packets": [], "timed_out": True}
                err_msg = stderr.decode(errors="replace").strip()
                logger.error("tshark preview failed: %s", err_msg)
                raise RuntimeError(
                    err_msg or f"tshark exited with code {proc.returncode}"
                )
            if bpf_filter and not timed_out and not stdout.strip():
                # the pipeline's status is head's: a filter tshark refused also printed nothing (#96)
                await self._check_filter(container_path, bpf_filter)

            packets = []
            for line in stdout.decode(errors="replace").strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split("|", 6)
                if len(parts) >= 6:
                    packets.append(
                        {
                            "frame_number": parts[0].strip(),
                            "timestamp": parts[1].strip(),
                            "source": parts[2].strip(),
                            "destination": parts[3].strip(),
                            "protocol": parts[4].strip(),
                            "length": parts[5].strip(),
                            "info": parts[6].strip() if len(parts) > 6 else "",
                        }
                    )

            return {"packets": packets, "timed_out": timed_out}

        except asyncio.TimeoutError:
            logger.warning("tshark preview timed out for %s", pcap_file)
            return {"packets": [], "timed_out": True}
        # OLD CODE START — #96: docker missing read as "no packets"
        # except FileNotFoundError:
        #     logger.error("docker not found in PATH")
        #     return {"packets": [], "timed_out": False}
        # OLD CODE END
        except FileNotFoundError as exc:
            # not FileNotFoundError: the API reads that as "PCAP file not found" (404)
            raise RuntimeError("docker not found in PATH") from exc

    async def _check_filter(self, container_path: str, display_filter: str) -> None:
        """Raise ValueError carrying tshark's message if it refuses the filter (#96)."""
        async with self._semaphore:
            proc = await asyncio.create_subprocess_exec(
                *bounded_exec(filter_check_cmd(container_path, display_filter), 15),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=25)
        raise_filter_check_failure(
            proc.returncode, stderr.decode(errors="replace"), ValueError
        )

    # ------------------------------------------------------------------
    # Download (merge + filter)
    # ------------------------------------------------------------------

    # OLD CODE START — NET-189: mergecap into the container's 100 MB /tmp failed for any
    # window of more than one ~107 MB file (and left the file there), and the result was
    # held in memory and written to the daemon's 50 MB /tmp. Replaced by a streamed job.
    # async def download_filtered(
    #     self,
    #     bpf_filter: str,
    #     from_ts: str | None = None,
    #     to_ts: str | None = None,
    # ) -> str | None:
    #     """Merge and filter PCAPs into a single temporary download file.
    #
    #     Runs mergecap and tshark inside the nettap-tshark container via
    #     docker exec.  Intermediate files live in the container's /tmp
    #     (tmpfs, 100M).  The final filtered output is written to stdout
    #     (``-w -``) and captured on the daemon side.
    #
    #     Uses asyncio.create_subprocess_exec (argument-list form, no shell).
    #     Returns the path to the temporary filtered PCAP file on the daemon,
    #     or None when there are no PCAP files; raises RuntimeError when the
    #     merge or filter fails (#96).  Caller is responsible for cleanup.
    #     """
    #     valid, err = self.validate_bpf_filter(bpf_filter)
    #     if not valid:
    #         raise ValueError(f"Invalid display filter: {err}")
    #
    #     # OLD CODE START — PR 2 (reliability): the file walk ran on the request loop
    #     # pcaps = self.get_available_pcaps(from_ts, to_ts)
    #     # OLD CODE END
    #     pcaps = await run_blocking(self.get_available_pcaps, from_ts, to_ts)
    #     if not pcaps:
    #         return None
    #
    #     pcap_files = [p["file"] for p in pcaps]
    #     container_pcap_files = [self._to_container_path(f) for f in pcap_files]
    #
    #     # Create daemon-side temp file for final output
    #     tmp = tempfile.NamedTemporaryFile(
    #         suffix=".pcap", prefix="nettap_filtered_", delete=False
    #     )
    #     tmp_path = tmp.name
    #     tmp.close()
    #
    #     # If merging multiple files, use a temp path inside the container
    #     container_merged_path = "/tmp/nettap_merged.pcap"
    #
    #     try:
    #         async with self._semaphore:
    #             if len(container_pcap_files) == 1:
    #                 # Single file — filter directly from the PCAP volume
    #                 source_path = container_pcap_files[0]
    #             else:
    #                 # Merge multiple PCAPs inside the container
    #                 merge_cmd = [
    #                     "docker",
    #                     "exec",
    #                     _TSHARK_CONTAINER,
    #                     "mergecap",
    #                     "-w",
    #                     container_merged_path,
    #                 ] + container_pcap_files
    #
    #                 logger.debug(
    #                     "Running: %s", " ".join(shlex.quote(c) for c in merge_cmd)
    #                 )
    #                 proc = await asyncio.create_subprocess_exec(
    #                     *bounded_exec(merge_cmd, 150),
    #                     stdout=asyncio.subprocess.PIPE,
    #                     stderr=asyncio.subprocess.PIPE,
    #                 )
    #                 _, stderr_bytes = await asyncio.wait_for(
    #                     proc.communicate(), timeout=150
    #                 )
    #
    #                 if proc.returncode != 0:
    #                     err = stderr_bytes.decode(errors="replace").strip()
    #                     logger.error("mergecap failed: %s", err)
    #                     os.unlink(tmp_path)
    #                     # OLD CODE START — #96: the API answered "No matching PCAP data"
    #                     # return None
    #                     # OLD CODE END
    #                     raise RuntimeError(f"mergecap failed: {err}")
    #
    #                 source_path = container_merged_path
    #
    #             # Filter inside the container, write to stdout (``-w -``)
    #             # and capture the binary output on the daemon side.
    #             filter_cmd = [
    #                 "docker",
    #                 "exec",
    #                 _TSHARK_CONTAINER,
    #                 "tshark",
    #                 "-r",
    #                 source_path,
    #                 "-Y",
    #                 bpf_filter,
    #                 "-w",
    #                 "-",
    #             ]
    #             logger.debug(
    #                 "Running: %s", " ".join(shlex.quote(c) for c in filter_cmd)
    #             )
    #             proc = await asyncio.create_subprocess_exec(
    #                 *bounded_exec(filter_cmd, 150),
    #                 stdout=asyncio.subprocess.PIPE,
    #                 stderr=asyncio.subprocess.PIPE,
    #             )
    #             stdout_bytes, stderr_bytes = await asyncio.wait_for(
    #                 proc.communicate(), timeout=150
    #             )
    #
    #             if proc.returncode != 0:
    #                 err = stderr_bytes.decode(errors="replace").strip()
    #                 logger.error("tshark filter failed: %s", err)
    #                 os.unlink(tmp_path)
    #                 await self._cleanup_container_tmp(container_merged_path, pcap_files)
    #                 # OLD CODE START — #96: the API answered "No matching PCAP data"
    #                 # return None
    #                 # OLD CODE END
    #                 raise RuntimeError(f"tshark filter failed: {err}")
    #
    #         # Write captured binary PCAP data to daemon-side temp file
    #         # (outside semaphore -- no docker exec needed)
    #         # OLD CODE START — PR 2 (reliability): up to ~100 MB written on the request loop
    #         # with open(tmp_path, "wb") as f:
    #         #     f.write(stdout_bytes)
    #         # OLD CODE END
    #         # OLD CODE START — F8: a cancel left the worker writing a file nobody deleted
    #         # await run_blocking(Path(tmp_path).write_bytes, stdout_bytes)
    #         # OLD CODE END
    #         write = asyncio.ensure_future(
    #             run_blocking(Path(tmp_path).write_bytes, stdout_bytes)
    #         )
    #         try:
    #             await asyncio.shield(write)
    #         except asyncio.CancelledError:
    #             # A cancel can't stop the worker thread: wait for it, or it would write the
    #             # file again after the unlink below. Its own error is moot now.
    #             # shortcut: a second cancel during this wait unlinks early; aiohttp and
    #             # asyncio.run cancel a request once, upgrade if that changes
    #             await asyncio.wait([write])
    #             if not write.cancelled():
    #                 write.exception()  # retrieved, so asyncio doesn't log it as lost
    #             raise
    #
    #         # Clean up merged temp file inside the container
    #         await self._cleanup_container_tmp(container_merged_path, pcap_files)
    #
    #         return tmp_path
    #
    #     # OLD CODE START — #96: a timeout or missing docker came back as None, which
    #     # the API answers with 404 "No matching PCAP data found"
    #     # except asyncio.TimeoutError:
    #     #     ... cleanup ...
    #     #     return None
    #     # except FileNotFoundError as exc:
    #     #     logger.error("docker not found: %s", exc)
    #     #     ... cleanup ...
    #     #     return None
    #     # OLD CODE END
    #     except asyncio.TimeoutError as exc:
    #         logger.error("PCAP download operation timed out")
    #         if os.path.exists(tmp_path):
    #             os.unlink(tmp_path)
    #         await self._cleanup_container_tmp(container_merged_path, pcap_files)
    #         raise RuntimeError("PCAP download timed out") from exc
    #     except FileNotFoundError as exc:
    #         logger.error("docker not found: %s", exc)
    #         if os.path.exists(tmp_path):
    #             os.unlink(tmp_path)
    #         raise RuntimeError("docker not found in PATH") from exc
    #     except BaseException:
    #         # F8: any other error (a full /tmp mid-write) or a cancel: the caller never gets
    #         # the path, so nobody else would delete the file
    #         Path(tmp_path).unlink(missing_ok=True)
    #         raise
    #
    # async def _cleanup_container_tmp(
    #     self, container_path: str, pcap_files: list[str]
    # ) -> None:
    #     """Remove a temp file inside the tshark container (best-effort)."""
    #     if len(pcap_files) <= 1:
    #         return  # No merged file was created
    #     try:
    #         proc = await asyncio.create_subprocess_exec(
    #             "docker",
    #             "exec",
    #             _TSHARK_CONTAINER,
    #             "rm",
    #             "-f",
    #             container_path,
    #             stdout=asyncio.subprocess.DEVNULL,
    #             stderr=asyncio.subprocess.DEVNULL,
    #         )
    #         await asyncio.wait_for(proc.communicate(), timeout=5)
    #     except Exception:
    #         logger.debug("Failed to clean up container temp file %s", container_path)
    # OLD CODE END

    async def download_filtered(
        self,
        bpf_filter: str,
        from_ts: str | None,
        to_ts: str | None,
        write: Callable[[bytes], Awaitable[None]],
    ) -> bool:
        """Stream the window's packets that match the filter, as one capture, to `write`.

        The files come from the capture index (real first and last packet times), and
        packet analysis's window cut reads them, so the output holds exactly the
        window's matching packets. False when no capture file holds the window.
        Raises ValueError (can't be served as asked), ReaderBusy or StillIndexing (try
        again), PacketError (the read failed, with a message for the user) or another
        exception (anything else). After the first chunk any error means
        the output is incomplete: the caller must abort the response, never end it.
        """
        started = time.monotonic()
        valid, err = self.validate_bpf_filter(bpf_filter)
        if not valid:
            raise ValueError(f"Invalid display filter: {err}")
        if self._index is None:
            raise RuntimeError("PCAP download is not configured")
        start, end = _window(from_ts, to_ts)
        if self._download_lock.locked():
            # two near-budget downloads would need about 1.1 GiB of the reader's 1 GiB
            raise ReaderBusy("Another download is running; try again when it finishes.")
        async with (
            self._download_lock,
            reader_slot(self._semaphore, _DOWNLOAD_SLOT_WAIT_SECONDS),
        ):
            sel = await self._index.select(start, end)
            _admit_download(sel, start, end)
            if not sel.files:
                return False
            await _check_download_filter(bpf_filter)
            left = _DOWNLOAD_SECONDS - (time.monotonic() - started)
            if left < _DOWNLOAD_MIN_JOB_SECONDS:
                raise ReaderBusy("The packet reader is busy; try again in a moment.")
            recent_ns = time.time_ns() - RECENT_SECONDS * 1_000_000_000
            paths = [
                job_path(f.container_path, e.cut_short or f.mtime_ns >= recent_ns)
                for f, e in sel.files
            ]
            size = sum(f.size for f, _ in sel.files)
            result = await run_in_tshark(
                FILTER_DOWNLOAD_JOB,
                [str(start), str(end), bpf_filter.strip(), *paths],
                deadline_s=left,
                # pcapng output of tiny frames is about 1.2x their pcap input
                max_stdout=2 * size + 1024 * 1024,
                sink=write,
            )
        if result.status("tshark") == 0 and cut_ok(result, _cuts(paths)):
            logger.info(
                "filtered download window=%s..%s files=%d bytes=%d seconds=%.2f",
                start,
                end,
                len(sel.files),
                size,
                result.seconds,
            )
            return True
        # OLD CODE START — NET-189: RuntimeError, so the daemon's 5xx filter replaced these
        # written messages with "Something went wrong"
        # if result.killed_for_memory():
        #     raise RuntimeError("The packet reader ran out of memory on this window. …")
        # if result.deadline:
        #     raise RuntimeError("The download took longer than the time allowed. …")
        # raise RuntimeError("Reading the capture files failed.")
        # OLD CODE END
        if result.killed_for_memory():
            raise PacketError(
                500,
                "The packet reader ran out of memory on this window. "
                "Try a shorter window or a narrower filter.",
            )
        if result.deadline:
            raise PacketError(
                500,
                "The download took longer than the time allowed. Try a shorter window.",
            )
        logger.error(
            "filtered download failed: statuses=%s stderr=%s",
            result.statuses,
            result.stderr[-2000:],
        )
        raise PacketError(500, "Reading the capture files failed.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# OLD CODE START — NET-189: a time without an offset came back naive, and comparing it
# with a file's (aware) time raised TypeError
# def _parse_iso(ts: str) -> datetime | None:
#     """Parse an ISO timestamp string, returning None on failure."""
#     try:
#         return datetime.fromisoformat(ts.replace("Z", "+00:00"))
#     except (ValueError, TypeError):
#         return None
# OLD CODE END
def _parse_iso(ts: str) -> datetime | None:
    """Parse an ISO timestamp string (UTC when it has no offset), None on failure."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _span_start(name: str, mtime: float) -> float:
    """The earliest time a capture file can hold packets from, for listing: its name's
    start epoch less the writer lag (at most its mtime); any time without one."""
    m = _NAME_EPOCH.search(name)
    return min(int(m.group(1)) - _WRITER_LAG_SECONDS, mtime) if m else float("-inf")


def _epoch(ts: str) -> Decimal:
    dt = _parse_iso(ts)
    if dt is None:
        raise ValueError(f"Unreadable time: {ts}")
    unix = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return Decimal((dt - unix) // timedelta(microseconds=1)) / 1_000_000


def _window(from_ts: str | None, to_ts: str | None) -> tuple[Decimal, Decimal]:
    """The download's window as epoch seconds: from 2000 and up to now when not given."""
    start = _epoch(from_ts) if from_ts else Decimal(TIME_FLOOR)
    end = _epoch(to_ts) if to_ts else Decimal(time.time_ns() // 1000) / 1_000_000
    if end <= start:
        raise ValueError("The download window must end after it starts.")
    return start, end


def _window_packets(sel: Selection, start: Decimal, end: Decimal) -> int:
    """About how many packets TShark dissects: the window cut passes only the window's
    packets, so each file counts with the share of its first-to-last span the window covers.

    shortcut: assumes an even packet rate inside a file; a burst can put more in the window,
    and then the container's memory limit stops the job with an "out of memory" error."""
    total = Decimal(0)
    for _, e in sel.files:  # indexed entries carry first, last and packets
        first, last = Decimal(e.first or 0), Decimal(e.last or 0)
        span = last - first
        covered = min(end, last) - max(start, first)
        share = min(Decimal(1), max(Decimal(0), covered / span)) if span > 0 else 1
        total += (e.packets or 0) * share
    return int(total)


# OLD CODE START — NET-189 review: whole files counted, so any window crossing a file change
# was refused (two ~300k-packet files are over the budget), though TShark reads only the window
# def _admit_download(sel: Selection) -> None:
# OLD CODE END
def _admit_download(sel: Selection, start: Decimal, end: Decimal) -> None:
    """ValueError unless the whole window can be read: every file's packet times are
    known, and the files fit the reader's budget."""
    if sel.failed:
        names = [f.id for f, _ in sel.failed]
        more = len(names) - _DOWNLOAD_NAMED_FAILED
        raise ValueError(
            f"NetTap couldn't read {', '.join(names[:_DOWNLOAD_NAMED_FAILED])}"
            + (f" and {more} more" if more > 0 else "")
            + ", so it can't tell whether they hold packets from this window and the "
            "download would be incomplete. Download those files on their own from the "
            "file list."
        )
    size = sum(f.size for f, _ in sel.files)
    # OLD CODE START — NET-189 review: see _window_packets
    # packets = sum(e.packets or 0 for _, e in sel.files)  # indexed entries carry it
    # OLD CODE END
    packets = _window_packets(sel, start, end)
    if (
        len(sel.files) > MAX_FILES
        or size > MAX_BYTES
        or packets > _DOWNLOAD_MAX_PACKETS
    ):
        raise ValueError(
            f"This window holds about {packets:,} packets in {len(sel.files)} capture files "
            f"({size / 1e9:.1f} GB). One download reads at most "
            f"{_DOWNLOAD_MAX_PACKETS:,} packets, {MAX_FILES} files or "
            f"{MAX_BYTES / 1e9:.0f} GB. Set a shorter download window, use Packet "
            "analysis, or download single files."
        )


async def _check_download_filter(display_filter: str) -> None:
    """ValueError with TShark's own message when it refuses the filter. The caller
    holds a reader slot."""
    result = await run_in_tshark(
        CHECK_JOB,
        [display_filter.strip()],
        deadline_s=CHECK_SECONDS,
        max_stdout=64 * 1024,
    )
    rc = result.status("tshark")
    raise_filter_check_failure(-1 if rc is None else rc, result.stderr, ValueError)
