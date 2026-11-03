"""#139: the slowest handlers keep their blocking OpenSearch calls off the request loop.

On the G11 the threat report (8-13 s), risk scores (7.5 s) and beaconing (5.6 s) ran on the
daemon's one request loop, so every other request waited; the top bar's 5 s liveness check
gave up and said "Can't reach NetTap". Each test blocks the handler's OpenSearch step until
the request loop runs other work: a handler that blocks the loop can never be released.
"""

import asyncio
import threading
from unittest.mock import MagicMock, patch

from api.risk import handle_risk_scores
from api.threats import handle_beaconing, handle_threat_report
from services.risk_scoring import RiskScorer


def _request(**app):
    request = MagicMock()
    request.query = {}
    request.app = {"storage": MagicMock(), "excluded_ips": [], **app}
    return request


def _status_while_loop_runs(handler, request, loop_ran: threading.Event) -> int:
    async def main():
        task = asyncio.ensure_future(handler(request))
        await asyncio.sleep(0)  # the handler starts and reaches its OpenSearch step
        loop_ran.set()  # only happens if that step left the loop free
        return (await task).status

    return asyncio.run(main())


def _blocks_until(loop_ran: threading.Event, result):
    def query(*_args, **_kwargs):
        if not loop_ran.wait(5):
            raise RuntimeError("the request loop was blocked")
        return result

    return query


def test_threat_report_leaves_the_request_loop_free():
    loop_ran = threading.Event()

    async def report(*_args, **_kwargs):
        return _blocks_until(loop_ran, {})()

    with patch("services.investigation.generate_threat_report", report):
        assert (
            _status_while_loop_runs(handle_threat_report, _request(), loop_ran) == 200
        )


def test_beaconing_leaves_the_request_loop_free():
    loop_ran = threading.Event()
    with patch(
        "services.threat_detection.detect_beaconing",
        side_effect=_blocks_until(loop_ran, ([], True)),
    ):
        assert _status_while_loop_runs(handle_beaconing, _request(), loop_ran) == 200


def test_risk_scores_leave_the_request_loop_free():
    loop_ran = threading.Event()
    with patch("api.risk._lan_device_buckets", side_effect=_blocks_until(loop_ran, [])):
        status = _status_while_loop_runs(
            handle_risk_scores, _request(risk_scorer=RiskScorer()), loop_ran
        )
    assert status == 200
