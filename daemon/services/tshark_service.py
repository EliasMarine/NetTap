"""
NetTap TShark Service -- On-demand packet analysis via containerized TShark.

All TShark operations run inside the nettap-tshark container via docker exec.
This module NEVER imports any Wireshark/TShark libraries -- all interaction
is via subprocess (docker exec) for GPL compliance and security isolation.

Security:
    - PCAP paths validated against allowed directory (no traversal)
    - Display filters sanitized against shell metacharacters
    - Output capped at MAX_OUTPUT_BYTES (5MB)
    - Execution timeout: 30 seconds
    - Max packets capped at 1000
"""

import asyncio
import json
import logging
import os
import re
import shlex
from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath
from typing import Any

logger = logging.getLogger("nettap.tshark")

# --- Constants ---
TSHARK_CONTAINER = "nettap-tshark"
PCAP_MOUNT_PATH = "/pcap"  # Path inside the tshark container
MAX_PACKETS = 1000
DEFAULT_MAX_PACKETS = 100
EXECUTION_TIMEOUT = 30  # seconds
MAX_OUTPUT_BYTES = 5 * 1024 * 1024  # 5MB
# A filtered analysis first scans for its matches (#64); the scan stops here and keeps
# what it found, leaving the rest of the web proxy's 60 s for the JSON and Info passes.
MATCH_SCAN_SECONDS = 15
# "<matches found> <frame number of the last>" for up to N matches (fewer if the file or
# the time runs out). Filter and path are positional args, never parsed by the shell.
# -l flushes each line: piped tshark otherwise buffers 4 KB, never notices head has quit, and
# reads the rest of the file, so every scan ran the full MATCH_SCAN_SECONDS (#78)
_LAST_MATCH_SCRIPT = (
    'timeout -k 2 "$4" tshark -l -r "$1" -Y "$2" -T fields -e frame.number 2>/dev/null'
    " | head -n \"$3\" | awk 'END { print NR, $1 }'"
)
# OLD CODE START — #78: without -l the scan always used the whole 15 s budget
# _LAST_MATCH_SCRIPT = (
#     'timeout -k 2 "$4" tshark -r "$1" -Y "$2" -T fields -e frame.number 2>/dev/null'
#     ' | head -n "$3" | awk \'END { print NR, $1 }\''
# )
# OLD CODE END
ALLOWED_FIELD_PATTERN = re.compile(r"^[a-z0-9_.]+$")
# Shell metacharacters that must NOT appear in display filters.
# Note: & and | are allowed because TShark uses && (AND) and || (OR)
# as valid display filter operators. Since we use subprocess_exec (not
# shell=True), these are safe — each argument is passed directly to the
# process without shell interpretation.
SHELL_METACHAR_PATTERN = re.compile(r"[;`$\"'\n\r\x00]")
ALLOWED_OUTPUT_FORMATS = {"json", "text", "pdml"}


ALLOWED_FOLLOW_PROTOCOLS = {"", "tcp", "udp", "tls", "http"}

# Max concurrent TShark docker exec operations.  The nettap-tshark container
# is capped at 1 CPU (0.5 before #137); more than 2 simultaneous analyses thrash it
# and increase the chance of hitting the 30s timeout.
MAX_CONCURRENT_ANALYSES = 2


def bounded_exec(cmd: list[str], seconds: int) -> list[str]:
    """Run a ``docker exec <container> ...`` argv under coreutils ``timeout`` inside it.

    Giving up on the docker exec client (asyncio timeout, kill) leaves the process
    running in the container: on the G11 seven orphaned full-file tshark reads held it
    at its 1 GiB limit and every analysis took minutes. ``-k 5`` follows up with KILL.
    """
    if cmd[:2] != ["docker", "exec"] or len(cmd) < 4:
        return cmd
    return [*cmd[:3], "timeout", "-k", "5", str(seconds), *cmd[3:]]


_ROOT_WARNING = (
    'Running as user "root"'  # tshark prints this on every run in the container
)


def filter_check_cmd(pcap_path: str, display_filter: str) -> list[str]:
    """tshark reads one packet with the filter: exit 0 when the filter compiles (#96).

    The match scan and the filtered preview pipe tshark into head, so their exit status
    is head's. pipefail can't help: TShark 4.0 also exits 2 when head quits early, the
    same code it gives a filter it refuses.
    """
    return [
        "docker",
        "exec",
        TSHARK_CONTAINER,
        "tshark",
        "-r",
        pcap_path,
        "-Y",
        display_filter,
        "-c",
        "1",
        "-T",
        "fields",
        "-e",
        "frame.number",
    ]


def raise_filter_check_failure(
    returncode: int, stderr: str, refused: type[Exception]
) -> None:
    """Return if the check passed. Raise `refused` carrying tshark's message when tshark
    refused the filter (or file), RuntimeError when docker exec itself failed."""
    if returncode == 0:
        return
    lines = [
        line
        for line in stderr.strip().splitlines()
        if not line.startswith(_ROOT_WARNING)
    ]
    message = "\n".join(lines).strip() or f"tshark exited with code {returncode}"
    raise (refused if message.startswith("tshark:") else RuntimeError)(message)


@dataclass
class TSharkRequest:
    pcap_path: str
    display_filter: str = ""
    max_packets: int = DEFAULT_MAX_PACKETS
    output_format: str = "json"
    fields: list[str] = field(default_factory=list)
    include_hex: bool = False
    verbose: bool = False
    follow_stream: str = ""  # 'tcp'|'udp'|'tls'|'http'|''


@dataclass
class TSharkResult:
    packets: list[dict[str, Any]]
    packet_count: int
    truncated: bool
    tshark_version: str
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "packets": self.packets,
            "packet_count": self.packet_count,
            "truncated": self.truncated,
            "tshark_version": self.tshark_version,
            "error": self.error,
        }


class TSharkValidationError(Exception):
    """Raised when request validation fails."""

    pass


class TSharkService:
    def __init__(self, pcap_base_dir: str = "/opt/nettap/pcap"):
        self.pcap_base_dir = pcap_base_dir
        self._tshark_version: str | None = None
        self._protocols_cache: list[dict] | None = None
        self._fields_cache: dict[str, list[dict]] = {}
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_ANALYSES)

    @property
    def semaphore(self) -> asyncio.Semaphore:
        """The reader slots, shared with PCAP Search and packet analysis (NET-188)."""
        return self._semaphore

    # --- Validation methods ---

    def validate_pcap_path(self, pcap_path: str) -> str:
        """Validate and normalize the PCAP path. Returns the container-internal path.

        Raises TSharkValidationError on traversal attempt or invalid path.
        """
        # Normalize the path
        normalized = PurePosixPath(pcap_path)

        # Check for traversal - resolve against base
        # The pcap_path should be relative or absolute under pcap_base_dir
        if pcap_path.startswith("/"):
            # Absolute path -- must be under pcap_base_dir
            try:
                normalized.relative_to(self.pcap_base_dir)
            except ValueError:
                raise TSharkValidationError(
                    f"PCAP path must be under {self.pcap_base_dir}"
                )
            # Convert host path to container path
            relative = str(normalized.relative_to(self.pcap_base_dir))
            container_path = f"{PCAP_MOUNT_PATH}/{relative}"
        else:
            # Relative path -- must not contain ..
            if ".." in normalized.parts:
                raise TSharkValidationError("Path traversal detected in pcap_path")
            container_path = f"{PCAP_MOUNT_PATH}/{pcap_path}"

        # Verify no remaining traversal
        resolved = PurePosixPath(container_path)
        try:
            resolved.relative_to(PCAP_MOUNT_PATH)
        except ValueError:
            raise TSharkValidationError("Path traversal detected after normalization")

        # Must end with .pcap or .pcapng
        suffix = normalized.suffix.lower()
        if suffix not in (".pcap", ".pcapng", ".cap"):
            raise TSharkValidationError(f"Invalid PCAP file extension: {suffix}")

        # Check file existence on the daemon side.  The daemon mounts the
        # same pcap-data volume (at self.pcap_base_dir), so we can verify
        # the file exists before spawning a docker exec that would fail
        # with an opaque TShark error.
        if pcap_path.startswith("/"):
            daemon_path = str(normalized)
        else:
            daemon_path = os.path.join(self.pcap_base_dir, pcap_path)

        if not os.path.exists(daemon_path):
            # Extract just the filename for a clear error message
            filename = PurePosixPath(pcap_path).name
            raise TSharkValidationError(f"PCAP file not found: {filename}")

        return container_path

    def validate_display_filter(self, display_filter: str) -> str:
        """Sanitize display filter string.

        Raises TSharkValidationError on dangerous characters.
        """
        if not display_filter:
            return ""

        # Check for shell metacharacters
        if SHELL_METACHAR_PATTERN.search(display_filter):
            raise TSharkValidationError("Display filter contains forbidden characters")

        # Length limit
        if len(display_filter) > 500:
            raise TSharkValidationError("Display filter too long (max 500 chars)")

        return display_filter

    def validate_fields(self, fields: list[str]) -> list[str]:
        """Validate field names match the allowed pattern."""
        validated = []
        for f in fields:
            if not ALLOWED_FIELD_PATTERN.match(f):
                raise TSharkValidationError(
                    f"Invalid field name: {f!r} (must match [a-z0-9_.]+)"
                )
            validated.append(f)
        if len(validated) > 50:
            raise TSharkValidationError("Too many fields (max 50)")
        return validated

    def validate_request(self, request: TSharkRequest) -> TSharkRequest:
        """Validate all fields of a TSharkRequest."""
        request.pcap_path = self.validate_pcap_path(request.pcap_path)
        request.display_filter = self.validate_display_filter(request.display_filter)
        request.fields = self.validate_fields(request.fields)
        request.max_packets = min(max(1, request.max_packets), MAX_PACKETS)
        if request.output_format not in ALLOWED_OUTPUT_FORMATS:
            raise TSharkValidationError(
                f"Invalid output format: {request.output_format}"
            )
        if request.follow_stream not in ALLOWED_FOLLOW_PROTOCOLS:
            raise TSharkValidationError(
                f"Invalid follow protocol: {request.follow_stream}"
            )
        return request

    # --- TShark command execution ---

    def _build_tshark_command(self, request: TSharkRequest) -> list[str]:
        """Build the tshark command-line arguments."""
        cmd = ["docker", "exec", TSHARK_CONTAINER, "tshark"]

        # Input file
        cmd.extend(["-r", request.pcap_path])

        # Follow stream mode: uses -q -z follow,<proto>,ascii,<filter>
        # No -Y, no -c, no -T flags — follow processes the entire file.
        #
        # The -z follow filter accepts either a stream index (e.g. "0") or a
        # display filter (e.g. "ip.addr==10.0.0.1 && tcp.port==443").
        # Defaulting to stream index "0" when no filter is provided is
        # misleading — it silently follows an arbitrary stream that may be
        # unrelated to the user's intent.  Instead, require a display_filter
        # to be present; if none was given, skip follow mode entirely and
        # fall through to normal packet listing so the caller gets useful
        # output rather than a random stream.
        if request.follow_stream:
            if request.display_filter:
                cmd.append("-q")
                cmd.extend(
                    [
                        "-z",
                        f"follow,{request.follow_stream},ascii,{request.display_filter}",
                    ]
                )
                return cmd
            # No display filter — cannot meaningfully follow a stream.
            # Fall through to normal packet output so the caller still
            # gets data instead of an error or a random stream 0.

        # Max packets
        cmd.extend(["-c", str(request.max_packets)])

        # Display filter
        if request.display_filter:
            cmd.extend(["-Y", request.display_filter])

        # Verbose mode: adds -V flag, forces text output
        if request.verbose:
            cmd.append("-V")
            # No -T flag — verbose text is the default
            return cmd

        # Specific fields override output format
        if request.fields:
            cmd.extend(["-T", "fields"])
            for f in request.fields:
                cmd.extend(["-e", f])
            cmd.extend(["-E", "header=y", "-E", "separator=,"])
        elif request.output_format == "json":
            cmd.extend(["-T", "json"])
        elif request.output_format == "pdml":
            cmd.extend(["-T", "pdml"])
        # "text" is the default -- no -T flag needed

        # Hex dump flag
        if request.include_hex:
            cmd.append("-x")

        return cmd

    async def _run_container_command(self, cmd: list[str]) -> tuple[str, str, int]:
        """Run a command via asyncio subprocess with timeout and output limits.

        Uses asyncio.create_subprocess_exec (argument-list form, no shell
        interpolation) for safety. Returns (stdout, stderr, returncode).
        """
        cmd = bounded_exec(cmd, EXECUTION_TIMEOUT)
        logger.info("Running: %s", " ".join(shlex.quote(c) for c in cmd))

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=MAX_OUTPUT_BYTES,
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=EXECUTION_TIMEOUT,
            )

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            # Truncate if needed
            if len(stdout_bytes) >= MAX_OUTPUT_BYTES:
                stdout = stdout[:MAX_OUTPUT_BYTES]
                logger.warning("TShark output truncated at %d bytes", MAX_OUTPUT_BYTES)

            return stdout, stderr, process.returncode or 0

        except asyncio.TimeoutError:
            logger.error("TShark timed out after %ds", EXECUTION_TIMEOUT)
            process.kill()
            await process.wait()
            raise TSharkValidationError(
                f"TShark execution timed out after {EXECUTION_TIMEOUT}s"
            )

    # Keep _exec_tshark as an alias for backward compatibility
    async def _exec_tshark(self, cmd: list[str]) -> tuple[str, str, int]:
        """Alias for _run_container_command."""
        return await self._run_container_command(cmd)

    def _parse_json_output(self, stdout: str) -> list[dict]:
        """Parse TShark JSON output into a list of packet dicts."""
        if not stdout.strip():
            return []
        try:
            data = json.loads(stdout)
            if isinstance(data, list):
                return data
            return [data]
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse TShark JSON output: %s", e)
            # OLD CODE START — #96: unparsable output (e.g. cut at the size limit) read as 0 packets
            # return []
            # OLD CODE END
            raise RuntimeError(f"TShark output could not be parsed: {e}") from e

    def _info_column_command(self, request: TSharkRequest) -> list[str]:
        """Same packets as the JSON pass, printing only frame number and Info."""
        cmd = ["docker", "exec", TSHARK_CONTAINER, "tshark", "-r", request.pcap_path]
        cmd.extend(["-c", str(request.max_packets)])
        if request.display_filter:
            cmd.extend(["-Y", request.display_filter])
        # TShark 4.0 names the columns _ws.col.Info (4.2+ renamed them _ws.col.info)
        # OLD CODE START — #141: the table took the protocol from frame.protocols' last
        # entry, so a payload tshark couldn't decode read "DATA" where Wireshark says UDP
        # cmd.extend(["-T", "fields", "-e", "frame.number", "-e", "_ws.col.Info"])
        # OLD CODE END
        cmd.extend(
            [
                "-T",
                "fields",
                "-e",
                "frame.number",
                "-e",
                "_ws.col.Protocol",
                "-e",
                "_ws.col.Info",
            ]
        )
        return cmd

    @staticmethod
    def _with_info_column(packets: list[dict], stdout: str) -> list[dict]:
        """Copy each packet with Wireshark's Protocol and Info columns added to its layers."""
        # OLD CODE START — #141: Info only; the Protocol column comes from the same pass now
        # info_by_frame = dict(
        #     line.split("\t", 1) for line in stdout.splitlines() if "\t" in line
        # )
        # OLD CODE END
        columns_by_frame = {}
        for line in stdout.splitlines():
            parts = line.split("\t", 2)  # Info is last, so a tab inside it stays in it
            if len(parts) == 3:
                columns_by_frame[parts[0]] = {
                    "_ws.col.Protocol": parts[1],
                    "_ws.col.Info": parts[2],
                }
        merged = []
        for pkt in packets:
            layers = pkt.get("_source", {}).get("layers")
            number = (layers or {}).get("frame", {}).get("frame.number")
            columns = columns_by_frame.get(str(number))
            if columns is None:
                merged.append(pkt)
                continue
            source = {**pkt["_source"], "layers": {**layers, **columns}}
            merged.append({**pkt, "_source": source})
        return merged

    def _parse_text_output(self, stdout: str) -> list[dict]:
        """Parse TShark text output into structured dicts."""
        packets = []
        for i, line in enumerate(stdout.strip().split("\n")):
            if line.strip():
                packets.append({"no": i + 1, "raw": line.strip()})
        return packets

    # --- Public API ---

    async def _last_match_frame(self, request: TSharkRequest) -> tuple[int, bool]:
        """(frame number of the request's Nth filter match or 0 for none, scan timed out).

        -c counts packets read, not matches, so "-c 100 -Y dns" only searched the first
        100 packets of a file (#64). Reading up to this frame returns the first N matches.
        """
        cmd = [
            "docker",
            "exec",
            TSHARK_CONTAINER,
            "sh",
            "-c",
            _LAST_MATCH_SCRIPT,
            "_",
            request.pcap_path,
            request.display_filter,
            str(request.max_packets),
            str(MATCH_SCAN_SECONDS),
        ]
        loop = asyncio.get_running_loop()
        started = loop.time()
        # OLD CODE START — #96: a failed docker exec (container down) read as "no matches"
        # stdout, _, _ = await self._exec_tshark(cmd)
        # OLD CODE END
        # The pipeline's status is awk's, so non-zero means docker exec itself failed
        stdout, stderr, rc = await self._exec_tshark(cmd)
        if rc != 0:
            raise RuntimeError(stderr.strip() or f"TShark scan exited with code {rc}")
        found, _, last = stdout.strip().partition(" ")
        found_n = int(found) if found.isdigit() else 0
        if not found_n:
            # a filter tshark refused also prints "0" here: its error went to /dev/null (#96)
            await self.validate_filter_dry_run(
                request.display_filter, request.pcap_path
            )
        # Cut short = fewer than N matches and the whole time budget used. shortcut: a file
        # that really ends right at the budget is reported the same way
        timed_out = (
            found_n < request.max_packets
            and loop.time() - started >= MATCH_SCAN_SECONDS
        )
        return (int(last) if found_n and last.isdigit() else 0), timed_out

    async def analyze(self, request: TSharkRequest) -> TSharkResult:
        """Run TShark analysis on a PCAP file.

        Validates the request, runs TShark in the container,
        and returns structured results.  A semaphore limits concurrent
        docker exec operations to MAX_CONCURRENT_ANALYSES to avoid
        thrashing the CPU-limited tshark container.
        """
        # Validate (before acquiring semaphore -- fast, no I/O)
        request = self.validate_request(request)

        # OLD CODE START — #64: the command is built after the match scan below, which may
        # raise the -c limit to the frame number of the Nth match
        # # Build command
        # cmd = self._build_tshark_command(request)
        # OLD CODE END
        scan_timed_out = False

        # Acquire semaphore to limit concurrent docker exec processes.
        # Queued requests still respect the overall EXECUTION_TIMEOUT
        # because _exec_tshark applies asyncio.wait_for internally.
        async with self._semaphore:
            logger.debug(
                "Semaphore acquired for analysis (%d/%d slots in use)",
                MAX_CONCURRENT_ANALYSES - self._semaphore._value,
                MAX_CONCURRENT_ANALYSES,
            )
            if request.display_filter and not request.follow_stream:
                last_frame, scan_timed_out = await self._last_match_frame(request)
                if not last_frame:
                    return TSharkResult(
                        packets=[],
                        packet_count=0,
                        truncated=scan_timed_out,  # more of the file was left unsearched
                        tshark_version=await self.get_version(),
                    )
                request = replace(request, max_packets=last_frame)
            cmd = self._build_tshark_command(request)
            stdout, stderr, returncode = await self._exec_tshark(cmd)
            # -T json has no column data, so the Info column comes from a second,
            # fields-only pass over the same packets
            info_stdout = ""
            wants_info = (
                request.output_format == "json"
                and not (request.fields or request.verbose or request.follow_stream)
                and stdout.strip()
            )
            if wants_info:
                try:
                    info_stdout, _, _ = await self._exec_tshark(
                        self._info_column_command(request)
                    )
                except TSharkValidationError as exc:
                    logger.warning("TShark Info column pass failed: %s", exc)

        if returncode != 0 and not stdout:
            return TSharkResult(
                packets=[],
                packet_count=0,
                truncated=False,
                tshark_version=await self.get_version(),
                error=stderr.strip() or f"TShark exited with code {returncode}",
            )

        # Parse output
        if request.follow_stream or request.verbose:
            # Follow stream and verbose modes return raw text
            packets = self._parse_text_output(stdout)
        elif request.output_format == "json":
            packets = self._with_info_column(
                self._parse_json_output(stdout), info_stdout
            )
        else:
            packets = self._parse_text_output(stdout)

        # OLD CODE START — #64: a filter scan cut short by time also means more matches may exist
        # truncated = len(stdout.encode()) >= MAX_OUTPUT_BYTES
        # OLD CODE END
        truncated = len(stdout.encode()) >= MAX_OUTPUT_BYTES or scan_timed_out

        return TSharkResult(
            packets=packets,
            packet_count=len(packets),
            truncated=truncated,
            tshark_version=await self.get_version(),
        )

    async def get_version(self) -> str:
        """Get TShark version string (cached)."""
        if self._tshark_version:
            return self._tshark_version
        try:
            cmd = ["docker", "exec", TSHARK_CONTAINER, "tshark", "--version"]
            stdout, _, rc = await self._exec_tshark(cmd)
            if rc == 0 and stdout:
                # First line is like "TShark (Wireshark) 4.2.2 (...)"
                first_line = stdout.split("\n")[0]
                self._tshark_version = first_line.strip()
                return self._tshark_version
        except Exception as e:
            logger.error("Failed to get TShark version: %s", e)
        return "unknown"

    async def get_protocols(self) -> list[dict]:
        """Get supported protocol dissectors (cached)."""
        if self._protocols_cache is not None:
            return self._protocols_cache
        # OLD CODE START — #96: a failure (container down) read as "no protocols"
        # try:
        #     ...
        #     if rc == 0:
        #         ...
        #         return protocols
        # except Exception as e:
        #     logger.error("Failed to get protocols: %s", e)
        # return []
        # OLD CODE END
        cmd = ["docker", "exec", TSHARK_CONTAINER, "tshark", "-G", "protocols"]
        stdout, stderr, rc = await self._exec_tshark(cmd)
        if rc != 0:
            raise RuntimeError(stderr.strip() or f"tshark -G exited with code {rc}")
        protocols = []
        for line in stdout.strip().split("\n"):
            parts = line.split("\t")
            if len(parts) >= 3:
                protocols.append(
                    {
                        "name": parts[0],
                        "short_name": parts[1],
                        "filter_name": parts[2],
                    }
                )
        self._protocols_cache = protocols
        return protocols

    async def get_fields(self, protocol: str = "") -> list[dict]:
        """Get display filter fields, optionally filtered by protocol (cached)."""
        cache_key = protocol or "__all__"
        if cache_key in self._fields_cache:
            return self._fields_cache[cache_key]
        # OLD CODE START — #96: a failure (container down) read as "no fields"
        # try:
        #     ...
        #     if rc == 0:
        #         ...
        #         return fields
        # except Exception as e:
        #     logger.error("Failed to get fields: %s", e)
        # return []
        # OLD CODE END
        cmd = ["docker", "exec", TSHARK_CONTAINER, "tshark", "-G", "fields"]
        stdout, stderr, rc = await self._exec_tshark(cmd)
        if rc != 0:
            raise RuntimeError(stderr.strip() or f"tshark -G exited with code {rc}")
        fields = []
        for line in stdout.strip().split("\n"):
            parts = line.split("\t")
            if len(parts) >= 4:
                entry = {
                    "name": parts[2] if len(parts) > 2 else "",
                    "filter_name": parts[2] if len(parts) > 2 else "",
                    "type": parts[3] if len(parts) > 3 else "",
                    "protocol": parts[1] if len(parts) > 1 else "",
                    "description": parts[0] if len(parts) > 0 else "",
                }
                if not protocol or entry["protocol"].lower() == protocol.lower():
                    fields.append(entry)
        self._fields_cache[cache_key] = fields
        return fields

    async def is_available(self) -> dict:
        """Check if TShark container is running and accessible."""
        try:
            cmd = [
                "docker",
                "inspect",
                "--format",
                "{{.State.Running}}",
                TSHARK_CONTAINER,
            ]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, _ = await asyncio.wait_for(process.communicate(), timeout=5)
            running = stdout_b.decode().strip().lower() == "true"
            version = await self.get_version() if running else "unknown"
            return {
                "available": running,
                "version": version,
                "container_running": running,
                "container_name": TSHARK_CONTAINER,
            }
        except Exception as e:
            logger.error("Failed to check TShark availability: %s", e)
            return {
                "available": False,
                "version": "unknown",
                "container_running": False,
                "container_name": TSHARK_CONTAINER,
                "error": str(e),
            }

    def list_pcap_files(self) -> list[dict]:
        """List available PCAP files in the pcap base directory."""
        import os

        pcaps = []
        base = self.pcap_base_dir
        if not os.path.isdir(base):
            return []
        for root, _dirs, files in os.walk(base):
            for f in files:
                if f.lower().endswith((".pcap", ".pcapng", ".cap")):
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, base)
                    try:
                        stat = os.stat(full)
                        pcaps.append(
                            {
                                "path": full,
                                "relative_path": rel,
                                "name": f,
                                "size_bytes": stat.st_size,
                                "modified": stat.st_mtime,
                            }
                        )
                    except OSError:
                        continue
        pcaps.sort(key=lambda p: p["modified"], reverse=True)
        return pcaps

    async def validate_filter_dry_run(
        self, display_filter: str, pcap_path: str
    ) -> None:
        """Raise TSharkValidationError carrying tshark's message if it refuses the filter.

        Reads one packet of pcap_path (a path inside the container) with the filter.
        """
        # OLD CODE START — #96: tshark refuses /dev/null as "a special file" (exit 2, TShark
        # 4.0), so every filter came back invalid; nothing called it
        # self.validate_display_filter(display_filter)  # Basic sanitization first
        # try:
        #     cmd = [
        #         "docker",
        #         "exec",
        #         TSHARK_CONTAINER,
        #         "tshark",
        #         "-Y",
        #         display_filter,
        #         "-r",
        #         "/dev/null",
        #     ]
        #     _, stderr, rc = await self._exec_tshark(cmd)
        #     # tshark returns 0 for valid filters (even with no packets)
        #     # and non-zero for invalid filter syntax
        #     return rc == 0
        # except Exception:
        #     return False
        # OLD CODE END
        self.validate_display_filter(display_filter)  # Basic sanitization first
        _, stderr, rc = await self._exec_tshark(
            filter_check_cmd(pcap_path, display_filter)
        )
        raise_filter_check_failure(rc, stderr, TSharkValidationError)
