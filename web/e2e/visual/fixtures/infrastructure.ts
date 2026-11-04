import type { OpenSearchCluster, getOpenSearchIndices } from '../../../src/lib/api/infrastructure.ts';
import { DAY, iso, type FixtureRoute } from './types.ts';

const GIB = 1024 ** 3;

/** GET /api/opensearch/cluster as the daemon sends it; the client copies total_size_bytes to total_data_size_bytes. */
interface DaemonCluster
	extends Pick<
		OpenSearchCluster,
		| 'status'
		| 'number_of_nodes'
		| 'active_primary_shards'
		| 'active_shards'
		| 'unassigned_shards'
		| 'relocating_shards'
		| 'total_docs'
	> {
	cluster_name: string;
	number_of_pending_tasks: number;
	total_indices: number;
	total_size_bytes: number;
}

/** One cat/templates row; every value is a string. */
interface DaemonTemplate {
	name: string;
	index_patterns: string;
	order: string;
	version: string;
}

interface DaemonTemplates {
	templates: DaemonTemplate[];
	count: number;
}

interface LogstashEvents {
	in: number;
	out: number;
	filtered: number;
	duration_in_millis: number;
}

/** GET /api/logstash/stats as the daemon sends it (Logstash's own nested names); the client flattens it. */
interface DaemonLogstashStats {
	available: true;
	jvm: { mem: { heap_used_in_bytes: number; heap_max_in_bytes: number; heap_used_percent: number } };
	process: { cpu: { percent: number } };
	pipelines: Record<string, { events: LogstashEvents }>;
	events: LogstashEvents;
}

interface DaemonLogstashPipeline {
	id: string;
	events: { in: number; out: number; filtered: number; duration_ms: number };
	plugins: Record<string, unknown>;
	reloads: Record<string, unknown>;
}

interface DaemonLogstashPipelines {
	pipelines: DaemonLogstashPipeline[];
	count: number;
}

type IndicesResponse = Awaited<ReturnType<typeof getOpenSearchIndices>>;

const CLUSTER_POPULATED = {
	cluster_name: 'nettap-opensearch',
	status: 'green',
	number_of_nodes: 1,
	active_primary_shards: 54,
	active_shards: 54,
	relocating_shards: 0,
	unassigned_shards: 0,
	number_of_pending_tasks: 0,
	total_indices: 54,
	total_docs: 48_213_907,
	total_size_bytes: Math.round(38.4 * GIB),
} satisfies DaemonCluster;

const CLUSTER_EMPTY = {
	cluster_name: 'nettap-opensearch',
	status: 'green',
	number_of_nodes: 1,
	active_primary_shards: 0,
	active_shards: 0,
	relocating_shards: 0,
	unassigned_shards: 0,
	number_of_pending_tasks: 0,
	total_indices: 0,
	total_docs: 0,
	total_size_bytes: 0,
} satisfies DaemonCluster;

function index(name: string, docs: number, size: string, daysAgo: number, health = 'green') {
	return {
		index: name,
		health,
		status: 'open',
		docs_count: String(docs),
		pri_store_size: size,
		store_size: size,
		creation_date: iso(daysAgo * DAY),
	};
}

const INDICES_POPULATED = {
	indices: [
		index('.opendistro_security', 10, '63.4kb', 12),
		index('.kibana_1', 42, '211.7kb', 12),
		index('arkime_sessions3-261101', 8_412_330, '6.1gb', 2),
		index('arkime_sessions3-261102', 9_033_518, '6.6gb', 1),
		index('arkime_sessions3-261103', 2_948_071, '2.2gb', 0),
		index('malcolm_beats_zeek_261102', 14_882_904, '4.3gb', 1),
		index('malcolm_beats_suricata_261102', 41_208, '38.9mb', 1),
		index('malcolm_beats_zeek_261103', 5_006_127, '1.5gb', 0, 'yellow'),
	],
	count: 8,
} satisfies IndicesResponse;

const INDICES_EMPTY = { indices: [], count: 0 } satisfies IndicesResponse;

const TEMPLATES_POPULATED = {
	templates: [
		{ name: 'malcolm_template', index_patterns: '[arkime_sessions3-*, malcolm_beats_*]', order: '0', version: '1' },
		{ name: 'arkime_sessions3_template', index_patterns: '[arkime_sessions3-*]', order: '0', version: '75' },
		{ name: 'ecs-legacy', index_patterns: '[logs-*]', order: '0', version: '' },
	],
	count: 3,
} satisfies DaemonTemplates;

const TEMPLATES_EMPTY = { templates: [], count: 0 } satisfies DaemonTemplates;

function events(inCount: number, durationMs: number): LogstashEvents {
	return { in: inCount, out: inCount, filtered: inCount, duration_in_millis: durationMs };
}

const LOGSTASH_STATS_POPULATED = {
	available: true,
	jvm: { mem: { heap_used_in_bytes: 612 * 1024 ** 2, heap_max_in_bytes: 1024 ** 3, heap_used_percent: 60 } },
	process: { cpu: { percent: 14 } },
	pipelines: {
		'malcolm-beats': { events: events(21_904_117, 9_412_220) },
		'malcolm-output': { events: events(21_904_117, 6_208_906) },
	},
	events: events(21_904_117, 15_621_126),
} satisfies DaemonLogstashStats;

/** Running but nothing shipped yet: the page reads this as Idle. */
const LOGSTASH_STATS_EMPTY = {
	available: true,
	jvm: { mem: { heap_used_in_bytes: 268 * 1024 ** 2, heap_max_in_bytes: 1024 ** 3, heap_used_percent: 26 } },
	process: { cpu: { percent: 2 } },
	pipelines: {},
	events: events(0, 0),
} satisfies DaemonLogstashStats;

function pipeline(id: string, inCount: number, durationMs: number): DaemonLogstashPipeline {
	return {
		id,
		events: { in: inCount, out: inCount, filtered: inCount, duration_ms: durationMs },
		plugins: {},
		reloads: {},
	};
}

const LOGSTASH_PIPELINES_POPULATED = {
	pipelines: [
		pipeline('malcolm-beats', 21_904_117, 9_412_220),
		pipeline('malcolm-enrichment', 21_904_117, 3_120_448),
		pipeline('malcolm-output', 21_904_117, 6_208_906),
	],
	count: 3,
} satisfies DaemonLogstashPipelines;

const LOGSTASH_PIPELINES_EMPTY = { pipelines: [], count: 0 } satisfies DaemonLogstashPipelines;

export const INFRASTRUCTURE_ROUTES: FixtureRoute[] = [
	{ path: '/api/opensearch/cluster', empty: CLUSTER_EMPTY, populated: CLUSTER_POPULATED },
	{ path: '/api/opensearch/indices', empty: INDICES_EMPTY, populated: INDICES_POPULATED },
	{ path: '/api/opensearch/templates', empty: TEMPLATES_EMPTY, populated: TEMPLATES_POPULATED },
	{ path: '/api/logstash/stats', empty: LOGSTASH_STATS_EMPTY, populated: LOGSTASH_STATS_POPULATED },
	{ path: '/api/logstash/pipelines', empty: LOGSTASH_PIPELINES_EMPTY, populated: LOGSTASH_PIPELINES_POPULATED },
];
