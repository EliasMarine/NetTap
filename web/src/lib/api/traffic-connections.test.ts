import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getConnectionStats,
	getConnectionSankey,
	getConnectionTimeline,
	getRelatedConnections,
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

describe('connections v3 API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getConnectionStats --------------------------------------------------

	describe('getConnectionStats', () => {
		it('returns parsed stats on success', async () => {
			const expected = {
				from: '2026-03-17T00:00:00Z',
				to: '2026-03-17T01:00:00Z',
				total_sessions: 5000,
				bytes_in: 1000000,
				bytes_out: 3000000,
				alert_sessions: 42,
				protocols: [{ name: 'tcp', count: 3000 }],
				top_sources: [{ ip: '192.168.1.10', total_bytes: 500000, connections: 200 }],
				top_destinations: [{ ip: '8.8.8.8', total_bytes: 300000, connections: 100, asn: 'Google', country: 'US' }],
			};
			mockFetchSuccess(expected);

			const result = await getConnectionStats({ from: '2026-03-17T00:00:00Z', to: '2026-03-17T01:00:00Z' });

			expect(fetch).toHaveBeenCalled();
			const calledUrl = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(calledUrl).toContain('/api/traffic/connections/stats');
			expect(result.total_sessions).toBe(5000);
			expect(result.alert_sessions).toBe(42);
			expect(result.protocols).toHaveLength(1);
		});

		it('returns empty defaults on HTTP error', async () => {
			mockFetchFailure(502);

			const result = await getConnectionStats();

			expect(result.total_sessions).toBe(0);
			expect(result.protocols).toEqual([]);
		});
	});

	// -- getConnectionSankey -------------------------------------------------

	describe('getConnectionSankey', () => {
		it('returns nodes and links on success', async () => {
			const expected = {
				from: '', to: '',
				nodes: {
					sources: [{ id: '10.0.0.1', label: '10.0.0.1', value: 1000 }],
					protocols: [{ id: 'tcp', label: 'TCP', value: 800 }],
					destinations: [{ id: 'Google', label: 'Google', value: 600, country: 'US' }],
				},
				links: [{ source: '10.0.0.1', target: 'tcp', value: 800 }],
			};
			mockFetchSuccess(expected);

			const result = await getConnectionSankey({ limit: 5 });

			const calledUrl = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(calledUrl).toContain('/api/traffic/connections/sankey');
			expect(calledUrl).toContain('limit=5');
			expect(result.nodes.sources).toHaveLength(1);
			expect(result.links).toHaveLength(1);
		});

		it('returns empty data on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getConnectionSankey();

			expect(result.nodes.sources).toEqual([]);
			expect(result.links).toEqual([]);
		});
	});

	// -- getConnectionTimeline -----------------------------------------------

	describe('getConnectionTimeline', () => {
		it('returns timeline buckets on success', async () => {
			const expected = {
				from: '', to: '', interval: '5m',
				buckets: [
					{ timestamp: '2026-03-17T00:00:00Z', total: 150, protocols: { tcp: 100, udp: 50 } },
					{ timestamp: '2026-03-17T00:05:00Z', total: 200, protocols: { tcp: 180, udp: 20 } },
				],
			};
			mockFetchSuccess(expected);

			const result = await getConnectionTimeline({ interval: '5m' });

			const calledUrl = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(calledUrl).toContain('/api/traffic/connections/timeline');
			expect(calledUrl).toContain('interval=5m');
			expect(result.buckets).toHaveLength(2);
			expect(result.buckets[0].protocols.tcp).toBe(100);
		});

		it('returns empty buckets on HTTP error', async () => {
			mockFetchFailure(502);

			const result = await getConnectionTimeline();

			expect(result.buckets).toEqual([]);
		});
	});

	// -- getRelatedConnections -----------------------------------------------

	describe('getRelatedConnections', () => {
		it('returns related connections with summary', async () => {
			const expected = {
				from: '', to: '',
				src_ip: '192.168.1.10', dst_ip: '8.8.8.8',
				total_connections: 5,
				total_bytes: 25000,
				protocols: ['tcp', 'udp'],
				first_seen: '2026-03-17T10:00:00Z',
				last_seen: '2026-03-17T11:00:00Z',
				connections: [{ _id: '1' }, { _id: '2' }],
			};
			mockFetchSuccess(expected);

			const result = await getRelatedConnections('192.168.1.10', '8.8.8.8');

			const calledUrl = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(calledUrl).toContain('/api/traffic/connections/related');
			expect(calledUrl).toContain('src_ip=192.168.1.10');
			expect(calledUrl).toContain('dst_ip=8.8.8.8');
			expect(result.total_connections).toBe(5);
			expect(result.protocols).toContain('tcp');
		});

		it('returns empty defaults on HTTP error', async () => {
			mockFetchFailure(400);

			const result = await getRelatedConnections('10.0.0.1', '10.0.0.2');

			expect(result.total_connections).toBe(0);
			expect(result.connections).toEqual([]);
			expect(result.first_seen).toBeNull();
		});
	});
});
