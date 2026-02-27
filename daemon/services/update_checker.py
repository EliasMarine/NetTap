"""
NetTap Update Checker Service

Checks for available updates across all NetTap components by querying
Docker Hub, GitHub Releases API, and package repositories. Results are
cached and refreshed every 6 hours.
"""

import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

import aiohttp

logger = logging.getLogger("nettap.services.update_checker")


@dataclass
class AvailableUpdate:
    """Describes an available update for a NetTap component."""

    component: str  # Component name matching VersionManager
    current_version: str
    latest_version: str
    update_type: str  # "major", "minor", "patch", "unknown"
    release_url: str  # Link to release notes
    release_date: str  # ISO timestamp
    changelog: str  # Brief changelog/description
    size_mb: float  # Estimated download size
    requires_restart: bool  # Whether component restart is needed

    def to_dict(self) -> dict:
        return asdict(self)


class UpdateChecker:
    """Checks for available updates across all NetTap components.

    Queries GitHub Releases, Docker Hub tags, and local package managers
    to determine if newer versions are available. Results are cached
    with a configurable TTL (default 6 hours).
    """

    def __init__(
        self,
        github_repo: str = "EliasMarine/NetTap",
        cache_ttl_hours: int = 6,
    ) -> None:
        self._github_repo = github_repo
        self._cache_ttl = cache_ttl_hours * 3600
        self._available_updates: list[AvailableUpdate] = []
        self._last_check: str | None = None
        self._checking: bool = False
        self._version_manager = None  # Set externally after init

        logger.info(
            "UpdateChecker initialized: repo=%s cache_ttl=%dh",
            github_repo,
            cache_ttl_hours,
        )

    def set_version_manager(self, vm: Any) -> None:
        """Set reference to VersionManager for current version lookups."""
        self._version_manager = vm

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    async def check_updates(self) -> dict:
        """Check all sources for available updates.

        Queries GitHub Releases, Docker Hub, Suricata rules, and GeoIP
        database for available updates. Updates internal cache.

        Returns:
            Dict with "updates" (list of AvailableUpdate dicts),
            "last_check" (ISO timestamp), "count" (int), and
            "has_updates" (bool).
        """
        if self._checking:
            return await self.get_available()

        self._checking = True
        now = datetime.now(timezone.utc).isoformat()

        try:
            all_updates: list[AvailableUpdate] = []

            # Get current versions from VersionManager if available
            current_versions: dict[str, str] = {}
            if self._version_manager is not None:
                try:
                    versions_data = await self._version_manager.get_versions()
                    for v in versions_data.get("versions", []):
                        current_versions[v["name"]] = v["current_version"]
                except Exception as exc:
                    logger.debug("Could not get current versions: %s", exc)

            # Check GitHub releases for NetTap core updates
            github_updates = await self._check_github_releases()
            all_updates.extend(github_updates)

            # Check Docker Hub for image updates
            docker_updates = await self._check_docker_updates(current_versions)
            all_updates.extend(docker_updates)

            # Check Suricata rule updates
            rules_update = await self._check_suricata_rules()
            if rules_update is not None:
                all_updates.append(rules_update)

            # Check GeoIP database updates
            geoip_update = await self._check_geoip_update()
            if geoip_update is not None:
                all_updates.append(geoip_update)

            self._available_updates = all_updates
            self._last_check = now

            logger.info(
                "Update check complete: %d updates available",
                len(all_updates),
            )

            return {
                "updates": [u.to_dict() for u in all_updates],
                "last_check": self._last_check,
                "count": len(all_updates),
                "has_updates": len(all_updates) > 0,
            }
        finally:
            self._checking = False

    async def get_available(self) -> dict:
        """Return cached available updates.

        Returns:
            Dict with "updates" (list), "last_check" (ISO timestamp),
            "count" (int), and "has_updates" (bool).
        """
        return {
            "updates": [u.to_dict() for u in self._available_updates],
            "last_check": self._last_check,
            "count": len(self._available_updates),
            "has_updates": len(self._available_updates) > 0,
        }

    async def get_update_for(self, component: str) -> dict | None:
        """Get update info for a specific component.

        Args:
            component: Component name (e.g. "nettap-daemon", "zeek").

        Returns:
            Dict with update info, or None if no update available.
        """
        for update in self._available_updates:
            if update.component == component:
                return update.to_dict()
        return None

    # -------------------------------------------------------------------
    # Internal check methods
    # -------------------------------------------------------------------

    async def _check_github_releases(self) -> list[AvailableUpdate]:
        """Check GitHub Releases API for NetTap updates.

        Fetches the latest release from the configured GitHub repository
        and compares against the current daemon version.

        Returns:
            List of AvailableUpdate (0 or 1 items).
        """
        results: list[AvailableUpdate] = []
        url = f"https://api.github.com/repos/{self._github_repo}/releases/latest"

        try:
            data = await self._fetch_json(url)
            if not data or "tag_name" not in data:
                return results

            latest_tag = data["tag_name"]
            # Strip leading 'v' for version comparison
            latest_version = latest_tag.lstrip("v")

            # Get current version from VersionManager or fallback
            from services.version_manager import NETTAP_VERSION

            current = NETTAP_VERSION

            update_type = await self._compare_versions(current, latest_version)
            if update_type == "same":
                return results

            results.append(
                AvailableUpdate(
                    component="nettap-daemon",
                    current_version=current,
                    latest_version=latest_version,
                    update_type=update_type,
                    release_url=data.get("html_url", ""),
                    release_date=data.get("published_at", ""),
                    changelog=data.get("body", "")[:500],
                    size_mb=self._estimate_release_size(data),
                    requires_restart=True,
                )
            )
        except Exception as exc:
            logger.debug("GitHub release check failed: %s", exc)

        return results

    async def _check_docker_updates(
        self, current_versions: dict[str, str]
    ) -> list[AvailableUpdate]:
        """Check Docker Hub for newer image tags.

        For each Docker component in current_versions, checks if a
        newer tag is available on Docker Hub.

        Args:
            current_versions: Dict mapping component names to current
                version strings.

        Returns:
            List of AvailableUpdate for components with newer images.
        """
        results: list[AvailableUpdate] = []

        # Malcolm Docker Hub namespace
        docker_images: dict[str, str] = {
            "zeek": "malcolm/zeek",
            "suricata": "malcolm/suricata",
            "arkime": "malcolm/arkime",
            "opensearch": "opensearchproject/opensearch",
            "dashboards": "opensearchproject/opensearch-dashboards",
            "logstash": "malcolm/logstash-oss",
            "file-monitor": "malcolm/file-monitor",
            "pcap-capture": "malcolm/pcap-capture",
        }

        for component, image_name in docker_images.items():
            current = current_versions.get(component)
            if not current or current in ("unknown", "latest"):
                continue

            # Query Docker Hub API for tags
            hub_url = (
                f"https://hub.docker.com/v2/repositories/{image_name}"
                f"/tags/?page_size=5&ordering=last_updated"
            )

            try:
                data = await self._fetch_json(hub_url)
                if not data or "results" not in data:
                    continue

                for tag_info in data["results"]:
                    tag_name = tag_info.get("name", "")
                    if tag_name in ("latest", ""):
                        continue

                    latest_version = tag_name.lstrip("v")
                    current_clean = current.lstrip("v")
                    update_type = await self._compare_versions(
                        current_clean, latest_version
                    )

                    if update_type != "same" and update_type != "unknown":
                        # Estimate size from compressed image layers
                        total_size = tag_info.get("full_size", 0) or 0
                        size_mb = round(total_size / (1024 * 1024), 1)

                        results.append(
                            AvailableUpdate(
                                component=component,
                                current_version=current,
                                latest_version=tag_name,
                                update_type=update_type,
                                release_url=(
                                    f"https://hub.docker.com/r/{image_name}/tags"
                                ),
                                release_date=tag_info.get("last_updated", ""),
                                changelog=f"Docker image {image_name} updated",
                                size_mb=size_mb,
                                requires_restart=True,
                            )
                        )
                        break  # Only report the latest newer tag
            except Exception as exc:
                logger.debug("Docker Hub check failed for %s: %s", component, exc)

        return results

    async def _check_suricata_rules(self) -> AvailableUpdate | None:
        """Check if Suricata ruleset has updates available.

        Compares local rule file mtime against current date to suggest
        daily rule updates.

        Returns:
            AvailableUpdate if rules are stale, None otherwise.
        """
        import os

        rule_paths = [
            "/var/lib/suricata/rules/suricata.rules",
            "/opt/nettap/config/suricata/rules/suricata.rules",
        ]

        for rule_path in rule_paths:
            try:
                if not os.path.exists(rule_path):
                    continue

                mtime = os.path.getmtime(rule_path)
                rule_date = datetime.fromtimestamp(mtime, tz=timezone.utc)
                now = datetime.now(timezone.utc)
                age_days = (now - rule_date).days

                if age_days >= 1:
                    return AvailableUpdate(
                        component="suricata-rules",
                        current_version=rule_date.strftime("%Y-%m-%d"),
                        latest_version=now.strftime("%Y-%m-%d"),
                        update_type="patch",
                        release_url="https://rules.emergingthreats.net/",
                        release_date=now.isoformat(),
                        changelog=f"Suricata rules are {age_days} day(s) old",
                        size_mb=15.0,  # Approximate ET ruleset size
                        requires_restart=True,
                    )
                return None
            except OSError:
                continue

        return None

    async def _check_geoip_update(self) -> AvailableUpdate | None:
        """Check if GeoIP database needs updating.

        MaxMind GeoLite2 databases are updated weekly. If the local
        database is older than 7 days, suggest an update.

        Returns:
            AvailableUpdate if database is stale, None otherwise.
        """
        import os

        geoip_paths = [
            os.environ.get("GEOIP_DB_PATH", "/opt/nettap/data/GeoLite2-City.mmdb"),
            "/usr/share/GeoIP/GeoLite2-City.mmdb",
            "/opt/nettap/data/GeoLite2-City.mmdb",
        ]

        for geoip_path in geoip_paths:
            try:
                if not os.path.exists(geoip_path):
                    continue

                mtime = os.path.getmtime(geoip_path)
                db_date = datetime.fromtimestamp(mtime, tz=timezone.utc)
                now = datetime.now(timezone.utc)
                age_days = (now - db_date).days

                if age_days >= 7:
                    return AvailableUpdate(
                        component="geoip-db",
                        current_version=db_date.strftime("%Y-%m-%d"),
                        latest_version=now.strftime("%Y-%m-%d"),
                        update_type="patch",
                        release_url="https://dev.maxmind.com/geoip/updating-databases",
                        release_date=now.isoformat(),
                        changelog=f"GeoIP database is {age_days} day(s) old",
                        size_mb=65.0,  # Approximate GeoLite2-City size
                        requires_restart=False,
                    )
                return None
            except OSError:
                continue

        return None

    async def _compare_versions(self, current: str, latest: str) -> str:
        """Compare two semver-style version strings.

        Args:
            current: Current version string (e.g. "1.2.3").
            latest: Latest version string (e.g. "1.3.0").

        Returns:
            "major", "minor", "patch", "same", or "unknown" if parsing
            fails.
        """
        try:
            curr_parts = self._parse_version(current)
            latest_parts = self._parse_version(latest)

            if curr_parts is None or latest_parts is None:
                return "unknown"

            curr_major, curr_minor, curr_patch = curr_parts
            lat_major, lat_minor, lat_patch = latest_parts

            if lat_major > curr_major:
                return "major"
            elif lat_major == curr_major and lat_minor > curr_minor:
                return "minor"
            elif (
                lat_major == curr_major
                and lat_minor == curr_minor
                and lat_patch > curr_patch
            ):
                return "patch"
            elif curr_parts == latest_parts:
                return "same"
            else:
                # Current is newer than latest (shouldn't happen normally)
                return "same"
        except Exception:
            return "unknown"

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    async def _fetch_json(self, url: str) -> dict:
        """Fetch JSON from a URL using aiohttp.

        Args:
            url: The URL to fetch.

        Returns:
            Parsed JSON as a dict, or empty dict on failure.
        """
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    url,
                    headers={"Accept": "application/json"},
                    ssl=False,
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        logger.debug("HTTP %d from %s", resp.status, url)
                        return {}
        except aiohttp.ClientError as exc:
            logger.debug("HTTP request failed for %s: %s", url, exc)
            return {}
        except Exception as exc:
            logger.debug("Unexpected error fetching %s: %s", url, exc)
            return {}

    @staticmethod
    def _parse_version(version_str: str) -> tuple[int, int, int] | None:
        """Parse a semver-style version string into (major, minor, patch).

        Handles versions like "1.2.3", "1.2", "v1.2.3", "26.02.0".

        Returns:
            Tuple of (major, minor, patch), or None if parsing fails.
        """
        # Strip leading 'v' and any pre-release suffix
        cleaned = version_str.strip().lstrip("v")
        cleaned = re.split(r"[-+]", cleaned)[0]

        parts = cleaned.split(".")
        try:
            major = int(parts[0]) if len(parts) > 0 else 0
            minor = int(parts[1]) if len(parts) > 1 else 0
            patch = int(parts[2]) if len(parts) > 2 else 0
            return (major, minor, patch)
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _estimate_release_size(release_data: dict) -> float:
        """Estimate release download size in MB from GitHub release data.

        Sums up asset sizes if available, otherwise returns a default.
        """
        total = 0
        for asset in release_data.get("assets", []):
            total += asset.get("size", 0)

        if total > 0:
            return round(total / (1024 * 1024), 1)

        # Default estimate for NetTap release
        return 50.0
