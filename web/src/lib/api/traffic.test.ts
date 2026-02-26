import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getTrafficSummary,
	getTopTalkers,
	getProtocolDistribution,
	getBandwidthTimeSeries,
} from './traffic';

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

describe('traffic API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getTrafficSummary ---------------------------------------------------

	describe('getTrafficSummary', () => {
		it('returns parsed summary data on success', async () => {
			const expected = {
				from: '2026-02-25T00:00:00Z',
				to: '2026-02-26T00:00:00Z',
				total_bytes: 1073741824,
				orig_bytes: 536870912,
				resp_bytes: 536870912,
				packet_count: 1000000,
				connection_count: 50000,
				top_protocol: 'tcp',
			};
			mockFetchSuccess(expected);

			const result = await getTrafficSummary();

			expect(fetch).toHaveBeenCalledWith('/api/traffic/summary');
			expect(result).toEqual(expected);
		});

		it('returns zero-value defaults on HTTP error', async () => {
			mockFetchFailure(502);

			const result = await getTrafficSummary();

			expect(result.total_bytes).toBe(0);
			expect(result.connection_count).toBe(0);
			expect(result.top_protocol).toBe('unknown');
		});

		it('passes time range parameters', async () => {
			mockFetchSuccess({ from: '', to: '', total_bytes: 0, orig_bytes: 0, resp_bytes: 0, packet_count: 0, connection_count: 0, top_protocol: 'unknown' });

			await getTrafficSummary({ from: '2026-02-25T00:00:00Z', to: '2026-02-26T00:00:00Z' });

			expect(fetch).toHaveBeenCalledWith(
				expect.stringContaining('/api/traffic/summary?')
			);
		});
	});

	// -- getTopTalkers -------------------------------------------------------

	describe('getTopTalkers', () => {
		it('returns parsed top talkers on success', async () => {
			const expected = {
				from: '2026-02-25T00:00:00Z',
				to: '2026-02-26T00:00:00Z',
				limit: 10,
				top_talkers: [
					{ ip: '192.168.1.100', total_bytes: 500000, connection_count: 120 },
					{ ip: '192.168.1.101', total_bytes: 300000, connection_count: 80 },
				],
			};
			mockFetchSuccess(expected);

			const result = await getTopTalkers({ limit: 10 });

			expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/traffic/top-talkers'));
			expect(result.top_talkers).toHaveLength(2);
			expect(result.top_talkers[0].ip).toBe('192.168.1.100');
		});

		it('returns empty list on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getTopTalkers();

			expect(result.top_talkers).toEqual([]);
		});
	});

	// -- getProtocolDistribution ---------------------------------------------

	describe('getProtocolDistribution', () => {
		it('returns parsed protocol data on success', async () => {
			const expected = {
				from: '',
				to: '',
				protocols: [
					{ name: 'tcp', count: 8000 },
					{ name: 'udp', count: 3000 },
				],
				services: [
					{ name: 'http', count: 4000 },
					{ name: 'dns', count: 2500 },
				],
			};
			mockFetchSuccess(expected);

			const result = await getProtocolDistribution();

			expect(fetch).toHaveBeenCalledWith('/api/traffic/protocols');
			expect(result.protocols).toHaveLength(2);
		});

		it('returns empty arrays on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getProtocolDistribution();

			expect(result.protocols).toEqual([]);
			expect(result.services).toEqual([]);
		});
	});

	// -- getBandwidthTimeSeries ----------------------------------------------

	describe('getBandwidthTimeSeries', () => {
		it('returns parsed bandwidth series on success', async () => {
			const expected = {
				from: '',
				to: '',
				interval: '1h',
				series: [
					{ timestamp: '2026-02-25T00:00:00Z', orig_bytes: 1000, resp_bytes: 2000, total_bytes: 3000, connections: 50 },
					{ timestamp: '2026-02-25T01:00:00Z', orig_bytes: 1500, resp_bytes: 2500, total_bytes: 4000, connections: 60 },
				],
			};
			mockFetchSuccess(expected);

			const result = await getBandwidthTimeSeries({ interval: '1h' });

			expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/traffic/bandwidth'));
			expect(result.series).toHaveLength(2);
		});

		it('returns empty series on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getBandwidthTimeSeries();

			expect(result.series).toEqual([]);
		});
	});
});
