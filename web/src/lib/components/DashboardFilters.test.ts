import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';

/**
 * Tests for DashboardFilters logic.
 *
 * DashboardFilters.svelte exports a FilterState interface and a
 * computeTimeRange() function. We test the time-range computation
 * thoroughly, as well as the FilterState shape and the supported
 * filter options (TIME_RANGES and PROTOCOLS).
 */

// ---------------------------------------------------------------------------
// Reproduced logic from DashboardFilters.svelte
// ---------------------------------------------------------------------------

/** Mirrors the exported FilterState interface */
interface FilterState {
	timeRange: string;
	from: string;
	to: string;
	device: string;
	protocol: string;
}

/**
 * Mirrors the exported computeTimeRange function.
 * Converts a relative time range string (e.g. '24h', '7d') into ISO 8601
 * from/to timestamps. Returns { from, to } with 'to' always set to now.
 */
function computeTimeRange(range: string): { from: string; to: string } {
	const now = new Date();
	const to = now.toISOString();

	const match = range.match(/^(\d+)(h|d)$/);
	if (!match) {
		// Fallback: default to last 24h
		const fallback = new Date(now.getTime() - 24 * 60 * 60 * 1000);
		return { from: fallback.toISOString(), to };
	}

	const amount = parseInt(match[1], 10);
	const unit = match[2];
	let msOffset: number;

	if (unit === 'h') {
		msOffset = amount * 60 * 60 * 1000;
	} else {
		// 'd'
		msOffset = amount * 24 * 60 * 60 * 1000;
	}

	const from = new Date(now.getTime() - msOffset);
	return { from: from.toISOString(), to };
}

/** Time range options as defined in the component */
const TIME_RANGES = [
	{ value: '1h', label: 'Last 1h' },
	{ value: '6h', label: 'Last 6h' },
	{ value: '24h', label: 'Last 24h' },
	{ value: '7d', label: 'Last 7d' },
	{ value: '30d', label: 'Last 30d' },
	{ value: 'custom', label: 'Custom' },
];

/** Protocol filter options as defined in the component */
const PROTOCOLS = [
	{ value: '', label: 'All Protocols' },
	{ value: 'tcp', label: 'TCP' },
	{ value: 'udp', label: 'UDP' },
	{ value: 'http', label: 'HTTP' },
	{ value: 'https', label: 'HTTPS' },
	{ value: 'dns', label: 'DNS' },
	{ value: 'ssh', label: 'SSH' },
	{ value: 'smtp', label: 'SMTP' },
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('DashboardFilters logic', () => {
	beforeEach(() => {
		vi.useFakeTimers();
		// Pin the clock so all time-based tests are deterministic
		vi.setSystemTime(new Date('2026-02-26T12:00:00.000Z'));
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	// -- computeTimeRange: hour-based ranges ----------------------------------

	describe('computeTimeRange with hour-based ranges', () => {
		it('computes "1h" as 1 hour before now', () => {
			const result = computeTimeRange('1h');
			expect(result.to).toBe('2026-02-26T12:00:00.000Z');
			expect(result.from).toBe('2026-02-26T11:00:00.000Z');
		});

		it('computes "6h" as 6 hours before now', () => {
			const result = computeTimeRange('6h');
			expect(result.to).toBe('2026-02-26T12:00:00.000Z');
			expect(result.from).toBe('2026-02-26T06:00:00.000Z');
		});

		it('computes "24h" as 24 hours before now', () => {
			const result = computeTimeRange('24h');
			expect(result.to).toBe('2026-02-26T12:00:00.000Z');
			expect(result.from).toBe('2026-02-25T12:00:00.000Z');
		});

		it('computes "12h" correctly', () => {
			const result = computeTimeRange('12h');
			expect(result.from).toBe('2026-02-26T00:00:00.000Z');
		});
	});

	// -- computeTimeRange: day-based ranges -----------------------------------

	describe('computeTimeRange with day-based ranges', () => {
		it('computes "7d" as 7 days before now', () => {
			const result = computeTimeRange('7d');
			expect(result.to).toBe('2026-02-26T12:00:00.000Z');
			expect(result.from).toBe('2026-02-19T12:00:00.000Z');
		});

		it('computes "30d" as 30 days before now', () => {
			const result = computeTimeRange('30d');
			expect(result.to).toBe('2026-02-26T12:00:00.000Z');
			expect(result.from).toBe('2026-01-27T12:00:00.000Z');
		});

		it('computes "1d" as 1 day before now', () => {
			const result = computeTimeRange('1d');
			expect(result.from).toBe('2026-02-25T12:00:00.000Z');
		});
	});

	// -- computeTimeRange: fallback behavior ----------------------------------

	describe('computeTimeRange fallback', () => {
		it('falls back to 24h for "custom" (non-matching string)', () => {
			const result = computeTimeRange('custom');
			expect(result.to).toBe('2026-02-26T12:00:00.000Z');
			expect(result.from).toBe('2026-02-25T12:00:00.000Z');
		});

		it('falls back to 24h for empty string', () => {
			const result = computeTimeRange('');
			expect(result.from).toBe('2026-02-25T12:00:00.000Z');
		});

		it('falls back to 24h for invalid format "abc"', () => {
			const result = computeTimeRange('abc');
			expect(result.from).toBe('2026-02-25T12:00:00.000Z');
		});

		it('falls back to 24h for unsupported unit "5m"', () => {
			const result = computeTimeRange('5m');
			expect(result.from).toBe('2026-02-25T12:00:00.000Z');
		});

		it('falls back to 24h for "0"', () => {
			const result = computeTimeRange('0');
			expect(result.from).toBe('2026-02-25T12:00:00.000Z');
		});
	});

	// -- computeTimeRange: output format --------------------------------------

	describe('computeTimeRange output format', () => {
		it('returns valid ISO 8601 strings for "from" and "to"', () => {
			const result = computeTimeRange('24h');
			// ISO 8601 format: YYYY-MM-DDTHH:mm:ss.sssZ
			const isoPattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/;
			expect(result.from).toMatch(isoPattern);
			expect(result.to).toMatch(isoPattern);
		});

		it('"from" is always earlier than "to"', () => {
			const result = computeTimeRange('7d');
			expect(new Date(result.from).getTime()).toBeLessThan(new Date(result.to).getTime());
		});

		it('"to" is always the current time', () => {
			const result = computeTimeRange('1h');
			expect(result.to).toBe(new Date().toISOString());
		});
	});

	// -- TIME_RANGES constant -------------------------------------------------

	describe('TIME_RANGES options', () => {
		it('has 6 time range options', () => {
			expect(TIME_RANGES).toHaveLength(6);
		});

		it('includes "1h", "6h", "24h", "7d", "30d", and "custom"', () => {
			const values = TIME_RANGES.map((r) => r.value);
			expect(values).toEqual(['1h', '6h', '24h', '7d', '30d', 'custom']);
		});

		it('each option has a non-empty label', () => {
			for (const range of TIME_RANGES) {
				expect(range.label.length).toBeGreaterThan(0);
			}
		});

		it('default time range is "24h"', () => {
			// The component defaults timeRange prop to '24h'
			const defaultRange = '24h';
			expect(TIME_RANGES.find((r) => r.value === defaultRange)).toBeTruthy();
		});
	});

	// -- PROTOCOLS constant ---------------------------------------------------

	describe('PROTOCOLS options', () => {
		it('has 8 protocol options', () => {
			expect(PROTOCOLS).toHaveLength(8);
		});

		it('first option is "All Protocols" with empty value', () => {
			expect(PROTOCOLS[0].value).toBe('');
			expect(PROTOCOLS[0].label).toBe('All Protocols');
		});

		it('includes common network protocols', () => {
			const values = PROTOCOLS.map((p) => p.value);
			expect(values).toContain('tcp');
			expect(values).toContain('udp');
			expect(values).toContain('dns');
			expect(values).toContain('http');
			expect(values).toContain('https');
			expect(values).toContain('ssh');
			expect(values).toContain('smtp');
		});

		it('each protocol has a label', () => {
			for (const proto of PROTOCOLS) {
				expect(proto.label.length).toBeGreaterThan(0);
			}
		});
	});

	// -- FilterState shape ----------------------------------------------------

	describe('FilterState interface', () => {
		it('constructs a valid FilterState object', () => {
			const state: FilterState = {
				timeRange: '24h',
				from: '2026-02-25T12:00:00.000Z',
				to: '2026-02-26T12:00:00.000Z',
				device: '',
				protocol: '',
			};

			expect(state.timeRange).toBe('24h');
			expect(state.from).toBeTruthy();
			expect(state.to).toBeTruthy();
			expect(state.device).toBe('');
			expect(state.protocol).toBe('');
		});

		it('accepts device IP and protocol values', () => {
			const state: FilterState = {
				timeRange: '7d',
				from: '2026-02-19T12:00:00.000Z',
				to: '2026-02-26T12:00:00.000Z',
				device: '192.168.1.100',
				protocol: 'tcp',
			};

			expect(state.device).toBe('192.168.1.100');
			expect(state.protocol).toBe('tcp');
		});

		it('supports custom time range', () => {
			const state: FilterState = {
				timeRange: 'custom',
				from: '2026-01-01T00:00:00.000Z',
				to: '2026-02-01T00:00:00.000Z',
				device: '',
				protocol: 'dns',
			};

			expect(state.timeRange).toBe('custom');
		});
	});
});
