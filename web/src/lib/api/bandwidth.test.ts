import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getMonthlyUsage,
	getDailyUsage,
	getDeviceUsage,
	getHeatmap,
	getBandwidthCap,
	setBandwidthCap,
	utcMonthWindow,
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

		// #96: a fake-empty result on failure read as a real "none" or 0
		it('throws on HTTP error so the page can say it failed', async () => {
			mockFetchFailure(502);
			await expect(getMonthlyUsage()).rejects.toThrow('HTTP 502');
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

		// #96: a fake-empty result on failure read as a real "none" or 0
		it('throws on HTTP error so the page can say it failed', async () => {
			mockFetchFailure(500);
			await expect(getDailyUsage()).rejects.toThrow('HTTP 500');
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

		// #96: a fake-empty result on failure read as a real "none" or 0
		it('throws on HTTP error so the page can say it failed', async () => {
			mockFetchFailure(500);
			await expect(getDeviceUsage()).rejects.toThrow('HTTP 500');
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

		it("asks for the hours in the viewer's time zone", async () => {
			vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions').mockReturnValue({
				timeZone: 'America/Los_Angeles',
			} as Intl.ResolvedDateTimeFormatOptions);
			mockFetchSuccess({ from: '', to: '', days: [], hours: [], matrix: [] });

			await getHeatmap({ from: 'a', to: 'b' });

			const url = vi.mocked(fetch).mock.calls[0][0] as string;
			expect(new URL(url, 'http://x').searchParams.get('tz')).toBe('America/Los_Angeles');
		});

		it('leaves tz off when the browser reports no zone', async () => {
			vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions').mockReturnValue({
				timeZone: '',
			} as Intl.ResolvedDateTimeFormatOptions);
			mockFetchSuccess({ from: '', to: '', days: [], hours: [], matrix: [] });

			await getHeatmap();

			expect(vi.mocked(fetch).mock.calls[0][0]).not.toContain('tz=');
		});

		// #96: a fake-empty result on failure read as a real "none" or 0
		it('throws on HTTP error so the page can say it failed', async () => {
			mockFetchFailure(500);
			await expect(getHeatmap()).rejects.toThrow('HTTP 500');
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

		// #96: a fake-empty result on failure read as a real "none" or 0
		it('throws on HTTP error so the page can say it failed', async () => {
			mockFetchFailure(500);
			await expect(getBandwidthCap()).rejects.toThrow('HTTP 500');
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

describe('utcMonthWindow (O5)', () => {
	it('starts at the first instant of the UTC month and ends at now', () => {
		expect(utcMonthWindow(new Date('2026-11-06T07:10:00Z'))).toEqual({
			year: 2026, month: 11, from: '2026-11-01T00:00:00.000Z', to: '2026-11-06T07:10:00.000Z',
		});
	});

	it('month rollover, positive offset: already December locally, still November in UTC', () => {
		// 01:30 on 1 December in UTC+2 is 23:30 on 30 November UTC
		const w = utcMonthWindow(new Date('2026-12-01T01:30:00+02:00'));
		expect([w.year, w.month, w.from]).toEqual([2026, 11, '2026-11-01T00:00:00.000Z']);
	});

	it('year rollover, negative offset: still 31 December locally, already January in UTC', () => {
		// 20:00 on 31 December in UTC-5 is 01:00 on 1 January UTC
		const w = utcMonthWindow(new Date('2026-12-31T20:00:00-05:00'));
		expect([w.year, w.month, w.from, w.to]).toEqual([2027, 1, '2027-01-01T00:00:00.000Z', '2027-01-01T01:00:00.000Z']);
	});
});
