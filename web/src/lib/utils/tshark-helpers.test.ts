import { describe, it, expect } from 'vitest';
import {
	unwrap,
	getPacketSummary,
	formatDuration,
	formatBytes,
	CONN_STATE_DESC,
} from './tshark-helpers';

// ---------------------------------------------------------------------------
// unwrap
// ---------------------------------------------------------------------------

describe('unwrap', () => {
	it('extracts first element from an array', () => {
		expect(unwrap(['42'])).toBe('42');
	});

	it('handles multi-element arrays (takes first)', () => {
		expect(unwrap(['a', 'b', 'c'])).toBe('a');
	});

	it('handles empty arrays', () => {
		expect(unwrap([])).toBe('');
	});

	it('converts non-string array elements to string', () => {
		expect(unwrap([123])).toBe('123');
	});

	it('returns empty string for null', () => {
		expect(unwrap(null)).toBe('');
	});

	it('returns empty string for undefined', () => {
		expect(unwrap(undefined)).toBe('');
	});

	it('converts a plain string through unchanged', () => {
		expect(unwrap('hello')).toBe('hello');
	});

	it('converts numbers to string', () => {
		expect(unwrap(99)).toBe('99');
	});

	it('converts booleans to string', () => {
		expect(unwrap(true)).toBe('true');
	});
});

// ---------------------------------------------------------------------------
// getPacketSummary
// ---------------------------------------------------------------------------

describe('getPacketSummary', () => {
	it('extracts fields from a standard TShark JSON packet', () => {
		const pkt = {
			_source: {
				layers: {
					frame: {
						'frame.number': ['7'],
						'frame.time_relative': ['0.001234'],
						'frame.len': ['128'],
						'frame.protocols': ['eth:ethertype:ip:tcp:http'],
					},
					ip: {
						'ip.src': ['192.168.1.1'],
						'ip.dst': ['10.0.0.1'],
					},
					'_ws.col': {
						'_ws.col.Info': ['GET /index.html HTTP/1.1'],
					},
				},
			},
		};

		const summary = getPacketSummary(pkt);
		expect(summary.no).toBe('7');
		expect(summary.time).toBe('0.001234');
		expect(summary.src).toBe('192.168.1.1');
		expect(summary.dst).toBe('10.0.0.1');
		expect(summary.proto).toBe('http');
		expect(summary.len).toBe('128');
		expect(summary.info).toBe('GET /index.html HTTP/1.1');
	});

	it('handles IPv6 addresses', () => {
		const pkt = {
			_source: {
				layers: {
					frame: {
						'frame.number': ['1'],
						'frame.protocols': ['eth:ethertype:ipv6:tcp'],
						'frame.len': ['64'],
					},
					ipv6: {
						'ipv6.src': ['::1'],
						'ipv6.dst': ['fe80::1'],
					},
				},
			},
		};

		const summary = getPacketSummary(pkt);
		expect(summary.src).toBe('::1');
		expect(summary.dst).toBe('fe80::1');
	});

	it('returns "?" for missing fields', () => {
		const pkt = { _source: { layers: {} } };
		const summary = getPacketSummary(pkt);
		expect(summary.no).toBe('?');
		expect(summary.src).toBe('?');
		expect(summary.dst).toBe('?');
		expect(summary.len).toBe('?');
	});

	it('returns empty string for missing info column', () => {
		const pkt = {
			_source: {
				layers: {
					frame: { 'frame.number': ['1'], 'frame.protocols': ['eth:ip'], 'frame.len': ['60'] },
					ip: { 'ip.src': ['1.1.1.1'], 'ip.dst': ['2.2.2.2'] },
				},
			},
		};
		const summary = getPacketSummary(pkt);
		expect(summary.info).toBe('');
	});

	it('falls back to frame.time when frame.time_relative is missing', () => {
		const pkt = {
			_source: {
				layers: {
					frame: {
						'frame.number': ['1'],
						'frame.time': ['Jan 01, 2024 00:00:00'],
						'frame.protocols': ['eth:ip'],
						'frame.len': ['60'],
					},
					ip: { 'ip.src': ['1.1.1.1'], 'ip.dst': ['2.2.2.2'] },
				},
			},
		};
		const summary = getPacketSummary(pkt);
		expect(summary.time).toBe('Jan 01, 2024 00:00:00');
	});

	it('handles null/undefined packet gracefully', () => {
		const summary = getPacketSummary(null as any);
		expect(summary.no).toBe('?');
		expect(summary.src).toBe('?');
		expect(summary.info).toBe('');
	});

	it('extracts last protocol from protocols chain', () => {
		const pkt = {
			_source: {
				layers: {
					frame: {
						'frame.number': ['1'],
						'frame.protocols': ['eth:ethertype:ip:tcp:tls'],
						'frame.len': ['100'],
					},
					ip: { 'ip.src': ['1.1.1.1'], 'ip.dst': ['2.2.2.2'] },
				},
			},
		};
		expect(getPacketSummary(pkt).proto).toBe('tls');
	});
});

// ---------------------------------------------------------------------------
// formatDuration
// ---------------------------------------------------------------------------

describe('formatDuration', () => {
	it('returns "--" for null', () => {
		expect(formatDuration(null)).toBe('--');
	});

	it('returns "--" for undefined', () => {
		expect(formatDuration(undefined)).toBe('--');
	});

	it('returns original string for NaN', () => {
		expect(formatDuration('abc')).toBe('abc');
	});

	it('formats microseconds', () => {
		expect(formatDuration(0.0005)).toBe('500\u00b5s');
	});

	it('formats milliseconds', () => {
		expect(formatDuration(0.5)).toBe('500ms');
	});

	it('formats seconds', () => {
		expect(formatDuration(5.3)).toBe('5.3s');
	});

	it('formats minutes and seconds', () => {
		expect(formatDuration(125)).toBe('2m 5s');
	});

	it('formats hours and minutes', () => {
		expect(formatDuration(3661)).toBe('1h 1m');
	});

	it('handles zero', () => {
		expect(formatDuration(0)).toBe('0\u00b5s');
	});

	it('handles string number input', () => {
		expect(formatDuration('30')).toBe('30.0s');
	});
});

// ---------------------------------------------------------------------------
// formatBytes
// ---------------------------------------------------------------------------

describe('formatBytes', () => {
	it('returns "--" for null', () => {
		expect(formatBytes(null)).toBe('--');
	});

	it('returns "--" for undefined', () => {
		expect(formatBytes(undefined)).toBe('--');
	});

	it('returns original string for NaN', () => {
		expect(formatBytes('xyz')).toBe('xyz');
	});

	it('formats bytes', () => {
		expect(formatBytes(500)).toBe('500 B');
	});

	it('formats kilobytes', () => {
		expect(formatBytes(1536)).toBe('1.5 KB');
	});

	it('formats megabytes', () => {
		expect(formatBytes(2_097_152)).toBe('2.0 MB');
	});

	it('formats gigabytes', () => {
		expect(formatBytes(1_610_612_736)).toBe('1.5 GB');
	});

	it('handles zero', () => {
		expect(formatBytes(0)).toBe('0 B');
	});

	it('handles string number input', () => {
		expect(formatBytes('1024')).toBe('1.0 KB');
	});
});

// ---------------------------------------------------------------------------
// CONN_STATE_DESC
// ---------------------------------------------------------------------------

describe('CONN_STATE_DESC', () => {
	it('has all standard Zeek connection states', () => {
		const expectedStates = ['S0', 'S1', 'SF', 'REJ', 'S2', 'S3', 'RSTO', 'RSTR', 'RSTOS0', 'RSTRH', 'SH', 'SHR', 'OTH'];
		for (const state of expectedStates) {
			expect(CONN_STATE_DESC[state]).toBeDefined();
			expect(CONN_STATE_DESC[state].length).toBeGreaterThan(0);
		}
	});

	it('returns undefined for unknown states', () => {
		expect(CONN_STATE_DESC['UNKNOWN']).toBeUndefined();
	});
});
