/**
 * Client-side API helpers for DHCP gateway capture mode.
 * Wraps GET /api/capture/dhcp/preflight, POST /api/capture/dhcp/enable,
 *       POST /api/capture/dhcp/disable, GET /api/capture/dhcp/status.
 *
 * Unlike the read-only capture helpers, these throw on non-OK responses:
 * the go-live flow must never act on a guessed state.
 */

// ---------------------------------------------------------------------------
// Types (design doc §6.2)
// ---------------------------------------------------------------------------

export interface DhcpUpstream {
	address: string; // NetTap's own address on the router subnet, e.g. "192.168.1.50/24"
	gateway: string; // the router, e.g. "192.168.1.1"
}

export interface DhcpServerOffer {
	server_ip: string;
	offered_ip: string;
}

export interface DhcpSubnetConflict {
	interface: string;
	network: string;
}

export interface DhcpCheck {
	// interface_up | upstream_detected | no_other_dhcp | no_subnet_conflict |
	// ip_forward | firewall_backend (blocking) | ipv6_bypass (non-blocking)
	name: string;
	passed: boolean;
	blocking: boolean;
	message: string;
}

export interface DhcpPreflight {
	interface: string;
	subnet: string;
	gateway_ip: string;
	upstream: DhcpUpstream | null;
	subnet_conflicts: DhcpSubnetConflict[];
	other_dhcp_servers: DhcpServerOffer[];
	ipv6_router_advertisements: boolean;
	ip_forward: boolean;
	firewall_backend: string | null; // "iptables-nft" | "iptables-legacy" | null
	checks: DhcpCheck[];
	ready: boolean;
}

export interface DhcpLease {
	mac: string;
	ip: string;
	hostname: string;
	expires: number; // unix seconds
}

export interface DhcpStatus {
	interface: string;
	subnet: string;
	gateway_ip: string;
	upstream: DhcpUpstream | null;
	routing_active: boolean;
	dhcp_enabled: boolean;
	dhcp_server_running: boolean;
	leases: DhcpLease[];
	issues: string[];
}

/** Result of rewriting capture.env and restarting the capture containers. */
export interface DhcpCaptureRestart {
	restarted: string[];
	errors: string[];
}

/** POST /enable answers with the status plus the capture restart result. */
export interface DhcpEnableResult extends DhcpStatus {
	capture_restart?: DhcpCaptureRestart;
}

/** Non-OK response. `checks` is set when a 409 carries the failed preflight checks. */
export class DhcpGatewayError extends Error {
	status: number;
	checks?: DhcpCheck[];

	constructor(message: string, status: number, checks?: DhcpCheck[]) {
		super(message);
		this.name = 'DhcpGatewayError';
		this.status = status;
		this.checks = checks;
	}
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

async function request<T>(path: string, init?: RequestInit): Promise<T> {
	const res = await fetch(`/api/capture/dhcp/${path}`, init);

	if (!res.ok) {
		const data = await res.json().catch(() => ({}));
		const message = typeof data?.error === 'string' && data.error ? data.error : `HTTP ${res.status}`;
		const checks = res.status === 409 && Array.isArray(data?.checks) ? (data.checks as DhcpCheck[]) : undefined;
		throw new DhcpGatewayError(message, res.status, checks);
	}

	return res.json();
}

/**
 * Run the pre-enable checks (includes a ~3 s DHCP probe on the daemon side).
 */
export async function getDhcpPreflight(): Promise<DhcpPreflight> {
	return request<DhcpPreflight>('preflight');
}

/**
 * Turn on routing + the DHCP server. Only call after the user confirmed.
 */
export async function enableDhcpGateway(): Promise<DhcpEnableResult> {
	return request<DhcpEnableResult>('enable', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ confirm: true }),
	});
}

/**
 * Turn off the DHCP server. Routing stays on so existing leases keep working.
 */
export async function disableDhcpGateway(): Promise<DhcpStatus> {
	return request<DhcpStatus>('disable', { method: 'POST' });
}

/**
 * Get routing / DHCP server state, leases and issues.
 */
export async function getDhcpStatus(): Promise<DhcpStatus> {
	return request<DhcpStatus>('status');
}
