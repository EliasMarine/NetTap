"""Which of 192.168.1.44's rules deploy-detection-slice1.sh suppresses (NET-191)."""

import importlib.util
from pathlib import Path

_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "remote"
    / "verify_detection_slice1.py"
)
_spec = importlib.util.spec_from_file_location("verify_detection_slice1", _PATH)
vs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vs)


def _bucket(sid: int, name: str, sev: str | None, count: int = 10) -> dict:
    return {
        "key": sid,
        "doc_count": count,
        "name": {"buckets": [{"key": name}]},
        "sev": {"buckets": [{"key": sev}] if sev else []},
    }


class _Client:
    def __init__(self, buckets: list[dict]) -> None:
        self.buckets = buckets
        self.bodies: list[dict] = []

    def search(self, index: str, body: dict) -> dict:
        self.bodies.append(body)
        return {"aggregations": {"sid": {"buckets": self.buckets}}}


def test_only_activity_rated_proxyware_rules_are_suppressed(monkeypatch, capsys):
    fake = _Client(
        [
            _bucket(
                2067457,
                "ET ADWARE_PUP Observed DNS Query to Bandwidth Sharing Tool Domain (mysterium .network)",
                "Informational",
            ),
            _bucket(
                2060251,
                "ET INFO Go-http-client User-Agent Observed Outbound",
                "Unknown",
            ),
            _bucket(
                2024897, "ET USER_AGENTS Go HTTP Client User-Agent", "Informational"
            ),
            _bucket(
                2013075, "ET MALWARE Large DNS Query possible covert channel", "Major"
            ),
            _bucket(2099999, "ET ADWARE_PUP Bandwidth Sharing Tool Exfil", "Major"),
            _bucket(
                2033078,
                "ET INFO Session Traversal Utilities for NAT (STUN Binding Request On Non-Standard High Port)",
                "Informational",
            ),
            _bucket(2210044, "SURICATA STREAM Packet with invalid timestamp", None),
        ]
    )
    monkeypatch.setattr(vs, "client", lambda: fake)

    vs.sids("192.168.1.44")

    chosen = [line.split("\t")[0] for line in capsys.readouterr().out.splitlines()]
    assert chosen == ["2067457", "2060251", "2024897"]
    # Only alerts the device itself raised: the suppress lines are track by_src
    assert {"term": {"source.ip": "192.168.1.44"}} in fake.bodies[0]["query"]["bool"][
        "filter"
    ]


def test_2013075_is_never_suppressed_even_if_rated_activity(monkeypatch, capsys):
    fake = _Client(
        [
            _bucket(
                2013075,
                "ET ADWARE_PUP Bandwidth Sharing Tool (renamed)",
                "Informational",
            )
        ]
    )
    monkeypatch.setattr(vs, "client", lambda: fake)

    vs.sids("192.168.1.44")

    assert capsys.readouterr().out == ""
