/**
 * The traffic categories' reports: Encryption, DNS security and Patch currency. Each reads the
 * score's own inputs for the score and formula, and /api/posture/{slug} for who and what is behind it.
 * Hints say what a protocol or port usually is ("often", "usually"), never what a device is; a
 * finding's severity comes from its protocol and is never lowered by a port or destination.
 */
import type { SeverityLevel } from '$lib/utils/severity';
import type { DnsDetail, EncryptionDetail, NamedCount, PatchDetail, PortCount } from '$api/posture';
import { connLogsHref, fmt, serviceLabel, serviceLogsHref } from '$lib/utils/drilldown';
import { legacyCounts } from './score';
import {
	device,
	deviceWords,
	failedSource,
	listSource,
	listWords,
	pct,
	scoreKpi,
	SEVERITY_RANK,
	truncationNote,
	unloaded,
	type Finding,
	type Note,
	type Report,
	type ReportData,
	type ResolverRow,
	type Source,
	type Step,
} from './report';

// --- Plain-English hints ---

export interface Hint {
	label: string;
	severity: SeverityLevel;
	what: string;
	fix: string;
}

const HTTP: Hint = {
	label: 'Unencrypted web traffic (HTTP)',
	severity: 'medium',
	what: 'Plain HTTP: web pages, device admin pages and update checks sent without encryption.',
	fix: "Use the HTTPS address where there is one; for a device's own admin page or updates, check for a firmware update that adds HTTPS.",
};
const FTP: Hint = {
	label: 'FTP file transfer',
	severity: 'high',
	what: 'FTP sends files and the login password in plain text.',
	fix: 'Turn FTP off on the device or server and use SFTP or FTPS instead.',
};
const TELNET: Hint = {
	label: 'Telnet remote login',
	severity: 'high',
	what: 'Telnet sends logins and everything typed in plain text; old routers, cameras and other smart devices often leave it on.',
	fix: "Turn Telnet off in the device's settings (use SSH if you need remote access), or update its firmware; replace the device if neither is possible.",
};
const MAIL: Hint = {
	label: 'Unencrypted email (POP3, IMAP or SMTP)',
	severity: 'medium',
	what: 'Email collected or sent without encryption, which usually exposes the mail password.',
	fix: 'In the mail app, switch the account to SSL/TLS (ports 993, 995, 465 or 587).',
};
const MQTT: Hint = {
	label: 'MQTT without encryption',
	severity: 'medium',
	what: 'MQTT is a messaging protocol smart-home hubs and sensors often use; on port 1883 it runs without encryption.',
	fix: 'Turn on TLS for MQTT (port 8883) in the hub or broker, if it offers it.',
};

export const SERVICE_HINTS: Record<string, Hint> = {
	http: HTTP,
	ftp: FTP,
	telnet: TELNET,
	pop3: MAIL,
	imap: MAIL,
	smtp: MAIL,
	mqtt: MQTT,
	syslog: {
		label: 'Syslog messages',
		severity: 'low',
		what: 'Log messages a router or device sends to a log server, usually one way and unencrypted.',
		fix: 'Usually fine inside your network; if they go to the internet, send them over TLS or a VPN.',
	},
	mysql: {
		label: 'MySQL database traffic',
		severity: 'medium',
		what: 'A database connection without TLS can expose its data and password.',
		fix: 'Turn on TLS for the database, and keep it off the internet.',
	},
};

export const BITTORRENT: Hint = {
	label: 'Ports BitTorrent apps use',
	severity: 'low',
	what: 'Ports 6881–6889 and 51413 are the ones BitTorrent apps usually use; many peer connections are one-way attempts that never get an answer.',
	fix: "NetTap's rule can't see a torrent app's own encryption. If you don't expect a torrent app on this device, remove it; if you do, you can ignore this.",
};

const PORT_HINTS: Record<number, Hint> = {
	23: TELNET,
	21: FTP,
	1883: MQTT,
	51413: BITTORRENT,
	554: {
		label: 'Camera video streams (RTSP)',
		severity: 'medium',
		what: 'Port 554 is usually RTSP, which cameras and video recorders use to stream video, often without encryption.',
		fix: "Keep the camera's stream inside your network (don't forward port 554 on the router), and turn on encrypted streaming if the camera has it.",
	},
	5060: {
		label: 'Internet phone calls (SIP)',
		severity: 'medium',
		what: 'Port 5060 is usually SIP, which internet phones use to set up calls, often unencrypted.',
		fix: 'Turn on TLS for SIP (port 5061) in the phone or provider settings, if offered.',
	},
	445: {
		label: 'Windows file sharing (SMB)',
		severity: 'medium',
		what: 'Port 445 is Windows file sharing (SMB). Inside your network that is normal; it should never go to the internet.',
		fix: 'Make sure the router blocks port 445 to and from the internet, and turn on SMB encryption on the file server if you can.',
	},
};
for (let p = 6881; p <= 6889; p++) PORT_HINTS[p] = BITTORRENT;

export const UNKNOWN_HINT: Hint = {
	label: "Traffic NetTap couldn't identify",
	severity: 'low',
	what: "NetTap couldn't tell which protocol these connections used.",
	fix: "Look at the ports and the device: it is often an app or a device's own cloud service. Remove anything you don't recognise.",
};

/** A hint for a service label; one the table doesn't know reads as that label, low. */
export function serviceHint(name: string): Hint {
	if (!name || name === 'unknown') return UNKNOWN_HINT;
	return (
		SERVICE_HINTS[name.toLowerCase()] ?? {
			label: `Unencrypted ${serviceLabel(name)} traffic`,
			severity: 'low',
			what: `NetTap identified these connections as ${serviceLabel(name)}, sent without encryption.`,
			fix: 'Check whether the device or app offers an encrypted option, and turn it on.',
		}
	);
}

const known = (s: NamedCount | undefined): s is NamedCount => !!s && !!s.name && s.name !== 'unknown';

/**
 * A device's hint: its top service when that is labelled; else its top port's hint (a small labelled
 * service beside a large unidentified share doesn't describe the device), at the higher severity of the
 * port and that service, since a port never lowers it; else the service; else unidentified.
 */
export function deviceHint(services: readonly NamedCount[], ports: readonly PortCount[]): Hint {
	if (known(services[0])) return serviceHint(services[0].name);
	const port = ports[0] && PORT_HINTS[ports[0].port];
	const labelled = services.find(known);
	const service = labelled && serviceHint(labelled.name);
	if (port && service) return SEVERITY_RANK[service.severity] < SEVERITY_RANK[port.severity] ? { ...port, severity: service.severity } : port;
	return port || service || UNKNOWN_HINT;
}

const portWords = (ports: readonly PortCount[]) => (ports.length ? `Top ports: ${listWords(ports.map((p) => String(p.port)))}.` : '');

// --- Encryption ---

/** A listed device at or over this share of the unencrypted connections is where to start. */
export const START_WITH_SHARE = 50;

export function encryptionReport(data: ReportData): Report {
	const { inputs, category, names } = data;
	const enc = inputs.protocols.encryption ?? { eligible: 0, encrypted: 0 };
	const detail = data.extras.encryption;
	const failed = data.failed.includes('encryption');
	const u = detail?.unencrypted;
	const other = u ? u.total - u.payload_both : 0;

	const sources: Source[] = failed || !detail
		? [failedSource('devices', 'Devices sending unencrypted traffic')]
		: [listSource('devices', 'Devices sending unencrypted traffic', { seen: detail.eligible > 0, total: u!.total, list: detail.devices, nothing: 'No connections that can be encrypted in the last 24 hours' }, inputs)];

	const findings: Finding[] = [];
	const steps: Step[] = [];
	const notes: Note[] = [];
	if (detail && u) {
		for (const d of detail.devices.rows) {
			const hint = deviceHint(d.services, d.ports);
			findings.push({
				key: `device-${d.ip}`,
				severity: hint.severity,
				title: hint.label,
				detail: `${fmt(d.connections)} unencrypted connections (${pct(d.connections, u.total)}% of all), ${fmt(d.payload_both)} with data both ways; ${fmt(d.private_local)} went to private or local-scope addresses. ${hint.what} ${portWords(d.ports)}`.trim(),
				devices: [device(d.ip, names)],
				count: d.connections,
				fix: hint.fix,
			});
			if (pct(d.connections, u.total) >= START_WITH_SHARE) {
				steps.push({ priority: 'high', text: `Start with ${deviceWords(d.ip, names)}: ${pct(d.connections, u.total)}% of the unencrypted connections. ${hint.fix}` });
			}
		}
		for (const s of u.services) {
			const hint = serviceHint(s.name);
			findings.push({
				key: `service-${s.name}`,
				severity: hint.severity,
				title: `${serviceLabel(s.name)} connections`,
				detail: `${fmt(s.count)} unencrypted connections. ${hint.what}`,
				devices: detail.devices.rows.filter((d) => d.services.some((x) => x.name === s.name)).map((d) => device(d.ip, names)),
				count: s.count,
				fix: hint.fix,
			});
		}
		const risky = u.risky;
		const logs = (query: string) => connLogsHref(detail, '24h', query);
		if (risky.telnet.count > 0) steps.push({ priority: 'high', text: `${fmt(risky.telnet.count)} Telnet connections send logins in plain text. Open them to see which devices, then turn Telnet off on each (use SSH instead).`, href: logs(risky.telnet.logs_query) });
		if (risky.ftp.count > 0) steps.push({ priority: 'high', text: `${fmt(risky.ftp.count)} FTP connections send passwords in plain text. Open them to see which devices, then switch them to SFTP or FTPS.`, href: logs(risky.ftp.logs_query) });
		if (risky.http.count > 0) steps.push({ priority: 'medium', text: `${fmt(risky.http.count)} unencrypted web (HTTP) connections. Open them to see which devices and sites, and use HTTPS where it is offered.`, href: logs(risky.http.logs_query) });
		if (u.total > 0 && pct(other, u.total) >= START_WITH_SHARE) {
			steps.push({ priority: 'low', text: `${pct(other, u.total)}% of the unencrypted connections carried data one way or none, often attempts that never got an answer. They lower the score; see What drives this score.` });
		}
		const note = truncationNote(detail.devices);
		if (note) notes.push(note);
	}

	return {
		kpis: [
			scoreKpi(category),
			unloaded({ key: 'encrypted', label: 'Encrypted', icon: 'check', value: fmt(enc.encrypted), sub: `of ${fmt(enc.eligible)} connections that can be encrypted` }, inputs.failed.includes('protocols')),
			{ key: 'both', label: 'Payload both ways', icon: 'connections', value: u ? fmt(u.payload_both) : '—', sub: u ? `of ${fmt(u.total)} unencrypted connections` : "Couldn't load" },
		],
		drivers: {
			formula: `${fmt(enc.encrypted)} encrypted ÷ ${fmt(enc.eligible)} connections that can be encrypted = ${pct(enc.encrypted, enc.eligible)}%`,
			counts: [
				'Counted as encrypted: HTTPS and other TLS, QUIC, SSH, VPNs (WireGuard, OpenVPN, IPsec), and ports 443, 853, 8443 and 8883.',
				'Left out: DNS, DHCP, NTP, local discovery (mDNS, LLMNR, SSDP, NetBIOS), pings, multicast, broadcast and STUN, which are never encrypted.',
				...(u ? [`${fmt(u.private_local)} of the unencrypted connections went to private or local-scope addresses.`] : []),
			],
			limits: [
				'A one-way attempt (a connection that never got a reply) counts as unencrypted, so an app trying unreachable peers lowers the score.',
				"“Other” is a connection whose data went one way only, none, or wasn't measured; a log message sent one way lands here.",
			],
			bars: u
				? [
						{ key: 'encrypted', label: 'Encrypted', value: enc.encrypted, display: fmt(enc.encrypted), colour: 1 },
						{ key: 'both', label: 'Unencrypted, data both ways', value: u.payload_both, display: fmt(u.payload_both), colour: 3 },
						{ key: 'other', label: 'Unencrypted, other', value: other, display: fmt(other), colour: 4 },
					]
				: [],
		},
		sources,
		findings,
		steps,
		notes,
	};
}

// --- DNS security ---

/** At or over this many plain lookups to public addresses, pointing devices at your resolver is high priority. */
export const PUBLIC_LOOKUPS_HIGH = 1000;

const SCOPE_WORDS = { private_local: 'Private or local-scope', unknown: 'Unknown', public: 'Public' } as const;
const orgWords = (ip: string, org: string | null) => (org ? `${ip} (${org})` : ip);

export function dnsReport(data: ReportData): Report {
	const { inputs, category, names } = data;
	const dns = inputs.protocols.dns ?? { plain: 0, over_tls: 0 };
	const detail: DnsDetail | undefined = data.extras['dns-security'];
	const failed = data.failed.includes('dns-security');
	const scope = detail?.plain_scope;

	const sources: Source[] = failed || !detail
		? [failedSource('public', 'Devices using public resolvers')]
		: [listSource('public', 'Devices using public resolvers', { seen: detail.plain + detail.over_tls > 0, total: scope!.public, list: detail.public_devices, nothing: 'No DNS lookups in the last 24 hours' }, inputs)];

	const findings: Finding[] = [];
	const steps: Step[] = [];
	const notes: Note[] = [];
	if (detail && scope) {
		// A private-address resolver forwarding plain lookups upstream is judged as a resolver below, not as a device
		const forwarders = new Map(detail.resolvers.plain.filter((r) => r.scope === 'private_local' && r.upstream).map((r) => [r.ip, r.upstream!.plain_public]));
		const fromDevices = Math.max(0, scope.public - [...forwarders.values()].reduce((sum, n) => sum + n, 0));
		for (const d of detail.public_devices.rows.filter((row) => !forwarders.has(row.ip))) {
			findings.push({
				key: `public-${d.ip}`,
				severity: 'medium',
				title: 'Plain lookups straight to public resolvers',
				detail: `${fmt(d.count)} plain lookups to ${listWords(d.resolvers.map((r) => orgWords(r.ip, r.org)))}.`,
				devices: [device(d.ip, names)],
				count: d.count,
				fix: "Point it at your router or local resolver, or turn on Private DNS (Android) or encrypted DNS on it. If it can't be changed: block outbound port 53 on the router except from your resolver (advanced).",
			});
		}
		for (const r of detail.resolvers.plain) {
			if (r.scope !== 'private_local' || !r.upstream) continue;
			const { plain_public, dot } = r.upstream;
			const base = { devices: [device(r.ip, names)], count: r.count };
			if (plain_public > 0) {
				findings.push({ ...base, key: `resolver-${r.ip}`, severity: 'medium', title: 'Private-address resolver also sends plain lookups out', detail: `It answered ${fmt(r.count)} lookups, and sent ${fmt(plain_public)} plain lookups to public addresses${dot > 0 ? ` beside ${fmt(dot)} DNS-over-TLS connections` : ''}.`, fix: 'Set its upstream to encrypted only (DNS-over-TLS or DNS-over-HTTPS).' });
				steps.push({ priority: 'medium', text: `Set ${deviceWords(r.ip, names)}'s upstream to encrypted only: it sent ${fmt(plain_public)} plain lookups to public addresses.` });
			} else if (dot > 0) {
				findings.push({ ...base, key: `resolver-${r.ip}`, severity: 'info', title: 'Private-address resolver uses DNS-over-TLS', detail: `It answered ${fmt(r.count)} lookups and was seen using DNS-over-TLS (${fmt(dot)} connections).`, fix: 'Nothing to change.' });
			} else {
				findings.push({ ...base, key: `resolver-${r.ip}`, severity: 'info', title: 'Private-address resolver: upstream unknown', detail: `It answered ${fmt(r.count)} lookups. Unknown: NetTap saw no lookups leaving it; it may use DNS-over-HTTPS, or its upstream isn't visible from where NetTap sits.`, fix: 'Nothing NetTap can check; its own settings show its upstream.' });
			}
		}
		if (fromDevices > 0) {
			steps.push({ priority: fromDevices >= PUBLIC_LOOKUPS_HIGH ? 'high' : 'medium', text: `${fmt(fromDevices)} plain lookups went straight to public resolvers. Point those devices at your router or resolver, or turn on Private DNS on phones.`, href: '/dns' });
			// exact counts, never list membership: a resolver outside the top ten still counts in private_local
			if (detail.over_tls === 0 && scope.private_local === 0) {
				steps.push({ priority: 'high', text: 'Turn on DNS-over-TLS on the router, or run a local resolver with an encrypted upstream (Pi-hole, AdGuard Home) and hand it out by DHCP.' });
			}
		}
		const note = truncationNote(detail.public_devices, '/dns');
		if (note) notes.push(note);
	}

	const resolvers: ResolverRow[] = detail
		? [
				...detail.resolvers.plain.map((r) => ({ key: `plain-${r.ip}`, ip: r.ip, kind: 'Plain' as const, org: r.org ?? '', scope: SCOPE_WORDS[r.scope], count: r.count })),
				...detail.resolvers.over_tls.map((r) => ({ key: `dot-${r.ip}`, ip: r.ip, kind: 'DNS-over-TLS' as const, org: r.org ?? '', scope: SCOPE_WORDS[r.scope], count: r.count })),
			]
		: [];

	return {
		kpis: [
			scoreKpi(category),
			unloaded({ key: 'dot', label: 'DNS-over-TLS', icon: 'dns', value: fmt(dns.over_tls), sub: `connections, beside ${fmt(dns.plain)} plain lookups` }, inputs.failed.includes('protocols')),
			{ key: 'public', label: 'Plain lookups to public addresses', icon: 'warn', value: scope ? fmt(scope.public) : '—', sub: scope ? 'sent straight to resolvers on the internet' : "Couldn't load" },
		],
		drivers: {
			formula: `${fmt(dns.over_tls)} DNS-over-TLS ÷ (${fmt(dns.plain)} plain + ${fmt(dns.over_tls)} DNS-over-TLS) = ${pct(dns.over_tls, dns.plain + dns.over_tls)}%`,
			counts: ["Plain: lookups NetTap identified as DNS, leaving out local discovery (mDNS on 5353, LLMNR on 5355).", 'DNS-over-TLS: connections to port 853.'],
			limits: [
				"DNS-over-HTTPS (DoH) looks like any other HTTPS, so NetTap can't count it; a device using it is in neither figure.",
				'Lookups to your own resolver (router, Pi-hole) count as plain, even when it forwards them encrypted.',
				'Addresses in 100.64.0.0/10, or missing, are “unknown”: often an ISP’s carrier-grade NAT or a VPN.',
			],
			bars: scope
				? [
						{ key: 'dot', label: 'DNS-over-TLS', value: detail!.over_tls, display: fmt(detail!.over_tls), colour: 1 },
						{ key: 'local', label: 'Plain, to private or local-scope addresses', value: scope.private_local, display: fmt(scope.private_local), colour: 2 },
						{ key: 'public', label: 'Plain, to public addresses', value: scope.public, display: fmt(scope.public), colour: 3 },
						{ key: 'unknown', label: 'Plain, address unknown', value: scope.unknown, display: fmt(scope.unknown), colour: 4 },
					]
				: [],
			resolvers,
		},
		sources,
		findings,
		steps,
		notes,
	};
}

// --- Patch currency ---

const UPDATE_FIX = 'Check for a firmware or software update; replace the device if the maker no longer updates it.';

export function patchReport(data: ReportData): Report {
	const { inputs, category, names } = data;
	const counts = legacyCounts(inputs.protocols.services);
	const detail: PatchDetail | undefined = data.extras['patch-currency'];
	const failed = data.failed.includes('patch-currency');
	const lan = detail ? { lan: detail.protocols.reduce((s, p) => s + p.devices.lan, 0), other: 0, rows: detail.protocols.flatMap((p) => p.devices.rows) } : null;

	const sources: Source[] = failed || !detail
		? [failedSource('legacy', 'Devices using old protocols')]
		: [listSource('legacy', 'Devices using old protocols', { seen: counts.total > 0 || detail.unique_connections > 0, total: detail.unique_connections, list: lan!, nothing: 'No labelled connections in the last 24 hours' }, inputs)];

	const findings: Finding[] = [];
	const notes: Note[] = [];
	for (const p of detail?.protocols ?? []) {
		const hint = serviceHint(p.name);
		for (const d of p.devices.rows) {
			findings.push({
				key: `${p.name}-${d.ip}`,
				severity: hint.severity,
				title: hint.label,
				detail: `${fmt(d.connections)} ${serviceLabel(p.name)} connections to ${listWords(d.destinations.map((x) => x.ip))}. ${portWords(d.ports)} ${hint.what}`.trim(),
				devices: [device(d.ip, names)],
				count: d.connections,
				fix: `${hint.fix} ${UPDATE_FIX}`,
			});
		}
		const note = truncationNote(p.devices, serviceLogsHref(p.name, detail!, detail!.excluded_ips, '24h'));
		if (note) notes.push({ ...note, text: `${serviceLabel(p.name)}: ${note.text}` });
	}

	const telnetFtp = counts.byName.telnet + counts.byName.ftp;
	const plainOther = counts.byName.http + counts.byName.pop3 + counts.byName.imap;
	const steps: Step[] = [
		...(telnetFtp > 0 ? [{ priority: 'high' as const, text: `Turn off Telnet and FTP (${fmt(telnetFtp)} connections): they send passwords in plain text. ${UPDATE_FIX}` }] : []),
		...(plainOther > 0 ? [{ priority: 'medium' as const, text: `Move devices off plain HTTP, POP3 and IMAP (${fmt(plainOther)} connections) where they offer an encrypted option, usually after an update.` }] : []),
		{ priority: 'low', text: 'Turn on automatic updates everywhere they are offered, and replace devices that no longer get updates.' },
	];

	return {
		kpis: [
			scoreKpi(category),
			unloaded({ key: 'legacy', label: 'Old-protocol connections', icon: 'warn', value: fmt(counts.legacy), sub: `of ${fmt(counts.total)} labelled connections` }, inputs.failed.includes('protocols')),
			unloaded({ key: 'telnet-ftp', label: 'Telnet or FTP connections', icon: 'threats', value: fmt(telnetFtp), sub: 'send passwords in plain text' }, inputs.failed.includes('protocols')),
		],
		drivers: {
			formula: `100 − (${fmt(counts.legacy)} old-protocol labels ÷ ${fmt(counts.total)} labels × 100) = ${counts.total > 0 ? Math.round(100 - (counts.legacy / counts.total) * 100) : 100}`,
			counts: [
				'Old protocols: plain HTTP, FTP, Telnet, POP3 and IMAP.',
				...(detail ? [`Connections with an old-protocol label, each counted once: ${fmt(detail.unique_connections)}.`] : []),
			],
			limits: ["NetTap can't read software versions; old protocols are a sign of out-of-date software, not proof.", 'A connection with two labels counts twice in the score.'],
			bars: Object.entries(counts.byName)
				.filter(([, n]) => n > 0)
				.map(([name, n], i) => ({ key: name, label: serviceLabel(name), value: n, display: fmt(n), colour: (((i % 6) + 1) as 1 | 2 | 3 | 4 | 5 | 6) })),
		},
		sources,
		findings,
		steps,
		notes,
	};
}
