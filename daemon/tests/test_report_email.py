"""send_report_email: the weekly report through the API-keys SMTP server (NET-340, plan §3.5)."""

import smtplib
from email import message_from_string, policy
from unittest.mock import MagicMock, patch

import pytest

from services import notification_hub as hub_module
from services.notification_hub import NotificationHub
from services.report_text import render_email
from tests.test_report_text import _report

SMTP_ENV = (
    'SMTP_HOST="smtp.example.net"\nSMTP_PORT=587\nSMTP_USERNAME=me@example.net\n'
    "SMTP_PASSWORD=pw\nSMTP_SENDER_EMAIL=nettap@example.net\n"
)
TO = ["owner@example.net", "Partner@Example.net"]


@pytest.fixture
def env_file(tmp_path):
    path = tmp_path / ".env"
    path.write_text(SMTP_ENV)
    return path


@pytest.fixture
def hub(tmp_path, env_file):
    return NotificationHub(
        config_path=str(tmp_path / "notifications.json"), env_file=str(env_file)
    )


def _smtp(refused=None, error=None):
    server = MagicMock()
    server.connect.return_value = (220, b"ready")
    server.__enter__.return_value = server
    server.__exit__.return_value = False
    if error:
        server.sendmail.side_effect = error
    else:
        server.sendmail.return_value = refused or {}
    return MagicMock(return_value=server), server


def _send(hub, smtp_cls, recipients=TO):
    subject, text = render_email(_report())
    with patch.object(hub_module.smtplib, "SMTP", smtp_cls):
        return hub.send_report_email(recipients, subject, text), subject, text


def test_the_report_goes_to_every_recipient_as_utf8_plain_text(hub):
    smtp_cls, server = _smtp()
    result, subject, text = _send(hub, smtp_cls)
    assert result == {"result": "sent", "refused": [], "error": None}
    assert server.connect.call_args.args == ("smtp.example.net", 587)
    server.starttls.assert_called_once()
    server.login.assert_called_once_with("me@example.net", "pw")
    sender, envelope, raw = server.sendmail.call_args.args
    assert sender == "nettap@example.net" and envelope == TO
    raw.encode("ascii")  # 7-bit safe on the wire
    msg = message_from_string(raw, policy=policy.default)
    assert msg["Subject"] == subject == "NetTap weekly report: 9–15 November 2026"
    assert "[" not in msg["Subject"]  # no severity tag
    assert msg.get_content_type() == "text/plain"
    assert msg.get_content() == text  # the en dash and every line, intact
    assert msg["To"] == "owner@example.net, Partner@Example.net"


def test_some_recipients_refused_is_partly_sent(hub):
    smtp_cls, _server = _smtp(refused={"Partner@Example.net": (550, b"no such user")})
    result, _s, _t = _send(hub, smtp_cls)
    assert result["result"] == "partly_sent"
    assert result["refused"] == ["Partner@Example.net"]


def test_every_recipient_refused_is_failed(hub):
    refused = {r: (550, b"no") for r in TO}
    smtp_cls, _server = _smtp(error=smtplib.SMTPRecipientsRefused(refused))
    result, _s, _t = _send(hub, smtp_cls)
    assert result["result"] == "failed"
    assert result["refused"] == sorted(TO)
    assert result["error"] == "the mail server refused every recipient"


def test_a_connection_failure_is_failed_and_logs_no_address(hub, caplog):
    smtp_cls, server = _smtp()
    server.connect.side_effect = ConnectionRefusedError(61, "Connection refused")
    with caplog.at_level("WARNING", logger="nettap.services.notification_hub"):
        result, _s, _t = _send(hub, smtp_cls)
    assert result == {
        "result": "failed",
        "refused": [],
        "error": "can't connect: Connection refused",
    }
    assert not any(addr in r.getMessage() for r in caplog.records for addr in TO)


def test_no_smtp_server_is_not_configured(hub, env_file):
    env_file.write_text("")
    smtp_cls, server = _smtp()
    result, _s, _t = _send(hub, smtp_cls)
    assert result["result"] == "not_configured"
    smtp_cls.assert_not_called()


@pytest.mark.parametrize(
    "recipients", [[], ["not-an-address"], ["a@b.net\r\nBcc: x@y.net"]]
)
def test_no_valid_recipients_sends_nothing(hub, recipients):
    smtp_cls, _server = _smtp()
    result, _s, _t = _send(hub, smtp_cls, recipients)
    assert result["result"] == "not_configured"
    smtp_cls.assert_not_called()
