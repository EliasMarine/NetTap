# Threat and risk scoring: what counts and why

Source of truth for how NetTap turns alerts and traffic into the Threats page threat score, kill chains and
the per-device risk score. Every number in `daemon/services/alert_intelligence.py` and
`daemon/services/risk_scoring.py` points at a rule here. Created 2026-11-08 for NET-209.

## Why this exists

On 2026-11-08 the owner opened a "device" page for 91.92.40.12. It showed a Ubiquiti MAC, "Windows 10/11"
and a risk score of 58 (High). The G11's own data showed the scoring was wrong:

| What the page said | What the data showed |
|---|---|
| 91.92.40.12 is a device | An internet address on the Spamhaus DROP list. It sent React2Shell (CVE-2025-55182) and prototype-pollution requests to the port-forwarded web server 192.168.1.24 on ports 80, 443 and 3000. Every attempt got a 405 or a reset. Its MAC is the UDM Pro's, because the mirror taps the gateway's LAN side. |
| Threats: 100/100, critical | Over 7 days, 2,428 of the 5,236 counted alerts were inbound reputation-list hits (ET CINS 1,243, ET DROP 1,167, ET COMPROMISED 18), all from internet addresses. Each scanner address added 5 points. |
| One active kill chain | The attacker above, built from its own inbound alerts. |
| 192.168.1.188 is critical | 279 "ET INFO Spotify P2P Client" broadcasts. |
| Exfiltration 15/15 for 91.92.40.12 | 11.7 KB up, 3.5 KB down. |
| Device risk factors | Points for 44 of 54 devices (exfiltration), 42 (ports) and 29 (external ratio). |

## Rules

Sources were read on 2026-11-08. Three vendor pages (Firewalla, UniFi, Fing) block automated reads, so they
are cited from search excerpts and marked as such.

### What makes an alert a likely true positive

1. **Use ET's own severity first.** ET's `signature_severity`:
   - **Critical:** "an end system is likely to be compromised".
   - **Major:** "an active attempt at compromise".
   - **Minor:** "reconnaissance, scanning, and other profiling".
   - **Informational:** "may not be malicious in and of itself".

   Sources: <https://community.emergingthreats.net/t/signature-metadata/96>,
   <https://www.proofpoint.com/us/blog/threat-insight/emerging-threats-updates-improve-metadata-including-mitre-attck-tags>
2. **Suricata `severity` is the classtype's priority, not a measure of maliciousness.** `policy-violation`
   and `trojan-activity` are both priority 1, and 687 ET Open rules marked Informational still carry priority 1.
   Use it only when a rule has no ET severity.
   Sources: <https://docs.suricata.io/en/latest/rules/meta.html>,
   <https://rules.emergingthreats.net/open/suricata-7.0.3/rules/classification.config>,
   <https://community.emergingthreats.net/t/bug-sid-2064326-has-severity-1-but-is-labeled-et-info/3171>
3. **Direction matters most.** ET's malware rules are written `$HOME_NET -> …`: an alert matters most when
   your device started the connection. About 17,400 of 19,398 ET MALWARE rules are written that way.
   Source: <https://docs.suricata.io/en/latest/output/eve/eve-json-format.html>
4. **An alert on an attempt is a sign, not a confirmed compromise.** NIST SP 800-61r2 §3.2.2 calls
   vulnerability scanning a *precursor*. It lists an IDS alert on a buffer-overflow attempt as an
   *indicator*: a sign that an incident "may have occurred or may be occurring". §3.2.4 says to validate
   indicators against other data. In a study of 30 million SOC alerts, separating successful from failed
   exploitation cut false positives by about 36%. **NetTap's policy:** an attempt against a device weighs at
   most low (0.5). The evidence of an outcome that NetTap can see, the device's own traffic, scores at full
   weight as the device's own finding. This weighting is our choice, not NIST's.
   Sources: <https://nvlpubs.nist.gov/nistpubs/specialpublications/nist.sp.800-61r2.pdf>,
   <https://arxiv.org/abs/2501.09808>
5. **One signature on one host is one finding, however often it fires.** Zeek treats repeated notices as
   duplicates. Security Onion groups alerts by rule. In the SOC study, a few rules made most of the alerts.
   Sources: <https://docs.zeek.org/en/master/frameworks/notice.html>,
   <https://docs.securityonion.net/en/2.4/alerts.html>, <https://arxiv.org/abs/2501.09808>
6. **Some ET categories are context, not threats.** INFO is "audit level events". HUNTING rules "can provide
   false positives on legitimate traffic". TOR, P2P, GAMES and CHAT describe what a device uses, not an
   attack. Proofpoint still recommends keeping them on, for context.
   Source: <https://community.emergingthreats.net/t/suricata-5-6-7-rule-categories/94>
7. **`SURICATA` engine events describe the sensor, not a device.** They are the stream and decoder rules
   (`protocol-command-decode`, no ET severity).
   Source: <https://github.com/OISF/suricata/blob/main-8.0.x/rules/stream-events.rules>

### Inbound scans and reputation lists

8. **A reputation hit doesn't prove an attack.** ET DROP, DShield, CINS, COMPROMISED and TOR rules are
   `alert ip [list] any -> $HOME_NET any`, with no `flow:` keyword. They fire on any packet from a listed
   address, replies to your own device's connections included. Spamhaus DROP is rated Minor; DShield, CINS
   and COMPROMISED are rated Major.
   Source: the rule files in <https://rules.emergingthreats.net/open/suricata-7.0.3/emerging.rules.tar.gz>
9. **Untargeted inbound traffic is background noise.** GreyNoise measures about 3,000 unsolicited packets a
   day, from about 1,000 addresses, reaching every routable IP.
   Sources: <https://www.greynoise.io/blog/internet-background-noise>, NIST §3.2.2
10. **On NetTap's mirror, the exposure is the finding.** This is our inference, not a source's. The mirror
    taps the router's LAN side, so inbound traffic the router drops never reaches it. Inbound traffic NetTap
    does see is either a reply to your own device or traffic through a port forward or UPnP. Fing's router
    check looks for exactly that (search excerpt: <https://help.fing.com/hc/en-us/articles/25893229155740>).

### Exfiltration and unusual activity

11. **Compare a device with its own normal, and require a floor.** MITRE ATT&CK T1041 and T1048 point to
    "uncommonly high volume" and activity "outside baseline". Splunk UBA requires outgoing bytes to beat the
    device's baseline by a ratio *and* an absolute threshold. None of them publishes a number.
    Sources: <https://attack.mitre.org/techniques/T1041/>, <https://attack.mitre.org/techniques/T1048/>,
    <https://help.splunk.com/en/security-offerings/splunk-user-behavior-analytics/use-splunk-user-behavior-analytics/5.4.2/splunk-uba-models/time-series-models>
12. **A ratio says nothing about volume.** The producer/consumer ratio is "independent of data load or rate".
    11.7 KB up and 3.5 KB down sits where sending email does. Small flows are mostly protocol overhead.
    Sources: <https://qosient.com/argus/presentations/Argus.FloCon.2014.PCR.Presentation.pdf>,
    <https://engineering.salesforce.com/detecting-multithreaded-exfiltration-in-zeek-e8a244885896/>
13. **Published volume floors:**
    - Firewalla Large Upload: 100 MB (search excerpt: <https://help.firewalla.com/hc/en-us/articles/360043859234>).
    - Malcolm "High volume connection": 1,000 MB
      (<https://github.com/idaholab/Malcolm/blob/main/logstash/pipelines/enrichment/24_severity.conf>).
    - Splunk: over 1 GB (<https://research.splunk.com/web/c8a6b56d-16dd-4e9c-b4bd-527742ead98d/>).

### Ports

14. **A fixed list of "bad ports" is not a sound indicator.** RFC 6335 says conclusions about a service
    "based on observed port numbers [are] not always reliable". 49152–65535 are ephemeral, so 65535 means
    nothing. ATT&CK T1571 asks for protocol-port *mismatches* instead. On the G11, Malcolm's mismatch tag
    ("Service on non-standard port") fired on 12 devices in 24 h, all STUN (WebRTC calls) or an AYIYA
    misdetection on 443. On a home network the mismatch is noise too, so ports are not scored.
    Sources: <https://www.rfc-editor.org/rfc/rfc6335.html>, <https://attack.mitre.org/techniques/T1571/>

### Existing models we checked

15. **Malcolm scores each log record, not each host.** Suricata severity 1, 2, 3 and 4 map to 91, 71, 51
    and 31; Inbound adds 50 and Outbound 20. It doesn't deduplicate.
    Source: <https://idaholab.github.io/Malcolm/docs/severity.html>
16. **Elastic entity risk combines a host's alerts.** The highest scores count most, over 30 days. Its
    bands: below 20 Unknown, 20–40 Low, 40–70 Moderate, 70–90 High, above 90 Critical.
    Source: <https://www.elastic.co/docs/solutions/security/advanced-entity-analytics/entity-risk-scoring>
17. **Security Onion, UniFi and Firewalla publish no weights.**

## How NetTap applies the rules

Rule numbers refer to the list above.

### Alert severity (`reclassify_severity`)

Severity is decided in this order:

1. **Context categories become activity** (shown, never counted): `ET INFO`, `ET HUNTING`, `ET TOR`,
   `ET P2P`, `ET GAMES`, `ET CHAT`, and `SURICATA` engine events. Rules 6 and 7.
2. **Otherwise ET's `signature_severity` sets it:** Critical is critical, Major is high, Minor is medium.
   Rule 1.
3. **Otherwise** the older prefix table applies, then Suricata's priority (1 is high, 2 is medium, the
   rest low). Rule 2.

The old "sensitive internal port" boost is gone. A destination port doesn't turn an attempt into a likely
compromise, and the boost also lifted informational alerts into the counted ones.

### Who acted: the device's own traffic, or an attempt against it

NetTap uses the daemon's LAN rule (`/api/network/lan`). It classifies every alert toward a LAN address on its
own, by the minute it fired in, before any counts are merged. Alert times are read per minute, so a flood
of alerts on one connection is one entry a minute, not one per alert. A community ID is a hash of the
addresses and ports, with no time and no direction, so the alert's `network.community_id` is matched to the
Zeek connection records with the same ID by time as well.

**Who opened a record's connection** comes from its `zeek.conn.history`
(<https://docs.zeek.org/en/master/scripts/base/protocols/conn/main.zeek.html>). Upper-case letters are
packets from the record's source, lower-case from its destination. Zeek's direction flip (`^`) swaps the two
ends without rewriting the letters before it, so those letters are swapped back first.

- **TCP: only a pure SYN shows the opener.** `S` is a SYN from the source, `s` from the destination. A
  SYN-ACK does not count: SYN-ACK scans and backscatter send one with no connection behind it.
- **TCP with no SYN, where both sides sent something other than a reset and there was payload**
  (`D`/`d`, or the byte counters `zeek.conn.orig_bytes`/`resp_bytes` above 0, or no counters) is a live
  session picked up mid-stream, opener unknown. That is what a device's C2 session looks like when it
  resumes after Zeek's 5-minute idle expiry. It counts like a missing record (below).
- **Any other TCP record is debris**: one side only, or answered only by a reset, or a bare teardown. A
  scanner's lone data packet (`D`), a late FIN logged on its own after a close (`^f`) and a SYN-ACK probe
  answered by a reset (`Hr`) are debris. Debris shows no live session on the device; it never decides.
- **UDP and ICMP**: whoever sent the first packet. Malware sending UDP from port 5353 makes Zeek flip the
  record, so its first letter is the device's (`^dD`), and the device is the opener. Zeek closes a UDP
  record after 60 s of silence, but the outside can reach the device only while the router's NAT mapping
  from the earlier traffic lives, so a UDP record that starts within 11 minutes of the previous one on the
  same addresses and ports continues it and keeps its opener. A C2 server that speaks first after a pause
  is not the opener.

**Which record an alert belongs to.** A record the alert's minute falls in (`event.start` to `event.end`,
±10 s) comes first. Otherwise the record that ended most recently, up to 11 minutes before, counts, debris
left out. When the minute's own records were picked up mid-stream (debris or opener unknown, for example a
session resuming with keepalives after hours idle), the session's handshake record on the same addresses
and ports names the opener, however old it is within the lookup. Suricata stamps an alert raised when a flow times out with the timeout time: on the G11 that is
600 s after the last packet for established TCP, and alerts arrived 600 to 608 s after their connection's
end. Records naming different openers make the alert's opener unknown, never an attempt.

**One decision per Suricata flow.** All alerts with the same community ID and `suricata.flow_id` are one
connection. When a record the flow's alerts fall in names one opener, every alert of the flow takes it, so a
timeout alert is judged by the connection its earlier alerts were in. A guess from a record that ended
before an alert applies to that alert only.

Each alert is charged to exactly one finding, for one device and one role:

| Alert packet | Charged to |
|---|---|
| LAN device → internet | The LAN device, as **its own traffic**. That covers its requests and its responses, for example an `ATTACK_RESPONSE` from a port-forwarded server. |
| Internet → LAN device, on a connection the device opened | The device, as **its own traffic**. That covers a malware server's reply or a blocklisted server answering it. Rule 3. |
| Internet → LAN device, the record shows the internet opened it | The device, as **an attempt against it**. The same when only debris matched, or the alert has no community ID. |
| Internet → LAN device, no record matched, or the opener is unknown | Zeek writes the record when a connection ends, and Malcolm indexes it within a minute. For the first 10 minutes the alert is **an attempt** while its record is on the way. After that it is a connection held open, as a C2 server can do for hours, and counts as **the device's own traffic**. |
| LAN device → LAN device | One device, chosen by the rule's ET `attack_target`. A client-only target (`Client_Endpoint`, `Mobile_Client`) charges the device that opened the connection, so a proxy relaying a client's malware traffic is not charged. With no matching record, nobody is charged: the alert counts on the Threats page but goes to no device. Any other target charges the sender. |

Each finding keeps its own counts and times.

On the G11 on 2026-11-08, all 300 alert groups of the last 24 hours matched their connection records in
109 ms. 57 groups that looked inbound were connections the owner's devices had opened (.148 and .205 to
Spamhaus DROP and CINS addresses).

### Reputation lists (rules 8–10)

An `ET DROP`, `ET CINS`, `ET COMPROMISED`, `ET TOR` or `ET 3CORESec` hit:

- **Is not counted when a connection record shows the internet side opened the connection.** When the
  device opened it, the hit counts, capped at medium.
- **Is never hidden when no record matched for 10 minutes.** A younger hit waits for its record as an
  attempt. A hit still unmatched after 10 minutes is a connection held open, so it counts as the device's
  own traffic, at medium.
- **Is listed at medium when neither side is a LAN device.** No device can be charged, so the hit stays on
  the Threats page with its raw count.
- **Never makes a kill-chain stage.** An address being on a list is not command-and-control evidence.

A hit that is not counted moves to "not counted". The Alerts page and its drill-down link still show its
raw alerts.

### Threats page threat score

- **One finding per signature and LAN device.** Each finding takes its worst severity. Rule 5.
- **Weights per finding:** critical 10, high 5, medium 2, low 0.5. The total is capped at 100.
- **A finding that is an attempt against a device weighs at most 0.5.** Rule 4.
- **The busier-than-usual boost (+15) and the level ceiling stay.** The level never exceeds the worst alert.
- **"Events that need attention" and the busier-than-usual check count only alerts that score.** Each alert
  counts once. The stored history is versioned (`counted-v2`), so it is never compared with the old
  whole-group counts.

### Kill chains

- A chain is per LAN device.
- Attempts against the device count only as reconnaissance or exploit-attempt stages.
- Reputation hits and context alerts make no stage.
- A chain is a sequence of real alert instants in time order, each at a later stage than the one before.
  Every alert time is used, not only the first and last.
- Each step is no more than 24 hours after the previous one. That limit is NetTap's choice.
- A chain is never invented, and widening the time range never removes one.
- A chain needs two or more stages, and at least one must come from the device's own traffic.
- The page shows only the findings in that sequence.
- An attacker on the internet is never a chain.

### Lateral movement and still-open connections (NET-240, 2026-11-11)

- Lateral movement lists internal-to-internal connections on admin ports (SMB, RDP, SSH and so on).
- It reads Zeek's final conn records and its interim long-connection records (`conn_long.log`, same `zeek.uid`).
  So a session that is still open is listed as of its latest interim record.
  Zeek writes the first interim record after a while (about 30 minutes on the G11), so a new session isn't listed at once.
- A connection counts when it was active in the window: it started before the window ended, and it was last seen (`lastPacket`) or started after the window began.
  A session begun yesterday and still open appears in today's window.
- "Connections (approx.)" is OpenSearch's approximate distinct count of `zeek.uid`, so a connection's interim and final records count once.
  Any record without a uid counts as one connection, and the assessment says how many there were (none on Zeek data).
- "Last seen" is the newest `lastPacket` or start time in the pair.
- Beaconing still reads final records only.
  One open connection is one connection, and its interim records would look periodic and invent beacons.
- Byte and connection totals elsewhere keep final records only (`CONN_ACCOUNTING`, F1).

### Device risk score

The score is out of 100. Its bands: 0–24 low, 25–49 medium, 50–74 high, 75+ critical.

| Factor | Max | Points |
|---|---|---|
| Alerts | 50 | Counts each distinct signature from the device's own traffic once: critical 50, high 25, medium 5, low 1. Rules 1, 3 and 5. One critical signature is High by itself. |
| Connection anomaly | 25 | Compares connections the device opened in the window with its median day over the 7 days before, counting only days it was seen. A window shorter than a day is compared with a whole usual day. 3× usual scores 10; 5× usual scores 25. Needs 500 or more connections and 3 days of history. Rule 11. |
| Upload spike | 25 | Compares bytes the device sent to internet addresses, on connections it opened and on ones it answered, with its median day, scaled the same way. Nothing under 100 MB. 3× usual scores 10; 3× usual and 1 GB or more scores 25. Needs 3 days of history. Rules 11–13. |

**The two volume factors score only alongside a high or critical alert from the device's own traffic that is
not a reputation hit.** Without one they score 0 and state the facts, for example "Sent 4.2 GB, 5.1× its
usual, not scored without a high or critical alert". A backup can't make a device look risky by itself, nor
with a low policy alert or a blocklist contact. NIST SP 800-61r2 §3.2.4 says to validate an alert against
other sources. The alert and the volume are matched by device and window, not by the exact bytes.

**Removed:**
- **External ratio.** No source treats "talks mostly to the internet" as a threat; IoT devices and phones do
  it by design.
- **Suspicious ports.** Rule 14.

## Known limits

- **A weekly backup still shows as an upload spike on its day.** It is only described, and scores 0 unless
  the device also has a counted alert.
- **A fresh install has under 3 days of history.** Both spike factors say so and score 0.
- **An open connection has no Zeek record yet.** For its first 10 minutes an internet packet counts as an
  attempt; after that the alerts count as the device's own traffic. A long inbound session the internet
  really opened, such as a scanner holding a port-forwarded server's connection open, therefore counts as
  the server's own until it ends and its record arrives. The record lookup reaches one day before the
  window, so a connection that started earlier is treated the same way.
- **A packet Zeek never logged counts like a connection held open.** Zeek and Suricata capture separately,
  so now and then Suricata alerts on a packet Zeek has no record for. On the G11 over 7 days that was 9
  findings, all blocklist hits from scanners at medium (2 points each).
- **A session picked up mid-stream whose handshake record is out of reach counts like a held-open
  connection.** The lookup reaches one day before the time range; an older session's handshake is not read.
- **UDP has no handshake.** A UDP conversation that resumes more than 11 minutes after its last packet is
  opened by whoever sends first after the gap.
- **An established inbound session from a blocklisted address is left out once its record shows the
  internet opened it.** That is rule 8: a port-forwarded server answering a listed scanner is the
  normal case. A compromise over such a session still shows through its other alerts (an exploit,
  `ATTACK_RESPONSE`, malware), which are not reputation hits.
- **ET's context categories outrank its severity metadata.** `ET INFO`, `HUNTING`, `TOR`, `P2P`, `GAMES`
  and `CHAT` are activity even when a rule's `signature_severity` says Major. ET files those rules as
  policy and context, not as compromise (rule 2); the raw alerts stay on the Alerts page.
- **A reused address-and-port pair can be ambiguous.** When two connection records with different openers
  could hold the same alert, its opener is unknown. A flow's alerts outside the time range, and its
  informational alerts, are not read, so they cannot settle it. Both need the same addresses and ports used
  again from the other end within 11 minutes.
- **An alert on a still-open connection, up to 11 minutes after an earlier connection on the same addresses
  and ports ended, takes that earlier connection's opener** until its own record arrives.
- **IPv6 alert groups have no LAN device.** They score as before, keyed by signature, source and destination.
- **No corroboration from Zeek intel or notices yet.** NIST SP 800-61r2 §3.2.4 says to validate alerts
  against other sources, and Malcolm weights an intel match at 80 against 30 for a bare alert
  (<https://github.com/idaholab/Malcolm/blob/main/logstash/maps/malcolm_severity.yaml>). Weighting
  corroborated findings higher is a later improvement.

## Before and after on the G11

Measured by `scripts/remote/deploy-threat-accuracy.sh` on 2026-11-08: before #223, after #223, and after
#225 (the matching fix).

| | Before | After #223 | After #225 |
|---|---|---|---|
| 24 h threat score | 100 critical | 50 high | 44 medium |
| 24 h counted alerts | 478 | 149 | 141 |
| 7 d threat score | 100 critical | 100 high | 100 high |
| 7 d counted alerts | 2,772 | 471 | 453 |
| 7 d kill chains | 5, all internet attackers | .24 (stages 1, 2) | none |
| 91.92.40.12 device page and risk | "Windows 10/11", risk 58 high | 404, not on your network | 404 |

Device risk (24 h), before → after #225: .188 78 critical → 0; .146 73 high → 0; .44 70 high → 50 high;
.205 60 high → 20 low; .1 33 medium → 0; .148 23 → 10; 10.10.0.27 25 medium → 25 medium; .24 8 → 0.

**Why 7 days still reads 100.** The points add up to about 140, and the score is capped at 100; the level is
high because no alert is critical. Most of it is real:

- **192.168.1.44, 48 points.** IPFire DBL malware and phishing lookups and connections, plus CINS and
  DShield contacts. .44 runs bandwidth-sharing apps on purpose (NET-191), so this is other people's traffic
  leaving through the owner's connection.
- **192.168.1.205, 20 points.** Contacts with Spamhaus DROP and CINS-listed addresses, mostly peers on
  UDP port 32021 that .205 talked to first (a BitTorrent-style client).
- **192.168.1.24, 18 points.** About 27 distinct exploit and scan signatures against the port-forwarded
  server, at 0.5 each, plus 3 blocklist packets Zeek never logged (see Known limits).
- **10.10.0.27, 5 points.** An abuse.ch JA3 fingerprint for possible adware.
