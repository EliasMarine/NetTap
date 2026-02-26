/**
 * Client-side API helpers for system health, storage, and SMART monitoring endpoints.
 * These functions call the SvelteKit server proxy routes which in turn
 * forward requests to the nettap-storage-daemon.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SystemHealth {
	uptime: number;
	timestamp: string;
	storage: any;
	smart: any;
	opensearch_reachable: boolean;
	healthy: boolean;
}

export interface StorageStatus {
	disk_usage_percent: number;
	disk_total_bytes: number;
	disk_used_bytes: number;
	disk_free_bytes: number;
	retention: any;
	index_summary: any;
}

export interface SmartHealth {
	device: string;
	model: string;
	temperature_c: number;
	percentage_used: number;
	power_on_hours: number;
	healthy: boolean;
	warnings: string[];
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

/**
 * Get overall system health including uptime, storage, SMART, and OpenSearch status.
 */
export async function getSystemHealth(): Promise<SystemHealth> {
	const res = await fetch('/api/system/health');

	if (!res.ok) {
		return {
			uptime: 0,
			timestamp: new Date().toISOString(),
			storage: null,
			smart: null,
			opensearch_reachable: false,
			healthy: false,
		};
	}

	return res.json();
}

/**
 * Get detailed storage/disk usage and retention policy status.
 */
export async function getStorageStatus(): Promise<StorageStatus> {
	const res = await fetch('/api/storage/status');

	if (!res.ok) {
		return {
			disk_usage_percent: 0,
			disk_total_bytes: 0,
			disk_used_bytes: 0,
			disk_free_bytes: 0,
			retention: null,
			index_summary: null,
		};
	}

	return res.json();
}

/**
 * Get SSD/NVMe SMART health data.
 */
export async function getSmartHealth(): Promise<SmartHealth> {
	const res = await fetch('/api/smart/health');

	if (!res.ok) {
		return {
			device: '',
			model: '',
			temperature_c: 0,
			percentage_used: 0,
			power_on_hours: 0,
			healthy: false,
			warnings: [],
		};
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
