"""NET-205: tc building blocks for the live bandwidth meter (pure functions and the tool runner)."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.live_bandwidth_tc import (
    COOKIE_PREFIX,
    OWNED_PREFS,
    Key,
    TcError,
    build_filter_lines,
    cookie_for,
    delete_args,
    foreign_filters,
    has_ingress_qdisc,
    parse_cookie,
    parse_filter_dump,
    parse_offloads,
    run_tool,
)

FIXTURE = Path(__file__).parent / "fixtures" / "tc_filter_show_g11.json"


class TestFilterLines:
    def test_mac_key_counts_both_directions_with_continue_and_the_cookie(self):
        lines = build_filter_lines("enp4s0", Key("mac", "aa:bb:cc:dd:ee:01"), 3, 7)
        cookie = cookie_for(3, 7)
        assert lines == [
            "filter add dev enp4s0 ingress pref 49152 protocol all handle 4 flower skip_hw "
            f"dst_mac aa:bb:cc:dd:ee:01 action continue cookie {cookie}",
            "filter add dev enp4s0 ingress pref 49153 protocol all handle 4 flower skip_hw "
            f"src_mac aa:bb:cc:dd:ee:01 action continue cookie {cookie}",
        ]

    def test_ip_key_also_counts_802_1q_tagged_frames(self):
        lines = build_filter_lines("enp4s0", Key("ip", "192.168.1.5"), 0, 1)
        assert [
            line.split(" flower skip_hw ")[1].split(" action")[0] for line in lines
        ] == [
            "dst_ip 192.168.1.5",
            "src_ip 192.168.1.5",
            "vlan_ethtype ip dst_ip 192.168.1.5",
            "vlan_ethtype ip src_ip 192.168.1.5",
        ]
        assert [line.split(" protocol ")[1].split()[0] for line in lines] == [
            "ip", "ip", "802.1Q", "802.1Q",
        ]  # fmt: skip
        # a terminal action would stop every later filter from counting
        assert all(" action continue cookie " in line for line in lines)


class TestCookie:
    def test_round_trip(self):
        cookie = cookie_for(7, 123456)
        assert cookie.startswith(COOKIE_PREFIX) and len(cookie) == 32
        assert parse_cookie(cookie) == (7, 123456)
        assert parse_cookie(cookie.upper()) == (7, 123456)

    @pytest.mark.parametrize("cookie", [None, "", "deadbeef", "00" * 16, 5])
    def test_anything_else_is_not_ours(self, cookie):
        assert parse_cookie(cookie) is None


class TestDump:
    def test_real_g11_dump_reads_counters_and_uncookied_filters_are_foreign(self):
        entries = parse_filter_dump(FIXTURE.read_text())
        assert len(entries) == 4  # the per-pref header lines carry no options
        first = entries[0]
        assert (first.pref, first.protocol, first.handle) == (49152, "ip", 1)
        assert (first.bytes, first.packets, first.cookie) == (10896379, 7699, None)
        assert foreign_filters(entries) == entries

    def test_our_cookie_in_someone_elses_pref_is_foreign(self):
        text = (
            '[{"pref": 1, "protocol": "all", "options": {"handle": 1, "actions": '
            f'[{{"cookie": "{cookie_for(0, 1)}", "stats": {{"bytes": 1, "packets": 1}}}}]}}}}]'
        )
        assert len(foreign_filters(parse_filter_dump(text))) == 1

    @pytest.mark.parametrize(
        "text", ["not json", '{"a": 1}', '[{"pref": "x", "options": {}}]']
    )
    def test_unreadable_dump_raises(self, text):
        with pytest.raises(TcError):
            parse_filter_dump(text)

    def test_missing_stats_read_as_none(self):
        entries = parse_filter_dump('[{"pref": 49152, "options": {"handle": 2}}]')
        assert entries[0].bytes is None and entries[0].cookie is None


class TestSmallParsers:
    def test_delete_is_exact_and_uses_our_own_protocol(self):
        assert delete_args("enp4s0", 49156, 3) == [
            "filter", "del", "dev", "enp4s0", "ingress",
            "pref", "49156", "protocol", "802.1Q", "handle", "3", "flower",
        ]  # fmt: skip
        with pytest.raises(KeyError):
            delete_args("enp4s0", 1, 1)  # never a pref NetTap doesn't own
        assert set(OWNED_PREFS) == set(range(49152, 49158))

    def test_qdisc_kinds(self):
        assert has_ingress_qdisc('[{"kind": "fq_codel"}, {"kind": "clsact"}]') == (
            True,
            False,
        )
        assert has_ingress_qdisc('[{"kind": "ingress"}]') == (False, True)
        with pytest.raises(TcError):
            has_ingress_qdisc("nope")

    def test_offloads(self):
        text = "generic-receive-offload: on\nlarge-receive-offload: off [fixed]\n"
        assert parse_offloads(text) == {"gro": True, "lro": False}
        assert parse_offloads("") == {"gro": None, "lro": None}


class _Proc:
    def __init__(self, returncode=0, out=b"", err=b"", hang=False):
        self.returncode = None if hang else returncode
        self._out, self._err, self._hang = out, err, hang
        self.kill = MagicMock(side_effect=self._killed)
        self.wait = AsyncMock()

    def _killed(self):
        self.returncode = -9

    async def communicate(self, data=None):
        if self._hang:
            await asyncio.sleep(10)
        return self._out, self._err


class TestRunTool:
    def test_returns_stdout_and_passes_stdin(self):
        proc = _Proc(out=b"ok\n")
        with patch(
            "asyncio.create_subprocess_exec", AsyncMock(return_value=proc)
        ) as spawn:
            assert asyncio.run(run_tool(["tc", "-batch", "-"], 1, "x\n")) == "ok\n"
        assert spawn.call_args.args == ("tc", "-batch", "-")

    def test_non_zero_exit_raises_with_the_first_error_line(self):
        proc = _Proc(returncode=2, err=b"RTNETLINK answers: File exists\nmore\n")
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            with pytest.raises(TcError, match="File exists"):
                asyncio.run(run_tool(["tc"], 1))

    def test_timeout_kills_and_reaps_the_child(self):
        proc = _Proc(hang=True)
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            with pytest.raises(TcError, match="took longer"):
                asyncio.run(run_tool(["tc"], 0.05))
        proc.kill.assert_called_once()
        proc.wait.assert_awaited_once()

    def test_no_time_left_never_starts_the_child(self):
        with patch("asyncio.create_subprocess_exec", AsyncMock()) as spawn:
            with pytest.raises(TcError, match="no time left"):
                asyncio.run(run_tool(["tc"], 0))
        spawn.assert_not_called()

    def test_missing_binary_is_a_tc_error(self):
        with patch(
            "asyncio.create_subprocess_exec", AsyncMock(side_effect=FileNotFoundError)
        ):
            with pytest.raises(TcError, match="could not run"):
                asyncio.run(run_tool(["tc"], 1))
