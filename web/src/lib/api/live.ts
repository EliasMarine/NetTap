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
	/**
	 * The place fields (country, country_name and the dest_* geo/AS fields) describe the remote end: the
	 * destination, or the source when only the source has a country (an inbound row). geo_ip says which.
	 */
	country: string;
	country_name: string;
	device_name: string;
	dest_lat: number | null;
	dest_lon: number | null;
	dest_city: string;
	dest_asn: number | null;
	dest_org: string;
	/** The address the place belongs to (source_ip or dest_ip); '' when neither end was located. Absent from older daemons. */
	geo_ip?: string;
	has_alert: boolean;
	/** From the daemon's LAN subnets (O2); absent from /api/live/connections and older daemons. */
	direction?: ConnectionDirection;
	/**
	 * NET-237 (TRF-1): when the connection ended, ISO UTC ('' if unknown). Zeek logs a connection when
	 * it closes, so the live window and feed go by this; `timestamp` is its start. Absent from older daemons.
	 */
	ended_at?: string;
}

/** Where a connection runs relative to the LAN: the daemon decides, never the port. */
export type ConnectionDirection = 'out' | 'in' | 'local' | 'unknown';

const DIRECTION_LABELS: Record<ConnectionDirection, string> = { out: 'Out', in: 'In', local: 'Local', unknown: 'Unknown' };

/** The connection's direction as a word; one the daemon didn't send reads "Unknown". */
export function directionLabel(c: Pick<LiveConnection, 'direction'>): string {
	return DIRECTION_LABELS[c.direction ?? 'unknown'] ?? DIRECTION_LABELS.unknown;
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

	// OLD CODE START — #96: a failed request read as 0 active connections
	// if (!res.ok) {
	// 	return {
	// 		connections: [],
	// 		count: 0,
	// 		filters: { device: null, proto: null, country: null },
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Live connections failed: HTTP ${res.status}`);

	return res.json();
}

/**
 * Get the current connection rate.
 */
export async function getConnectionRate(): Promise<ConnectionRate> {
	const res = await fetch('/api/live/rate');

	// OLD CODE START — #96: a failed request read as 0 connections per second
	// if (!res.ok) {
	// 	return {
	// 		connections_per_second: 0,
	// 		total_in_window: 0,
	// 		window_seconds: 60,
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Connection rate failed: HTTP ${res.status}`);

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
	/** Connections in the 5-minute window (the protocol donut's total) */
	connections_in_window?: number;
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
	/** The stored rule.category values (NET-160 slice 2b-2): the category links only when it is one of them */
	rule_category?: string[];
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

	// OLD CODE START — #96: a failed request replaced the live view with zeros
	// if (!res.ok) {
	// 	return {
	// 		connections: [],
	// 		count: 0,
	// 		stats: { connections_per_second: 0, bandwidth_bytes_per_second: 0, active_devices: 0, top_country: '' },
	// 		protocols: {},
	// 		top_talkers: [],
	// 		geo_arcs: [],
	// 		_error: `Dashboard API returned ${res.status}`,
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Live dashboard failed: HTTP ${res.status}`);

	return res.json();
}

/**
 * Get detailed info for a specific connection pair (for the detail drawer).
 */
export async function getLiveConnectionDetail(
	src: string,
	dst: string,
	port?: number,
	/** The end to locate (the row's geo_ip); the daemon takes dst when absent. */
	geo?: string
): Promise<ConnectionDetailResponse> {
	const query = buildQuery({ src, dst, port, geo });
	const res = await fetch(`/api/live/connection/detail${query}`);

	// OLD CODE START — #96: a failed request read as "No alerts for this connection"
	// if (!res.ok) {
	// 	return {
	// 		geo: { ip: dst, country: '', country_code: '', city: '', lat: null, lon: null, asn: null, organization: '' },
	// 		alerts: [],
	// 		alert_count: 0,
	// 		history: { total_bytes: 0, connection_count: 0, timeline: [] },
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Connection detail failed: HTTP ${res.status}`);

	return res.json();
}
