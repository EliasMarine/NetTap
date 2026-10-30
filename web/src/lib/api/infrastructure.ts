/**
 * Client-side API helpers for infrastructure monitoring endpoints.
 * Wraps GET /api/opensearch/cluster, /api/opensearch/indices, /api/opensearch/templates,
 *        GET /api/logstash/stats, /api/logstash/pipelines.
 *
 * The catch-all proxy at web/src/routes/api/[...path]/+server.ts forwards all
 * /api/* requests to the nettap-storage-daemon — no new proxy routes are needed.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface OpenSearchCluster {
	status: string; // 'green' | 'yellow' | 'red'
	number_of_nodes: number;
	active_primary_shards: number;
	active_shards: number;
	unassigned_shards: number;
	relocating_shards: number;
	pending_tasks: number;
	total_docs: number;
	total_data_size_bytes: number;
	[key: string]: unknown;
}

export interface OpenSearchIndex {
	index: string;
	health: string;
	status: string;
	docs_count: number | string;
	pri_store_size: string;
	store_size: string;
	creation_date: string | null;
	[key: string]: unknown;
}

export interface LogstashStats {
	events_in: number;
	events_out: number;
	events_filtered: number;
	events_duration_millis: number;
	heap_used_bytes: number;
	heap_max_bytes: number;
	heap_used_percent: number;
	cpu_percent: number;
	[key: string]: unknown;
}

export interface LogstashPipeline {
	id: string;
	events_in: number;
	events_out: number;
	events_filtered: number;
	duration_in_millis: number;
	[key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Defaults
// ---------------------------------------------------------------------------

const DEFAULT_CLUSTER: OpenSearchCluster = {
	status: 'red',
	number_of_nodes: 0,
	active_primary_shards: 0,
	active_shards: 0,
	unassigned_shards: 0,
	relocating_shards: 0,
	pending_tasks: 0,
	total_docs: 0,
	total_data_size_bytes: 0,
};

const DEFAULT_LOGSTASH_STATS: LogstashStats = {
	events_in: 0,
	events_out: 0,
	events_filtered: 0,
	events_duration_millis: 0,
	heap_used_bytes: 0,
	heap_max_bytes: 0,
	heap_used_percent: 0,
	cpu_percent: 0,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Normalise a Logstash stats response that may use either nested
 * (`events.in`, `jvm.mem.heap_used_in_bytes`) or flat (`events_in`,
 * `heap_used_bytes`) field names into the flat LogstashStats shape.
 */
function normaliseLogstashStats(raw: Record<string, unknown>): LogstashStats {
	// Helper to reach into a nested object by dot-path
	function dig(obj: Record<string, unknown>, path: string): unknown {
		return path.split('.').reduce<unknown>((cur, key) => {
			if (cur && typeof cur === 'object' && key in (cur as Record<string, unknown>)) {
				return (cur as Record<string, unknown>)[key];
			}
			return undefined;
		}, obj);
	}

	function num(value: unknown): number {
		return typeof value === 'number' ? value : 0;
	}

	return {
		events_in: num(raw.events_in ?? dig(raw, 'events.in')),
		events_out: num(raw.events_out ?? dig(raw, 'events.out')),
		events_filtered: num(raw.events_filtered ?? dig(raw, 'events.filtered')),
		events_duration_millis: num(
			raw.events_duration_millis ?? dig(raw, 'events.duration_in_millis'),
		),
		heap_used_bytes: num(raw.heap_used_bytes ?? dig(raw, 'jvm.mem.heap_used_in_bytes')),
		heap_max_bytes: num(raw.heap_max_bytes ?? dig(raw, 'jvm.mem.heap_max_in_bytes')),
		heap_used_percent: num(
			raw.heap_used_percent ?? dig(raw, 'jvm.mem.heap_used_percent'),
		),
		cpu_percent: num(raw.cpu_percent ?? dig(raw, 'process.cpu.percent')),
	};
}

// ---------------------------------------------------------------------------
// OpenSearch fetch helpers
// ---------------------------------------------------------------------------

/**
 * Get the OpenSearch cluster health summary.
 */
export async function getOpenSearchCluster(): Promise<OpenSearchCluster> {
	try {
		const res = await fetch('/api/opensearch/cluster');
		if (!res.ok) {
			return { ...DEFAULT_CLUSTER };
		}
		return res.json();
	} catch {
		return { ...DEFAULT_CLUSTER };
	}
}

/**
 * Get the list of OpenSearch indices with doc counts and sizes.
 */
export async function getOpenSearchIndices(): Promise<{ indices: OpenSearchIndex[]; count: number }> {
	try {
		const res = await fetch('/api/opensearch/indices');
		if (!res.ok) {
			return { indices: [], count: 0 };
		}
		return res.json();
	} catch {
		return { indices: [], count: 0 };
	}
}

/**
 * Get the list of OpenSearch index templates.
 */
export async function getOpenSearchTemplates(): Promise<unknown[]> {
	try {
		const res = await fetch('/api/opensearch/templates');
		if (!res.ok) {
			return [];
		}
		const data = await res.json();
		return Array.isArray(data) ? data : [];
	} catch {
		return [];
	}
}

// ---------------------------------------------------------------------------
// Logstash fetch helpers
// ---------------------------------------------------------------------------

/**
 * Get Logstash node stats (event throughput, JVM heap, CPU).
 * Handles both flat (`events_in`) and nested (`events.in`) response formats.
 */
export async function getLogstashStats(): Promise<LogstashStats> {
	try {
		const res = await fetch('/api/logstash/stats');
		if (!res.ok) {
			return { ...DEFAULT_LOGSTASH_STATS };
		}
		const raw = await res.json();
		return normaliseLogstashStats(raw);
	} catch {
		return { ...DEFAULT_LOGSTASH_STATS };
	}
}

/**
 * Get Logstash pipeline details.
 * The daemon may return `{ pipelines: [...] }` or a bare array.
 */
export async function getLogstashPipelines(): Promise<LogstashPipeline[]> {
	try {
		const res = await fetch('/api/logstash/pipelines');
		if (!res.ok) {
			return [];
		}
		const data = await res.json();
		if (Array.isArray(data)) {
			return data;
		}
		if (data && Array.isArray(data.pipelines)) {
			return data.pipelines;
		}
		return [];
	} catch {
		return [];
	}
}
