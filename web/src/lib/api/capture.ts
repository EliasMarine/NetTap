/**
 * Client-side API helpers for capture mode and capture control endpoints.
 * Wraps GET /api/capture/mode, /api/capture/health, /api/capture/stats,
 *        GET /api/capture/status, PUT /api/capture/toggle, PUT /api/capture/settings.
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

export interface CaptureStatus {
	enabled: boolean;
	maxFileSizeMB: number;
	containerRunning: boolean;
	containerStatus: string;
}

export interface CaptureToggleResult {
	enabled: boolean;
	containerRunning: boolean;
	containerStatus: string;
}

export interface CaptureSettings {
	maxFileSizeMB: number;
}

export interface CaptureSettingsResult {
	maxFileSizeMB: number;
	restarted: boolean;
}

// ---------------------------------------------------------------------------
// Defaults
// ---------------------------------------------------------------------------

const DEFAULT_STATUS: CaptureStatus = {
	enabled: true,
	maxFileSizeMB: 100,
	containerRunning: false,
	containerStatus: 'unknown',
};

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

/**
 * Get the current capture mode (bridge or mirror).
 */
export async function getCaptureMode(): Promise<CaptureMode> {
	try {
		const res = await fetch('/api/capture/mode');
		if (!res.ok) {
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

// ---------------------------------------------------------------------------
// Capture control helpers (status / toggle / settings)
// ---------------------------------------------------------------------------

/**
 * Get capture control status (enabled state, file size, container state).
 */
export async function getCaptureStatus(): Promise<CaptureStatus> {
	try {
		const res = await fetch('/api/capture/status');
		if (!res.ok) {
			return { ...DEFAULT_STATUS };
		}
		return res.json();
	} catch {
		return { ...DEFAULT_STATUS };
	}
}

/**
 * Start or stop the pcap-capture container.
 */
export async function toggleCapture(enabled: boolean): Promise<CaptureToggleResult> {
	const res = await fetch('/api/capture/toggle', {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ enabled }),
	});

	if (!res.ok) {
		const data = await res.json().catch(() => ({ error: 'Toggle failed' }));
		throw new Error(data.error || `Toggle failed: ${res.status}`);
	}

	return res.json();
}

/**
 * Update the max PCAP file rotation size.
 */
export async function updateCaptureSettings(
	settings: CaptureSettings,
): Promise<CaptureSettingsResult> {
	const res = await fetch('/api/capture/settings', {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ maxFileSizeMB: settings.maxFileSizeMB }),
	});

	if (!res.ok) {
		const data = await res.json().catch(() => ({ error: 'Settings update failed' }));
		throw new Error(data.error || `Settings update failed: ${res.status}`);
	}

	return res.json();
}
