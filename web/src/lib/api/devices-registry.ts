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
	/** The owner's name first (NET-200), then the discovered one */
	display_name: string;
	/** NET-200: the owner's own name for the device, or null */
	custom_name?: string | null;
	/** NET-200: the name the network gives it, without the owner's name */
	discovered_name?: string;
	/** NET-200: a built-in icon the owner picked (DEVICE_ICONS), or null */
	icon?: string | null;
	/** NET-200: the owner's photo, `/api/devices/registry/<MAC>/picture?v=<hash>`, or null */
	picture?: string | null;
	category: string; // "computer" | "phone" | "iot" | "infrastructure" | "unknown"
	first_seen: string;
	last_seen: string;
	is_new: boolean;
	total_bytes?: number;
	connection_count?: number;
	/** How many of `ips` the device list held when total_bytes was added up (withTraffic) */
	ips_listed?: number;
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
	// The daemon doesn't send these three (yet); the page hides their sections when absent
	dns_queries?: Array<{ domain: string; count: number }>;
	alerts?: Array<{ signature: string; severity: number; timestamp: string }>;
	bandwidth_series?: Array<{ timestamp: string; bytes: number }>;
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

/**
 * Get all devices from the registry.
 */
/**
 * How many devices NetTap saw for the first time since `since` (ISO). The device list's
 * first_seen is the first record in its time window, so it can't tell new devices from old.
 */
export async function getNewDeviceCount(since: string): Promise<{ count: number; since: string }> {
	const res = await fetch(`/api/devices/registry/new-count?${new URLSearchParams({ since })}`);
	if (!res.ok) throw new Error(`New device count failed: HTTP ${res.status}`);
	return res.json();
}

/** "New" means first seen by NetTap in the last 24 hours: the "New in 24 h" count's rule. */
export const NEW_DEVICE_WINDOW_MS = 24 * 60 * 60 * 1000;

/**
 * The "New" chip's rule, the same as getNewDeviceCount(now - NEW_DEVICE_WINDOW_MS) counts
 * (NET-158: the chip read is_new, which the registry clears on a device's next update).
 */
export function isNewDevice(device: Pick<RegistryDevice, 'first_seen'>, now: number = Date.now()): boolean {
	const first = Date.parse(device.first_seen);
	return Number.isFinite(first) && first >= now - NEW_DEVICE_WINDOW_MS;
}

export async function getRegistryDevices(
	opts: { limit?: number; offset?: number } = {}
): Promise<RegistryListResponse> {
	const params = new URLSearchParams();
	if (opts.limit !== undefined) params.set('limit', String(opts.limit));
	if (opts.offset !== undefined) params.set('offset', String(opts.offset));
	const qs = params.toString();
	const url = `/api/devices/registry${qs ? `?${qs}` : ''}`;

	// OLD CODE START — #96: a failed request read as "No devices detected yet"
	// try {
	// 	const res = await fetch(url);
	// 	if (!res.ok) {
	// 		return { devices: [], total: 0 };
	// 	}
	// 	return res.json();
	// } catch {
	// 	return { devices: [], total: 0 };
	// }
	// OLD CODE END
	const res = await fetch(url);
	if (!res.ok) throw new Error(`Device registry failed: HTTP ${res.status}`);
	return res.json();
}

/**
 * Get a single device by MAC address.
 * Resolves null only when the registry has no such device (404); any other failure throws.
 */
export async function getRegistryDevice(mac: string): Promise<RegistryDevice | null> {
	// OLD CODE START — #96: every failure read as "Device not found"
	// try {
	// 	const res = await fetch(`/api/devices/registry/${encodeURIComponent(mac)}`);
	// 	if (!res.ok) return null;
	// 	// OLD CODE START — #89: the daemon wraps the device as {device: {...}}, so the MAC page read
	// 	// device.ips of the wrapper and crashed on .length
	// 	// return res.json();
	// 	// OLD CODE END
	// 	const data = await res.json();
	// 	return data?.device ?? null;
	// } catch {
	// 	return null;
	// }
	// OLD CODE END
	const res = await fetch(`/api/devices/registry/${encodeURIComponent(mac)}`);
	if (res.status === 404) return null;
	if (!res.ok) throw new Error(`Registry device failed: HTTP ${res.status}`);
	const data = await res.json();
	return data?.device ?? null;
}

/**
 * Get traffic data for a specific device by MAC address.
 * Resolves null only when the registry has no such device (404); any other failure throws.
 */
/** `win`: the window to read (the daemon reads the last 24 hours without one). */
export async function getDeviceTraffic(mac: string, win?: { from: string; to: string }): Promise<DeviceTraffic | null> {
	// OLD CODE START — #96: a failure silently hid the device's traffic
	// try {
	// 	const res = await fetch(
	// 		`/api/devices/registry/${encodeURIComponent(mac)}/traffic`
	// 	);
	// 	if (!res.ok) return null;
	// 	// OLD CODE START — #89: the daemon sends {from, to, traffic: {...}}
	// 	// return res.json();
	// 	// OLD CODE END
	// 	const data = await res.json();
	// 	return data?.traffic ?? null;
	// } catch {
	// 	return null;
	// }
	// OLD CODE END
	// OLD CODE: const res = await fetch(`/api/devices/registry/${encodeURIComponent(mac)}/traffic`); (NET-192 PR 4: the page's range)
	const query = win ? `?${new URLSearchParams(win)}` : '';
	const res = await fetch(`/api/devices/registry/${encodeURIComponent(mac)}/traffic${query}`);
	if (res.status === 404) return null;
	if (!res.ok) throw new Error(`Device traffic failed: HTTP ${res.status}`);
	const data = await res.json();
	return data?.traffic ?? null;
}

// ---------------------------------------------------------------------------
// NET-200: the owner's name and picture for a device
// ---------------------------------------------------------------------------

/** The built-in icons the owner can pick: the daemon's allowlist, all in ui/icons.ts. */
export const DEVICE_ICONS = ['laptop', 'phone', 'tablet', 'tv', 'nas', 'gamepad', 'camera', 'speaker', 'printer', 'iot', 'infra', 'devices'] as const;

/** One save; resolves to the device as the daemon now has it, or throws the daemon's reason. */
async function saveDevice(mac: string, part: 'name' | 'picture', method: 'PUT' | 'DELETE', body?: object): Promise<RegistryDevice> {
	const res = await fetch(`/api/devices/registry/${encodeURIComponent(mac)}/${part}`, {
		method,
		...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
	});
	// nginx or the web server refuses an oversize body before the daemon sees it
	if (res.status === 413) throw new Error('The picture is too large');
	const data = await res.json().catch(() => null);
	if (!res.ok || !data?.device) throw new Error(data?.error ?? `Couldn't save the device: HTTP ${res.status}`);
	return data.device;
}

export const setDeviceName = (mac: string, name: string) => saveDevice(mac, 'name', 'PUT', { name });
export const clearDeviceName = (mac: string) => saveDevice(mac, 'name', 'DELETE');
/** `image` is a data URL (PNG, JPEG or WebP); the daemon checks its bytes. */
export const setDevicePicture = (mac: string, picture: { icon: string } | { image: string }) =>
	saveDevice(mac, 'picture', 'PUT', picture);
export const clearDevicePicture = (mac: string) => saveDevice(mac, 'picture', 'DELETE');

/**
 * Mark a device as acknowledged (clear is_new flag).
 */
export async function acknowledgeDevice(mac: string): Promise<boolean> {
	try {
		const res = await fetch(
			`/api/devices/registry/${encodeURIComponent(mac)}`,
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
