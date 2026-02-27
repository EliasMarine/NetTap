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

export interface TrafficCategoryDomain {
	domain: string;
	count: number;
}

export interface TrafficCategory {
	name: string;
	label: string;
	total_bytes: number;
	connection_count: number;
	top_domains: TrafficCategoryDomain[];
}

export interface CategoriesResponse {
	from: string;
	to: string;
	categories: TrafficCategory[];
}

export interface Connection {
	_id: string;
	_index: string;
	ts?: string;
	proto?: string;
	service?: string;
	[key: string]: unknown;
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
