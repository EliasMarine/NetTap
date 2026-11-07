# Alerts

NetTap uses Suricata as its intrusion detection system (IDS), monitoring all network traffic for known malicious patterns using the Emerging Threats Open ruleset.

---

## Understanding Alerts

An alert fires when network traffic matches a Suricata detection rule. Each alert includes:

- **Signature** --- the rule name describing what was detected (e.g., "ET MALWARE Known Malicious User-Agent")
- **Severity** --- how serious the detection is
- **Source IP** --- the device that initiated the connection
- **Destination IP** --- the remote host
- **Protocol** --- the network protocol (TCP, UDP, etc.)
- **Timestamp** --- when the detection occurred

!!! info "Alerts are detections, not blocks"
    NetTap v1.0 is read-only. It detects and reports suspicious traffic but does **not** block it. Think of it as a security camera, not a security guard.

---

## Severity Levels

Suricata assigns a numeric severity (1--3) to each rule. NetTap maps these to human-readable labels:

| Severity | Label | Badge Color | Meaning |
|---|---|---|---|
| 1 | **HIGH** | Red | Likely malicious activity. Investigate promptly. |
| 2 | **MEDIUM** | Yellow | Potentially suspicious. May be legitimate but worth reviewing. |
| 3 | **LOW** | Blue | Informational or policy-level detection. Usually benign. |
| (none) | **INFO** | Grey | Miscellaneous detection with no severity assigned. |

### What counts as an alert

Emerging Threats rates each of its rules as Critical, Major, Minor, Informational or Unknown. NetTap counts an alert only when ET rates it Critical, Major or Minor. Rules from other sources, and your own rules, always count.

Rules that ET rates Informational or Unknown match ordinary traffic: video-call STUN, DNS over HTTPS, apps checking for updates. NetTap still stores these. It lists them as **activity**, but leaves them out of every alert total, the Home page, device risk scores and the threat summary. On a home network they are usually most of what Suricata reports.

To see them, open **Alerts**. Under the severity tiles, the line "… informational events not counted · Show" opens the list filtered to activity. The **Activity** chip above the list shows the filter is on; clear it to go back to counted alerts.

---

## Alerts Page

The dedicated alerts page (`/alerts`) provides a full-featured alert management interface.

### Severity Filter Tabs

Filter the alert list by severity using the tabs at the top:

- **All** --- show all alerts
- **High** --- show only severity 1 (red)
- **Medium** --- show only severity 2 (yellow)
- **Low** --- show only severity 3 (blue)

### Alert Table

The main table displays alerts with columns for severity, signature, source IP, destination IP, protocol, and timestamp. Click any column header to sort.

### Pagination

Alerts are paginated at 50 per page. Navigation controls at the bottom let you move between pages. The total alert count is shown above the table.

### Alert Detail Panel

Click any alert row to open a slide-out detail panel on the right side of the screen. The detail panel shows:

- Full signature name and description
- Source IP and port
- Destination IP and port
- Protocol
- Exact timestamp
- Alert category
- Raw alert data (JSON)

### Auto-Refresh

Enable auto-refresh (30-second interval) using the toggle in the page header to see new alerts as they arrive.

---

## Common Alert Types

### True Positives (Real Threats)

- **Malware communication** --- a device contacting known command-and-control servers
- **Exploit attempts** --- traffic matching known vulnerability exploit patterns
- **Data exfiltration** --- unusual outbound data transfers to suspicious destinations

### Common False Positives

Some alerts are triggered by legitimate traffic. Common examples:

- **"ET INFO"** rules --- informational detections about normal protocols (e.g., TLS version detection)
- **"ET POLICY"** rules --- policy-level detections (e.g., P2P traffic, VPN usage)
- **Gaming and streaming** --- some game and streaming protocols trigger low-severity rules
- **IoT devices** --- smart home devices sometimes use non-standard protocols that trigger alerts

!!! tip "Evaluating alerts"
    When investigating an alert:

    1. Check the **severity** --- HIGH alerts deserve immediate attention
    2. Read the **signature** --- the rule name usually explains what was detected
    3. Look at the **source IP** --- is it one of your devices or external?
    4. Check the **destination** --- is it a known legitimate service?
    5. Look for **patterns** --- a single alert is less concerning than repeated alerts from the same device

---

## Alert Volume

On a typical home network, you should expect:

- **0--5 HIGH alerts per day** (investigate all of these)
- **5--20 MEDIUM alerts per day** (review periodically)
- **20--100+ LOW/INFO alerts per day** (normal background noise)
- **Thousands of activity events per day** (ET Informational; listed, not counted)

If you see significantly more HIGH alerts than expected, it could indicate a compromised device on your network.

---

## Where Alerts Come From

The alert pipeline:

1. Raw packets traverse the `br0` bridge
2. Suricata captures and inspects packets in real-time using the rule sources listed below
3. Matching packets generate alert events in `eve.json`
4. Filebeat ships `eve.json` logs to Logstash
5. Logstash enriches and forwards to OpenSearch
6. NetTap dashboard queries OpenSearch and displays alerts

### Rule sources

Suricata uses four free rule sources:

| Source | What it catches |
|---|---|
| Emerging Threats Open (`et/open`) | The general ruleset: malware, exploits, scans, policy |
| abuse.ch SSL Blacklist (`abuse.ch/sslbl-blacklist`) | TLS certificates used by malware command servers |
| Echap stalkerware indicators (`echap/stalkerware`) | Domains that stalkerware apps report to |
| IPFire DBL (`ipfire/dbl`) | Malware and phishing domains only |

IPFire's other categories (ads, gambling, DNS over HTTPS and so on) are turned off on purpose: they flag ordinary browsing.
Settings › Suricata rules lists the sources Suricata really runs.

### When rules update

Rules update when Suricata starts, every night at 00:00 UTC, and when you press **Update now** on Settings › Suricata rules.
An update is kept only if Suricata loads it with no failed rules. If a download fails or a rule doesn't load, Suricata keeps
the last good rules, and the page says why the update failed. After 48 hours without a successful update the status turns amber.

### Emerging Threats Pro (optional)

If you have a paid Emerging Threats Pro code from Proofpoint, enter it on Settings › Suricata rules. NetTap checks the code
with Proofpoint first and saves it only if Proofpoint accepts it. Suricata then restarts and downloads ET Pro instead of
ET Open; this takes a few minutes and the page follows it. The code stays on the appliance (`/etc/nettap/suricata.env`,
readable by root only) and is never shown again or written to a log. **Remove code** goes back to ET Open.

When the code expires, every nightly update fails until you renew or remove it; Suricata keeps the last good rules meanwhile.
