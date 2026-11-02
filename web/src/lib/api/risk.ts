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
}

export interface RiskScoresResponse {
	scores: DeviceRiskScore[];
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

/**
 * Get risk scores for all monitored devices.
 */
export async function getRiskScores(): Promise<RiskScoresResponse> {
	const res = await fetch('/api/risk/scores');

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
