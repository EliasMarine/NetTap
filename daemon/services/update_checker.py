"""
NetTap Update Checker Service

Checks for available updates across all NetTap components by querying
Docker Hub, GitHub Releases API, and package repositories. Results are
cached and refreshed every 6 hours.
"""

import asyncio
import logging
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

import aiohttp

from services.suricata_rules import SuricataRuleManager

logger = logging.getLogger("nettap.services.update_checker")

# Where the deployed images come from (docker/docker-compose.yml)
_MALCOLM_REGISTRY = "ghcr.io/idaholab/malcolm/"
_MALCOLM_RELEASE_URL = "https://api.github.com/repos/idaholab/Malcolm/releases/latest"
_NETTAP_IMAGE_PREFIX = "nettap/"  # built by NetTap; the NetTap release check covers them
# NetTap pins Malcolm's images to a tested release, so it can't apply a newer one itself
MALCOLM_APPLIES_WITH = "Comes with NetTap's pinned Malcolm release: update NetTap to get it."

# With no local database, enrichment uses the one bundled in Malcolm's Logstash image
_LOGSTASH_CONTAINER = os.environ.get("LOGSTASH_CONTAINER_NAME", "nettap-logstash")
_LOGSTASH_GEOIP_DB = (  # the jruby and gem versions vary between images
    "/usr/share/logstash/vendor/bundle/jruby/*/gems/logstash-filter-geoip-*"
    "/vendor/GeoLite2-City.mmdb"
)
_LOGSTASH_GEOIP_APPLIES_WITH = (
    "Comes with Malcolm's Logstash image: update NetTap to get a newer one."
)
# the update executor has no way to replace the running daemon and web containers
NETTAP_APPLIES_WITH = (
    "NetTap can't replace itself from this page: get the new release and rerun its install script."
)


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
    size_mb: float | None  # Download size in MB; None = not known
    requires_restart: bool  # Whether component restart is needed
    # Set when NetTap can't apply this update itself: one sentence on how it does arrive
    applies_with: str | None = None

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
        # Components the last check could not ask about (#96): unknown, not "up to date"
        self._failed_checks: list[str] = []
        # components the last check looked at; anything else has no update source here
        self._checked: list[str] = []
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
            "last_check" (ISO timestamp), "count" (int),
            "has_updates" (bool) and "failed_checks" (components that
            could not be checked, so their update state is unknown).
        """
        if self._checking:
            return await self.get_available()

        self._checking = True
        now = datetime.now(timezone.utc).isoformat()
        self._failed_checks = []

        try:
            all_updates: list[AvailableUpdate] = []

            # Get current versions from VersionManager if available
            current_versions: dict[str, str] = {}
            images: dict[str, str] = {}  # running container -> image reference
            if self._version_manager is not None:
                try:
                    versions_data = await self._version_manager.get_versions()
                    for v in versions_data.get("versions", []):
                        current_versions[v["name"]] = v["current_version"]
                        if v.get("category") != "docker":
                            continue
                        if v.get("status") == "ok":
                            images[v["name"]] = (v.get("details") or {}).get("image", "")
                        else:  # docker couldn't be asked: container updates unknown
                            self._failed_checks.append(v["name"])
                except Exception as exc:
                    # OLD CODE START — #96: the container checks were skipped unseen
                    # logger.debug("Could not get current versions: %s", exc)
                    # OLD CODE END
                    logger.warning("Could not get current versions: %s", exc)
                    self._failed_checks.append("component-versions")

            # Check GitHub releases for NetTap core updates
            # OLD CODE START — #96: a failed GitHub request read as "no NetTap update"
            # github_updates = await self._check_github_releases()
            # all_updates.extend(github_updates)
            # OLD CODE END
            try:
                all_updates.extend(await self._check_github_releases())
            except Exception as exc:
                logger.warning("GitHub release check failed: %s", exc)
                self._failed_checks.append("nettap-daemon")

            # OLD CODE START — #96: checked Docker Hub malcolm/*, which isn't where the
            # deployed images come from (ghcr.io), so it could never find an update
            # # Check Docker Hub for image updates
            # docker_updates = await self._check_docker_updates(current_versions)
            # all_updates.extend(docker_updates)
            # OLD CODE END
            # Check the running containers' images against their real source
            docker_updates = await self._check_docker_updates(current_versions, images)
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
            own_images = (_MALCOLM_REGISTRY, _NETTAP_IMAGE_PREFIX)
            # OLD CODE START — a source that couldn't be read was still listed as checked
            # self._checked = sorted(
            #     {"nettap-daemon", "suricata-rules", "geoip-db", *(c for c, i in images.items() if i.startswith(own_images))}
            # )
            # OLD CODE END
            self._checked = sorted(
                {"nettap-daemon", "suricata-rules", "geoip-db", *(c for c, i in images.items() if i.startswith(own_images))}
                - set(self._failed_checks)
            )

            logger.info(
                "Update check complete: %d updates available",
                len(all_updates),
            )

            return {
                "updates": [u.to_dict() for u in all_updates],
                "last_check": self._last_check,
                "count": len(all_updates),
                "has_updates": len(all_updates) > 0,
                "failed_checks": list(self._failed_checks),
                "checked": list(self._checked),
            }
        finally:
            self._checking = False

    async def get_available(self) -> dict:
        """Return cached available updates.

        Returns:
            Dict with "updates" (list), "last_check" (ISO timestamp),
            "count" (int), "has_updates" (bool) and "failed_checks" (list).
        """
        return {
            "updates": [u.to_dict() for u in self._available_updates],
            "last_check": self._last_check,
            "count": len(self._available_updates),
            "has_updates": len(self._available_updates) > 0,
            "failed_checks": list(self._failed_checks),
            "checked": list(self._checked),
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

        Raises:
            Exception: if GitHub could not be asked (check_updates records it).
        """
        results: list[AvailableUpdate] = []
        url = f"https://api.github.com/repos/{self._github_repo}/releases/latest"

        # OLD CODE START — #96: any failure was logged at debug and read as "no update"
        # try:
        #     data = await self._fetch_json(url)
        #     ...
        # except Exception as exc:
        #     logger.debug("GitHub release check failed: %s", exc)
        # OLD CODE END
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
                changelog=(data.get("body") or "")[:500],
                size_mb=self._estimate_release_size(data),
                requires_restart=True,
                # was unset: the page offered Update and the executor answered
                # "Unsupported component for update: nettap-daemon"
                applies_with=NETTAP_APPLIES_WITH,
            )
        )

        return results

    # OLD CODE START — #96: asked Docker Hub malcolm/*, but the deployed images come from
    # ghcr.io/idaholab/malcolm, so it could never find an update ("up to date" was false)
    # async def _check_docker_updates(self, current_versions):
    #     docker_images = {
    #         "zeek": "malcolm/zeek", "suricata": "malcolm/suricata",
    #         "arkime": "malcolm/arkime", "opensearch": "opensearchproject/opensearch",
    #         "dashboards": "opensearchproject/opensearch-dashboards",
    #         "logstash": "malcolm/logstash-oss", "file-monitor": "malcolm/file-monitor",
    #         "pcap-capture": "malcolm/pcap-capture",
    #     }
    #     for component, image_name in docker_images.items():
    #         current = current_versions.get(component)
    #         if not current or current in ("unknown", "latest"):
    #             continue
    #         hub_url = (f"https://hub.docker.com/v2/repositories/{image_name}"
    #                    f"/tags/?page_size=5&ordering=last_updated")
    #         try:
    #             data = await self._fetch_json(hub_url)
    #             ... first tag newer than current -> AvailableUpdate(size from full_size)
    #         except Exception as exc:
    #             logger.warning("Docker Hub check failed for %s: %s", component, exc)
    #             self._failed_checks.append(component)
    #     return results
    # OLD CODE END
    async def _check_docker_updates(
        self, current_versions: dict[str, str], images: dict[str, str]
    ) -> list[AvailableUpdate]:
        """Check the running containers' images for newer versions.

        Malcolm images (ghcr.io/idaholab/malcolm/*) all carry the Malcolm release
        tag (docker/docker-compose.yml), so they are compared with Malcolm's latest
        GitHub release. NetTap's own images (nettap/*) follow the NetTap release
        check. Any other image has no source to ask, so it goes in failed_checks
        rather than reading as up to date.

        Args:
            current_versions: Component name -> running image tag.
            images: Component name -> running image reference (from docker ps).

        Returns:
            List of AvailableUpdate for components with a newer release.
        """
        results: list[AvailableUpdate] = []
        malcolm: list[str] = []
        for component, image in sorted(images.items()):
            if image.startswith(_MALCOLM_REGISTRY):
                malcolm.append(component)
            elif not image.startswith(_NETTAP_IMAGE_PREFIX):
                # shortcut: no registry lookup for third-party images (grafana, nginx);
                # add one if NetTap ever updates them itself
                self._failed_checks.append(component)
        if not malcolm:
            return results

        try:
            data = await self._fetch_json(_MALCOLM_RELEASE_URL)
        except Exception as exc:
            logger.warning("Malcolm release check failed: %s", exc)
            self._failed_checks.extend(malcolm)
            return results
        latest = (data.get("tag_name") or "").lstrip("v")
        if not latest:  # nothing to compare with is not "no update"
            self._failed_checks.extend(malcolm)
            return results

        for component in malcolm:
            current = current_versions.get(component, "")
            update_type = await self._compare_versions(current.lstrip("v"), latest)
            if update_type == "unknown":  # e.g. a "latest" or custom tag
                self._failed_checks.append(component)
            elif update_type != "same":
                results.append(
                    AvailableUpdate(
                        component=component,
                        current_version=current,
                        latest_version=latest,
                        update_type=update_type,
                        release_url=data.get("html_url", ""),
                        release_date=data.get("published_at", ""),
                        changelog=f"Malcolm {latest}: {images[component].split(':')[0]}",
                        size_mb=None,  # the image size isn't known from the release
                        requires_restart=True,
                        applies_with=MALCOLM_APPLIES_WITH,
                    )
                )
        return results

    async def _check_suricata_rules(self) -> AvailableUpdate | None:
        """Check if Suricata ruleset has updates available.

        Compares the rule file's mtime against the current date (Suricata's own job
        refreshes it every night). The daemon container holds no copy, so the file is
        read in the Suricata container; if it can't be, "suricata-rules" goes in
        failed_checks.

        Returns:
            AvailableUpdate if rules are stale, None otherwise.
        """
        import os

        rule_paths = [
            "/var/lib/suricata/rules/suricata.rules",
            "/opt/nettap/config/suricata/rules/suricata.rules",
        ]

        # OLD CODE START — no local rules file read as "rules are current", but the
        # daemon container never has one: the file lives in the Suricata container
        # for rule_path in rule_paths:
        #     try:
        #         if not os.path.exists(rule_path):
        #             continue
        #         mtime = os.path.getmtime(rule_path)
        #         rule_date = datetime.fromtimestamp(mtime, tz=timezone.utc)
        #         ... (age check below, unchanged)
        #     except OSError:
        #         continue
        # return None
        # OLD CODE END
        rule_date = None
        for rule_path in rule_paths:
            try:
                if os.path.exists(rule_path):
                    rule_date = datetime.fromtimestamp(os.path.getmtime(rule_path), tz=timezone.utc)
                    break
            except OSError:
                continue

        if rule_date is None:
            live = await SuricataRuleManager().get_live_status()
            if not live.get("last_updated"):
                logger.warning("Could not read Suricata's rules date: %s", live.get("error"))
                self._failed_checks.append("suricata-rules")
                return None
            rule_date = datetime.fromisoformat(live["last_updated"])

        now = datetime.now(timezone.utc)
        age_days = (now - rule_date).days
        if age_days < 1:
            return None
        return AvailableUpdate(
            component="suricata-rules",
            current_version=rule_date.strftime("%Y-%m-%d"),
            latest_version=now.strftime("%Y-%m-%d"),
            update_type="patch",
            release_url="https://rules.emergingthreats.net/",
            release_date=now.isoformat(),
            changelog=f"Suricata rules are {age_days} day(s) old",
            # OLD CODE START — #96: an approximate size shown as the download size
            # size_mb=15.0,  # Approximate ET ruleset size
            # OLD CODE END
            size_mb=None,
            # was True: the update reloads the rules into the running Suricata
            requires_restart=False,
        )

    async def _check_geoip_update(self) -> AvailableUpdate | None:
        """Check if GeoIP database needs updating.

        MaxMind GeoLite2 databases are updated weekly. If the local
        database is older than 7 days, suggest an update. With no local
        database, the one bundled in the Logstash container is checked; its
        update comes with a NetTap release (applies_with), and if it can't be
        read, "geoip-db" goes in failed_checks.

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
                        # OLD CODE START — #96: an approximate size shown as the download size
                        # size_mb=65.0,  # Approximate GeoLite2-City size
                        # OLD CODE END
                        size_mb=None,
                        requires_restart=False,
                    )
                return None
            except OSError:
                continue

        # OLD CODE START — no local database read as "no update", but enrichment uses
        # the database bundled in Malcolm's Logstash image (9 months old on the G11)
        # return None
        # OLD CODE END
        try:
            mtime = await self._logstash_geoip_mtime()
        except Exception as exc:
            logger.warning("Could not read Logstash's GeoIP database date: %s", exc)
            self._failed_checks.append("geoip-db")
            return None

        db_date = datetime.fromtimestamp(mtime, tz=timezone.utc)
        now = datetime.now(timezone.utc)
        age_days = (now - db_date).days
        if age_days < 7:
            return None
        return AvailableUpdate(
            component="geoip-db",
            current_version=db_date.strftime("%Y-%m-%d"),
            latest_version=now.strftime("%Y-%m-%d"),
            update_type="patch",
            release_url="https://dev.maxmind.com/geoip/updating-databases",
            release_date=now.isoformat(),
            changelog=f"Logstash's GeoIP database is {age_days} day(s) old",
            size_mb=None,
            requires_restart=False,
            applies_with=_LOGSTASH_GEOIP_APPLIES_WITH,
        )

    async def _logstash_geoip_mtime(self) -> float:
        """Modified time (epoch seconds) of the GeoIP database in the Logstash container.

        Raises:
            RuntimeError: if docker or the container couldn't be read.
            ValueError: if stat printed no date.
        """
        # create_subprocess_exec: no host shell; sh -c runs inside the container for the glob
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            _LOGSTASH_CONTAINER,
            "sh",
            "-c",
            f"stat -c %Y {_LOGSTASH_GEOIP_DB}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode("utf-8", errors="replace").strip())
        # one line per match (normally one): take the newest rather than guess
        return max(float(line) for line in stdout.decode().split())

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
            Parsed JSON as a dict, or an empty dict on 404 (nothing published).

        Raises:
            RuntimeError: on any other non-200 status (rate limit, server error).
            aiohttp.ClientError, asyncio.TimeoutError: if the request failed.
        """
        # OLD CODE START — #96: every failure (offline, rate-limited) read as "no data",
        # so the update page said "up to date"
        # try:
        #     ...
        #             if resp.status == 200:
        #                 return await resp.json()
        #             else:
        #                 logger.debug("HTTP %d from %s", resp.status, url)
        #                 return {}
        # except aiohttp.ClientError as exc:
        #     logger.debug("HTTP request failed for %s: %s", url, exc)
        #     return {}
        # except Exception as exc:
        #     logger.debug("Unexpected error fetching %s: %s", url, exc)
        #     return {}
        # OLD CODE END
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                url,
                headers={"Accept": "application/json"},
                ssl=False,
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                if resp.status == 404:
                    return {}
                raise RuntimeError(f"HTTP {resp.status} from {url}")

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
    def _estimate_release_size(release_data: dict) -> float | None:
        """Release download size in MB from GitHub release data.

        Sums up asset sizes if available, otherwise None (not known).
        """
        total = 0
        for asset in release_data.get("assets", []):
            total += asset.get("size", 0)

        if total > 0:
            return round(total / (1024 * 1024), 1)

        # OLD CODE START — #96: a release without assets showed a made-up 50 MB
        # # Default estimate for NetTap release
        # return 50.0
        # OLD CODE END
        return None
