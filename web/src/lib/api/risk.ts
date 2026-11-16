/**
 * Client-side API helpers for device risk scoring endpoints.
 * These functions call the SvelteKit server proxy routes which in turn
 * forward requests to the nettap-storage-daemon.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface RiskFactor {
	name: string;
	score: number;
	max: number;
	description: string;
}

export interface DeviceRiskScore {
	ip: string;
	score: number;
	level: string; // 'low' | 'medium' | 'high' | 'critical'
	factors: RiskFactor[];
	/** Connections it opened in the window; the list sends it, a single score may not */
	connection_count?: number;
	/** Rule matches in its own traffic (NET-209) */
	alert_count?: number;
}

export interface RiskScoresResponse {
	scores: DeviceRiskScore[];
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

/**
 * Get risk scores for all monitored devices, over `from`/`to` when given (the daemon's last 24 h otherwise).
 */
// OLD CODE: export async function getRiskScores(): Promise<RiskScoresResponse> { (posture pages: the window their other figures use)
export async function getRiskScores(opts: { from?: string; to?: string } = {}): Promise<RiskScoresResponse> {
	// OLD CODE: const res = await fetch('/api/risk/scores');
	const query = opts.from && opts.to ? `?${new URLSearchParams({ from: opts.from, to: opts.to }).toString()}` : '';
	const res = await fetch(`/api/risk/scores${query}`);

	// OLD CODE START — #96: a failure read as "0 of N devices have risk scores"
	// if (!res.ok) {
	// 	return { scores: [] };
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Risk scores failed: HTTP ${res.status}`);

	// OLD CODE START — #81: the daemon sends its list as `devices`, so `scores` was undefined
	// and the Security Posture page crashed on `.length`, stuck on "Calculating..."
	// return res.json();
	// OLD CODE END
	const data = await res.json();
	return { scores: Array.isArray(data?.devices) ? data.devices : [] };
}

/**
 * Get the risk score for a single device by IP address.
 */
export async function getDeviceRiskScore(ip: string): Promise<DeviceRiskScore | null> {
	const res = await fetch(`/api/risk/scores/${encodeURIComponent(ip)}`);

	// OLD CODE START — #96: a failed query read the same as a device with no data to score
	// if (!res.ok) {
	// 	return null;
	// }
	// OLD CODE END
	// 404: the daemon has no connections for this IP, so there is nothing to score
	if (res.status === 404) return null;
	if (!res.ok) throw new Error(`Risk score failed: HTTP ${res.status}`);

	return res.json();
}
