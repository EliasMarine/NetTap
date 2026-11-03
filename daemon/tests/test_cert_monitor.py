"""
Tests for daemon/services/cert_monitor.py

The inventory is built from Zeek x509 records, one row per fingerprint, and
joined to ssl sessions through zeek.ssl.cert_chain_fps. All tests use a fake
OpenSearch client.
"""

import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

from opensearchpy import OpenSearchException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.cert_monitor import (
    CertificateMonitor,
    CertQueryFailed,
    CertStatsUnavailable,
)


def _iso(days: int) -> str:
    """An OpenSearch-style date string `days` from now."""
    when = datetime.now(timezone.utc) + timedelta(days=days)
    return when.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _terms(keys) -> dict:
    return {"buckets": [{"key": k, "doc_count": 1} for k in keys]}


def _x509_bucket(
    fp: str,
    cn: str = "example.com",
    issuer_cn: str = "R11",
    issuer_org: str = "Let's Encrypt",
    not_after_days: int | None = 200,
    self_signed: bool = False,
    doc_count: int = 2,
) -> dict:
    """A terms bucket of the x509 inventory aggregation."""
    issuer_full = f"CN={issuer_cn},O={issuer_org},C=US"
    x509 = {
        "fingerprint": fp,
        "certificate_subject": {"CN": cn},
        "certificate_subject_full": issuer_full if self_signed else f"CN={cn}",
        "certificate_issuer": {"CN": issuer_cn, "O": issuer_org, "C": "US"},
        "certificate_issuer_full": issuer_full,
        "certificate_not_valid_before": _iso(-90),
        "certificate_key_type": "rsa",
        "certificate_key_length": 2048,
        "certificate_sig_alg": "sha256WithRSAEncryption",
        "san_dns": [cn, f"www.{cn}"],
    }
    if not_after_days is not None:
        x509["certificate_not_valid_after"] = _iso(not_after_days)
    return {
        "key": fp,
        "doc_count": doc_count,
        "first_seen": {"value": 1.0, "value_as_string": "2026-10-28T10:00:00.000Z"},
        "last_seen": {"value": 2.0, "value_as_string": "2026-10-31T10:00:00.000Z"},
        "latest": {"hits": {"hits": [{"_source": {"zeek": {"x509": x509}}}]}},
    }


def _session_bucket(
    fp: str,
    server_names=("example.com",),
    clients=("192.168.1.10",),
    doc_count: int = 7,
) -> dict:
    """A terms bucket of the ssl session join aggregation."""
    return {
        "key": fp,
        "doc_count": doc_count,
        "first_seen": {"value_as_string": "2026-10-27T09:00:00.000Z"},
        "last_seen": {"value_as_string": "2026-11-01T09:00:00.000Z"},
        "server_names": _terms(server_names),
        "clients": _terms(clients),
        "servers": _terms(["93.184.216.34"]),
        "ports": _terms([443]),
        "versions": _terms(["TLSv12"]),
        "validation": _terms(["ok"]),
    }


def _kind(body: dict) -> str:
    aggs = body.get("aggs", {})
    # "hits": a plain document fetch, which the old session-based code made
    return next((k for k in ("certs", "fps", "total", "all") if k in aggs), "hits")


class FakeOpenSearch:
    """Answers each query kind from canned buckets and records the bodies.

    Like OpenSearch, a terms list keeps only its top `size` buckets (#96) and a
    composite ("all") pages through every bucket.
    """

    def __init__(self, certs=(), sessions=(), stats=None, fail=()) -> None:
        self.certs = list(certs)
        self.sessions = list(sessions)
        self.stats = stats or {}
        self.fail = set(fail)
        self.bodies: list[dict] = []

    def search(self, index: str, body: dict) -> dict:
        self.bodies.append(body)
        kind = _kind(body)
        if kind in self.fail:
            raise OpenSearchException("boom")
        if kind == "certs":
            return {"aggregations": {"certs": {"buckets": self._certs(body)}}}
        if kind == "fps":
            return {"aggregations": {"fps": {"buckets": self._sessions(body)}}}
        if kind == "all":
            return {"aggregations": {"all": self._page(body)}}
        if kind == "hits":
            return {"hits": {"hits": []}}
        return {"aggregations": self.stats}

    def _certs(self, body: dict) -> list[dict]:
        wanted = next(
            (
                f["terms"]["zeek.x509.fingerprint"]
                for f in _filters(body)
                if "zeek.x509.fingerprint" in f.get("terms", {})
            ),
            None,
        )
        certs = [c for c in self.certs if wanted is None or c["key"] in wanted]
        return certs[: body["aggs"]["certs"]["terms"]["size"]]

    def _sessions(self, body: dict) -> list[dict]:
        size = body["aggs"]["fps"]["aggs"]["server_names"]["terms"]["size"]
        return [
            {**s, "server_names": {"buckets": s["server_names"]["buckets"][:size]}}
            for s in self.sessions
        ]

    def _page(self, body: dict) -> dict:
        if "after" in body["aggs"]["all"]["composite"]:
            return {"buckets": []}
        if {"term": {"event.dataset": "x509"}} in _filters(body):
            buckets = [
                {
                    "key": {"fp": c["key"]},
                    "doc_count": c["doc_count"],
                    "latest": c["latest"],
                }
                for c in self.certs
            ]
        else:
            buckets = [
                {"key": {"fp": s["key"], "name": n["key"]}, "doc_count": 1}
                for s in self.sessions
                for n in s["server_names"]["buckets"]
            ]
        return {
            "buckets": buckets,
            **({"after_key": buckets[-1]["key"]} if buckets else {}),
        }

    def body(self, kind: str) -> dict:
        return next(b for b in self.bodies if _kind(b) == kind)


def _filters(body: dict) -> list[dict]:
    return body["query"]["bool"]["filter"]


class TestInventory(unittest.TestCase):
    def test_one_row_per_fingerprint_with_x509_details(self):
        fake = FakeOpenSearch(certs=[_x509_bucket("aa"), _x509_bucket("bb", "b.io")])
        certs = CertificateMonitor(fake).get_certificates()

        self.assertEqual([c["fingerprint"] for c in certs], ["aa", "bb"])
        cert = certs[0]
        self.assertEqual(cert["_id"], "aa")
        self.assertEqual(cert["hash_sha256"], "aa")
        self.assertEqual(cert["subject"], "example.com")
        self.assertEqual(cert["subject_full"], "CN=example.com")
        self.assertEqual(cert["issuer"], "R11")
        self.assertEqual(cert["issuer_org"], "Let's Encrypt")
        self.assertTrue(cert["not_after"])
        self.assertTrue(cert["not_before"])
        self.assertEqual(cert["key_type"], "rsa")
        self.assertEqual(cert["key_length"], 2048)
        self.assertEqual(cert["san_dns"], ["example.com", "www.example.com"])
        self.assertEqual(cert["status"], "valid")
        self.assertFalse(cert["self_signed"])

    def test_queries_x509_records_aggregated_by_fingerprint(self):
        fake = FakeOpenSearch(certs=[_x509_bucket("aa")])
        CertificateMonitor(fake).get_certificates()

        body = fake.body("certs")
        self.assertEqual(body["size"], 0)
        self.assertEqual(
            body["aggs"]["certs"]["terms"]["field"], "zeek.x509.fingerprint"
        )
        filters = _filters(body)
        self.assertIn({"term": {"event.dataset": "x509"}}, filters)
        self.assertIn({"terms": {"zeek.x509.host_cert": ["true", "T"]}}, filters)

    def test_joins_ssl_sessions_by_chain_fingerprint(self):
        fake = FakeOpenSearch(
            certs=[_x509_bucket("aa", cn="*.example.com"), _x509_bucket("bb", "b.io")],
            sessions=[
                _session_bucket(
                    "aa", ("api.example.com",), ("192.168.1.10", "192.168.1.11")
                )
            ],
        )
        joined, unjoined = CertificateMonitor(fake).get_certificates()

        self.assertEqual(joined["domain"], "api.example.com")
        self.assertEqual(joined["server_names"], ["api.example.com"])
        self.assertEqual(joined["clients"], ["192.168.1.10", "192.168.1.11"])
        self.assertEqual(joined["source_ip"], "192.168.1.10")
        self.assertEqual(joined["destination_port"], 443)
        self.assertEqual(joined["tls_version"], "TLSv12")
        self.assertEqual(joined["validation_status"], "ok")
        self.assertEqual(joined["times_seen"], 7)
        self.assertEqual(joined["last_seen"], "2026-11-01T09:00:00.000Z")
        # No session in range: names from the cert, counts from x509 records
        self.assertEqual(unjoined["domain"], "b.io")
        self.assertEqual(unjoined["server_names"], [])
        self.assertEqual(unjoined["times_seen"], 2)
        self.assertEqual(unjoined["last_seen"], "2026-10-31T10:00:00.000Z")

        body = fake.body("fps")
        self.assertIn({"term": {"event.dataset": "ssl"}}, _filters(body))
        self.assertIn(
            {"terms": {"zeek.ssl.cert_chain_fps": ["aa", "bb"]}}, _filters(body)
        )
        terms = body["aggs"]["fps"]["terms"]
        self.assertEqual(terms["field"], "zeek.ssl.cert_chain_fps")
        self.assertEqual(terms["include"], ["aa", "bb"])

    def test_excluded_ips_narrow_the_session_join(self):
        fake = FakeOpenSearch(certs=[_x509_bucket("aa")])
        CertificateMonitor(fake).get_certificates(excluded_ips=["192.168.1.50"])

        must_not = fake.body("fps")["query"]["bool"]["must_not"]
        self.assertEqual(must_not, [{"terms": {"source.ip": ["192.168.1.50"]}}])

    def test_empty_index_returns_no_rows_and_skips_join(self):
        fake = FakeOpenSearch()
        self.assertEqual(CertificateMonitor(fake).get_certificates(), [])
        self.assertEqual(len(fake.bodies), 1)

    def test_opensearch_error_raises_and_logs(self):
        """#96: [] read as "no certificates seen"."""
        fake = FakeOpenSearch(certs=[_x509_bucket("aa")], fail={"certs"})
        monitor = CertificateMonitor(fake)
        for read in (
            monitor.get_certificates,
            monitor.get_expiring_certs,
            monitor.detect_self_signed,
        ):
            with self.assertLogs("nettap.services.cert_monitor", "ERROR"):
                with self.assertRaises(CertQueryFailed, msg=read.__name__):
                    read()

    def test_session_join_error_raises(self):
        """#96: rows without their sessions showed no clients and x509 relog counts as times seen."""
        fake = FakeOpenSearch(certs=[_x509_bucket("aa")], fail={"fps"})
        with self.assertLogs("nettap.services.cert_monitor", "ERROR"):
            with self.assertRaises(CertQueryFailed):
                CertificateMonitor(fake).get_certificates()

    def test_missing_expiry_is_valid_with_no_day_count(self):
        fake = FakeOpenSearch(certs=[_x509_bucket("aa", not_after_days=None)])
        cert = CertificateMonitor(fake).get_certificates()[0]
        self.assertEqual(cert["status"], "valid")
        self.assertIsNone(cert["days_until_expiry"])

    def test_queries_use_malcolm_field_names_not_keyword(self):
        fake = FakeOpenSearch(certs=[_x509_bucket("aa")])
        monitor = CertificateMonitor(fake)
        monitor.get_certificates()
        monitor.get_expiring_certs()
        monitor.detect_self_signed()
        monitor.get_cert_stats()
        self.assertNotIn(".keyword", json.dumps(fake.bodies))


class TestExpiring(unittest.TestCase):
    def test_filters_on_not_valid_after_and_labels_status(self):
        fake = FakeOpenSearch(
            certs=[
                _x509_bucket("old", not_after_days=-5),
                _x509_bucket("soon", not_after_days=10),
            ]
        )
        expired, expiring = CertificateMonitor(fake).get_expiring_certs(days=30)

        self.assertEqual(expired["status"], "expired")
        self.assertEqual(expired["days_until_expiry"], 0)
        self.assertEqual(expiring["status"], "expiring")
        self.assertIn(expiring["days_until_expiry"], (9, 10))
        range_filter = {
            "range": {"zeek.x509.certificate_not_valid_after": {"lte": "now+30d"}}
        }
        self.assertIn(range_filter, _filters(fake.body("certs")))

    def test_window_beyond_warning_still_labels_expiring(self):
        fake = FakeOpenSearch(certs=[_x509_bucket("aa", not_after_days=45)])
        cert = CertificateMonitor(fake).get_expiring_certs(days=60)[0]
        self.assertEqual(cert["status"], "expiring")

    def test_days_are_clamped(self):
        for days, expected in ((-5, "now+0d"), (10**9, "now+3650d")):
            fake = FakeOpenSearch()
            CertificateMonitor(fake).get_expiring_certs(days=days)
            dumped = json.dumps(_filters(fake.body("certs")))
            self.assertIn(expected, dumped)


class TestSelfSigned(unittest.TestCase):
    def test_subject_equal_to_issuer_is_self_signed(self):
        fake = FakeOpenSearch(
            certs=[_x509_bucket("ss", "router.lan", self_signed=True)]
        )
        cert = CertificateMonitor(fake).detect_self_signed()[0]

        self.assertEqual(cert["status"], "self-signed")
        self.assertTrue(cert["self_signed"])
        self.assertEqual(cert["detection_reason"], "subject matches issuer")
        scripts = [f for f in _filters(fake.body("certs")) if "script" in f]
        self.assertEqual(len(scripts), 1)
        self.assertIn("certificate_subject_full", json.dumps(scripts))


class TestIssuerChanges(unittest.TestCase):
    def _changes(self, certs, sessions=()):
        fake = FakeOpenSearch(certs=certs, sessions=sessions)
        return CertificateMonitor(fake).detect_issuer_changes()

    def test_flags_server_name_served_by_two_cas(self):
        changes = self._changes(
            [
                _x509_bucket("a", "bank.com", issuer_org="DigiCert Inc"),
                _x509_bucket("b", "bank.com", issuer_org="Evil CA"),
            ],
            [_session_bucket("a", ("bank.com",)), _session_bucket("b", ("bank.com",))],
        )
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["domain"], "bank.com")
        self.assertEqual(changes[0]["issuers"], ["DigiCert Inc", "Evil CA"])
        self.assertEqual(changes[0]["issuer_count"], 2)
        self.assertEqual(len(changes[0]["certificates"]), 2)

    def test_intermediate_rotation_is_not_a_change(self):
        changes = self._changes(
            [
                _x509_bucket("a", "site.org", issuer_cn="R10"),
                _x509_bucket("b", "site.org", issuer_cn="R11"),
            ]
        )
        self.assertEqual(changes, [])

    def test_empty_index_has_no_changes(self):
        self.assertEqual(self._changes([]), [])

    def test_change_beyond_the_newest_1000_certificates_is_found(self):
        """#96: only the newest 1,000 certificates were compared; the older one went unseen."""
        fillers = [_x509_bucket(f"f{i}", f"site{i}.com") for i in range(1000)]
        fake = FakeOpenSearch(
            certs=[
                _x509_bucket("new", "bank.com", issuer_org="DigiCert Inc"),
                *fillers,
                _x509_bucket("old", "bank.com", issuer_org="Evil CA"),
            ]
        )
        monitor = CertificateMonitor(fake)
        changes = monitor.detect_issuer_changes()

        self.assertEqual([c["domain"] for c in changes], ["bank.com"])
        self.assertEqual(changes[0]["issuers"], ["DigiCert Inc", "Evil CA"])
        fps = {c["fingerprint"] for c in changes[0]["certificates"]}
        self.assertEqual(fps, {"new", "old"})
        self.assertEqual(monitor.get_cert_stats()["issuer_changes_count"], 1)

    def test_every_server_name_of_a_certificate_is_compared(self):
        """#96: only a certificate's 10 busiest server names were compared."""
        names = (*(f"n{i}.example.com" for i in range(10)), "shop.example.com")
        changes = self._changes(
            [
                _x509_bucket("wild", "*.example.com"),
                _x509_bucket("other", "shop.example.com", issuer_org="Evil CA"),
            ],
            [
                _session_bucket("wild", names),
                _session_bucket("other", ("shop.example.com",)),
            ],
        )
        self.assertEqual([c["domain"] for c in changes], ["shop.example.com"])


class TestStats(unittest.TestCase):
    def test_counts_are_distinct_certificates_not_a_fetch_cap(self):
        """Fails against the old code, which counted fetched ssl sessions."""
        stats = {
            "total": {"value": 42},
            "expiring": {"doc_count": 5, "n": {"value": 3}},
            "expired": {"doc_count": 2, "n": {"value": 2}},
            "self_signed": {"doc_count": 1, "n": {"value": 1}},
        }
        fake = FakeOpenSearch(certs=[_x509_bucket("aa")], stats=stats)
        result = CertificateMonitor(fake).get_cert_stats()

        self.assertEqual(result["total_certs"], 42)
        self.assertEqual(result["expiring_count"], 3)
        self.assertEqual(result["expired_count"], 2)
        self.assertEqual(result["self_signed_count"], 1)
        self.assertEqual(result["issuer_changes_count"], 0)
        body = fake.body("total")
        self.assertEqual(body["size"], 0)
        self.assertEqual(
            body["aggs"]["total"]["cardinality"]["field"], "zeek.x509.fingerprint"
        )
        self.assertIn({"term": {"event.dataset": "x509"}}, _filters(body))

    # OLD CODE START — 2026-11-02: zeros on failure showed "0 certificates" as fact
    # def test_opensearch_error_returns_zero_counts(self):
    #     fake = FakeOpenSearch(fail={"total", "certs"})
    #     with self.assertLogs("nettap.services.cert_monitor", "ERROR"):
    #         result = CertificateMonitor(fake).get_cert_stats()
    #     for key in (
    #         "total_certs",
    #         "expiring_count",
    #         "expired_count",
    #         "self_signed_count",
    #     ):
    #         self.assertEqual(result[key], 0)

    # OLD CODE END

    def test_opensearch_error_raises_instead_of_zero_counts(self):
        """The G11 card read 0 while 85 certificates existed (query failed, logged)."""
        fake = FakeOpenSearch(fail={"total", "certs"})
        with self.assertLogs("nettap.services.cert_monitor", "ERROR"):
            with self.assertRaises(CertQueryFailed):
                CertificateMonitor(fake).get_cert_stats()

    def test_stats_reply_without_aggregations_raises(self):
        fake = FakeOpenSearch(certs=[_x509_bucket("aa")])
        fake.search = lambda index, body: {}
        with self.assertRaises(CertStatsUnavailable):
            CertificateMonitor(fake).get_cert_stats()

    def test_stats_aggregations_use_absolute_times(self):
        """A "now" range in a filter agg trips an OpenSearch 2.x createWeight bug."""
        fake = FakeOpenSearch(certs=[_x509_bucket("aa")], stats={"total": {"value": 1}})
        CertificateMonitor(fake).get_cert_stats()
        aggs = json.dumps(fake.body("total")["aggs"])
        self.assertNotIn('"now', aggs)
        self.assertIn("certificate_not_valid_after", aggs)


if __name__ == "__main__":
    unittest.main()


# OLD CODE START — 2026-11-01: these tested the session-based inventory, which read
# zeek.ssl.* / tls.server.* cert fields that Zeek 6+ ssl.log does not carry.
# """
# Tests for daemon/services/cert_monitor.py
#
# Covers certificate listing, expiry detection, self-signed detection,
# and issuer change detection. All tests use mocked OpenSearch.
# """
#
# import os
# import sys
# import unittest
# from datetime import datetime, timedelta, timezone
# from unittest.mock import MagicMock
#
# sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
#
# from services.cert_monitor import CertificateMonitor
#
#
# def _make_ssl_hit(
#     _id: str,
#     domain: str = "example.com",
#     subject: str = "example.com",
#     issuer: str = "Let's Encrypt",
#     not_before: str = "2026-01-01T00:00:00Z",
#     not_after: str = "2026-12-31T00:00:00Z",
#     validation_status: str = "ok",
#     source_ip: str = "192.168.1.100",
#     dest_ip: str = "93.184.216.34",
# ) -> dict:
#     """Build a fake OpenSearch SSL log hit."""
#     return {
#         "_id": _id,
#         "_source": {
#             "@timestamp": "2026-03-08T10:00:00Z",
#             "tls": {
#                 "server": {
#                     "subject": subject,
#                     "issuer": issuer,
#                     "not_before": not_before,
#                     "not_after": not_after,
#                     "hash": {"sha256": "abc123def456"},
#                     "x509": {
#                         "subject": {"common_name": subject},
#                         "issuer": {"common_name": issuer},
#                         "not_before": not_before,
#                         "not_after": not_after,
#                     },
#                 },
#                 "version": "TLSv1.3",
#             },
#             "destination": {"domain": domain, "ip": dest_ip, "port": 443},
#             "source": {"ip": source_ip},
#             "zeek": {
#                 "ssl": {
#                     "server_name": domain,
#                     "subject": subject,
#                     "issuer": issuer,
#                     "not_valid_before": not_before,
#                     "not_valid_after": not_after,
#                     "validation_status": validation_status,
#                 }
#             },
#             "event": {"provider": "zeek", "dataset": "ssl"},
#         },
#     }
#
#
# class TestCertificateMonitorGetCertificates(unittest.TestCase):
#     """Tests for CertificateMonitor.get_certificates()."""
#
#     def setUp(self):
#         self.mock_client = MagicMock()
#         self.monitor = CertificateMonitor(client=self.mock_client)
#
#     def test_get_certificates_returns_normalized_certs(self):
#         """get_certificates() normalizes SSL hits into cert records."""
#         self.mock_client.search.return_value = {
#             "hits": {
#                 "hits": [
#                     _make_ssl_hit("cert-1", domain="google.com", issuer="GTS CA 1C3"),
#                     _make_ssl_hit("cert-2", domain="github.com", issuer="DigiCert"),
#                 ]
#             }
#         }
#
#         certs = self.monitor.get_certificates()
#         self.assertEqual(len(certs), 2)
#         self.assertEqual(certs[0]["domain"], "google.com")
#         self.assertEqual(certs[0]["issuer"], "GTS CA 1C3")
#         self.assertEqual(certs[0]["_id"], "cert-1")
#         self.assertEqual(certs[1]["domain"], "github.com")
#
#     def test_get_certificates_opensearch_error(self):
#         """get_certificates() returns empty list on error."""
#         from opensearchpy import OpenSearchException
#
#         self.mock_client.search.side_effect = OpenSearchException("timeout")
#         certs = self.monitor.get_certificates()
#         self.assertEqual(certs, [])
#
#     def test_get_certificates_empty_results(self):
#         """get_certificates() returns empty list when no hits."""
#         self.mock_client.search.return_value = {"hits": {"hits": []}}
#         certs = self.monitor.get_certificates()
#         self.assertEqual(certs, [])
#
#
# class TestCertificateMonitorExpiring(unittest.TestCase):
#     """Tests for CertificateMonitor.get_expiring_certs()."""
#
#     def setUp(self):
#         self.mock_client = MagicMock()
#         self.monitor = CertificateMonitor(client=self.mock_client)
#
#     def test_detects_expiring_cert(self):
#         """get_expiring_certs() flags certs expiring within N days."""
#         # Cert expiring in 15 days
#         soon = (datetime.now(timezone.utc) + timedelta(days=15)).isoformat()
#         self.mock_client.search.return_value = {
#             "hits": {
#                 "hits": [
#                     _make_ssl_hit("cert-exp", not_after=soon),
#                 ]
#             }
#         }
#
#         certs = self.monitor.get_expiring_certs(days=30)
#         self.assertEqual(len(certs), 1)
#         self.assertEqual(certs[0]["status"], "expiring")
#         self.assertIn("days_until_expiry", certs[0])
#
#     def test_detects_expired_cert(self):
#         """get_expiring_certs() flags already-expired certs."""
#         past = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
#         self.mock_client.search.return_value = {
#             "hits": {
#                 "hits": [
#                     _make_ssl_hit("cert-expired", not_after=past),
#                 ]
#             }
#         }
#
#         certs = self.monitor.get_expiring_certs(days=30)
#         self.assertEqual(len(certs), 1)
#         self.assertEqual(certs[0]["status"], "expired")
#
#     def test_ignores_valid_cert(self):
#         """get_expiring_certs() ignores certs not expiring soon."""
#         future = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
#         self.mock_client.search.return_value = {
#             "hits": {
#                 "hits": [
#                     _make_ssl_hit("cert-valid", not_after=future),
#                 ]
#             }
#         }
#
#         certs = self.monitor.get_expiring_certs(days=30)
#         self.assertEqual(len(certs), 0)
#
#
# class TestCertificateMonitorSelfSigned(unittest.TestCase):
#     """Tests for CertificateMonitor.detect_self_signed()."""
#
#     def setUp(self):
#         self.mock_client = MagicMock()
#         self.monitor = CertificateMonitor(client=self.mock_client)
#
#     def test_detects_subject_equals_issuer(self):
#         """detect_self_signed() flags certs where subject == issuer."""
#         self.mock_client.search.return_value = {
#             "hits": {
#                 "hits": [
#                     _make_ssl_hit(
#                         "cert-ss",
#                         subject="myserver.local",
#                         issuer="myserver.local",
#                     ),
#                 ]
#             }
#         }
#
#         certs = self.monitor.detect_self_signed()
#         self.assertEqual(len(certs), 1)
#         self.assertEqual(certs[0]["detection_reason"], "subject matches issuer")
#
#     def test_detects_validation_status_self_signed(self):
#         """detect_self_signed() flags certs with self-signed validation status."""
#         self.mock_client.search.return_value = {
#             "hits": {
#                 "hits": [
#                     _make_ssl_hit(
#                         "cert-ss2",
#                         subject="server.local",
#                         issuer="My CA",
#                         validation_status="self signed certificate",
#                     ),
#                 ]
#             }
#         }
#
#         certs = self.monitor.detect_self_signed()
#         self.assertEqual(len(certs), 1)
#
#     def test_ignores_valid_ca_signed(self):
#         """detect_self_signed() ignores properly CA-signed certs."""
#         self.mock_client.search.return_value = {
#             "hits": {
#                 "hits": [
#                     _make_ssl_hit("cert-ok", subject="example.com", issuer="DigiCert"),
#                 ]
#             }
#         }
#
#         certs = self.monitor.detect_self_signed()
#         self.assertEqual(len(certs), 0)
#
#
# class TestCertificateMonitorIssuerChanges(unittest.TestCase):
#     """Tests for CertificateMonitor.detect_issuer_changes()."""
#
#     def setUp(self):
#         self.mock_client = MagicMock()
#         self.monitor = CertificateMonitor(client=self.mock_client)
#
#     def test_detects_multiple_issuers(self):
#         """detect_issuer_changes() flags domains with multiple issuers."""
#         self.mock_client.search.return_value = {
#             "hits": {
#                 "hits": [
#                     _make_ssl_hit("c1", domain="bank.com", issuer="DigiCert"),
#                     _make_ssl_hit("c2", domain="bank.com", issuer="Unknown CA"),
#                 ]
#             }
#         }
#
#         changes = self.monitor.detect_issuer_changes()
#         self.assertEqual(len(changes), 1)
#         self.assertEqual(changes[0]["domain"], "bank.com")
#         self.assertEqual(changes[0]["issuer_count"], 2)
#         self.assertIn("DigiCert", changes[0]["issuers"])
#         self.assertIn("Unknown CA", changes[0]["issuers"])
#
#     def test_no_changes_single_issuer(self):
#         """detect_issuer_changes() returns empty for single-issuer domains."""
#         self.mock_client.search.return_value = {
#             "hits": {
#                 "hits": [
#                     _make_ssl_hit("c1", domain="google.com", issuer="GTS CA 1C3"),
#                     _make_ssl_hit("c2", domain="google.com", issuer="GTS CA 1C3"),
#                 ]
#             }
#         }
#
#         changes = self.monitor.detect_issuer_changes()
#         self.assertEqual(len(changes), 0)
#
#     def test_empty_results(self):
#         """detect_issuer_changes() returns empty for no certs."""
#         self.mock_client.search.return_value = {"hits": {"hits": []}}
#         changes = self.monitor.detect_issuer_changes()
#         self.assertEqual(changes, [])
#
#
# class TestCertificateMonitorStats(unittest.TestCase):
#     """Tests for CertificateMonitor.get_cert_stats()."""
#
#     def setUp(self):
#         self.mock_client = MagicMock()
#         self.monitor = CertificateMonitor(client=self.mock_client)
#
#     def test_stats_aggregates_counts(self):
#         """get_cert_stats() returns correct aggregate counts."""
#         soon = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
#         self.mock_client.search.return_value = {
#             "hits": {
#                 "hits": [
#                     _make_ssl_hit("c1", domain="a.com", issuer="CA1", not_after=soon),
#                     _make_ssl_hit("c2", domain="b.com", subject="self", issuer="self"),
#                     _make_ssl_hit("c3", domain="c.com", issuer="CA2"),
#                     _make_ssl_hit("c4", domain="c.com", issuer="CA3"),
#                 ]
#             }
#         }
#
#         stats = self.monitor.get_cert_stats()
#         self.assertEqual(stats["total_certs"], 4)
#         self.assertGreaterEqual(stats["expiring_count"], 1)
#         self.assertGreaterEqual(stats["self_signed_count"], 1)
#         self.assertGreaterEqual(stats["issuer_changes_count"], 1)
#
#
# class TestCertificateMonitorNormalize(unittest.TestCase):
#     """Tests for the _normalize_cert static method."""
#
#     def test_normalize_ecs_fields(self):
#         """_normalize_cert extracts ECS TLS fields."""
#         src = {
#             "@timestamp": "2026-03-08T10:00:00Z",
#             "tls": {
#                 "server": {
#                     "subject": "example.com",
#                     "issuer": "CA",
#                     "not_before": "2026-01-01",
#                     "not_after": "2026-12-31",
#                     "hash": {"sha256": "abc"},
#                     "x509": {
#                         "subject": {"common_name": "example.com"},
#                         "issuer": {"common_name": "CA"},
#                         "not_before": "2026-01-01",
#                         "not_after": "2026-12-31",
#                     },
#                 },
#                 "version": "TLSv1.3",
#             },
#             "destination": {"domain": "example.com", "ip": "1.2.3.4", "port": 443},
#             "source": {"ip": "192.168.1.1"},
#             "zeek": {"ssl": {}},
#         }
#
#         cert = CertificateMonitor._normalize_cert(src)
#         self.assertEqual(cert["domain"], "example.com")
#         self.assertEqual(cert["issuer"], "CA")
#         self.assertEqual(cert["tls_version"], "TLSv1.3")
#
#     def test_normalize_zeek_fallback(self):
#         """_normalize_cert falls back to Zeek-native fields."""
#         src = {
#             "@timestamp": "2026-03-08T10:00:00Z",
#             "tls": {"server": {}},
#             "destination": {},
#             "source": {},
#             "zeek": {
#                 "ssl": {
#                     "server_name": "test.local",
#                     "subject": "test.local",
#                     "issuer": "Self",
#                     "not_valid_before": "2026-01-01",
#                     "not_valid_after": "2026-12-31",
#                     "validation_status": "self signed certificate",
#                 }
#             },
#         }
#
#         cert = CertificateMonitor._normalize_cert(src)
#         self.assertEqual(cert["domain"], "test.local")
#         self.assertEqual(cert["issuer"], "Self")
#         self.assertEqual(cert["status"], "self-signed")
#
#
# if __name__ == "__main__":
#     unittest.main()
# OLD CODE END
