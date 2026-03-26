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

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Get UniFi integration status (configured, controller URL, errors).
 */
export async function getUnifiStatus(): Promise<UnifiStatus> {
	try {
		const res = await fetch(`${DAEMON}/status`);
		if (!res.ok) {
			return { configured: false, controller_url: null, site_id: null, last_error: null, cache_counts: {} };
		}
		return res.json();
	} catch {
		return { configured: false, controller_url: null, site_id: null, last_error: null, cache_counts: {} };
	}
}

/**
 * Get UniFi network devices (APs, switches, gateway).
 */
export async function getUnifiDevices(): Promise<UnifiDevice[]> {
	try {
		const res = await fetch(`${DAEMON}/devices`);
		if (!res.ok) return [];
		const data = await res.json();
		return data.devices || [];
	} catch {
		return [];
	}
}

/**
 * Get connected clients from the UniFi controller.
 */
export async function getUnifiClients(): Promise<UnifiClient[]> {
	try {
		const res = await fetch(`${DAEMON}/clients`);
		if (!res.ok) return [];
		const data = await res.json();
		return data.clients || [];
	} catch {
		return [];
	}
}

/**
 * Get UniFi networks (VLANs, subnets).
 */
export async function getUnifiNetworks(): Promise<UnifiNetwork[]> {
	try {
		const res = await fetch(`${DAEMON}/networks`);
		if (!res.ok) return [];
		const data = await res.json();
		return data.networks || [];
	} catch {
		return [];
	}
}

/**
 * Get UniFi WiFi SSIDs and radio configuration.
 */
export async function getUnifiWifi(): Promise<UnifiWifi[]> {
	try {
		const res = await fetch(`${DAEMON}/wifi`);
		if (!res.ok) return [];
		const data = await res.json();
		return data.wifi || [];
	} catch {
		return [];
	}
}

/**
 * Get firewall policies and zones from the UniFi controller.
 */
export async function getUnifiFirewall(): Promise<UnifiFirewall> {
	try {
		const res = await fetch(`${DAEMON}/firewall`);
		if (!res.ok) return { policies: [], zones: [] };
		return res.json();
	} catch {
		return { policies: [], zones: [] };
	}
}

/**
 * Get DNS content filtering policies.
 */
export async function getUnifiDnsPolicies(): Promise<DnsPolicy[]> {
	try {
		const res = await fetch(`${DAEMON}/dns-policies`);
		if (!res.ok) return [];
		const data = await res.json();
		return data.dns_policies || [];
	} catch {
		return [];
	}
}

/**
 * Get WAN interface information.
 */
export async function getUnifiWans(): Promise<UnifiWan[]> {
	try {
		const res = await fetch(`${DAEMON}/wans`);
		if (!res.ok) return [];
		const data = await res.json();
		return data.wans || [];
	} catch {
		return [];
	}
}

/**
 * Get VPN tunnel status and configuration.
 */
export async function getUnifiVpn(): Promise<UnifiVpnTunnel[]> {
	try {
		const res = await fetch(`${DAEMON}/vpn`);
		if (!res.ok) return [];
		const data = await res.json();
		return data.vpn_tunnels || [];
	} catch {
		return [];
	}
}
