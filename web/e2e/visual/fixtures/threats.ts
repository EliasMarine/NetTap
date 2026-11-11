/** Fixtures for /api/threats/* (daemon/api/threats.py), reached through the web passthrough routes. */
import type { ThreatIntelInfo, ThreatReport } from '../../../src/lib/api/threats.ts';
import { HOUR, iso, MIN, type FixtureRoute } from './types.ts';

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
		dga_suspects: [{ domain: 'xk3q9vtlw2ahd.example.net', entropy: 3.9, query_count: 48, assessment: 'High-entropy domain name, possibly machine generated.' }],
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

export const THREAT_ROUTES: FixtureRoute[] = [
	{ path: '/api/threats/intel', empty: INTEL_EMPTY, populated: INTEL },
	{ path: '/api/threats/report', empty: REPORT_EMPTY, populated: REPORT },
];
