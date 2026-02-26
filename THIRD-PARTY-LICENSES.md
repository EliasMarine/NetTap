# Third-Party Licenses

NetTap integrates the following third-party components. Each runs in its own
isolated Docker container with no code linking to NetTap's own codebase.

## TShark (Wireshark CLI)

- **License:** GNU General Public License v2.0 (GPL-2.0)
- **Project:** https://www.wireshark.org
- **Source:** https://gitlab.com/wireshark/wireshark
- **Integration:** Containerized process, invoked via `docker exec` subprocess
- **Purpose:** On-demand deep packet inspection and protocol dissection
- **Isolation:** Runs in `nettap-tshark` container with read-only PCAP access,
  no network listeners, 512MB memory limit, no-new-privileges security option.
  All communication is via subprocess stdout/stderr — no shared memory or
  dynamic linking.

## CyberChef

- **License:** Apache License 2.0
- **Project:** https://github.com/gchq/CyberChef
- **Author:** Government Communications Headquarters (GCHQ)
- **Integration:** Static web application served by nginx in separate container
- **Purpose:** Data encoding/decoding, format conversion, and forensic analysis
- **Isolation:** Runs in `nettap-cyberchef` container as a static website.
  NetTap embeds it via iframe/link. No server-side code interaction.

## Malcolm Stack (CISA)

- **License:** Various (see below)
- **Project:** https://github.com/cisagov/Malcolm
- **Components:**
  - OpenSearch / OpenSearch Dashboards — Apache 2.0
  - Zeek — BSD 3-Clause
  - Suricata — GPL 2.0 (containerized, arm's length)
  - Arkime — Apache 2.0
  - Logstash — Elastic License 2.0 / SSPL (dual-licensed)
  - Filebeat — Elastic License 2.0 / SSPL (dual-licensed)
  - Redis — BSD 3-Clause
  - Nginx — BSD 2-Clause

## Note on GPL Components

TShark and Suricata are licensed under GPL-2.0. NetTap integrates these
components strictly at "arm's length" — they run in isolated Docker containers
with all communication happening via subprocess calls, pipes, or HTTP. NetTap's
own source code does not link against, import, or embed any GPL-licensed code.
This isolation pattern is explicitly supported by GPL interpretation for
aggregate works distributed alongside GPL software.
