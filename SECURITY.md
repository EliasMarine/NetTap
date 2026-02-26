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
- Change default credentials during the setup wizard
- Enable the firewall (`scripts/install/setup-firewall.sh`)
- Monitor the System page for health alerts
- Review Suricata alerts regularly
