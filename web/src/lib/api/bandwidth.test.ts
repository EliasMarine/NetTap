import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getMonthlyUsage,
	getDailyUsage,
	getDeviceUsage,
	getHeatmap,
	getBandwidthCap,
	setBandwidthCap,
} from './bandwidth';

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

describe('bandwidth API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getMonthlyUsage ---------------------------------------------------

	describe('getMonthlyUsage', () => {
		it('returns parsed monthly data on success', async () => {
			const expected = {
				year: 2026,
				month: 3,
				total_bytes: 800_000_000_000,
				orig_bytes: 500_000_000_000,
				resp_bytes: 300_000_000_000,
				projection: {
					year: 2026,
					month: 3,
					current_bytes: 800_000_000_000,
					projected_bytes: 1_200_000_000_000,
					days_elapsed: 15.5,
					days_in_month: 31,
					daily_rate_bytes: 51_000_000_000,
					cap_bytes: 0,
					usage_percent: 0,
					projected_percent: 0,
					exceeds_cap: false,
				},
			};
			mockFetchSuccess(expected);

			const result = await getMonthlyUsage();

			expect(fetch).toHaveBeenCalledWith('/api/bandwidth/monthly');
			expect(result.total_bytes).toBe(800_000_000_000);
			expect(result.projection.projected_bytes).toBe(1_200_000_000_000);
		});

		it('passes year/month parameters', async () => {
			mockFetchSuccess({ year: 2026, month: 1, total_bytes: 0, orig_bytes: 0, resp_bytes: 0, projection: {} });

			await getMonthlyUsage({ year: 2026, month: 1 });

			const calledUrl = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(calledUrl).toContain('year=2026');
			expect(calledUrl).toContain('month=1');
		});

		it('returns zero defaults on HTTP error', async () => {
			mockFetchFailure(502);

			const result = await getMonthlyUsage();

			expect(result.total_bytes).toBe(0);
		});
	});

	// -- getDailyUsage ---------------------------------------------------

	describe('getDailyUsage', () => {
		it('returns parsed daily data on success', async () => {
			const expected = {
				from: '2026-03-01T00:00:00Z',
				to: '2026-03-08T00:00:00Z',
				daily: [
					{ date: '2026-03-01', total_bytes: 30_000_000_000, orig_bytes: 10_000_000_000, resp_bytes: 20_000_000_000, connections: 5000 },
					{ date: '2026-03-02', total_bytes: 25_000_000_000, orig_bytes: 8_000_000_000, resp_bytes: 17_000_000_000, connections: 4500 },
				],
			};
			mockFetchSuccess(expected);

			const result = await getDailyUsage();

			expect(fetch).toHaveBeenCalledWith('/api/bandwidth/daily');
			expect(result.daily).toHaveLength(2);
		});

		it('returns empty daily on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getDailyUsage();

			expect(result.daily).toEqual([]);
		});
	});

	// -- getDeviceUsage ---------------------------------------------------

	describe('getDeviceUsage', () => {
		it('returns parsed device data on success', async () => {
			const expected = {
				from: '',
				to: '',
				devices: [
					{ ip: '192.168.1.100', total_bytes: 100_000_000, orig_bytes: 40_000_000, resp_bytes: 60_000_000, connection_count: 1000, percent_of_total: 65.5 },
					{ ip: '192.168.1.101', total_bytes: 50_000_000, orig_bytes: 20_000_000, resp_bytes: 30_000_000, connection_count: 500, percent_of_total: 34.5 },
				],
			};
			mockFetchSuccess(expected);

			const result = await getDeviceUsage();

			expect(result.devices).toHaveLength(2);
			expect(result.devices[0].ip).toBe('192.168.1.100');
		});

		it('returns empty devices on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getDeviceUsage();

			expect(result.devices).toEqual([]);
		});
	});

	// -- getHeatmap ---------------------------------------------------

	describe('getHeatmap', () => {
		it('returns parsed heatmap on success', async () => {
			const matrix = Array.from({ length: 7 }, () => Array(24).fill(0));
			matrix[0][9] = 3000;
			const expected = {
				from: '',
				to: '',
				days: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
				hours: Array.from({ length: 24 }, (_, i) => i),
				matrix,
			};
			mockFetchSuccess(expected);

			const result = await getHeatmap();

			expect(result.matrix).toHaveLength(7);
			expect(result.matrix[0][9]).toBe(3000);
		});

		it('returns zero matrix on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getHeatmap();

			expect(result.matrix).toHaveLength(7);
			expect(result.matrix[0]).toHaveLength(24);
		});
	});

	// -- getBandwidthCap ---------------------------------------------------

	describe('getBandwidthCap', () => {
		it('returns cap on success', async () => {
			const expected = {
				monthly_cap_bytes: 1_288_490_188_800,
				monthly_cap_gb: 1200,
				enabled: true,
				current_usage_bytes: 800_000_000_000,
				usage_percent: 62.1,
			};
			mockFetchSuccess(expected);

			const result = await getBandwidthCap();

			expect(result.monthly_cap_gb).toBe(1200);
			expect(result.enabled).toBe(true);
		});

		it('returns disabled cap on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getBandwidthCap();

			expect(result.enabled).toBe(false);
		});
	});

	// -- setBandwidthCap ---------------------------------------------------

	describe('setBandwidthCap', () => {
		it('sends PUT request with cap value', async () => {
			mockFetchSuccess({ result: 'saved', monthly_cap_gb: 1200, monthly_cap_bytes: 1_288_490_188_800 });

			const result = await setBandwidthCap(1200);

			expect(fetch).toHaveBeenCalledWith('/api/settings/bandwidth-cap', expect.objectContaining({
				method: 'PUT',
			}));
			expect(result.monthly_cap_gb).toBe(1200);
		});

		it('throws on HTTP error', async () => {
			mockFetchFailure(400);

			await expect(setBandwidthCap(0)).rejects.toThrow();
		});
	});
});
