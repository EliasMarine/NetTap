import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getLogStats,
	getLogTimeline,
	getLogTopTalkers,
	getLogProtocolBreakdown,
	getLogTopDestinations,
	getLogTopDns,
	formatBytes,
	formatCompactNumber,
	protocolColor,
	protocolLabel,
} from './logs';

// ---------------------------------------------------------------------------
// Mock helpers
// ---------------------------------------------------------------------------

function mockFetchSuccess(body: unknown, status = 200): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: status >= 200 && status < 300,
			status,
			json: () => Promise.resolve(body),
		}),
	);
}

function mockFetchFailure(status = 500): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: false,
			status,
			json: () => Promise.reject(new Error('no body')),
		}),
	);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('logs API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getLogStats ---------------------------------------------------------

	describe('getLogStats', () => {
		it('returns stats on success', async () => {
			const expected = {
				from: '2026-03-09T00:00:00Z',
				to: '2026-03-10T00:00:00Z',
				total_events: 125000,
				unique_sources: 42,
				protocol_count: 6,
				total_bytes: 1073741824,
			};
			mockFetchSuccess(expected);

			const result = await getLogStats();

			expect(fetch).toHaveBeenCalledWith('/api/logs/stats');
			expect(result.total_events).toBe(125000);
			expect(result.unique_sources).toBe(42);
			expect(result.total_bytes).toBe(1073741824);
		});

		it('returns zeros on failure', async () => {
			mockFetchFailure(502);

			const result = await getLogStats();

			expect(result.total_events).toBe(0);
			expect(result.unique_sources).toBe(0);
			expect(result.protocol_count).toBe(0);
			expect(result.total_bytes).toBe(0);
		});

		it('passes time range parameters', async () => {
			mockFetchSuccess({ from: '', to: '', total_events: 0, unique_sources: 0, protocol_count: 0, total_bytes: 0 });

			await getLogStats({ from: '2026-03-09T00:00:00Z', to: '2026-03-10T00:00:00Z' });

			expect(fetch).toHaveBeenCalledWith(
				'/api/logs/stats?from=2026-03-09T00%3A00%3A00Z&to=2026-03-10T00%3A00%3A00Z',
			);
		});
	});

	// -- getLogTimeline ------------------------------------------------------

	describe('getLogTimeline', () => {
		it('returns timeline buckets on success', async () => {
			const expected = {
				from: '2026-03-09T00:00:00Z',
				to: '2026-03-10T00:00:00Z',
				interval: '1h',
				buckets: [
					{ timestamp: '2026-03-09T00:00:00Z', total: 100, conn: 50, dns: 20, http: 15, ssl: 5, files: 3, dhcp: 2, smtp: 1, alert: 4 },
				],
			};
			mockFetchSuccess(expected);

			const result = await getLogTimeline();

			expect(fetch).toHaveBeenCalledWith('/api/logs/timeline');
			expect(result.buckets).toHaveLength(1);
			expect(result.buckets[0].total).toBe(100);
			expect(result.buckets[0].conn).toBe(50);
		});

		it('returns empty buckets on failure', async () => {
			mockFetchFailure(500);

			const result = await getLogTimeline();

			expect(result.buckets).toEqual([]);
			expect(result.interval).toBe('1h');
		});

		it('passes interval parameter', async () => {
			mockFetchSuccess({ from: '', to: '', interval: '5m', buckets: [] });

			await getLogTimeline({ interval: '5m' });

			expect(fetch).toHaveBeenCalledWith('/api/logs/timeline?interval=5m');
		});
	});

	// -- getLogTopTalkers ----------------------------------------------------

	describe('getLogTopTalkers', () => {
		it('returns talkers on success', async () => {
			const expected = {
				from: '2026-03-09T00:00:00Z',
				to: '2026-03-10T00:00:00Z',
				talkers: [
					{ ip: '192.168.1.100', count: 5000 },
					{ ip: '192.168.1.101', count: 3000 },
				],
			};
			mockFetchSuccess(expected);

			const result = await getLogTopTalkers();

			expect(fetch).toHaveBeenCalledWith('/api/logs/top-talkers');
			expect(result.talkers).toHaveLength(2);
			expect(result.talkers[0].ip).toBe('192.168.1.100');
		});

		it('returns empty talkers on failure', async () => {
			mockFetchFailure(500);

			const result = await getLogTopTalkers();

			expect(result.talkers).toEqual([]);
		});

		it('passes limit parameter', async () => {
			mockFetchSuccess({ from: '', to: '', talkers: [] });

			await getLogTopTalkers({ limit: 5 });

			expect(fetch).toHaveBeenCalledWith('/api/logs/top-talkers?limit=5');
		});
	});

	// -- getLogProtocolBreakdown ---------------------------------------------

	describe('getLogProtocolBreakdown', () => {
		it('returns protocols on success', async () => {
			const expected = {
				from: '2026-03-09T00:00:00Z',
				to: '2026-03-10T00:00:00Z',
				protocols: [
					{ protocol: 'conn', label: 'Connections', count: 80000 },
					{ protocol: 'dns', label: 'DNS', count: 25000 },
				],
			};
			mockFetchSuccess(expected);

			const result = await getLogProtocolBreakdown();

			expect(fetch).toHaveBeenCalledWith('/api/logs/protocol-breakdown');
			expect(result.protocols).toHaveLength(2);
			expect(result.protocols[0].protocol).toBe('conn');
		});

		it('returns empty protocols on failure', async () => {
			mockFetchFailure(500);

			const result = await getLogProtocolBreakdown();

			expect(result.protocols).toEqual([]);
		});

		it('passes time range parameters', async () => {
			mockFetchSuccess({ from: '', to: '', protocols: [] });

			await getLogProtocolBreakdown({ from: '2026-03-09T00:00:00Z' });

			expect(fetch).toHaveBeenCalledWith(
				'/api/logs/protocol-breakdown?from=2026-03-09T00%3A00%3A00Z',
			);
		});
	});

	// -- getLogTopDestinations -----------------------------------------------

	describe('getLogTopDestinations', () => {
		it('returns destinations on success', async () => {
			const expected = {
				from: '2026-03-09T00:00:00Z',
				to: '2026-03-10T00:00:00Z',
				destinations: [
					{ ip: '8.8.8.8', count: 12000 },
					{ ip: '1.1.1.1', count: 8000 },
				],
			};
			mockFetchSuccess(expected);

			const result = await getLogTopDestinations();

			expect(fetch).toHaveBeenCalledWith('/api/logs/top-destinations');
			expect(result.destinations).toHaveLength(2);
			expect(result.destinations[0].ip).toBe('8.8.8.8');
		});

		it('returns empty destinations on failure', async () => {
			mockFetchFailure(500);

			const result = await getLogTopDestinations();

			expect(result.destinations).toEqual([]);
		});

		it('passes limit parameter', async () => {
			mockFetchSuccess({ from: '', to: '', destinations: [] });

			await getLogTopDestinations({ limit: 10 });

			expect(fetch).toHaveBeenCalledWith('/api/logs/top-destinations?limit=10');
		});
	});

	// -- getLogTopDns --------------------------------------------------------

	describe('getLogTopDns', () => {
		it('returns DNS queries on success', async () => {
			const expected = {
				from: '2026-03-09T00:00:00Z',
				to: '2026-03-10T00:00:00Z',
				queries: [
					{ domain: 'google.com', count: 500 },
					{ domain: 'cloudflare.com', count: 300 },
				],
			};
			mockFetchSuccess(expected);

			const result = await getLogTopDns();

			expect(fetch).toHaveBeenCalledWith('/api/logs/top-dns');
			expect(result.queries).toHaveLength(2);
			expect(result.queries[0].domain).toBe('google.com');
		});

		it('returns empty queries on failure', async () => {
			mockFetchFailure(500);

			const result = await getLogTopDns();

			expect(result.queries).toEqual([]);
		});

		it('passes limit parameter', async () => {
			mockFetchSuccess({ from: '', to: '', queries: [] });

			await getLogTopDns({ limit: 20 });

			expect(fetch).toHaveBeenCalledWith('/api/logs/top-dns?limit=20');
		});
	});
});

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

describe('formatBytes', () => {
	it('formats bytes correctly', () => {
		expect(formatBytes(0)).toBe('0 B');
		expect(formatBytes(512)).toBe('512 B');
		expect(formatBytes(1024)).toBe('1.0 KB');
		expect(formatBytes(1048576)).toBe('1.0 MB');
		expect(formatBytes(1073741824)).toBe('1.0 GB');
		expect(formatBytes(1099511627776)).toBe('1.0 TB');
	});

	it('formats fractional values', () => {
		expect(formatBytes(1536)).toBe('1.5 KB');
		expect(formatBytes(2621440)).toBe('2.5 MB');
	});
});

describe('formatCompactNumber', () => {
	it('formats small numbers as-is', () => {
		expect(formatCompactNumber(0)).toBe('0');
		expect(formatCompactNumber(500)).toBe('500');
		expect(formatCompactNumber(999)).toBe('999');
	});

	it('formats thousands with K suffix', () => {
		expect(formatCompactNumber(1000)).toBe('1.0K');
		expect(formatCompactNumber(1500)).toBe('1.5K');
		expect(formatCompactNumber(42000)).toBe('42.0K');
	});

	it('formats millions with M suffix', () => {
		expect(formatCompactNumber(1000000)).toBe('1.0M');
		expect(formatCompactNumber(2500000)).toBe('2.5M');
	});
});

describe('protocolColor', () => {
	it('returns correct colors for known protocols', () => {
		expect(protocolColor('conn')).toBe('#00b8d4');
		expect(protocolColor('dns')).toBe('#00e676');
		expect(protocolColor('http')).toBe('#ff9100');
		expect(protocolColor('ssl')).toBe('#aa66ff');
		expect(protocolColor('files')).toBe('#ffd600');
		expect(protocolColor('dhcp')).toBe('#ff4081');
		expect(protocolColor('smtp')).toBe('#18ffff');
		expect(protocolColor('alert')).toBe('#ff1744');
	});

	it('returns muted color for unknown protocol', () => {
		expect(protocolColor('unknown')).toBe('#888');
		expect(protocolColor('')).toBe('#888');
	});
});

describe('protocolLabel', () => {
	it('returns correct labels for known protocols', () => {
		expect(protocolLabel('conn')).toBe('Connections');
		expect(protocolLabel('dns')).toBe('DNS');
		expect(protocolLabel('http')).toBe('HTTP');
		expect(protocolLabel('ssl')).toBe('TLS');
		expect(protocolLabel('files')).toBe('Files');
		expect(protocolLabel('dhcp')).toBe('DHCP');
		expect(protocolLabel('smtp')).toBe('SMTP');
		expect(protocolLabel('alert')).toBe('IDS Alerts');
	});

	it('returns raw protocol string for unknown protocol', () => {
		expect(protocolLabel('ftp')).toBe('ftp');
		expect(protocolLabel('custom')).toBe('custom');
	});
});
