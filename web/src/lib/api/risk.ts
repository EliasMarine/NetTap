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

	if (!res.ok) {
		return { scores: [] };
	}

	return res.json();
}

/**
 * Get the risk score for a single device by IP address.
 */
export async function getDeviceRiskScore(ip: string): Promise<DeviceRiskScore | null> {
	const res = await fetch(`/api/risk/scores/${encodeURIComponent(ip)}`);

	if (!res.ok) {
		return null;
	}

	return res.json();
}
