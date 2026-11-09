# 2026-11-09 First-run and container security (NET-229, NET-237 B-o and B-p)

Branch `fix/net-229-first-run-security` (from `fix/release-audit-2026-11` at `e3391970`). Release audit
blocker B6 (findings A13 and A14) plus P2 items B-o and B-p.

## Problems

- **A13:** on a fresh install, the first host on the LAN to reach the web app could create the admin account.
- **A14 (confirmed on the G11):** `nettap-tshark` ran as uid 0 on `docker_default`, next to Dashboards (which
  trusts `X-Forwarded-User` from nginx), OpenSearch, nginx, web, Logstash, Redis and Malcolm's API. TShark parses
  packets an attacker can craft.
- **B-o:** CyberChef was served without a login. Other hardening items needed a written reason.
- **B-p:** 5xx replies carried exception text: OpenSearch URLs, host:port pairs, Docker stderr (`detail`,
  `output`). The web proxy added the Node connection error to "Daemon unreachable".

## Root cause

- First-run routes were open by design while no user existed, and the account step asked for nothing the
  owner has and a LAN host doesn't.
- `nettap-tshark` kept the compose default network. The daemon only ever runs TShark through `docker exec`, so it
  never needed one. It ran as root because an older capture layout wrote files a non-root user couldn't read.
  Captures are 0644 now.
- About 150 handlers build 5xx replies from `str(exc)`, and nothing between them and the client checked them.

## Fix

- **Setup code** (`web/src/lib/server/auth.ts`):
  - `ensureSetupCode()` writes a 12-symbol code (~59 bits, `XXXX-XXXX-XXXX`) to
    `/var/lib/nettap-web/setup-code` (mode 0600, written then renamed) while no user exists, and replaces a
    missing, short or damaged file. It deletes the file once a user exists. Only nettap-web mounts `web-data`.
    The `daemon-auth` volume is read-only in web and the daemon can read it, so it was not used.
  - `setupCodeMatches()` accepts only a well-formed code and compares SHA-256 digests with
    `crypto.timingSafeEqual`.
  - `checkSetupCode()` in `login.ts` takes each try from the login's per-IP budget (5 a minute).
  - The `createAdmin` action checks the code before anything else and deletes it after the admin is created.
  - The `init` hook and the wizard's `load` make sure a code exists.
  - The Account step has a "Setup code" field, with the command to read the code again.
  - Installs with an admin never see a code: `createAdmin` still sends them to /login first, and login never
    looks at the code.
- **Installer:** `nettap_setup_code` (`scripts/common.sh`) waits up to 60 s for nettap-web, then prints the
  code. Nothing is printed once an admin exists. The install summary card and `activate-bridge.sh` show it with
  `sudo docker exec nettap-web cat /var/lib/nettap-web/setup-code`. The deferred summary says activate-bridge
  prints it. README quick start documents it.
- **TShark:** `network_mode: none`, `user: "65534:65534"`. On the G11, as uid 65534, `tshark -r` and
  `capinfos` read real captures.
- **CyberChef:** `/cyberchef/` uses `auth_request /_nettap_auth`, the same as `/grafana/`.
- **Accepted risks** in `SECURITY.md`:
  - The daemon binds 0.0.0.0:8880. The web reaches it through the Docker gateway, whose address isn't pinned.
  - The daemon is root-equivalent on the host.
  - The capture containers run as root.
  - Images are pinned by tag, not by digest.
  - The other first-run routes stay open until the admin exists.
- **5xx replies** (`daemon/api/error_replies.py`, the innermost middleware):
  - A 5xx JSON reply keeps `error` only when the message is on the allowlist of hand-written messages (one
    template for the WAN lookup). Any other `error` becomes "Something went wrong; the daemon log has the details."
  - Only bool, number and null fields survive. `detail`, `output`, lists and objects are dropped.
  - The original reply is logged.
  - A guard test AST-scans `daemon/api` so a new hand-written 5xx message must join the list.
  - `daemonFetch` now says only "Daemon unreachable" and logs the reason. The setup action's 500 no longer
    echoes `err.message`.

## Files

`web/src/lib/server/{auth,login,daemon}.ts`, `web/src/hooks.server.ts`, `web/src/routes/setup/+page.{server.ts,svelte}`,
`web/e2e/{shell,setup-wizard}.spec.ts`, `web/e2e/visual/auth.setup.ts`, `web/playwright.visual.config.ts`,
`daemon/api/{error_replies,server}.py`, `docker/docker-compose.yml`, `docker/nginx.conf`, `scripts/common.sh`,
`scripts/install/{ui,activate-bridge}.sh`, `README.md`, `SECURITY.md`, and tests.

## Tests

- **Web:** `setup-action.test.ts` covers:
  - no code, a wrong code, and any case or spacing
  - single use
  - the 6th try in a minute is refused, while another address still works
  - an empty, truncated or malformed code file
  - an existing admin gets no code and signs in as before
- **Web, other files:** `daemon.test.ts` (no reason in the unreachable reply) and `suricata-rules.test.ts` (a 500
  without `output`).
- **Daemon:** `tests/test_error_replies.py` covers the middleware cases, and these through the real
  `create_app()`: a storage 500, a packets 502 with stderr in `detail`, and a rule update whose subprocess raises
  `OSError`. It also has the allowlist guard.
- **Bats:**
  - `/cyberchef/` needs a login
  - TShark has `network_mode: none` and runs as 65534
  - the install card prints the code, and prints nothing when an admin exists
- **Fail-before:** 9 web tests, 3 daemon `create_app` tests and 3 bats tests fail on the old files.

## Lessons

- A pattern that guesses which messages are exception text leaks (Docker stderr matched none of them). A fixed
  allowlist plus a guard test fails safe.
- Read-only volume mounts decide where a secret can live: `daemon-auth` looked right but is read-only in web.

## Next steps

- Deploy: recreate `nettap-storage-daemon` and `nettap-web` (both rebuilt), `nettap-tshark`, then
  `nettap-nginx` with `--force-recreate`.
- Follow-up for the lead: `scripts/install/setup-firewall.sh` denies 8880 on every interface. Since the daemon
  moved to host networking, that rule would also block `nettap-web` reaching the daemon through the Docker gateway.
