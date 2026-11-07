"""NET-191 slice 3: saving owner rules: Suricata's test, the rename, the reload, and putting back."""

import asyncio
import fcntl
import json
import logging
import os
import re
import shutil
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services import etpro
from services import owner_rules as orm
from services import rules_lock
from services.owner_rules import (
    OwnerRules,
    OwnerRulesError,
    analysis_problem,
    suricata_errors,
)
from services.rules_lock import RulesBusyError
from services.suricata_rules import SuricataRuleManager

OLD = 'alert dns any any -> any any (msg:"old"; dns.query; content:"old.invalid"; sid:1000001; rev:1;)\n'
NEW = 'alert dns any any -> any any (msg:"secret-rule-text"; dns.query; content:"nettap-selftest.invalid"; sid:1999999; rev:1;)\n'
YAML = b"rule-files:\n  - suricata.rules\n  - /opt/suricata/rules/custom/owner.rules\n"
OK = '{"message": "done", "return": "OK"}'
IN_PROGRESS = '{"message": "Reload already in progress", "return": "NOK"}'
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
# Suricata 8.0.7's engine analysis of the review's quoted-";" rule (the Malcolm image, -S, rules.json)
ANALYSED_BYPASS = (
    '{"class":"threat detection","raw":"alert tcp any any -> any any (msg:\\"x\\"; metadata:a\\"; '
    'bypass; metadata:b\\"; sid:1000001; rev:1;)","id":1000001,"gid":1,"rev":1,"msg":"x",'
    '"app_proto":"unknown","requirements":[],"match_policy":{"actions":["alert"],"scope":"packet"},'
    '"type":"pkt","flags":["src_any","dst_any","sp_any","dp_any","toserver","toclient","bypass"],'
    '"pkt_engines":[],"frame_engines":[],"lists":{"postmatch":{"matches":[{"name":"bypass"}]}}}'
)


class FakeDocker:
    """Stands in for the docker CLI; records every call and what the custom dir held during the test.
    `test` None = Suricata passes and analyses each staged rule with the keywords in `names`."""

    def __init__(self, staging_source: str, custom: str):
        self.calls: list[tuple] = []
        self.staging_source = staging_source
        self.custom = custom
        self.yaml = YAML
        self.test = None
        self.names = ["content"]
        self.dropped = 0
        self.reloads = [OK]
        self.stats = [STATS_OK]
        self.running = 0
        self.most_running = 0
        self.during_test: dict = {}

    def _passed(self, candidate: str) -> tuple[int, str]:
        sids = re.findall(r"sid:(\d+);", candidate)[self.dropped :]
        matches = [{"name": name} for name in self.names]
        analysed = [
            json.dumps({"id": int(sid), "lists": {"payload": {"matches": matches}}})
            for sid in sids
        ]
        return 0, "\n".join([PASSED, *analysed])

    @staticmethod
    def _next(answers: list):
        answer = answers.pop(0) if len(answers) > 1 else answers[0]
        return answer if isinstance(answer, tuple) else (0, answer)

    async def __call__(self, *cmd: str, timeout: float) -> tuple[int | None, str]:
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
            return await self._run_test(cmd)
        if verb == "rm":
            return 0, ""
        if verb == "exec" and cmd[-1] == "reload-rules":
            return self._next(self.reloads)
        if verb == "exec" and cmd[-1] == "ruleset-stats":
            return self._next(self.stats)
        raise AssertionError(f"unexpected docker call {cmd}")

    async def _run_test(self, cmd: tuple) -> tuple[int | None, str]:
        self.running += 1
        self.most_running = max(self.most_running, self.running)
        docker_args = cmd[
            : cmd.index("--entrypoint")
        ]  # Suricata's own options come after
        mounts = [docker_args[i + 1] for i, a in enumerate(docker_args) if a == "-v"]
        candidate = next(
            m for m in mounts if m.endswith(":/opt/suricata/rules/custom:ro")
        )
        staged = candidate.split(":")[0].replace(self.staging_source, orm.STAGING_DIR)
        with open(os.path.join(staged, "owner.rules")) as fh:
            text = fh.read()
        self.during_test = {
            "custom": sorted(os.listdir(self.custom)),
            "owner": open(os.path.join(self.custom, "owner.rules")).read(),
            "staged": sorted(os.listdir(staged)),
            "candidate": text,
            "mounts": mounts,
        }
        try:
            await asyncio.sleep(0.01)
            if isinstance(self.test, BaseException):
                raise self.test
            return self._passed(text) if self.test is None else self.test
        finally:
            self.running -= 1


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
    monkeypatch.setattr(orm, "RELOAD_RETRY_S", 0)
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


def refused(owner: OwnerRules, content=NEW) -> OwnerRulesError:
    with pytest.raises(OwnerRulesError) as err:
        save(owner, content)
    return err.value


def lock_is_free(state) -> bool:
    fd = os.open(state / "rules.lock", os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False
    finally:
        os.close(fd)


def execs(docker: FakeDocker) -> list[str]:
    return [c[-1] for c in docker.calls if c[1] == "exec"]


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
        assert execs(docker) == ["reload-rules", "ruleset-stats"]

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
                     "--log-driver none", "--tmpfs /tmp/owner-analysis:size=64m",
                     "malcolm/suricata:26.10.0 -c"):  # fmt: skip
            assert part in text
        script = run[run.index("-c") + 1]
        assert script == orm.TEST_SH
        assert "-T -v" in script and "--set security.lua.allow-rules=false" in script
        assert "--engine-analysis -S /opt/suricata/rules/custom/owner.rules" in script
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
        error = refused(owner, NEW.replace("alert", "drop"))
        assert error.status == 400
        assert error.errors == [{"line": 1, "message": "Only alert rules can be used."}]
        assert str(error) == "Nothing was saved: Only alert rules can be used."
        assert docker.calls == [] and (custom / "owner.rules").read_text() == OLD

    @pytest.mark.parametrize("content", [None, 5, ["x"]])
    def test_content_must_be_text(self, env, content):
        owner, docker, *_ = env
        assert refused(owner, content).status == 400 and docker.calls == []

    def test_a_reload_in_progress_is_waited_out(self, env):
        owner, docker, custom, *_ = env
        docker.reloads = [IN_PROGRESS, OK]
        assert save(owner, NEW)["saved"]
        assert execs(docker) == ["reload-rules", "reload-rules", "ruleset-stats"]


class TestFailures:
    def test_suricata_refuses_and_nothing_changes(self, env):
        owner, docker, custom, staging, state = env
        docker.test = (1, REFUSED)
        error = refused(owner)
        assert error.status == 422
        assert error.errors == [
            {"line": 2, "message": "unknown rule keyword 'nosuchkeyword'."}
        ]
        assert (
            str(error)
            == "Suricata refused the rules: unknown rule keyword 'nosuchkeyword'."
        )
        assert (custom / "owner.rules").read_text() == OLD
        assert not (custom / "owner.rules.prev").exists()
        assert not execs(docker)  # no reload
        assert os.listdir(staging) == [] and lock_is_free(state)

    @pytest.mark.parametrize(
        "result",
        [
            (137, ""),  # out of memory at 1 GiB
            (125, "docker: Error response from daemon: invalid mount config"),
            (139, ""),
            (1, ""),  # no Suricata error at all
            (0, "Info: detect: 1 rules successfully loaded, 10 rules failed"),
        ],
    )
    def test_a_test_that_couldnt_run_is_not_a_refusal(self, env, result):
        # P1: only Suricata's own errors are the rules' fault
        owner, docker, custom, *_ = env
        docker.test = result
        error = refused(owner)
        assert error.status == 502 and error.errors == []
        assert (
            str(error)
            == f"Suricata's test couldn't run (exit {result[0]}). Nothing was changed."
        )
        assert (custom / "owner.rules").read_text() == OLD and not execs(docker)

    def test_exit_1_with_errors_off_the_owner_lines_is_still_a_refusal(self, env):
        owner, docker, *_ = env
        docker.test = (
            1,
            "E: detect: something about the ruleset\nE: suricata: Loading signatures failed.",
        )
        error = refused(owner)
        assert error.status == 422
        assert str(error) == "Suricata refused the rules: Loading signatures failed."

    @pytest.mark.parametrize("name", ["bypass", "tls_store", "lua", "filestore"])
    def test_the_analysis_finds_a_forbidden_keyword(self, env, name):
        # S3: Suricata's own reading of the rules, alone; tls_store is what tls.store parses to
        owner, docker, custom, *_ = env
        docker.names = ["content", name]
        error = refused(owner)
        assert error.status == 422
        assert (
            str(error)
            == f'Suricata reads "{name}" in your rules, and it can\'t be used.'
        )
        assert (custom / "owner.rules").read_text() == OLD and not execs(docker)

    def test_a_rule_that_doesnt_load_alone_is_refused(self, env):
        # S3: Lua is off in the analysis run, so a Lua rule is missing from it
        owner, docker, custom, *_ = env
        docker.dropped = 1
        error = refused(owner)
        assert error.status == 422 and str(error).startswith(
            "Only 0 of your 1 rules load on their own in Suricata."
        )
        assert (custom / "owner.rules").read_text() == OLD

    def test_reload_failure_puts_the_previous_rules_back(self, env):
        owner, docker, custom, staging, state = env
        docker.reloads = ['{"message": "busy", "return": "NOK"}', OK]
        error = refused(owner)
        assert error.status == 502
        assert "The previous rules were put back." in str(error)
        assert (custom / "owner.rules").read_text() == OLD
        assert execs(docker) == ["reload-rules", "reload-rules", "ruleset-stats"]
        assert os.listdir(staging) == [] and lock_is_free(state)

    def test_a_timed_out_reload_is_waited_out_before_the_put_back(self, env):
        # P2: after a reload timeout Suricata is still loading the new rules; the put-back's
        # reload answers "in progress" until it ends
        owner, docker, custom, *_ = env
        docker.reloads = [(None, "no answer in 120 s"), IN_PROGRESS, IN_PROGRESS, OK]
        error = refused(owner)
        assert str(error).endswith("The previous rules were put back.")
        assert execs(docker) == ["reload-rules"] * 4 + ["ruleset-stats"]
        assert (custom / "owner.rules").read_text() == OLD

    def test_a_reload_in_progress_for_too_long_gives_up(self, env, monkeypatch):
        owner, docker, custom, *_ = env
        monkeypatch.setattr(orm, "RELOAD_TIMEOUT_S", 0.05)
        monkeypatch.setattr(orm, "RELOAD_RETRY_S", 0.01)
        docker.reloads = [IN_PROGRESS]
        error = refused(owner)
        assert "didn't confirm loading them" in str(error)
        assert (custom / "owner.rules").read_text() == OLD

    def test_failed_rules_after_the_reload_put_the_previous_rules_back(self, env):
        owner, docker, custom, *_ = env
        docker.stats = [STATS_BAD, STATS_OK]
        error = refused(owner)
        assert error.status == 502 and "1 rules failed to load" in str(error)
        assert (custom / "owner.rules").read_text() == OLD

    def test_an_unconfirmed_put_back_says_so(self, env):
        owner, docker, custom, *_ = env
        docker.reloads = ['{"return": "NOK"}']
        assert "didn't confirm loading them" in str(refused(owner))
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
        error = refused(owner)
        assert error.status == 502 and "didn't confirm loading them" in str(error)
        assert (custom / "owner.rules").read_text() == OLD

    def test_timeout_removes_the_container_and_releases_the_locks(self, env):
        owner, docker, custom, staging, state = env
        docker.test = (None, "no answer in 180 s")
        error = refused(owner)
        assert error.status == 500 and "within 180 s" in str(error)
        run = next(c for c in docker.calls if c[1] == "run")
        name = run[run.index("--name") + 1]
        assert docker.calls[-1] == ("docker", "rm", "-f", name)
        assert (custom / "owner.rules").read_text() == OLD
        assert os.listdir(staging) == []
        assert lock_is_free(state) and not owner._rules.op_lock.locked()

    def test_a_real_timeout_stops_the_test_and_removes_its_container(
        self, env, tmp_path, monkeypatch
    ):
        # P5: the real _run against a docker that never answers; no text is matched
        owner, docker, custom, staging, state = env
        bin_dir, calls = tmp_path / "bin", tmp_path / "calls"
        bin_dir.mkdir()
        (bin_dir / "docker").write_text(
            f'#!/bin/sh\necho "$1 $2 $3" >> "{calls}"\n[ "$1" = run ] && exec sleep 30\nexit 0\n'
        )
        (bin_dir / "docker").chmod(0o755)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setattr(orm, "TEST_TIMEOUT_S", 0.5)

        async def real_for_the_test(*cmd, timeout):
            run = etpro._run if cmd[1] in ("run", "rm") else docker
            return await run(*cmd, timeout=timeout)

        monkeypatch.setattr(orm, "_run", real_for_the_test)
        started = time.monotonic()
        error = refused(owner)
        assert error.status == 500 and time.monotonic() - started < 10
        assert "rm -f nettap-sv-" in calls.read_text()
        assert (custom / "owner.rules").read_text() == OLD
        assert os.listdir(staging) == [] and lock_is_free(state)

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
        error = refused(owner)
        assert error.status == 409 and "deploy-detection-slice3.sh" in str(error)
        assert not [c for c in docker.calls if c[1] == "run"]
        assert (custom / "owner.rules").read_text() == OLD

    def test_an_interrupted_save_leaves_no_extra_rules_file(self, env, monkeypatch):
        owner, docker, custom, *_ = env
        real_replace = os.replace
        target = str(custom / "owner.rules")

        def crash(src, dst):
            if dst == target:
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
        assert refused(owner).status == 502
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


def test_file_work_and_the_check_run_off_the_event_loop(env, monkeypatch):
    # P4: the loop thread only waits; validate, the reads, the writes and the clean-up are on workers
    owner, *_ = env
    loop_thread, seen = threading.get_ident(), {}

    def on_a_worker(name, fn):
        def wrapped(*args, **kwargs):
            seen.setdefault(name, set()).add(threading.get_ident())
            return fn(*args, **kwargs)

        return wrapped

    monkeypatch.setattr(orm, "validate", on_a_worker("validate", orm.validate))
    monkeypatch.setattr(
        orm, "write_file_atomic", on_a_worker("write", orm.write_file_atomic)
    )
    monkeypatch.setattr(OwnerRules, "_read", on_a_worker("read", OwnerRules._read))
    monkeypatch.setattr(
        OwnerRules, "_clean_stale", on_a_worker("clean", OwnerRules._clean_stale)
    )
    monkeypatch.setattr(shutil, "rmtree", on_a_worker("rmtree", shutil.rmtree))
    save(owner, NEW)
    assert set(seen) == {"validate", "write", "read", "clean", "rmtree"}
    assert all(loop_thread not in threads for threads in seen.values())


def test_logs_carry_counts_never_rule_text(env, caplog):
    owner, docker, *_ = env
    caplog.set_level(logging.DEBUG)
    save(owner, NEW)
    docker.test = (1, REFUSED)
    refused(owner)
    docker.test, docker.reloads = None, ['{"return": "NOK"}']
    refused(owner)
    assert "Owner rules" in caplog.text
    assert (
        "secret-rule-text" not in caplog.text and "nettap-selftest" not in caplog.text
    )


class TestAnalysis:
    def test_suricatas_own_analysis_of_the_quoted_semicolon_rule(self):
        out = PASSED + "\n" + ANALYSED_BYPASS
        assert analysis_problem(out, 1) == (
            'Suricata reads "bypass" in your rules, and it can\'t be used.'
        )

    def test_a_clean_analysis(self):
        clean = ANALYSED_BYPASS.replace('"bypass"]', '"x"]').replace(
            '{"name":"bypass"}', '{"name":"content"}'
        )
        assert analysis_problem(PASSED + "\n" + clean, 1) is None
        assert analysis_problem(PASSED, 0) is None

    def test_only_json_lines_with_an_id_count(self):
        out = "\n".join(
            [PASSED, "{not json", '{"no": "id"}', ' {"id": 5}', '{"id": 1000001}']
        )
        assert analysis_problem(out, 1) is None
        assert analysis_problem(out, 2).startswith("Only 1 of your 2 rules")


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
        + '\nE: detect-parse: no terminating ";" found\n'
        + (
            'E: detect: error parsing signature "x" from file /opt/suricata/rules/custom/owner.rules at line 7'
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
