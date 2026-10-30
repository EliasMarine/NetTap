/**
 * Client-side API helpers for traffic monitoring endpoints.
 * These functions call the SvelteKit server proxy routes which in turn
 * forward requests to the nettap-storage-daemon.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Time range options shared by all traffic queries. */
export interface TimeRangeParams {
	from?: string;
	to?: string;
}

export interface TrafficSummary {
	from: string;
	to: string;
	total_bytes: number;
	orig_bytes: number;
	resp_bytes: number;
	packet_count: number;
	connection_count: number;
	top_protocol: string;
}

export interface TopTalker {
	ip: string;
	total_bytes: number;
	connection_count: number;
}

export interface TopTalkersResponse {
	from: string;
	to: string;
	limit: number;
	top_talkers: TopTalker[];
}

export interface TopDestination {
	ip: string;
	total_bytes: number;
	connection_count: number;
}

export interface TopDestinationsResponse {
	from: string;
	to: string;
	limit: number;
	top_destinations: TopDestination[];
}

export interface ProtocolEntry {
	name: string;
	count: number;
}

export interface ProtocolsResponse {
	from: string;
	to: string;
	protocols: ProtocolEntry[];
	services: ProtocolEntry[];
}

export interface BandwidthPoint {
	timestamp: string;
	orig_bytes: number;
	resp_bytes: number;
	total_bytes: number;
	connections: number;
}

export interface BandwidthResponse {
	from: string;
	to: string;
	interval: string;
	series: BandwidthPoint[];
}

// OLD CODE START — domain-based type replaced by ASN-based top_services
// export interface TrafficCategoryDomain {
// 	domain: string;
// 	count: number;
// }
// OLD CODE END

export interface TrafficCategoryService {
	name: string;
	bytes: number;
	connections?: number;
}

export interface TrafficCategory {
	name: string;
	label: string;
	total_bytes: number;
	connection_count: number;
	top_services: TrafficCategoryService[];
}

export interface CategoriesResponse {
	from: string;
	to: string;
	categories: TrafficCategory[];
}

export interface CategoryDevice {
	ip: string;
	hostname?: string;
	total_bytes: number;
	download_bytes: number;
	upload_bytes: number;
	connections: number;
	percent: number;
}

export interface CategoryDetailResponse {
	category: string;
	label: string;
	device_count: number;
	total_bytes: number;
	connection_count: number;
	devices: CategoryDevice[];
	services: TrafficCategoryService[];
}

export interface CategoryBandwidthPoint {
	timestamp: string;
	download_bytes: number;
	upload_bytes: number;
	total_bytes: number;
	connections: number;
}

export interface CategoryBandwidthResponse {
	category: string;
	from: string;
	to: string;
	interval: string;
	series: CategoryBandwidthPoint[];
}

export interface Connection {
	_id: string;
	_index: string;
	/** ECS fields from OpenSearch _source */
	'@timestamp'?: string;
	source?: { ip?: string; port?: number; bytes?: number; packets?: number; as?: { full?: string }; geo?: { country_iso_code?: string; country_name?: string } };
	destination?: { ip?: string; port?: number; bytes?: number; packets?: number; as?: { full?: string }; geo?: { country_iso_code?: string; country_name?: string } };
	client?: { bytes?: number };
	server?: { bytes?: number };
	network?: { transport?: string; protocol?: string; community_id?: string };
	event?: { duration?: number };
	zeek?: { session_id?: string; conn?: { state?: string; history?: string } };
	[key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Connections v3 types
// ---------------------------------------------------------------------------

export interface ConnectionStatsSource {
	ip: string;
	total_bytes: number;
	connections: number;
}

export interface ConnectionStatsDestination {
	ip: string;
	total_bytes: number;
	connections: number;
	asn: string;
	country: string;
}

export interface ConnectionStatsResponse {
	from: string;
	to: string;
	total_sessions: number;
	bytes_in: number;
	bytes_out: number;
	alert_sessions: number;
	protocols: ProtocolEntry[];
	top_sources: ConnectionStatsSource[];
	top_destinations: ConnectionStatsDestination[];
}

export interface SankeyNode {
	id: string;
	label: string;
	value: number;
	country?: string;
}

export interface SankeyLink {
	source: string;
	target: string;
	value: number;
}

export interface SankeyResponse {
	from: string;
	to: string;
	nodes: {
		sources: SankeyNode[];
		protocols: SankeyNode[];
		destinations: SankeyNode[];
	};
	links: SankeyLink[];
}

export interface ConnectionTimelineBucket {
	timestamp: string;
	total: number;
	protocols: Record<string, number>;
}

export interface ConnectionTimelineResponse {
	from: string;
	to: string;
	interval: string;
	buckets: ConnectionTimelineBucket[];
}

export interface RelatedConnectionsResponse {
	from: string;
	to: string;
	src_ip: string;
	dst_ip: string;
	total_connections: number;
	total_bytes: number;
	protocols: string[];
	first_seen: string | null;
	last_seen: string | null;
	connections: Connection[];
}

export interface ConnectionsResponse {
	from: string;
	to: string;
	page: number;
	size: number;
	total: number;
	total_pages: number;
	connections: Connection[];
}

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function buildQuery(params: Record<string, string | number | undefined>): string {
	const qs = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (value !== undefined && value !== '') {
			qs.set(key, String(value));
		}
	}
	const str = qs.toString();
	return str ? `?${str}` : '';
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

/**
 * Get traffic summary for a time range (defaults to last 24h on the daemon).
 */
export async function getTrafficSummary(
	opts: TimeRangeParams = {}
): Promise<TrafficSummary> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/traffic/summary${query}`);

	if (!res.ok) {
		return {
			from: '',
			to: '',
			total_bytes: 0,
			orig_bytes: 0,
			resp_bytes: 0,
			packet_count: 0,
			connection_count: 0,
			top_protocol: 'unknown',
		};
	}

	return res.json();
}

/**
 * Get top source IPs by total bytes.
 */
export async function getTopTalkers(
	opts: TimeRangeParams & { limit?: number } = {}
): Promise<TopTalkersResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to, limit: opts.limit });
	const res = await fetch(`/api/traffic/top-talkers${query}`);

	if (!res.ok) {
		return { from: '', to: '', limit: opts.limit ?? 20, top_talkers: [] };
	}

	return res.json();
}

/**
 * Get top destination IPs by total bytes.
 */
export async function getTopDestinations(
	opts: TimeRangeParams & { limit?: number } = {}
): Promise<TopDestinationsResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to, limit: opts.limit });
	const res = await fetch(`/api/traffic/top-destinations${query}`);

	if (!res.ok) {
		return { from: '', to: '', limit: opts.limit ?? 20, top_destinations: [] };
	}

	return res.json();
}

/**
 * Get protocol and service distribution.
 */
export async function getProtocolDistribution(
	opts: TimeRangeParams = {}
): Promise<ProtocolsResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/traffic/protocols${query}`);

	if (!res.ok) {
		return { from: '', to: '', protocols: [], services: [] };
	}

	return res.json();
}

/**
 * Get bandwidth time-series data.
 * @param opts.interval - Bucket interval (e.g. '5m', '1h', '1d')
 */
export async function getBandwidthTimeSeries(
	opts: TimeRangeParams & { interval?: string } = {}
): Promise<BandwidthResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to, interval: opts.interval });
	const res = await fetch(`/api/traffic/bandwidth${query}`);

	if (!res.ok) {
		return { from: '', to: '', interval: opts.interval ?? '5m', series: [] };
	}

	return res.json();
}

/**
 * Get paginated connection list with optional search.
 */
export async function getConnections(
	opts: TimeRangeParams & { page?: number; size?: number; q?: string } = {}
): Promise<ConnectionsResponse> {
	const query = buildQuery({
		from: opts.from,
		to: opts.to,
		page: opts.page,
		size: opts.size,
		q: opts.q,
	});
	const res = await fetch(`/api/traffic/connections${query}`);

	if (!res.ok) {
		return {
			from: '',
			to: '',
			page: opts.page ?? 1,
			size: opts.size ?? 50,
			total: 0,
			total_pages: 0,
			connections: [],
		};
	}

	return res.json();
}

/**
 * Get traffic breakdown by human-readable categories (Streaming, Gaming, etc.).
 */
export async function getTrafficCategories(
	opts: TimeRangeParams = {}
): Promise<CategoriesResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/traffic/categories${query}`);

	if (!res.ok) {
		return { from: '', to: '', categories: [] };
	}

	return res.json();
}

/**
 * Get detailed breakdown for a single traffic category, listing per-device usage.
 */
export async function getCategoryDetail(
	category: string,
	opts: TimeRangeParams = {}
): Promise<CategoryDetailResponse> {
	const q = buildQuery(opts as Record<string, string | number | undefined>);
	const url = `/api/traffic/categories/${encodeURIComponent(category)}${q}`;
	try {
		const res = await fetch(url, { signal: AbortSignal.timeout(15_000) });
		if (!res.ok) throw new Error(`${res.status}`);
		return await res.json();
	} catch (err) {
		console.error('[getCategoryDetail] fetch failed for', category, err);
		return {
			category,
			label: category,
			device_count: 0,
			total_bytes: 0,
			connection_count: 0,
			devices: [],
			services: [],
		};
	}
}

/**
 * Get bandwidth time-series for a specific traffic category.
 */
export async function getCategoryBandwidth(
	category: string,
	opts: TimeRangeParams & { interval?: string } = {}
): Promise<CategoryBandwidthResponse> {
	const q = buildQuery(opts as Record<string, string | number | undefined>);
	const url = `/api/traffic/categories/${encodeURIComponent(category)}/bandwidth${q}`;
	try {
		const res = await fetch(url, { signal: AbortSignal.timeout(15_000) });
		if (!res.ok) throw new Error(`${res.status}`);
		return await res.json();
	} catch (err) {
		console.error('[getCategoryBandwidth] fetch failed for', category, err);
		return {
			category,
			from: '',
			to: '',
			interval: opts.interval ?? '15m',
			series: [],
		};
	}
}

// ---------------------------------------------------------------------------
// Connections v3 fetch functions
// ---------------------------------------------------------------------------

/**
 * Get aggregated connection statistics (stat cards + analytics data).
 */
export async function getConnectionStats(
	opts: TimeRangeParams = {}
): Promise<ConnectionStatsResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/traffic/connections/stats${query}`);
	if (!res.ok) {
		return {
			from: '', to: '', total_sessions: 0, bytes_in: 0, bytes_out: 0,
			alert_sessions: 0, protocols: [], top_sources: [], top_destinations: [],
		};
	}
	return res.json();
}

/**
 * Get Sankey diagram data (source IPs → protocols → destination orgs).
 */
export async function getConnectionSankey(
	opts: TimeRangeParams & { limit?: number } = {}
): Promise<SankeyResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to, limit: opts.limit });
	const res = await fetch(`/api/traffic/connections/sankey${query}`);
	if (!res.ok) {
		return {
			from: '', to: '',
			nodes: { sources: [], protocols: [], destinations: [] },
			links: [],
		};
	}
	return res.json();
}

/**
 * Get connection timeline (session count by protocol over time).
 */
export async function getConnectionTimeline(
	opts: TimeRangeParams & { interval?: string } = {}
): Promise<ConnectionTimelineResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to, interval: opts.interval });
	const res = await fetch(`/api/traffic/connections/timeline${query}`);
	if (!res.ok) {
		return { from: '', to: '', interval: opts.interval ?? '15m', buckets: [] };
	}
	return res.json();
}

/**
 * Get all connections between a specific source-destination pair.
 */
export async function getRelatedConnections(
	srcIp: string,
	dstIp: string,
	opts: TimeRangeParams = {}
): Promise<RelatedConnectionsResponse> {
	const query = buildQuery({ src_ip: srcIp, dst_ip: dstIp, from: opts.from, to: opts.to });
	const res = await fetch(`/api/traffic/connections/related${query}`);
	if (!res.ok) {
		return {
			from: '', to: '', src_ip: srcIp, dst_ip: dstIp,
			total_connections: 0, total_bytes: 0, protocols: [],
			first_seen: null, last_seen: null, connections: [],
		};
	}
	return res.json();
}
