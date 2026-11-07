"""NET-192 PR 3: the LAN rule is CIDR terms on source.ip, not a Painless script.

On the G11 over 30 days the script took 3.8-4.3 s and CIDR terms 0.9-1.0 s, with identical
results. Python (network.py, drilldown_runner.py, live_connections.py) reads the subnets back
with lan_subnets_of.
"""

import ipaddress
from unittest.mock import patch

import pytest

from services import excluded_ips
from services.excluded_ips import (
    RFC1918_CIDRS,
    build_lan_filter,
    changed_lan_filter,
    lan_subnets_of,
)

G11 = [(192, 168, 1), (10, 10, 0), (192, 168, 40)]


@pytest.mark.parametrize(
    "subnet, cidr",
    [
        ((10, -1, -1), "10.0.0.0/8"),
        ((172, 16, -1), "172.16.0.0/16"),
        ((192, 168, 1), "192.168.1.0/24"),
        ((10, 10, 0), "10.10.0.0/24"),
    ],
)
def test_each_subnet_form_is_its_cidr(subnet, cidr):
    assert build_lan_filter([subnet]) == {"terms": {"source.ip": [cidr]}}


def test_the_g11_subnets():
    assert build_lan_filter(G11) == {
        "terms": {"source.ip": ["192.168.1.0/24", "10.10.0.0/24", "192.168.40.0/24"]}
    }


def test_no_subnets_is_all_of_rfc1918():
    assert build_lan_filter([]) == {
        "terms": {"source.ip": ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]}
    }
    assert lan_subnets_of(build_lan_filter([])) == []


@pytest.mark.parametrize(
    "subnets",
    [G11, [(10, -1, -1)], [(172, 16, -1), (192, 168, 1)], [(10, -1, -1), (10, 1, 2)]],
)
def test_lan_subnets_of_reads_back_what_was_built(subnets):
    assert lan_subnets_of(build_lan_filter(subnets)) == subnets


def test_lan_subnets_of_anything_else_is_all_of_rfc1918():
    assert lan_subnets_of(None) == []
    assert lan_subnets_of({"script": {"script": {}}}) == []
    assert lan_subnets_of({"terms": {"source.ip": []}}) == []


def _script_rule(subnets, ip: str) -> bool:
    """The old Painless filter's rule, in Python: split on dots, compare octets."""
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    a, b, c = (int(p) for p in parts[:3])
    if not subnets:
        return a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168)
    return any(
        a == sa and (sb == -1 or b == sb) and (sc == -1 or c == sc)
        for sa, sb, sc in subnets
    )


@pytest.mark.parametrize("subnets", [G11, [(10, -1, -1), (172, 16, -1)], []])
def test_matches_the_same_addresses_as_the_script(subnets):
    nets = [
        ipaddress.ip_network(c) for c in build_lan_filter(subnets)["terms"]["source.ip"]
    ]
    for ip in [
        "192.168.1.0", "192.168.1.255", "192.168.2.1", "192.168.40.7", "192.168.41.7",
        "10.10.0.9", "10.10.1.9", "10.0.0.1", "10.255.255.255", "11.0.0.1",
        "172.15.0.1", "172.16.0.1", "172.31.255.1", "172.32.0.1", "8.8.8.8",
        "2606:4700::1111", "fd00::1",
    ]:  # fmt: skip
        addr = ipaddress.ip_address(ip)
        assert any(addr in n for n in nets) == _script_rule(subnets, ip), ip


def test_redetection_sees_no_change_when_the_subnets_are_the_same(monkeypatch):
    monkeypatch.delenv("LAN_SUBNETS", raising=False)
    current = build_lan_filter(G11)
    with patch.object(excluded_ips, "detect_lan_subnets", return_value=list(G11)):
        assert changed_lan_filter(object(), current) is None
    with patch.object(
        excluded_ips, "detect_lan_subnets", return_value=[*G11, (10, 20, 0)]
    ):
        assert changed_lan_filter(object(), current) == build_lan_filter(
            [*G11, (10, 20, 0)]
        )


def test_the_rfc1918_list_is_the_fallback_constant():
    assert build_lan_filter([])["terms"]["source.ip"] == RFC1918_CIDRS
