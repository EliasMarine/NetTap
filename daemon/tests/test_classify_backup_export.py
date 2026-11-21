"""NET-344 plan §4: the export classifier the deploy gates share with F2 (NET-320).

The script runs in a fresh interpreter (-I, cwd outside daemon/), so an import from the
daemon would fail here as it would in a daemon image from before F2.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from services.config_backup import RESTORE_LIMIT_BYTES

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "remote"
    / "classify_backup_export.py"
)
PRE_F2 = {"metadata": {"schema_version": 2}, "sections": {"alert_acknowledgements": {}}}
POST_F2 = {"metadata": {"schema_version": 2}, "sections": {"device_details": {}}}


def body(doc: object) -> bytes:
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode()


def padded(size: int) -> bytes:
    """A valid backup of exactly `size` bytes: spaces before the last brace."""
    head = body(PRE_F2)[:-1]
    return head + b" " * (size - len(head) - 1) + b"}"


def run(status: str, data: bytes, *args: str, tmp_path: Path) -> tuple[str, int]:
    done = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), status, *args],
        input=data,
        capture_output=True,
        cwd=tmp_path,
        timeout=60,
    )
    assert done.stderr == b""
    return done.stdout.decode().strip(), done.returncode


TOO_LARGE = {
    "error": "This backup would be 17.4 MB, over the 16 MB restore limit.",
    "code": "backup_too_large",
}
LEGACY = {
    "error": "Excluded IPs: 10.0.0.0/8 is a range.",
    "code": "legacy_excluded_ips",
}
INVALID = {"error": "device_details isn't valid", "code": "invalid_section"}


@pytest.mark.parametrize(
    ("status", "data", "args", "verdict", "says"),
    [
        ("200", body(PRE_F2), [], "OK", "acknowledgements_left_out 0"),
        (
            "200",
            body({**PRE_F2, "metadata": {"acknowledgements_left_out": 12}}),
            [],
            "OK",
            "left_out 12",
        ),
        (
            "200",
            body(POST_F2),
            ["--require-section", "device_details"],
            "OK",
            "left_out 0",
        ),
        (
            "200",
            body(PRE_F2),
            ["--require-section", "device_details"],
            "FAIL",
            "without the device_details",
        ),
        (
            "200",
            body({**PRE_F2, "metadata": {"acknowledgements_left_out": True}}),
            [],
            "FAIL",
            "True",
        ),
        (
            "200",
            body({**PRE_F2, "metadata": {"acknowledgements_left_out": -1}}),
            [],
            "FAIL",
            "-1",
        ),
        ("200", b"<html>sign in</html>", [], "FAIL", "not a backup"),
        ("200", b'{"metadata":{},"sections":{"x":NaN}}', [], "FAIL", "not a backup"),
        ("200", b'{"metadata":{},"sections":{"x":"\xff"}}', [], "FAIL", "not a backup"),
        ("413", body(TOO_LARGE), [], "FINDING", "17.4 MB"),
        (
            "422",
            body(LEGACY),
            ["--require-section", "device_details"],
            "FINDING",
            "10.0.0.0/8",
        ),
        ("422", body(INVALID), [], "FAIL", "invalid_section: device_details"),
        ("413", b"<html>413 Request Entity Too Large</html>", [], "FAIL", "413 None"),
        ("500", body({"error": "Config export failed: boom"}), [], "FAIL", "boom"),
        ("503", body({"error": "A backup is already being made."}), [], "FAIL", "503"),
        ("000", b"", [], "FAIL", "000"),
    ],
)
def test_classifies(status, data, args, verdict, says, tmp_path) -> None:
    out, code = run(status, data, *args, tmp_path=tmp_path)
    assert out.split(" ", 1)[0] == verdict, out
    assert says in out
    assert code == (1 if verdict == "FAIL" else 0)
    assert "\n" not in out


def test_a_200_restores_only_under_the_limit(tmp_path) -> None:
    """The classifier's own copy of the limit is the daemon's."""
    out, code = run("200", padded(RESTORE_LIMIT_BYTES - 1), tmp_path=tmp_path)
    assert (out.split()[0], code) == ("OK", 0), out
    out, code = run("200", padded(RESTORE_LIMIT_BYTES), tmp_path=tmp_path)
    assert (out.split()[0], code) == ("FAIL", 1), out


def test_runs_as_dash_c_with_the_body_on_stdin(tmp_path) -> None:
    """How the deploy scripts hand it to the daemon container: python3 -c "$(cat …)" STATUS < body."""
    done = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            SCRIPT.read_text(),
            "200",
            "--require-section",
            "device_details",
        ],
        input=body(POST_F2),
        capture_output=True,
        cwd=tmp_path,
        timeout=60,
    )
    assert (done.returncode, done.stdout.decode().split()[0]) == (0, "OK"), done
