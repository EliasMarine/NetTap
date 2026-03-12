/**
 * Client-side API helpers for capture mode endpoints.
 * Wraps GET /api/capture/mode, /api/capture/health, /api/capture/stats.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CaptureMode {
	mode: string; // "bridge" | "mirror"
	interface: string;
}

export interface CaptureHealthResponse {
	mode: string;
	status: string; // "normal" | "degraded" | "down" | "not_configured"
	capture_interface: string;
	link_up: boolean;
	promisc_enabled: boolean;
	issues: string[];
	[key: string]: unknown; // extra fields from bridge/mirror
}

export interface CaptureStatsResponse {
	capture_interface: string;
	rx_bytes: number;
	tx_bytes: number;
	rx_packets: number;
	tx_packets: number;
	rx_dropped: number;
	rx_missed_errors: number;
	link_speed_mbps: number;
	drop_rate_pct: number;
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

/**
 * Get the current capture mode (bridge or mirror).
 */
export async function getCaptureMode(): Promise<CaptureMode> {
	try {
		const res = await fetch('/api/capture/mode');		if (!res.ok) {
			return { mode: 'bridge', interface: '' };
		}
		return res.json();
	} catch {
		return { mode: 'bridge', interface: '' };
	}
}

/**
 * Get capture health status.
 */
export async function getCaptureHealth(): Promise<CaptureHealthResponse> {
	try {
		const res = await fetch('/api/capture/health');
		if (!res.ok) {
			return {
				mode: 'bridge',
				status: 'down',
				capture_interface: '',
				link_up: false,
				promisc_enabled: false,
				issues: ['Unable to reach capture health endpoint'],
			};
		}
		return res.json();
	} catch {
		return {
			mode: 'bridge',
			status: 'down',
			capture_interface: '',
			link_up: false,
			promisc_enabled: false,
			issues: ['Unable to reach capture health endpoint'],
		};
	}
}

/**
 * Get capture interface statistics (drop counters, throughput).
 */
export async function getCaptureStats(): Promise<CaptureStatsResponse> {
	try {
		const res = await fetch('/api/capture/stats');
		if (!res.ok) {
			return {
				capture_interface: '',
				rx_bytes: 0,
				tx_bytes: 0,
				rx_packets: 0,
				tx_packets: 0,
				rx_dropped: 0,
				rx_missed_errors: 0,
				link_speed_mbps: 0,
				drop_rate_pct: 0,
			};
		}
		return res.json();
	} catch {
		return {
			capture_interface: '',
			rx_bytes: 0,
			tx_bytes: 0,
			rx_packets: 0,
			tx_packets: 0,
			rx_dropped: 0,
			rx_missed_errors: 0,
			link_speed_mbps: 0,
			drop_rate_pct: 0,
		};
	}
}
