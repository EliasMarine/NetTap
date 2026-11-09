# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 1.x.x   | Yes               |
| < 1.0   | No (pre-release)  |

## Reporting a Vulnerability

If you discover a security vulnerability in NetTap, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

### How to Report

1. **GitHub Private Advisory** (preferred): Go to the [Security Advisories](https://github.com/EliasMarine/NetTap/security/advisories) page and click "New draft security advisory."
2. **Email**: Send details to the maintainers via the email listed in the GitHub profile.

### What to Include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response Timeline

- **Acknowledgment**: Within 48 hours of report
- **Initial assessment**: Within 5 business days
- **Fix for critical issues**: Within 30 days
- **Fix for non-critical issues**: Within 90 days

### What Qualifies as a Security Issue

- Authentication or authorization bypass
- Remote code execution
- SQL/NoSQL injection
- Cross-site scripting (XSS) in the dashboard
- Privilege escalation
- Sensitive data exposure (credentials, API keys)
- Container escape or host compromise
- Network traffic interception on the management interface

### Out of Scope

- Vulnerabilities in upstream dependencies that are already publicly disclosed (open a regular issue instead)
- Denial of service on the capture bridge (NetTap is inline; availability is handled by the bypass system)
- Issues requiring physical access to the appliance
- Social engineering attacks
- Vulnerabilities in software not distributed with NetTap

### Credit

We appreciate responsible disclosure and will credit reporters in the release notes (unless you prefer to remain anonymous). Let us know your preference when reporting.

## Security Best Practices for Operators

- Keep NetTap updated to the latest version
- Use the management interface on a separate network segment
- Keep the installer's one-time setup code to yourself until the setup wizard has created the admin account (there are no default credentials)
- Enable the firewall (`scripts/install/setup-firewall.sh`)
- Monitor the System page for health alerts
- Review Suricata alerts regularly

## Known, accepted risks

These were reviewed in the first-release audit (NET-229, 2026-11-09) and are accepted for v1.0, with the reason:

| What | Why it stays |
|------|--------------|
| The daemon API listens on `0.0.0.0:8880`. | The daemon uses host networking, and `nettap-web` reaches it through the Docker bridge gateway (`host.docker.internal`), whose address Docker picks for each network. Binding only to that address needs a pinned Docker subnet, which recreates every container on the network and can clash with your LAN. Every route except `GET /api/health` needs the shared daemon token, which only `nettap-web` and the daemon can read. With the firewall on (`setup-firewall.sh --enable`), only NetTap's Docker network can reach port 8880. |
| The daemon is equivalent to root on the host. It mounts the Docker socket and the host's systemd, netplan, sysctl and `/etc/nettap` folders, and has `SYS_ADMIN`, `NET_ADMIN`, `SYS_RAWIO`, `pid: host` and `/dev`. | Its job needs them: System › Updates recreates Malcolm's containers, the bridge and DHCP gateway modes write host network config, and drive health reads SMART data. It sits behind the token above and parses no packets itself. |
| Malcolm's capture containers (Zeek, Suricata, netsniff-ng, Arkime) run as root with `NET_ADMIN`, `NET_RAW` and, for netsniff-ng, `SYS_ADMIN`. | Live capture on the host's interfaces needs them, and Malcolm's images expect it. They use host networking and get no NetTap credentials. |
| Images are pinned by tag (Malcolm's tested release, `nginx:1.30-alpine`, `grafana/grafana:10.4.2`), not by digest. | System › Updates moves between tested Malcolm tags, which a digest pin would block. A tag can in principle be re-pushed; pin digests in `docker/docker-compose.yml` yourself if that matters to you. |
| Malcolm's `api` container (Malcolm's own REST API, port 5000) keeps running, although NetTap never calls it. | Malcolm's dashboards set up an OpenSearch alert channel that points at it, and System › Updates stops, backs up and restarts it with the rest of Malcolm. Removing it would change the tested update and rollback path. It publishes no port, so only containers on Malcolm's Docker network reach it, and TShark has no network. |

<!-- OLD (NET-229 follow-up: the wizard's API calls now need the setup code, typed on the Welcome step): | The first-run wizard routes other than account creation (`/api/setup/*`, `/api/bridge/*`, the UniFi test) answer anyone on the LAN until the admin account exists. | The setup code guards the account, so nobody else can claim the box. Before setup is finished there is nothing stored to read. Finish setup soon after the install. | -->

Until the admin account exists, the first-run wizard's API calls (`/api/setup/*`, `/api/bridge/*`, the UniFi test) need the setup code too: the wizard asks for it on its first step.

TShark, which decodes captured packets on request, runs as `nobody` with no network at all (`network_mode: none`), so a packet that exploits a TShark bug can't reach the other containers. CyberChef and OpenSearch Dashboards need a NetTap login.
