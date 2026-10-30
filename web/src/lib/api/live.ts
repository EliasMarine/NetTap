/**
 * Client-side API helpers for live connection monitoring endpoints.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface LiveConnection {
	timestamp: string;
	source_ip: string;
	source_port: number;
	dest_ip: string;
	dest_port: number;
	protocol: string;
	service: string;
	bytes: number;
	duration: number;
	country: string;
	country_name: string;
	device_name: string;
	dest_lat: number | null;
	dest_lon: number | null;
	dest_city: string;
	dest_asn: number | null;
	dest_org: string;
	has_alert: boolean;
}

export interface LiveConnectionsResponse {
	connections: LiveConnection[];
	count: number;
	filters: {
		device: string | null;
		proto: string | null;
		country: string | null;
	};
}

export interface ConnectionRate {
	connections_per_second: number;
	total_in_window: number;
	window_seconds: number;
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
 * Get a snapshot of active connections.
 */
export async function getLiveConnections(
	opts: { device?: string; proto?: string; country?: string; limit?: number } = {}
): Promise<LiveConnectionsResponse> {
	const query = buildQuery({
		device: opts.device,
		proto: opts.proto,
		country: opts.country,
		limit: opts.limit,
	});
	const res = await fetch(`/api/live/connections${query}`);

	if (!res.ok) {
		return {
			connections: [],
			count: 0,
			filters: { device: null, proto: null, country: null },
		};
	}

	return res.json();
}

/**
 * Get the current connection rate.
 */
export async function getConnectionRate(): Promise<ConnectionRate> {
	const res = await fetch('/api/live/rate');

	if (!res.ok) {
		return {
			connections_per_second: 0,
			total_in_window: 0,
			window_seconds: 60,
		};
	}

	return res.json();
}

// ---------------------------------------------------------------------------
// Dashboard types (consolidated endpoint)
// ---------------------------------------------------------------------------

export interface DashboardStats {
	connections_per_second: number;
	bandwidth_bytes_per_second: number;
	active_devices: number;
	top_country: string;
}

export interface GeoArc {
	city: string;
	country: string;
	country_code: string;
	lat: number;
	lon: number;
	count: number;
	bytes: number;
}

export interface TopTalker {
	ip: string;
	bytes: number;
	connections: number;
}

export interface LiveDashboardResponse {
	connections: LiveConnection[];
	count: number;
	stats: DashboardStats;
	protocols: Record<string, number>;
	top_talkers: TopTalker[];
	geo_arcs: GeoArc[];
	_error?: string;
}

export interface ConnectionDetailAlert {
	timestamp: string;
	signature: string;
	severity: number;
	category: string;
}

export interface ConnectionDetailHistory {
	total_bytes: number;
	connection_count: number;
	timeline: { timestamp: string; bytes: number; connections: number }[];
}

export interface ConnectionDetailResponse {
	geo: {
		ip: string;
		country: string;
		country_code: string;
		city: string;
		lat: number | null;
		lon: number | null;
		asn: number | null;
		organization: string;
	};
	alerts: ConnectionDetailAlert[];
	alert_count: number;
	history: ConnectionDetailHistory;
}

// ---------------------------------------------------------------------------
// Dashboard fetch helpers
// ---------------------------------------------------------------------------

/**
 * Consolidated live dashboard data — single request for all widgets.
 */
export async function getLiveDashboard(
	opts: { device?: string; proto?: string; country?: string; limit?: number } = {}
): Promise<LiveDashboardResponse> {
	const query = buildQuery({
		device: opts.device,
		proto: opts.proto,
		country: opts.country,
		limit: opts.limit,
	});
	const res = await fetch(`/api/live/dashboard${query}`);

	if (!res.ok) {
		return {
			connections: [],
			count: 0,
			stats: { connections_per_second: 0, bandwidth_bytes_per_second: 0, active_devices: 0, top_country: '' },
			protocols: {},
			top_talkers: [],
			geo_arcs: [],
			_error: `Dashboard API returned ${res.status}`,
		};
	}

	return res.json();
}

/**
 * Get detailed info for a specific connection pair (for the detail drawer).
 */
export async function getLiveConnectionDetail(
	src: string,
	dst: string,
	port?: number
): Promise<ConnectionDetailResponse> {
	const query = buildQuery({ src, dst, port });
	const res = await fetch(`/api/live/connection/detail${query}`);

	if (!res.ok) {
		return {
			geo: { ip: dst, country: '', country_code: '', city: '', lat: null, lon: null, asn: null, organization: '' },
			alerts: [],
			alert_count: 0,
			history: { total_bytes: 0, connection_count: 0, timeline: [] },
		};
	}

	return res.json();
}
