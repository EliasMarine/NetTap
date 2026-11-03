"""
Tests for daemon/services/dhcp_gateway_net.py

Pure helpers only: subnet and interface validation, address math, the
firewall rule list, dnsmasq arguments, the boot file renderers and lease
parsing. No I/O.
"""

import os
import subprocess
import sys

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services.dhcp_gateway_net import (
    HOST_UNIT_PATH,
    RULE_COMMENT,
    BootDirs,
    boot_files,
    boot_paths,
    capture_filter,
    dnsmasq_args,
    firewall_rules,
    gateway_cidr,
    gateway_ip,
    parse_leases,
    pool_range,
    render_firewall_script,
    render_netplan,
    render_sysctl,
    render_systemd_unit,
    validate_interface_name,
    validate_subnet,
)


class TestValidateSubnet:
    @pytest.mark.parametrize(
        "cidr",
        ["10.77.0.0/24", "172.16.0.0/16", "192.168.200.0/28", "10.0.0.0/16"],
    )
    def test_accepts_private_networks(self, cidr):
        assert validate_subnet(cidr) == cidr

    def test_rejects_surrounding_whitespace(self):
        # Strict: a caller that reuses its own string must not keep the junk
        with pytest.raises(ValueError):
            validate_subnet(" 10.77.0.0/24")

    @pytest.mark.parametrize(
        "cidr, fragment",
        [
            ("10.77.0.5/24", "network address"),  # host bits set
            ("8.8.8.0/24", "not a private subnet"),
            ("100.64.0.0/24", "not a private subnet"),  # CGNAT is not RFC1918
            ("169.254.0.0/24", "not a private subnet"),
            ("10.0.0.0/8", "/8 prefix"),
            ("10.77.0.0/29", "/29 prefix"),
            ("10.77.0.0", "not a subnet"),
            ("10.77.0.0/33", "invalid prefix"),
            ("not-a-subnet/24", "not a valid subnet"),
            ("10.77.0.0/24\n", "invalid prefix"),
            ("", "not a subnet"),
        ],
    )
    def test_rejects_with_plain_message(self, cidr, fragment):
        with pytest.raises(ValueError, match=fragment):
            validate_subnet(cidr)

    def test_rejects_non_string(self):
        with pytest.raises(ValueError):
            validate_subnet(None)


class TestValidateInterfaceName:
    @pytest.mark.parametrize("name", ["enp1s0", "eth0.10", "wlp2s0_x", "a", "x" * 15])
    def test_accepts_valid(self, name):
        assert validate_interface_name(name) == name

    @pytest.mark.parametrize(
        "name",
        ["", "x" * 16, "eth0\n", "eth 0", "eth0;rm", "../etc", ".", "..", "-j", None],
    )
    def test_rejects_invalid(self, name):
        with pytest.raises(ValueError, match="not a valid network interface name"):
            validate_interface_name(name)


class TestAddressMath:
    def test_gateway_ip_is_first_host(self):
        assert gateway_ip("10.77.0.0/24") == "10.77.0.1"
        assert gateway_cidr("10.77.0.0/24") == "10.77.0.1/24"

    def test_pool_range_24(self):
        assert pool_range("10.77.0.0/24") == ("10.77.0.10", "10.77.0.254")

    def test_pool_range_smallest_allowed(self):
        assert pool_range("192.168.50.16/28") == ("192.168.50.26", "192.168.50.30")

    def test_pool_range_16(self):
        assert pool_range("172.20.0.0/16") == ("172.20.0.10", "172.20.255.254")

    def test_capture_filter(self):
        assert (
            capture_filter("10.77.0.0/24")
            == "net 10.77.0.0/24 or udp port 67 or udp port 68"
        )

    def test_capture_filter_validates(self):
        with pytest.raises(ValueError):
            capture_filter("10.77.0.0/24 or host 1.2.3.4")


class TestFirewallRules:
    def test_rules_match_design(self):
        tag = ("-m", "comment", "--comment", "nettap-dhcp-gateway")
        assert firewall_rules("10.77.0.0/24", "enp1s0") == [
            (
                "filter",
                "DOCKER-USER",
                "-I",
                ("-i", "enp1s0", "-o", "enp1s0", "-s", "10.77.0.0/24",
                 *tag, "-j", "ACCEPT"),
            ),
            (
                "filter",
                "DOCKER-USER",
                "-I",
                (
                    "-i", "enp1s0", "-o", "enp1s0", "-d", "10.77.0.0/24",
                    "-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED",
                    *tag, "-j", "ACCEPT",
                ),
            ),
            (
                "nat",
                "POSTROUTING",
                "-I",
                ("-o", "enp1s0", "-s", "10.77.0.0/24", "!", "-d", "10.77.0.0/24",
                 *tag, "-j", "MASQUERADE"),
            ),
            (
                "filter",
                "OUTPUT",
                "-I",
                ("-o", "enp1s0", "-p", "icmp", "--icmp-type", "redirect",
                 *tag, "-j", "DROP"),
            ),
        ]  # fmt: skip

    def test_docker_user_rules_pinned_to_one_armed_path(self):
        """No DOCKER-USER rule may lack -o: subnet devices must not reach other NICs."""
        docker_user = [
            args
            for _, chain, _, args in firewall_rules("10.77.0.0/24", "enp1s0")
            if chain == "DOCKER-USER"
        ]
        assert len(docker_user) == 2
        for args in docker_user:
            assert args[args.index("-i") + 1] == "enp1s0"
            assert args[args.index("-o") + 1] == "enp1s0"

    def test_every_rule_is_tagged(self):
        for _, _, _, args in firewall_rules("10.77.0.0/24", "enp1s0"):
            assert RULE_COMMENT in args

    def test_rejects_bad_inputs(self):
        with pytest.raises(ValueError):
            firewall_rules("10.77.0.0/24", "eth0 -j ACCEPT")
        with pytest.raises(ValueError):
            firewall_rules("0.0.0.0/0", "enp1s0")


class TestDnsmasqArgs:
    def test_exact_args(self):
        assert dnsmasq_args(
            "enp1s0",
            "10.77.0.0/24",
            "192.168.1.1",
            "/var/lib/nettap/dhcp/dnsmasq.leases",
        ) == [
            "dnsmasq",
            "--keep-in-foreground",
            "--port=0",
            "--conf-file=/dev/null",
            "--pid-file",
            "--user=nobody",
            "--group=nogroup",
            "--interface=enp1s0",
            "--except-interface=lo",
            "--bind-interfaces",
            "--dhcp-authoritative",
            "--dhcp-range=10.77.0.10,10.77.0.254,255.255.255.0,1h",
            "--dhcp-option=option:router,10.77.0.1",
            "--dhcp-option=option:dns-server,192.168.1.1",
            "--dhcp-leasefile=/var/lib/nettap/dhcp/dnsmasq.leases",
            "--log-facility=-",
        ]

    def test_rejects_bad_dns(self):
        with pytest.raises(ValueError):
            dnsmasq_args("enp1s0", "10.77.0.0/24", "192.168.1.1,8.8.8.8", "/x")


class TestRenderers:
    def test_netplan(self):
        text = render_netplan(
            "enp1s0", "192.168.1.50/24", "192.168.1.1", "10.77.0.1/24"
        )
        assert "    enp1s0:\n      dhcp4: false\n" in text
        assert "        - 192.168.1.50/24\n        - 10.77.0.1/24\n" in text
        assert "        - to: default\n          via: 192.168.1.1\n" in text
        assert (
            "      nameservers:\n        addresses:\n          - 192.168.1.1\n" in text
        )

    def test_netplan_rejects_bad_values(self):
        with pytest.raises(ValueError):
            render_netplan(
                "enp1s0", "192.168.1.50/24\n  evil: 1", "192.168.1.1", "10.77.0.1/24"
            )
        with pytest.raises(ValueError):
            render_netplan("enp1s0", "192.168.1.50/24", "router", "10.77.0.1/24")

    def test_sysctl(self):
        text = render_sysctl("eth0.10")
        assert "net.ipv4.ip_forward = 1" in text
        assert "net.ipv4.conf.all.send_redirects = 0" in text
        assert "net.ipv4.conf.default.send_redirects = 0" in text
        # Slash form so the VLAN dot isn't read as a key separator
        assert "net/ipv4/conf/eth0.10/send_redirects = 0" in text

    def test_systemd_unit(self):
        text = render_systemd_unit()
        assert "Type=oneshot" in text
        assert "After=docker.service" in text
        assert "Wants=docker.service" in text
        assert "ExecStart=/etc/nettap/dhcp-gateway-firewall.sh" in text
        assert "WantedBy=multi-user.target" in text

    def test_firewall_script_structure(self):
        text = render_firewall_script("10.77.0.0/24", "enp1s0")
        assert text.startswith("#!/bin/sh\n")
        assert "while ! iptables -w -S DOCKER-USER" in text
        assert '[ "$i" -ge 60 ]' in text
        # -C before add, and never fail the unit
        assert 'if ! iptables -w -t "$table" -C "$chain" "$@"' in text
        assert text.rstrip().endswith("exit 0")
        assert "set -e" not in text
        assert text.count("add_rule filter DOCKER-USER -I ") == 2
        # Boot script uses the same pinned specs as runtime
        assert text.count("add_rule filter DOCKER-USER -I -i enp1s0 -o enp1s0 ") == 2
        assert (
            "add_rule nat POSTROUTING -I -o enp1s0 -s 10.77.0.0/24 '!' -d 10.77.0.0/24"
            in text
        )
        assert (
            "add_rule filter OUTPUT -I -o enp1s0 -p icmp --icmp-type redirect" in text
        )

    def test_firewall_script_is_valid_sh(self):
        text = render_firewall_script("10.77.0.0/24", "enp1s0")
        result = subprocess.run(
            ["sh", "-n"], input=text, text=True, capture_output=True
        )
        assert result.returncode == 0, result.stderr

    def test_firewall_script_runs_with_fake_iptables(self, tmp_path):
        """Exercise the script: missing rules are added once, present ones skipped."""
        log = tmp_path / "calls.log"
        fake = tmp_path / "iptables"
        # -S succeeds; -C succeeds only for the nat rule; adds are logged
        fake.write_text(
            "#!/bin/sh\n"
            f'echo "$*" >> {log}\n'
            'case "$*" in\n'
            '  *" -C POSTROUTING "*) exit 0 ;;\n'
            '  *" -C "*) exit 1 ;;\n'
            "esac\n"
            "exit 0\n"
        )
        fake.chmod(0o755)
        script = render_firewall_script("10.77.0.0/24", "enp1s0").replace(
            "PATH=/usr/sbin:/usr/bin:/sbin:/bin", f"PATH={tmp_path}:/usr/bin:/bin"
        )
        result = subprocess.run(["sh", "-c", script], capture_output=True, text=True)
        assert result.returncode == 0
        calls = log.read_text().splitlines()
        adds = [c for c in calls if " -I " in c]
        assert len(adds) == 3  # the nat rule already existed
        assert not any("POSTROUTING" in c for c in adds)

    def test_firewall_script_never_fails(self, tmp_path):
        """Every iptables call failing still exits 0."""
        fake = tmp_path / "iptables"
        fake.write_text("#!/bin/sh\nexit 1\n")
        fake.chmod(0o755)
        fake_sleep = tmp_path / "sleep"
        fake_sleep.write_text("#!/bin/sh\nexit 0\n")
        fake_sleep.chmod(0o755)
        script = render_firewall_script("10.77.0.0/24", "enp1s0").replace(
            "PATH=/usr/sbin:/usr/bin:/sbin:/bin", f"PATH={tmp_path}:/usr/bin:/bin"
        )
        result = subprocess.run(["sh", "-c", script], capture_output=True, text=True)
        assert result.returncode == 0
        assert "DOCKER-USER chain not found after 60s" in result.stderr


class TestBootFiles:
    def test_paths_and_modes(self):
        dirs = BootDirs(netplan="/n", sysctl="/s", etc="/e", systemd="/u")
        files = boot_files(
            dirs, "enp1s0", "10.77.0.0/24", "192.168.1.50/24", "192.168.1.1"
        )
        assert [(p, m) for p, _, m in files] == [
            ("/n/90-nettap-dhcp-gateway.yaml", 0o600),
            ("/s/99-nettap-dhcp-gateway.conf", 0o644),
            ("/e/dhcp-gateway-firewall.sh", 0o755),
            ("/u/nettap-dhcp-gateway.service", 0o644),
        ]

    def test_boot_paths_include_wants_link_and_skip_unset(self):
        dirs = BootDirs(netplan="", sysctl="/s", etc="/e", systemd="/u")
        assert boot_paths(dirs) == [
            "/s/99-nettap-dhcp-gateway.conf",
            "/e/dhcp-gateway-firewall.sh",
            "/u/nettap-dhcp-gateway.service",
            "/u/multi-user.target.wants/nettap-dhcp-gateway.service",
        ]

    def test_host_unit_path(self):
        assert HOST_UNIT_PATH == "/etc/systemd/system/nettap-dhcp-gateway.service"


class TestParseLeases:
    def test_parses_dnsmasq_format(self):
        text = (
            "1793389200 aa:bb:cc:dd:ee:ff 10.77.0.23 pixel-8 01:aa:bb:cc:dd:ee:ff\n"
            "1793389300 11:22:33:44:55:66 10.77.0.24 * *\n"
        )
        assert parse_leases(text) == [
            {"mac": "aa:bb:cc:dd:ee:ff", "ip": "10.77.0.23", "hostname": "pixel-8", "expires": 1793389200},
            {"mac": "11:22:33:44:55:66", "ip": "10.77.0.24", "hostname": "", "expires": 1793389300},
        ]  # fmt: skip

    def test_skips_malformed_and_duid_lines(self):
        text = (
            "duid 00:01:00:01:2c:aa\n"
            "garbage\n"
            "notanumber aa:bb:cc:dd:ee:ff 10.77.0.2 host *\n"
            "1793389200 aa:bb:cc:dd:ee:ff not-an-ip host *\n"
            "\n"
            "1793389200 AA:BB:CC:DD:EE:01 10.77.0.30 tv *\n"
        )
        leases = parse_leases(text)
        assert len(leases) == 1
        assert leases[0]["mac"] == "aa:bb:cc:dd:ee:01"

    def test_empty(self):
        assert parse_leases("") == []
