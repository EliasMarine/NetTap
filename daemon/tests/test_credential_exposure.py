"""Credential exposure ET rates Informational/Unknown counts (NET-228, release audit B-i).

ET rates "ET INFO Outgoing Basic Auth Base64 HTTP Password detected unencrypted" and
"GPL WEB_SERVER .htpasswd access" Informational/Unknown, so every count left them out without the
page saying so, though the owner can act on them. Such a record counts now, as medium (3); every
other rule keeps its classification. The query (ET_ACTIVITY_CLAUSE) and the smart-alert severity
(reclassify_severity) must agree record by record.
"""

import os
import sys
from fnmatch import fnmatchcase
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.alerts import ET_ACTIVITY_CLAUSE, alert_query
from services import alert_intelligence
from services.alert_findings import is_credential_exposure
from services.alert_intelligence import get_smart_alerts, reclassify_severity

_FROM, _TO = "2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z"
_RATING = "suricata.alert.metadata.signature_severity"
_BASIC_AUTH = "ET INFO Outgoing Basic Auth Base64 HTTP Password detected unencrypted"


# --- a test-only evaluator for the clause shapes used here (bool, terms, wildcard) ---------------


def _values(doc: dict, field: str) -> list:
    value = doc.get(field)
    return value if isinstance(value, list) else [] if value is None else [value]


def _matches(clause: dict, doc: dict) -> bool:
    if "bool" in clause:
        b = clause["bool"]
        should = b.get("should", [])
        return (
            all(_matches(c, doc) for c in b.get("filter", []))
            and not any(_matches(c, doc) for c in b.get("must_not", []))
            and (
                not should
                or sum(_matches(c, doc) for c in should)
                >= b.get("minimum_should_match", 1)
            )
        )
    if "terms" in clause:
        ((field, wanted),) = clause["terms"].items()
        return any(v in wanted for v in _values(doc, field))
    if "wildcard" in clause:
        ((field, spec),) = clause["wildcard"].items()
        assert spec["case_insensitive"] is True
        pattern = spec["value"].lower()
        return any(fnmatchcase(str(v).lower(), pattern) for v in _values(doc, field))
    raise AssertionError(f"unsupported clause {clause}")


def _doc(name: str, rating) -> dict:
    return {"rule.name": name, _RATING: rating}


# name, rating, activity (listed, not counted), counted, promotion_eligible
_TABLE = [
    (_BASIC_AUTH, ["Informational"], False, True, True),
    (_BASIC_AUTH, "Informational", False, True, True),  # a scalar, not Malcolm's list
    (
        "ET INFO Http Client Body contains pwd= in cleartext",
        ["Informational"],
        False,
        True,
        True,
    ),
    ("GPL WEB_SERVER .htpasswd access", ["Unknown"], False, True, True),
    (
        "ET SCAN SFTP/FTP Password Exposure via sftp-config.json",
        ["Informational"],
        False,
        True,
        True,
    ),
    # mixed list: ET rated it Major somewhere, so it is not a promotion; it stays where it was
    (_BASIC_AUTH, ["Informational", "Major"], True, False, False),
    # ET-rated and unrated rules were counted already, and are not promotions
    ("ET TROJAN Password Stealer", ["Major"], False, True, False),
    ("ET TROJAN Password Stealer", None, False, True, False),
    # an admin event, not a secret exposed: stays activity
    ("ET INFO external cPanel password change", ["Informational"], True, False, False),
    (
        "ET INFO F5 BIG-IP - Failed Auth Due To Expired Password",
        ["Informational"],
        True,
        False,
        False,
    ),
    # informational without a secret in the name stays activity
    ("ET P2P BitTorrent DHT ping request", ["Informational"], True, False, False),
    ("ET INFO Session Traversal Utilities for NAT", ["Unknown"], True, False, False),
]


@pytest.mark.parametrize("name,rating,activity,counted,eligible", _TABLE)
def test_the_query_and_python_agree_record_by_record(
    name, rating, activity, counted, eligible
):
    doc = _doc(name, rating)
    assert _matches(ET_ACTIVITY_CLAUSE, doc) is activity
    # the counted query drops what the activity clause matches; nothing else here
    assert (not _matches(ET_ACTIVITY_CLAUSE, doc)) is counted
    assert is_credential_exposure(name, rating) is eligible


def test_the_list_and_the_count_still_use_the_one_clause():
    counted = alert_query(_FROM, _TO)["bool"]
    listed = alert_query(_FROM, _TO, activity=True)["bool"]
    assert ET_ACTIVITY_CLAUSE in counted["must_not"]
    assert ET_ACTIVITY_CLAUSE in listed["filter"]


# --- severity ----------------------------------------------------------------------------------


def test_a_promoted_record_is_medium_not_context():
    # OLD: ET INFO is a context prefix, so 5 and never counted
    assert reclassify_severity(_BASIC_AUTH, 1, et_severity=["Informational"]) == 3
    assert (
        reclassify_severity(
            "GPL WEB_SERVER .htpasswd access", 1, et_severity=["Unknown"]
        )
        == 3
    )


def test_other_classifications_are_unchanged():
    assert reclassify_severity("ET TROJAN Password Stealer", 1, et_severity=None) == 1
    assert (
        reclassify_severity("ET TROJAN Password Stealer", 1, et_severity=["Major"]) == 2
    )
    assert (
        reclassify_severity(_BASIC_AUTH, 1, et_severity=["Minor"]) == 5
    )  # context prefix, as before
    assert (
        reclassify_severity(
            "ET P2P BitTorrent DHT ping request", 1, et_severity=["Informational"]
        )
        == 5
    )


# --- group severity: the strongest record, not the newest sample --------------------------------


def _bucket(sig, count, sample_rating, ratings=None, unrated=0, sev=1):
    bucket = {
        "key": {"sig_name": sig, "src_ip": "192.0.2.10", "dst_ip": "198.51.100.7"},
        "doc_count": count,
        "first_seen": {"value_as_string": "2026-11-01T01:00:00Z"},
        "last_seen": {"value_as_string": "2026-11-01T02:00:00Z"},
        "sample": {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "alert": {
                                "signature": sig,
                                "signature_id": 2006380,
                                "severity": sev,
                                "category": "x",
                            },
                            "suricata": {
                                "alert": {
                                    "metadata": {"signature_severity": sample_rating}
                                }
                            },
                        }
                    }
                ]
            }
        },
    }
    if ratings is not None:
        bucket["et_ratings"] = {
            "buckets": [{"key": r, "doc_count": n} for r, n in ratings]
        }
        bucket["et_unrated"] = {"doc_count": unrated}
    return bucket


def _groups(*buckets):
    client = MagicMock()

    def search(index, body):
        if "all" in body["aggs"]:  # the alert-instant read finds none here
            return {"aggregations": {"all": {"buckets": []}}}
        return {"aggregations": {"grouped": {"buckets": list(buckets)}}}

    client.search.side_effect = search
    with patch.object(alert_intelligence, "is_suppressed", return_value=False):
        return get_smart_alerts(client, _FROM, _TO, limit=None)


def test_the_grouped_query_asks_for_every_rating_in_a_group():
    client = MagicMock()
    client.search.return_value = {"aggregations": {"grouped": {"buckets": []}}}
    get_smart_alerts(client, _FROM, _TO, limit=None)
    aggs = client.search.call_args.kwargs["body"]["aggs"]["grouped"]["aggs"]
    assert aggs["et_ratings"] == {"terms": {"field": _RATING, "size": 10}}
    assert aggs["et_unrated"] == {"missing": {"field": _RATING}}


@pytest.mark.parametrize("newest", ["Informational", "Major"])
def test_a_promoted_credential_group_with_a_major_record_keeps_the_strongest(newest):
    # Codex round 3 case 1: one Informational (promoted, 3) and one Major (context prefix, 5)
    (group,) = _groups(
        _bucket(_BASIC_AUTH, 2, [newest], ratings=[("Informational", 1), ("Major", 1)])
    )
    assert group["severity"] == 3


@pytest.mark.parametrize("newest", [None, ["Informational"]])
def test_an_unrated_critical_record_is_not_lowered_by_an_informational_one(newest):
    # Codex round 3 case 2: ET TROJAN unrated (prefix table, 1) and Informational (promoted, 3)
    (group,) = _groups(
        _bucket(
            "ET TROJAN Password Stealer",
            2,
            newest,
            ratings=[("Informational", 1)],
            unrated=1,
        )
    )
    assert group["severity"] == 1


def test_m_major_and_n_promoted_matches_all_count():
    # 3 Major + 4 promoted Informational in one group: 7 alerts, at the Major record's severity
    (group,) = _groups(
        _bucket(
            "ET SCAN SFTP/FTP Password Exposure via sftp-config.json",
            7,
            ["Informational"],
            ratings=[("Major", 3), ("Informational", 4)],
            sev=2,
        )
    )
    assert group["count"] == 7
    assert group["severity"] == 2
    assert (
        group["counted_events"] == 7
    )  # no LAN party here, so every alert is unattributed and counts


def test_without_the_rating_aggregation_it_reads_the_sample_as_before():
    (group,) = _groups(_bucket(_BASIC_AUTH, 1, ["Informational"]))
    assert group["severity"] == 3
