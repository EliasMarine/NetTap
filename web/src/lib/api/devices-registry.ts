/**
 * Client-side API helpers for the device registry (v2, MAC-keyed) endpoints.
 * Wraps GET /api/devices/registry, /api/devices/registry/{mac}, etc.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface RegistryDevice {
	mac: string;
	ips: string[];
	hostnames: string[];
	manufacturer: string | null;
	friendly_name: string | null;
	display_name: string;
	category: string; // "computer" | "phone" | "iot" | "infrastructure" | "unknown"
	first_seen: string;
	last_seen: string;
	is_new: boolean;
	total_bytes?: number;
	connection_count?: number;
	enrichment_sources?: Record<string, unknown>;
}

export interface RegistryListResponse {
	devices: RegistryDevice[];
	total: number;
}

export interface DeviceTraffic {
	mac: string;
	total_bytes: number;
	inbound_bytes: number;
	outbound_bytes: number;
	connection_count: number;
	top_destinations: Array<{ ip: string; bytes: number; connections: number }>;
	top_protocols: Array<{ name: string; count: number }>;
	dns_queries: Array<{ domain: string; count: number }>;
	alerts: Array<{ signature: string; severity: number; timestamp: string }>;
	bandwidth_series: Array<{ timestamp: string; bytes: number }>;
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8880';

/**
 * Get all devices from the registry.
 */
export async function getRegistryDevices(
	opts: { limit?: number; offset?: number } = {}
): Promise<RegistryListResponse> {
	const params = new URLSearchParams();
	if (opts.limit !== undefined) params.set('limit', String(opts.limit));
	if (opts.offset !== undefined) params.set('offset', String(opts.offset));
	const qs = params.toString();
	const url = `${API_BASE}/api/devices/registry${qs ? `?${qs}` : ''}`;

	try {
		const res = await fetch(url);
		if (!res.ok) {
			return { devices: [], total: 0 };
		}
		return res.json();
	} catch {
		return { devices: [], total: 0 };
	}
}

/**
 * Get a single device by MAC address.
 */
export async function getRegistryDevice(mac: string): Promise<RegistryDevice | null> {
	try {
		const res = await fetch(`${API_BASE}/api/devices/registry/${encodeURIComponent(mac)}`);
		if (!res.ok) return null;
		return res.json();
	} catch {
		return null;
	}
}

/**
 * Get traffic data for a specific device by MAC address.
 */
export async function getDeviceTraffic(mac: string): Promise<DeviceTraffic | null> {
	try {
		const res = await fetch(
			`${API_BASE}/api/devices/registry/${encodeURIComponent(mac)}/traffic`
		);
		if (!res.ok) return null;
		return res.json();
	} catch {
		return null;
	}
}

/**
 * Mark a device as acknowledged (clear is_new flag).
 */
export async function acknowledgeDevice(mac: string): Promise<boolean> {
	try {
		const res = await fetch(
			`${API_BASE}/api/devices/registry/${encodeURIComponent(mac)}`,
			{
				method: 'PATCH',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ is_new: false }),
			}
		);
		return res.ok;
	} catch {
		return false;
	}
}
