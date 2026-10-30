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
			// Shape of daemon/api/opensearch_cluster.py handle_cluster_health:
			// cluster.health fields + total_indices/total_docs/total_size_bytes
			mockFetchSuccess({
				status: 'green',
				number_of_nodes: 1,
				active_primary_shards: 5,
				active_shards: 5,
				unassigned_shards: 0,
				relocating_shards: 0,
				number_of_pending_tasks: 0,
				total_indices: 12,
				total_docs: 123456,
				total_size_bytes: 99887766,
			});

			const result = await getOpenSearchCluster();

			expect(result.status).toBe('green');
			expect(result.number_of_nodes).toBe(1);
			expect(result.active_primary_shards).toBe(5);
			expect(result.total_docs).toBe(123456);
			expect(result.total_data_size_bytes).toBe(99887766);
		});

		it('defaults the data size to 0 when the daemon omits it', async () => {
			mockFetchSuccess({ status: 'yellow' });

			const result = await getOpenSearchCluster();

			expect(result.total_data_size_bytes).toBe(0);
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
		it('unwraps the daemon { templates, count } envelope', async () => {
			mockFetchSuccess({
				templates: [
					{ name: 'zeek_template', index_patterns: '[zeek-*]', order: '0', version: '' },
					{ name: 'suricata_template', index_patterns: '[suricata-*]', order: '0', version: '' },
				],
				count: 2,
			});

			const result = await getOpenSearchTemplates();

			expect(result).toHaveLength(2);
			expect(result[0]).toMatchObject({ name: 'zeek_template' });
		});

		it('calls the correct URL', async () => {
			mockFetchSuccess({ templates: [], count: 0 });

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
		/** Shape of daemon/api/logstash.py handle_logstash_pipelines entries */
		function daemonPipeline(id: string, inN: number, out: number, filtered: number, ms: number) {
			return {
				id,
				events: { in: inN, out, filtered, duration_ms: ms },
				plugins: {},
				reloads: { successes: 0, failures: 0 },
			};
		}

		it('flattens nested events into the pipeline fields', async () => {
			mockFetchSuccess({ pipelines: [daemonPipeline('main', 5000, 4500, 500, 6000)], count: 1 });

			const result = await getLogstashPipelines();

			expect(result).toHaveLength(1);
			expect(result[0]).toMatchObject({
				id: 'main',
				events_in: 5000,
				events_out: 4500,
				events_filtered: 500,
				duration_in_millis: 6000,
			});
		});

		it('unwraps { pipelines: [...] } envelope', async () => {
			mockFetchSuccess({
				pipelines: [daemonPipeline('main', 3000, 2800, 200, 4000), daemonPipeline('beats', 1000, 1000, 0, 500)],
				count: 2,
			});

			const result = await getLogstashPipelines();

			expect(result).toHaveLength(2);
			expect(result[0].id).toBe('main');
			expect(result[1].id).toBe('beats');
			expect(result[1].duration_in_millis).toBe(500);
		});

		it('zeroes missing event counters', async () => {
			mockFetchSuccess({ pipelines: [{ id: 'empty' }], count: 1 });

			const [p] = await getLogstashPipelines();

			expect(p).toMatchObject({ events_in: 0, events_out: 0, events_filtered: 0, duration_in_millis: 0 });
		});

		it('calls the correct URL', async () => {
			mockFetchSuccess({ pipelines: [], count: 0 });

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
