"""
NetTap Version Inventory Service

Detects running versions of all NetTap components by querying Docker,
system packages, and file metadata. Provides a unified view of the
software stack for the update system.
"""

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("nettap.services.version_manager")

# Current NetTap daemon version
NETTAP_VERSION = "0.4.0"

# Cache staleness threshold: 10 minutes
_CACHE_TTL_SECONDS = 600


@dataclass
class ComponentVersion:
    """Version information for a single NetTap component."""

    name: str               # e.g. "zeek", "suricata", "opensearch"
    category: str           # "core", "docker", "system", "database", "os"
    current_version: str    # e.g. "6.0.4", "7.0.3"
    install_type: str       # "docker", "apt", "pip", "npm", "builtin"
    last_checked: str       # ISO timestamp
    status: str             # "ok", "unknown", "error"
    details: dict           # extra info (image ID, package source, etc.)

    def to_dict(self) -> dict:
        return asdict(self)


class VersionManager:
    """Inventories running versions of all NetTap components.

    Queries Docker images, system packages, database metadata, and OS
    information to build a unified version inventory. Results are cached
    and refreshed on demand or when stale.
    """

    def __init__(
        self,
        compose_file: str = "/opt/nettap/docker/docker-compose.yml",
    ) -> None:
        self._compose_file = compose_file
        self._versions: dict[str, ComponentVersion] = {}
        self._last_scan: str | None = None
        self._scanning: bool = False

        logger.info(
            "VersionManager initialized: compose_file=%s",
            compose_file,
        )

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    async def scan_versions(self) -> dict:
        """Full version scan of all components.

        Scans core NetTap components, Docker images, system packages,
        databases, and OS information. Updates the internal cache.

        Returns:
            Dict with "versions" (list of ComponentVersion dicts),
            "last_scan" (ISO timestamp), and "count" (int).
        """
        self._scanning = True
        now = datetime.now(timezone.utc).isoformat()

        try:
            # Run all scan categories
            results: list[ComponentVersion] = []

            core = await self._scan_core()
            results.extend(core)

            docker = await self._scan_docker_images()
            results.extend(docker)

            system = await self._scan_system_packages()
            results.extend(system)

            databases = await self._scan_databases()
            results.extend(databases)

            os_info = await self._scan_os_info()
            results.extend(os_info)

            # Update cache (keyed by component name)
            self._versions = {cv.name: cv for cv in results}
            self._last_scan = now

            logger.info(
                "Version scan complete: %d components detected", len(results)
            )

            return {
                "versions": [cv.to_dict() for cv in results],
                "last_scan": self._last_scan,
                "count": len(results),
            }
        finally:
            self._scanning = False

    async def get_versions(self) -> dict:
        """Return cached versions, scanning if stale or empty.

        Returns:
            Dict with "versions" (list), "last_scan" (ISO timestamp),
            and "count" (int).
        """
        if self._is_cache_stale():
            return await self.scan_versions()

        versions_list = [cv.to_dict() for cv in self._versions.values()]
        return {
            "versions": versions_list,
            "last_scan": self._last_scan,
            "count": len(versions_list),
        }

    async def get_component(self, name: str) -> dict | None:
        """Get version info for a specific component.

        Args:
            name: Component name (e.g. "zeek", "suricata").

        Returns:
            Dict with component version info, or None if not found.
        """
        if not self._versions:
            await self.scan_versions()

        cv = self._versions.get(name)
        if cv is None:
            return None
        return cv.to_dict()

    # -------------------------------------------------------------------
    # Internal scan methods
    # -------------------------------------------------------------------

    async def _scan_core(self) -> list[ComponentVersion]:
        """Scan NetTap core component versions.

        Detects daemon version, web UI version (from package.json),
        and config version.
        """
        now = datetime.now(timezone.utc).isoformat()
        results: list[ComponentVersion] = []

        # Daemon version (from module constant)
        results.append(ComponentVersion(
            name="nettap-daemon",
            category="core",
            current_version=NETTAP_VERSION,
            install_type="pip",
            last_checked=now,
            status="ok",
            details={"source": "module_constant"},
        ))

        # Web UI version (from package.json)
        web_version = "unknown"
        web_status = "unknown"
        web_details: dict[str, Any] = {}

        # Try multiple possible locations for package.json
        package_paths = [
            "/opt/nettap/web/package.json",
            os.path.join(os.path.dirname(self._compose_file), "..", "web", "package.json"),
        ]

        for pkg_path in package_paths:
            try:
                with open(pkg_path, "r") as f:
                    pkg_data = json.load(f)
                    web_version = pkg_data.get("version", "unknown")
                    web_status = "ok"
                    web_details = {"package_json": pkg_path}
                    break
            except (FileNotFoundError, json.JSONDecodeError, PermissionError):
                continue

        results.append(ComponentVersion(
            name="nettap-web",
            category="core",
            current_version=web_version,
            install_type="npm",
            last_checked=now,
            status=web_status,
            details=web_details,
        ))

        # Config version (based on compose file existence)
        config_version = "unknown"
        config_status = "unknown"
        config_details: dict[str, Any] = {}
        try:
            if os.path.exists(self._compose_file):
                mtime = os.path.getmtime(self._compose_file)
                config_version = datetime.fromtimestamp(
                    mtime, tz=timezone.utc
                ).strftime("%Y%m%d")
                config_status = "ok"
                config_details = {"compose_file": self._compose_file}
        except OSError as exc:
            config_details = {"error": str(exc)}

        results.append(ComponentVersion(
            name="nettap-config",
            category="core",
            current_version=config_version,
            install_type="builtin",
            last_checked=now,
            status=config_status,
            details=config_details,
        ))

        return results

    async def _scan_docker_images(self) -> list[ComponentVersion]:
        """Scan Docker container image versions.

        Queries running containers and their image tags via
        ``docker ps``.
        """
        now = datetime.now(timezone.utc).isoformat()
        results: list[ComponentVersion] = []

        # Malcolm container name-to-component mapping
        malcolm_containers = [
            "zeek",
            "suricata",
            "arkime",
            "opensearch",
            "dashboards",
            "logstash",
            "file-monitor",
            "pcap-capture",
            "freq",
            "htadmin",
            "nginx-proxy",
        ]

        # Try to get running container versions via docker
        try:
            output = await self._run_command([
                "docker", "ps", "--format", "{{.Names}}\t{{.Image}}\t{{.ID}}"
            ])

            if output:
                for line in output.strip().split("\n"):
                    if not line.strip():
                        continue
                    parts = line.split("\t")
                    if len(parts) < 2:
                        continue

                    container_name = parts[0].strip()
                    image = parts[1].strip()
                    container_id = parts[2].strip() if len(parts) > 2 else ""

                    # Extract version from image tag
                    # e.g., "malcolm/zeek:v26.02.0" -> "v26.02.0"
                    tag = "latest"
                    if ":" in image:
                        tag = image.split(":")[-1]

                    # Match to known Malcolm containers
                    component_name = None
                    for mc in malcolm_containers:
                        if mc in container_name.lower():
                            component_name = mc
                            break

                    if component_name is None:
                        # Use container name as-is for non-Malcolm containers
                        component_name = container_name

                    results.append(ComponentVersion(
                        name=component_name,
                        category="docker",
                        current_version=tag,
                        install_type="docker",
                        last_checked=now,
                        status="ok",
                        details={
                            "image": image,
                            "container_name": container_name,
                            "container_id": container_id,
                        },
                    ))
        except Exception as exc:
            logger.debug("Docker scan failed: %s", exc)
            # Return a single entry indicating Docker is unavailable
            results.append(ComponentVersion(
                name="docker",
                category="docker",
                current_version="unknown",
                install_type="docker",
                last_checked=now,
                status="error",
                details={"error": str(exc)},
            ))

        return results

    async def _scan_system_packages(self) -> list[ComponentVersion]:
        """Scan system package versions.

        Checks installed versions of zeek, suricata, tshark, python3,
        and node by running their ``--version`` commands.
        """
        now = datetime.now(timezone.utc).isoformat()
        results: list[ComponentVersion] = []

        # Package -> (command, version_regex)
        packages: list[tuple[str, list[str], str]] = [
            ("zeek", ["zeek", "--version"], r"(\d+\.\d+(?:\.\d+)?)"),
            ("suricata", ["suricata", "--build-info"], r"Suricata\s+(\d+\.\d+(?:\.\d+)?)"),
            ("tshark", ["tshark", "--version"], r"TShark.*?(\d+\.\d+(?:\.\d+)?)"),
            ("python3", ["python3", "--version"], r"Python\s+(\d+\.\d+(?:\.\d+)?)"),
            ("node", ["node", "--version"], r"v?(\d+\.\d+(?:\.\d+)?)"),
            ("docker", ["docker", "--version"], r"(\d+\.\d+(?:\.\d+)?)"),
            ("docker-compose", ["docker", "compose", "version"], r"(\d+\.\d+(?:\.\d+)?)"),
        ]

        for pkg_name, cmd, version_re in packages:
            version = "unknown"
            status = "unknown"
            details: dict[str, Any] = {}

            try:
                output = await self._run_command(cmd)
                if output:
                    match = re.search(version_re, output)
                    if match:
                        version = match.group(1)
                        status = "ok"
                        details = {"raw_output": output.strip()[:200]}
                    else:
                        details = {"raw_output": output.strip()[:200]}
            except Exception as exc:
                status = "error"
                details = {"error": str(exc)}

            results.append(ComponentVersion(
                name=pkg_name,
                category="system",
                current_version=version,
                install_type="apt",
                last_checked=now,
                status=status,
                details=details,
            ))

        return results

    async def _scan_databases(self) -> list[ComponentVersion]:
        """Scan database and ruleset versions.

        Checks:
        - Suricata ruleset date (from suricata-update)
        - GeoIP database date (from mmdb file mtime)
        - OpenSearch version (from cluster info API)
        """
        now = datetime.now(timezone.utc).isoformat()
        results: list[ComponentVersion] = []

        # Suricata ruleset date
        rules_version = "unknown"
        rules_status = "unknown"
        rules_details: dict[str, Any] = {}

        try:
            output = await self._run_command([
                "suricata-update", "list-sources", "--free"
            ])
            if output:
                rules_version = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                rules_status = "ok"
                rules_details = {"source": "suricata-update"}
        except Exception:
            pass

        # Also try checking rule file mtime as fallback
        rule_paths = [
            "/var/lib/suricata/rules/suricata.rules",
            "/opt/nettap/config/suricata/rules/suricata.rules",
        ]
        for rule_path in rule_paths:
            try:
                if os.path.exists(rule_path):
                    mtime = os.path.getmtime(rule_path)
                    rules_version = datetime.fromtimestamp(
                        mtime, tz=timezone.utc
                    ).strftime("%Y-%m-%d")
                    rules_status = "ok"
                    rules_details = {"rule_file": rule_path}
                    break
            except OSError:
                continue

        results.append(ComponentVersion(
            name="suricata-rules",
            category="database",
            current_version=rules_version,
            install_type="builtin",
            last_checked=now,
            status=rules_status,
            details=rules_details,
        ))

        # GeoIP database date
        geoip_version = "unknown"
        geoip_status = "unknown"
        geoip_details: dict[str, Any] = {}

        geoip_paths = [
            os.environ.get("GEOIP_DB_PATH", "/opt/nettap/data/GeoLite2-City.mmdb"),
            "/usr/share/GeoIP/GeoLite2-City.mmdb",
            "/opt/nettap/data/GeoLite2-City.mmdb",
        ]

        for geoip_path in geoip_paths:
            try:
                if os.path.exists(geoip_path):
                    mtime = os.path.getmtime(geoip_path)
                    geoip_version = datetime.fromtimestamp(
                        mtime, tz=timezone.utc
                    ).strftime("%Y-%m-%d")
                    geoip_status = "ok"
                    geoip_details = {"db_file": geoip_path}
                    break
            except OSError:
                continue

        results.append(ComponentVersion(
            name="geoip-db",
            category="database",
            current_version=geoip_version,
            install_type="builtin",
            last_checked=now,
            status=geoip_status,
            details=geoip_details,
        ))

        # OpenSearch version (via API)
        os_version = "unknown"
        os_status = "unknown"
        os_details: dict[str, Any] = {}

        opensearch_url = os.environ.get(
            "OPENSEARCH_URL", "https://localhost:9200"
        )
        try:
            output = await self._run_command([
                "curl", "-sk", opensearch_url,
                "--connect-timeout", "5",
            ])
            if output:
                data = json.loads(output)
                os_version = data.get("version", {}).get("number", "unknown")
                os_status = "ok"
                os_details = {
                    "cluster_name": data.get("cluster_name", ""),
                    "distribution": data.get("version", {}).get(
                        "distribution", "opensearch"
                    ),
                }
        except (json.JSONDecodeError, Exception) as exc:
            os_details = {"error": str(exc)}

        results.append(ComponentVersion(
            name="opensearch",
            category="database",
            current_version=os_version,
            install_type="docker",
            last_checked=now,
            status=os_status,
            details=os_details,
        ))

        return results

    async def _scan_os_info(self) -> list[ComponentVersion]:
        """Scan operating system information.

        Reads Ubuntu version from /etc/os-release and kernel version
        from ``uname -r``.
        """
        now = datetime.now(timezone.utc).isoformat()
        results: list[ComponentVersion] = []

        # OS version from /etc/os-release
        os_version = "unknown"
        os_name = "unknown"
        os_status = "unknown"
        os_details: dict[str, Any] = {}

        try:
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release", "r") as f:
                    content = f.read()
                for line in content.strip().split("\n"):
                    if line.startswith("VERSION_ID="):
                        os_version = line.split("=", 1)[1].strip().strip('"')
                    elif line.startswith("PRETTY_NAME="):
                        os_name = line.split("=", 1)[1].strip().strip('"')
                os_status = "ok"
                os_details = {"pretty_name": os_name}
        except (OSError, PermissionError) as exc:
            os_details = {"error": str(exc)}

        results.append(ComponentVersion(
            name="os",
            category="os",
            current_version=os_version,
            install_type="builtin",
            last_checked=now,
            status=os_status,
            details=os_details,
        ))

        # Kernel version
        kernel_version = "unknown"
        kernel_status = "unknown"
        kernel_details: dict[str, Any] = {}

        try:
            output = await self._run_command(["uname", "-r"])
            if output:
                kernel_version = output.strip()
                kernel_status = "ok"
        except Exception as exc:
            kernel_details = {"error": str(exc)}

        results.append(ComponentVersion(
            name="kernel",
            category="os",
            current_version=kernel_version,
            install_type="builtin",
            last_checked=now,
            status=kernel_status,
            details=kernel_details,
        ))

        return results

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    async def _run_command(self, cmd: list[str]) -> str:
        """Run a subprocess command asynchronously and return stdout.

        Uses asyncio.create_subprocess_exec for safe argument passing
        (no shell injection). Each argument is passed directly to the
        executable without shell interpretation.

        Args:
            cmd: Command and arguments as a list.

        Returns:
            Decoded stdout string, or empty string on failure.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=15.0
            )
            return stdout.decode("utf-8", errors="replace")
        except FileNotFoundError:
            logger.debug("Command not found: %s", cmd[0])
            return ""
        except asyncio.TimeoutError:
            logger.debug("Command timed out: %s", " ".join(cmd))
            return ""
        except OSError as exc:
            logger.debug("Command failed: %s -- %s", " ".join(cmd), exc)
            return ""

    def _is_cache_stale(self) -> bool:
        """Check if the version cache needs refreshing."""
        if not self._versions or self._last_scan is None:
            return True

        try:
            last_scan_dt = datetime.fromisoformat(self._last_scan)
            now = datetime.now(timezone.utc)
            elapsed = (now - last_scan_dt).total_seconds()
            return elapsed > _CACHE_TTL_SECONDS
        except (ValueError, TypeError):
            return True
