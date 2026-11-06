/**
 * Client-side API helpers for system health, storage, and SMART monitoring endpoints.
 * These functions call the SvelteKit server proxy routes which in turn
 * forward requests to the nettap-storage-daemon.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * S5: one aggregate status. A check that found a failure makes it "problem"; otherwise a
 * check that couldn't run (an unreadable drive, say) makes it "incomplete", never "Degraded".
 */
export type HealthStatus = 'healthy' | 'incomplete' | 'problem';

/** The aggregate status as a pipeline stage: Home and System read this one map. */
// (typed structurally: e2e fixtures type-check this file with plain tsc, which can't read .svelte)
export const HEALTH_STAGE: Record<HealthStatus, { status: 'ok' | 'failing' | 'unknown'; detail: string }> = {
	healthy: { status: 'ok', detail: 'Healthy' },
	problem: { status: 'failing', detail: 'Reports a problem' },
	incomplete: { status: 'unknown', detail: "Incomplete · some checks couldn't run" },
};

export interface SystemHealth {
	/** The appliance's (host's) uptime in seconds, from /proc/uptime */
	uptime: number;
	timestamp: string;
	storage: any;
	smart: any;
	opensearch_reachable: boolean;
	// OLD CODE START — 2026-11-06 (S5): a boolean, so "couldn't check" read as "Degraded"
	// healthy: boolean;
	// OLD CODE END
	status: HealthStatus;
	/** status as a tri-state: null when incomplete */
	healthy: boolean | null;
}

export interface StorageStatus {
	disk_usage_percent: number;
	disk_total_bytes: number;
	disk_used_bytes: number;
	disk_free_bytes: number;
	// GB fields returned by daemon alongside bytes
	disk_total_gb?: number;
	disk_used_gb?: number;
	disk_free_gb?: number;
	retention: any;
	index_summary?: any;
	// Daemon returns index_counts (object) + total_indices (number) instead
	// null, with indices_error, when OpenSearch couldn't be asked (#96)
	index_counts?: Record<string, number> | null;
	total_indices?: number | null;
	indices_error?: string;
	/** S6: the daemon starts pruning old data here, and prunes hard at the emergency line (0-100) */
	disk_threshold_percent: number;
	emergency_threshold_percent: number;
}

export interface SmartHealth {
	device: string;
	device_type: string;
	model: string;
	serial: string;
	temperature_c: number | null;
	percentage_used: number | null;
	power_on_hours: number | null;
	total_bytes_written: number | null;
	total_bytes_read: number | null;
	media_errors: number | null;
	reallocated_sectors: number | null;
	/** null, with `error`, when the drive's health couldn't be read (#96) */
	healthy: boolean | null;
	error?: string;
	warnings: string[];
	timestamp: string;
}

export interface SmartDiagnostics {
	device: string;
	device_type: string;
	model: string;
	serial: string;
	raw_output_available: boolean;
	missing_fields: string[];
	guidance: string[];
	timestamp: string;
}

export interface SmartTestResult {
	diagnostics: SmartDiagnostics;
	health: SmartHealth;
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

/**
 * Get overall system health including uptime, storage, SMART, and OpenSearch status.
 */
export async function getSystemHealth(): Promise<SystemHealth> {
	const res = await fetch('/api/system/health');

	// OLD CODE START — #96: a failed request read as "Degraded", OpenSearch unreachable
	// if (!res.ok) {
	// 	return {
	// 		uptime: 0,
	// 		timestamp: new Date().toISOString(),
	// 		storage: null,
	// 		smart: null,
	// 		opensearch_reachable: false,
	// 		healthy: false,
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) {
		throw new Error(`System health request failed: HTTP ${res.status}`);
	}

	return res.json();
}

/**
 * Get detailed storage/disk usage and retention policy status.
 */
export async function getStorageStatus(): Promise<StorageStatus> {
	const res = await fetch('/api/storage/status');

	// OLD CODE START — #96: a failed request read as "0.0% used"
	// if (!res.ok) {
	// 	return {
	// 		disk_usage_percent: 0,
	// 		disk_total_bytes: 0,
	// 		disk_used_bytes: 0,
	// 		disk_free_bytes: 0,
	// 		retention: null,
	// 		index_summary: null,
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) {
		throw new Error(`Storage status request failed: HTTP ${res.status}`);
	}

	return res.json();
}

/**
 * Get SSD/NVMe SMART health data.
 */
export async function getSmartHealth(): Promise<SmartHealth> {
	const res = await fetch('/api/smart/health');

	// OLD CODE START — #96: a failed request read as drive "Degraded", smartmontools missing
	// if (!res.ok) {
	// 	return {
	// 		device: '',
	// 		device_type: '',
	// 		model: '',
	// 		serial: '',
	// 		temperature_c: null,
	// 		percentage_used: null,
	// 		power_on_hours: null,
	// 		total_bytes_written: null,
	// 		total_bytes_read: null,
	// 		media_errors: null,
	// 		reallocated_sectors: null,
	// 		healthy: false,
	// 		warnings: [],
	// 		timestamp: new Date().toISOString(),
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) {
		throw new Error(`Drive health request failed: HTTP ${res.status}`);
	}

	return res.json();
}

/**
 * Get the list of OpenSearch indices managed by the daemon.
 */
export async function getIndices(): Promise<{ indices: any[]; count: number }> {
	const res = await fetch('/api/indices');

	if (!res.ok) {
		return { indices: [], count: 0 };
	}

	return res.json();
}

/**
 * Get SMART self-test diagnostics (missing fields, guidance messages).
 */
export async function getSmartDiagnostics(): Promise<SmartDiagnostics> {
	const res = await fetch('/api/smart/diagnostics');

	if (!res.ok) {
		return {
			device: '',
			device_type: '',
			model: '',
			serial: '',
			raw_output_available: false,
			missing_fields: [],
			guidance: [],
			timestamp: new Date().toISOString(),
		};
	}

	return res.json();
}

/**
 * Trigger an on-demand SMART check and return fresh diagnostics + health.
 */
export async function runSmartTest(): Promise<SmartTestResult> {
	const res = await fetch('/api/smart/test', { method: 'POST' });

	if (!res.ok) {
		return {
			diagnostics: {
				device: '',
				device_type: '',
				model: '',
				serial: '',
				raw_output_available: false,
				missing_fields: [],
				guidance: [],
				timestamp: new Date().toISOString(),
			},
			health: {
				device: '',
				device_type: '',
				model: '',
				serial: '',
				temperature_c: null,
				percentage_used: null,
				power_on_hours: null,
				total_bytes_written: null,
				total_bytes_read: null,
				media_errors: null,
				reallocated_sectors: null,
				healthy: false,
				warnings: [],
				timestamp: new Date().toISOString(),
			},
		};
	}

	return res.json();
}
