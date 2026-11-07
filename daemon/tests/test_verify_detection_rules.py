"""NET-191 slice 2: the rules-driven fixtures and the staged-rules gate in verify_detection.py."""

import base64
import importlib.util
import json
from pathlib import Path

_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "remote" / "verify_detection.py"
)
_spec = importlib.util.spec_from_file_location("verify_detection", _PATH)
vd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vd)


def _ipfire(category: str, sid: int, dataset: str, active: bool = True) -> str:
    rule = (
        f'alert dns $HOME_NET any -> any any (msg:"IPFire DBL [{category}] Blocked DNS Query"; '
        f"dns.query; dataset:isset,ipfire-{category.lower()},type string,load {dataset}; "
        f"classtype:bad-unknown; sid:{sid}; rev:1;)\n"
    )
    return rule if active else "# " + rule


STALKER = (
    'alert dns $HOME_NET any -> any any (msg:"PTS STALKERWARE copy9 (dns)"; '
    'dns.query; content:"copy9.com"; depth:9; nocase; endswith; sid:3600001; rev:1;)\n'
)


def _b64(*values: str) -> str:
    return "".join(base64.b64encode(v.encode()).decode() + "\n" for v in values)


def _ruleset(tmp_path, extra: str = "", datasets: bool = True) -> str:
    """Malware and Phishing on, DoH off (as SURICATA_DISABLE_SIDS leaves it), Echap and SSLBL on."""
    tmp_path.mkdir(exist_ok=True)
    rules = (
        _ipfire("Malware", 12001201, "datasets/aa.txt")
        + _ipfire("Phishing", 12001901, "/var/lib/suricata/rules/datasets/bb.txt")
        + _ipfire("DoH", 12000501, "datasets/cc.txt", active=False)
        + STALKER
        + 'alert tls any any -> any any (msg:"SSLBL: Malicious SSL certificate detected"; sid:902202001; rev:1;)\n'
        + extra
    )
    (tmp_path / "suricata.rules").write_text(rules)
    if datasets:
        (tmp_path / "datasets").mkdir()
        # a wildcard and a bare TLD first: not usable as a query name, so the next one is taken
        (tmp_path / "datasets" / "aa.txt").write_text(
            "!!notbase64\n" + _b64("*.x.example", "com", "bad-one.example")
        )
        (tmp_path / "datasets" / "bb.txt").write_text(_b64("phish.example"))
        (tmp_path / "datasets" / "cc.txt").write_text(_b64("dns.quad9.net"))
    return str(tmp_path)


def _by_name(fixtures: list) -> dict:
    return {f["name"]: f for f in fixtures}


class TestRuleFixtures:
    def test_built_from_the_staged_rules_and_their_datasets(self, tmp_path):
        fx = _by_name(vd.rule_fixtures(_ruleset(tmp_path)))
        assert fx["ipfire-malware"]["domain"] == "bad-one.example"
        assert fx["ipfire-malware"]["expect"] == [
            {"sid": 12001201, "src": vd.HOME_DEVICE, "present": True}
        ]
        assert (
            fx["ipfire-phishing"]["domain"] == "phish.example"
        )  # absolute /var/lib/suricata/rules path
        assert fx["echap-stalkerware"]["domain"] == "copy9.com"
        assert fx["echap-stalkerware"]["expect"][0]["sid"] == 3600001

    def test_the_owners_doh_must_not_fire_any_disabled_category(self, tmp_path):
        fx = _by_name(vd.rule_fixtures(_ruleset(tmp_path)))["ipfire-disabled-doh"]
        assert fx["domain"] == vd.OWN_DOH
        assert fx["expect"] == [
            {"sid": 12000501, "src": vd.HOME_DEVICE, "present": False}
        ]

    def test_skipped_without_a_ruleset_or_the_rule(self, tmp_path):
        assert all("skip" in f for f in vd.rule_fixtures(None))
        (tmp_path / "suricata.rules").write_text(
            'alert ip any any -> any any (msg:"ET X"; sid:2000001; rev:1;)\n'
        )
        fx = vd.rule_fixtures(str(tmp_path))
        assert [f["name"] for f in fx] == [
            "ipfire-malware", "ipfire-phishing", "ipfire-disabled-doh", "echap-stalkerware",
        ]  # fmt: skip
        assert all("skip" in f for f in fx)

    def test_write_fixtures_writes_a_pcap_per_rule_fixture(self, tmp_path):
        rules = _ruleset(tmp_path / "r")
        pcaps = tmp_path / "p"
        pcaps.mkdir()
        vd.write_fixtures(str(pcaps), rules)
        names = {p.stem for p in pcaps.glob("*.pcap")}
        assert {
            "ipfire-malware",
            "ipfire-phishing",
            "ipfire-disabled-doh",
            "echap-stalkerware",
        } <= names
        assert b"bad-one" in (pcaps / "ipfire-malware.pcap").read_bytes()


class TestCheckStaged:
    def test_passes_the_allowlisted_ruleset(self, tmp_path, capsys):
        assert vd.check_staged(_ruleset(tmp_path)) == 0
        out = capsys.readouterr().out
        assert "{'Malware': 1, 'Phishing': 1}" in out
        assert "Echap stalkerware rules active: 1" in out
        assert "abuse.ch SSLBL rules active: 1" in out

    def test_fails_a_category_outside_the_allowlist(self, tmp_path, capsys):
        assert (
            vd.check_staged(
                _ruleset(tmp_path, _ipfire("Advertising", 12000101, "datasets/aa.txt"))
            )
            == 1
        )
        assert (
            "outside the allowlist are active: Advertising" in capsys.readouterr().out
        )

    def test_fails_a_non_dns_rule_of_a_category_outside_the_allowlist(
        self, tmp_path, capsys
    ):
        tls = 'alert tls $HOME_NET any -> any any (msg:"IPFire DBL [Gambling] Blocked TLS Connection"; sid:12000302; rev:1;)\n'
        assert vd.check_staged(_ruleset(tmp_path, tls)) == 1
        assert "outside the allowlist are active: Gambling" in capsys.readouterr().out

    def test_fails_a_missing_category(self, tmp_path, capsys):
        rules = _ruleset(tmp_path)
        text = (
            (tmp_path / "suricata.rules")
            .read_text()
            .replace(
                'alert dns $HOME_NET any -> any any (msg:"IPFire DBL [Phishing]',
                '# alert dns $HOME_NET any -> any any (msg:"IPFire DBL [Phishing]',
            )
        )
        (tmp_path / "suricata.rules").write_text(text)
        assert vd.check_staged(rules) == 1
        assert (
            "IPFire categories missing (the allowlist or the feed changed): Phishing"
            in capsys.readouterr().out
        )

    def test_fails_an_unresolved_dataset(self, tmp_path, capsys):
        assert vd.check_staged(_ruleset(tmp_path, datasets=False)) == 1
        assert "datasets not in the staged rules: " in capsys.readouterr().out

    def test_fails_a_sid_in_the_owner_range(self, tmp_path, capsys):
        extra = 'alert ip any any -> any any (msg:"Feed X"; sid:1000005; rev:1;)\n'
        assert vd.check_staged(_ruleset(tmp_path, extra)) == 1
        assert (
            "SIDs in the owner range 1000000-1999999: 1000005"
            in capsys.readouterr().out
        )

    def test_main_routes_the_new_commands(self, tmp_path):
        assert vd.main(["x", "check-staged", _ruleset(tmp_path)]) == 0
        assert vd.main(["x", "check-staged"]) == 2


def _eve(out: Path, *sids: int) -> str:
    (out / "engine").mkdir(parents=True)
    lines = [
        {"event_type": "alert", "src_ip": "192.168.1.5", "dest_ip": "192.0.2.1",
         "alert": {"signature_id": s, "signature": f"Rule {s}", "metadata": {"signature_severity": ["Major"]}}}
        for s in sids
    ]  # fmt: skip
    (out / "engine" / "eve.json").write_text(
        "".join(json.dumps(e) + "\n" for e in lines)
    )
    return str(out)


def test_diff_sids_lists_what_only_one_ruleset_fires(tmp_path, capsys):
    live = _eve(tmp_path / "live", 2000001, 2000002, 2000002)
    staged = _eve(tmp_path / "staged", 2000002, 3600001, 3600001, 3600001)
    assert vd.main(["x", "diff-sids", live, staged]) == 0
    out = capsys.readouterr().out
    assert "SIDs only with the new rules: 1" in out
    assert "3  3600001  [Major]  Rule 3600001" in out
    assert "SIDs only with the current rules: 1" in out
    assert "2000001" in out.split("only with the current rules")[1]


def test_report_with_rules_checks_the_rule_fixtures(tmp_path, capsys):
    rules = _ruleset(tmp_path / "r")
    out = tmp_path / "o"
    eve_lines = [
        {"event_type": "alert", "src_ip": vd.HOME_DEVICE, "dest_ip": vd.RESOLVER,
         "alert": {"signature_id": sid, "signature": "x", "metadata": {}}}
        for sid in (12001201, 12001901, 3600001, 12000501)
    ]  # fmt: skip
    (out / "engine").mkdir(parents=True)
    (out / "engine" / "eve.json").write_text(
        "".join(json.dumps(e) + "\n" for e in eve_lines)
    )
    (out / "runner-exit").write_text("0\n")
    (out / "engine" / "suricata.log").write_text(
        "1 rule files processed. 5 rules successfully loaded, 0 rules failed\n"
    )
    assert vd.report("fixtures", str(out), rules) == 1
    text = capsys.readouterr().out
    assert "PASS     ipfire-malware" in text
    assert "PASS     echap-stalkerware" in text
    assert (
        "FAIL     ipfire-disabled-doh — sid 12000501 from 192.168.1.50 present" in text
    )


class TestOwnerFixture:
    """NET-191 slice 3: the owner rule self-test, only when check-owner-rules.sh asks for it."""

    def test_off_unless_asked(self, monkeypatch):
        monkeypatch.delenv("NETTAP_OWNER_FIXTURE", raising=False)
        assert vd.owner_fixtures() == []
        monkeypatch.setenv("NETTAP_OWNER_FIXTURE", "yes")
        assert vd.owner_fixtures() == []

    def test_writes_the_self_test_query(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NETTAP_OWNER_FIXTURE", "present")
        vd.write_fixtures(str(tmp_path))
        assert b"nettap-selftest" in (tmp_path / "owner-selftest.pcap").read_bytes()

    def test_matches_the_rule_the_check_script_saves(self):
        script = (_PATH.parent / "check-owner-rules.sh").read_text()
        assert f"sid:{vd.OWNER_TEST_SID};" in script
        assert f'content:"{vd.OWNER_TEST_DOMAIN}"' in script
        assert vd.OWNER_TEST_SID in vd.OWNER_SIDS

    def test_present_and_absent_are_checked(self, tmp_path, monkeypatch, capsys):
        alerts = [{"sid": vd.OWNER_TEST_SID, "src": vd.HOME_DEVICE}]
        monkeypatch.setenv("NETTAP_OWNER_FIXTURE", "present")
        vd.print_fixtures(alerts, str(tmp_path))
        assert "PASS     owner-selftest" in capsys.readouterr().out
        monkeypatch.setenv("NETTAP_OWNER_FIXTURE", "absent")
        assert vd.print_fixtures(alerts, str(tmp_path)) == 1
        assert (
            "FAIL     owner-selftest — sid 1999999 from 192.168.1.50 present"
            in capsys.readouterr().out
        )
