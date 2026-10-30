import { describe, it, expect, vi, afterEach } from 'vitest';
import { previewCleanup, executeCleanup } from './storage';

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

function mockFetchError(body: unknown, status = 500): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: false,
			status,
			json: () => Promise.resolve(body),
		}),
	);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('storage cleanup API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- previewCleanup -------------------------------------------------------

	describe('previewCleanup', () => {
		it('sends POST with correct body and returns preview', async () => {
			const expected = {
				indices: [{ name: 'zeek-conn-2026.01.15', size_bytes: 50000000, tier: 'hot', parsed_date: '2026-01-15T00:00:00+00:00' }],
				pcap_files: [],
				total_indices: 1,
				total_pcap_files: 0,
				total_size_bytes: 50000000,
				index_size_bytes: 50000000,
				pcap_size_bytes: 0,
				cutoff_date: '2026-02-20T00:00:00+00:00',
				estimated_freed_bytes: 50000000,
			};
			mockFetchSuccess(expected);

			const result = await previewCleanup(30);

			expect(result.total_indices).toBe(1);
			expect(result.estimated_freed_bytes).toBe(50000000);
			expect(result.indices[0].name).toBe('zeek-conn-2026.01.15');

			const callArgs = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
			expect(callArgs[0]).toBe('/api/storage/cleanup/preview');
			expect(callArgs[1].method).toBe('POST');
			const body = JSON.parse(callArgs[1].body);
			expect(body.older_than_days).toBe(30);
		});

		it('throws on server error with error message', async () => {
			mockFetchError({ error: 'OpenSearch is unreachable' }, 503);

			await expect(previewCleanup(30)).rejects.toThrow('OpenSearch is unreachable');
		});

		it('throws with generic message when error body is unparseable', async () => {
			vi.stubGlobal(
				'fetch',
				vi.fn().mockResolvedValue({
					ok: false,
					status: 500,
					json: () => Promise.reject(new Error('no body')),
				}),
			);

			await expect(previewCleanup(30)).rejects.toThrow('Preview failed');
		});
	});

	// -- executeCleanup -------------------------------------------------------

	describe('executeCleanup', () => {
		it('sends POST with correct body and returns result', async () => {
			const expected = {
				deleted_indices: 5,
				deleted_pcap_files: 3,
				freed_bytes_estimate: 150000000,
				errors: [],
				cutoff_date: '2026-02-20T00:00:00+00:00',
			};
			mockFetchSuccess(expected);

			const result = await executeCleanup(30);

			expect(result.deleted_indices).toBe(5);
			expect(result.deleted_pcap_files).toBe(3);
			expect(result.freed_bytes_estimate).toBe(150000000);
			expect(result.errors).toEqual([]);

			const callArgs = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
			expect(callArgs[0]).toBe('/api/storage/cleanup/execute');
			expect(callArgs[1].method).toBe('POST');
			const body = JSON.parse(callArgs[1].body);
			expect(body.older_than_days).toBe(30);
		});

		it('throws on 409 conflict (lock contention)', async () => {
			mockFetchError(
				{ error: 'A storage maintenance cycle is currently running. Please try again in a few minutes.' },
				409,
			);

			await expect(executeCleanup(30)).rejects.toThrow('maintenance cycle is currently running');
		});

		it('throws on server error', async () => {
			mockFetchError({ error: 'Cleanup failed: connection timeout' }, 500);

			await expect(executeCleanup(30)).rejects.toThrow('Cleanup failed: connection timeout');
		});

		it('throws with generic message when error body is unparseable', async () => {
			vi.stubGlobal(
				'fetch',
				vi.fn().mockResolvedValue({
					ok: false,
					status: 500,
					json: () => Promise.reject(new Error('no body')),
				}),
			);

			await expect(executeCleanup(30)).rejects.toThrow('Cleanup failed');
		});
	});
});
