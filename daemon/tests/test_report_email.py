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


# --- NET-381: the branded HTML part ---------------------------------------------------

from email.message import EmailMessage  # noqa: E402

from services.notification_hub import (  # noqa: E402
    REPORT_EMAIL_MAX_BYTES,
    compose_report_message,
)
from services.report_html import logo_png, render_html  # noqa: E402
from tests.test_report_html import owner_week  # noqa: E402

CID = "171.42.9@nettap.local"


def _send_rich(hub, smtp_cls, logo=True, report=None):
    report = report or _report()
    subject, text = render_email(report)
    html = render_html(report, CID if logo else None)
    parts = (html, (CID, logo_png()) if logo else None)
    with patch.object(hub_module.smtplib, "SMTP", smtp_cls):
        return hub.send_report_email(TO, subject, text, *parts), text, html


def _wire(server):
    raw = server.sendmail.call_args.args[2]
    raw.encode("ascii")  # 7-bit safe on the wire
    return message_from_string(raw, policy=policy.default)


def test_the_html_part_and_its_logo_go_as_alternative_and_related(hub):
    smtp_cls, server = _smtp()
    result, text, html = _send_rich(hub, smtp_cls)
    assert result == {"result": "sent", "refused": [], "error": None}
    assert server.sendmail.call_count == 1
    msg = _wire(server)
    assert msg["To"] == "owner@example.net, Partner@Example.net"
    assert server.sendmail.call_args.args[1] == TO
    assert msg.get_content_type() == "multipart/alternative"
    plain, related = msg.get_payload()
    assert plain.get_content_type() == "text/plain" and plain.get_content() == text
    assert plain["Content-Transfer-Encoding"] == "quoted-printable"
    assert related.get_content_type() == "multipart/related"
    assert related.get_param("type") == "text/html"
    page, image = related.get_payload()
    assert page.get_content_type() == "text/html"
    assert page.get_content().rstrip("\n") == html
    assert page["Content-Transfer-Encoding"] == "quoted-printable"
    assert image.get_content_type() == "image/png"
    assert image.get_content() == logo_png() and logo_png().startswith(b"\x89PNG")
    assert image["Content-ID"].strip("<>") == CID and f"cid:{CID}" in html


def test_html_without_a_logo_is_the_second_alternative(hub):
    smtp_cls, server = _smtp()
    _send_rich(hub, smtp_cls, logo=False)
    plain, page = _wire(server).get_payload()
    assert page.get_content_type() == "text/html" and "cid:" not in page.get_content()


def test_a_failure_composing_the_html_sends_the_plain_email_once(hub, caplog):
    smtp_cls, server = _smtp()
    with patch.object(EmailMessage, "add_related", side_effect=ValueError("bad")):
        with caplog.at_level("WARNING"):
            result, text, _html = _send_rich(hub, smtp_cls)
    assert result["result"] == "sent" and server.sendmail.call_count == 1
    msg = _wire(server)
    assert msg.get_content_type() == "text/plain" and msg.get_content() == text
    assert any(
        "HTML part dropped (logo: ValueError)" in r.getMessage() for r in caplog.records
    )


def test_html_over_the_size_budget_goes_as_plain_text(hub, monkeypatch, caplog):
    monkeypatch.setattr(hub_module, "REPORT_EMAIL_MAX_BYTES", 1000)
    smtp_cls, server = _smtp()
    with caplog.at_level("WARNING"):
        result, text, _html = _send_rich(hub, smtp_cls)
    assert result["result"] == "sent" and server.sendmail.call_count == 1
    assert _wire(server).get_content() == text
    assert any("HTML part dropped (size " in r.getMessage() for r in caplog.records)


def test_an_smtp_failure_with_html_is_failed_after_one_attempt(hub):
    smtp_cls, server = _smtp(error=smtplib.SMTPDataError(554, b"rejected"))
    result, _t, _h = _send_rich(hub, smtp_cls)
    assert result["result"] == "failed" and server.sendmail.call_count == 1


def _busy() -> dict:
    report = owner_week()
    devices = report["sections"]["new_devices"]
    one = {**devices["listed"][3], "name": "Living-room television " + "x" * 100}
    devices.update(count=50, listed=[one] * 50)
    incident = {
        "mac": "AA:BB:CC:00:00:09",
        "name": "Back-garden camera " + "y" * 100,
        "from": "2026-11-21T09:12:00Z",
        "to": "2026-11-21T10:30:00Z",
        "minutes": 78,
        "state": "returned",
        "detail": None,
    }
    report["sections"]["offline"].update(incidents=[incident] * 200, watched_now=12)
    return report


def test_a_busy_week_keeps_its_html_and_logo_under_the_size_budget():
    report = _busy()
    subject, text = render_email(report)
    html = render_html(report, CID)
    wire, dropped = compose_report_message(
        subject,
        "n@example.invalid",
        ["o@example.invalid"],
        text,
        html,
        (CID, logo_png()),
    )
    assert dropped is None and len(html.encode()) < REPORT_EMAIL_MAX_BYTES
    msg = message_from_string(wire, policy=policy.default)
    page, image = msg.get_payload()[1].get_payload()
    assert page.get_content().rstrip("\n") == html and image.get_content() == logo_png()
    assert "and 180 more: see the Reports page in NetTap." in html  # 20 of 200 listed
    assert (
        "Watched now:</span> 12." in html
    )  # the line after the outages survives the cut
    assert text.count("Back-garden camera") == 200  # the plain part keeps every one
