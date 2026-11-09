"""NET-205: the live bandwidth on/off setting file."""

import json

import pytest

from services.live_bandwidth_setting import load_enabled, parse_enabled, save_enabled


def test_off_when_never_saved(tmp_path):
    assert load_enabled(str(tmp_path / "missing.json")) is False


def test_round_trip_creates_the_directory(tmp_path):
    path = tmp_path / "data" / "live_bandwidth.json"
    save_enabled(True, str(path))
    assert load_enabled(str(path)) is True
    assert json.loads(path.read_text()) == {"enabled": True}
    save_enabled(False, str(path))
    assert load_enabled(str(path)) is False
    assert [p.name for p in path.parent.iterdir()] == ["live_bandwidth.json"]


def test_a_failed_write_leaves_the_old_file_and_no_temp_file(tmp_path, monkeypatch):
    path = tmp_path / "live_bandwidth.json"
    save_enabled(True, str(path))

    def fail(*_args):
        raise OSError("disk full")

    monkeypatch.setattr("os.replace", fail)
    with pytest.raises(OSError, match="disk full"):
        save_enabled(False, str(path))
    assert load_enabled(str(path)) is True
    assert [p.name for p in tmp_path.iterdir()] == ["live_bandwidth.json"]


@pytest.mark.parametrize("text", ["{not json", '{"enabled": "true"}', "[]", ""])
def test_a_bad_file_reads_off_and_is_logged(tmp_path, caplog, text):
    path = tmp_path / "live_bandwidth.json"
    path.write_text(text)
    assert load_enabled(str(path)) is False
    assert "Ignoring the live bandwidth setting file" in caplog.text


def test_the_env_var_names_the_file(tmp_path, monkeypatch):
    path = tmp_path / "lb.json"
    monkeypatch.setenv("LIVE_BANDWIDTH_FILE", str(path))
    save_enabled(True)
    assert load_enabled() is True and path.exists()


@pytest.mark.parametrize(
    "body",
    [{"enabled": "true"}, {"enabled": 1}, {"enabled": None}, {}, [], "true", None],
)
def test_only_a_json_bool_is_accepted(body):
    with pytest.raises(ValueError):
        parse_enabled(body)


def test_a_bool_is_accepted():
    assert parse_enabled({"enabled": True}) is True
    assert parse_enabled({"enabled": False}) is False
