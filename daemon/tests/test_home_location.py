"""Live globe: the network's home location (store, routes, WAN lookup). No network access."""

import asyncio
import json

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import api.home_location as api_home
from api.home_location import register_home_location_routes, wan_suggestion
from services.home_location import clear_home, load_home, parse_home, save_home

URL = "/api/settings/home-location"


# --------------------------------------------------------------------------- parse_home


@pytest.mark.parametrize(
    "body, message",
    [
        ([], "JSON object"),
        ({"lat": True, "lon": 0}, "'lat' must be a number"),
        ({"lat": 0, "lon": False}, "'lon' must be a number"),
        ({"lat": "51.5", "lon": 0}, "'lat' must be a number"),
        ({"lon": 0}, "'lat' must be a number"),
        ({"lat": float("nan"), "lon": 0}, "between -90 and 90"),
        ({"lat": 0, "lon": float("inf")}, "between -180 and 180"),
        ({"lat": 0, "lon": float("-inf")}, "between -180 and 180"),
        ({"lat": 90.0001, "lon": 0}, "between -90 and 90"),
        ({"lat": 0, "lon": -180.5}, "between -180 and 180"),
        ({"lat": 10**400, "lon": 0}, "between -90 and 90"),
        ({"lat": 0, "lon": 0, "label": 5}, "'label' must be text"),
        ({"lat": 0, "lon": 0, "label": "x" * 81}, "at most 80"),
        ({"lat": 0, "lon": 0, "label": "Home\nBase"}, "control characters"),
        ({"lat": 0, "lon": 0, "label": "Home​Base"}, "control characters"),
    ],
)
def test_parse_home_refuses(body, message):
    with pytest.raises(ValueError, match=message):
        parse_home(body)


def test_parse_home_accepts_rounds_and_strips():
    assert parse_home({"lat": 51.507351, "lon": -0.12776, "label": "  London  "}) == {
        "lat": 51.5074,
        "lon": -0.1278,
        "label": "London",
    }
    assert parse_home({"lat": -90, "lon": 180, "label": None}) == {
        "lat": -90.0,
        "lon": 180.0,
        "label": "",
    }
    assert parse_home({"lat": 0, "lon": 0})["label"] == ""
    assert (
        parse_home({"lat": 0, "lon": 0, "label": "  " + "x" * 80 + " "})["label"]
        == "x" * 80
    )


# --------------------------------------------------------------------------- store


def test_save_load_clear_round_trip(tmp_path):
    path = str(tmp_path / "sub" / "home.json")
    assert load_home(path) is None
    home = parse_home({"lat": 48.8566, "lon": 2.3522, "label": "Paris"})
    save_home(home, path)
    assert load_home(path) == home
    assert [p.name for p in (tmp_path / "sub").iterdir()] == [
        "home.json"
    ]  # no temp left
    clear_home(path)
    assert load_home(path) is None
    clear_home(path)  # already gone: no error


@pytest.mark.parametrize(
    "content", ["{not json", "[]", '{"lat": 200, "lon": 0}', "\xff\xfe"]
)
def test_malformed_file_reads_as_none(tmp_path, content):
    path = tmp_path / "home.json"
    path.write_text(content, encoding="latin-1")
    assert load_home(str(path)) is None


def test_env_names_the_file(tmp_path, monkeypatch):
    path = tmp_path / "home.json"
    monkeypatch.setenv("HOME_LOCATION_FILE", str(path))
    save_home({"lat": 1.0, "lon": 2.0, "label": ""})
    assert json.loads(path.read_text()) == {"lat": 1.0, "lon": 2.0, "label": ""}


# --------------------------------------------------------------------------- wan_suggestion


def test_wan_suggestion_builds_the_label():
    reply = {
        "ip": "81.2.69.142",
        "city": " London ",
        "region": "England",
        "country": "GB",
        "loc": "51.5085,-0.1257",
    }
    assert wan_suggestion(reply) == {
        "lat": 51.5085,
        "lon": -0.1257,
        "label": "London, England, GB",
    }
    assert wan_suggestion({"loc": "1,2", "city": "", "region": None})["label"] == ""


def test_wan_suggestion_strips_control_characters_and_truncates():
    reply = {"loc": "1,2", "city": "Lon\x00don​", "region": "y" * 100}
    label = wan_suggestion(reply)["label"]
    assert label.startswith("London, yyy")
    assert len(label) == 80


@pytest.mark.parametrize(
    "reply, message",
    [
        (["loc"], "JSON object"),
        ({"city": "London"}, "no location"),
        ({"loc": 51.5}, "no location"),
        ({"loc": "1,2,3"}, "no location"),
        ({"loc": "north,west"}, "two numbers"),
        ({"loc": "95.0,10.0"}, "between -90 and 90"),
        ({"loc": "nan,0"}, "between -90 and 90"),
    ],
)
def test_wan_suggestion_refuses_unusable_replies(reply, message):
    with pytest.raises(ValueError, match=message):
        wan_suggestion(reply)


# --------------------------------------------------------------------------- routes


@pytest.fixture
def home_file(tmp_path, monkeypatch):
    path = tmp_path / "home_location.json"
    monkeypatch.setenv("HOME_LOCATION_FILE", str(path))
    return path


def _app() -> web.Application:
    app = web.Application()
    register_home_location_routes(app)
    return app


@pytest.mark.asyncio
async def test_get_put_delete(home_file):
    async with TestClient(TestServer(_app())) as client:
        resp = await client.get(URL)
        assert (resp.status, await resp.json()) == (200, {"home": None})

        resp = await client.put(
            URL, json={"lat": 40.7128, "lon": -74.006, "label": "NYC"}
        )
        saved = {"lat": 40.7128, "lon": -74.006, "label": "NYC"}
        assert (resp.status, await resp.json()) == (200, {"home": saved})
        assert json.loads(home_file.read_text()) == saved

        resp = await client.get(URL)
        assert await resp.json() == {"home": saved}

        resp = await client.delete(URL)
        assert (resp.status, await resp.json()) == (200, {"home": None})
        assert not home_file.exists()


@pytest.mark.asyncio
async def test_put_refuses_bad_input_and_saves_nothing(home_file):
    async with TestClient(TestServer(_app())) as client:
        resp = await client.put(URL, json={"lat": 91, "lon": 0})
        assert resp.status == 400
        assert "between -90 and 90" in (await resp.json())["error"]

        resp = await client.put(
            URL, data=b"{oops", headers={"Content-Type": "application/json"}
        )
        assert resp.status == 400
        assert not home_file.exists()


@pytest.mark.asyncio
async def test_put_answers_500_when_the_disk_refuses(tmp_path, monkeypatch):
    (tmp_path / "a-file").write_text("")
    monkeypatch.setenv("HOME_LOCATION_FILE", str(tmp_path / "a-file" / "home.json"))
    async with TestClient(TestServer(_app())) as client:
        resp = await client.put(URL, json={"lat": 1, "lon": 2})
        assert resp.status == 500
        assert await resp.json() == {"error": "Couldn't save the location"}


def _fake_fetch(reply=None, error=None):
    async def fetch():
        if error is not None:
            raise error
        return reply

    return fetch


@pytest.mark.asyncio
async def test_wan_lookup_suggests_and_never_saves(home_file, monkeypatch):
    monkeypatch.setattr(
        api_home,
        "fetch_wan_geo",
        _fake_fetch({"city": "Berlin", "country": "DE", "loc": "52.5244,13.4105"}),
    )
    async with TestClient(TestServer(_app())) as client:
        resp = await client.post(URL + "/wan-lookup")
        assert resp.status == 200
        assert await resp.json() == {
            "suggestion": {"lat": 52.5244, "lon": 13.4105, "label": "Berlin, DE"}
        }
        assert not home_file.exists()
        assert (await (await client.get(URL)).json()) == {"home": None}


@pytest.mark.parametrize(
    "fake, reason",
    [
        (_fake_fetch(["not", "an", "object"]), "the reply wasn't a JSON object"),
        (_fake_fetch({"city": "Berlin"}), "the reply had no location"),
        (_fake_fetch({"loc": "123.0,10.0"}), "'lat' must be between -90 and 90"),
        (
            _fake_fetch(error=asyncio.TimeoutError()),
            "the lookup service didn't answer within 5 seconds",
        ),
        (
            _fake_fetch(error=aiohttp.ClientConnectionError("refused")),
            "the lookup service couldn't be reached",
        ),
        (
            _fake_fetch(error=json.JSONDecodeError("x", "<html>", 0)),
            "the reply wasn't JSON",
        ),
        (_fake_fetch(error=RuntimeError("boom")), "something unexpected went wrong"),
    ],
)
@pytest.mark.asyncio
async def test_wan_lookup_failures_are_502_in_plain_words(
    home_file, monkeypatch, fake, reason
):
    monkeypatch.setattr(api_home, "fetch_wan_geo", fake)
    async with TestClient(TestServer(_app())) as client:
        resp = await client.post(URL + "/wan-lookup")
        assert resp.status == 502
        assert await resp.json() == {
            "error": f"Couldn't look up your WAN location: {reason}. "
            "Enter the coordinates by hand."
        }
        assert not home_file.exists()


# --------------------------------------------------------------------------- fetch_wan_geo


async def _serve(handler) -> TestServer:
    app = web.Application()
    app.router.add_get("/json", handler)
    server = TestServer(app)
    await server.start_server()
    return server


@pytest.mark.asyncio
async def test_fetch_wan_geo_reads_a_reply_in_pieces(monkeypatch):
    async def reply(request):
        resp = web.StreamResponse()
        await resp.prepare(request)
        await resp.write(b'{"loc": "1.5,')
        await resp.write(b' 2.5"}')
        return resp

    server = await _serve(reply)
    try:
        monkeypatch.setattr(api_home, "WAN_LOOKUP_URL", str(server.make_url("/json")))
        assert await api_home.fetch_wan_geo() == {"loc": "1.5, 2.5"}
    finally:
        await server.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body, status, message",
    [(b"x" * (17 * 1024), 200, "too large"), (b"{}", 429, "HTTP 429")],
    ids=["too-large", "http-429"],
)
async def test_fetch_wan_geo_refuses_big_or_failed_replies(
    monkeypatch, body, status, message
):
    async def reply(request):
        return web.Response(body=body, status=status)

    server = await _serve(reply)
    try:
        monkeypatch.setattr(api_home, "WAN_LOOKUP_URL", str(server.make_url("/json")))
        with pytest.raises(ValueError, match=message):
            await api_home.fetch_wan_geo()
    finally:
        await server.close()
