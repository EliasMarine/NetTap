"""Real dig output for the resolver compare tests (NET-262).

Captured on the G11 on 2026-11-13 with
`dig @<resolver> <name> <type> +noall +answer +comments +stats +time=2 +tries=1`
inside nettap-storage-daemon (dig 9.18.49). Everything dig wrote went to stdout.
"""

# @192.168.1.1 setup.ui.com A: the router answers its own address
ROUTER_PRIVATE = (
    ";; Got answer:\n"
    ";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 58928\n"
    ";; flags: qr aa rd ra; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL: 1\n"
    "\n"
    ";; OPT PSEUDOSECTION:\n"
    "; EDNS: version: 0, flags:; udp: 1232\n"
    ";; ANSWER SECTION:\n"
    "setup.ui.com.\t\t0\tIN\tA\t192.168.1.1\n"
    "\n"
    ";; Query time: 0 msec\n"
    ";; SERVER: 192.168.1.1#53(192.168.1.1) (UDP)\n"
    ";; WHEN: Fri Nov 13 21:07:57 UTC 2026\n"
    ";; MSG SIZE  rcvd: 57\n"
    "\n"
)

# @1.1.1.1 setup.ui.com A: the public answer
CLOUDFLARE_PUBLIC = (
    ";; Got answer:\n"
    ";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 58120\n"
    ";; flags: qr rd ra; QUERY: 1, ANSWER: 4, AUTHORITY: 0, ADDITIONAL: 1\n"
    "\n"
    ";; OPT PSEUDOSECTION:\n"
    "; EDNS: version: 0, flags:; udp: 1232\n"
    ";; ANSWER SECTION:\n"
    "setup.ui.com.\t\t32\tIN\tA\t3.169.231.76\n"
    "setup.ui.com.\t\t32\tIN\tA\t3.169.231.111\n"
    "setup.ui.com.\t\t32\tIN\tA\t3.169.231.94\n"
    "setup.ui.com.\t\t32\tIN\tA\t3.169.231.81\n"
    "\n"
    ";; Query time: 8 msec\n"
    ";; SERVER: 1.1.1.1#53(1.1.1.1) (UDP)\n"
    ";; WHEN: Fri Nov 13 21:08:22 UTC 2026\n"
    ";; MSG SIZE  rcvd: 105\n"
    "\n"
)

# @9.9.9.9 nettap A: a LAN-only name
QUAD9_NXDOMAIN = (
    ";; Got answer:\n"
    ";; ->>HEADER<<- opcode: QUERY, status: NXDOMAIN, id: 54163\n"
    ";; flags: qr rd ra ad; QUERY: 1, ANSWER: 0, AUTHORITY: 1, ADDITIONAL: 1\n"
    "\n"
    ";; OPT PSEUDOSECTION:\n"
    "; EDNS: version: 0, flags:; udp: 512\n"
    "; EDE: 29: (Result synthesized from aggressive NSEC cache (RFC8198))\n"
    ";; Query time: 522 msec\n"
    ";; SERVER: 9.9.9.9#53(9.9.9.9) (UDP)\n"
    ";; WHEN: Fri Nov 13 21:07:57 UTC 2026\n"
    ";; MSG SIZE  rcvd: 171\n"
    "\n"
)

# @192.0.2.53 example.com A: nothing listening (exit 9)
TIMED_OUT = (
    ";; communications error to 192.0.2.53#53: timed out\n"
    "\n"
    "; <<>> DiG 9.18.49-1~deb12u3-Debian <<>> @192.0.2.53 example.com A +noall +answer +comments +stats +time=2 +tries=1\n"
    "; (1 server found)\n"
    ";; global options: +cmd\n"
    ";; no servers could be reached\n"
)

# @2606:4700:4700::1111 example.com AAAA: the G11 has no IPv6 route (exit 9)
V6_UNREACHABLE = (
    ";; UDP setup with 2606:4700:4700::1111#53(2606:4700:4700::1111) for example.com failed: network unreachable.\n"
    ";; no servers could be reached\n"
)

# @9.9.9.9 example.com TXT
QUAD9_TXT = (
    ";; Got answer:\n"
    ";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 1016\n"
    ";; flags: qr rd ra ad; QUERY: 1, ANSWER: 2, AUTHORITY: 0, ADDITIONAL: 1\n"
    "\n"
    ";; OPT PSEUDOSECTION:\n"
    "; EDNS: version: 0, flags:; udp: 1232\n"
    ";; ANSWER SECTION:\n"
    'example.com.\t\t300\tIN\tTXT\t"v=spf1 -all"\n'
    'example.com.\t\t300\tIN\tTXT\t"_k2n1y4vw3qtb4skdx9e7dxt97qrmmq9"\n'
    "\n"
    ";; Query time: 10 msec\n"
    ";; SERVER: 9.9.9.9#53(9.9.9.9) (UDP)\n"
    ";; WHEN: Fri Nov 13 21:07:37 UTC 2026\n"
    ";; MSG SIZE  rcvd: 109\n"
    "\n"
)

# @9.9.9.9 www.github.com A: a CNAME chain
QUAD9_CNAME = (
    ";; Got answer:\n"
    ";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 46031\n"
    ";; flags: qr rd ra; QUERY: 1, ANSWER: 2, AUTHORITY: 0, ADDITIONAL: 1\n"
    "\n"
    ";; OPT PSEUDOSECTION:\n"
    "; EDNS: version: 0, flags:; udp: 1232\n"
    ";; ANSWER SECTION:\n"
    "www.github.com.\t\t1944\tIN\tCNAME\tgithub.com.\n"
    "github.com.\t\t46\tIN\tA\t20.172.24.160\n"
    "\n"
    ";; Query time: 1149 msec\n"
    ";; SERVER: 9.9.9.9#53(9.9.9.9) (UDP)\n"
    ";; WHEN: Fri Nov 13 21:07:22 UTC 2026\n"
    ";; MSG SIZE  rcvd: 73\n"
    "\n"
)

# QUAD9_CNAME with only its Query time raised to 3.4 s: Quad9 from the G11 sometimes took 2-4 s
# (at +time=2 those read as no reply), but none was slow when this was captured
QUAD9_SLOW = (
    ";; Got answer:\n"
    ";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 46031\n"
    ";; flags: qr rd ra; QUERY: 1, ANSWER: 2, AUTHORITY: 0, ADDITIONAL: 1\n"
    "\n"
    ";; OPT PSEUDOSECTION:\n"
    "; EDNS: version: 0, flags:; udp: 1232\n"
    ";; ANSWER SECTION:\n"
    "www.github.com.\t\t1944\tIN\tCNAME\tgithub.com.\n"
    "github.com.\t\t46\tIN\tA\t20.172.24.160\n"
    "\n"
    ";; Query time: 3412 msec\n"
    ";; SERVER: 9.9.9.9#53(9.9.9.9) (UDP)\n"
    ";; WHEN: Fri Nov 13 21:07:22 UTC 2026\n"
    ";; MSG SIZE  rcvd: 73\n"
    "\n"
)

# @192.168.1.1 unifi A: the same record twice
ROUTER_DUPLICATE = (
    ";; Got answer:\n"
    ";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 57901\n"
    ";; flags: qr aa rd ra; QUERY: 1, ANSWER: 2, AUTHORITY: 0, ADDITIONAL: 1\n"
    "\n"
    ";; OPT PSEUDOSECTION:\n"
    "; EDNS: version: 0, flags:; udp: 1232\n"
    ";; ANSWER SECTION:\n"
    "unifi.\t\t\t0\tIN\tA\t192.168.1.1\n"
    "unifi.\t\t\t0\tIN\tA\t192.168.1.1\n"
    "\n"
    ";; Query time: 0 msec\n"
    ";; SERVER: 192.168.1.1#53(192.168.1.1) (UDP)\n"
    ";; WHEN: Fri Nov 13 21:08:00 UTC 2026\n"
    ";; MSG SIZE  rcvd: 66\n"
    "\n"
)

# @9.9.9.9 example.com AAAA
QUAD9_AAAA = (
    ";; Got answer:\n"
    ";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 11050\n"
    ";; flags: qr rd ra ad; QUERY: 1, ANSWER: 2, AUTHORITY: 0, ADDITIONAL: 1\n"
    "\n"
    ";; OPT PSEUDOSECTION:\n"
    "; EDNS: version: 0, flags:; udp: 1232\n"
    ";; ANSWER SECTION:\n"
    "example.com.\t\t164\tIN\tAAAA\t2606:4700:10::ac42:93f3\n"
    "example.com.\t\t164\tIN\tAAAA\t2606:4700:10::6814:179a\n"
    "\n"
    ";; Query time: 12 msec\n"
    ";; SERVER: 9.9.9.9#53(9.9.9.9) (UDP)\n"
    ";; WHEN: Fri Nov 13 21:07:23 UTC 2026\n"
    ";; MSG SIZE  rcvd: 96\n"
    "\n"
)

# @192.168.1.1 example.com A
ROUTER_PUBLIC = (
    ";; Got answer:\n"
    ";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 28901\n"
    ";; flags: qr rd ra; QUERY: 1, ANSWER: 2, AUTHORITY: 0, ADDITIONAL: 1\n"
    "\n"
    ";; OPT PSEUDOSECTION:\n"
    "; EDNS: version: 0, flags:; udp: 1232\n"
    ";; ANSWER SECTION:\n"
    "example.com.\t\t3\tIN\tA\t172.66.147.243\n"
    "example.com.\t\t3\tIN\tA\t104.20.23.154\n"
    "\n"
    ";; Query time: 72 msec\n"
    ";; SERVER: 192.168.1.1#53(192.168.1.1) (UDP)\n"
    ";; WHEN: Fri Nov 13 21:07:15 UTC 2026\n"
    ";; MSG SIZE  rcvd: 72\n"
    "\n"
)

# @9.9.9.9 example.com A: the same records in another order and TTL
QUAD9_PUBLIC = (
    ";; Got answer:\n"
    ";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 22090\n"
    ";; flags: qr rd ra ad; QUERY: 1, ANSWER: 2, AUTHORITY: 0, ADDITIONAL: 1\n"
    "\n"
    ";; OPT PSEUDOSECTION:\n"
    "; EDNS: version: 0, flags:; udp: 512\n"
    ";; ANSWER SECTION:\n"
    "example.com.\t\t3\tIN\tA\t104.20.23.154\n"
    "example.com.\t\t3\tIN\tA\t172.66.147.243\n"
    "\n"
    ";; Query time: 6 msec\n"
    ";; SERVER: 9.9.9.9#53(9.9.9.9) (UDP)\n"
    ";; WHEN: Fri Nov 13 21:07:15 UTC 2026\n"
    ";; MSG SIZE  rcvd: 72\n"
    "\n"
)


# @1.1.1.1 github.com AAAA (+time=4): NOERROR with no answers (NODATA)
CLOUDFLARE_NODATA = (
    ";; Got answer:\n"
    ";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 2377\n"
    ";; flags: qr rd ra; QUERY: 1, ANSWER: 0, AUTHORITY: 1, ADDITIONAL: 1\n"
    "\n"
    ";; OPT PSEUDOSECTION:\n"
    "; EDNS: version: 0, flags:; udp: 1232\n"
    ";; Query time: 7 msec\n"
    ";; SERVER: 1.1.1.1#53(1.1.1.1) (UDP)\n"
    ";; WHEN: Fri Nov 13 22:25:19 UTC 2026\n"
    ";; MSG SIZE  rcvd: 104\n"
    "\n"
)
