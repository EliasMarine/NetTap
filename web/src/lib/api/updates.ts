/**
 * Client-side API helpers for software update management endpoints.
 * These functions call the SvelteKit server proxy routes which in turn
 * forward requests to the nettap-storage-daemon.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ComponentVersion {
	name: string;
	category: 'core' | 'docker' | 'system' | 'database' | 'os';
	current_version: string;
	install_type: string;
	last_checked: string;
	status: 'ok' | 'unknown' | 'error';
	details: Record<string, any>;
}

export interface AvailableUpdate {
	component: string;
	current_version: string;
	latest_version: string;
	update_type: 'major' | 'minor' | 'patch' | 'unknown';
	release_url: string;
	release_date: string;
	changelog: string;
	// OLD CODE START — the daemon sends null when nobody measured the size
	// size_mb: number;
	// OLD CODE END
	/** null = not measured: show "size unknown", never 0 MB */
	size_mb: number | null;
	requires_restart: boolean;
	/** Set when NetTap can't apply this update itself: how it does arrive (one sentence) */
	applies_with?: string | null;
}

export interface UpdateStatus {
	state: 'idle' | 'in_progress' | 'completed' | 'error';
	/** The batch being (or last) applied; [] when idle with no history */
	components: string[];
	current_component: string | null;
	/** Plain-English step, shown as is */
	current_step: string | null;
	progress_percent: number;
	started_at: string | null;
	completed_at: string | null;
	results: UpdateResult[];
	/** Set by applyUpdates on a 409: this is the update that was already running */
	already_running?: boolean;
}

export interface UpdateResult {
	component: string;
	success: boolean;
	old_version: string;
	new_version: string;
	started_at: string;
	completed_at: string;
	error: string | null;
	rollback_available: boolean;
}

export interface AutoUpdateConfig {
	suricata_rules_daily: boolean;
	geoip_weekly: boolean;
	containers_auto: boolean;
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

/**
 * Get all component versions currently installed on the appliance.
 */
// OLD CODE: export async function getVersions(): Promise<{ versions: Record<string, ComponentVersion>; last_scan: string }> { (NET-237: the daemon sends a list)
export async function getVersions(): Promise<{ versions: ComponentVersion[]; last_scan: string }> {
	const res = await fetch('/api/system/versions');

	// OLD CODE START — #96: a failed request read as "No version information available"
	// if (!res.ok) {
	// 	return {
	// 		versions: {},
	// 		last_scan: '',
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) {
		throw new Error(`Installed versions request failed: HTTP ${res.status}`);
	}

	return res.json();
}

/**
 * Trigger a fresh scan of all component versions.
 */
// OLD CODE: export async function scanVersions(): Promise<{ versions: Record<string, ComponentVersion> }> { (NET-237: a list)
export async function scanVersions(): Promise<{ versions: ComponentVersion[] }> {
	const res = await fetch('/api/system/versions/scan', {
		method: 'POST',
	});

	if (!res.ok) {
		// OLD CODE: return { versions: {} }; (NET-237)
		return { versions: [] };
	}

	return res.json();
}

/**
 * Get a list of available updates that have been previously checked.
 */
export async function getAvailableUpdates(): Promise<{ updates: AvailableUpdate[]; last_check: string; failed_checks?: string[]; checked?: string[] }> {
	const res = await fetch('/api/system/updates/available');

	// OLD CODE START — #96: a failed request marked every component "Up to Date"
	// if (!res.ok) {
	// 	return {
	// 		updates: [],
	// 		last_check: '',
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) {
		throw new Error(`Available updates request failed: HTTP ${res.status}`);
	}

	return res.json();
}

/**
 * Check for new updates from upstream sources.
 */
export async function checkForUpdates(): Promise<{ updates: AvailableUpdate[]; failed_checks?: string[]; checked?: string[] }> {
	const res = await fetch('/api/system/updates/check', {
		method: 'POST',
	});

	// OLD CODE START — #96: a failed check read as "Up to Date, last checked just now"
	// if (!res.ok) {
	// 	return { updates: [] };
	// }
	// OLD CODE END
	if (!res.ok) {
		throw new Error(`Update check failed: HTTP ${res.status}`);
	}

	return res.json();
}

/**
 * Start applying updates to the specified components. The daemon works in the background;
 * follow it with getUpdateStatus().
 */
export async function applyUpdates(components: string[]): Promise<UpdateStatus> {
	const res = await fetch('/api/system/updates/apply', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ components }),
	});

	// The daemon answers 202 with the started update's status (res.ok covers it), or 409 with the
	// status of the update already running, so the caller can follow that one instead
	if (res.status === 409) {
		const running: UpdateStatus = await res.json();
		return { ...running, already_running: true };
	}

	if (!res.ok) {
		// OLD CODE START — before components/current_step/completed_at were part of the status
		// return {
		// 	state: 'error',
		// 	current_component: null,
		// 	progress_percent: 0,
		// 	started_at: null,
		// 	results: [],
		// };
		// OLD CODE END
		return {
			state: 'error',
			components: [],
			current_component: null,
			current_step: null,
			progress_percent: 0,
			started_at: null,
			completed_at: null,
			results: [],
		};
	}

	return res.json();
}

/**
 * Get the current status of an in-progress or completed update operation.
 */
export async function getUpdateStatus(): Promise<UpdateStatus> {
	const res = await fetch('/api/system/updates/status');

	// OLD CODE START — #96: a failed request read as "idle", which ended a running update as "Update Complete"
	// if (!res.ok) {
	// 	return {
	// 		state: 'idle',
	// 		current_component: null,
	// 		progress_percent: 0,
	// 		started_at: null,
	// 		results: [],
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) {
		throw new Error(`Update status request failed: HTTP ${res.status}`);
	}

	return res.json();
}

/**
 * Get the history of past update operations.
 */
export async function getUpdateHistory(): Promise<UpdateResult[]> {
	const res = await fetch('/api/system/updates/history');

	// OLD CODE START — the daemon replies {history, count}, so this object never read as a list and
	// the history never showed; a failure also read as "no past updates"
	// if (!res.ok) {
	// 	return [];
	// }
	//
	// return res.json();
	// OLD CODE END
	if (!res.ok) {
		throw new Error(`Update history request failed: HTTP ${res.status}`);
	}

	const body: { history: UpdateResult[]; count: number } = await res.json();
	return body.history;
}

/**
 * Rollback a specific component to its previous version.
 */
export async function rollbackComponent(component: string): Promise<{ result: string }> {
	const res = await fetch('/api/system/updates/rollback', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ component }),
	});

	if (!res.ok) {
		return { result: 'error' };
	}

	return res.json();
}
