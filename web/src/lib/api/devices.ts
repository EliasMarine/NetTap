/**
 * Client-side API helpers for device inventory endpoints.
 * These functions call the SvelteKit server proxy routes which in turn
 * forward requests to the nettap-storage-daemon.
 */

import type { Ipv6LeftOutReason } from '$lib/utils/ipv6-coverage';
import type { GuessBasis } from '$lib/utils/device-guess';

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
	// OLD CODE START — NET-226: connections the device started only
	// /** Bytes the device sent (sum of source.bytes). */
	// orig_bytes?: number;
	// /** Bytes the device received (sum of destination.bytes). */
	// resp_bytes?: number;
	// OLD CODE END
	/** NET-226: bytes the device sent and received, on connections it started and answered, IPv4 and IPv6 */
	upload_bytes?: number;
	download_bytes?: number;
	/** Connections it started and answered, IPv6 included */
	connection_count: number;
	/** Of connection_count, those over IPv6 (matched to the device by its MAC) */
	ipv6_connections?: number;
	/** IPv6 connections not counted, and why (ipv6-coverage.ts) */
	ipv6_left_out?: number;
	ipv6_left_out_reason?: Ipv6LeftOutReason | null;
	protocols: string[];
	alert_count: number;
	category?: string;
	/** What the type was guessed from (device-guess.ts); null when it is unknown */
	category_basis?: GuessBasis | null;
	/** What the OS was guessed from */
	os_basis?: string | null;
	unifi_name?: string;
	/** NET-200: the owner's name, picked icon and photo URL; `hostname` already carries the name */
	custom_name?: string | null;
	/** NET-200: the hostname before the owner's name replaced it (sent only when it did) */
	discovered_name?: string | null;
	icon?: string | null;
	picture?: string | null;
}

export interface DeviceListResponse {
	from: string;
	to: string;
	limit: number;
	devices: Device[];
	/** Devices before the limit cut: the same set /api/devices/count counts over this window (NET-160 slice 2b-3). */
	total: number;
	/** The daemon's clock when it answered, ISO with exactly three fractional digits. */
	as_of: string;
	/** `as_of` minus exactly 5 minutes, same format: a device last seen at or after it is online. */
	online_since: string;
	/** Devices before the cut whose `last_seen` is at or after `online_since`. */
	online_total: number;
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
	// OLD CODE START — NET-226: upload_bytes/download_bytes on Device now
	// orig_bytes?: number;
	// resp_bytes?: number;
	// OLD CODE END
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
	/** From the device's side: 'out' when it started the session, 'in' when it answered */
	direction?: 'in' | 'out';
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
 * Get the number of devices seen on the network (same rule as the device list).
 * With `active_since`, only the listed devices whose newest record is at or after it: the
 * table's Online rule (NET-158).
 */
export async function getDeviceCount(
	opts: TimeRangeParams & { active_since?: string } = {}
): Promise<DeviceCountResponse> {
	// OLD CODE START — NET-158: no active_since, so "Online now" counted a 5-minute range
	// const query = buildQuery({ from: opts.from, to: opts.to });
	// OLD CODE END
	const query = buildQuery({ from: opts.from, to: opts.to, active_since: opts.active_since });
	const res = await fetch(`/api/devices/count${query}`);

	// OLD CODE START — #96: a failed request read as no devices
	// if (!res.ok) {
	// 	return { from: '', to: '', count: 0 };
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Device count failed: HTTP ${res.status}`);

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

	// OLD CODE START — #96: a failed request read as "No devices seen yet"
	// if (!res.ok) {
	// 	return {
	// 		from: '',
	// 		to: '',
	// 		limit: opts.limit ?? 100,
	// 		devices: [],
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Device list failed: HTTP ${res.status}`);

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

	// OLD CODE START — #96: a failed request read as a device with no traffic
	// if (!res.ok) {
	// 	return {
	// 		device: {
	// 			ip,
	// 			mac: null,
	// 			hostname: null,
	// 			manufacturer: null,
	// 			os_hint: null,
	// 			first_seen: '',
	// 			last_seen: '',
	// 			total_bytes: 0,
	// 			connection_count: 0,
	// 			protocols: [],
	// 			alert_count: 0,
	// 			top_destinations: [],
	// 			dns_queries: [],
	// 			bandwidth_series: [],
	// 		},
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Device detail failed: HTTP ${res.status}`);

	return res.json();
}

/**
 * Get paginated connections for a specific device.
 */
/** Recent Connections columns the daemon sorts on (#140). */
// OLD CODE START — NET-158: no direction column
// export type DeviceConnectionSort = 'time' | 'destination' | 'proto' | 'service' | 'duration' | 'dl' | 'ul';
// OLD CODE END
/** dl, ul and direction sort on the device's side of each session (the daemon does it) */
// OLD CODE START — NET-160: no source column; the address page lists both sides
// export type DeviceConnectionSort = 'time' | 'direction' | 'destination' | 'proto' | 'service' | 'duration' | 'dl' | 'ul';
// OLD CODE END
export type DeviceConnectionSort = 'time' | 'direction' | 'source' | 'destination' | 'proto' | 'service' | 'duration' | 'dl' | 'ul';

export async function getDeviceConnections(
	ip: string,
	// OLD CODE START — #140: no sort, so the device page's connection columns couldn't sort
	// opts: TimeRangeParams & { page?: number; size?: number } = {}
	// OLD CODE END
	opts: TimeRangeParams & {
		page?: number;
		size?: number;
		sort?: DeviceConnectionSort;
		order?: 'asc' | 'desc';
		/** tcp, udp or icmp: filtered on the daemon, so the total and pages match (NET-158) */
		proto?: string;
	} = {}
): Promise<DeviceConnectionsResponse> {
	const query = buildQuery({
		from: opts.from,
		to: opts.to,
		page: opts.page,
		size: opts.size,
		sort: opts.sort,
		order: opts.order,
		proto: opts.proto,
	});
	const res = await fetch(`/api/devices/${encodeURIComponent(ip)}/connections${query}`);

	// OLD CODE START — #96: a failed request read as 0 connections
	// if (!res.ok) {
	// 	return {
	// 		from: '',
	// 		to: '',
	// 		ip,
	// 		page: opts.page ?? 1,
	// 		size: opts.size ?? 50,
	// 		total: 0,
	// 		total_pages: 0,
	// 		connections: [],
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Device connections failed: HTTP ${res.status}`);

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
	// OLD CODE START — #96: a failed request read as "No category data available"
	// if (!res.ok) return { ip, from: '', to: '', categories: [] };
	// OLD CODE END
	if (!res.ok) throw new Error(`Device categories failed: HTTP ${res.status}`);
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
	// OLD CODE START — #96: a failed request read as no alerts
	// if (!res.ok) return { ip, from: '', to: '', total: 0, alerts: [] };
	// OLD CODE END
	if (!res.ok) throw new Error(`Device alerts failed: HTTP ${res.status}`);
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
	// OLD CODE START — #96: a failed request read as "No port data"
	// if (!res.ok) return { ip, from: '', to: '', ports: [] };
	// OLD CODE END
	if (!res.ok) throw new Error(`Device ports failed: HTTP ${res.status}`);
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
	// OLD CODE START — #96: a failed request read as risk 0, LOW
	// if (!res.ok) return { ip, from: '', to: '', score: 0, level: 'low', factors: [], connection_count: 0, alert_count: 0 };
	// OLD CODE END
	if (!res.ok) throw new Error(`Device risk score failed: HTTP ${res.status}`);
	return res.json();
}
