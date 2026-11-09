"""F1: Zeek's long-connection interim records are not summed with the final record.

Malcolm's zeek-long-connections writes cumulative interim records to conn_long.log
(event.dataset=conn, same zeek.uid) before the final conn.log record. Summing all three
counted one connection three times and inflated bytes ~9% a day on the G11 (2026-11-08).
The fake evaluates the real queries over the raw documents.
"""

from types import SimpleNamespace

from aiohttp.test_utils import AioHTTPTestCase

from api.addresses import register_address_routes
from api.logs import register_log_routes
from api.traffic import register_traffic_routes
from services import alert_findings
from services.excluded_ips import build_lan_filter
from tests.fake_drill_opensearch import (
    AUTH,
    FROM,
    TO,
    WINDOW,
    DrillOpenSearch,
    conn,
    make_app,
    matches,
)

DEVICE, SERVER = "192.168.1.20", "93.184.216.34"
STARTED = "2026-11-05T09:00:00.000Z"
CID = "1:long-lived-connection"


def _record(path, sent, received):
    """One record of the same connection; interim records carry its bytes so far."""
    return conn(
        DEVICE,
        SERVER,
        t=STARTED,
        zeek__uid="CLong1",
        network__community_id=CID,
        network__transport="tcp",
        zeek__conn__history="ShAD",
        event__start=STARTED,
        source__bytes=sent,
        destination__bytes=received,
        log__file__path=path,
    )


INTERIM_10_MIN = _record("conn_long.log", 20_000, 50_000)
INTERIM_30_MIN = _record("conn_long.log", 30_000, 77_769)
FINAL = _record("conn.log", 39_792, 100_000)  # 139,792 B, the connection's true total


def test_accounting_drops_interim_records_and_raw_keeps_them():
    from services.excluded_ips import CONN_ACCOUNTING, CONN_RECORDS

    no_path = {k: v for k, v in FINAL.items() if k != "log.file.path"}
    assert matches(FINAL, CONN_ACCOUNTING)
    # a record without a file path still counts
    assert matches(no_path, CONN_ACCOUNTING)
    assert not matches(INTERIM_10_MIN, CONN_ACCOUNTING)
    assert matches(INTERIM_10_MIN, CONN_RECORDS)
    assert matches(FINAL, CONN_RECORDS)


def _register(app, client):
    storage = SimpleNamespace(_client=client)
    app["storage"] = storage
    register_traffic_routes(app, storage)
    register_address_routes(app, client)
    register_log_routes(app, storage)


class TestOneLongConnectionCountsOnce(AioHTTPTestCase):
    async def get_application(self):
        self.os = DrillOpenSearch([INTERIM_10_MIN, INTERIM_30_MIN, FINAL])
        return make_app(
            self.os, _register, lan_filter=build_lan_filter([(192, 168, 1)])
        )

    async def _get(self, path):
        resp = await self.client.get(f"{path}?{WINDOW}", headers=AUTH)
        self.assertEqual(resp.status, 200, await resp.text())
        return await resp.json()

    async def test_the_traffic_summary_is_the_final_record_only(self):
        body = await self._get("/api/traffic/summary")
        # summed with the interim records: 317,561 B over 3 connections
        self.assertEqual(body["total_bytes"], 139_792)
        self.assertEqual(body["connection_count"], 1)

    async def test_the_connections_log_list_holds_the_connection_count(self):
        # Home's Connections count links to Log Explorer's zeek.conn list (NET-160): one row each
        summary = await self._get("/api/traffic/summary")
        resp = await self.client.get(
            f"/api/logs/search?log_type=zeek.conn&size=50&{WINDOW}", headers=AUTH
        )
        self.assertEqual(resp.status, 200, await resp.text())
        found = await resp.json()
        self.assertEqual(found["total"], summary["connection_count"])
        self.assertEqual(found["total"], 1)

    async def test_the_device_bytes_are_the_final_record_only(self):
        body = await self._get(f"/api/addresses/{DEVICE}")
        self.assertEqual(body["connections"], 1)
        self.assertEqual(body["bytes_from"]["total"], 39_792)  # sent on its connection
        self.assertEqual(body["bytes_to"]["total"], 100_000)  # received on it


def test_a_still_open_connection_still_shows_who_opened_it():
    """Only interim records exist until it ends; they prove the device opened it."""
    client = DrillOpenSearch([INTERIM_10_MIN, INTERIM_30_MIN])
    spans = alert_findings.connection_spans(client, "idx", [CID], FROM, TO)
    assert spans[CID] and all(who == DEVICE for who, _, _ in spans[CID])
