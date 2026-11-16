"""NetTap's own update check. It asked /releases/latest, which GitHub answers 404 while every
release is a pre-release (v0.4.0-alpha.1 and -alpha.2 so far), and it compared versions without
their "-alpha.N", so no box could ever be told about a newer NetTap."""

import asyncio
from unittest.mock import patch

import pytest

from services.update_checker import NETTAP_APPLIES_WITH, UpdateChecker, _release_key


def test_release_keys_follow_semver_precedence():
    ordered = [
        "0.3.9",
        "0.4.0-alpha.1",
        "0.4.0-alpha.2",
        "0.4.0-alpha.10",
        "0.4.0-alpha.beta",
        "0.4.0-beta.1",
        "0.4.0-rc.1",
        "0.4.0",
        "v0.4.1",
        "1.0.0",
    ]
    keys = [_release_key(t) for t in ordered]
    assert keys == sorted(keys)
    assert _release_key("v0.4.0") == _release_key("0.4.0")
    for bad in ("latest", "0.4", "v0.4.0-", "26.10", ""):
        assert _release_key(bad) is None


def _release(tag, prerelease=None, draft=False):
    return {
        "tag_name": tag,
        "prerelease": "-" in tag if prerelease is None else prerelease,
        "draft": draft,
        "html_url": f"https://github.com/EliasMarine/NetTap/releases/tag/{tag}",
        "published_at": "2026-11-16T03:42:42Z",
        "body": f"Release {tag}",
        "assets": [],
    }


def _check(current, releases):
    uc = UpdateChecker()
    seen = []

    async def fetch(url):
        seen.append(url)
        return releases

    uc._fetch_json = fetch
    with patch("services.version_manager.NETTAP_VERSION", current):
        updates = asyncio.run(uc._check_github_releases())
    assert seen == [
        "https://api.github.com/repos/EliasMarine/NetTap/releases?per_page=20"
    ]
    return updates


ALPHAS = [_release("v0.4.0-alpha.2"), _release("v0.4.0-alpha.1")]


def test_a_newer_pre_release_is_offered_to_a_pre_release():
    (update,) = _check("0.4.0-alpha.1", ALPHAS)
    assert (update.component, update.current_version, update.latest_version) == (
        "nettap-daemon",
        "0.4.0-alpha.1",
        "0.4.0-alpha.2",
    )
    assert update.update_type == "unknown"  # only the pre-release part moved
    assert update.applies_with == NETTAP_APPLIES_WITH
    assert update.release_url.endswith("v0.4.0-alpha.2")


def test_the_newest_release_is_current():
    assert _check("0.4.0-alpha.2", ALPHAS) == []


def test_a_final_release_beats_its_pre_releases():
    (update,) = _check("0.4.0-alpha.2", [*ALPHAS, _release("v0.4.0")])
    assert update.latest_version == "0.4.0"


def test_a_final_release_ignores_newer_pre_releases():
    assert _check("0.4.0", [_release("v0.4.1-alpha.1"), _release("v0.4.0")]) == []
    (update,) = _check("0.4.0", [_release("v0.4.1-alpha.1"), _release("v0.4.1")])
    assert (update.latest_version, update.update_type) == ("0.4.1", "patch")


def test_drafts_and_unreadable_tags_are_ignored():
    releases = [
        _release("v0.5.0", draft=True),
        {"tag_name": "nightly", "prerelease": True},
        "not a release",
        *ALPHAS,
    ]
    assert _check("0.4.0-alpha.2", releases) == []


@pytest.mark.parametrize("reply", [{}, []])
def test_nothing_published_is_no_update(reply):
    assert _check("0.4.0-alpha.2", reply) == []


def test_a_failed_request_reaches_the_caller():
    uc = UpdateChecker()

    async def fetch(url):
        raise RuntimeError("HTTP 403 rate limited")

    uc._fetch_json = fetch
    with pytest.raises(RuntimeError):
        asyncio.run(uc._check_github_releases())
