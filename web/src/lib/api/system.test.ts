import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getSystemHealth,
	getStorageStatus,
	getSmartHealth,
	getIndices,
} from './system';

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

function mockFetchFailure(status = 500, body?: unknown): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: false,
			status,
			json: () => (body !== undefined ? Promise.resolve(body) : Promise.reject(new Error('no body'))),
		}),
	);
}

function mockFetchNetworkError(): void {
	vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('system API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getSystemHealth -----------------------------------------------------

	describe('getSystemHealth', () => {
		it('returns parsed health data on success', async () => {
			const expected = {
				uptime: 86400,
				timestamp: '2026-02-26T12:00:00Z',
				storage: { disk_usage_percent: 42 },
				smart: { healthy: true },
				opensearch_reachable: true,
				healthy: true,
			};
			mockFetchSuccess(expected);

			const result = await getSystemHealth();

			expect(fetch).toHaveBeenCalledWith('/api/system/health');
			expect(result).toEqual(expected);
		});

		it('returns unhealthy defaults on HTTP error', async () => {
			mockFetchFailure(503);

			const result = await getSystemHealth();

			expect(result.uptime).toBe(0);
			expect(result.storage).toBeNull();
			expect(result.smart).toBeNull();
			expect(result.opensearch_reachable).toBe(false);
			expect(result.healthy).toBe(false);
			// timestamp should be a valid ISO string
			expect(() => new Date(result.timestamp)).not.toThrow();
		});

		it('handles network failure gracefully', async () => {
			mockFetchNetworkError();

			await expect(getSystemHealth()).rejects.toThrow('Failed to fetch');
		});
	});

	// -- getStorageStatus ----------------------------------------------------

	describe('getStorageStatus', () => {
		it('returns parsed storage data on success', async () => {
			const expected = {
				disk_usage_percent: 42,
				disk_total_bytes: 1000000000,
				disk_used_bytes: 420000000,
				disk_free_bytes: 580000000,
				retention: { hot_days: 90, warm_days: 180 },
				index_summary: { total_indices: 5 },
			};
			mockFetchSuccess(expected);

			const result = await getStorageStatus();

			expect(fetch).toHaveBeenCalledWith('/api/storage/status');
			expect(result).toEqual(expected);
		});

		it('returns zero-value defaults on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getStorageStatus();

			expect(result.disk_usage_percent).toBe(0);
			expect(result.disk_total_bytes).toBe(0);
			expect(result.disk_used_bytes).toBe(0);
			expect(result.disk_free_bytes).toBe(0);
			expect(result.retention).toBeNull();
			expect(result.index_summary).toBeNull();
		});
	});

	// -- getSmartHealth ------------------------------------------------------

	describe('getSmartHealth', () => {
		it('returns parsed SMART data on success', async () => {
			const expected = {
				device: '/dev/nvme0n1',
				model: 'Samsung 980 PRO',
				temperature_c: 38,
				percentage_used: 2,
				power_on_hours: 1200,
				healthy: true,
				warnings: [],
			};
			mockFetchSuccess(expected);

			const result = await getSmartHealth();

			expect(fetch).toHaveBeenCalledWith('/api/smart/health');
			expect(result).toEqual(expected);
		});

		it('returns unhealthy defaults on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getSmartHealth();

			expect(result.device).toBe('');
			expect(result.model).toBe('');
			expect(result.temperature_c).toBe(0);
			expect(result.percentage_used).toBe(0);
			expect(result.power_on_hours).toBe(0);
			expect(result.healthy).toBe(false);
			expect(result.warnings).toEqual([]);
		});
	});

	// -- getIndices ----------------------------------------------------------

	describe('getIndices', () => {
		it('returns parsed index list on success', async () => {
			const expected = {
				indices: [
					{ name: 'zeek-conn-2026.02', size: '120mb', docs: 45000 },
					{ name: 'suricata-alert-2026.02', size: '8mb', docs: 320 },
				],
				count: 2,
			};
			mockFetchSuccess(expected);

			const result = await getIndices();

			expect(fetch).toHaveBeenCalledWith('/api/indices');
			expect(result).toEqual(expected);
		});

		it('returns empty list on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getIndices();

			expect(result.indices).toEqual([]);
			expect(result.count).toBe(0);
		});
	});
});
