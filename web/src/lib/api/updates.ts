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

/** One update run as the daemon keeps it in its history: what it was asked to update and each result. */
export interface UpdateBatch {
	results: UpdateResult[];
	components: string[];
	success: boolean;
	started_at: string;
	completed_at: string;
}

/** A history row: one result, with a key unique in the list (a batch can repeat a component). */
export type UpdateHistoryRow = UpdateResult & { key: string };

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
// stale: no check since the daemon started, or the last one is over 6 h old (the page then checks)
export async function getAvailableUpdates(): Promise<{ updates: AvailableUpdate[]; last_check: string; failed_checks?: string[]; checked?: string[]; stale?: boolean }> {
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
export async function checkForUpdates(): Promise<{ updates: AvailableUpdate[]; last_check?: string; failed_checks?: string[]; checked?: string[] }> {
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
		// OLD CODE START — dropped the daemon's reason (e.g. a 400's "components must be names NetTap can update")
		// return {
		// 	state: 'error',
		// 	components: [],
		// 	current_component: null,
		// 	current_step: null,
		// 	progress_percent: 0,
		// 	started_at: null,
		// 	completed_at: null,
		// 	results: [],
		// };
		// OLD CODE END
		throw new Error(await errorText(res));
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
 * The daemon's update history as it sends it: one batch per update run, newest first.
 */
export async function getUpdateHistoryBatches(): Promise<UpdateBatch[]> {
	const res = await fetch('/api/system/updates/history');
	if (!res.ok) {
		throw new Error(`Update history request failed: HTTP ${res.status}`);
	}
	const body: { history: UpdateBatch[]; count: number } = await res.json();
	return body.history;
}

/**
 * The history of past updates, one row per component result, newest batch first.
 */
// OLD CODE START — returned the daemon's batches as if each were one component's result, so every
// history row read "undefined → undefined" with no component
// export async function getUpdateHistory(): Promise<UpdateResult[]> {
// 	const res = await fetch('/api/system/updates/history');
//
// 	// OLD CODE START — the daemon replies {history, count}, so this object never read as a list and
// 	// the history never showed; a failure also read as "no past updates"
// 	// if (!res.ok) {
// 	// 	return [];
// 	// }
// 	//
// 	// return res.json();
// 	// OLD CODE END
// 	if (!res.ok) {
// 		throw new Error(`Update history request failed: HTTP ${res.status}`);
// 	}
//
// 	const body: { history: UpdateResult[]; count: number } = await res.json();
// 	return body.history;
// }
// OLD CODE END
export async function getUpdateHistory(): Promise<UpdateHistoryRow[]> {
	const batches = await getUpdateHistoryBatches();
	return batches.flatMap((batch, b) => (batch.results ?? []).map((result, r) => ({ ...result, key: `${b}:${r}` })));
}

/**
 * Rollback a specific component to its previous version.
 */
// OLD CODE START — expected {result}, but the daemon sends {success, component, message} (or {error} on a
// 500, and the proxy {error} on a 502), so its reason never reached the page
// export async function rollbackComponent(component: string): Promise<{ result: string }> {
// 	const res = await fetch('/api/system/updates/rollback', {
// 		method: 'POST',
// 		headers: { 'Content-Type': 'application/json' },
// 		body: JSON.stringify({ component }),
// 	});
//
// 	if (!res.ok) {
// 		return { result: 'error' };
// 	}
//
// 	return res.json();
// }
// OLD CODE END
/** Always {success, message}: the daemon's message, its or the proxy's error, or the HTTP status. Throws only when the request itself fails. */
export async function rollbackComponent(component: string): Promise<{ success: boolean; message: string }> {
	const res = await fetch('/api/system/updates/rollback', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ component }),
	});
	const body = await readBody(res);
	if (res.ok && body.success === true) {
		return { success: true, message: typeof body.message === 'string' ? body.message : '' };
	}
	return { success: false, message: textOf(body, res.status) };
}

/** A response's JSON object, or {} when it has none. */
async function readBody(res: Response): Promise<Record<string, unknown>> {
	const body: unknown = await res.json().catch(() => ({}));
	return body && typeof body === 'object' ? (body as Record<string, unknown>) : {};
}

/** What a failed reply says: its message, else its error, else that it failed, with its HTTP status. */
function textOf(body: Record<string, unknown>, status: number): string {
	for (const key of ['message', 'error']) {
		const value = body[key];
		if (typeof value === 'string' && value) return value;
	}
	return `the request failed (HTTP ${status}).`;
}

async function errorText(res: Response): Promise<string> {
	return textOf(await readBody(res), res.status);
}
