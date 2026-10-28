import { describe, it, expect, vi, afterEach } from 'vitest';
import { getLiveConnections, getConnectionRate } from './live';

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

describe('live API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getLiveConnections ---------------------------------------------------

	describe('getLiveConnections', () => {
		it('returns parsed connections on success', async () => {
			const expected = {
				connections: [
					{
						timestamp: '2026-03-08T10:00:00Z',
						source_ip: '192.168.1.100',
						source_port: 54321,
						dest_ip: '93.184.216.34',
						dest_port: 443,
						protocol: 'tcp',
						service: 'https',
						bytes: 1024,
						duration: 1.5,
						country: 'US',
						country_name: 'United States',
						device_name: '',
					},
				],
				count: 1,
				filters: { device: null, proto: null, country: null },
			};
			mockFetchSuccess(expected);

			const result = await getLiveConnections();

			expect(fetch).toHaveBeenCalledWith('/api/live/connections');
			expect(result.connections).toHaveLength(1);
			expect(result.connections[0].source_ip).toBe('192.168.1.100');
		});

		it('passes filter parameters in query string', async () => {
			mockFetchSuccess({ connections: [], count: 0, filters: {} });

			await getLiveConnections({
				device: '192.168.1.100',
				proto: 'tcp',
				country: 'US',
				limit: 50,
			});

			const calledUrl = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(calledUrl).toContain('device=192.168.1.100');
			expect(calledUrl).toContain('proto=tcp');
			expect(calledUrl).toContain('country=US');
			expect(calledUrl).toContain('limit=50');
		});

		it('returns empty connections on HTTP error', async () => {
			mockFetchFailure(502);

			const result = await getLiveConnections();

			expect(result.connections).toEqual([]);
			expect(result.count).toBe(0);
		});
	});

	// -- getConnectionRate ---------------------------------------------------

	describe('getConnectionRate', () => {
		it('returns parsed rate on success', async () => {
			const expected = {
				connections_per_second: 12.5,
				total_in_window: 750,
				window_seconds: 60,
			};
			mockFetchSuccess(expected);

			const result = await getConnectionRate();

			expect(fetch).toHaveBeenCalledWith('/api/live/rate');
			expect(result.connections_per_second).toBe(12.5);
			expect(result.total_in_window).toBe(750);
		});

		it('returns zero defaults on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getConnectionRate();

			expect(result.connections_per_second).toBe(0);
			expect(result.total_in_window).toBe(0);
		});
	});
});
