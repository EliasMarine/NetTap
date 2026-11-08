import { describe, it, expect, vi, afterEach } from 'vitest';
import { getLiveConnections, getConnectionRate, getLiveDashboard, getLiveConnectionDetail, directionLabel } from './live';
import type { ConnectionDirection } from './live';

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

		// #96: a fake-empty result on failure read as a real "none" or 0
		it('throws on HTTP error so the page can say it failed', async () => {
			mockFetchFailure(502);
			await expect(getLiveConnections()).rejects.toThrow('HTTP 502');
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

		// #96: a fake-empty result on failure read as a real "none" or 0
		it('throws on HTTP error so the page can say it failed', async () => {
			mockFetchFailure(500);
			await expect(getConnectionRate()).rejects.toThrow('HTTP 500');
		});
	});

	// #96: the dashboard replaced the live view with zeros, and a failed detail read as "No alerts"
	describe('getLiveDashboard / getLiveConnectionDetail', () => {
		it('throws on HTTP error instead of a zero dashboard', async () => {
			mockFetchFailure(503);
			await expect(getLiveDashboard()).rejects.toThrow('HTTP 503');
		});

		it('throws on HTTP error instead of a detail with no alerts', async () => {
			mockFetchFailure(503);
			await expect(getLiveConnectionDetail('10.0.0.5', '8.8.8.8', 53)).rejects.toThrow('HTTP 503');
		});

		it('asks for the located end when the row names one, else leaves it to the daemon', async () => {
			mockFetchSuccess({ geo: {}, alerts: [], alert_count: 0, history: {} });
			await getLiveConnectionDetail('203.0.113.9', '192.168.1.20', 22, '203.0.113.9');
			await getLiveConnectionDetail('192.168.1.20', '8.8.8.8', 53);
			const urls = vi.mocked(fetch).mock.calls.map((c) => String(c[0]));
			expect(urls).toEqual([
				'/api/live/connection/detail?src=203.0.113.9&dst=192.168.1.20&port=22&geo=203.0.113.9',
				'/api/live/connection/detail?src=192.168.1.20&dst=8.8.8.8&port=53',
			]);
		});
	});
});

// O2: the port guess called a LAN device's WireGuard session (port 51820) inbound
describe('directionLabel', () => {
	it("words the daemon's direction", () => {
		expect(['out', 'in', 'local', 'unknown'].map((d) => directionLabel({ direction: d as ConnectionDirection }))).toEqual([
			'Out', 'In', 'Local', 'Unknown',
		]);
	});

	it('a row without a direction is unknown, not guessed from its port', () => {
		expect(directionLabel({})).toBe('Unknown');
	});
});
