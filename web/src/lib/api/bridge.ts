/**
 * Client-side API helpers for bridge health monitoring and failover endpoints.
 * These functions call the SvelteKit server proxy routes which in turn
 * forward requests to the nettap-storage-daemon.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface BridgeHealth {
	bridge_state: 'up' | 'down' | 'unknown';
	wan_link: boolean;
	lan_link: boolean;
	bypass_active: boolean;
	watchdog_active: boolean;
	latency_us: number;
	rx_bytes_delta: number;
	tx_bytes_delta: number;
	rx_packets_delta: number;
	tx_packets_delta: number;
	uptime_seconds: number;
	health_status: 'normal' | 'degraded' | 'bypass' | 'down';
	issues: string[];
	last_check: string;
}

export interface BridgeStats {
	avg_latency_us: number;
	total_rx_packets: number;
	total_tx_packets: number;
	uptime_percent: number;
	longest_downtime_seconds: number;
	check_count: number;
}

export interface BypassStatus {
	active: boolean;
	activated_at: string | null;
}

// ---------------------------------------------------------------------------
// Helpers
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
 * Get the current bridge health snapshot including link states, latency, and issues.
 */
export async function getBridgeHealth(): Promise<BridgeHealth> {
	const res = await fetch('/api/bridge/health');

	if (!res.ok) {
		return {
			bridge_state: 'unknown',
			wan_link: false,
			lan_link: false,
			bypass_active: false,
			watchdog_active: false,
			latency_us: 0,
			rx_bytes_delta: 0,
			tx_bytes_delta: 0,
			rx_packets_delta: 0,
			tx_packets_delta: 0,
			uptime_seconds: 0,
			health_status: 'down',
			issues: ['Unable to reach bridge health endpoint'],
			last_check: '',
		};
	}

	return res.json();
}

/**
 * Get historical bridge health snapshots.
 */
export async function getBridgeHistory(
	limit?: number
): Promise<{ history: BridgeHealth[] }> {
	const query = buildQuery({ limit });
	const res = await fetch(`/api/bridge/history${query}`);

	if (!res.ok) {
		return { history: [] };
	}

	return res.json();
}

/**
 * Get aggregated bridge statistics (averages, totals, uptime percentage).
 */
export async function getBridgeStats(): Promise<BridgeStats> {
	const res = await fetch('/api/bridge/stats');

	if (!res.ok) {
		return {
			avg_latency_us: 0,
			total_rx_packets: 0,
			total_tx_packets: 0,
			uptime_percent: 0,
			longest_downtime_seconds: 0,
			check_count: 0,
		};
	}

	return res.json();
}

/**
 * Enable bypass mode (stops capture, passes traffic through directly).
 */
export async function enableBypass(): Promise<{ result: string }> {
	const res = await fetch('/api/bridge/bypass/enable', {
		method: 'POST',
	});

	if (!res.ok) {
		return { result: 'error' };
	}

	return res.json();
}

/**
 * Disable bypass mode (resumes normal bridge capture).
 */
export async function disableBypass(): Promise<{ result: string }> {
	const res = await fetch('/api/bridge/bypass/disable', {
		method: 'POST',
	});

	if (!res.ok) {
		return { result: 'error' };
	}

	return res.json();
}

/**
 * Get the current bypass mode status.
 */
export async function getBypassStatus(): Promise<BypassStatus> {
	const res = await fetch('/api/bridge/bypass/status');

	if (!res.ok) {
		return {
			active: false,
			activated_at: null,
		};
	}

	return res.json();
}
