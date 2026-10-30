"""
Tests for daemon/services/dhcp_gateway.py (and its preflight, runtime and
host helper modules).

The host is simulated by FakeHost, which answers the ``ip -j`` / iptables /
ethtool commands sent through ``_run_nsenter`` and keeps addresses, routes and
firewall rules in memory. dnsmasq is a fake and the DHCP probe is mocked, so
no network namespace, raw socket or root access is needed. Persistence files
go to tmp_path.
"""

import asyncio
import json
import os
import stat
import sys
from unittest.mock import AsyncMock, patch

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services import dhcp_gateway, dhcp_gateway_host
from services.capture_config import (
    CaptureConfig,
    load_capture_config,
    save_capture_config,
)
from services.capture_manager import (
    CaptureHealth,
    CaptureManager,
    CaptureMode,
    CaptureStats,
)
from services.dhcp_gateway import DhcpGatewayManager
from services.dhcp_gateway_host import DnsmasqProcess
from services.dhcp_gateway_net import dnsmasq_args, firewall_rules

IFACE = "enp1s0"
SUBNET = "10.77.0.0/24"
UPSTREAM = {"address": "192.168.1.50/24", "gateway": "192.168.1.1"}
PROBE = "services.dhcp_gateway_preflight.probe_dhcp_servers"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeHost:
    """In-memory host network namespace for ``_run_nsenter``."""

    def __init__(self):
        self.addrs = {IFACE: ["192.168.1.50/24"], "docker0": ["172.17.0.1/16"]}
        self.routes = [
            {
                "dst": "default",
                "gateway": "192.168.1.1",
                "dev": IFACE,
                "protocol": "dhcp",
            }
        ]
        self.routes6 = []
        self.slaac = False
        self.backend = "iptables-nft"  # which iptables has DOCKER-USER
        self.rules = set()  # (backend, table, chain, args)
        self.fail = []  # command prefixes that return rc=1
        self.calls = []

    async def run(self, *args):
        self.calls.append(list(args))
        for prefix in self.fail:
            if tuple(args[: len(prefix)]) == prefix:
                return (1, "", "injected failure")
        if args[0] == "ip":
            return self._ip(list(args[1:]))
        if args[0] in ("iptables-nft", "iptables-legacy"):
            return self._iptables(args[0], list(args[1:]))
        if args[0] == "ethtool":
            return (0, "", "")
        return (1, "", "unknown command")

    def _ip(self, a):
        if a[:4] == ["-j", "-4", "addr", "show"]:
            names = [a[5]] if len(a) > 4 else list(self.addrs)
            out = [
                {
                    "ifname": n,
                    "addr_info": [
                        {"family": "inet", "local": c.split("/")[0], "prefixlen": int(c.split("/")[1])}
                        for c in self.addrs.get(n, [])
                    ],
                }
                for n in names
            ]  # fmt: skip
            return (0, json.dumps(out), "")
        if a == ["-j", "-4", "route", "show", "default"]:
            return (0, json.dumps(self.routes), "")
        if a == ["-j", "-6", "route", "show", "default"]:
            return (0, json.dumps(self.routes6), "")
        if a[:4] == ["-j", "-6", "addr", "show"]:
            info = [
                {
                    "family": "inet6",
                    "local": "2001:db8::5",
                    "prefixlen": 64,
                    "dynamic": True,
                }
            ]
            return (
                0,
                json.dumps([{"ifname": a[5], "addr_info": info if self.slaac else []}]),
                "",
            )
        if a[:2] == ["addr", "add"]:
            cidrs = self.addrs.setdefault(a[4], [])
            if a[2] in cidrs:
                return (2, "", "RTNETLINK answers: File exists")
            cidrs.append(a[2])
            return (0, "", "")
        if a[:2] == ["addr", "del"]:
            if a[2] not in self.addrs.get(a[4], []):
                return (2, "", "RTNETLINK answers: Cannot assign requested address")
            self.addrs[a[4]].remove(a[2])
            return (0, "", "")
        if a[:3] == ["route", "add", "default"]:
            self.routes.append({"dst": "default", "gateway": a[4], "dev": a[6]})
            return (0, "", "")
        return (1, "", "unsupported ip command")

    def _iptables(self, backend, a):
        assert a[0] == "-w", "every iptables call must wait for the xtables lock"
        if a[1:] == ["-S", "DOCKER-USER"]:
            return (0, "", "") if backend == self.backend else (1, "", "No chain")
        assert a[1] == "-t"
        table, op, chain, args = a[2], a[3], a[4], tuple(a[5:])
        key = (backend, table, chain, args)
        if op == "-C":
            return (0, "", "") if key in self.rules else (1, "", "Bad rule")
        if op in ("-I", "-A"):
            self.rules.add(key)
            return (0, "", "")
        if op == "-D":
            self.rules.discard(key)
            return (0, "", "")
        return (1, "", "unsupported iptables op")

    def mutations(self):
        """Every call that changes host state."""
        changing = {"add", "del", "-I", "-A", "-D"}
        return [c for c in self.calls if changing & set(c[:5])]


class FakeDnsmasq:
    def __init__(self, fail=False):
        self.running = False
        self.fail = fail
        self.started_args = []
        self.stops = 0

    async def start(self, args, lease_dir):
        if self.running:
            return False
        if self.fail:
            raise RuntimeError("dnsmasq stopped right after starting (exit code 2)")
        self.started_args.append(args)
        self.running = True
        return True

    async def stop(self):
        self.stops += 1
        self.running = False


@pytest.fixture
def env(tmp_path):
    """Directories, sysfs, config file and a manager wired to fakes."""
    dirs = {
        name: tmp_path / name
        for name in ("netplan", "systemd", "sysctl", "etc", "leases")
    }
    for d in dirs.values():
        d.mkdir()
    (dirs["systemd"] / "multi-user.target.wants").mkdir()
    sys_net = tmp_path / "sys"
    nic = sys_net / IFACE
    (nic / "statistics").mkdir(parents=True)
    for name, value in {
        "operstate": "up",
        "carrier": "1",
        "address": "aa:bb:cc:dd:ee:ff",
        "flags": "0x1103",
        "speed": "2500",
    }.items():
        (nic / name).write_text(value + "\n")
    for name, value in {
        "rx_bytes": 1000,
        "tx_bytes": 2000,
        "rx_packets": 99,
        "tx_packets": 50,
        "rx_dropped": 1,
        "rx_missed_errors": 0,
    }.items():
        (nic / "statistics" / name).write_text(f"{value}\n")
    ip_forward = tmp_path / "ip_forward"
    ip_forward.write_text("1\n")
    config_path = str(dirs["etc"] / "capture-mode.conf")

    class Env:
        pass

    e = Env()
    e.tmp, e.dirs, e.nic, e.ip_forward, e.config_path = (
        tmp_path,
        dirs,
        nic,
        ip_forward,
        config_path,
    )
    e.host = FakeHost()

    def make(config=None, dnsmasq=None):
        cfg = config or CaptureConfig(mode=CaptureMode.DHCP_GATEWAY, interface=IFACE)
        save_capture_config(cfg, config_path)
        mgr = DhcpGatewayManager(
            cfg,
            config_path=config_path,
            netplan_dir=str(dirs["netplan"]),
            systemd_dir=str(dirs["systemd"]),
            sysctl_dir=str(dirs["sysctl"]),
            etc_dir=str(dirs["etc"]),
            lease_dir=str(dirs["leases"]),
            sys_net=str(sys_net),
        )
        mgr._run_nsenter = e.host.run
        mgr._dnsmasq = dnsmasq or FakeDnsmasq()
        mgr.ip_forward_path = str(ip_forward)
        return mgr

    e.make = make
    return e


def _enabled_config():
    return CaptureConfig(
        mode=CaptureMode.DHCP_GATEWAY,
        interface=IFACE,
        dhcp_upstream_address=UPSTREAM["address"],
        dhcp_upstream_gateway=UPSTREAM["gateway"],
        dhcp_enabled=True,
    )


def _run(coro_fn, offers=None, probe_error=None):
    """Run an async scenario with the DHCP probe mocked."""
    mock = AsyncMock(return_value=offers or [], side_effect=probe_error)
    with patch(PROBE, mock):
        return asyncio.run(coro_fn())


def _check(pre, name):
    return next(c for c in pre["checks"] if c["name"] == name)


# ---------------------------------------------------------------------------
# CaptureManager base additions
# ---------------------------------------------------------------------------


class TestCaptureManagerBase:
    def test_dhcp_gateway_mode_value(self):
        assert CaptureMode.DHCP_GATEWAY.value == "dhcp_gateway"
        assert CaptureMode("dhcp_gateway") is CaptureMode.DHCP_GATEWAY

    def test_reconcile_default_is_noop(self):
        class Minimal(CaptureManager):
            async def setup(self):
                return {}

            async def teardown(self):
                return {}

            async def get_health(self):
                return CaptureHealth("bridge", "normal", "br0", True, True)

            def get_capture_interface(self):
                return "br0"

            async def get_stats(self):
                return CaptureStats(capture_interface="br0")

            @property
            def mode(self):
                return CaptureMode.BRIDGE

        assert asyncio.run(Minimal().reconcile()) is None


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


class TestPreflight:
    def test_ready_on_a_clean_host(self, env):
        mgr = env.make()
        pre = _run(mgr.preflight)
        assert pre["ready"] is True
        assert pre["interface"] == IFACE
        assert pre["subnet"] == SUBNET
        assert pre["gateway_ip"] == "10.77.0.1"
        assert pre["upstream"] == UPSTREAM
        assert pre["subnet_conflicts"] == []
        assert pre["other_dhcp_servers"] == []
        assert pre["ipv6_router_advertisements"] is False
        assert pre["ip_forward"] is True
        assert pre["firewall_backend"] == "iptables-nft"
        assert [c["name"] for c in pre["checks"]] == [
            "interface_up",
            "upstream_detected",
            "no_other_dhcp",
            "no_subnet_conflict",
            "ip_forward",
            "firewall_backend",
            "ipv6_bypass",
        ]
        assert all(c["passed"] for c in pre["checks"])
        assert [c["blocking"] for c in pre["checks"]] == [True] * 6 + [False]

    def test_preflight_changes_nothing(self, env):
        mgr = env.make()
        _run(mgr.preflight)
        assert env.host.mutations() == []

    def test_other_dhcp_server_blocks(self, env):
        mgr = env.make()
        offers = [{"server_ip": "192.168.1.1", "offered_ip": "192.168.1.77"}]
        pre = _run(mgr.preflight, offers=offers)
        assert pre["ready"] is False
        assert pre["other_dhcp_servers"] == offers
        check = _check(pre, "no_other_dhcp")
        assert check["passed"] is False and check["blocking"] is True
        assert (
            check["message"] == "Your router's DHCP server is still on (192.168.1.1)."
        )

    def test_probe_uses_nic_mac(self, env):
        mgr = env.make()
        mock = AsyncMock(return_value=[])
        with patch(PROBE, mock):
            asyncio.run(mgr.preflight())
        mock.assert_awaited_once_with(IFACE, "aa:bb:cc:dd:ee:ff")

    def test_own_dhcp_server_is_ignored(self, env):
        mgr = env.make()
        offers = [{"server_ip": "10.77.0.1", "offered_ip": "10.77.0.50"}]
        pre = _run(mgr.preflight, offers=offers)
        assert pre["other_dhcp_servers"] == []
        assert pre["ready"] is True

    def test_probe_failure_blocks(self, env):
        mgr = env.make()
        pre = _run(
            mgr.preflight, probe_error=PermissionError(1, "Operation not permitted")
        )
        check = _check(pre, "no_other_dhcp")
        assert check["passed"] is False
        assert "could not check" in check["message"]
        assert pre["ready"] is False

    def test_subnet_conflict_blocks(self, env):
        env.host.addrs["br-abc"] = ["10.77.5.1/16"]
        mgr = env.make()
        pre = _run(mgr.preflight)
        assert pre["subnet_conflicts"] == [
            {"interface": "br-abc", "network": "10.77.0.0/16"}
        ]
        assert _check(pre, "no_subnet_conflict")["passed"] is False
        assert pre["ready"] is False

    def test_own_gateway_address_is_not_a_conflict(self, env):
        env.host.addrs[IFACE].append("10.77.0.1/24")
        mgr = env.make()
        pre = _run(mgr.preflight)
        assert pre["subnet_conflicts"] == []
        assert pre["upstream"] == UPSTREAM  # gateway address is not the upstream

    def test_no_default_route_means_no_upstream(self, env):
        env.host.routes = []
        mgr = env.make()
        pre = _run(mgr.preflight)
        assert pre["upstream"] is None
        assert _check(pre, "upstream_detected")["passed"] is False
        assert pre["ready"] is False

    def test_upstream_picks_address_in_gateway_network(self, env):
        env.host.addrs[IFACE] = ["172.30.0.9/24", "192.168.1.50/24"]
        mgr = env.make()
        assert _run(mgr.preflight)["upstream"] == UPSTREAM

    def test_falls_back_to_legacy_backend(self, env):
        env.host.backend = "iptables-legacy"
        mgr = env.make()
        pre = _run(mgr.preflight)
        assert pre["firewall_backend"] == "iptables-legacy"
        probes = [c[0] for c in env.host.calls if c[1:] == ["-w", "-S", "DOCKER-USER"]]
        assert probes == ["iptables-nft", "iptables-legacy"]

    def test_no_backend_blocks(self, env):
        env.host.backend = None
        mgr = env.make()
        pre = _run(mgr.preflight)
        assert pre["firewall_backend"] is None
        assert _check(pre, "firewall_backend")["passed"] is False
        assert pre["ready"] is False

    def test_ip_forward_off_blocks(self, env):
        env.ip_forward.write_text("0\n")
        mgr = env.make()
        pre = _run(mgr.preflight)
        assert pre["ip_forward"] is False
        assert pre["ready"] is False

    def test_interface_down_blocks(self, env):
        (env.nic / "operstate").write_text("down\n")
        mgr = env.make()
        pre = _run(mgr.preflight)
        assert _check(pre, "interface_up")["passed"] is False
        assert pre["ready"] is False

    @pytest.mark.parametrize("ra", ["route", "slaac"])
    def test_ipv6_only_warns(self, env, ra):
        if ra == "route":
            env.host.routes6 = [
                {"dst": "default", "gateway": "fe80::1", "dev": IFACE, "protocol": "ra"}
            ]
        else:
            env.host.slaac = True
        mgr = env.make()
        pre = _run(mgr.preflight)
        assert pre["ipv6_router_advertisements"] is True
        check = _check(pre, "ipv6_bypass")
        assert check["passed"] is False and check["blocking"] is False
        assert pre["ready"] is True

    @pytest.mark.parametrize(
        "cfg",
        [
            CaptureConfig(mode=CaptureMode.DHCP_GATEWAY, interface="eth0;reboot"),
            CaptureConfig(
                mode=CaptureMode.DHCP_GATEWAY, interface=IFACE, dhcp_subnet="8.8.8.0/24"
            ),
        ],
    )
    def test_invalid_config_fails_without_touching_host(self, env, cfg):
        mgr = env.make(config=cfg)
        mock = AsyncMock(return_value=[])
        with patch(PROBE, mock):
            pre = asyncio.run(mgr.preflight())
        assert pre["ready"] is False
        assert all(not c["passed"] for c in pre["checks"])
        assert env.host.calls == []
        mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# Enable
# ---------------------------------------------------------------------------


class TestEnable:
    def test_enable_applies_everything(self, env):
        mgr = env.make()
        ok, body = _run(mgr.enable)
        assert ok is True
        assert body["routing_active"] is True
        assert body["dhcp_enabled"] is True
        assert body["dhcp_server_running"] is True
        assert body["upstream"] == UPSTREAM
        assert body["issues"] == []

        assert "10.77.0.1/24" in env.host.addrs[IFACE]
        expected = {
            ("iptables-nft", t, c, args)
            for t, c, _, args in firewall_rules(SUBNET, IFACE)
        }
        assert env.host.rules == expected
        assert mgr._dnsmasq.started_args == [
            dnsmasq_args(
                IFACE, SUBNET, "192.168.1.1", str(env.dirs["leases"] / "dnsmasq.leases")
            )
        ]

        saved = load_capture_config(env.config_path)
        assert saved.dhcp_upstream_address == "192.168.1.50/24"
        assert saved.dhcp_upstream_gateway == "192.168.1.1"
        assert saved.dhcp_enabled is True
        assert saved.mode == CaptureMode.DHCP_GATEWAY

    def test_rules_checked_before_insert(self, env):
        mgr = env.make()
        _run(mgr.enable)
        ipt = [
            c
            for c in env.host.calls
            if c[0] == "iptables-nft" and c[1:3] == ["-w", "-t"]
        ]
        for table, chain, action, args in firewall_rules(SUBNET, IFACE):
            check = ["iptables-nft", "-w", "-t", table, "-C", chain, *args]
            add = ["iptables-nft", "-w", "-t", table, action, chain, *args]
            assert ipt.index(check) < ipt.index(add)

    def test_enable_is_idempotent(self, env):
        mgr = env.make()
        _run(mgr.enable)
        env.host.calls.clear()
        ok, _ = _run(mgr.enable)
        assert ok is True
        assert len(env.host.rules) == 4
        assert env.host.mutations() == []  # nothing added twice
        assert env.host.addrs[IFACE].count("10.77.0.1/24") == 1

    def test_gro_lro_turned_off(self, env):
        mgr = env.make()
        _run(mgr.enable)
        assert ["ethtool", "-K", IFACE, "gro", "off", "lro", "off"] in env.host.calls

    def test_ethtool_failure_is_only_a_warning(self, env):
        env.host.fail.append(("ethtool",))
        mgr = env.make()
        ok, _ = _run(mgr.enable)
        assert ok is True

    def test_writes_boot_files(self, env):
        mgr = env.make()
        _run(mgr.enable)
        netplan = env.dirs["netplan"] / "90-nettap-dhcp-gateway.yaml"
        sysctl = env.dirs["sysctl"] / "99-nettap-dhcp-gateway.conf"
        script = env.dirs["etc"] / "dhcp-gateway-firewall.sh"
        unit = env.dirs["systemd"] / "nettap-dhcp-gateway.service"
        assert stat.S_IMODE(netplan.stat().st_mode) == 0o600
        assert stat.S_IMODE(sysctl.stat().st_mode) == 0o644
        assert stat.S_IMODE(script.stat().st_mode) == 0o755
        assert stat.S_IMODE(unit.stat().st_mode) == 0o644
        assert "- 192.168.1.50/24" in netplan.read_text()
        assert "- 10.77.0.1/24" in netplan.read_text()
        assert "net.ipv4.ip_forward = 1" in sysctl.read_text()
        assert "MASQUERADE" in script.read_text()
        assert "ExecStart=/etc/nettap/dhcp-gateway-firewall.sh" in unit.read_text()

    def test_wants_symlink_targets_host_path(self, env):
        mgr = env.make()
        _run(mgr.enable)
        link = (
            env.dirs["systemd"]
            / "multi-user.target.wants"
            / "nettap-dhcp-gateway.service"
        )
        assert link.is_symlink()
        assert os.readlink(link) == "/etc/systemd/system/nettap-dhcp-gateway.service"

    def test_replaces_dangling_symlink(self, env):
        link = (
            env.dirs["systemd"]
            / "multi-user.target.wants"
            / "nettap-dhcp-gateway.service"
        )
        os.symlink("/nonexistent/old", link)
        mgr = env.make()
        ok, _ = _run(mgr.enable)
        assert ok is True
        assert os.readlink(link) == "/etc/systemd/system/nettap-dhcp-gateway.service"

    def test_refused_when_other_dhcp_answers(self, env):
        mgr = env.make()
        offers = [{"server_ip": "192.168.1.1", "offered_ip": "192.168.1.77"}]
        ok, body = _run(mgr.enable, offers=offers)
        assert ok is False
        assert "checks" in body
        assert "192.168.1.1" in body["error"]
        self._assert_untouched(env, mgr)

    @pytest.mark.parametrize(
        "problem", ["conflict", "no_upstream", "no_backend", "probe_error"]
    )
    def test_refused_on_blocking_failures(self, env, problem):
        probe_error = None
        if problem == "conflict":
            env.host.addrs["br-x"] = ["10.77.0.0/16"]
        elif problem == "no_upstream":
            env.host.routes = []
        elif problem == "no_backend":
            env.host.backend = None
        else:
            probe_error = OSError(19, "No such device")
        mgr = env.make()
        ok, body = _run(mgr.enable, probe_error=probe_error)
        assert ok is False
        assert set(body) == {"error", "checks"}
        self._assert_untouched(env, mgr)

    def test_refused_when_host_dirs_not_mounted(self, env):
        mgr = env.make()
        mgr._dirs = mgr._dirs._replace(netplan="")
        ok, body = _run(mgr.enable)
        assert ok is False
        assert "checks" not in body
        assert "reboot" in body["error"]
        self._assert_untouched(env, mgr)

    def test_rollback_when_a_rule_fails(self, env):
        env.host.fail.append(("iptables-nft", "-w", "-t", "nat", "-I"))
        mgr = env.make()
        ok, body = _run(mgr.enable)
        assert ok is False
        assert "checks" not in body
        assert "nat/POSTROUTING" in body["error"]
        # The DOCKER-USER rules and gateway address added before the failure are gone
        assert env.host.rules == set()
        assert "10.77.0.1/24" not in env.host.addrs[IFACE]
        self._assert_untouched(env, mgr)

    def test_rollback_when_dnsmasq_fails(self, env):
        mgr = env.make(dnsmasq=FakeDnsmasq(fail=True))
        ok, body = _run(mgr.enable)
        assert ok is False
        assert "dnsmasq" in body["error"]
        assert env.host.rules == set()
        assert "10.77.0.1/24" not in env.host.addrs[IFACE]
        self._assert_untouched(env, mgr)

    def test_rollback_keeps_preexisting_gateway_address(self, env):
        env.host.addrs[IFACE].append("10.77.0.1/24")
        mgr = env.make(dnsmasq=FakeDnsmasq(fail=True))
        ok, _ = _run(mgr.enable)
        assert ok is False
        assert "10.77.0.1/24" in env.host.addrs[IFACE]

    def test_failed_reenable_keeps_existing_gateway(self, env):
        """enable -> disable -> re-enable with dnsmasq failing: only DHCP stays off."""
        mgr = env.make()

        async def scenario():
            await mgr.enable()
            await mgr.disable()
            mgr._dnsmasq.fail = True
            return await mgr.enable()

        ok, body = _run(scenario)
        assert ok is False
        assert "dnsmasq" in body["error"]
        expected = {
            ("iptables-nft", t, c, args)
            for t, c, _, args in firewall_rules(SUBNET, IFACE)
        }
        assert env.host.rules == expected
        assert "10.77.0.1/24" in env.host.addrs[IFACE]
        for path in (
            env.dirs["netplan"] / "90-nettap-dhcp-gateway.yaml",
            env.dirs["sysctl"] / "99-nettap-dhcp-gateway.conf",
            env.dirs["etc"] / "dhcp-gateway-firewall.sh",
            env.dirs["systemd"] / "nettap-dhcp-gateway.service",
        ):
            assert path.exists(), path
        link = (
            env.dirs["systemd"]
            / "multi-user.target.wants"
            / "nettap-dhcp-gateway.service"
        )
        assert os.readlink(link) == "/etc/systemd/system/nettap-dhcp-gateway.service"
        saved = load_capture_config(env.config_path)
        assert saved.dhcp_upstream_address == "192.168.1.50/24"
        assert saved.dhcp_upstream_gateway == "192.168.1.1"
        assert saved.dhcp_enabled is False
        assert mgr.routing_active is True
        assert mgr._config.dhcp_enabled is False

    def test_rollback_continues_after_a_failing_undo_step(self, env):
        """The config-restore save raising must not stop the remaining undo steps."""
        mgr = env.make(dnsmasq=FakeDnsmasq(fail=True))
        real_save = dhcp_gateway.save_capture_config
        calls = []

        def save_then_fail(config, path=None):
            calls.append(config)
            if len(calls) == 2:  # the rollback's restore of the old config
                raise OSError("disk full")
            return real_save(config, path)

        with patch.object(dhcp_gateway, "save_capture_config", save_then_fail):
            ok, _ = _run(mgr.enable)
        assert ok is False
        assert len(calls) == 2
        assert env.host.rules == set()
        assert "10.77.0.1/24" not in env.host.addrs[IFACE]
        for d in ("netplan", "sysctl"):
            assert list(env.dirs[d].iterdir()) == []
        assert not (env.dirs["etc"] / "dhcp-gateway-firewall.sh").exists()
        assert not (env.dirs["systemd"] / "nettap-dhcp-gateway.service").exists()
        assert list((env.dirs["systemd"] / "multi-user.target.wants").iterdir()) == []

    def _assert_untouched(self, env, mgr):
        """No boot files, config on disk and in memory as before."""
        for d in ("netplan", "sysctl"):
            assert list(env.dirs[d].iterdir()) == []
        assert not (env.dirs["etc"] / "dhcp-gateway-firewall.sh").exists()
        assert not (env.dirs["systemd"] / "nettap-dhcp-gateway.service").exists()
        assert list((env.dirs["systemd"] / "multi-user.target.wants").iterdir()) == []
        saved = load_capture_config(env.config_path)
        assert saved.dhcp_upstream_gateway == ""
        assert saved.dhcp_enabled is False
        assert mgr.routing_active is False
        assert mgr._dnsmasq.running is False


# ---------------------------------------------------------------------------
# Disable / status
# ---------------------------------------------------------------------------


class TestDisableAndStatus:
    def test_disable_keeps_routing(self, env):
        mgr = env.make()

        async def scenario():
            await mgr.enable()
            return await mgr.disable()

        body = _run(scenario)
        assert body["dhcp_enabled"] is False
        assert body["dhcp_server_running"] is False
        assert body["routing_active"] is True
        assert body["upstream"] == UPSTREAM
        assert body["issues"] == []
        assert len(env.host.rules) == 4
        assert "10.77.0.1/24" in env.host.addrs[IFACE]
        assert (env.dirs["netplan"] / "90-nettap-dhcp-gateway.yaml").exists()
        saved = load_capture_config(env.config_path)
        assert saved.dhcp_enabled is False
        assert saved.dhcp_upstream_gateway == "192.168.1.1"

    def test_status_reads_leases(self, env):
        (env.dirs["leases"] / "dnsmasq.leases").write_text(
            "1793389200 aa:bb:cc:dd:ee:ff 10.77.0.23 pixel-8 *\n"
        )
        mgr = env.make()
        body = _run(mgr.status)
        assert body["leases"] == [
            {"mac": "aa:bb:cc:dd:ee:ff", "ip": "10.77.0.23", "hostname": "pixel-8", "expires": 1793389200}
        ]  # fmt: skip
        assert body["routing_active"] is False
        assert body["upstream"] is None
        assert body["gateway_ip"] == "10.77.0.1"

    def test_status_reports_dead_dnsmasq(self, env):
        mgr = env.make(config=_enabled_config())
        env.host.addrs[IFACE].append("10.77.0.1/24")
        for t, c, _, args in firewall_rules(SUBNET, IFACE):
            env.host.rules.add(("iptables-nft", t, c, args))
        body = _run(mgr.status)
        assert body["issues"] == ["The DHCP server is not running."]


# ---------------------------------------------------------------------------
# Reconcile / setup
# ---------------------------------------------------------------------------


class TestReconcile:
    def test_readds_missing_pieces(self, env):
        mgr = env.make(config=_enabled_config())
        env.host.addrs[IFACE] = []
        env.host.routes = []
        _run(mgr.reconcile)
        assert set(env.host.addrs[IFACE]) == {"192.168.1.50/24", "10.77.0.1/24"}
        assert {
            "dst": "default",
            "gateway": "192.168.1.1",
            "dev": IFACE,
        } in env.host.routes
        assert len(env.host.rules) == 4
        assert mgr._dnsmasq.running is True
        ip_adds = [c for c in env.host.calls if c[0] == "ip" and c[2] == "add"]
        # Upstream address before the default route that needs it
        assert ip_adds[0] == ["ip", "addr", "add", "192.168.1.50/24", "dev", IFACE]
        assert ip_adds[1] == [
            "ip",
            "route",
            "add",
            "default",
            "via",
            "192.168.1.1",
            "dev",
            IFACE,
        ]

    def test_readds_only_the_missing_rule(self, env):
        mgr = env.make(config=_enabled_config())
        env.host.addrs[IFACE].append("10.77.0.1/24")
        rules = firewall_rules(SUBNET, IFACE)
        for t, c, _, args in rules[1:]:
            env.host.rules.add(("iptables-nft", t, c, args))
        mgr._dnsmasq.running = True
        _run(mgr.reconcile)
        assert len(env.host.rules) == 4
        adds = [c for c in env.host.calls if "-I" in c]
        assert len(adds) == 1 and "DOCKER-USER" in adds[0]

    def test_healthy_host_needs_no_changes(self, env):
        mgr = env.make(config=_enabled_config())
        env.host.addrs[IFACE].append("10.77.0.1/24")
        for t, c, _, args in firewall_rules(SUBNET, IFACE):
            env.host.rules.add(("iptables-nft", t, c, args))
        mgr._dnsmasq.running = True
        _run(mgr.reconcile)
        assert env.host.mutations() == []

    def test_probes_before_restarting_dnsmasq(self, env):
        mgr = env.make(config=_enabled_config())
        mock = AsyncMock(return_value=[])
        with patch(PROBE, mock):
            asyncio.run(mgr.reconcile())
        mock.assert_awaited_once_with(IFACE, "aa:bb:cc:dd:ee:ff")
        assert mgr._dnsmasq.running is True
        assert load_capture_config(env.config_path).dhcp_enabled is True

    def test_no_probe_while_dnsmasq_runs(self, env):
        mgr = env.make(config=_enabled_config())
        mgr._dnsmasq.running = True
        mock = AsyncMock(return_value=[])
        with patch(PROBE, mock):
            asyncio.run(mgr.reconcile())
        mock.assert_not_awaited()

    def test_other_server_keeps_dnsmasq_off(self, env):
        mgr = env.make(config=_enabled_config())
        offers = [{"server_ip": "192.168.1.1", "offered_ip": "192.168.1.77"}]
        _run(mgr.reconcile, offers=offers)
        assert mgr._dnsmasq.started_args == []
        assert mgr._config.dhcp_enabled is False
        saved = load_capture_config(env.config_path)
        assert saved.dhcp_enabled is False
        assert saved.dhcp_upstream_gateway == "192.168.1.1"  # routing stays
        assert len(env.host.rules) == 4
        issues = _run(mgr.status)["issues"]
        assert any(
            "Another DHCP server (192.168.1.1) is answering" in i
            and "kept its DHCP server off" in i
            for i in issues
        )
        # Flag cleared, so later reconciles neither probe nor start
        mock = AsyncMock(return_value=[])
        with patch(PROBE, mock):
            asyncio.run(mgr.reconcile())
        mock.assert_not_awaited()
        assert mgr._dnsmasq.started_args == []

    def test_probe_error_holds_for_one_tick_then_retries(self, env):
        # A transient probe error must not persist "off": the router's DHCP is
        # off by design, so that would leave the LAN with no DHCP server.
        mgr = env.make(config=_enabled_config())
        _run(mgr.reconcile, probe_error=OSError(19, "No such device"))
        assert mgr._dnsmasq.started_args == []
        assert mgr._config.dhcp_enabled is True
        assert load_capture_config(env.config_path).dhcp_enabled is True
        issues = _run(mgr.status)["issues"]
        assert any("could not check for other DHCP servers" in i for i in issues)
        # Next tick: the probe is clean, so dnsmasq starts and the issue clears
        _run(mgr.reconcile)
        assert mgr._dnsmasq.running is True
        assert not any("could not check" in i for i in _run(mgr.status)["issues"])

    def test_does_not_start_dnsmasq_when_disabled(self, env):
        cfg = _enabled_config()
        cfg = CaptureConfig(**{**cfg.__dict__, "dhcp_enabled": False})
        mgr = env.make(config=cfg)
        _run(mgr.reconcile)
        assert mgr._dnsmasq.started_args == []
        assert len(env.host.rules) == 4  # routing still reconciled

    def test_noop_when_routing_inactive(self, env):
        mgr = env.make()
        _run(mgr.reconcile)
        assert env.host.calls == []

    def test_never_raises(self, env):
        mgr = env.make(config=_enabled_config())

        async def boom(*args):
            raise RuntimeError("nsenter exploded")

        mgr._run_nsenter = boom
        assert _run(mgr.reconcile) is None

    def test_never_raises_on_dnsmasq_failure(self, env):
        mgr = env.make(config=_enabled_config(), dnsmasq=FakeDnsmasq(fail=True))
        assert _run(mgr.reconcile) is None

    def test_never_raises_on_invalid_saved_upstream(self, env):
        cfg = CaptureConfig(
            mode=CaptureMode.DHCP_GATEWAY,
            interface=IFACE,
            dhcp_upstream_address="garbage",
            dhcp_upstream_gateway="192.168.1.1",
        )
        mgr = env.make(config=cfg)
        assert _run(mgr.reconcile) is None
        assert env.host.mutations() == []

    def test_skips_while_another_operation_holds_the_lock(self, env):
        mgr = env.make(config=_enabled_config())
        env.host.addrs[IFACE] = []

        async def scenario():
            async with mgr._lock:
                await mgr.reconcile()

        _run(scenario)
        assert env.host.calls == []


class TestSetup:
    def test_setup_before_enable_does_nothing(self, env):
        mgr = env.make()
        result = _run(mgr.setup)
        assert result["success"] is True
        assert result["routing_active"] is False
        assert env.host.calls == []

    def test_setup_restores_routing_and_dnsmasq(self, env):
        mgr = env.make(config=_enabled_config())
        result = _run(mgr.setup)
        assert result["success"] is True
        assert result["dhcp_server_running"] is True
        assert ["ethtool", "-K", IFACE, "gro", "off", "lro", "off"] in env.host.calls
        assert len(env.host.rules) == 4
        assert "10.77.0.1/24" in env.host.addrs[IFACE]

    def test_setup_keeps_dnsmasq_off_when_router_answers(self, env):
        mgr = env.make(config=_enabled_config())
        offers = [{"server_ip": "192.168.1.1", "offered_ip": "192.168.1.77"}]
        result = _run(mgr.setup, offers=offers)
        assert result["dhcp_server_running"] is False
        assert mgr._dnsmasq.started_args == []
        assert result["success"] is False
        assert any("Turn it back on from Go Live" in e for e in result["errors"])
        assert load_capture_config(env.config_path).dhcp_enabled is False
        assert len(env.host.rules) == 4  # routing restored regardless

    def test_setup_reports_invalid_config(self, env):
        cfg = CaptureConfig(**{**_enabled_config().__dict__, "interface": "bad name"})
        mgr = env.make(config=cfg)
        result = _run(mgr.setup)
        assert result["success"] is False
        assert env.host.calls == []


# ---------------------------------------------------------------------------
# Teardown
# ---------------------------------------------------------------------------


class TestTeardown:
    def test_removes_everything_but_nettap_address(self, env):
        mgr = env.make()

        async def scenario():
            await mgr.enable()
            return await mgr.teardown()

        result = _run(scenario)
        assert result["torn_down"] is True
        assert result["errors"] == []
        assert mgr._dnsmasq.running is False
        assert env.host.rules == set()
        deletes = [c for c in env.host.calls if "-D" in c]
        assert len(deletes) == 4
        assert env.host.addrs[IFACE] == ["192.168.1.50/24"]  # dashboard stays reachable
        for path in (
            env.dirs["netplan"] / "90-nettap-dhcp-gateway.yaml",
            env.dirs["sysctl"] / "99-nettap-dhcp-gateway.conf",
            env.dirs["etc"] / "dhcp-gateway-firewall.sh",
            env.dirs["systemd"] / "nettap-dhcp-gateway.service",
            env.dirs["systemd"]
            / "multi-user.target.wants"
            / "nettap-dhcp-gateway.service",
        ):
            assert not os.path.lexists(path), path
        saved = load_capture_config(env.config_path)
        assert saved.dhcp_upstream_address == ""
        assert saved.dhcp_upstream_gateway == ""
        assert saved.dhcp_enabled is False
        assert mgr.routing_active is False

    def test_keeps_mode_already_saved_by_wizard(self, env):
        mgr = env.make()

        async def scenario():
            await mgr.enable()
            current = load_capture_config(env.config_path)
            save_capture_config(
                CaptureConfig(**{**current.__dict__, "mode": CaptureMode.MIRROR}),
                env.config_path,
            )
            return await mgr.teardown()

        _run(scenario)
        saved = load_capture_config(env.config_path)
        assert saved.mode == CaptureMode.MIRROR
        assert saved.dhcp_upstream_gateway == ""

    def test_reports_missing_backend_but_still_cleans_files(self, env):
        mgr = env.make()

        async def scenario():
            await mgr.enable()
            env.host.backend = None
            mgr._backend = None
            return await mgr.teardown()

        result = _run(scenario)
        assert result["torn_down"] is False
        assert any("DOCKER-USER" in e for e in result["errors"])
        assert not (env.dirs["netplan"] / "90-nettap-dhcp-gateway.yaml").exists()
        assert not any(c[0] == "iptables-legacy" and "-D" in c for c in env.host.calls)

    def test_teardown_without_enable_is_safe(self, env):
        mgr = env.make()
        result = _run(mgr.teardown)
        assert result["torn_down"] is True
        assert env.host.mutations() == []


# ---------------------------------------------------------------------------
# Health / stats / identity
# ---------------------------------------------------------------------------


class TestHealthAndStats:
    def test_not_configured_before_enable(self, env):
        mgr = env.make()
        health = _run(mgr.get_health)
        assert health.mode == "dhcp_gateway"
        assert health.status == "not_configured"
        d = health.to_dict()
        for key in ("subnet", "routing_active", "dhcp_server_running", "lease_count"):
            assert key in d

    def test_normal_after_enable(self, env):
        mgr = env.make()

        async def scenario():
            await mgr.enable()
            return await mgr.get_health()

        health = _run(scenario)
        assert health.status == "normal"
        assert health.link_up is True
        assert health.issues == []
        assert health.extra["routing_active"] is True
        assert health.extra["dhcp_server_running"] is True
        assert health.capture_interface == IFACE

    def test_down_without_link(self, env):
        mgr = env.make(config=_enabled_config())
        (env.nic / "carrier").write_text("0\n")
        health = _run(mgr.get_health)
        assert health.status == "down"

    def test_degraded_when_pieces_missing(self, env):
        mgr = env.make(config=_enabled_config())
        health = _run(mgr.get_health)
        assert health.status == "degraded"
        assert "The DHCP server is not running." in health.issues
        assert any("10.77.0.1/24" in i for i in health.issues)

    def test_stats_from_sysfs(self, env):
        mgr = env.make()
        stats = _run(mgr.get_stats)
        assert stats.capture_interface == IFACE
        assert stats.rx_bytes == 1000
        assert stats.tx_packets == 50
        assert stats.link_speed_mbps == 2500
        assert stats.drop_rate_pct == 1.0

    def test_identity(self, env):
        mgr = env.make()
        assert mgr.mode == CaptureMode.DHCP_GATEWAY
        assert mgr.get_capture_interface() == IFACE
        assert isinstance(mgr, CaptureManager)


# ---------------------------------------------------------------------------
# DnsmasqProcess (real child processes, no dnsmasq needed)
# ---------------------------------------------------------------------------


class TestDnsmasqProcess:
    def test_start_and_stop(self, tmp_path):
        proc = DnsmasqProcess()
        lease_dir = tmp_path / "leases" / "nested"

        async def scenario():
            started = await proc.start(
                [sys.executable, "-c", "import time; time.sleep(30)"], str(lease_dir)
            )
            again = await proc.start([sys.executable, "-c", "pass"], str(lease_dir))
            running = proc.running
            await proc.stop()
            return started, again, running

        started, again, running = asyncio.run(scenario())
        assert (started, again, running) == (True, False, True)
        assert proc.running is False
        assert lease_dir.is_dir()

    def test_early_exit_raises_with_last_line(self, tmp_path):
        proc = DnsmasqProcess()
        script = "import sys; sys.stderr.write('failed to bind DHCP server socket\\n'); sys.exit(2)"

        async def scenario():
            await proc.start([sys.executable, "-c", script], str(tmp_path))

        with pytest.raises(RuntimeError, match="exit code 2.*failed to bind"):
            asyncio.run(scenario())
        assert proc.running is False

    def test_missing_binary_raises(self, tmp_path):
        proc = DnsmasqProcess()
        with pytest.raises(RuntimeError, match="Could not start dnsmasq"):
            asyncio.run(proc.start([str(tmp_path / "no-such-dnsmasq")], str(tmp_path)))

    def test_kill_after_sigterm_timeout(self, tmp_path):
        proc = DnsmasqProcess()
        script = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"

        async def scenario():
            await proc.start([sys.executable, "-c", script], str(tmp_path))
            with patch.object(dhcp_gateway_host, "_STOP_TIMEOUT_S", 0.2):
                await proc.stop()

        asyncio.run(scenario())
        assert proc.running is False

    def test_stop_when_never_started(self):
        asyncio.run(DnsmasqProcess().stop())
