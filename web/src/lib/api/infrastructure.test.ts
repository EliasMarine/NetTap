import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getOpenSearchCluster,
	getOpenSearchIndices,
	getOpenSearchTemplates,
	getLogstashStats,
	getLogstashPipelines,
} from './infrastructure';

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

function mockFetchReject(): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockRejectedValue(new Error('network error')),
	);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('infrastructure API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getOpenSearchCluster -------------------------------------------------

	describe('getOpenSearchCluster', () => {
		it('returns parsed cluster health on success', async () => {
			const expected = {
				status: 'green',
				number_of_nodes: 1,
				active_primary_shards: 5,
				active_shards: 5,
				unassigned_shards: 0,
				relocating_shards: 0,
				pending_tasks: 0,
				total_docs: 123456,
				total_data_size_bytes: 99887766,
			};
			mockFetchSuccess(expected);

			const result = await getOpenSearchCluster();

			expect(result.status).toBe('green');
			expect(result.number_of_nodes).toBe(1);
			expect(result.active_primary_shards).toBe(5);
			expect(result.total_docs).toBe(123456);
			expect(result.total_data_size_bytes).toBe(99887766);
		});

		it('calls the correct URL', async () => {
			mockFetchSuccess({ status: 'green' });

			await getOpenSearchCluster();

			expect(fetch).toHaveBeenCalledWith('/api/opensearch/cluster');
		});

		it('returns red defaults on HTTP error', async () => {
			mockFetchFailure(503);

			const result = await getOpenSearchCluster();

			expect(result.status).toBe('red');
			expect(result.number_of_nodes).toBe(0);
			expect(result.total_docs).toBe(0);
		});

		it('returns red defaults on network error', async () => {
			mockFetchReject();

			const result = await getOpenSearchCluster();

			expect(result.status).toBe('red');
			expect(result.number_of_nodes).toBe(0);
		});
	});

	// -- getOpenSearchIndices -------------------------------------------------

	describe('getOpenSearchIndices', () => {
		it('returns parsed indices on success', async () => {
			const expected = {
				indices: [
					{
						index: 'arkime_sessions3-250322',
						health: 'green',
						status: 'open',
						docs_count: 5000,
						pri_store_size: '100mb',
						store_size: '100mb',
						creation_date: '2026-03-22',
					},
				],
				count: 1,
			};
			mockFetchSuccess(expected);

			const result = await getOpenSearchIndices();

			expect(result.indices).toHaveLength(1);
			expect(result.indices[0].index).toBe('arkime_sessions3-250322');
			expect(result.indices[0].docs_count).toBe(5000);
			expect(result.count).toBe(1);
		});

		it('calls the correct URL', async () => {
			mockFetchSuccess({ indices: [], count: 0 });

			await getOpenSearchIndices();

			expect(fetch).toHaveBeenCalledWith('/api/opensearch/indices');
		});

		it('returns empty array on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getOpenSearchIndices();

			expect(result.indices).toEqual([]);
			expect(result.count).toBe(0);
		});

		it('returns empty array on network error', async () => {
			mockFetchReject();

			const result = await getOpenSearchIndices();

			expect(result.indices).toEqual([]);
			expect(result.count).toBe(0);
		});
	});

	// -- getOpenSearchTemplates -----------------------------------------------

	describe('getOpenSearchTemplates', () => {
		it('returns parsed templates on success', async () => {
			const expected = [
				{ name: 'zeek_template', index_patterns: ['zeek-*'] },
				{ name: 'suricata_template', index_patterns: ['suricata-*'] },
			];
			mockFetchSuccess(expected);

			const result = await getOpenSearchTemplates();

			expect(result).toHaveLength(2);
			expect(result[0]).toEqual({ name: 'zeek_template', index_patterns: ['zeek-*'] });
		});

		it('calls the correct URL', async () => {
			mockFetchSuccess([]);

			await getOpenSearchTemplates();

			expect(fetch).toHaveBeenCalledWith('/api/opensearch/templates');
		});

		it('returns empty array if response is not an array', async () => {
			mockFetchSuccess({ templates: 'not-an-array' });

			const result = await getOpenSearchTemplates();

			expect(result).toEqual([]);
		});

		it('returns empty array on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getOpenSearchTemplates();

			expect(result).toEqual([]);
		});

		it('returns empty array on network error', async () => {
			mockFetchReject();

			const result = await getOpenSearchTemplates();

			expect(result).toEqual([]);
		});
	});

	// -- getLogstashStats -----------------------------------------------------

	describe('getLogstashStats', () => {
		it('returns parsed stats from flat response', async () => {
			const expected = {
				events_in: 10000,
				events_out: 9500,
				events_filtered: 500,
				events_duration_millis: 12345,
				heap_used_bytes: 500000000,
				heap_max_bytes: 1000000000,
				heap_used_percent: 50,
				cpu_percent: 15,
			};
			mockFetchSuccess(expected);

			const result = await getLogstashStats();

			expect(result.events_in).toBe(10000);
			expect(result.events_out).toBe(9500);
			expect(result.events_filtered).toBe(500);
			expect(result.events_duration_millis).toBe(12345);
			expect(result.heap_used_bytes).toBe(500000000);
			expect(result.heap_max_bytes).toBe(1000000000);
			expect(result.heap_used_percent).toBe(50);
			expect(result.cpu_percent).toBe(15);
		});

		it('normalises nested response format', async () => {
			const nested = {
				events: {
					in: 8000,
					out: 7500,
					filtered: 400,
					duration_in_millis: 9999,
				},
				jvm: {
					mem: {
						heap_used_in_bytes: 400000000,
						heap_max_in_bytes: 800000000,
						heap_used_percent: 50,
					},
				},
				process: {
					cpu: {
						percent: 25,
					},
				},
			};
			mockFetchSuccess(nested);

			const result = await getLogstashStats();

			expect(result.events_in).toBe(8000);
			expect(result.events_out).toBe(7500);
			expect(result.events_filtered).toBe(400);
			expect(result.events_duration_millis).toBe(9999);
			expect(result.heap_used_bytes).toBe(400000000);
			expect(result.heap_max_bytes).toBe(800000000);
			expect(result.heap_used_percent).toBe(50);
			expect(result.cpu_percent).toBe(25);
		});

		it('prefers flat keys over nested when both are present', async () => {
			const mixed = {
				events_in: 100,
				events: { in: 200 },
			};
			mockFetchSuccess(mixed);

			const result = await getLogstashStats();

			expect(result.events_in).toBe(100);
		});

		it('calls the correct URL', async () => {
			mockFetchSuccess({});

			await getLogstashStats();

			expect(fetch).toHaveBeenCalledWith('/api/logstash/stats');
		});

		it('returns zeros on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getLogstashStats();

			expect(result.events_in).toBe(0);
			expect(result.events_out).toBe(0);
			expect(result.heap_used_bytes).toBe(0);
			expect(result.cpu_percent).toBe(0);
		});

		it('returns zeros on network error', async () => {
			mockFetchReject();

			const result = await getLogstashStats();

			expect(result.events_in).toBe(0);
			expect(result.heap_used_bytes).toBe(0);
		});
	});

	// -- getLogstashPipelines -------------------------------------------------

	describe('getLogstashPipelines', () => {
		it('returns parsed pipelines from array response', async () => {
			const expected = [
				{
					id: 'main',
					events_in: 5000,
					events_out: 4500,
					events_filtered: 500,
					duration_in_millis: 6000,
				},
			];
			mockFetchSuccess(expected);

			const result = await getLogstashPipelines();

			expect(result).toHaveLength(1);
			expect(result[0].id).toBe('main');
			expect(result[0].events_in).toBe(5000);
			expect(result[0].events_out).toBe(4500);
		});

		it('unwraps { pipelines: [...] } envelope', async () => {
			const wrapped = {
				pipelines: [
					{
						id: 'main',
						events_in: 3000,
						events_out: 2800,
						events_filtered: 200,
						duration_in_millis: 4000,
					},
					{
						id: 'beats',
						events_in: 1000,
						events_out: 1000,
						events_filtered: 0,
						duration_in_millis: 500,
					},
				],
			};
			mockFetchSuccess(wrapped);

			const result = await getLogstashPipelines();

			expect(result).toHaveLength(2);
			expect(result[0].id).toBe('main');
			expect(result[1].id).toBe('beats');
		});

		it('calls the correct URL', async () => {
			mockFetchSuccess([]);

			await getLogstashPipelines();

			expect(fetch).toHaveBeenCalledWith('/api/logstash/pipelines');
		});

		it('returns empty array for unexpected response shape', async () => {
			mockFetchSuccess({ something: 'unexpected' });

			const result = await getLogstashPipelines();

			expect(result).toEqual([]);
		});

		it('returns empty array on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getLogstashPipelines();

			expect(result).toEqual([]);
		});

		it('returns empty array on network error', async () => {
			mockFetchReject();

			const result = await getLogstashPipelines();

			expect(result).toEqual([]);
		});
	});
});
