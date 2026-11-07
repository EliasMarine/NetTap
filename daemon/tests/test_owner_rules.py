"""NET-191 slice 3: saving owner rules: Suricata's test, the rename, the reload, and putting back."""

import asyncio
import fcntl
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services import owner_rules as orm
from services import rules_lock
from services.owner_rules import OwnerRules, OwnerRulesError, suricata_errors
from services.rules_lock import RulesBusyError
from services.suricata_rules import SuricataRuleManager

OLD = 'alert dns any any -> any any (msg:"old"; dns.query; content:"old.invalid"; sid:1000001; rev:1;)\n'
NEW = 'alert dns any any -> any any (msg:"secret-rule-text"; dns.query; content:"nettap-selftest.invalid"; sid:1999999; rev:1;)\n'
YAML = b"rule-files:\n  - suricata.rules\n  - /opt/suricata/rules/custom/owner.rules\n"
OK = '{"message": "done", "return": "OK"}'
STATS_OK = (
    '{"message": [{"id": 0, "rules_loaded": 65379, "rules_failed": 0}], "return": "OK"}'
)
STATS_BAD = (
    '{"message": [{"id": 0, "rules_loaded": 65378, "rules_failed": 1}], "return": "OK"}'
)
PASSED = "Info: detect: 8 rule files processed. 65379 rules successfully loaded, 0 rules failed, 0 rules skipped\nNotice: suricata: Configuration provided was successfully loaded. Exiting."
REFUSED = (
    "Error: detect-parse: unknown rule keyword 'nosuchkeyword'.\n"
    'Error: detect: error parsing signature "alert dns any any -> any any (nosuchkeyword; sid:1000002;)" '
    "from file /opt/suricata/rules/custom/owner.rules at line 2\n"
    "Error: suricata: Loading signatures failed."
)


class FakeDocker:
    """Stands in for the docker CLI; records every call and what the custom dir held during the test."""

    def __init__(self, staging_source: str, custom: str):
        self.calls: list[tuple] = []
        self.staging_source = staging_source
        self.custom = custom
        self.yaml = YAML
        self.test = (0, PASSED)
        self.reloads = [OK]
        self.stats = [STATS_OK]
        self.running = 0
        self.most_running = 0
        self.during_test: dict = {}

    async def __call__(self, *cmd: str, timeout: float) -> tuple[int, str]:
        self.calls.append(cmd)
        verb = cmd[1]
        if verb == "inspect":
            return 0, json.dumps([
                {"Config": {"Image": "malcolm/suricata:26.10.0", "Env": ["PUID=1000", "PGID=1001"]},
                 "Mounts": [{"Name": "nettap_suricata-rules", "Destination": "/var/lib/suricata/rules"}]},
                {"Mounts": [{"Source": self.staging_source, "Destination": orm.STAGING_DIR}]},
            ])  # fmt: skip
        if verb == "cp":
            if cmd[2].endswith("/etc/suricata/."):
                with open(os.path.join(cmd[3], "suricata.yaml"), "wb") as fh:
                    fh.write(self.yaml)
            return 0, ""
        if verb == "run":
            self.running += 1
            self.most_running = max(self.most_running, self.running)
            docker_args = cmd[
                : cmd.index("--entrypoint")
            ]  # Suricata's own -v comes after
            mounts = [
                docker_args[i + 1] for i, arg in enumerate(docker_args) if arg == "-v"
            ]
            candidate = next(
                m for m in mounts if m.endswith(":/opt/suricata/rules/custom:ro")
            )
            staged = candidate.split(":")[0].replace(
                self.staging_source, orm.STAGING_DIR
            )
            self.during_test = {
                "custom": sorted(os.listdir(self.custom)),
                "owner": open(os.path.join(self.custom, "owner.rules")).read(),
                "staged": sorted(os.listdir(staged)),
                "candidate": open(os.path.join(staged, "owner.rules")).read(),
                "mounts": mounts,
            }
            try:
                await asyncio.sleep(0.01)
                if isinstance(self.test, BaseException):
                    raise self.test
                return self.test
            finally:
                self.running -= 1
        if verb == "rm":
            return 0, ""
        if verb == "exec" and cmd[-1] == "reload-rules":
            return 0, self.reloads.pop(0) if len(self.reloads) > 1 else self.reloads[0]
        if verb == "exec" and cmd[-1] == "ruleset-stats":
            return 0, self.stats.pop(0) if len(self.stats) > 1 else self.stats[0]
        raise AssertionError(f"unexpected docker call {cmd}")


@pytest.fixture
def env(tmp_path, monkeypatch):
    custom = tmp_path / "custom"
    staging = tmp_path / "staging"
    state = tmp_path / "state"
    for d in (custom, staging, state):
        d.mkdir()
    monkeypatch.setattr(rules_lock, "RULES_STATE_DIR", str(state))
    monkeypatch.setattr(orm, "STAGING_DIR", str(staging))
    monkeypatch.setattr(orm, "THRESHOLD_FILE", str(tmp_path / "no-threshold"))
    docker = FakeDocker(
        "/var/lib/docker/volumes/nettap_rules-staging/_data", str(custom)
    )
    monkeypatch.setattr(orm, "_run", docker)
    owner = OwnerRules(
        SuricataRuleManager(container_name="live"), str(custom), str(staging)
    )
    (custom / "owner.rules").write_text(OLD)
    return owner, docker, custom, staging, state


def save(owner: OwnerRules, content):
    return asyncio.run(owner.save(content))


def lock_is_free(state) -> bool:
    fd = os.open(state / "rules.lock", os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False
    finally:
        os.close(fd)


class TestSave:
    def test_success_tests_renames_and_reloads(self, env):
        owner, docker, custom, staging, state = env
        result = save(owner, NEW)
        assert result == {
            "saved": True,
            "rule_count": 1,
            "engine": {"loaded": 65379, "failed": 0},
        }
        assert (custom / "owner.rules").read_text() == NEW
        assert (custom / "owner.rules.prev").read_text() == OLD
        assert oct((custom / "owner.rules").stat().st_mode & 0o777) == "0o644"
        assert sorted(os.listdir(custom)) == ["owner.rules", "owner.rules.prev"]
        assert os.listdir(staging) == []  # the snapshot is removed
        assert lock_is_free(state) and not owner._rules.op_lock.locked()
        assert [c[-1] for c in docker.calls if c[1] == "exec"] == [
            "reload-rules",
            "ruleset-stats",
        ]

    def test_the_test_runs_on_the_staged_candidate_never_in_the_custom_dir(self, env):
        owner, docker, custom, staging, _ = env
        save(owner, NEW)
        seen = docker.during_test
        assert seen["custom"] == ["owner.rules"] and seen["owner"] == OLD
        assert seen["staged"] == ["owner.rules"] and seen["candidate"] == NEW
        src = docker.staging_source
        assert all(
            m.startswith((src + "/", "nettap_suricata-rules:")) for m in seen["mounts"]
        )
        assert any(m.endswith(":/etc/suricata:ro") for m in seen["mounts"])
        assert "nettap_suricata-rules:/var/lib/suricata/rules:ro" in seen["mounts"]

    def test_the_runner_is_boxed(self, env):
        owner, docker, *_ = env
        save(owner, NEW)
        run = next(c for c in docker.calls if c[1] == "run")
        text = " ".join(run)
        for part in ("--rm", "--network none", "--memory 1g", "--memory-swap 1g", "--cpus 1",
                     "--user 1000:1001", "--cap-drop ALL", "--security-opt no-new-privileges",
                     "malcolm/suricata:26.10.0 -T"):  # fmt: skip
            assert part in text
        name = run[run.index("--name") + 1]
        assert ("docker", "rm", "-f", name) in docker.calls

    def test_the_threshold_file_is_mounted_when_there_is_one(
        self, env, tmp_path, monkeypatch
    ):
        owner, docker, *_ = env
        threshold = tmp_path / "suricata-threshold.config"
        threshold.write_text("suppress gen_id 1, sig_id 1\n")
        monkeypatch.setattr(orm, "THRESHOLD_FILE", str(threshold))
        save(owner, NEW)
        assert f"{threshold}:{threshold}:ro" in docker.during_test["mounts"]

    def test_empty_content_clears_the_rules(self, env):
        owner, docker, custom, *_ = env
        assert save(owner, "")["rule_count"] == 0
        assert (custom / "owner.rules").read_text() == ""
        assert (custom / "owner.rules.prev").read_text() == OLD

    def test_validator_refusal_never_reaches_docker(self, env):
        owner, docker, custom, *_ = env
        with pytest.raises(OwnerRulesError) as err:
            save(owner, NEW.replace("alert", "drop"))
        assert err.value.status == 400
        assert err.value.errors == [
            {"line": 1, "message": "Only alert rules can be used."}
        ]
        assert docker.calls == [] and (custom / "owner.rules").read_text() == OLD

    @pytest.mark.parametrize("content", [None, 5, ["x"]])
    def test_content_must_be_text(self, env, content):
        owner, docker, *_ = env
        with pytest.raises(OwnerRulesError) as err:
            save(owner, content)
        assert err.value.status == 400 and docker.calls == []


class TestFailures:
    def test_suricata_refuses_and_nothing_changes(self, env):
        owner, docker, custom, staging, state = env
        docker.test = (1, REFUSED)
        with pytest.raises(OwnerRulesError) as err:
            save(owner, NEW)
        assert err.value.status == 422
        assert err.value.errors == [
            {"line": 2, "message": "unknown rule keyword 'nosuchkeyword'."}
        ]
        assert (
            str(err.value)
            == "Suricata refused the rules: unknown rule keyword 'nosuchkeyword'."
        )
        assert (custom / "owner.rules").read_text() == OLD
        assert not (custom / "owner.rules.prev").exists()
        assert not [c for c in docker.calls if c[1] == "exec"]  # no reload
        assert os.listdir(staging) == [] and lock_is_free(state)

    def test_exit_0_without_0_failed_is_a_refusal(self, env):
        owner, docker, custom, *_ = env
        docker.test = (0, "Info: detect: 1 rules successfully loaded, 10 rules failed")
        with pytest.raises(OwnerRulesError) as err:
            save(owner, NEW)
        assert err.value.status == 422 and (custom / "owner.rules").read_text() == OLD

    def test_reload_failure_puts_the_previous_rules_back(self, env):
        owner, docker, custom, staging, state = env
        docker.reloads = ['{"message": "busy", "return": "NOK"}', OK]
        with pytest.raises(OwnerRulesError) as err:
            save(owner, NEW)
        assert err.value.status == 502
        assert "The previous rules were put back." in str(err.value)
        assert (custom / "owner.rules").read_text() == OLD
        assert [c[-1] for c in docker.calls if c[1] == "exec"] == [
            "reload-rules",
            "reload-rules",
            "ruleset-stats",
        ]
        assert os.listdir(staging) == [] and lock_is_free(state)

    def test_failed_rules_after_the_reload_put_the_previous_rules_back(self, env):
        owner, docker, custom, *_ = env
        docker.stats = [STATS_BAD, STATS_OK]
        with pytest.raises(OwnerRulesError) as err:
            save(owner, NEW)
        assert err.value.status == 502 and "1 rules failed to load" in str(err.value)
        assert (custom / "owner.rules").read_text() == OLD

    def test_an_unconfirmed_put_back_says_so(self, env):
        owner, docker, custom, *_ = env
        docker.reloads = ['{"return": "NOK"}']
        with pytest.raises(OwnerRulesError) as err:
            save(owner, NEW)
        assert "didn't confirm loading them" in str(err.value)
        assert (custom / "owner.rules").read_text() == OLD

    def test_docker_failing_at_the_reload_still_puts_the_previous_rules_back(
        self, env, monkeypatch
    ):
        owner, docker, custom, *_ = env

        async def no_exec(*cmd, timeout):
            if cmd[1] == "exec":
                raise OSError("docker went away")
            return await docker(*cmd, timeout=timeout)

        monkeypatch.setattr(orm, "_run", no_exec)
        with pytest.raises(OwnerRulesError) as err:
            save(owner, NEW)
        assert err.value.status == 502 and "didn't confirm loading them" in str(
            err.value
        )
        assert (custom / "owner.rules").read_text() == OLD

    def test_timeout_removes_the_container_and_releases_the_locks(self, env):
        owner, docker, custom, staging, state = env
        docker.test = (-1, "no answer in 180 s")
        with pytest.raises(OwnerRulesError) as err:
            save(owner, NEW)
        assert err.value.status == 500 and "within 180 s" in str(err.value)
        run = next(c for c in docker.calls if c[1] == "run")
        name = run[run.index("--name") + 1]
        assert docker.calls[-1] == ("docker", "rm", "-f", name)
        assert (custom / "owner.rules").read_text() == OLD
        assert os.listdir(staging) == []
        assert lock_is_free(state) and not owner._rules.op_lock.locked()

    def test_a_cancelled_save_removes_the_container_and_releases_the_locks(self, env):
        owner, docker, custom, staging, state = env
        docker.test = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            save(owner, NEW)
        assert docker.calls[-1][:3] == ("docker", "rm", "-f")
        assert (custom / "owner.rules").read_text() == OLD
        assert os.listdir(staging) == [] and lock_is_free(state)

    def test_suricata_started_before_owner_rules_existed(self, env):
        owner, docker, custom, *_ = env
        docker.yaml = b"rule-files:\n  - suricata.rules\n"
        with pytest.raises(OwnerRulesError) as err:
            save(owner, NEW)
        assert err.value.status == 409 and "deploy-detection-slice3.sh" in str(
            err.value
        )
        assert not [c for c in docker.calls if c[1] == "run"]
        assert (custom / "owner.rules").read_text() == OLD

    def test_an_interrupted_save_leaves_no_extra_rules_file(self, env, monkeypatch):
        owner, docker, custom, *_ = env
        real_replace = os.replace

        def crash(src, dst):
            if dst.endswith("/owner.rules"):
                raise OSError("disk gone")
            real_replace(src, dst)

        monkeypatch.setattr(orm.os, "replace", crash)
        with pytest.raises(OSError):
            save(owner, NEW)
        assert sorted(os.listdir(custom)) == ["owner.rules", "owner.rules.prev"]
        assert (custom / "owner.rules").read_text() == OLD
        assert [f for f in os.listdir(custom) if f.endswith(".rules")] == [
            "owner.rules"
        ]

    def test_busy_lock_is_refused(self, env, monkeypatch):
        owner, docker, custom, staging, state = env
        monkeypatch.setattr(orm, "LOCK_WAIT_S", 0.1)
        fd = os.open(state / "rules.lock", os.O_RDONLY | os.O_CREAT)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            with pytest.raises(RulesBusyError):
                save(owner, NEW)
        finally:
            os.close(fd)
        assert docker.calls == [] and not owner._rules.op_lock.locked()

    def test_container_unreadable(self, env, monkeypatch):
        owner, docker, custom, *_ = env

        async def broken(*cmd, timeout):
            return 1, "Error: No such object: live"

        monkeypatch.setattr(orm, "_run", broken)
        with pytest.raises(OwnerRulesError) as err:
            save(owner, NEW)
        assert err.value.status == 502
        assert (custom / "owner.rules").read_text() == OLD


def test_concurrent_saves_run_one_after_the_other(env):
    owner, docker, custom, *_ = env
    second = NEW.replace("1999999", "1999998")

    async def both():
        return await asyncio.gather(owner.save(NEW), owner.save(second))

    first, last = asyncio.run(both())
    assert first["saved"] and last["saved"]
    assert docker.most_running == 1
    assert [c[1] for c in docker.calls].count("run") == 2
    assert (custom / "owner.rules").read_text() == second
    assert (custom / "owner.rules.prev").read_text() == NEW


def test_logs_carry_counts_never_rule_text(env, caplog):
    owner, docker, *_ = env
    caplog.set_level(logging.DEBUG)
    save(owner, NEW)
    docker.test = (1, REFUSED)
    with pytest.raises(OwnerRulesError):
        save(owner, NEW)
    docker.test, docker.reloads = (0, PASSED), ['{"return": "NOK"}']
    with pytest.raises(OwnerRulesError):
        save(owner, NEW)
    assert "Owner rules" in caplog.text
    assert (
        "secret-rule-text" not in caplog.text and "nettap-selftest" not in caplog.text
    )


class TestPrepareAndRead:
    def test_prepare_creates_an_empty_world_readable_file(self, tmp_path):
        custom, staging = tmp_path / "custom", tmp_path / "staging"
        custom.mkdir()
        OwnerRules(SuricataRuleManager(), str(custom), str(staging)).prepare()
        assert (custom / "owner.rules").read_text() == ""
        assert oct((custom / "owner.rules").stat().st_mode & 0o777) == "0o644"

    def test_prepare_keeps_existing_rules(self, env):
        owner, _, custom, *_ = env
        owner.prepare()
        assert (custom / "owner.rules").read_text() == OLD

    def test_prepare_removes_only_stale_staging_dirs(self, env):
        owner, _, _, staging, _ = env
        old, fresh = staging / "old", staging / "fresh"
        (old / "etc-suricata").mkdir(parents=True)
        fresh.mkdir()
        hour_ago = time.time() - 3700
        os.utime(old, (hour_ago, hour_ago))
        owner.prepare()
        assert os.listdir(staging) == ["fresh"]

    def test_prepare_without_the_volume_does_nothing(self, tmp_path):
        OwnerRules(
            SuricataRuleManager(), str(tmp_path / "none"), str(tmp_path / "s")
        ).prepare()
        assert os.listdir(tmp_path) == []

    def test_staging_inside_the_custom_dir_is_refused(self, tmp_path):
        with pytest.raises(ValueError):
            OwnerRules(SuricataRuleManager(), str(tmp_path), str(tmp_path / "staging"))
        with pytest.raises(ValueError):
            OwnerRules(SuricataRuleManager(), str(tmp_path), str(tmp_path))

    def test_read(self, env):
        owner, *_ = env
        assert owner.read() == {
            "content": OLD,
            "rule_count": 1,
            "max_rules": 2000,
            "max_bytes": 262144,
        }

    def test_read_without_a_file(self, tmp_path):
        owner = OwnerRules(
            SuricataRuleManager(), str(tmp_path / "c"), str(tmp_path / "s")
        )
        assert owner.read()["content"] == "" and owner.read()["rule_count"] == 0


def test_suricata_errors_finds_each_line():
    out = (
        REFUSED
        + '\nError: detect-parse: no terminating ";" found\n'
        + (
            'Error: detect: error parsing signature "x" from file /opt/suricata/rules/custom/owner.rules at line 7'
        )
    )
    assert suricata_errors(out) == [
        {"line": 2, "message": "unknown rule keyword 'nosuchkeyword'."},
        {"line": 7, "message": 'no terminating ";" found'},
    ]
    assert (
        suricata_errors(
            "Error: detect: error parsing signature from file /x/other.rules at line 3"
        )
        == []
    )
