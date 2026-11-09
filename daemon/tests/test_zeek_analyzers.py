"""NET-219: zeek-live runs the QUIC analyzer and not the industrial-control (ICS) ones."""

import os

import yaml

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_zeek_live_turns_quic_on_and_ics_off():
    with open(os.path.join(REPO, "docker", "docker-compose.yml")) as f:
        env = yaml.safe_load(f)["services"]["zeek-live"]["environment"]
    # Malcolm's local.zeek treats only a "true" value as disabled
    assert env["ZEEK_DISABLE_SPICY_QUIC"] == "false"
    assert env["ZEEK_DISABLE_ICS_ALL"] == "true"
