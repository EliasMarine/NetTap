/**
 * Client-side API helpers for UniFi integration endpoints.
 * Wraps GET /api/integrations/unifi/* endpoints.
 *
 * The catch-all proxy at web/src/routes/api/[...path]/+server.ts forwards all
 * /api/* requests to the nettap-storage-daemon — no new proxy routes are needed.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface UnifiStatus {
	configured: boolean;
	controller_url: string | null;
	site_id: string | null;
	/** True once the current configuration has polled successfully. */
	connected: boolean;
	/** Epoch seconds of the last successful poll; 0 = never. */
	last_poll_time: number;
	last_error: string | null;
	cache_counts: Record<string, number>;
}

export interface UnifiDevice {
	id: string;
	macAddress: string;
	ipAddress: string;
	name: string;
	model: string;
	state: string; // ONLINE, OFFLINE, etc.
	firmwareVersion: string;
	firmwareUpdatable: boolean;
	features: string[]; // e.g. ["switching"], ["accessPoint"]
	interfaces: string[]; // e.g. ["ports"], ["radios"]
	[key: string]: unknown;
}

export interface UnifiClient {
	id: string;
	name: string;
	macAddress: string;
	ipAddress: string;
	type: string;
	[key: string]: unknown;
}

export interface UnifiNetwork {
	id: string;
	name: string;
	vlanId: number | null;
	subnet: string | null;
	purpose: string;
	[key: string]: unknown;
}

export interface UnifiWifi {
	id: string;
	name: string;
	band: string;
	security: string;
	enabled: boolean;
	[key: string]: unknown;
}

export interface FirewallPolicy {
	id: string;
	name: string;
	enabled: boolean;
	action: { type: string; [key: string]: unknown } | string;
	[key: string]: unknown;
}

export interface FirewallZone {
	id: string;
	name: string;
	[key: string]: unknown;
}

export interface UnifiFirewall {
	policies: FirewallPolicy[];
	zones: FirewallZone[];
}

export interface DnsPolicy {
	id: string;
	name: string;
	enabled: boolean;
	[key: string]: unknown;
}

export interface UnifiWan {
	id: string;
	name: string;
	type: string;
	status: string;
	[key: string]: unknown;
}

export interface UnifiVpnTunnel {
	id: string;
	name: string;
	type: string;
	status: string;
	[key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DAEMON = '/api/integrations/unifi';

// OLD CODE START — #96: the fallback a failed status read returned; it read as "not configured"
// const EMPTY_STATUS: UnifiStatus = {
// 	configured: false,
// 	controller_url: null,
// 	site_id: null,
// 	connected: false,
// 	last_poll_time: 0,
// 	last_error: null,
// 	cache_counts: {},
// };
// OLD CODE END

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Get UniFi integration status (configured, controller URL, errors).
 */
export async function getUnifiStatus(): Promise<UnifiStatus> {
	// OLD CODE START — returned the raw payload, so fields an older daemon omits came back undefined
	// try {
	// 	const res = await fetch(`${DAEMON}/status`);
	// 	if (!res.ok) {
	// 		return { configured: false, controller_url: null, site_id: null, last_error: null, cache_counts: {} };
	// 	}
	// 	return res.json();
	// } catch {
	// 	return { configured: false, controller_url: null, site_id: null, last_error: null, cache_counts: {} };
	// }
	// OLD CODE END
	// OLD CODE START — #96: a failed read came back as "not configured" / [] and showed as fact
	// try {
	// 	const res = await fetch(`${DAEMON}/status`);
	// 	if (!res.ok) return { ...EMPTY_STATUS };
	// 	const raw: Partial<UnifiStatus> = await res.json();
	// 	// `connected` and `site_id` are absent on daemons older than this contract
	// 	return {
	// 		configured: raw.configured ?? false,
	// 		controller_url: raw.controller_url ?? null,
	// 		site_id: raw.site_id || null,
	// 		connected: raw.connected ?? false,
	// 		last_poll_time: typeof raw.last_poll_time === 'number' ? raw.last_poll_time : 0,
	// 		last_error: raw.last_error ?? null,
	// 		cache_counts: raw.cache_counts ?? {},
	// 	};
	// } catch {
	// 	return { ...EMPTY_STATUS };
	// }
	// OLD CODE END
	const res = await fetch(`${DAEMON}/status`);
	if (!res.ok) throw new Error(`UniFi status failed: HTTP ${res.status}`);
	const raw: Partial<UnifiStatus> = await res.json();
	// `connected` and `site_id` are absent on daemons older than this contract
	return {
		configured: raw.configured ?? false,
		controller_url: raw.controller_url ?? null,
		site_id: raw.site_id || null,
		connected: raw.connected ?? false,
		last_poll_time: typeof raw.last_poll_time === 'number' ? raw.last_poll_time : 0,
		last_error: raw.last_error ?? null,
		cache_counts: raw.cache_counts ?? {},
	};
}

/**
 * Get UniFi network devices (APs, switches, gateway).
 */
export async function getUnifiDevices(): Promise<UnifiDevice[]> {
	// OLD CODE START — #96: a failed read came back as "not configured" / [] and showed as fact
	// try {
	// 	const res = await fetch(`${DAEMON}/devices`);
	// 	if (!res.ok) return [];
	// 	const data = await res.json();
	// 	return data.devices || [];
	// } catch {
	// 	return [];
	// }
	// OLD CODE END
	const res = await fetch(`${DAEMON}/devices`);
	if (!res.ok) throw new Error(`UniFi devices failed: HTTP ${res.status}`);
	const data = await res.json();
	return data.devices || [];
}

/**
 * Get connected clients from the UniFi controller.
 */
export async function getUnifiClients(): Promise<UnifiClient[]> {
	// OLD CODE START — #96: a failed read came back as "not configured" / [] and showed as fact
	// try {
	// 	const res = await fetch(`${DAEMON}/clients`);
	// 	if (!res.ok) return [];
	// 	const data = await res.json();
	// 	return data.clients || [];
	// } catch {
	// 	return [];
	// }
	// OLD CODE END
	const res = await fetch(`${DAEMON}/clients`);
	if (!res.ok) throw new Error(`UniFi clients failed: HTTP ${res.status}`);
	const data = await res.json();
	return data.clients || [];
}

/**
 * Get UniFi networks (VLANs, subnets).
 */
export async function getUnifiNetworks(): Promise<UnifiNetwork[]> {
	// OLD CODE START — #96: a failed read came back as "not configured" / [] and showed as fact
	// try {
	// 	const res = await fetch(`${DAEMON}/networks`);
	// 	if (!res.ok) return [];
	// 	const data = await res.json();
	// 	return data.networks || [];
	// } catch {
	// 	return [];
	// }
	// OLD CODE END
	const res = await fetch(`${DAEMON}/networks`);
	if (!res.ok) throw new Error(`UniFi networks failed: HTTP ${res.status}`);
	const data = await res.json();
	return data.networks || [];
}

/**
 * Get UniFi WiFi SSIDs and radio configuration.
 */
export async function getUnifiWifi(): Promise<UnifiWifi[]> {
	// OLD CODE START — #96: a failed read came back as "not configured" / [] and showed as fact
	// try {
	// 	const res = await fetch(`${DAEMON}/wifi`);
	// 	if (!res.ok) return [];
	// 	const data = await res.json();
	// 	return data.wifi || [];
	// } catch {
	// 	return [];
	// }
	// OLD CODE END
	const res = await fetch(`${DAEMON}/wifi`);
	if (!res.ok) throw new Error(`UniFi WiFi failed: HTTP ${res.status}`);
	const data = await res.json();
	return data.wifi || [];
}

/**
 * Get firewall policies and zones from the UniFi controller.
 */
export async function getUnifiFirewall(): Promise<UnifiFirewall> {
	// OLD CODE START — #96: a failed read came back as "not configured" / [] and showed as fact
	// try {
	// 	const res = await fetch(`${DAEMON}/firewall`);
	// 	if (!res.ok) return { policies: [], zones: [] };
	// 	return res.json();
	// } catch {
	// 	return { policies: [], zones: [] };
	// }
	// OLD CODE END
	const res = await fetch(`${DAEMON}/firewall`);
	if (!res.ok) throw new Error(`UniFi firewall failed: HTTP ${res.status}`);
	return res.json();
}

/**
 * Get DNS content filtering policies.
 */
export async function getUnifiDnsPolicies(): Promise<DnsPolicy[]> {
	// OLD CODE START — #96: a failed read came back as "not configured" / [] and showed as fact
	// try {
	// 	const res = await fetch(`${DAEMON}/dns-policies`);
	// 	if (!res.ok) return [];
	// 	const data = await res.json();
	// 	return data.policies || [];
	// } catch {
	// 	return [];
	// }
	// OLD CODE END
	const res = await fetch(`${DAEMON}/dns-policies`);
	if (!res.ok) throw new Error(`UniFi DNS policies failed: HTTP ${res.status}`);
	const data = await res.json();
	// OLD CODE START — the daemon sends `policies`; `dns_policies` never existed
	// return data.dns_policies || [];
	// OLD CODE END
	return data.policies || [];
}

/**
 * Get WAN interface information.
 */
export async function getUnifiWans(): Promise<UnifiWan[]> {
	// OLD CODE START — #96: a failed read came back as "not configured" / [] and showed as fact
	// try {
	// 	const res = await fetch(`${DAEMON}/wans`);
	// 	if (!res.ok) return [];
	// 	const data = await res.json();
	// 	return data.wans || [];
	// } catch {
	// 	return [];
	// }
	// OLD CODE END
	const res = await fetch(`${DAEMON}/wans`);
	if (!res.ok) throw new Error(`UniFi WANs failed: HTTP ${res.status}`);
	const data = await res.json();
	return data.wans || [];
}

/**
 * Get VPN tunnel status and configuration.
 */
export async function getUnifiVpn(): Promise<UnifiVpnTunnel[]> {
	// OLD CODE START — #96: a failed read came back as "not configured" / [] and showed as fact
	// try {
	// 	const res = await fetch(`${DAEMON}/vpn`);
	// 	if (!res.ok) return [];
	// 	const data = await res.json();
	// 	return data.tunnels || [];
	// } catch {
	// 	return [];
	// }
	// OLD CODE END
	const res = await fetch(`${DAEMON}/vpn`);
	if (!res.ok) throw new Error(`UniFi VPN failed: HTTP ${res.status}`);
	const data = await res.json();
	// OLD CODE START — the daemon sends `tunnels`; `vpn_tunnels` never existed
	// return data.vpn_tunnels || [];
	// OLD CODE END
	return data.tunnels || [];
}
