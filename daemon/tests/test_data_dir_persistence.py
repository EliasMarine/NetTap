"""F4: suppressions, false-positive marks, baselines and the threat-intel cache outlive a restart.

The paths are module-level constants read from NETTAP_DATA_DIR at import, so each check runs in
its own Python process: that is the new process lifetime a daemon restart gives.
"""

import os
import subprocess
import sys
from pathlib import Path

DAEMON_DIR = Path(__file__).resolve().parents[1]


def _python(code: str, data_dir: Path | None = None) -> str:
    env = {k: v for k, v in os.environ.items() if k != "NETTAP_DATA_DIR"}
    if data_dir is not None:
        env["NETTAP_DATA_DIR"] = str(data_dir)
    done = subprocess.run(
        [sys.executable, "-c", code],
        cwd=DAEMON_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def test_default_paths_are_on_the_persistent_volume():
    # /tmp is a tmpfs in the daemon container: everything there dies with the container
    out = _python(
        "import services.alert_intelligence as a, services.threat_intel as t\n"
        "print(a._SUPPRESS_PATH, a._BASELINE_PATH, t._TI_CACHE_PATH, sep='\\n')"
    )
    assert out.splitlines() == [
        "/opt/nettap/data/nettap-suppress.json",
        "/opt/nettap/data/nettap-baselines.json",
        "/opt/nettap/data/nettap-threat-intel.json",
    ]


def test_a_suppression_survives_a_new_process(tmp_path):
    _python(
        "from services.alert_intelligence import suppress_rule, mark_false_positive\n"
        "suppress_rule(2027865, reason='noisy')\n"
        "suppress_rule(2013028, device_ip='192.168.1.20')\n"
        "mark_false_positive(2210054)",
        tmp_path,
    )
    assert (tmp_path / "nettap-suppress.json").exists()

    out = _python(
        "from services.alert_intelligence import is_suppressed\n"
        "print(is_suppressed(2027865), is_suppressed(2013028, '192.168.1.20'),"
        " is_suppressed(2210054), is_suppressed(1))",
        tmp_path,
    )
    assert out == "True True True False"
