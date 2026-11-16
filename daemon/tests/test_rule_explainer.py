"""The rule page's explanations and links (services/rule_explainer.py): each family's texts,
per-SID advice from ET's own rating list, and links built only from verified templates."""

import pytest

from services import rule_explainer as rx
from services.alert_enrichment import get_recommendation

# Every URL the module can emit starts with one of these (each verified 2026-11-15, HTTP 200)
VERIFIED = (
    "https://attack.mitre.org/techniques/",
    "https://attack.mitre.org/tactics/",
    "https://nvd.nist.gov/vuln/detail/",
    "https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
    "https://www.cisa.gov/secure-our-world/recognize-and-report-phishing",
    "https://www.cisa.gov/topics/cyber-threats-and-response/malware-phishing-and-ransomware",
    "https://www.ipfire.org/dbl",
    "https://isc.sans.edu/",
    "https://cinsscore.com/",
    "https://www.spamhaus.org/blocklists/do-not-route-or-peer/",
    "https://docs.suricata.io/en/latest/rules/intro.html",
)
DBL_SENTENCE = (
    "NetTap observed traffic matching this blocklist rule. NetTap did not block it; this alert "
    "alone does not show whether the lookup or connection succeeded."
)
NAMES = [
    ("ET DROP Dshield Block Listed Source group 1", "reputation"),
    ("ET CINS Active Threat Intelligence Poor Reputation IP group 8", "reputation"),
    ("ET TOR Known Tor Exit Node Traffic group 1", "reputation"),
    ("IPFire DBL [Phishing] Blocked DNS Query", "dbl"),
    ("IPFire DBL [Malware] Blocked TLS Connection", "dbl"),
    ("IPFire DBL [Advertising] Blocked DNS Query", "dbl"),
    ("ET INFO Session Traversal Utilities for NAT (STUN Binding Request)", "info"),
    ("ET SCAN Potential SSH Scan OUTBOUND", "scan"),
    ("ET MALWARE Win32/Emotet Activity", "malware"),
    ("ET TROJAN Old style name", "malware"),
    ("ET PHISHING Successful Generic Phish", "phishing"),
    (
        "ET EXPLOIT Apache HTTP Server 2.4.49 - Path Traversal Attempt (CVE-2021-41773) M2",
        "exploit",
    ),
    ("ET WEB_SPECIFIC_APPS WordPress Plugin Gravity SMTP", "web_server"),
    ("ET DYN_DNS DYNAMIC_DNS Query to *.duckdns. Domain", "dyn_dns"),
    ("GPL P2P BitTorrent transfer", "p2p"),
    (
        "ET REMOTE_ACCESS Observed RMM Tool in TLS SNI (screenconnect .com)",
        "remote_access",
    ),
    ("ET INFO Observed Discord Domain in DNS Lookup (discord .com)", "info"),
    ("ET CHAT Discord", "apps"),
    ("ET HUNTING Suspicious Header Name In HTTP Request (U)", "hunting"),
    ("SURICATA STREAM Packet with invalid timestamp", "engine"),
    ("NETTAP my own rule", "unknown"),
    ("ET SOMETHING_NEW thing", "unknown"),
]


@pytest.mark.parametrize("name, family", NAMES)
def test_each_name_gets_its_family_and_full_texts(name, family):
    texts = rx.explain_name(name, 2)
    assert texts["family"] == family
    assert all(texts[k] for k in ("what", "risk", "todo"))
    # UK spelling and the ellipsis character in every text the app shows
    for k in ("what", "risk", "todo"):
        assert "..." not in texts[k]


def test_existing_advice_is_reused_where_it_fits():
    assert rx.explain_name("ET DROP Dshield x", 2)["todo"] == get_recommendation("drop")
    assert rx.explain_name("ET SCAN y", 2)["todo"] == get_recommendation("scan")
    assert rx.explain_name("ET POLICY z", 2)["todo"] == get_recommendation("policy")


def test_a_dbl_rule_never_claims_the_traffic_went_through_or_was_blocked():
    for name in (
        "IPFire DBL [Phishing] Blocked DNS Query",
        "IPFire DBL [Malware] Blocked TLS Connection",
    ):
        texts = rx.explain_name(name, 1)
        assert texts["risk"].startswith(DBL_SENTENCE)
        assert "went through" not in " ".join(texts.values())
    assert (
        "phishing list"
        in rx.explain_name("IPFire DBL [Phishing] Blocked DNS Query", 1)["what"]
    )


def test_an_unknown_name_falls_back_to_the_generic_texts():
    texts = rx.explain_name("Something odd", 1)
    assert texts == {
        "family": "unknown",
        "what": "Rule matched: Something odd",
        "risk": texts["risk"],
        "todo": get_recommendation("unknown"),
    }
    assert "high priority" in texts["risk"]


@pytest.mark.parametrize(
    "ratings, credential",
    [
        (["Informational"], True),
        (["Unknown"], True),
        (["Major"], False),
        (["Informational", "Major"], False),
        ([], False),
    ],
)
def test_sid_advice_reads_et_rating_lists(ratings, credential):
    name = "ET POLICY Outgoing Basic Auth Base64 HTTP Password detected unencrypted"
    advice = rx.sid_advice(None, name, ratings)
    assert (
        advice == {k: rx.CREDENTIAL[k] for k in ("what", "risk", "todo")}
    ) is credential
    assert (advice is None) is not credential


def test_a_curated_description_wins_and_a_plain_rule_has_no_advice():
    curated = {"what": "w", "risk": "r", "todo": "t"}
    assert (
        rx.sid_advice(curated, "ET INFO Cleartext Password", ["Informational"])
        == curated
    )
    assert rx.sid_advice(None, "ET INFO plain", ["Informational"]) is None


def test_own_sids_are_the_owner_range_only():
    assert rx.is_own_sid("1000001") and rx.is_own_sid("1999999")
    assert not any(rx.is_own_sid(s) for s in ("999999", "2000000", "", None, "12a"))


def test_sid_links_from_validated_ids_only():
    links = rx.sid_links(
        [{"id": "T1071.001", "name": "Web Protocols"}, {"id": "T1190", "name": None}],
        [{"id": "TA0011", "name": "Command and Control"}],
        ["CVE-2021-41773"],
        True,
        True,
    )
    assert [link["url"] for link in links] == [
        "https://nvd.nist.gov/vuln/detail/CVE-2021-41773",
        "https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
        "https://attack.mitre.org/techniques/T1071/001/",
        "https://attack.mitre.org/techniques/T1190/",
        "https://attack.mitre.org/tactics/TA0011/",
        "https://attack.mitre.org/techniques/T1552/",
    ]
    assert links[2]["label"] == "MITRE ATT&CK T1071.001: Web Protocols"
    assert links[3]["label"] == "MITRE ATT&CK T1190: Exploit Public-Facing Application"
    bad = rx.sid_links(
        [{"id": "X1", "name": None}],
        [{"id": "TA1", "name": None}],
        ["CVE-12"],
        False,
        False,
    )
    assert bad == []


def test_name_links_end_with_the_suricata_docs_and_stay_capped():
    dbl = rx.name_links("IPFire DBL [Advertising] Blocked DNS Query", "dbl")
    assert [link["url"] for link in dbl] == [
        "https://www.ipfire.org/dbl/lists/ads",
        rx.SURICATA_DOCS["url"],
    ]
    odd = rx.name_links("IPFire DBL [Dating] Blocked DNS Query", "dbl")
    assert odd[0]["url"] == "https://www.ipfire.org/dbl"
    phishing = rx.name_links("ET PHISHING x", "phishing")
    assert [link["url"] for link in phishing] == [
        "https://attack.mitre.org/techniques/T1566/",
        "https://www.cisa.gov/secure-our-world/recognize-and-report-phishing",
        rx.SURICATA_DOCS["url"],
    ]
    tor = rx.name_links("ET TOR Known Tor Exit Node", "reputation")
    assert tor[0]["url"] == "https://attack.mitre.org/techniques/T1090/003/"
    many = [
        {
            "label": str(i),
            "url": f"https://attack.mitre.org/techniques/T10{i:02d}/",
            "source": "x",
        }
        for i in range(9)
    ]
    merged = rx.merged_links(many, phishing)
    assert len(merged) == rx.MAX_LINKS and merged[-1] == rx.SURICATA_DOCS
    assert len({link["url"] for link in rx.merged_links(phishing, phishing)}) == 3


@pytest.mark.parametrize("name, family", NAMES)
def test_every_url_is_a_verified_one(name, family):
    links = rx.name_links(name, family) + rx.sid_links(
        [{"id": "T1572", "name": None}],
        [{"id": "TA0007", "name": None}],
        ["CVE-2026-4020"],
        True,
        True,
    )
    for link in links:
        assert link["url"].startswith(VERIFIED), link["url"]
        assert link["label"] and link["source"]


def test_ids_take_ascii_digits_only():
    # Arabic-Indic and full-width digits match \d, never a real ATT&CK or CVE id
    for bad in ("T\u0661\u0660\u0667\u0661", "T\uff11\uff10\uff17\uff11"):
        assert not rx.TECHNIQUE_ID.fullmatch(bad)
    assert not rx.TACTIC_ID.fullmatch("TA\u0660\u0660\u0661\u0661")
    assert not rx.CVE_ID.fullmatch("CVE-2021-\u0664\u0661\u0667\u0667\u0663")
    assert (
        rx.sid_links(
            [{"id": "T\u0661\u0660\u0667\u0661", "name": None}], [], [], False, False
        )
        == []
    )
    assert rx.TECHNIQUE_ID.fullmatch("T1071.001") and rx.CVE_ID.fullmatch(
        "CVE-2021-41773"
    )
