/** Fixtures for /api/threats/* (daemon/api/threats.py, threat_drilldowns.py), reached through the web passthrough routes. */
// OLD CODE: import type { ThreatIntelInfo, ThreatReport } from '../../../src/lib/api/threats.ts'; (the drill-downs' replies)
import type { BeaconPair, FailedLookups, ThreatIntelInfo, ThreatReport } from '../../../src/lib/api/threats.ts';
import type { DomainSummary } from '../../../src/lib/api/drilldown.ts';
import { HOUR, iso, MIN, type FixtureRoute } from './types.ts';
import { DOMAIN_EMPTY } from './drilldown.ts';

const FROM = iso(24 * HOUR);
const TO = iso(0);

// OLD CODE: const INTEL_EMPTY = { from: FROM, to: TO, new_indicators: 0, feeds: {}, total_indicators: 0 } satisfies ThreatIntelInfo; (NET-238: complete)
const INTEL_EMPTY = { from: FROM, to: TO, new_indicators: 0, feeds: {}, total_indicators: 0, complete: true } satisfies ThreatIntelInfo;
const INTEL = {
	...INTEL_EMPTY,
	new_indicators: 6,
	feeds: {
		abuse_ch_feodo: { label: 'Abuse.ch Feodo (Banking Trojans/C2)', indicator_count: 118 },
		// OLD CODE: et_compromised: { label: 'ET Compromised IPs', … } (NET-228: the daemon's new label)
		et_compromised: { label: 'Suricata blocklist rules', indicator_count: 342 },
		dshield_block: { label: 'DShield Block List', indicator_count: 20 },
	},
	total_indicators: 480,
} satisfies ThreatIntelInfo;

const REPORT_EMPTY = {
	from: FROM,
	to: TO,
	generated_at: TO,
	summary: {
		threat_score: 0,
		threat_level: 'none',
		total_groups: 0,
		total_events: 0,
		categories: {},
		top_threats: [],
		kill_chains: [],
		baseline: null,
	},
	kill_chains: [],
	beaconing: [],
	dns_anomalies: { dga_suspects: [], tunnel_suspects: [], nxdomain_spikes: [], suspicious_tlds: [] },
	lateral_movement: [],
	investigations: [],
} satisfies ThreatReport;

const KILL_CHAIN = {
	source_ip: '192.168.1.42',
	stages: [1, 3],
	stage_labels: ['Reconnaissance', 'Malware & C2'],
	alert_count: 2,
	assessment: '192.168.1.42 shows activity across 2 attack stages (Reconnaissance → Malware & C2): possible active intrusion.',
};

const TOP_THREAT = {
	signature_id: 2900001,
	signature: 'ET MALWARE Example Agent.Gen CnC Checkin',
	severity: 1,
	severity_label: 'CRITICAL',
	category: 'malware_c2',
	category_label: 'Malware & C2',
	source_ip: '192.168.1.42',
	destination_ip: '203.0.113.45',
	destination_port: 8080,
	count: 142,
	first_seen: iso(22 * HOUR),
	last_seen: iso(6 * MIN),
	trend: 'increasing',
	assessment: 'This alert indicates potential malicious activity. Only this device triggers this alert, so it may be targeted.',
};

const REPORT = {
	...REPORT_EMPTY,
	summary: {
		threat_score: 29,
		threat_level: 'medium',
		total_groups: 6,
		total_events: 291,
		categories: {
			malware_c2: { label: 'Malware & C2', groups: 2, events: 179 },
			reconnaissance: { label: 'Reconnaissance', groups: 1, events: 64 },
			policy: { label: 'Policy Violation', groups: 1, events: 27 },
		},
		top_threats: [TOP_THREAT],
		kill_chains: [KILL_CHAIN],
		baseline: { deviation: 1.8, avg_events: 160, avg_threat_score: 17, history_points: 14, is_anomalous: false },
	},
	kill_chains: [KILL_CHAIN],
	beaconing: [
		{ source_ip: '192.168.1.42', destination_ip: '203.0.113.45', destination_port: 8080, connection_count: 142, interval_seconds: 300, jitter_coefficient: 0.04, confidence: 0.93, assessment: 'Regular 5-minute callbacks with very little variation, typical of automated beaconing.', pattern: 'beacon' },
	],
	dns_anomalies: {
		// OLD CODE: dga_suspects: [{ domain: 'xk3q9vtlw2ahd.example.net', entropy: 3.9, … }], (13 characters can't score 3.9; the drill-down shows the measurement)
		dga_suspects: [{ domain: 'kq3z8wxv1m7tbn5r6yhp.example.net', entropy: 4.322, query_count: 48, assessment: 'High-entropy domain name, possibly machine generated.' }],
		tunnel_suspects: [{ domain: 'data.tunnel.example.org', subdomain_length: 52, query_count: 210, assessment: 'Very long subdomains, possibly data hidden in DNS.' }],
		nxdomain_spikes: [{ source_ip: '192.168.1.80', total_queries: 640, nxdomain_count: 410, nxdomain_ratio: 0.64, assessment: 'Most lookups from this device failed.' }],
		suspicious_tlds: [{ domain: 'promo.example.com', tld: 'example', query_count: 14 }],
	},
	lateral_movement: [
		{ source_ip: '192.168.1.57', destination_ip: '192.168.1.23', port: 22, service: 'SSH', connection_count: 38, first_seen: iso(5 * HOUR), last_seen: iso(41 * MIN), assessment: 'One device opened many SSH sessions to another local device.', fan_out: 1 },
	],
	investigations: [
		{
			alert: { signature: TOP_THREAT.signature, severity_label: 'CRITICAL', category_label: 'Malware & C2', source_ip: '192.168.1.42', destination_ip: '203.0.113.45', count: 142 },
			generated_at: TO,
			sections: {
				source_profile: { ip: '192.168.1.42', connection_count_24h: 5210, unique_destinations: 64, total_bytes_24h: 812_000_000, protocols: ['tcp', 'udp'], top_ports: [443, 8080, 53] },
				destination_profile: { ip: '203.0.113.45', connection_count_24h: 142, unique_destinations: 1, total_bytes_24h: 2_400_000 },
				connection_history: { total_connections_7d: 910, total_bytes_7d: 18_000_000, first_seen: iso(22 * HOUR), last_seen: iso(6 * MIN) },
			},
			recommendation: 'Isolate 192.168.1.42 from the network and run a full malware scan.',
		},
	],
} satisfies ThreatReport;

/** Full-length IPv6 addresses (RFC 3849's documentation prefix): the longest an investigation's facts show. */
export const INVESTIGATION_IPV6 = { source: '2001:0db8:85a3:0000:0000:8a2e:0370:7334', destination: '2001:0db8:0000:0042:0000:8a2e:0370:7335' };
const INVESTIGATION = REPORT.investigations[0];

/** The report with its investigation between two full-length IPv6 addresses (threats-layout.visual.ts). */
export const REPORT_WITH_IPV6_INVESTIGATION = {
	...REPORT,
	investigations: [
		{
			...INVESTIGATION,
			alert: { ...INVESTIGATION.alert, source_ip: INVESTIGATION_IPV6.source, destination_ip: INVESTIGATION_IPV6.destination },
			sections: {
				...INVESTIGATION.sections,
				source_profile: { ...INVESTIGATION.sections.source_profile, ip: INVESTIGATION_IPV6.source },
				destination_profile: { ...INVESTIGATION.sections.destination_profile, ip: INVESTIGATION_IPV6.destination },
			},
		},
	],
} satisfies ThreatReport;

// --- Drill-downs (threat_drilldowns.py): the report's beacon and NXDOMAIN rows, and its DGA name in finding mode ---

/** 142 calls every 5 minutes over the last 12 hours, one point an hour. */
const PAIR_TIMELINE = Array.from({ length: 24 }, (_, i) => ({ t: iso((24 - i) * HOUR), n: i < 12 ? 0 : i === 23 ? 10 : 12 }));

export const BEACON_PAIR = {
	device: '192.168.1.42',
	server: '203.0.113.45',
	port: 8080,
	device_excluded: false,
	from: FROM,
	to: TO,
	interval: '1h',
	connections: 142,
	first_seen: iso(12 * HOUR),
	last_seen: iso(6 * MIN),
	timeline: PAIR_TIMELINE,
	transports: [{ name: 'tcp', connections: 142 }],
	services: [{ name: 'http', connections: 142 }],
	timing: {
		status: 'periodic',
		slots: 142,
		mean_gap_seconds: 300.4,
		jitter: 0.04,
		confidence: 100,
		min_calls: 10,
		max_jitter: 0.15,
		gaps: [
			{ seconds: 300, count: 131 },
			{ seconds: 290, count: 6 },
			{ seconds: 310, count: 4 },
		],
	},
	tls_names: [],
	tls_complete: true,
	dns_names: [{ name: 'updates.example.com', lookups: 3 }],
	dns_complete: true,
	threat_intel: { matched: true, feeds: [{ feed: 'et_compromised', label: 'Suricata blocklist rules', indicator: '203.0.113.45', type: 'ip' }], indicators: 342, in_window: true },
} satisfies BeaconPair;

export const BEACON_PAIR_EMPTY = {
	...BEACON_PAIR,
	connections: 0,
	first_seen: null,
	last_seen: null,
	timeline: [],
	transports: [],
	services: [],
	timing: { status: 'too_few', slots: 0, mean_gap_seconds: null, jitter: null, confidence: null, min_calls: 10, max_jitter: 0.15, gaps: [] },
	dns_names: [],
	threat_intel: { matched: false, feeds: [], indicators: 0, in_window: false },
} satisfies BeaconPair;

/** 640 lookups an hour apart in equal parts, 410 of them failed. */
const LOOKUP_TIMELINE = Array.from({ length: 24 }, (_, i) => ({ t: iso((24 - i) * HOUR), n: i < 22 ? 27 : 23, failed: i < 22 ? 17 : 18 }));

export const FAILED_LOOKUPS = {
	ip: '192.168.1.80',
	excluded: false,
	from: FROM,
	to: TO,
	interval: '1h',
	lookups: 640,
	failed: 410,
	timeline: LOOKUP_TIMELINE,
	rcodes: [
		{ rcode: 'NXDOMAIN', lookups: 410 },
		{ rcode: 'NOERROR', lookups: 230 },
	],
	failed_names: [
		{ name: 'lb._dns-sd._udp.0.1.168.192.in-addr.arpa', lookups: 300, last_seen: iso(4 * MIN), kind: 'service_discovery' },
		{ name: 'wpad.lan', lookups: 60, last_seen: iso(20 * MIN), kind: 'wpad' },
		{ name: 'printer', lookups: 30, last_seen: iso(2 * HOUR), kind: 'bare' },
		{ name: 'kq3z8wxv1m7tbn5r6yhp.com', lookups: 20, last_seen: iso(3 * HOUR), kind: 'generated' },
	],
	failed_names_read: 4,
	failed_names_complete: true,
	kinds: [
		{ kind: 'service_discovery', names: 1, lookups: 300 },
		{ kind: 'wpad', names: 1, lookups: 60 },
		{ kind: 'bare', names: 1, lookups: 30 },
		{ kind: 'generated', names: 1, lookups: 20 },
	],
	generated_names: 1,
	meets_rule: true,
	rule: { min_lookups: 50, min_share: 0.4 },
} satisfies FailedLookups;

export const FAILED_LOOKUPS_EMPTY = {
	...FAILED_LOOKUPS,
	lookups: 0,
	failed: 0,
	timeline: [],
	rcodes: [],
	failed_names: [],
	failed_names_read: 0,
	kinds: [],
	generated_names: 0,
	meets_rule: false,
} satisfies FailedLookups;

const DGA_NAME = REPORT.dns_anomalies.dga_suspects[0].domain;

/** The report's DGA name in finding mode: 48 lookups, all failed, one of them from a device excluded in Settings. */
export const DOMAIN_FINDING = {
	...DOMAIN_EMPTY,
	name: DGA_NAME,
	from: FROM,
	to: TO,
	dns: {
		...DOMAIN_EMPTY.dns,
		lookups: 48,
		askers: [
			{ ip: '192.168.1.42', lan: true, lookups: 40, last_seen: iso(8 * MIN), excluded: false },
			{ ip: '192.168.1.99', lan: true, lookups: 8, last_seen: iso(3 * HOUR), excluded: true },
		],
		addresses: 0,
		rcodes: [{ rcode: 'NXDOMAIN', lookups: 48 }],
		timeline: Array.from({ length: 24 }, (_, i) => ({ t: iso((24 - i) * HOUR), n: 2 })),
	},
	finding: {
		name: DGA_NAME,
		dga: { label: 'kq3z8wxv1m7tbn5r6yhp', length: 20, entropy: 4.322, threshold: 3.8, min_length: 9 },
		tunnel: null,
	},
} satisfies DomainSummary;

export const THREAT_ROUTES: FixtureRoute[] = [
	{ path: '/api/threats/intel', empty: INTEL_EMPTY, populated: INTEL },
	{ path: '/api/threats/report', empty: REPORT_EMPTY, populated: REPORT },
	{ path: '/api/threats/beaconing/pair', empty: BEACON_PAIR_EMPTY, populated: BEACON_PAIR },
	{ path: /^\/api\/threats\/failed-lookups\/[^/]+$/, empty: FAILED_LOOKUPS_EMPTY, populated: FAILED_LOOKUPS },
	// an exact path, so it wins over the drill-down's domain pattern
	// (finding mode always carries the evidence, so the empty reply does too)
	{ path: `/api/domains/${DGA_NAME}`, empty: { ...DOMAIN_EMPTY, name: DGA_NAME, finding: DOMAIN_FINDING.finding } satisfies DomainSummary, populated: DOMAIN_FINDING },
];
