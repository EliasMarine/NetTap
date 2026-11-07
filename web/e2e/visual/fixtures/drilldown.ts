/**
 * Fixtures for the drill-down endpoints (NET-160): /api/network/lan, /api/addresses/{ip} and
 * /api/domains/{name} (daemon/api/network.py, addresses.py, domains.py), through the web
 * catch-all. Figures add up the way the daemon's do (drilldown.test.ts checks them).
 *
 * Two addresses and two domains, so the visual suite sees every state:
 * - 198.51.100.10 / stream.example.net: complete lists, partial byte totals, a tagged alert;
 * - 192.0.2.80 / quiet.example.org: bytes not measured, lists too long to count, a threat-list
 *   match, a TLS session with no name, and no alert carrying a host name ("Not recorded").
 */
import type { LanPolicy } from '../../../src/lib/api/network.ts';
import type { AddressSummary, DomainSummary, TimelinePoint } from '../../../src/lib/api/drilldown.ts';
import { HOUR, iso, MIN, type FixtureRoute } from './types.ts';
import { MB, PEERS, WINDOW } from './net-world.ts';

export const LAN_POLICY: LanPolicy = { version: 'fx-1', subnets: ['192.168.1.0/24'], source: 'env', ipv6: 'not-lan' };

/** `total` spread over the last 24 hours, oldest first, with a busier evening. */
export function hourly(total: number): TimelinePoint[] {
	const weights = Array.from({ length: 24 }, (_, i) => 1 + ((i * 7) % 5) + (i > 17 ? 4 : 0));
	const sumW = weights.reduce((a, b) => a + b, 0);
	const counts = weights.map((w) => Math.floor((total * w) / sumW));
	counts[counts.length - 1] += total - counts.reduce((a, b) => a + b, 0);
	return counts.map((n, i) => ({ t: iso((24 - i) * HOUR), n }));
}

const STREAM = PEERS[0]; // 198.51.100.10, stream.example.net
const QUIET = PEERS[6]; // 192.0.2.80

export const ADDRESS: AddressSummary = {
	ip: STREAM.ip,
	...WINDOW,
	lan: false,
	connections: STREAM.connections, // 1,980
	first_seen: iso(23 * HOUR),
	last_seen: iso(2 * MIN),
	bytes_to: { total: 200 * MB, measured: 1970, connections: 1980, partial: true },
	bytes_from: { total: 18200 * MB, measured: 1970, connections: 1980, partial: true },
	peers: [
		{ ip: '192.168.1.22', lan: true, connections: 1200, bytes_to: 120 * MB, bytes_from: 11000 * MB, bytes_partial: false, last_seen: iso(2 * MIN) },
		{ ip: '192.168.1.20', lan: true, connections: 500, bytes_to: 60 * MB, bytes_from: 4700 * MB, bytes_partial: true, last_seen: iso(30 * MIN) },
		{ ip: '192.168.1.21', lan: true, connections: 280, bytes_to: 20 * MB, bytes_from: 2500 * MB, bytes_partial: false, last_seen: iso(3 * HOUR) },
	],
	peers_complete: true,
	ports: [
		{ port: 443, transport: 'tcp', services: ['ssl'], connections: 1700 },
		// Zeek logs some QUIC sessions with two services; the row counts each connection once
		{ port: 443, transport: 'udp', services: ['quic', 'ssl'], connections: 250 },
		{ port: 80, transport: 'tcp', services: [], connections: 30 },
	],
	ports_complete: true,
	timeline: hourly(1980),
	tls_names: [
		{ name: STREAM.host, sessions: 1600, statuses: { ok: 1598, unchecked: 2 } },
		{ name: 'edge.example.net', sessions: 100, statuses: { ok: 100 } },
	],
	tls_complete: true,
	alerts: 0,
	threat_intel: { matched: false, feeds: [], indicators: 5400 },
};

export const ADDRESS_QUIET: AddressSummary = {
	ip: QUIET.ip,
	...WINDOW,
	lan: false,
	connections: 1190,
	first_seen: iso(22 * HOUR),
	last_seen: iso(10 * MIN),
	bytes_to: { total: 0, measured: 0, connections: 1190, partial: true },
	bytes_from: { total: 0, measured: 0, connections: 1190, partial: true },
	peers: [
		{ ip: '192.168.1.50', lan: true, connections: 900, bytes_to: null, bytes_from: null, bytes_partial: true, last_seen: iso(10 * MIN) },
		{ ip: '192.168.1.31', lan: true, connections: 200, bytes_to: null, bytes_from: null, bytes_partial: true, last_seen: iso(HOUR) },
	],
	peers_complete: false,
	ports: [
		{ port: 8883, transport: 'tcp', services: [], connections: 1100 },
		// connections with no port or transport recorded keep their own row
		{ port: null, transport: null, services: [], connections: 90 },
	],
	ports_complete: false,
	timeline: hourly(1190),
	tls_names: [
		{ name: null, sessions: 700, statuses: { unchecked: 700 } },
		{ name: 'telemetry.example.org', sessions: 400, statuses: { ok: 380, 'unable to get local issuer certificate': 20 } },
	],
	tls_complete: false,
	alerts: 2,
	// a listing-rule alert in the window named it, with no indicator cache loaded
	threat_intel: {
		matched: true,
		feeds: [{ feed: 'et_compromised', label: 'ET Compromised IPs', indicator: QUIET.ip, type: 'ip' }],
		indicators: 0,
	},
};

export const ADDRESS_EMPTY: AddressSummary = {
	ip: STREAM.ip,
	...WINDOW,
	lan: false,
	connections: 0,
	first_seen: null,
	last_seen: null,
	bytes_to: { total: 0, measured: 0, connections: 0, partial: false },
	bytes_from: { total: 0, measured: 0, connections: 0, partial: false },
	peers: [],
	peers_complete: true,
	ports: [],
	ports_complete: true,
	timeline: [],
	tls_names: [],
	tls_complete: true,
	alerts: 0,
	// no indicator cache: still checked against this window's alerts
	threat_intel: { matched: false, feeds: [], indicators: 0 },
};

export const DOMAIN: DomainSummary = {
	name: STREAM.host,
	...WINDOW,
	dns: {
		lookups: 420,
		askers: [
			{ ip: '192.168.1.22', lan: true, lookups: 260, last_seen: iso(5 * MIN) },
			{ ip: '192.168.1.20', lan: true, lookups: 110, last_seen: iso(40 * MIN) },
			{ ip: '192.168.1.21', lan: true, lookups: 50, last_seen: iso(2 * HOUR) },
		],
		askers_complete: true,
		answers: [
			{ value: 'edge.example.net', kind: 'name', lan: null, lookups: 410 },
			{ value: STREAM.ip, kind: 'ip', lan: false, lookups: 400 },
			{ value: '2001:db8::10', kind: 'ip', lan: false, lookups: 120 },
		],
		answers_complete: true,
		addresses: 2,
		rcodes: [
			{ rcode: 'NOERROR', lookups: 410 },
			{ rcode: null, lookups: 10 },
		],
		timeline: hourly(420),
	},
	tls: {
		sessions: 1600,
		servers: [{ ip: STREAM.ip, lan: false, sessions: 1600 }],
		servers_complete: true,
		clients: [
			{ ip: '192.168.1.22', lan: true, sessions: 1000 },
			{ ip: '192.168.1.20', lan: true, sessions: 400 },
			{ ip: '192.168.1.21', lan: true, sessions: 200 },
		],
		clients_complete: true,
		statuses: { ok: 1598, unchecked: 2 },
	},
	http: { requests: 12 },
	alerts: { tagged: 1, alerts_in_window: 57, with_host_field: 12 },
};

export const DOMAIN_QUIET: DomainSummary = {
	name: 'quiet.example.org',
	...WINDOW,
	dns: {
		lookups: 90,
		askers: [{ ip: '192.168.1.50', lan: true, lookups: 90, last_seen: iso(10 * MIN) }],
		askers_complete: false,
		answers: [
			{ value: QUIET.ip, kind: 'ip', lan: false, lookups: 80 },
			{ value: 'v=spf1 -all', kind: 'other', lan: null, lookups: 10 },
		],
		answers_complete: false,
		addresses: null,
		rcodes: [{ rcode: 'NOERROR', lookups: 90 }],
		timeline: hourly(90),
	},
	tls: {
		sessions: 0,
		servers: [],
		servers_complete: true,
		clients: [],
		clients_complete: true,
		statuses: {},
	},
	http: { requests: 0 },
	alerts: { tagged: null, alerts_in_window: 57, with_host_field: 0 },
};

export const DOMAIN_EMPTY: DomainSummary = {
	name: STREAM.host,
	...WINDOW,
	dns: { lookups: 0, askers: [], askers_complete: true, answers: [], answers_complete: true, addresses: 0, rcodes: [], timeline: [] },
	tls: { sessions: 0, servers: [], servers_complete: true, clients: [], clients_complete: true, statuses: {} },
	http: { requests: 0 },
	alerts: { tagged: null, alerts_in_window: 0, with_host_field: 0 },
};

export const DRILLDOWN_ROUTES: FixtureRoute[] = [
	{ path: '/api/network/lan', empty: LAN_POLICY },
	// exact paths win over the patterns, so each variant keeps its own figures
	{ path: `/api/addresses/${QUIET.ip}`, empty: ADDRESS_EMPTY, populated: ADDRESS_QUIET },
	{ path: /^\/api\/addresses\/[^/]+$/, empty: ADDRESS_EMPTY, populated: ADDRESS },
	{ path: '/api/domains/quiet.example.org', empty: DOMAIN_EMPTY, populated: DOMAIN_QUIET },
	{ path: /^\/api\/domains\/[^/]+$/, empty: DOMAIN_EMPTY, populated: DOMAIN },
];
