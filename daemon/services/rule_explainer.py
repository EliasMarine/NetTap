"""Plain-English explanations and "learn more" links for one Suricata rule (rule page).

Pure functions, no I/O. The page explains a rule by its name's family (an ET or GPL class word,
IPFire DBL, a reputation list, Suricata's own checks), reusing the alert enrichment's advice where
it fits. Per-SID advice (a curated description, or a credential sent in the clear) is chosen by
the caller, who knows the SIDs. Every link is built from a template below with a validated id,
never from a stored URL.

Every URL and URL pattern here returned HTTP 200 on 2026-11-15 (curl -L): the MITRE ATT&CK
technique and tactic pages, NVD, CISA (KEV, phishing, malware), IPFire DBL lists, SANS ISC,
CINS, Spamhaus DROP and the Suricata rules docs. The Proofpoint SID lookup answers 403 to
non-browser clients, so it is not used.
"""

import re
from typing import Any

from services.alert_enrichment import (
    generate_description,
    get_recommendation,
    get_risk_context,
)

# OLD CODE: from services.alert_findings import is_credential_exposure, is_reputation (sid_advice went)
from services.alert_findings import is_reputation
from services.owner_rules_validator import SID_MAX, SID_MIN

MAX_LINKS = 6

# OLD CODE: TECHNIQUE_ID = re.compile(r"T\d{4}(?:\.\d{3})?"), TACTIC_ID r"TA\d{4}", CVE_ID r"CVE-\d{4}-\d{4,7}" (review: ASCII digits)
# [0-9], not \d: \d also matches other scripts' digits, which no ATT&CK or CVE id uses
TECHNIQUE_ID = re.compile(r"T[0-9]{4}(?:\.[0-9]{3})?")
TACTIC_ID = re.compile(r"TA[0-9]{4}")
CVE_ID = re.compile(r"CVE-[0-9]{4}-[0-9]{4,7}")
_DBL_NAME = re.compile(r"IPFire DBL \[([^\]]+)\]", re.IGNORECASE)

MITRE = "MITRE ATT&CK"
SURICATA_DOCS = {
    "label": "How Suricata rules work",
    "url": "https://docs.suricata.io/en/latest/rules/intro.html",
    "source": "Suricata",
}
KEV_LINK = {
    "label": "CISA's catalogue of known exploited vulnerabilities",
    "url": "https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
    "source": "CISA",
}
_CISA_PHISHING = {
    "label": "Recognise and report phishing",
    "url": "https://www.cisa.gov/secure-our-world/recognize-and-report-phishing",
    "source": "CISA",
}
_CISA_MALWARE = {
    "label": "Malware, phishing and ransomware",
    "url": "https://www.cisa.gov/topics/cyber-threats-and-response/malware-phishing-and-ransomware",
    "source": "CISA",
}
# IPFire DBL list pages that exist (/dbl/lists/advertising is a 404: the slug is "ads")
DBL_SLUGS = {"phishing", "malware", "ads", "doh", "gambling", "piracy"}
_DBL_WORD_SLUG = {"advertising": "ads", "dns-over-https": "doh"}
# The reputation list a rule name names, and that list's own page
_REPUTATION_LINKS = (
    (
        "DSHIELD",
        "SANS Internet Storm Center (DShield)",
        "https://isc.sans.edu/",
        "SANS ISC",
    ),
    ("CINS", "CINS Army list", "https://cinsscore.com/", "CINS"),
    (
        "SPAMHAUS",
        "Spamhaus Don't Route Or Peer lists",
        "https://www.spamhaus.org/blocklists/do-not-route-or-peer/",
        "Spamhaus",
    ),
)
# Names of the techniques the families fall back on (their ATT&CK page titles)
_TECHNIQUE_NAMES = {
    "T1046": "Network Service Discovery",
    "T1566": "Phishing",
    "T1071": "Application Layer Protocol",
    "T1190": "Exploit Public-Facing Application",
    "T1189": "Drive-by Compromise",
    "T1568": "Dynamic Resolution",
    "T1219": "Remote Access Tools",
    "T1498": "Network Denial of Service",
    "T1090.003": "Proxy: Multi-hop Proxy",
    "T1552": "Unsecured Credentials",
}

_ENGINE = {
    "what": (
        "This is one of Suricata's own protocol checks, not a threat rule: Suricata saw traffic it "
        "couldn't decode the usual way, such as a truncated packet or a stream out of order."
    ),
    "risk": (
        "These describe how traffic looked on the wire, usually a capture or network quirk, not an "
        "attack. NetTap leaves them out of the alert counts."
    ),
    "todo": (
        "Nothing to do for a few of these. If they come in large numbers, check the System page for "
        "capture problems such as dropped packets."
    ),
}
_OWN = {
    "what": (
        "This is one of your own rules (Settings › Suricata rules), so NetTap can say only what its "
        "name says."
    ),
    "risk": "You wrote what it looks for, so you know best what a match means.",
    "todo": "Check the rule in Settings › Suricata rules, then the devices it matched.",
}
CREDENTIAL = {
    "what": "This rule matched a password, credential or other secret sent without encryption.",
    "risk": (
        "Anyone on the path between the device and the server could read it. ET rates the rule "
        "informational, but NetTap counts it because you can act on it."
    ),
    "todo": (
        "Find the device and the service it was signing in to. Change that password, and switch the "
        "service to an encrypted option (HTTPS, SSH, IMAPS) if it has one."
    ),
}
_REPUTATION = {
    "what": (
        "This rule matches traffic to or from an address on a reputation list, such as DShield, CINS "
        "or Spamhaus: addresses seen attacking, scanning or sending spam elsewhere."
    ),
    "risk": (
        "The list says the address misbehaved somewhere, not that it attacked you. These rules also "
        "match replies to connections your own devices opened."
    ),
    "todo": get_recommendation("drop"),
}
_DBL_RISK = (
    "NetTap observed traffic matching this blocklist rule. NetTap did not block it; this alert "
    "alone does not show whether the lookup or connection succeeded. The rule's name says "
    '"Blocked" because IPFire wrote it for a firewall that blocks.'
)
_DBL_TODO = (
    "Check which device made the lookup or connection, and whether anyone on it opened a link they "
    "didn't expect. If the domain should be blocked, block it on your router or DNS filter."
)
_DBL_LIST_WORDS = {
    "phishing": "phishing list (fake sites that try to steal passwords)",
    "malware": "malware list (sites that spread or control malicious software)",
    "ads": "advertising list",
}

# The ET (or GPL) class word, the rule name's second word, and its family
_CLASS_FAMILY = {
    "MALWARE": "malware",
    "MOBILE_MALWARE": "malware",
    "TROJAN": "malware",
    "ADWARE_PUP": "adware",
    "COINMINING": "coinmining",
    "PHISHING": "phishing",
    "EXPLOIT": "exploit",
    "EXPLOIT_KIT": "exploit_kit",
    "WEB_SERVER": "web_server",
    "WEB_SPECIFIC_APPS": "web_server",
    "WEB_CLIENT": "web_client",
    "SCAN": "scan",
    "POLICY": "policy",
    "INFO": "info",
    "HUNTING": "hunting",
    "DYN_DNS": "dyn_dns",
    "DNS": "dns",
    "P2P": "p2p",
    "GAMES": "apps",
    "CHAT": "apps",
    "USER_AGENTS": "user_agents",
    "REMOTE_ACCESS": "remote_access",
    "CURRENT_EVENTS": "current_events",
    "ATTACK_RESPONSE": "attack_response",
    "DOS": "dos",
}

# what, risk, todo (an existing recommendation where one fits), and fallback links
_FAMILIES: dict[str, dict[str, Any]] = {
    "malware": {
        "what": (
            "This rule matches traffic known to come from malware, such as a check-in with a "
            "control server or a download of more malicious code."
        ),
        "risk": (
            "If the rule is right, the device may be infected. A match is evidence to check, not "
            "proof: some rules also match harmless software."
        ),
        "todo": get_recommendation("malware"),
        "techniques": ("T1071",),
        "links": (_CISA_MALWARE,),
    },
    "adware": {
        "what": (
            "This rule matches traffic from adware or a potentially unwanted program (PUP): "
            "software that shows ads, tracks browsing or bundles itself with other installs."
        ),
        "risk": (
            "Usually a nuisance and a privacy problem rather than a direct danger, but it can open "
            "the door to worse software."
        ),
        "todo": "Check the device for programs or browser extensions nobody meant to install, and remove them.",
    },
    "coinmining": {
        "what": "This rule matches traffic to a cryptocurrency mining pool or from mining software.",
        "risk": (
            "If nobody on your network mines on purpose, mining software may be running without "
            "your say-so, using the device's power and electricity."
        ),
        "todo": (
            "Check whether anyone runs mining software on purpose. If not, check the device with "
            "up-to-date security software."
        ),
    },
    "phishing": {
        "what": (
            "This rule matches traffic to a known phishing page or phishing kit: a fake site made "
            "to steal passwords or payment details."
        ),
        "risk": (
            "Someone on the device may have opened a phishing link. Visiting the page is not the "
            "same as typing a password into it."
        ),
        "todo": (
            "Ask whoever uses the device whether they opened a link or typed a password into a site "
            "recently. If they did, change that password and turn on two-step sign-in."
        ),
        "techniques": ("T1566",),
        "links": (_CISA_PHISHING,),
    },
    "exploit": {
        "what": "This rule matches traffic shaped like an attempt to exploit a known software flaw.",
        "risk": (
            "Attempts like this are common on the internet and usually fail against up-to-date "
            "software. It matters most when the target runs the affected software and can be "
            "reached from the internet."
        ),
        "todo": get_recommendation("exploit"),
        "techniques": ("T1190",),
    },
    "exploit_kit": {
        "what": (
            "This rule matches traffic from an exploit kit: a website that tries flaws in the "
            "visitor's browser or plug-ins to install malware."
        ),
        "risk": "A device visited a page tied to an exploit kit. Up-to-date browsers usually resist these.",
        "todo": get_recommendation("web_client"),
        "techniques": ("T1189",),
    },
    "web_server": {
        "what": (
            "This rule matches requests that try to attack a web server or web application, such as "
            "a known flaw in a plug-in."
        ),
        "risk": (
            "Requests like these are common internet background noise. They matter when the "
            "targeted device really runs that web app and can be reached from the internet."
        ),
        "todo": get_recommendation("web_server"),
        "techniques": ("T1190",),
    },
    "web_client": {
        "what": (
            "This rule matches web content that can harm the browser or app that fetched it, such "
            "as a malicious script or a file built to exploit a flaw."
        ),
        "risk": "A device fetched content that looks harmful; up-to-date browsers block much of it.",
        "todo": get_recommendation("web_client"),
        "techniques": ("T1189",),
    },
    "scan": {
        "what": "This rule matches scanning: one address probing many ports or devices to see what answers.",
        "risk": (
            "Scans from the internet are constant background noise. A scan from one of your own "
            "devices is worth a look if nobody ran it on purpose."
        ),
        "todo": get_recommendation("scan"),
        "techniques": ("T1046",),
    },
    "policy": {
        "what": (
            "This rule matches activity that many organisations restrict, such as file sharing, "
            "remote access tools or software update checks. It is not a sign of an attack on its own."
        ),
        "risk": "Usually legitimate. It is worth knowing about if you didn't expect that app on your network.",
        "todo": get_recommendation("policy"),
    },
    "info": {
        "what": (
            "This is an informational rule: it notes something worth knowing, such as a device using "
            "a particular app, service or protocol, not an attack."
        ),
        "risk": (
            "Usually harmless. ET rates most informational rules so that NetTap lists them as "
            "activity and leaves them out of the alert counts."
        ),
        "todo": get_recommendation("info"),
    },
    "hunting": {
        "what": (
            "This is a threat-hunting rule: a broad pattern that can turn up unusual activity and "
            "often matches harmless traffic too."
        ),
        "risk": "Weak evidence on its own. It matters when it lines up with other alerts for the same device.",
        "todo": get_recommendation("hunting"),
    },
    "dyn_dns": {
        "what": (
            "This rule matches a lookup for a dynamic DNS name, such as one under duckdns.org: a free "
            "name that follows a changing home or server address."
        ),
        "risk": (
            "Many people use dynamic DNS for their own home servers and cameras. Malware uses it "
            "too, to find its control server."
        ),
        "todo": (
            "Check whether the name belongs to something you run, such as a home server, camera or "
            "NAS. If nobody recognises it, check the device that looked it up."
        ),
        "techniques": ("T1568",),
    },
    "dns": {
        "what": (
            "This rule matches a DNS lookup worth noting, such as a query for an unusual top-level "
            "domain or a pattern malware uses."
        ),
        "risk": "Often harmless; it matters if the name looked up turns out to be malicious.",
        "todo": get_recommendation("dns"),
    },
    "p2p": {
        "what": (
            "This rule matches peer-to-peer traffic, such as BitTorrent, where devices share files "
            "directly with each other."
        ),
        "risk": (
            "Not an attack. Peer-to-peer apps can share more than intended and bring copyright "
            "problems or unwanted downloads."
        ),
        "todo": (
            "Check whether someone on the device runs a peer-to-peer app on purpose. If not, find "
            "and remove it."
        ),
    },
    "apps": {
        "what": "This rule notes a game or chat service, such as Discord, in use on your network.",
        "risk": "Not an attack; it tells you which apps are in use.",
        "todo": get_recommendation("info"),
    },
    "user_agents": {
        "what": (
            "This rule matches the name a program gave itself in a web request (its user agent), "
            "such as a scripting library or an unusual client."
        ),
        "risk": "Plenty of normal software uses these names, and so can malware. It is weak evidence on its own.",
        "todo": (
            "Check whether the device runs software that would make requests like this, such as "
            "developer tools, scripts or smart-home apps."
        ),
    },
    "remote_access": {
        "what": (
            "This rule matches a remote access or remote management tool, such as ScreenConnect or "
            "AnyDesk, connecting out."
        ),
        "risk": (
            "These tools are legitimate, but scammers and attackers also use them to control a "
            "computer from afar."
        ),
        "todo": (
            "Check that whoever uses the device installed the tool on purpose and knows who connects "
            "with it. If not, remove it and change the passwords used on that device."
        ),
        "techniques": ("T1219",),
    },
    "current_events": {
        "what": "This rule tracks a current threat campaign that Emerging Threats is following.",
        "risk": (
            "If the rule is right, a device took part in that campaign; new rules like this can also "
            "match harmless traffic."
        ),
        "todo": get_recommendation("current_events"),
    },
    "attack_response": {
        "what": (
            "This rule looks for what a compromised system sends back, such as command output or a "
            "shell prompt."
        ),
        "risk": (
            "If the rule is right, someone may have access to the device; these rules also match "
            "harmless traffic."
        ),
        "todo": get_recommendation("attack_response"),
    },
    "dos": {
        "what": "This rule matches denial-of-service traffic: floods meant to overwhelm a device or connection.",
        "risk": "Small floods are common and harmless; a large one can slow or cut your connection.",
        "todo": get_recommendation("dos"),
        "techniques": ("T1498",),
    },
}


def _texts(family: str, texts: dict) -> dict:
    return {
        "family": family,
        "what": texts["what"],
        "risk": texts["risk"],
        "todo": texts["todo"],
    }


def dbl_slug(word: str) -> str:
    """An IPFire DBL list word ("Phishing", "Advertising") as its list page's slug."""
    lowered = word.strip().lower()
    return _DBL_WORD_SLUG.get(lowered, lowered)


def name_family(name: str) -> str:
    """The family a rule name belongs to; "unknown" when none matches."""
    upper = name.upper()
    if upper.startswith("SURICATA "):
        return "engine"
    if _DBL_NAME.match(name):
        return "dbl"
    if is_reputation(name):
        return "reputation"
    words = upper.split()
    if len(words) > 1 and words[0] in ("ET", "GPL"):
        return _CLASS_FAMILY.get(words[1], "unknown")
    return "unknown"


def explain_name(name: str, severity: int) -> dict:
    """{family, what, risk, todo} from the rule's name alone (never a SID's own facts)."""
    family = name_family(name)
    if family == "engine":
        return _texts(family, _ENGINE)
    if family == "reputation":
        return _texts(family, _REPUTATION)
    if family == "dbl":
        slug = dbl_slug(_DBL_NAME.match(name).group(1))  # type: ignore[union-attr]
        listed = _DBL_LIST_WORDS.get(slug, f"{slug} list")
        what = (
            "IPFire's DBL is a community domain blocklist. This rule matched a lookup or connection "
            f"for a domain on its {listed}."
        )
        return {"family": family, "what": what, "risk": _DBL_RISK, "todo": _DBL_TODO}
    if family in _FAMILIES:
        return _texts(family, _FAMILIES[family])
    return {
        "family": "unknown",
        "what": generate_description(name),
        "risk": get_risk_context(severity, "unknown"),
        "todo": get_recommendation("unknown"),
    }


def is_own_sid(sid: str | None) -> bool:
    """A SID in the owner range (Settings › Suricata rules), which no rule source uses."""
    return bool(sid) and sid.isdigit() and SID_MIN <= int(sid) <= SID_MAX


def own_rule() -> dict:
    return _texts("own", _OWN)


def credential_advice() -> dict:
    return _texts("credential", CREDENTIAL)


# OLD CODE START — over-engineering gate: _sid_facts picks the curated text or CREDENTIAL in one line
# def sid_advice(curated: dict | None, name: str, et_ratings: list) -> dict | None:
#     """One SID's own advice: its curated description, else the credential text when ET rates it
#     only Informational/Unknown and its name names a secret in the clear, else None."""
#     if curated:
#         return curated
#     if is_credential_exposure(name, et_ratings):
#         return {
#             "what": CREDENTIAL["what"],
#             "risk": CREDENTIAL["risk"],
#             "todo": CREDENTIAL["todo"],
#         }
#     return None
# OLD CODE END


def _technique_link(tid: str, name: str | None = None) -> dict:
    path = tid.replace(".", "/")
    title = name or _TECHNIQUE_NAMES.get(tid)
    return {
        "label": f"{MITRE} {tid}: {title}" if title else f"{MITRE} technique {tid}",
        "url": f"https://attack.mitre.org/techniques/{path}/",
        "source": MITRE,
    }


def _capped(links: list[dict]) -> list[dict]:
    """The links in order, each URL once, at most MAX_LINKS."""
    seen: set[str] = set()
    kept = []
    for link in links:
        if link["url"] not in seen:
            seen.add(link["url"])
            kept.append(link)
    return kept[:MAX_LINKS]


def sid_links(
    techniques: list[dict],
    tactics: list[dict],
    cves: list[str],
    cisa_kev: bool,
    credential: bool,
) -> list[dict]:
    """One SID's links from its validated ids: CVEs on NVD, the KEV catalogue, its ATT&CK
    techniques and tactics, and Unsecured Credentials for a credential rule."""
    links = [
        {
            "label": f"{cve} in the National Vulnerability Database",
            "url": f"https://nvd.nist.gov/vuln/detail/{cve}",
            "source": "NIST NVD",
        }
        for cve in cves
        if CVE_ID.fullmatch(cve)
    ]
    if cisa_kev:
        links.append(KEV_LINK)
    links += [
        _technique_link(t["id"], t.get("name"))
        for t in techniques
        if TECHNIQUE_ID.fullmatch(t["id"])
    ]
    links += [
        {
            "label": f"{MITRE} tactic {t['id']}: {t['name']}"
            if t.get("name")
            else f"{MITRE} tactic {t['id']}",
            "url": f"https://attack.mitre.org/tactics/{t['id']}/",
            "source": MITRE,
        }
        for t in tactics
        if TACTIC_ID.fullmatch(t["id"])
    ]
    if credential:
        links.append(_technique_link("T1552"))
    return _capped(links)


def name_links(name: str, family: str) -> list[dict]:
    """Links from the rule's name: its DBL list page, its reputation list, its family's ATT&CK
    technique and CISA page, then how Suricata rules work (always last)."""
    links: list[dict] = []
    found = _DBL_NAME.match(name) if family == "dbl" else None
    if found:
        slug = dbl_slug(found.group(1))
        known = slug in DBL_SLUGS
        links.append(
            {
                "label": f"IPFire DBL: the {slug} list" if known else "IPFire DBL",
                "url": f"https://www.ipfire.org/dbl/lists/{slug}"
                if known
                else "https://www.ipfire.org/dbl",
                "source": "IPFire",
            }
        )
    if family == "reputation":
        upper = name.upper()
        links += [
            {"label": label, "url": url, "source": source}
            for marker, label, url, source in _REPUTATION_LINKS
            if marker in upper
        ]
        if upper.startswith("ET TOR"):
            links.append(_technique_link("T1090.003"))
    spec = _FAMILIES.get(family, {})
    links += [_technique_link(t) for t in spec.get("techniques", ())]
    links += list(spec.get("links", ()))
    return _capped([*links[: MAX_LINKS - 1], SURICATA_DOCS])


def merged_links(first: list[dict], then: list[dict]) -> list[dict]:
    """`first` (one SID's links), then `then` (the name's), each URL once, at most MAX_LINKS,
    keeping how Suricata rules work as the last link."""
    rest = [link for link in then if link["url"] != SURICATA_DOCS["url"]]
    return _capped([*_capped([*first, *rest])[: MAX_LINKS - 1], SURICATA_DOCS])
