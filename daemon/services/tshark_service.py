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
import re
import shlex
from dataclasses import dataclass, field
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
ALLOWED_FIELD_PATTERN = re.compile(r"^[a-z0-9_.]+$")
# Shell metacharacters that must NOT appear in display filters.
# Note: & and | are allowed because TShark uses && (AND) and || (OR)
# as valid display filter operators. Since we use subprocess_exec (not
# shell=True), these are safe — each argument is passed directly to the
# process without shell interpretation.
SHELL_METACHAR_PATTERN = re.compile(r"[;`$\"'\n\r\x00]")
ALLOWED_OUTPUT_FORMATS = {"json", "text", "pdml"}


@dataclass
class TSharkRequest:
    pcap_path: str
    display_filter: str = ""
    max_packets: int = DEFAULT_MAX_PACKETS
    output_format: str = "json"
    fields: list[str] = field(default_factory=list)


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
        return request

    # --- TShark command execution ---

    def _build_tshark_command(self, request: TSharkRequest) -> list[str]:
        """Build the tshark command-line arguments."""
        cmd = ["docker", "exec", TSHARK_CONTAINER, "tshark"]

        # Input file
        cmd.extend(["-r", request.pcap_path])

        # Max packets
        cmd.extend(["-c", str(request.max_packets)])

        # Display filter
        if request.display_filter:
            cmd.extend(["-Y", request.display_filter])

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

        return cmd

    async def _run_container_command(self, cmd: list[str]) -> tuple[str, str, int]:
        """Run a command via asyncio subprocess with timeout and output limits.

        Uses asyncio.create_subprocess_exec (argument-list form, no shell
        interpolation) for safety. Returns (stdout, stderr, returncode).
        """
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
            return []

    def _parse_text_output(self, stdout: str) -> list[dict]:
        """Parse TShark text output into structured dicts."""
        packets = []
        for i, line in enumerate(stdout.strip().split("\n")):
            if line.strip():
                packets.append({"no": i + 1, "raw": line.strip()})
        return packets

    # --- Public API ---

    async def analyze(self, request: TSharkRequest) -> TSharkResult:
        """Run TShark analysis on a PCAP file.

        Validates the request, runs TShark in the container,
        and returns structured results.
        """
        # Validate
        request = self.validate_request(request)

        # Build command
        cmd = self._build_tshark_command(request)

        # Run
        stdout, stderr, returncode = await self._exec_tshark(cmd)

        if returncode != 0 and not stdout:
            return TSharkResult(
                packets=[],
                packet_count=0,
                truncated=False,
                tshark_version=await self.get_version(),
                error=stderr.strip() or f"TShark exited with code {returncode}",
            )

        # Parse output
        if request.output_format == "json":
            packets = self._parse_json_output(stdout)
        else:
            packets = self._parse_text_output(stdout)

        truncated = len(stdout.encode()) >= MAX_OUTPUT_BYTES

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
        try:
            cmd = ["docker", "exec", TSHARK_CONTAINER, "tshark", "-G", "protocols"]
            stdout, _, rc = await self._exec_tshark(cmd)
            if rc == 0:
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
        except Exception as e:
            logger.error("Failed to get protocols: %s", e)
        return []

    async def get_fields(self, protocol: str = "") -> list[dict]:
        """Get display filter fields, optionally filtered by protocol (cached)."""
        cache_key = protocol or "__all__"
        if cache_key in self._fields_cache:
            return self._fields_cache[cache_key]
        try:
            cmd = ["docker", "exec", TSHARK_CONTAINER, "tshark", "-G", "fields"]
            stdout, _, rc = await self._exec_tshark(cmd)
            if rc == 0:
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
                        if (
                            not protocol
                            or entry["protocol"].lower() == protocol.lower()
                        ):
                            fields.append(entry)
                self._fields_cache[cache_key] = fields
                return fields
        except Exception as e:
            logger.error("Failed to get fields: %s", e)
        return []

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

    async def validate_filter_dry_run(self, display_filter: str) -> bool:
        """Validate a display filter by running tshark -Y <filter> -r /dev/null.

        Returns True if the filter is syntactically valid.
        """
        self.validate_display_filter(display_filter)  # Basic sanitization first
        try:
            cmd = [
                "docker",
                "exec",
                TSHARK_CONTAINER,
                "tshark",
                "-Y",
                display_filter,
                "-r",
                "/dev/null",
            ]
            _, stderr, rc = await self._exec_tshark(cmd)
            # tshark returns 0 for valid filters (even with no packets)
            # and non-zero for invalid filter syntax
            return rc == 0
        except Exception:
            return False
