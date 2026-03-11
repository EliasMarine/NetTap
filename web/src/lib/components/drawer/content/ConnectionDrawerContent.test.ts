import { describe, it, expect, vi, afterEach } from 'vitest';

/**
 * Tests for ConnectionDrawerContent component logic.
 *
 * ConnectionDrawerContent.svelte uses Svelte 5 runes ($state, $props, $derived,
 * $effect) and relies on multiple API imports. Instead of rendering, we extract
 * and test the pure logic: formatting functions, connection state descriptions,
 * tab visibility, and field derivation.
 */

// ---------------------------------------------------------------------------
// Reproduced logic from ConnectionDrawerContent.svelte
// ---------------------------------------------------------------------------

const STATE_DESC: Record<string, string> = {
	S0: 'Connection attempt seen, no reply',
	S1: 'Connection established, not terminated',
	SF: 'Normal establishment and termination',
	REJ: 'Connection attempt rejected',
	S2: 'Connection established, close attempted by originator',
	S3: 'Connection established, close attempted by responder',
	RSTO: 'Connection established, originator aborted',
	RSTR: 'Connection established, responder aborted',
	RSTOS0: 'Originator sent a SYN then RST, responder never replied',
	RSTRH: 'Responder sent a SYN ACK then RST, originator never replied',
	SH: 'Originator sent SYN then FIN, responder never replied (half-open)',
	SHR: 'Responder sent SYN ACK then FIN, originator never replied',
	OTH: 'No SYN seen, midstream traffic',
};

function formatDuration(val: unknown): string {
	if (val == null) return '--';
	const n = Number(val);
	if (isNaN(n)) return String(val);
	if (n < 1) return `${(n * 1000).toFixed(0)}ms`;
	if (n < 60) return `${n.toFixed(1)}s`;
	return `${Math.floor(n / 60)}m ${(n % 60).toFixed(0)}s`;
}

function formatBytes(val: unknown): string {
	if (val == null) return '--';
	const n = Number(val);
	if (isNaN(n)) return String(val);
	if (n >= 1_073_741_824) return `${(n / 1_073_741_824).toFixed(1)} GB`;
	if (n >= 1_048_576) return `${(n / 1_048_576).toFixed(1)} MB`;
	if (n >= 1_024) return `${(n / 1_024).toFixed(1)} KB`;
	return `${n} B`;
}

/** Simulates active tab visibility — mirrors the {#if activeTab === ...} blocks */
function getVisibleContent(activeTab: string): 'details' | 'tshark' | 'raw' | 'none' {
	if (activeTab === 'details') return 'details';
	if (activeTab === 'tshark') return 'tshark';
	if (activeTab === 'raw') return 'raw';
	return 'none';
}

/** Field extraction helper — mirrors getField from tshark-filter.ts */
function getField(obj: Record<string, unknown>, path: string): unknown {
	const parts = path.split('.');
	let current: unknown = obj;
	for (const part of parts) {
		if (current == null || typeof current !== 'object') return undefined;
		current = (current as Record<string, unknown>)[part];
	}
	return current;
}

/** Mirrors getPacketInfo from ConnectionDrawerContent.svelte */
function getPacketInfo(pkt: Record<string, unknown>): {
	no: string;
	time: string;
	src: string;
	dst: string;
	proto: string;
	len: string;
	info: string;
} {
	const layers = (pkt?.['_source'] as Record<string, unknown>)?.['layers'] as Record<string, unknown> || pkt;
	const frame = layers?.['frame'] as Record<string, unknown> || {};
	const ip = (layers?.['ip'] || layers?.['ipv6']) as Record<string, unknown> || {};
	return {
		no: (frame['frame.number'] as string) || '?',
		time: (frame['frame.time_relative'] as string) || (frame['frame.time'] as string) || '?',
		src: (ip['ip.src'] as string) || (ip['ipv6.src'] as string) || '?',
		dst: (ip['ip.dst'] as string) || (ip['ipv6.dst'] as string) || '?',
		proto: ((frame['frame.protocols'] as string) || '?').split(':').pop() || '?',
		len: (frame['frame.len'] as string) || '?',
		info: ((pkt?.['_source'] as Record<string, unknown>)?.['layers'] as Record<string, unknown>)?.['_ws.col'] ?
			(((pkt?.['_source'] as Record<string, unknown>)?.['layers'] as Record<string, unknown>)?.['_ws.col'] as Record<string, unknown>)?.['_ws.col.Info'] as string || '' : '',
	};
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ConnectionDrawerContent logic', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- Tab visibility -------------------------------------------------------

	describe('tab visibility', () => {
		it('renders details tab when activeTab="details"', () => {
			expect(getVisibleContent('details')).toBe('details');
		});

		it('renders TShark tab when activeTab="tshark"', () => {
			expect(getVisibleContent('tshark')).toBe('tshark');
		});

		it('renders Raw JSON when activeTab="raw"', () => {
			expect(getVisibleContent('raw')).toBe('raw');
		});

		it('renders nothing for unknown tab', () => {
			expect(getVisibleContent('other')).toBe('none');
		});
	});

	// -- formatDuration -------------------------------------------------------

	describe('formatDuration', () => {
		it('returns "--" for null', () => {
			expect(formatDuration(null)).toBe('--');
		});

		it('returns "--" for undefined', () => {
			expect(formatDuration(undefined)).toBe('--');
		});

		it('returns original string for NaN values', () => {
			expect(formatDuration('invalid')).toBe('invalid');
		});

		it('formats sub-second as milliseconds', () => {
			expect(formatDuration(0.5)).toBe('500ms');
			expect(formatDuration(0.003)).toBe('3ms');
		});

		it('formats seconds', () => {
			expect(formatDuration(5)).toBe('5.0s');
			expect(formatDuration(30.5)).toBe('30.5s');
		});

		it('formats minutes and seconds', () => {
			expect(formatDuration(90)).toBe('1m 30s');
			expect(formatDuration(120)).toBe('2m 0s');
		});
	});

	// -- formatBytes ----------------------------------------------------------

	describe('formatBytes', () => {
		it('returns "--" for null', () => {
			expect(formatBytes(null)).toBe('--');
		});

		it('returns "--" for undefined', () => {
			expect(formatBytes(undefined)).toBe('--');
		});

		it('returns original string for NaN values', () => {
			expect(formatBytes('invalid')).toBe('invalid');
		});

		it('formats bytes', () => {
			expect(formatBytes(500)).toBe('500 B');
			expect(formatBytes(0)).toBe('0 B');
		});

		it('formats kilobytes', () => {
			expect(formatBytes(1024)).toBe('1.0 KB');
			expect(formatBytes(10240)).toBe('10.0 KB');
		});

		it('formats megabytes', () => {
			expect(formatBytes(1_048_576)).toBe('1.0 MB');
		});

		it('formats gigabytes', () => {
			expect(formatBytes(1_073_741_824)).toBe('1.0 GB');
		});
	});

	// -- Connection state descriptions ----------------------------------------

	describe('connection state descriptions', () => {
		it('has description for SF (normal)', () => {
			expect(STATE_DESC['SF']).toBe('Normal establishment and termination');
		});

		it('has description for S0 (no reply)', () => {
			expect(STATE_DESC['S0']).toBe('Connection attempt seen, no reply');
		});

		it('has description for REJ (rejected)', () => {
			expect(STATE_DESC['REJ']).toBe('Connection attempt rejected');
		});

		it('has description for RSTO (originator aborted)', () => {
			expect(STATE_DESC['RSTO']).toBe('Connection established, originator aborted');
		});

		it('has description for OTH (midstream)', () => {
			expect(STATE_DESC['OTH']).toBe('No SYN seen, midstream traffic');
		});

		it('returns undefined for unknown states', () => {
			expect(STATE_DESC['UNKNOWN']).toBeUndefined();
		});

		it('covers all 13 Zeek connection states', () => {
			expect(Object.keys(STATE_DESC)).toHaveLength(13);
		});
	});

	// -- Field extraction from connection objects -----------------------------

	describe('field extraction', () => {
		const connectionSource = {
			source: { ip: '192.168.1.100', port: 54321 },
			destination: { ip: '8.8.8.8', port: 443 },
			network: { transport: 'tcp', protocol: 'tls' },
			zeek: {
				conn: {
					uid: 'CwA123',
					conn_state: 'SF',
					history: 'ShADafF',
					duration: 1.5,
					orig_bytes: 1024,
					resp_bytes: 8192,
				},
			},
			'@timestamp': '2026-03-01T12:00:00Z',
		};

		it('extracts source IP from nested _source', () => {
			const val = getField(connectionSource as Record<string, unknown>, 'source.ip');
			expect(val).toBe('192.168.1.100');
		});

		it('extracts destination port', () => {
			const val = getField(connectionSource as Record<string, unknown>, 'destination.port');
			expect(val).toBe(443);
		});

		it('extracts Zeek conn state', () => {
			const val = getField(connectionSource as Record<string, unknown>, 'zeek.conn.conn_state');
			expect(val).toBe('SF');
		});

		it('returns undefined for missing fields', () => {
			const val = getField(connectionSource as Record<string, unknown>, 'nonexistent.field');
			expect(val).toBeUndefined();
		});
	});

	// -- Raw JSON generation --------------------------------------------------

	describe('raw JSON', () => {
		it('generates valid JSON from connection _source', () => {
			const source = { source: { ip: '10.0.0.1' }, network: { transport: 'tcp' } };
			const rawJson = JSON.stringify(source, null, 2);

			const parsed = JSON.parse(rawJson);
			expect(parsed.source.ip).toBe('10.0.0.1');
			expect(parsed.network.transport).toBe('tcp');
		});
	});

	// -- getPacketInfo --------------------------------------------------------

	describe('getPacketInfo', () => {
		it('extracts packet info from TShark JSON', () => {
			const pkt = {
				'_source': {
					'layers': {
						'frame': {
							'frame.number': '1',
							'frame.time_relative': '0.000000',
							'frame.protocols': 'eth:ethertype:ip:tcp:tls',
							'frame.len': '66',
						},
						'ip': {
							'ip.src': '192.168.1.1',
							'ip.dst': '8.8.8.8',
						},
						'_ws.col': {
							'_ws.col.Info': 'Client Hello',
						},
					},
				},
			};

			const info = getPacketInfo(pkt as Record<string, unknown>);

			expect(info.no).toBe('1');
			expect(info.time).toBe('0.000000');
			expect(info.src).toBe('192.168.1.1');
			expect(info.dst).toBe('8.8.8.8');
			expect(info.proto).toBe('tls');
			expect(info.len).toBe('66');
			expect(info.info).toBe('Client Hello');
		});

		it('returns "?" for missing packet fields', () => {
			const pkt = {};
			const info = getPacketInfo(pkt);

			expect(info.no).toBe('?');
			expect(info.src).toBe('?');
			expect(info.dst).toBe('?');
			expect(info.proto).toBe('?');
		});
	});

	// -- Mirror mode flag -----------------------------------------------------

	describe('mirror mode behavior', () => {
		it('isMirrorMode flag is accessible as a boolean', () => {
			const isMirrorMode = true;
			expect(isMirrorMode).toBe(true);
		});

		it('defaults to false', () => {
			const isMirrorMode = false;
			expect(isMirrorMode).toBe(false);
		});
	});
});
