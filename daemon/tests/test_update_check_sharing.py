"""One update check at a time, shared by every caller; "stale" tells the page when to run one;
no made-up release dates; TLS checked on GitHub calls."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from services.os_updates import os_update_fields
from services.update_checker import UpdateChecker


def _checker(gate=None, calls=None):
    """A checker whose only work is one GitHub call that waits on gate."""
    uc = UpdateChecker()

    async def fetch(url):
        if calls is not None:
            calls.append(url)
        if gate is not None:
            await gate.wait()
        return {}

    async def none():
        return None

    uc._fetch_json = fetch
    uc._check_suricata_rules = none
    uc._check_geoip_update = none
    uc._check_os_updates = lambda version: None
    return uc


def test_overlapping_checks_run_once_and_both_get_the_finished_result():
    async def scenario():
        gate, calls = asyncio.Event(), []
        uc = _checker(gate, calls)
        first = asyncio.ensure_future(uc.check_updates())
        second = asyncio.ensure_future(uc.check_updates())
        await asyncio.sleep(0)
        during = await uc.get_available()  # nothing finished yet: the empty first state
        gate.set()
        return calls, await first, await second, during

    calls, first, second, during = asyncio.run(scenario())
    assert len(calls) == 1  # one GitHub call: one check
    assert first == second
    assert first["last_check"] is not None and first["stale"] is False
    assert during["last_check"] is None and during["stale"] is True


def test_during_a_check_readers_see_the_last_finished_one():
    async def scenario():
        uc = _checker()
        uc._failed_checks = []
        done = await uc.check_updates()
        gate = asyncio.Event()

        async def slow(url):
            uc._failed_checks.append(
                "half-built"
            )  # what a running check leaves mid-way
            await gate.wait()
            return {}

        uc._fetch_json = slow
        running = asyncio.ensure_future(uc.check_updates())
        await asyncio.sleep(0)
        during = await uc.get_available()
        gate.set()
        await running
        return done, during

    done, during = asyncio.run(scenario())
    assert during["failed_checks"] == done["failed_checks"] == []
    assert during["last_check"] == done["last_check"]


def test_a_check_that_crashes_part_way_serves_nothing_half_built():
    """Review: the empty first state was built from the check's working fields."""
    uc = _checker()

    async def crash():
        uc._failed_checks.append("half-built")
        raise RuntimeError("unexpected")

    uc._check_geoip_update = crash
    try:
        asyncio.run(uc.check_updates())
    except RuntimeError:
        pass
    assert asyncio.run(uc.get_available()) == {
        "updates": [],
        "last_check": None,
        "count": 0,
        "has_updates": False,
        "failed_checks": [],
        "checked": [],
        "stale": True,
    }
    # after a check that finished, a later crash leaves that one in place
    uc._check_geoip_update = _checker()._check_geoip_update
    done = asyncio.run(uc.check_updates())
    uc._check_geoip_update = crash
    try:
        asyncio.run(uc.check_updates())
    except RuntimeError:
        pass
    assert asyncio.run(uc.get_available())["failed_checks"] == done["failed_checks"]


def test_stale_until_checked_and_again_after_the_ttl():
    uc = _checker()
    assert asyncio.run(uc.get_available())["stale"] is True
    asyncio.run(uc.check_updates())
    assert asyncio.run(uc.get_available())["stale"] is False
    seven_hours_ago = datetime.now(timezone.utc) - timedelta(hours=7)
    uc._last_check = seven_hours_ago.isoformat()
    uc._last_result = {**uc._last_result, "last_check": uc._last_check}
    assert asyncio.run(uc.get_available())["stale"] is True


def test_a_failed_check_can_be_retried():
    uc = _checker()

    async def boom(url):
        raise RuntimeError("network down")

    uc._fetch_json = boom
    first = asyncio.run(
        uc.check_updates()
    )  # the GitHub failure is a failed check, not a crash
    assert "nettap-daemon" in first["failed_checks"]
    uc._fetch_json = _checker()._fetch_json
    assert "nettap-daemon" not in asyncio.run(uc.check_updates())["failed_checks"]


def test_rules_and_os_rows_carry_no_made_up_release_date(tmp_path):
    month_old = datetime.now(timezone.utc).timestamp() - 30 * 86400
    with (
        patch("os.path.exists", return_value=True),
        patch("os.path.getmtime", return_value=month_old),
    ):
        rules = asyncio.run(UpdateChecker()._check_suricata_rules())
    assert rules.release_date == ""
    notifier = tmp_path / "updates-available"
    notifier.write_text("3 updates can be applied immediately.\n")
    fields = os_update_fields("24.04", str(notifier))
    assert fields["release_date"] == ""
    assert "(as of " in fields["changelog"]  # when Ubuntu counted them stays visible


def test_github_calls_check_tls():
    session = MagicMock()
    response = MagicMock(status=404)
    session.get.return_value.__aenter__.return_value = response
    client = MagicMock()
    client.return_value.__aenter__.return_value = session
    with patch("services.update_checker.aiohttp.ClientSession", client):
        assert (
            asyncio.run(UpdateChecker()._fetch_json("https://api.github.com/x")) == {}
        )
    assert "ssl" not in session.get.call_args.kwargs
