"""Malcolm update: order, backup, --no-deps, rollback (services/malcolm_upgrade.py)."""

import asyncio
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

import pytest
import yaml

from services import malcolm_upgrade as mu
from services.malcolm_upgrade import MalcolmUpgrade, newer, tag_of

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NOW = datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc)
LABELS = {
    "com.docker.compose.project": "docker",
    "com.docker.compose.project.working_dir": "/home/nettap/NetTap/docker",
    "com.docker.compose.project.config_files": "/home/nettap/NetTap/docker/docker-compose.yml",
}
RUNNING = [
    "opensearch",
    "dashboards-helper",
    "dashboards",
    "logstash",
    "filebeat",
    "zeek-live",
    "suricata-live",
    "pcap-capture",
    "redis",
    "api",
]  # arkime-live's profile is off


class FakeDocker:
    """Answers the docker commands the update runs; fail= names a step to fail."""

    def __init__(
        self, fail: str = "", tag: str = "26.02.0", free_kb: int = 900 * 1048576
    ) -> None:
        self.calls: list[list[str]] = []
        self.fail = fail
        self.tags = {s: tag for s in RUNNING}
        self.free_kb = free_kb

    async def run(self, cmd: list[str], timeout: float) -> tuple[str, int]:
        self.calls.append(cmd)
        text = " ".join(cmd)
        for step, needle in (
            ("pull", " pull "),
            ("build", " build "),
            ("copy", "cp -a"),
            ("login", "_cluster/health"),
            ("healthy", "State.Health"),
            ("up", " up -d"),
        ):
            if self.fail == step and needle in text:
                return ("boom", 1)
        if cmd[:3] == ["docker", "inspect", mu.DAEMON_CONTAINER]:
            return (json.dumps(LABELS) + "\tsha256:daemonimage\n", 0)
        if cmd[:3] == ["docker", "ps", "-a"]:

            def img(s: str) -> str:
                return (
                    f"nettap/zeek-live:{self.tags[s]}"
                    if s == "zeek-live"
                    else f"ghcr.io/idaholab/malcolm/{s}:{self.tags[s]}"
                )

            return (
                "".join(f"{s}\tnettap-{s}\trunning\t{img(s)}\n" for s in RUNNING)
                + "nettap-storage-daemon\tnettap-storage-daemon\trunning\tnettap/storage-daemon:latest\n",
                0,
            )
        if "Destination" in text:
            return ("docker_opensearch-data\n", 0)
        if "du -sk" in text:
            return (f"1468006\n{self.free_kb}\n", 0)
        if " up -d " in text:
            tag = next(
                a.split("=", 1)[1] for a in cmd if a.startswith("MALCOLM_IMAGE_TAG=")
            )
            for s in cmd[cmd.index("--no-build") + 1 :]:
                self.tags[s] = tag
            return ("", 0)
        if "_cluster/health" in text:
            return ('{"status":"green"}', 0)
        if "State.Health" in text:
            names = cmd[4:]
            return (
                "".join(
                    f"/{n}\trunning\tnone\tx/{n}:{self.tags[n.removeprefix('nettap-')]}\n"
                    for n in names
                ),
                0,
            )
        return ("", 0)

    def text(self) -> list[str]:
        return [" ".join(c) for c in self.calls]


class FakeOpenSearch:
    """after: the count once the update starts, or a function of nothing (e.g. of the running tag)."""

    def __init__(self, before: int = 50, after=50) -> None:
        self.before, self.after = before, after

    def count(self, index: str, body: dict) -> dict:
        since = body["query"]["bool"]["filter"][1]["range"]["@timestamp"]["gte"]
        after = self.after() if callable(self.after) else self.after
        return {"count": self.before if since < NOW.isoformat() else after}


async def _no_sleep(_s: float) -> None:
    return None


def _upgrade(
    docker: FakeDocker, client=None, pcap=lambda: NOW.timestamp() + 30, tmp_path=None
) -> MalcolmUpgrade:
    return MalcolmUpgrade(
        client=client if client is not None else FakeOpenSearch(),
        run=docker.run,
        sleep=_no_sleep,
        now=lambda: NOW,
        pcap_mtime=pcap,
        state_file=str(tmp_path / "state.json"),
    )


def _apply(up: MalcolmUpgrade, target: str = "26.10.0") -> dict:
    steps: list[str] = []
    result = asyncio.run(
        up.apply(target, on_step=lambda name, done, total: steps.append(name))
    )
    result["steps"] = steps
    return result


class TestHappyPath:
    def test_updates_every_running_malcolm_container(self, tmp_path):
        docker = FakeDocker()
        result = _apply(_upgrade(docker, tmp_path=tmp_path))
        assert result["success"] is True, result
        assert (result["old_version"], result["new_version"]) == ("26.02.0", "26.10.0")
        assert set(docker.tags.values()) == {"26.10.0"}

    def test_order_is_pull_then_stop_then_backup_then_start(self, tmp_path):
        docker = FakeDocker()
        _apply(_upgrade(docker, tmp_path=tmp_path))
        text = docker.text()

        def first(needle: str) -> int:
            return next(i for i, t in enumerate(text) if needle in t)

        assert (
            first(" pull ")
            < first(" build ")
            < first("docker stop")
            < first("cp -a")
            < first("/home/nettap/NetTap/docker/.env MALCOLM_IMAGE_TAG=26.10.0")
            < first(" up -d ")
        )
        assert (
            first("up -d --no-deps --no-build opensearch")
            < first("_cluster/health")
            < first("up -d --no-deps --no-build dashboards-helper")
        )
        assert text[-1] == "docker volume rm docker_opensearch-data-before-update"

    def test_never_touches_the_daemon_running_it(self, tmp_path):
        docker = FakeDocker()
        _apply(_upgrade(docker, tmp_path=tmp_path))
        for cmd in docker.calls:
            if "up" in cmd or cmd[:2] == ["docker", "stop"]:
                assert "nettap-storage-daemon" not in cmd
                assert "--no-deps" in cmd or cmd[:2] == ["docker", "stop"]

    def test_capture_keeps_running_during_the_backup(self, tmp_path):
        docker = FakeDocker()
        _apply(_upgrade(docker, tmp_path=tmp_path))
        stop = next(c for c in docker.calls if c[:2] == ["docker", "stop"])
        assert "nettap-zeek-live" not in stop and "nettap-pcap-capture" not in stop
        assert stop[-1] == "nettap-opensearch"  # its writers stop first

    def test_pulls_only_running_services_and_builds_zeek_live(self, tmp_path):
        docker = FakeDocker()
        _apply(_upgrade(docker, tmp_path=tmp_path))
        pull = next(c for c in docker.calls if "pull" in c)
        assert (
            "arkime-live" not in pull
            and "zeek-live" not in pull
            and "opensearch" in pull
        )
        build = next(c for c in docker.calls if "build" in c and "--no-build" not in c)
        assert build[-1] == "zeek-live" and "MALCOLM_IMAGE_TAG=26.10.0" in build

    def test_compose_runs_with_the_project_at_its_host_path(self, tmp_path):
        docker = FakeDocker()
        _apply(_upgrade(docker, tmp_path=tmp_path))
        pull = next(c for c in docker.calls if "pull" in c)
        assert (
            "/home/nettap/NetTap:/home/nettap/NetTap" in pull
            and pull[pull.index("-w") + 1] == "/home/nettap/NetTap/docker"
        )
        assert pull[pull.index("-p") + 1] == "docker" and "sha256:daemonimage" in pull

    def test_compose_gets_the_release_key_value_image_with_the_tag(self, tmp_path):
        # Malcolm replaced Redis with Valkey in 26.04.0: a new image and a new data volume
        docker = FakeDocker()
        _apply(_upgrade(docker, tmp_path=tmp_path))
        composes = [c for c in docker.calls if "compose" in c]
        assert composes and all(
            "MALCOLM_IMAGE_TAG=26.10.0" in c and "MALCOLM_KV_IMAGE=valkey" in c
            for c in composes
        )
        write = next(c for c in docker.calls if "/home/nettap/NetTap/docker/.env" in c)
        assert write[-2:] == ["MALCOLM_IMAGE_TAG=26.10.0", "MALCOLM_KV_IMAGE=valkey"]

    def test_every_helper_runs_as_root(self, tmp_path):
        # the daemon image's USER is nettap; only compose's user: root makes the daemon root,
        # and nettap can't use docker.sock, write docker/.env or copy OpenSearch's files
        docker = FakeDocker()
        _apply(_upgrade(docker, tmp_path=tmp_path))
        helpers = [c for c in docker.calls if c[:2] == ["docker", "run"]]
        assert helpers and all(c[c.index("--user") + 1] == "root" for c in helpers)


class TestNothingChangesBeforeTheStop:
    @pytest.mark.parametrize("fail", ["pull", "build"])
    def test_a_failed_download_or_build_stops_nothing(self, tmp_path, fail):
        docker = FakeDocker(fail=fail)
        result = _apply(_upgrade(docker, tmp_path=tmp_path))
        assert result["success"] is False and "Nothing was changed" in result["error"]
        assert not any(c[:2] == ["docker", "stop"] for c in docker.calls)
        assert result["new_version"] == "26.02.0"

    def test_too_little_disk_refuses_before_downloading(self, tmp_path):
        docker = FakeDocker(free_kb=10 * 1048576)
        result = _apply(_upgrade(docker, tmp_path=tmp_path))
        assert "Not enough disk space" in result["error"]
        # NET-166: df/du count 1,024-byte blocks; the message says decimal GB, like every page
        assert "needs 23.0 GB free" in result["error"]
        assert "OpenSearch's 1.5 GB of data" in result["error"]
        assert "and 10.7 GB is" in result["error"]
        assert not any("pull" in c for c in docker.calls)

    def test_a_need_just_above_the_free_space_never_prints_the_same_figure(
        self, tmp_path
    ):
        # need = 1,468,006 KiB of data + 20 GiB of images = 22.978 GB; free is one KiB less
        docker = FakeDocker(free_kb=1468006 + 20 * 1048576 - 1)
        result = _apply(_upgrade(docker, tmp_path=tmp_path))
        assert "needs 23.0 GB free" in result["error"]
        assert "and 22.9 GB is" in result["error"]

    def test_mixed_releases_refuse(self, tmp_path):
        docker = FakeDocker()
        docker.tags["logstash"] = "26.10.0"
        result = _apply(_upgrade(docker, tmp_path=tmp_path))
        assert result["success"] is False and "different releases" in result["error"]

    def test_an_older_or_equal_target_refuses(self, tmp_path):
        docker = FakeDocker(tag="26.10.0")
        result = _apply(_upgrade(docker, tmp_path=tmp_path))
        assert result["success"] is False and "already" in result["error"]
        assert not any("pull" in c for c in docker.calls)

    def test_a_bad_tag_is_refused(self, tmp_path):
        with pytest.raises(ValueError):
            asyncio.run(
                _upgrade(FakeDocker(), tmp_path=tmp_path).apply("26.10.0; rm -rf /")
            )


class TestRollback:
    @pytest.mark.parametrize("fail", ["login", "healthy"])
    def test_a_failure_after_the_start_restores_the_old_release_and_data(
        self, tmp_path, fail
    ):
        docker = FakeDocker(fail=fail)
        result = _apply(_upgrade(docker, tmp_path=tmp_path))
        assert result["success"] is False and result["rolled_back"] is True
        assert (
            "rolled back to Malcolm 26.02.0" in result["error"]
            or "failed too" in result["error"]
        )
        restore = [c for c in docker.calls if "cp -a" in " ".join(c)]
        assert (
            restore[-1][restore[-1].index("-v") + 1]
            == "docker_opensearch-data-before-update:/from:ro"
        )
        writes = [c for c in docker.calls if "/home/nettap/NetTap/docker/.env" in c]
        assert writes[-1][-2:] == [
            "MALCOLM_IMAGE_TAG=26.02.0",
            "MALCOLM_KV_IMAGE=redis",
        ]
        ups = [c for c in docker.calls if " up -d " in " ".join(c)]
        assert "MALCOLM_KV_IMAGE=redis" in ups[-1]

    def test_capture_that_doesnt_resume_rolls_back(self, tmp_path):
        docker = FakeDocker()
        on_old = FakeOpenSearch(
            before=50, after=lambda: 0 if docker.tags["logstash"] == "26.10.0" else 50
        )
        result = _apply(_upgrade(docker, client=on_old, tmp_path=tmp_path))
        assert (
            result["rolled_back"] is True and "no new Zeek records" in result["error"]
        )
        assert set(docker.tags.values()) == {"26.02.0"}
        assert "rolled back to Malcolm 26.02.0" in result["error"]

    def test_a_rollback_waits_for_records_to_arrive_again(self, tmp_path):
        # healthy 26.02.0 containers with Logstash still starting aren't a working rollback
        docker = FakeDocker()
        up = _upgrade(
            docker, client=FakeOpenSearch(before=50, after=0), tmp_path=tmp_path
        )
        result = _apply(up)
        assert result["rolled_back"] is True and "failed too" in result["error"]
        assert "no new Zeek records" in result["error"].split("failed too")[1]
        assert "docker_opensearch-data-before-update" in result["error"]
        assert not any("volume rm" in t for t in docker.text())  # the backup is kept
        assert up.take_unfinished()["step"] == "rollback_failed"

    def test_pcap_that_stops_rolls_back(self, tmp_path):
        docker = FakeDocker()
        result = _apply(
            _upgrade(docker, pcap=lambda: NOW.timestamp() - 60, tmp_path=tmp_path)
        )
        assert result["rolled_back"] is True and "no new PCAP" in result["error"]

    def test_quiet_network_isnt_a_failure(self, tmp_path):
        docker = FakeDocker()
        result = _apply(
            _upgrade(
                docker,
                client=FakeOpenSearch(before=0, after=0),
                pcap=lambda: None,
                tmp_path=tmp_path,
            )
        )
        assert result["success"] is True

    def test_a_failed_rollback_says_where_the_data_is(self, tmp_path):
        docker = FakeDocker(fail="healthy")
        up = _upgrade(docker, tmp_path=tmp_path)
        result = _apply(up)
        assert (
            "failed too" in result["error"]
            and "docker_opensearch-data-before-update" in result["error"]
        )
        assert up.take_unfinished()["step"] == "rollback_failed"
        assert up.take_unfinished() is None  # read once


class TestHelpers:
    def test_newer(self):
        assert (
            newer("26.10.0", "26.02.0")
            and not newer("26.02.0", "26.10.0")
            and not newer("26.10.0", "26.10.0")
        )
        assert not newer("latest", "26.02.0")

    def test_tag_of(self):
        assert tag_of("ghcr.io/idaholab/malcolm/api:26.02.0") == "26.02.0"
        assert tag_of("localhost:5000/x") == ""

    def test_release_env_follows_malcolms_switch_to_valkey(self):
        assert mu.release_env("26.02.0") == {
            "MALCOLM_IMAGE_TAG": "26.02.0",
            "MALCOLM_KV_IMAGE": "redis",
        }
        assert mu.release_env("26.04.0")["MALCOLM_KV_IMAGE"] == "valkey"
        assert mu.release_env("26.10.0")["MALCOLM_KV_IMAGE"] == "valkey"

    def test_set_env_script_replaces_or_adds_each_line(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("PUID=1000\nMALCOLM_IMAGE_TAG=26.02.0\nX=1\n")
        os.chmod(env, 0o600)
        pairs = ["MALCOLM_IMAGE_TAG=26.10.0", "MALCOLM_KV_IMAGE=valkey"]
        subprocess.run(
            [sys.executable, "-c", mu._SET_ENV, str(env), *pairs], check=True
        )
        assert env.read_text() == (
            "PUID=1000\nMALCOLM_IMAGE_TAG=26.10.0\nX=1\nMALCOLM_KV_IMAGE=valkey\n"
        )
        assert oct(env.stat().st_mode & 0o777) == "0o600"
        subprocess.run(
            [sys.executable, "-c", mu._SET_ENV, str(env), "MALCOLM_KV_IMAGE=redis"],
            check=True,
        )
        assert "MALCOLM_KV_IMAGE=redis\n" in env.read_text()
        assert "valkey" not in env.read_text()

    # OLD CODE START — 2026-11-03: _SET_TAG became _SET_ENV (the key-value image moves too)
    def _old_test_set_tag_script_replaces_or_adds(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("PUID=1000\nMALCOLM_IMAGE_TAG=26.02.0\n")
        os.chmod(env, 0o600)
        subprocess.run(
            [sys.executable, "-c", mu._SET_TAG, str(env), "26.10.0"], check=True
        )
        assert (
            env.read_text() == "PUID=1000\nMALCOLM_IMAGE_TAG=26.10.0\n"
            and oct(env.stat().st_mode & 0o777) == "0o600"
        )
        added = tmp_path / "other.env"
        added.write_text("PUID=1000")
        subprocess.run(
            [sys.executable, "-c", mu._SET_TAG, str(added), "26.10.0"], check=True
        )
        assert added.read_text() == "PUID=1000\nMALCOLM_IMAGE_TAG=26.10.0\n"

    # OLD CODE END


def _compose_tags() -> set[str]:
    text = open(os.path.join(REPO, "docker", "docker-compose.yml")).read()
    return set(re.findall(r"MALCOLM_IMAGE_TAG:-([0-9.]+)", text)) | set(
        re.findall(r'x-malcolm-tag: &malcolm-tag "([0-9.]+)"', text)
    )


class TestTheTestedReleaseIsTheOneNetTapInstalls:
    def test_compose_defaults(self):
        assert _compose_tags() == {mu.TESTED_MALCOLM_TAG}

    def test_install_pins(self):
        conf = open(
            os.path.join(REPO, "scripts", "install", "malcolm-versions.conf")
        ).read()
        assert f'MALCOLM_IMAGE_TAG="{mu.TESTED_MALCOLM_TAG}"' in conf
        gen = open(os.path.join(REPO, "scripts", "install", "malcolm-config.sh")).read()
        assert f"MALCOLM_IMAGE_TAG={mu.TESTED_MALCOLM_TAG}\n" in gen
        dockerfile = open(os.path.join(REPO, "docker", "Dockerfile.zeek-live")).read()
        assert f"ARG MALCOLM_IMAGE_TAG={mu.TESTED_MALCOLM_TAG}" in dockerfile

    def test_install_and_compose_use_the_tested_key_value_image(self):
        kv = mu.release_env(mu.TESTED_MALCOLM_TAG)["MALCOLM_KV_IMAGE"]
        conf = open(
            os.path.join(REPO, "scripts", "install", "malcolm-versions.conf")
        ).read()
        assert f'MALCOLM_IMG_REDIS="{kv}"' in conf
        gen = open(os.path.join(REPO, "scripts", "install", "malcolm-config.sh")).read()
        assert f"MALCOLM_KV_IMAGE={kv}\n" in gen
        compose = yaml.safe_load(
            open(os.path.join(REPO, "docker", "docker-compose.yml"))
        )
        redis = compose["services"]["redis"]
        assert "/${MALCOLM_KV_IMAGE:-redis}:" in redis["image"]
        assert "${MALCOLM_KV_IMAGE:-redis}-data:/data" in redis["volumes"]
        # each image keeps its own data: Valkey 8.1 can't read Redis 7.4's RDB files
        assert {"redis-data", "valkey-data"} <= set(compose["volumes"])
        # "/" is a 404 on 26.10.0's api; /mapi/ping is what Malcolm's container_health.sh uses
        api_check = " ".join(compose["services"]["api"]["healthcheck"]["test"])
        assert "http://localhost:5000/mapi/ping" in api_check
        # the only 26.10.0 images that read VALKEY_* (every file in each image searched)
        for svc in ("api", "filebeat"):
            env = compose["services"][svc]["environment"]
            assert env["VALKEY_HOST"] == env["REDIS_HOST"] == "redis", svc
            assert env["VALKEY_PASSWORD"] == env["REDIS_PASSWORD"], svc

    def test_malcolm_services_are_the_compose_services_on_the_tag(self):
        services = yaml.safe_load(
            open(os.path.join(REPO, "docker", "docker-compose.yml"))
        )["services"]
        on_tag = {
            n
            for n, s in services.items()
            if "MALCOLM_IMAGE_TAG" in str(s.get("image", "")) + str(s.get("build", ""))
        }
        assert on_tag == set(mu.MALCOLM_SERVICES)
