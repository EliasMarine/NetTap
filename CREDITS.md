# Credits

NetTap depends on the work of many maintainers, researchers, designers and contributors. Thank you for building and maintaining the projects that make it possible.

NetTap's contribution is the installation and setup workflow, its own web dashboard, integrations and storage management. The underlying capture, protocol analysis, detection and search capabilities come from the upstream projects credited here.

## Network analysis and infrastructure

| Project and contributors | How NetTap uses their work |
| --- | --- |
| [Malcolm](https://github.com/cisagov/Malcolm) — CISA, Idaho National Laboratory and the Malcolm contributors | Integrated traffic analysis stack, container images and configuration foundation |
| [Zeek](https://zeek.org/) | Network connection and application-protocol metadata |
| [Suricata](https://suricata.io/) and [suricata-update](https://github.com/OISF/suricata-update) — Open Information Security Foundation and contributors | Intrusion detection and rule-source management |
| [OpenSearch and OpenSearch Dashboards](https://opensearch.org/) | Indexed traffic and alert storage, search and data exploration |
| [Logstash](https://github.com/elastic/logstash) and [Filebeat](https://github.com/elastic/beats) — Elastic and contributors | Log ingestion and processing through Malcolm's images |
| [netsniff-ng](https://github.com/netsniff-ng/netsniff-ng) | Raw packet capture |
| [Wireshark / TShark](https://www.wireshark.org/) | Packet dissection and on-demand analysis |
| [CyberChef](https://github.com/gchq/CyberChef) — GCHQ and contributors | Browser-based decoding and data transformation |
| [Arkime](https://arkime.com/) | Optional session search and packet exploration (`arkime` Compose profile) |
| [Grafana](https://grafana.com/oss/grafana/) and its [OpenSearch data source](https://github.com/grafana/opensearch-datasource) | Optional dashboards (`grafana` Compose profile) |
| [Valkey](https://valkey.io/) / [Redis](https://redis.io/) | Ingestion queue, depending on the Malcolm version and configured image |
| [NGINX](https://nginx.org/) | Reverse proxy and static content serving |
| [Docker Engine](https://github.com/moby/moby) and [Docker Compose](https://github.com/docker/compose) | Container runtime and service orchestration |
| [Linux](https://www.kernel.org/), [Ubuntu](https://ubuntu.com/) and [Debian](https://www.debian.org/) | Host networking, supported host operating system and container foundations |
| [smartmontools](https://www.smartmontools.org/) and [nvme-cli](https://github.com/linux-nvme/nvme-cli) | Storage-device health information |
| [dnsmasq](https://thekelleys.org.uk/dnsmasq/doc.html) and [Netfilter](https://www.netfilter.org/) | DHCP and forwarding support for gateway mode |

## Detection rules and threat intelligence

The Compose configuration enables these sources; the actual enabled set can change with configuration and updates:

- [Emerging Threats Open](https://rules.emergingthreats.net/) — Proofpoint and the Emerging Threats community. The optional ET Pro integration uses the operator's separately obtained subscription.
- [SSL Blacklist](https://sslbl.abuse.ch/) — abuse.ch and contributors.
- [Stalkerware indicators](https://github.com/AssoEchap/stalkerware-indicators) — Echap and contributors.
- [IPFire Domain Blocklist](https://www.ipfire.org/dbl) — the IPFire project and contributors.

These providers create and maintain the signatures and indicators consumed by Suricata. Their individual terms apply to their feeds. The source IDs are recorded in [docker/docker-compose.yml](docker/docker-compose.yml); additional sources can be managed through Suricata's rule-source catalog.

## Application libraries and development tools

- [Svelte and SvelteKit](https://svelte.dev/), [TypeScript](https://www.typescriptlang.org/), [Vite](https://vite.dev/) and [Node.js](https://nodejs.org/) — web interface, application framework and build/runtime tooling.
- [Three.js](https://threejs.org/) — globe rendering.
- [node-argon2](https://github.com/ranisalt/node-argon2) and [jsonwebtoken](https://github.com/auth0/node-jsonwebtoken) — password hashing and token handling.
- [Python](https://www.python.org/), [aiohttp](https://docs.aiohttp.org/), [opensearch-py](https://github.com/opensearch-project/opensearch-py), [psutil](https://github.com/giampaolo/psutil) and [PyYAML](https://pyyaml.org/) — daemon runtime, HTTP services, search access, system information and configuration parsing.
- [pySMART](https://github.com/truenas/py-SMART) — SMART library declared in the daemon's project metadata.
- [pytest](https://pytest.org/), [Vitest](https://vitest.dev/), [Playwright](https://playwright.dev/), [Testing Library](https://testing-library.com/), [jsdom](https://github.com/jsdom/jsdom), [Ruff](https://github.com/astral-sh/ruff) and [ShellCheck](https://www.shellcheck.net/) — testing and code checks.

The dependency manifests and lockfile record the direct packages and their transitive dependencies: [web/package.json](web/package.json), [web/package-lock.json](web/package-lock.json), [daemon/pyproject.toml](daemon/pyproject.toml) and [daemon/requirements.txt](daemon/requirements.txt). This acknowledgement list is not an exhaustive software bill of materials.

## Maps, geolocation and typography

- **Made with [Natural Earth](https://www.naturalearthdata.com/).** The country boundaries used by the map and globe come from Natural Earth's public-domain map data. Thanks to Tom Patterson, Nathaniel Vaughn Kelso and the other contributors. See the [data terms](https://www.naturalearthdata.com/about/terms-of-use/).
- **[MaxMind](https://www.maxmind.com/)** — GeoLite2 data used for geolocation when supplied through the configured Malcolm/Logstash enrichment pipeline. GeoLite2 data is created by MaxMind and remains subject to its [data terms](https://dev.maxmind.com/geoip/geolite2-free-geolocation-data/).
- **[Sora](https://github.com/sora-xor/sora-font)** — the Sora Project Authors; copyright 2019. [Bundled license](web/static/fonts/sora/OFL.txt).
- **[Manrope](https://github.com/googlefonts/manrope)** — the Manrope Project Authors; copyright 2018. [Bundled license](web/static/fonts/manrope/OFL.txt).
- **[JetBrains Mono](https://github.com/JetBrains/JetBrainsMono)** — the JetBrains Mono Project Authors; copyright 2020. [Bundled license](web/static/fonts/jetbrains-mono/OFL.txt).

## Licenses and independence

NetTap's [GPLv3 license](LICENSE) applies to NetTap-original work. Upstream code, images, datasets, rules and fonts retain their respective copyrights and licenses. See [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md) and the notices shipped with each dependency for details; these credits do not replace those notices or redistribution requirements.

NetTap is independently maintained. Naming these projects credits their work and does not imply affiliation, sponsorship or endorsement.
