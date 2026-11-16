"""Build site/features.html and site/404.html, reusing index.html's sprite, nav and footer.

Every feature claim comes from the 2026-11-15 inventory of origin/main (web/src/routes, daemon/services, docs).
Run: python3 website/build-features.py <out-dir>  (build.sh runs it with dist/)
"""
import html
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).parent / 'site'
INDEX = (ROOT / 'index.html').read_text()
OUT = pathlib.Path(sys.argv[1])

EXTRA_ICONS = {  # from nettap-design-system/assets/Icons
    'home': '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
    'search': '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    'settings': '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M2 14h4M10 8h4M18 16h4"/>',
    'tools': '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.8-3.8a6 6 0 0 1-7.9 7.9l-6.9 6.9a2.1 2.1 0 0 1-3-3l6.9-6.9a6 6 0 0 1 7.9-7.9z"/>',
    'logs': '<path d="M4 6h16M4 12h8M4 18h6"/><circle cx="17" cy="16" r="3"/><path d="m21 20-1.8-1.8"/>',
    'iot': '<path d="M9 2v5M15 2v5"/><path d="M6 7h12v4a6 6 0 0 1-12 0z"/><path d="M12 17v5"/>',
    'refresh': '<path d="M20 12a8 8 0 1 1-2.3-5.7L20 8.5"/><path d="M20 3.5v5h-5"/>',
    'warn': '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
    'user': '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    'changelog': '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
}

# (icon, title, description, tags)
GROUPS = [
    dict(id='overview', label='Overview', icon='home', title='The whole network at a glance.',
         lede='Big numbers first, details on click. Every time chart opens the moment behind it.',
         img=('home.jpg', 'NetTap Home: bandwidth, connections, alerts and devices with trends, and the bandwidth chart'),
         items=[
             ('home', 'Home', 'Bandwidth, connections, alerts and devices, each with its trend against the previous period, from the last hour to the last 30 days.', []),
             ('bandwidth', 'Charts that open the moment', 'Click or drag across a time chart to open that window: its bandwidth, protocols, categories, alerts and new devices.', []),
             ('live', 'Live monitor', 'Connections to the world, refreshed every 3 seconds, with top talkers and a live feed you can pause and filter.', []),
             ('dns', '3D globe', 'Packets fly from your home to each country they reach. Expand it to fill the window, or switch to a flat map.', []),
             ('bandwidth', 'Monthly bandwidth', 'Internet use this month, a month-end projection, the top 10 users and the busiest hours. Traffic between your own devices is left out.', []),
             ('filter', '18 traffic categories', 'From streaming and gaming to ads and tracking, worked out from who each destination belongs to.', []),
             ('system', 'Capture health', 'Home shows how many packets the box saw, and how many it missed, over the last hour.', []),
         ]),
    dict(id='devices', label='Devices', icon='devices', title='Every device, by name.',
         lede='NetTap sorts the traffic by device, names what it can and lets you name the rest.',
         img=('device-detail.jpg', 'A NetTap device page: traffic, destinations, protocols and alerts for one device'), flip=True,
         items=[
             ('devices', 'Devices by type', "Computers, phones and tablets, media, IoT, infrastructure and unknown, with each device's maker, likely OS, traffic and alerts.", []),
             ('search', 'Names it works out itself', 'From UniFi aliases, DHCP hostnames and mDNS names, or failing that the maker of the network card.', []),
             ('user', 'Your names and pictures', 'Rename any device and give it one of 12 icons or your own photo. Photos are cropped in your browser, which strips their metadata.', []),
             ('warn', 'New devices up front', 'Devices first seen in the last 24 hours are listed at the top, so a newcomer never slips by.', []),
             ('infra', 'A page for every device', 'Addresses, maker, hostnames, first and last seen, bandwidth over time, top destinations, protocols, lookups and alerts.', []),
             ('threats', 'Risk score', "A 0 to 100 score from a device's alerts, unusual connections and upload spikes, banded from low to critical.", []),
             ('live', 'Live bandwidth per device', 'Download and upload every 2 seconds, with a 5-minute chart.', ['Opt-in', 'Mirror mode']),
             ('connections', 'Compare two periods', 'See which destinations a device started or stopped talking to, and which changed the most.', []),
             ('iot', 'IoT trust score', 'A score and an A to F grade for each smart-home device, across privacy, security and behaviour. Checks it can\'t measure are left out, not guessed.', []),
             ('dns', 'Local services', 'Speakers, printers, casting, hubs and file shares your devices announce on the network, in one searchable list.', []),
             ('changelog', 'Changelog', 'When devices joined, how much data new devices moved, and when old data was cleared.', []),
         ]),
    dict(id='alerts', label='Alerts and threats', icon='alerts', title='Alerts you can act on.',
         lede='Suricata spots it. NetTap explains it in plain English and tells you what to do next.',
         img=('threats.jpg', 'The NetTap Threats page: the threat score, attack chains and behaviour findings'),
         items=[
             ('alerts', 'Alerts by severity', 'High, medium, low and info, on a timeline, by category or as one list, with the top signatures, devices and sources.', []),
             ('logs', 'What happened, and what to do', 'Each alert opens with what happened, the risk in context and a recommendation, written for people rather than analysts.', []),
             ('filter', '13 alert categories', 'From credential abuse and malware to IoT anomalies, each mapped to MITRE ATT&CK techniques.', []),
             ('check', 'Suppress or mark false', 'One click hides a noisy alert or marks it as a false positive, from the list or the alert itself.', []),
             ('live', 'Activity kept apart', 'Informational rules, such as Tor, peer-to-peer or games, show as activity and stay out of totals and scores.', []),
             ('threats', 'Threat score', 'One 0 to 100 number for the whole network, with a note on exactly how it is worked out.', []),
             ('changelog', 'Beaconing', 'Spots a device calling one server on a schedule, and ignores protocols that repeat by design.', []),
             ('dns', 'DNS anomalies', 'Flags generated-looking names, DNS tunnelling and spikes of failed lookups.', []),
             ('connections', 'Lateral movement', 'Device-to-device connections on admin services, where an intruder would move next.', []),
             ('warn', 'Attack chains', 'Follows one device through reconnaissance, exploit, malware and data theft within 24 hours.', []),
             ('pcap', 'Automatic investigations', "For critical alerts, NetTap gathers both hosts' profiles and seven days of their connections for you.", []),
             ('search', 'Known bad addresses', "Addresses on Suricata's blocklist rules are flagged wherever they appear.", []),
         ]),
    dict(id='detection', label='Detection', icon='threats', title='Rules that stay current.',
         lede='Suricata with free, community-maintained rules, updated safely, and room for your own.',
         items=[
             ('refresh', 'Four free rule sources', 'Emerging Threats Open, the abuse.ch SSL blacklist, Echap stalkerware and IPFire DBL.', []),
             ('check', 'Safe rule updates', 'Rules update when Suricata starts, every night and on demand. An update is kept only if Suricata loads it cleanly.', []),
             ('threats', 'Emerging Threats Pro', 'Add a Pro code and Suricata switches to ET Pro. The code is checked with Proofpoint, then stays on the box.', ['Optional', 'Uses the internet']),
             ('logs', 'Your own rules', 'Write your own alert rules. NetTap checks them, then tests them on a throwaway copy of Suricata before loading them.', []),
             ('connections', 'QUIC counted once', 'QUIC is identified as its own protocol, not counted twice as QUIC and TLS.', []),
         ]),
    dict(id='traffic', label='Traffic', icon='connections', title='Follow any conversation.',
         lede='Search every connection, lookup and certificate, then move between devices, addresses and domains.',
         items=[
             ('connections', 'Connections', 'Every session, with a flow diagram from device to protocol to destination, filters, and the packets behind each one.', []),
             ('logs', 'Log Explorer', "Search Zeek's connection, DNS, HTTP, TLS, file, DHCP and SMTP logs and Suricata's alerts, then export to CSV.", []),
             ('dns', 'DNS analytics', 'Lookups over time, the most-asked names, failed lookups and suspicious patterns, device by device.', []),
             ('certs', 'Certificates', "Finds unverified, expired and weak certificates, and your own devices' certificates that expire within 30 days.", []),
             ('search', 'Search from anywhere', 'Type an IP address, device, MAC address or domain in the top bar and go straight to its page.', []),
             ('dns', 'Domain pages', 'Who looked a name up, what it resolved to, its secure sessions and any alerts.', []),
             ('infra', 'Address pages', 'For any internet address: which of your devices talked to it, on which ports, and its location, network and owner.', []),
             ('copy', 'Every IP is a shortcut', 'Right-click an address to copy it, look it up, ping it, trace it or see its alerts.', []),
             ('pcap', 'Investigations', 'Keep a case with a severity, tags, notes and a status from open to closed.', []),
         ]),
    dict(id='packets', label='Packets', icon='pcap', title='Down to the last byte.',
         lede='NetTap keeps full packet captures, so you can always check what was actually sent.',
         img=('packet-detail.jpg', 'NetTap Packet analysis: one packet decoded layer by layer, with its raw bytes'), flip=True,
         items=[
             ('pcap', 'PCAP search', 'Search captures with a Wireshark display filter or six quick filters, preview a file and download what matches.', []),
             ('filter', 'Ask a question', 'Pick a device, who it talked to, a port, the kind of traffic and when. NetTap writes the filter and finds the files.', []),
             ('logs', '37 ready-made filters', 'In 6 groups, from name lookups to logins and remote access, plus 5 common questions.', []),
             ('infra', 'Layer by layer', 'Open a packet to see each decoded layer and its raw bytes.', []),
             ('bandwidth', 'The conversation over time', 'Charts show how a conversation unfolded and who sent what.', []),
             ('download', 'Take it with you', 'Download the packets you found and open them in Wireshark.', []),
             ('tools', 'CyberChef built in', 'Encode, decode and pick apart data with CyberChef, running on the box.', []),
             ('system', 'Capture controls', 'Turn capture on or off and set the file size, from 10 MB to 10 GB.', []),
         ]),
    dict(id='tools', label='Tools', icon='tools', title='14 tools on the box.',
         lede='The network tools you would reach for anyway, built into the dashboard and run from NetTap.',
         items=[
             ('live', 'Ping, traceroute and MTU', 'Check a host, trace the route to it and find the largest packet that gets through.', []),
             ('bandwidth', 'LAN speed test', 'Measure upload and download between NetTap and another device on your network running an iperf3 server.', []),
             ('changelog', 'DHCP lease timeline', 'Every DHCP exchange NetTap saw for a device, with a link to the packets.', []),
             ('dns', 'DNS lookups and resolver check', "See a name's records, and ask up to 6 resolvers the same question to check they agree.", []),
             ('infra', 'Subnet calculator', 'Work out ranges and masks, right in your browser.', []),
             ('connections', 'IPv6 toolkit', 'Any IPv6 address explained in plain English: its type, short and full forms, and the device part.', []),
             ('search', 'Port reference', 'A searchable list of well-known ports.', []),
             ('devices', 'MAC vendor lookup', "Name a device's maker from its network card, offline.", []),
             ('certs', 'Certificate viewer', 'See the certificate any host presents: issuer, validity, names and fingerprint.', []),
             ('user', 'WHOIS, reverse DNS and GeoIP', 'Who owns an address, the name it answers to and where it is.', ['Uses the internet']),
             ('copy', 'Base64 and hex', 'Convert between text, Base64 and hex in your browser.', []),
         ]),
    dict(id='notifications', label='Notifications', icon='alerts', title='Hear about it, without the flood.',
         lede='Get the alerts that matter where you already are, grouped so a noisy night stays readable.',
         items=[
             ('alerts', 'Six ways to hear', 'Email, Discord, Slack, Telegram, Pushover or any webhook, including ntfy or Gotify on your own network.', []),
             ('filter', 'Choose what reaches you', 'Pick a minimum severity for each channel: critical, high, medium or all.', []),
             ('refresh', 'No floods', 'Alerts are grouped into one digest a minute, retried if a send fails, and capped at 100 a day per channel.', []),
             ('check', 'Test it first', 'Send a test message and see the last 20 delivery attempts.', []),
             ('alerts', 'In-app bell', 'An unread count and the last 15 alerts, updated live.', []),
             ('download', 'Exports', 'CSV from Log Explorer, packet downloads and a settings backup file.', []),
         ]),
    dict(id='upkeep', label='Storage and health', icon='system', title='Looks after itself.',
         lede='Sensible retention, a disk that never fills and a drive that is watched for wear.',
         items=[
             ('system', 'Sensible retention', '90 days of records, alerts included, and 30 days of packet captures, capped at a quarter of the disk. Change it in Settings.', []),
             ('warn', 'Never fills the disk', 'Checked every 5 minutes: expired data goes at 80%, the oldest at 90%, and capture pauses at 95% until there is room.', []),
             ('search', 'Clean up with a preview', 'See exactly what will go, and how much space it frees, before anything is deleted.', []),
             ('infra', 'SSD health', "Reads the drive's temperature, wear and errors every hour, and warns before it wears out.", []),
             ('refresh', 'Hardware watchdog', 'If the box ever hangs, the watchdog reboots it.', []),
             ('connections', 'Bridge bypass', "In inline bridge mode, see the bridge's health and switch it to bypass.", ['Bridge mode']),
         ]),
    dict(id='setup', label='Setup and updates', icon='settings', title='Up and running in an afternoon.',
         lede='One installer, a guided setup and updates you can roll back.',
         items=[
             ('download', 'One installer', "Blinks each port's light so you can tell them apart, installs Docker and the tested Malcolm release, and prints a wiring diagram.", []),
             ('user', 'A setup code only you have', 'The installer prints a one-time code, so nobody else on your network can claim the box first.', []),
             ('settings', 'Setup wizard', 'Checks the ports and disk, then walks you through capture mode, interfaces, storage, enrichment and your account.', []),
             ('connections', 'Three ways to connect', 'A mirror port (recommended and tested), an inline bridge (advanced) or DHCP gateway (in development).', []),
             ('live', 'Guided go-live', 'A guided cable swap for the bridge, or a check and switch-over for DHCP gateway.', []),
             ('refresh', 'Updates from the dashboard', "See versions, check for updates, update one part or all of them, roll back and read what's new.", ['Uses the internet']),
             ('infra', 'Safe Malcolm updates', 'Only releases NetTap has tested. Your data is backed up first and the old version comes back if a step fails.', []),
             ('copy', 'Backup and restore', 'Your settings, device names, pictures and suppressions in one file. Passwords and keys are left out.', []),
             ('iot', 'UniFi integration', 'Bring in device names, models and networks from your UniFi controller.', ['Optional']),
             ('home', 'Three themes', 'Ember, Graphite and Spectrum, plus your default time range.', []),
         ]),
    dict(id='privacy', label='Privacy', icon='certs', title='Yours, and only yours.',
         lede='Your network data never leaves the box, and the few things that touch the internet are listed below.',
         items=[
             ('check', 'No cloud, no account, no subscription', 'Your traffic stays on the box. Nothing is sent home and there is no telemetry.', []),
             ('dns', 'What does use the internet', 'Update checks, rule downloads and WHOIS lookups, plus the optional ET Pro and location checks and any notification channels you set up.', []),
             ('user', 'One admin sign-in', 'Every page sits behind your login, with strong password hashing and a lockout after failed attempts.', []),
             ('certs', 'HTTPS on your network', 'The dashboard is served at nettap.local over HTTPS with its own certificate, which your browser asks you to trust once.', []),
             ('threats', 'Reports, never blocks', "NetTap tells you about suspicious traffic. It doesn't block it.", []),
             ('devices', 'Leave addresses out', 'Hide chosen addresses from device views. They stay in logs and alerts.', []),
         ]),
]

LIMITS = [
    'Encrypted DNS lookups (DNS over HTTPS or TLS) can\'t be read.',
    'Certificates are visible for TLS 1.2 and older. TLS 1.3 encrypts them.',
    'Packet analysis looks at up to 30 minutes at a time.',
    'Live bandwidth per device works in mirror mode only.',
    "In inline bridge mode, devices behind your router appear as the router's address.",
    'NetTap is pre-release. DHCP gateway mode is still being tested on hardware.',
]

COUNTS = [('14', 'built-in network tools'), ('37', 'ready-made packet filters'), ('13', 'alert categories'), ('6', 'ways to get alerts')]

e = html.escape


def item_html(icon, title, desc, tags):
    tag_html = ''.join(f' <span class="tag tag--soft">{e(t)}</span>' for t in tags)
    return (f'          <li class="fitem"><span class="ic-tile"><svg class="ic" aria-hidden="true"><use href="#i-{icon}"/></svg></span>'
            f'<div><h3>{e(title)}{tag_html}</h3><p>{e(desc)}</p></div></li>')


def group_html(n, g):
    head_cls = 'fgroup__head' + (' fgroup__head--flip' if g.get('flip') else '') + ('' if g.get('img') else ' fgroup__head--text')
    media = ''
    if g.get('img'):
        src, alt = g['img']
        media = (f'\n          <div class="fgroup__media" data-reveal><div class="app-frame">'
                 f'<img src="/img/{src}" width="1600" height="1000" alt="{e(alt)}" loading="lazy" decoding="async"></div></div>')
    items = '\n'.join(item_html(*it) for it in g['items'])
    return f'''    <section class="section fgroup" id="{g['id']}" aria-labelledby="{g['id']}-title">
      <div class="container">
        <div class="{head_cls}">
          <div class="fgroup__copy" data-reveal>
            <p class="eyebrow"><span class="fgroup__num">{n:02d}</span> {e(g['label'])}</p>
            <h2 class="display-l" id="{g['id']}-title">{e(g['title'])}</h2>
            <p class="lead">{e(g['lede'])}</p>
          </div>{media}
        </div>
        <ul class="flist">
{items}
        </ul>
      </div>
    </section>
'''


def block(start, end):
    i = INDEX.index(start)
    return INDEX[i:INDEX.index(end, i) + len(end)]


def relink(s, current=None):
    """index.html's in-page links point at the home page from here; `current` marks this page in the nav."""
    s = s.replace('href="#top"', 'href="/"')
    s = re.sub(r'href="#(?!main\b|i-)', 'href="/#', s)
    return s.replace(f'href="{current}"', f'href="{current}" aria-current="page"') if current else s


def page(title, desc, og_desc, path, nav, main, css=()):
    """A whole page around `main`. Root-relative assets, so the 404 page works at any depth."""
    links = ''.join(f'\n  <link rel="stylesheet" href="/{c}">' for c in ('tokens.css', 'site.css', *css))
    where = (f'\n  <meta property="og:url" content="https://nettap.dev{path}">'
             f'\n  <link rel="canonical" href="https://nettap.dev{path}">') if path else '\n  <meta name="robots" content="noindex">'
    return f'''<!doctype html>
<html lang="en-GB" data-theme="ember">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{desc}">
  <meta name="theme-color" content="#000000">
  <link rel="icon" href="/img/nettap-mark.svg" type="image/svg+xml">
  <link rel="apple-touch-icon" href="/img/apple-touch-icon.png">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{og_desc}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="NetTap">
  <meta property="og:image" content="https://nettap.dev/img/og.png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta name="twitter:card" content="summary_large_image">{where}
  <meta name="nettap-release" content="dev">
  <link rel="preload" href="/fonts/Sora-Variable.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="preload" href="/fonts/Manrope-Variable.woff2" as="font" type="font/woff2" crossorigin>{links}
  <script>document.documentElement.classList.add('js');</script>
  <script src="/site.js" defer></script>
</head>
<body>
{sprite}

  <a class="skip-link" href="#main">Skip to content</a>

{nav}

  <main id="main">
{main}
  </main>

{footer}
</body>
</html>
'''


sprite = block('  <svg width="0" height="0"', '  </svg>')
extra = ''.join(f'    <symbol id="i-{k}" viewBox="0 0 24 24">{v}</symbol>\n' for k, v in EXTRA_ICONS.items())
sprite = sprite.replace('  </svg>', extra + '  </svg>')
nav_html = block('  <header class="nav">', '  </header>')
nav = relink(nav_html, current='/features')
final = relink(block('    <section class="final"', '    </section>'))
footer = relink(block('  <footer class="footer">', '  </footer>'))

jump = '\n'.join(f'          <li><a href="#{g["id"]}">{e(g["label"])}</a></li>' for g in GROUPS)
counts = '\n'.join(f'          <li><b>{n}</b><span>{e(t)}</span></li>' for n, t in COUNTS)
limits = '\n'.join(f'            <li>{e(t)}</li>' for t in LIMITS)
groups = ''.join(group_html(i + 1, g) for i, g in enumerate(GROUPS))
total = sum(len(g['items']) for g in GROUPS)

features_main = f'''    <section class="fhero" aria-labelledby="features-title">
      <div class="container">
        <div class="fhero__grid">
        <div class="fhero__inner">
          <p class="eyebrow">Features</p>
          <h1 class="display-xl" id="features-title">Everything NetTap <span class="glow-text">can show you.</span></h1>
          <p class="lead">{total} features across {len(GROUPS)} areas, from the first glance at Home to the last byte of a packet. All of it runs on your own box.</p>
          <div class="hero__cta">
            <a class="btn btn--primary" href="https://eliasmarine.github.io/NetTap/getting-started/setup-guide/">Get started <svg class="ic arrow" aria-hidden="true"><use href="#i-arrow"/></svg></a>
            <a class="btn btn--ghost" href="https://github.com/EliasMarine/NetTap"><svg aria-hidden="true" style="fill:currentColor"><use href="#i-github"/></svg>View on GitHub</a>
          </div>
        </div>
        <div class="fhero__stack" aria-hidden="true">
          <div class="app-frame"><img src="/img/live-globe-expanded.jpg" width="1600" height="1000" alt=""></div>
          <div class="app-frame"><img src="/img/alerts.jpg" width="1600" height="1000" alt=""></div>
          <div class="app-frame"><img src="/img/packets.jpg" width="1600" height="1000" alt=""></div>
        </div>
        </div>
        <ul class="fhero__counts" aria-label="NetTap in numbers">
{counts}
        </ul>
      </div>
    </section>

    <nav class="fnav" aria-label="Feature areas">
      <div class="container">
        <ul>
{jump}
        </ul>
      </div>
    </nav>

{groups}
    <section class="section" id="limits" aria-labelledby="limits-title" style="padding-top:0">
      <div class="container">
        <div class="card limits">
          <div class="limits__copy">
            <p class="eyebrow">Good to know</p>
            <h2 class="display-m" id="limits-title">What NetTap can't see</h2>
            <p>NetTap reads traffic, it doesn't break encryption. These are the honest limits.</p>
          </div>
          <ul class="limits__list">
{limits}
          </ul>
        </div>
      </div>
    </section>

{final}'''
(OUT / 'features.html').write_text(page(
    'Features · NetTap',
    'Everything NetTap does: devices, plain-English alerts, threat detection, traffic and packet analysis, '
    '14 network tools, notifications and storage that looks after itself. All on your own box.',
    'Everything NetTap does, all on your own box. No cloud, no account, no subscription.',
    '/features', nav, features_main, css=('features.css',)))

not_found_main = f'''    <section class="section notfound" aria-labelledby="notfound-title">
      <div class="container">
        <p class="eyebrow">404</p>
        <h1 class="display-xl" id="notfound-title">This page isn’t <span class="glow-text">here.</span></h1>
        <p class="lead">The link may be old, or the address may have a typo.</p>
        <div class="hero__cta">
          <a class="btn btn--primary" href="/">Back to the home page <svg class="ic arrow" aria-hidden="true"><use href="#i-arrow"/></svg></a>
          <a class="btn btn--ghost" href="/features">See the features</a>
        </div>
      </div>
    </section>'''
not_found = 'This page isn’t on nettap.dev.'
(OUT / '404.html').write_text(page('Page not found · NetTap', not_found, not_found, None, relink(nav_html), not_found_main))
print(f'features.html: {total} features in {len(GROUPS)} groups; 404.html')
