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
