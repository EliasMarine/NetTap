/**
 * Zeek connection records (the OpenSearch `_source` the daemon returns, plus `_id` and `_index`),
 * generated from a few templates so the Connections page, the device page and the drawers agree.
 * No randomness: row `i` is always the same record.
 */
import type { Connection } from '../../../src/lib/api/traffic.ts';
import { iso } from './types.ts';
import { asnFull, peer } from './net-world.ts';

export interface ConnTemplate {
	src: string;
	dst: string;
	port: number;
	transport: 'tcp' | 'udp';
	service: string;
	/** bytes sent / received, and duration in ms */
	up: number;
	down: number;
	ms: number;
	/** Zeek conn_state */
	state: string;
}

const KB = 1024;
const MB = KB * KB;

export const CONN_TEMPLATES: readonly ConnTemplate[] = [
	{ src: '192.168.1.22', dst: '198.51.100.10', port: 443, transport: 'tcp', service: 'ssl', up: 90 * KB, down: 48 * MB, ms: 612_000, state: 'SF' },
	{ src: '192.168.1.20', dst: '203.0.113.15', port: 443, transport: 'tcp', service: 'ssl', up: 340 * KB, down: 5 * MB, ms: 42_000, state: 'SF' },
	{ src: '192.168.1.21', dst: '192.0.2.50', port: 443, transport: 'tcp', service: 'ssl', up: 120 * KB, down: 2 * MB, ms: 18_500, state: 'SF' },
	{ src: '192.168.1.22', dst: '198.51.100.20', port: 443, transport: 'udp', service: 'quic', up: 60 * KB, down: 21 * MB, ms: 305_000, state: 'SF' },
	{ src: '192.168.1.30', dst: '198.51.100.77', port: 443, transport: 'tcp', service: 'ssl', up: 48 * KB, down: 3 * MB, ms: 9_800, state: 'SF' },
	{ src: '192.168.1.20', dst: '198.51.100.77', port: 443, transport: 'tcp', service: 'ssl', up: 22 * KB, down: 900 * KB, ms: 2_400, state: 'SF' },
	{ src: '192.168.1.50', dst: '192.0.2.80', port: 443, transport: 'tcp', service: 'ssl', up: 14 * MB, down: 60 * KB, ms: 1_800_000, state: 'S1' },
	{ src: '192.168.1.20', dst: '203.0.113.40', port: 80, transport: 'tcp', service: 'http', up: 6 * KB, down: 17 * MB, ms: 21_000, state: 'SF' },
	{ src: '192.168.1.30', dst: '203.0.113.99', port: 993, transport: 'tcp', service: 'ssl', up: 12 * KB, down: 400 * KB, ms: 61_000, state: 'S3' },
	{ src: '192.168.1.31', dst: '192.0.2.80', port: 443, transport: 'tcp', service: 'ssl', up: 3 * KB, down: 5 * KB, ms: 700, state: 'SF' },
	{ src: '192.168.1.20', dst: '198.51.100.10', port: 443, transport: 'tcp', service: 'ssl', up: 70 * KB, down: 9 * MB, ms: 88_000, state: 'SF' },
	{ src: '192.168.1.50', dst: '203.0.113.15', port: 8883, transport: 'tcp', service: 'unknown', up: 1 * KB, down: 0, ms: 3_000, state: 'S0' },
	{ src: '192.168.1.21', dst: '203.0.113.99', port: 443, transport: 'tcp', service: 'ssl', up: 9 * KB, down: 90 * KB, ms: 1_200, state: 'REJ' },
];

/** Connection `i` (0 newest) from the templates in rotation; sizes vary a little per row. */
export function connection(templates: readonly ConnTemplate[], i: number): Connection {
	const t = templates[i % templates.length];
	const p = peer(t.dst);
	const scale = 1 + (i % 5) * 0.2;
	const up = Math.round(t.up * scale);
	const down = Math.round(t.down * scale);
	// The page reads zeek.conn.conn_state; Connection's zeek.conn type lists only state/history.
	const zeekConn = { conn_state: t.state, history: 'ShADadFf' };
	return {
		_id: `conn-${String(i + 1).padStart(4, '0')}`,
		_index: 'arkime_sessions3-fixture',
		'@timestamp': iso(30_000 + i * 70_000),
		source: { ip: t.src, port: 40_000 + ((i * 7919) % 20_000), bytes: up, packets: Math.ceil(up / 900) },
		destination: {
			ip: t.dst,
			port: t.port,
			bytes: down,
			packets: Math.ceil(down / 1200),
			as: { full: asnFull(p) },
			geo: { country_iso_code: p.countryCode, country_name: p.country },
		},
		network: { transport: t.transport, protocol: t.service, community_id: `1:fixture-${i}` },
		length: t.ms,
		zeek: { session_id: `CFixture${i}`, conn: zeekConn },
	};
}

export const connections = (templates: readonly ConnTemplate[], count: number): Connection[] =>
	Array.from({ length: count }, (_, i) => connection(templates, i));
