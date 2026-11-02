"""
NetTap Update Executor Service

Performs software updates with rollback capability. Handles Docker
image pulls, Suricata rule updates, GeoIP database downloads, and
system package updates. Creates pre-update snapshots for safety.
"""

import asyncio
import json
import logging
import os
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("nettap.services.update_executor")

# Malcolm's containers, by the names VersionManager gives them. NetTap pins their images
# to a tested release, and a pull from here could never work anyway: these names aren't
# the compose services and the compose file isn't inside the daemon container.
_MALCOLM_COMPONENTS = frozenset(
    {
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
    }
)
PINNED_REASON = (
    "NetTap pins Malcolm's container images to a tested release, so they can't be "
    "updated from here: update NetTap to get a newer Malcolm."
)


@dataclass
class UpdateResult:
    """Result of a single component update operation."""

    component: str
    success: bool
    old_version: str
    new_version: str
    started_at: str
    completed_at: str
    error: str | None
    rollback_available: bool

    def to_dict(self) -> dict:
        return asdict(self)


class UpdateExecutor:
    """Performs software updates with rollback capability.

    Handles Docker image pulls, Suricata rule updates, GeoIP database
    downloads, and system package updates. Creates pre-update backups
    for rollback safety.
    """

    def __init__(
        self,
        compose_file: str = "/opt/nettap/docker/docker-compose.yml",
        backup_dir: str = "/opt/nettap/backups",
    ) -> None:
        self._compose_file = compose_file
        self._backup_dir = backup_dir
        self._current_update: dict | None = None  # tracks in-progress update
        self._update_history: list[dict] = []
        self._max_history = 50
        self._version_manager = None  # Set externally after init
        self._update_checker = None  # Set externally after init

        logger.info(
            "UpdateExecutor initialized: compose_file=%s backup_dir=%s",
            compose_file,
            backup_dir,
        )

    def set_version_manager(self, vm: Any) -> None:
        """Set reference to VersionManager for current version lookups."""
        self._version_manager = vm

    def set_update_checker(self, uc: Any) -> None:
        """Set reference to UpdateChecker for available update lookups."""
        self._update_checker = uc

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    async def apply_update(self, components: list[str]) -> dict:
        """Apply updates to specified components.

        Creates pre-update backups, then applies updates one component
        at a time. If any update fails, the component is rolled back
        automatically.

        Args:
            components: List of component names to update.

        Returns:
            Dict with "results" (list of UpdateResult dicts),
            "success" (bool, True if all updates succeeded),
            "total" (int), "succeeded" (int), "failed" (int).
        """
        if self._current_update is not None:
            return {
                "error": "An update is already in progress",
                "current_update": self._current_update,
                "results": [],
                "success": False,
                "total": 0,
                "succeeded": 0,
                "failed": 0,
            }

        if not components:
            return {
                "results": [],
                "success": True,
                "total": 0,
                "succeeded": 0,
                "failed": 0,
                "message": "No components specified for update",
            }

        now = datetime.now(timezone.utc).isoformat()
        self._current_update = {
            "started_at": now,
            "components": components,
            "status": "in_progress",
        }

        results: list[UpdateResult] = []

        try:
            # Categorize components by update type
            # OLD CODE START — Malcolm's images are pinned: the pull below could never
            # work (wrong service names, no compose file in the container)
            # docker_components = []
            # OLD CODE END
            rule_components = []
            geoip_components = []
            other_components = []

            for comp in components:
                # OLD CODE START — Malcolm's images are pinned (see PINNED_REASON)
                # if comp in (
                #     "zeek",
                #     "suricata",
                #     "arkime",
                #     "opensearch",
                #     "dashboards",
                #     "logstash",
                #     "file-monitor",
                #     "pcap-capture",
                #     "freq",
                #     "htadmin",
                #     "nginx-proxy",
                # ):
                #     docker_components.append(comp)
                # elif comp == "suricata-rules":
                # OLD CODE END
                reason = await self._not_applicable_reason(comp)
                if reason:
                    results.append(
                        UpdateResult(
                            component=comp,
                            success=False,
                            old_version="unknown",
                            new_version="unknown",
                            started_at=now,
                            completed_at=datetime.now(timezone.utc).isoformat(),
                            error=reason,
                            rollback_available=False,
                        )
                    )
                elif comp == "suricata-rules":
                    rule_components.append(comp)
                elif comp == "geoip-db":
                    geoip_components.append(comp)
                else:
                    other_components.append(comp)

            # Apply updates by category
            # OLD CODE START — Malcolm's images are pinned (see PINNED_REASON)
            # if docker_components:
            #     docker_results = await self._update_docker_images(docker_components)
            #     results.extend(docker_results)
            # OLD CODE END

            if rule_components:
                rule_result = await self._update_suricata_rules()
                results.append(rule_result)

            if geoip_components:
                geoip_result = await self._update_geoip()
                results.append(geoip_result)

            # Handle unsupported components
            for comp in other_components:
                results.append(
                    UpdateResult(
                        component=comp,
                        success=False,
                        old_version="unknown",
                        new_version="unknown",
                        started_at=now,
                        completed_at=datetime.now(timezone.utc).isoformat(),
                        error=f"Unsupported component for update: {comp}",
                        rollback_available=False,
                    )
                )

            # Build summary
            succeeded = sum(1 for r in results if r.success)
            failed = sum(1 for r in results if not r.success)

            result_dict = {
                "results": [r.to_dict() for r in results],
                "success": failed == 0,
                "total": len(results),
                "succeeded": succeeded,
                "failed": failed,
            }

            # Store in history
            history_entry = {
                **result_dict,
                "started_at": now,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
            self._update_history.append(history_entry)

            # Trim history if needed
            if len(self._update_history) > self._max_history:
                self._update_history = self._update_history[-self._max_history :]

            logger.info(
                "Update batch complete: %d succeeded, %d failed",
                succeeded,
                failed,
            )

            return result_dict

        finally:
            self._current_update = None

    async def get_status(self) -> dict:
        """Get current update status.

        Returns:
            Dict with "status" ("idle" | "in_progress"), "current_update"
            (dict | None), and "last_completed" (dict | None from history).
        """
        last_completed = None
        if self._update_history:
            last_completed = self._update_history[-1]

        if self._current_update is not None:
            return {
                "status": "in_progress",
                "current_update": self._current_update,
                "last_completed": last_completed,
            }

        return {
            "status": "idle",
            "current_update": None,
            "last_completed": last_completed,
        }

    async def get_history(self) -> list[dict]:
        """Get update execution history.

        Returns:
            List of past update result dicts, newest first.
        """
        return list(reversed(self._update_history))

    async def rollback(self, component: str) -> dict:
        """Rollback a component to its pre-update state.

        Checks for a backup of the specified component and restores it.

        Args:
            component: Component name to rollback.

        Returns:
            Dict with "success" (bool), "component" (str), and
            "message" (str).
        """
        if component in _MALCOLM_COMPONENTS:  # nothing was pulled, so nothing to restore
            return {"success": False, "component": component, "message": PINNED_REASON}

        backup_path = os.path.join(self._backup_dir, component)

        if not os.path.exists(backup_path):
            return {
                "success": False,
                "component": component,
                "message": f"No backup available for component: {component}",
            }

        try:
            # Rollback strategy depends on component type
            # OLD CODE START — Malcolm's images are pinned (answered above), and
            # _rollback_docker never used the saved image ID, so it restored nothing
            # if component in (
            #     "zeek",
            #     "suricata",
            #     "arkime",
            #     "opensearch",
            #     "dashboards",
            #     "logstash",
            #     "file-monitor",
            #     "pcap-capture",
            # ):
            #     result = await self._rollback_docker(component, backup_path)
            # elif component == "suricata-rules":
            # OLD CODE END
            if component == "suricata-rules":
                result = await self._rollback_files(
                    component, backup_path, "/var/lib/suricata/rules/suricata.rules"
                )
            elif component == "geoip-db":
                geoip_path = os.environ.get(
                    "GEOIP_DB_PATH", "/opt/nettap/data/GeoLite2-City.mmdb"
                )
                result = await self._rollback_files(component, backup_path, geoip_path)
            else:
                return {
                    "success": False,
                    "component": component,
                    "message": f"Rollback not supported for: {component}",
                }

            logger.info("Rollback completed for %s: %s", component, result)
            return result
        except Exception as exc:
            logger.exception("Rollback failed for %s", component)
            return {
                "success": False,
                "component": component,
                "message": f"Rollback failed: {exc}",
            }

    # -------------------------------------------------------------------
    # Internal update methods
    # -------------------------------------------------------------------

    async def _not_applicable_reason(self, component: str) -> str | None:
        """Why NetTap can't apply this component's update itself, or None if it can.

        Malcolm's containers are pinned; anything else the update checker listed with
        applies_with (e.g. Logstash's bundled GeoIP database) arrives the same way.
        """
        if component in _MALCOLM_COMPONENTS:
            return PINNED_REASON
        if self._update_checker is None:
            return None
        update = await self._update_checker.get_update_for(component)
        return (update or {}).get("applies_with")

    # Unreachable while Malcolm's images are pinned (apply_update answers PINNED_REASON)
    async def _update_docker_images(self, components: list[str]) -> list[UpdateResult]:
        """Update Docker images for specified components.

        For each component, pulls the latest image tag and restarts
        the container via docker compose.

        Args:
            components: List of Docker component names to update.

        Returns:
            List of UpdateResult for each component.
        """
        results: list[UpdateResult] = []

        for component in components:
            started = datetime.now(timezone.utc).isoformat()
            old_version = "unknown"
            new_version = "unknown"

            try:
                # Get current version
                if self._version_manager:
                    comp_info = await self._version_manager.get_component(component)
                    if comp_info:
                        old_version = comp_info.get("current_version", "unknown")

                # Create backup (save current image ID)
                # OLD CODE START — #96: the result was ignored and rollback_available
                # was always True below
                # await self._create_backup(component)
                # OLD CODE END
                backup_ok = self._has_restorable_backup(
                    await self._create_backup(component)
                )

                # Pull latest image via docker compose
                output, returncode = await self._run_command(
                    [
                        "docker",
                        "compose",
                        "-f",
                        self._compose_file,
                        "pull",
                        component,
                    ]
                )

                if returncode != 0:
                    results.append(
                        UpdateResult(
                            component=component,
                            success=False,
                            old_version=old_version,
                            new_version=old_version,
                            started_at=started,
                            completed_at=datetime.now(timezone.utc).isoformat(),
                            error=f"Docker pull failed: {output}",
                            rollback_available=backup_ok,  # was True (#96)
                        )
                    )
                    continue

                # Restart the container with the new image
                output, returncode = await self._run_command(
                    [
                        "docker",
                        "compose",
                        "-f",
                        self._compose_file,
                        "up",
                        "-d",
                        "--no-deps",
                        component,
                    ]
                )

                if returncode != 0:
                    results.append(
                        UpdateResult(
                            component=component,
                            success=False,
                            old_version=old_version,
                            new_version=old_version,
                            started_at=started,
                            completed_at=datetime.now(timezone.utc).isoformat(),
                            error=f"Container restart failed: {output}",
                            rollback_available=backup_ok,  # was True (#96)
                        )
                    )
                    continue

                # Get new version after update
                if self._version_manager:
                    # Force rescan for this component
                    await self._version_manager.scan_versions()
                    comp_info = await self._version_manager.get_component(component)
                    if comp_info:
                        new_version = comp_info.get("current_version", "unknown")

                results.append(
                    UpdateResult(
                        component=component,
                        success=True,
                        old_version=old_version,
                        new_version=new_version,
                        started_at=started,
                        completed_at=datetime.now(timezone.utc).isoformat(),
                        error=None,
                        rollback_available=backup_ok,  # was True (#96)
                    )
                )

            except Exception as exc:
                logger.exception("Failed to update Docker image: %s", component)
                results.append(
                    UpdateResult(
                        component=component,
                        success=False,
                        old_version=old_version,
                        new_version=old_version,
                        started_at=started,
                        completed_at=datetime.now(timezone.utc).isoformat(),
                        error=str(exc),
                        rollback_available=False,
                    )
                )

        return results

    async def _update_suricata_rules(self) -> UpdateResult:
        """Update Suricata IDS rules via suricata-update.

        Returns:
            UpdateResult for the suricata-rules component.
        """
        started = datetime.now(timezone.utc).isoformat()
        old_version = "unknown"

        try:
            # Get current rule date
            rule_paths = [
                "/var/lib/suricata/rules/suricata.rules",
                "/opt/nettap/config/suricata/rules/suricata.rules",
            ]
            for rule_path in rule_paths:
                try:
                    if os.path.exists(rule_path):
                        mtime = os.path.getmtime(rule_path)
                        old_version = datetime.fromtimestamp(
                            mtime, tz=timezone.utc
                        ).strftime("%Y-%m-%d")
                        break
                except OSError:
                    continue

            # Create backup
            # OLD CODE START — #96: rollback_available was True even with no backup
            # await self._create_backup("suricata-rules")
            # OLD CODE END
            backup_ok = self._has_restorable_backup(
                await self._create_backup("suricata-rules")
            )

            # Run suricata-update
            output, returncode = await self._run_command(
                [
                    "suricata-update",
                    "update",
                ]
            )

            if returncode != 0:
                return UpdateResult(
                    component="suricata-rules",
                    success=False,
                    old_version=old_version,
                    new_version=old_version,
                    started_at=started,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    error=f"suricata-update failed: {output}",
                    rollback_available=backup_ok,  # was True (#96)
                )

            new_version = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # Reload Suricata rules (best effort)
            await self._run_command(
                [
                    "suricatasc",
                    "-c",
                    "reload-rules",
                ]
            )

            return UpdateResult(
                component="suricata-rules",
                success=True,
                old_version=old_version,
                new_version=new_version,
                started_at=started,
                completed_at=datetime.now(timezone.utc).isoformat(),
                error=None,
                rollback_available=backup_ok,  # was True (#96)
            )

        except Exception as exc:
            logger.exception("Failed to update Suricata rules")
            return UpdateResult(
                component="suricata-rules",
                success=False,
                old_version=old_version,
                new_version=old_version,
                started_at=started,
                completed_at=datetime.now(timezone.utc).isoformat(),
                error=str(exc),
                rollback_available=False,
            )

    async def _update_geoip(self) -> UpdateResult:
        """Update GeoIP database.

        Downloads the latest GeoLite2-City database from MaxMind
        using the geoipupdate tool.

        Returns:
            UpdateResult for the geoip-db component.
        """
        started = datetime.now(timezone.utc).isoformat()
        old_version = "unknown"

        geoip_path = os.environ.get(
            "GEOIP_DB_PATH", "/opt/nettap/data/GeoLite2-City.mmdb"
        )

        try:
            # Get current database date
            if os.path.exists(geoip_path):
                mtime = os.path.getmtime(geoip_path)
                old_version = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime(
                    "%Y-%m-%d"
                )

            # Create backup
            # OLD CODE START — #96: rollback_available was True even with no backup
            # await self._create_backup("geoip-db")
            # OLD CODE END
            backup_ok = self._has_restorable_backup(
                await self._create_backup("geoip-db")
            )

            # Run geoipupdate tool
            output, returncode = await self._run_command(
                [
                    "geoipupdate",
                    "-v",
                ]
            )

            if returncode != 0:
                return UpdateResult(
                    component="geoip-db",
                    success=False,
                    old_version=old_version,
                    new_version=old_version,
                    started_at=started,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    error=f"geoipupdate failed: {output}",
                    rollback_available=backup_ok,  # was True (#96)
                )

            new_version = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            return UpdateResult(
                component="geoip-db",
                success=True,
                old_version=old_version,
                new_version=new_version,
                started_at=started,
                completed_at=datetime.now(timezone.utc).isoformat(),
                error=None,
                rollback_available=backup_ok,  # was True (#96)
            )

        except Exception as exc:
            logger.exception("Failed to update GeoIP database")
            return UpdateResult(
                component="geoip-db",
                success=False,
                old_version=old_version,
                new_version=old_version,
                started_at=started,
                completed_at=datetime.now(timezone.utc).isoformat(),
                error=str(exc),
                rollback_available=False,
            )

    async def _create_backup(self, component: str) -> str:
        """Create a pre-update backup for a component.

        Creates a timestamped backup directory for the given component
        and copies relevant files or metadata.

        Args:
            component: Component name to back up.

        Returns:
            Path to the backup directory.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(self._backup_dir, component, timestamp)

        try:
            os.makedirs(backup_path, exist_ok=True)

            # Save component metadata
            metadata = {
                "component": component,
                "backup_time": datetime.now(timezone.utc).isoformat(),
                "type": "pre_update",
            }

            metadata_file = os.path.join(backup_path, "metadata.json")
            with open(metadata_file, "w") as f:
                json.dump(metadata, f, indent=2)

            # Backup component-specific files
            if component == "suricata-rules":
                rule_paths = [
                    "/var/lib/suricata/rules/suricata.rules",
                    "/opt/nettap/config/suricata/rules/suricata.rules",
                ]
                for rule_path in rule_paths:
                    if os.path.exists(rule_path):
                        dest = os.path.join(backup_path, os.path.basename(rule_path))
                        shutil.copy2(rule_path, dest)
                        break

            elif component == "geoip-db":
                geoip_path = os.environ.get(
                    "GEOIP_DB_PATH", "/opt/nettap/data/GeoLite2-City.mmdb"
                )
                if os.path.exists(geoip_path):
                    dest = os.path.join(backup_path, os.path.basename(geoip_path))
                    shutil.copy2(geoip_path, dest)

            elif component in (
                "zeek",
                "suricata",
                "arkime",
                "opensearch",
                "dashboards",
                "logstash",
            ):
                # For Docker components, save the current image ID
                # Uses create_subprocess_exec for safe argument passing
                # OLD CODE START — #96: docker's error text was saved as the image ID
                # output, _ = await self._run_command(
                # ...
                # if output:
                # OLD CODE END
                output, returncode = await self._run_command(
                    [
                        "docker",
                        "inspect",
                        "--format",
                        "{{.Image}}",
                        component,
                    ]
                )
                if returncode == 0 and output.strip():
                    image_file = os.path.join(backup_path, "image_id.txt")
                    with open(image_file, "w") as f:
                        f.write(output.strip())

            logger.info("Backup created for %s at %s", component, backup_path)
            return backup_path

        except OSError as exc:
            logger.warning("Could not create backup for %s: %s", component, exc)
            # #96: a half-copied file must not be what a rollback restores
            shutil.rmtree(backup_path, ignore_errors=True)
            return backup_path

    @staticmethod
    def _has_restorable_backup(backup_path: str) -> bool:
        """True when the backup holds what a rollback restores (image ID, rules or
        GeoIP file), not just its metadata (#96)."""
        try:
            return any(name != "metadata.json" for name in os.listdir(backup_path))
        except OSError:
            return False

    async def _run_command(self, cmd: list[str]) -> tuple[str, int]:
        """Run a subprocess command and return (output, returncode).

        Uses asyncio.create_subprocess_exec for safe argument passing
        (no shell injection). Each argument is passed directly to the
        executable without shell interpretation.

        Args:
            cmd: Command and arguments as a list.

        Returns:
            Tuple of (combined stdout+stderr output, return code).
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=300.0,  # 5 minute timeout for updates
            )
            output = stdout.decode("utf-8", errors="replace")
            if stderr:
                output += "\n" + stderr.decode("utf-8", errors="replace")
            return (output, proc.returncode or 0)
        except FileNotFoundError:
            logger.debug("Command not found: %s", cmd[0])
            return (f"Command not found: {cmd[0]}", 127)
        except asyncio.TimeoutError:
            logger.warning("Command timed out: %s", " ".join(cmd))
            return ("Command timed out", 124)
        except OSError as exc:
            logger.debug("Command failed: %s -- %s", " ".join(cmd), exc)
            return (str(exc), 1)

    # -------------------------------------------------------------------
    # Rollback helpers
    # -------------------------------------------------------------------

    # Unreachable while Malcolm's images are pinned; it also never used the saved image ID
    async def _rollback_docker(self, component: str, backup_path: str) -> dict:
        """Rollback a Docker component to its backed-up image.

        Args:
            component: Component name.
            backup_path: Path to the backup directory.

        Returns:
            Dict with rollback result.
        """
        # Find the most recent backup with an image ID
        image_id = None
        try:
            # List backup timestamps (subdirectories)
            if os.path.isdir(backup_path):
                timestamps = sorted(os.listdir(backup_path), reverse=True)
                for ts_dir in timestamps:
                    image_file = os.path.join(backup_path, ts_dir, "image_id.txt")
                    if os.path.exists(image_file):
                        with open(image_file, "r") as f:
                            image_id = f.read().strip()
                        break
        except OSError:
            pass

        if not image_id:
            return {
                "success": False,
                "component": component,
                "message": "No backed-up image ID found",
            }

        # Restart the container with the backed-up image
        output, returncode = await self._run_command(
            [
                "docker",
                "compose",
                "-f",
                self._compose_file,
                "up",
                "-d",
                "--no-deps",
                component,
            ]
        )

        return {
            "success": returncode == 0,
            "component": component,
            "message": (
                f"Rolled back {component} to image {image_id[:12]}"
                if returncode == 0
                else f"Rollback failed: {output}"
            ),
        }

    async def _rollback_files(
        self, component: str, backup_path: str, target_path: str
    ) -> dict:
        """Rollback a file-based component from backup.

        Args:
            component: Component name.
            backup_path: Path to the backup directory.
            target_path: Path to restore the file to.

        Returns:
            Dict with rollback result.
        """
        try:
            # Find the most recent backup
            if os.path.isdir(backup_path):
                timestamps = sorted(os.listdir(backup_path), reverse=True)
                for ts_dir in timestamps:
                    ts_path = os.path.join(backup_path, ts_dir)
                    if not os.path.isdir(ts_path):
                        continue
                    # Find the backed-up file
                    target_name = os.path.basename(target_path)
                    backup_file = os.path.join(ts_path, target_name)
                    if os.path.exists(backup_file):
                        shutil.copy2(backup_file, target_path)
                        return {
                            "success": True,
                            "component": component,
                            "message": (f"Restored {target_path} from backup {ts_dir}"),
                        }

            return {
                "success": False,
                "component": component,
                "message": "No backup file found to restore",
            }
        except OSError as exc:
            return {
                "success": False,
                "component": component,
                "message": f"File restore failed: {exc}",
            }
