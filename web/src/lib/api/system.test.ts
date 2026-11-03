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

		it('throws on HTTP error instead of reporting the system degraded', async () => {
			mockFetchFailure(503);

			await expect(getSystemHealth()).rejects.toThrow('HTTP 503');
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

		it('throws on HTTP error instead of reporting 0% used', async () => {
			mockFetchFailure(500);

			await expect(getStorageStatus()).rejects.toThrow('HTTP 500');
		});
	});

	// -- getSmartHealth ------------------------------------------------------

	describe('getSmartHealth', () => {
		it('returns parsed SMART data on success', async () => {
			const expected = {
				device: '/dev/nvme0n1',
				device_type: 'nvme',
				model: 'Samsung 980 PRO',
				serial: 'S6B1NJ0TB12345',
				temperature_c: 38,
				percentage_used: 2,
				power_on_hours: 1200,
				total_bytes_written: 22162086016000,
				total_bytes_read: 44164000000000,
				media_errors: 0,
				reallocated_sectors: null,
				healthy: true,
				warnings: [],
				timestamp: '2026-03-22T14:30:00Z',
			};
			mockFetchSuccess(expected);

			const result = await getSmartHealth();

			expect(fetch).toHaveBeenCalledWith('/api/smart/health');
			expect(result).toEqual(expected);
			expect(result.total_bytes_written).toBe(22162086016000);
			expect(result.device_type).toBe('nvme');
			expect(result.serial).toBe('S6B1NJ0TB12345');
		});

		it('throws on HTTP error instead of reporting the drive degraded', async () => {
			mockFetchFailure(500);

			await expect(getSmartHealth()).rejects.toThrow('HTTP 500');
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
