# Tools Section Design

**Goal:** Create a unified `/tools` section in the sidebar with 10 network analysis and utility tools, consolidating existing tools (tshark, CyberChef) and adding new ones (DNS Recon, Subnet Calculator, MAC Lookup, Ping/Traceroute, SSL Cert Viewer, Port Reference, Base64/Hex Converter).

**Architecture:** New sidebar nav entry "Tools" linking to `/tools` index (card grid grouped by category). Each tool gets its own sub-page. Backend tools use daemon API endpoints with subprocess execution (dig, ping, traceroute, openssl). Frontend-only tools run entirely in the browser.

## Route Structure

| Route | Tool | Backend | Status |
|-------|------|---------|--------|
| `/tools` | Tools Index (card grid) | No | NEW |
| `/tools/tshark` | Packet Analysis | Existing | NEW page, existing backend |
| `/tools/cyberchef` | CyberChef | Existing | MOVE from `/system/cyberchef` |
| `/tools/dns-recon` | DNS Reconnaissance | NEW | NEW |
| `/tools/subnet-calc` | Subnet Calculator | No | NEW (pure frontend) |
| `/tools/mac-lookup` | MAC Vendor Lookup | NEW | NEW |
| `/tools/ping` | Ping & Traceroute | NEW | NEW |
| `/tools/ssl-cert` | SSL Certificate Viewer | NEW | NEW |
| `/tools/port-reference` | Port Reference Table | No | NEW (pure frontend) |
| `/tools/base64` | Base64/Hex Converter | No | NEW (pure frontend) |

Existing WHOIS (`/lookup/whois/[ip]`) and DNS (`/lookup/dns/[ip]`) pages stay at current routes. Tools index links to them.

## Backend Endpoints (daemon)

### DNS Recon — `POST /api/tools/dns-recon`
- Input: `{ "domain": "example.com", "record_types": ["A","AAAA","MX","NS","TXT","SOA","CNAME"] }`
- Runs `dig` subprocess for each record type
- Returns structured results per record type

### MAC Lookup — `GET /api/tools/mac-lookup/{mac}`
- Validates MAC format, looks up OUI prefix in bundled IEEE database
- Returns vendor name, address, MAC prefix

### Ping — `POST /api/tools/ping`
- Input: `{ "target": "8.8.8.8", "count": 4 }`
- Runs `ping -c N target` with 15s timeout
- Returns parsed RTT stats (min/avg/max/stddev), packet loss, individual results

### Traceroute — `POST /api/tools/traceroute`
- Input: `{ "target": "8.8.8.8", "max_hops": 30 }`
- Runs `traceroute target` with 30s timeout
- Returns parsed hops (hop number, IP, hostname, RTT)

### SSL Certificate — `POST /api/tools/ssl-cert`
- Input: `{ "host": "example.com", "port": 443 }`
- Runs `openssl s_client -connect host:port` with 10s timeout
- Parses certificate chain: subject, issuer, validity, SANs, serial, fingerprint

## Frontend-Only Tools

### Subnet Calculator
- CIDR notation input (e.g., 192.168.1.0/24)
- Calculates: network address, broadcast, first/last usable, host count, netmask, wildcard mask
- All JavaScript math, no backend

### Port Reference
- Static JSON of ~200 well-known ports (0-1023 + common high ports)
- Searchable, filterable table (by port number, protocol, service name)
- No backend needed

### Base64/Hex Converter
- Input textarea, output textarea
- Operations: Base64 encode/decode, Hex encode/decode, URL encode/decode
- All browser-native APIs (btoa/atob, TextEncoder)

## Tools Index Page
Card grid grouped by category:
- **Network:** Ping/Traceroute, Subnet Calculator, Port Reference
- **Analysis:** TShark, CyberChef, Base64/Hex
- **Lookup:** DNS Recon, WHOIS, DNS, MAC Lookup, SSL Cert

Each card: icon + name + one-line description + status badge (for backend tools).

## Design Pillars
- **Self-contained:** No external API dependencies, everything runs on the appliance
- **Safe:** All inputs validated, subprocess timeouts, no shell=True
- **Consistent:** Same page layout pattern as existing lookup pages (back button, search bar, results)
