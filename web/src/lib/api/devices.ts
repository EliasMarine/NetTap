/**
 * Client-side API helpers for device inventory endpoints.
 * These functions call the SvelteKit server proxy routes which in turn
 * forward requests to the nettap-storage-daemon.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Time range options shared by all device queries. */
export interface TimeRangeParams {
	from?: string;
	to?: string;
}

export interface Device {
	ip: string;
	mac: string | null;
	hostname: string | null;
	manufacturer: string | null;
	os_hint: string | null;
	first_seen: string;
	last_seen: string;
	total_bytes: number;
	connection_count: number;
	protocols: string[];
	alert_count: number;
}

export interface DeviceListResponse {
	from: string;
	to: string;
	limit: number;
	devices: Device[];
}

export interface DeviceDestination {
	ip: string;
	bytes: number;
	connections: number;
}

export interface DeviceDNSQuery {
	domain: string;
	count: number;
}

export interface DeviceBandwidthPoint {
	timestamp: string;
	bytes: number;
	download_bytes?: number;
	upload_bytes?: number;
}

export interface DeviceDetail extends Device {
	top_destinations: DeviceDestination[];
	dns_queries: DeviceDNSQuery[];
	bandwidth_series: DeviceBandwidthPoint[];
	orig_bytes?: number;
	resp_bytes?: number;
	unique_destinations?: number;
	top_services?: Array<{ name: string; bytes: number; connections: number }>;
}

export interface DeviceDetailResponse {
	device: DeviceDetail;
}

export interface DeviceConnection {
	_id: string;
	_index: string;
	ts?: string;
	proto?: string;
	service?: string;
	[key: string]: unknown;
}

export interface DeviceConnectionsResponse {
	from: string;
	to: string;
	ip: string;
	page: number;
	size: number;
	total: number;
	total_pages: number;
	connections: DeviceConnection[];
}

export interface DeviceCategory {
	name: string;
	label: string;
	total_bytes: number;
	connection_count: number;
}

export interface DeviceCategoriesResponse {
	ip: string;
	from: string;
	to: string;
	categories: DeviceCategory[];
}

export interface DeviceAlert {
	timestamp: string;
	severity: number;
	signature: string;
	category: string;
	signature_id: number;
	source_ip: string;
	destination_ip: string;
	source_port?: number;
	destination_port?: number;
}

export interface DeviceAlertsResponse {
	ip: string;
	from: string;
	to: string;
	total: number;
	alerts: DeviceAlert[];
}

export interface DevicePort {
	port: number;
	service: string;
	connections: number;
	suspicious: boolean;
}

export interface DevicePortsResponse {
	ip: string;
	from: string;
	to: string;
	ports: DevicePort[];
}

export interface RiskFactor {
	name: string;
	score: number;
	max: number;
	description: string;
}

export interface RiskScoreResponse {
	ip: string;
	from: string;
	to: string;
	score: number;
	level: string;
	factors: RiskFactor[];
	connection_count: number;
	alert_count: number;
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

export interface DeviceCountResponse {
	from: string;
	to: string;
	count: number;
}

/**
 * Get count of unique DHCP-leased devices on the network.
 */
export async function getDeviceCount(
	opts: TimeRangeParams = {}
): Promise<DeviceCountResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/devices/count${query}`);

	if (!res.ok) {
		return { from: '', to: '', count: 0 };
	}

	return res.json();
}

/**
 * Get device inventory list with optional sorting and filtering.
 */
export async function getDevices(
	opts: TimeRangeParams & { sort?: string; order?: string; limit?: number } = {}
): Promise<DeviceListResponse> {
	const query = buildQuery({
		from: opts.from,
		to: opts.to,
		sort: opts.sort,
		order: opts.order,
		limit: opts.limit,
	});
	const res = await fetch(`/api/devices${query}`);

	if (!res.ok) {
		return {
			from: '',
			to: '',
			limit: opts.limit ?? 100,
			devices: [],
		};
	}

	return res.json();
}

/**
 * Get detailed information for a single device by IP address.
 */
export async function getDeviceDetail(
	ip: string,
	opts: TimeRangeParams = {}
): Promise<DeviceDetailResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/devices/${encodeURIComponent(ip)}${query}`);

	if (!res.ok) {
		return {
			device: {
				ip,
				mac: null,
				hostname: null,
				manufacturer: null,
				os_hint: null,
				first_seen: '',
				last_seen: '',
				total_bytes: 0,
				connection_count: 0,
				protocols: [],
				alert_count: 0,
				top_destinations: [],
				dns_queries: [],
				bandwidth_series: [],
			},
		};
	}

	return res.json();
}

/**
 * Get paginated connections for a specific device.
 */
export async function getDeviceConnections(
	ip: string,
	opts: TimeRangeParams & { page?: number; size?: number } = {}
): Promise<DeviceConnectionsResponse> {
	const query = buildQuery({
		from: opts.from,
		to: opts.to,
		page: opts.page,
		size: opts.size,
	});
	const res = await fetch(`/api/devices/${encodeURIComponent(ip)}/connections${query}`);

	if (!res.ok) {
		return {
			from: '',
			to: '',
			ip,
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
 * Get traffic categories for a specific device.
 */
export async function getDeviceCategories(
	ip: string,
	opts: TimeRangeParams = {}
): Promise<DeviceCategoriesResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/devices/${encodeURIComponent(ip)}/categories${query}`);
	if (!res.ok) return { ip, from: '', to: '', categories: [] };
	return res.json();
}

/**
 * Get alerts associated with a specific device.
 */
export async function getDeviceAlerts(
	ip: string,
	opts: TimeRangeParams & { limit?: number } = {}
): Promise<DeviceAlertsResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to, limit: opts.limit });
	const res = await fetch(`/api/devices/${encodeURIComponent(ip)}/alerts${query}`);
	if (!res.ok) return { ip, from: '', to: '', total: 0, alerts: [] };
	return res.json();
}

/**
 * Get port analysis for a specific device.
 */
export async function getDevicePorts(
	ip: string,
	opts: TimeRangeParams = {}
): Promise<DevicePortsResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/devices/${encodeURIComponent(ip)}/ports${query}`);
	if (!res.ok) return { ip, from: '', to: '', ports: [] };
	return res.json();
}

/**
 * Get the risk score for a specific device.
 */
export async function getDeviceRiskScore(
	ip: string,
	opts: TimeRangeParams = {}
): Promise<RiskScoreResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/risk/scores/${encodeURIComponent(ip)}${query}`);
	if (!res.ok) return { ip, from: '', to: '', score: 0, level: 'low', factors: [], connection_count: 0, alert_count: 0 };
	return res.json();
}
