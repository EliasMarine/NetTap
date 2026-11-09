"""NET-224: notification config safety (no secret out, validation, atomic saves, routing that a
bad rule or a save mid-send can't break) and the senders' deadlines, TLS and failure reasons."""

import asyncio
import json
import logging
import os
import socket
import ssl
import stat
import sys
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import notification_config as nc  # noqa: E402
from services import notification_hub as hub_module  # noqa: E402
from services.notification_hub import NotificationHub  # noqa: E402

TOKEN = "s3cr3t-T0KEN-value"


@pytest.fixture
def env_file(tmp_path):
    path = tmp_path / ".env"
    path.write_text("")
    return path


@pytest.fixture
def hub(tmp_path, env_file):
    return NotificationHub(
        config_path=str(tmp_path / "notifications.json"), env_file=str(env_file)
    )


def _session(status=200, calls=None):
    """A patched aiohttp.ClientSession whose post answers `status`, recording every call."""
    calls = calls if calls is not None else {}
    resp = MagicMock(status=status)
    post_cm = MagicMock()
    post_cm.__aenter__ = AsyncMock(return_value=resp)
    post_cm.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()

    def post(url, **kwargs):
        calls.setdefault("post", []).append((url, kwargs))
        return post_cm

    session.post = post
    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=False)

    def factory(**kwargs):
        calls.setdefault("session", []).append(kwargs)
        return session_cm

    return factory, calls


# ---------------------------------------------------------------------------
# GET never returns a secret
# ---------------------------------------------------------------------------


def test_the_public_view_carries_no_secret_value(hub):
    hub.configure(
        "email",
        {
            "name": "Mail",
            "smtp_host": "smtp.example.net",
            "smtp_pass": TOKEN,
            "recipients": ["a@example.net"],
        },
    )
    hub.configure(
        "webhook",
        {
            "name": "Hook",
            "url": f"https://user:{TOKEN}@hooks.example.net/x/{TOKEN}?k={TOKEN}",
            "headers": {"Authorization": f"Bearer {TOKEN}"},
            "extra": TOKEN,
        },
    )
    hub.configure("telegram", {"name": "TG", "bot_token": TOKEN, "chat_id": "42"})
    hub.configure("pushover", {"name": "PO", "user_key": TOKEN, "api_token": TOKEN})

    shown = hub.public_channels()

    assert TOKEN not in json.dumps(shown)
    by_name = {c["name"]: c["config"] for c in shown}
    assert by_name["Mail"]["has_smtp_pass"] is True
    assert by_name["Mail"]["recipients"] == ["a@example.net"]
    assert by_name["Hook"]["url_hint"] == "https://hooks.example.net/…"
    assert by_name["Hook"]["has_headers"] is True
    assert by_name["TG"]["has_bot_token"] is True and by_name["TG"]["chat_id"] == "42"


# ---------------------------------------------------------------------------
# Validation at the trust boundary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.net/x",
        "file:///etc/passwd",
        "https://",
        "http://user:pw@example.net/x",
        "javascript:alert(1)",
        "",
    ],
)
def test_a_webhook_url_must_be_plain_http_or_https(url):
    assert nc.validate_channel("webhook", {"url": url}) is not None
    assert nc.validate_channel("discord", {"webhook_url": url}) is not None


def test_a_lan_webhook_is_fine():
    assert (
        nc.validate_channel("webhook", {"url": "http://192.0.2.10:8080/nettap"}) is None
    )


@pytest.mark.parametrize(
    "recipients",
    [
        [],
        "a@example.net",
        ["a@example.net\r\nBcc: x@example.net"],
        ["not-an-address"],
        [{"a": 1}],
    ],
)
def test_email_recipients_must_be_addresses_without_line_breaks(recipients):
    assert nc.validate_channel("email", {"recipients": recipients}) is not None


@pytest.mark.parametrize(
    "body",
    [
        {"event_type": "alert", "channels": ["c1"], "min_severity": "2"},
        {"event_type": "alert", "channels": ["c1"], "min_severity": True},
        {"event_type": "alert", "channels": ["c1"], "min_severity": 9},
        {"event_type": "alert", "channels": ["gone"], "min_severity": 2},
        {"event_type": "alert", "channels": [{}], "min_severity": 2},
        {"event_type": "alert", "channels": "c1", "min_severity": 2},
        {"event_type": "nope", "channels": ["c1"], "min_severity": 2},
    ],
)
def test_a_rule_must_be_well_formed(body):
    assert nc.validate_rule(body, {"c1"}) is not None


def test_stored_bad_rules_disabled_and_missing_channels_never_break_routing(
    hub, caplog
):
    good = hub.configure("webhook", {"url": "https://hooks.example.net/a"})
    off = hub.configure("webhook", {"url": "https://hooks.example.net/b"})
    hub._commit(
        {**hub._channels, off["id"]: {**off, "enabled": False}},
        {
            "legacy": {"event_type": "alert", "channels": [{}], "min_severity": 4},
            "text": {
                "event_type": "alert",
                "channels": [good["id"]],
                "min_severity": "2",
            },
            "junk": "not a rule",
            "ok": {
                "event_type": "alert",
                "channels": [good["id"], off["id"], "gone"],
                "min_severity": 4,
            },
        },
    )

    with caplog.at_level(logging.WARNING):
        assert hub.channels_for("alert", 3) == [good["id"]]
        assert hub.channels_for("alert", 3) == [good["id"]]
    assert (
        sum("Skipping notification rule" in r.message for r in caplog.records) == 3
    )  # once each


def test_a_save_while_a_send_waits_does_not_break_routing(hub):
    ch = hub.configure("webhook", {"url": "https://hooks.example.net/a"})
    hub.add_rule("alert", [ch["id"]], 4)
    hub.add_rule("alert", [ch["id"]], 4)
    gate = asyncio.Event()

    async def slow_send(*_a, **_k):
        await gate.wait()
        return True

    async def run():
        with patch.object(hub, "send", side_effect=slow_send):
            task = asyncio.create_task(hub.process_event("alert", "T", "B", 2))
            await asyncio.sleep(0)
            hub.add_rule("alert", [ch["id"]], 1)  # the live rules change mid-send
            gate.set()
            return await task

    result = asyncio.run(run())
    assert result["channels_notified"] == {ch["id"]: True}


# ---------------------------------------------------------------------------
# Saves: atomic, 600, and live only once written
# ---------------------------------------------------------------------------


def test_the_config_file_is_mode_600(hub, tmp_path):
    hub.configure("webhook", {"url": "https://hooks.example.net/a"})
    mode = stat.S_IMODE(os.stat(tmp_path / "notifications.json").st_mode)
    assert mode == 0o600


def test_a_failed_write_changes_neither_the_live_nor_the_saved_config(hub, tmp_path):
    hub.configure("webhook", {"url": "https://hooks.example.net/a", "name": "A"})
    before = (tmp_path / "notifications.json").read_text()

    with patch.object(
        hub_module,
        "write_file_atomic",
        side_effect=OSError(28, "No space left on device"),
    ):
        with pytest.raises(OSError):
            hub.configure(
                "webhook", {"url": "https://hooks.example.net/b", "name": "B"}
            )
        with pytest.raises(OSError):
            hub.set_quick_settings(
                {
                    "min_severity": 1,
                    "email": {},
                    "webhook": {"enabled": True, "url": "https://hooks.example.net/c"},
                }
            )

    assert [c["name"] for c in hub.get_channels()] == ["A"]
    assert hub.get_rules() == []
    assert (tmp_path / "notifications.json").read_text() == before


# ---------------------------------------------------------------------------
# HTTP senders: deadline, no redirects, the status as the reason
# ---------------------------------------------------------------------------


def test_http_sends_have_a_deadline_and_never_follow_a_redirect(hub):
    ch = hub.configure("webhook", {"url": "https://hooks.example.net/a"})
    factory, calls = _session(302)

    with patch.object(hub_module.aiohttp, "ClientSession", side_effect=factory):
        ok = asyncio.run(hub.send(ch["id"], "T", "B", 2))

    assert ok is False
    assert hub.last_delivery(ch["id"])["error"] == "HTTP 302"
    assert calls["post"][0][1]["allow_redirects"] is False
    assert calls["session"][0]["timeout"].total == 10
    assert hub.get_delivery_log()[0]["error"] == "HTTP 302"


def test_a_failure_reason_never_carries_the_url_or_its_token(hub, caplog):
    ch = hub.configure("telegram", {"bot_token": TOKEN, "chat_id": "42"})

    def boom(**_kwargs):
        raise aiohttp.InvalidURL(f"https://api.telegram.org/bot{TOKEN}/sendMessage")

    with (
        caplog.at_level(logging.ERROR),
        patch.object(hub_module.aiohttp, "ClientSession", side_effect=boom),
    ):
        assert asyncio.run(hub.send(ch["id"], "T", "B", 2)) is False

    assert TOKEN not in hub.last_delivery(ch["id"])["error"]
    assert TOKEN not in caplog.text


# ---------------------------------------------------------------------------
# Email: TLS, the API-keys server, refused recipients, the overall deadline
# ---------------------------------------------------------------------------


def _smtp_mock(refused=None):
    server = MagicMock()
    server.sendmail.return_value = refused or {}
    cls = MagicMock()
    cls.return_value.__enter__ = MagicMock(return_value=server)
    cls.return_value.__exit__ = MagicMock(return_value=False)
    return cls, server


def test_port_465_uses_implicit_tls_with_a_verifying_context(hub):
    ch = hub.configure(
        "email",
        {
            "smtp_host": "smtp.example.net",
            "smtp_port": 465,
            "recipients": ["a@example.net"],
        },
    )
    ssl_cls, server = _smtp_mock()

    with (
        patch.object(hub_module.smtplib, "SMTP_SSL", ssl_cls),
        patch.object(hub_module.smtplib, "SMTP") as plain,
    ):
        assert asyncio.run(hub.send(ch["id"], "T", "B", 2)) is True

    plain.assert_not_called()
    context = ssl_cls.call_args.kwargs["context"]
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is True
    server.starttls.assert_not_called()


def test_a_channel_without_its_own_server_uses_the_api_keys_one(hub, env_file):
    env_file.write_text(
        'SMTP_HOST="smtp.example.net"\nSMTP_PORT=587\nSMTP_USERNAME=me@example.net\nSMTP_PASSWORD=pw\nSMTP_SENDER_EMAIL=nettap@example.net\n'
    )
    ch = hub.configure("email", {"recipients": ["a@example.net"]})
    smtp_cls, server = _smtp_mock()

    with patch.object(hub_module.smtplib, "SMTP", smtp_cls):
        assert asyncio.run(hub.send(ch["id"], "T", "B", 2)) is True

    assert smtp_cls.call_args.args[:2] == ("smtp.example.net", 587)
    server.login.assert_called_once_with("me@example.net", "pw")
    assert server.sendmail.call_args.args[0] == "nettap@example.net"


def test_no_smtp_server_anywhere_is_a_plain_reason(hub):
    ch = hub.configure("email", {"recipients": ["a@example.net"]})
    assert asyncio.run(hub.send(ch["id"], "T", "B", 2)) is False
    assert "API keys" in hub.last_delivery(ch["id"])["error"]


def test_a_port_that_isnt_a_number_is_a_plain_reason(hub, env_file):
    env_file.write_text("SMTP_HOST=smtp.example.net\nSMTP_PORT=five-eight-seven\n")
    ch = hub.configure("email", {"recipients": ["a@example.net"]})
    assert asyncio.run(hub.send(ch["id"], "T", "B", 2)) is False
    assert hub.last_delivery(ch["id"])["error"] == "the SMTP port isn't a number"


@pytest.mark.parametrize(
    "url, hint",
    [
        (
            "https://me:pw@hooks.example.net:8443/x?t=1",
            "https://hooks.example.net:8443/…",
        ),
        ("http://[2001:db8::1]:8080/hook", "http://[2001:db8::1]:8080/…"),
        ("not a url", ""),
    ],
)
def test_a_url_hint_is_scheme_and_host_only(url, hint):
    assert nc.url_hint(url) == hint


def test_a_partly_refused_email_is_a_failure_naming_the_refused_address(hub):
    ch = hub.configure(
        "email",
        {
            "smtp_host": "smtp.example.net",
            "recipients": ["a@example.net", "b@example.net"],
        },
    )
    smtp_cls, _server = _smtp_mock(refused={"b@example.net": (550, b"no such user")})

    with patch.object(hub_module.smtplib, "SMTP", smtp_cls):
        assert asyncio.run(hub.send(ch["id"], "T", "B", 2)) is False

    assert (
        hub.last_delivery(ch["id"])["error"] == "the mail server refused b@example.net"
    )


def test_the_subject_takes_no_line_break(hub):
    ch = hub.configure(
        "email", {"smtp_host": "smtp.example.net", "recipients": ["a@example.net"]}
    )
    smtp_cls, server = _smtp_mock()

    with patch.object(hub_module.smtplib, "SMTP", smtp_cls):
        asyncio.run(hub.send(ch["id"], "Line\r\nBcc: x@example.net", "B", 2))

    headers = server.sendmail.call_args.args[2].split("\n\n")[0]
    assert "\nBcc:" not in headers


def _endless_smtp_server():
    """A local SMTP server that greets, then answers EHLO with continuation lines for ever."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    stop = threading.Event()

    def serve():
        conn, _ = listener.accept()
        conn.sendall(b"220 fake ESMTP\r\n")
        conn.recv(1024)  # EHLO
        try:
            while not stop.is_set():
                conn.sendall(b"250-still going\r\n")
                time.sleep(0.2)  # each line well inside the 10 s socket timeout
        except OSError:
            pass
        finally:
            conn.close()

    threading.Thread(target=serve, daemon=True).start()
    return listener, stop


def test_the_whole_smtp_transaction_has_a_deadline():
    listener, stop = _endless_smtp_server()
    port = listener.getsockname()[1]
    started = time.monotonic()
    try:
        with patch.object(hub_module, "_SMTP_DEADLINE_S", 1):
            with pytest.raises(Exception):
                NotificationHub._smtp_send(
                    "127.0.0.1",
                    port,
                    False,
                    "",
                    "",
                    "a@example.net",
                    ["b@example.net"],
                    "x",
                )
    finally:
        stop.set()
        listener.close()
    assert time.monotonic() - started < 6


# ---------------------------------------------------------------------------
# One-time seed from the environment
# ---------------------------------------------------------------------------


def test_the_env_seeds_the_settings_channels_once(tmp_path, env_file):
    env_file.write_text(
        "ALERT_EMAIL=a@example.net, b@example.net\nWEBHOOK_URL=https://hooks.example.net/x\nALERT_SEVERITY_THRESHOLD=1\n"
    )
    path = tmp_path / "notifications.json"

    first = NotificationHub(config_path=str(path), env_file=str(env_file))

    assert {c["id"] for c in first.get_channels()} == {nc.QUICK_EMAIL, nc.QUICK_WEBHOOK}
    rule = first.get_rules()[0]
    assert (rule["event_type"], rule["min_severity"], rule["channels"]) == (
        "alert",
        1,
        [nc.QUICK_EMAIL, nc.QUICK_WEBHOOK],
    )
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600

    first.delete_channel(nc.QUICK_WEBHOOK)
    second = NotificationHub(config_path=str(path), env_file=str(env_file))
    assert {c["id"] for c in second.get_channels()} == {
        nc.QUICK_EMAIL
    }  # not seeded again


def test_an_invalid_env_value_is_skipped_by_name(tmp_path, env_file, caplog):
    env_file.write_text("WEBHOOK_URL=ftp://example.net/x\n")
    with caplog.at_level(logging.WARNING):
        hub = NotificationHub(
            config_path=str(tmp_path / "n.json"), env_file=str(env_file)
        )
    assert hub.get_channels() == []
    assert "WEBHOOK_URL" in caplog.text and "ftp://" not in caplog.text


# ---------------------------------------------------------------------------
# The Settings tab's quick setup
# ---------------------------------------------------------------------------


def test_quick_settings_save_for_real_and_hide_the_url(hub, env_file):
    env_file.write_text("SMTP_HOST=smtp.example.net\n")
    url = f"https://hooks.example.net/{TOKEN}"

    view = hub.set_quick_settings(
        {
            "min_severity": 3,
            "email": {"enabled": True, "recipients": ["a@example.net"]},
            "webhook": {"enabled": True, "url": url},
        }
    )

    assert TOKEN not in json.dumps(view)
    assert view == {
        "min_severity": 3,
        "email": {
            "enabled": True,
            "recipients": ["a@example.net"],
            "smtp_configured": True,
        },
        "webhook": {
            "enabled": True,
            "has_url": True,
            "url_hint": "https://hooks.example.net/…",
        },
    }
    assert hub.channels_for("alert", 3) == [nc.QUICK_EMAIL, nc.QUICK_WEBHOOK]
    assert hub.channels_for("alert", 4) == []


def test_turning_the_webhook_off_and_on_keeps_its_url(hub):
    url = "https://hooks.example.net/x"
    hub.set_quick_settings(
        {"min_severity": 2, "email": {}, "webhook": {"enabled": True, "url": url}}
    )

    off = hub.set_quick_settings(
        {"min_severity": 2, "email": {}, "webhook": {"enabled": False}}
    )
    assert off["webhook"] == {
        "enabled": False,
        "has_url": True,
        "url_hint": "https://hooks.example.net/…",
    }
    assert hub.channels_for("alert", 1) == []

    hub.set_quick_settings(
        {"min_severity": 2, "email": {}, "webhook": {"enabled": True, "url": ""}}
    )
    assert hub.get_channel(nc.QUICK_WEBHOOK)["config"]["url"] == url
    assert hub.channels_for("alert", 1) == [nc.QUICK_WEBHOOK]


@pytest.mark.parametrize(
    "body",
    [
        {
            "min_severity": 2,
            "email": {"enabled": True, "recipients": ["a@example.net"]},
            "webhook": {},
        },  # no SMTP
        {
            "min_severity": 2,
            "email": {},
            "webhook": {"enabled": True, "url": ""},
        },  # no URL saved
        {
            "min_severity": 2,
            "email": {},
            "webhook": {"enabled": True, "url": "ftp://x"},
        },
        {"min_severity": "2", "email": {}, "webhook": {}},
        ["not", "an", "object"],
    ],
)
def test_quick_settings_refuse_what_cannot_work(hub, body):
    with pytest.raises(ValueError):
        hub.set_quick_settings(body)
    assert hub.get_channels() == []
