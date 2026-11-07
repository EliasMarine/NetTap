/**
 * Client-side API helpers for Suricata rule management endpoints.
 * These functions call the SvelteKit server proxy routes which in turn
 * forward requests to the nettap-storage-daemon.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** What Suricata really runs, read from its container (GET /api/suricata/rules/live). */
export interface LiveRuleStatus {
	available: boolean;
	enabled_rules: number;
	disabled_rules: number;
	last_updated: string | null;
	sources: string[];
	schedule: string | null; // cron expression, container time (UTC)
	error: string | null;
	// NET-191 slice 2; optional because an older daemon doesn't send them
	/** suricata-update's enabled sources, e.g. "et/open". */
	enabled_sources?: string[];
	/** Active ET Pro rules. */
	etpro_rules?: number;
	/** What Suricata's socket reports; null when it didn't answer. */
	engine?: { loaded: number; failed: number; reload_time: string | null } | null;
	update?: RuleUpdateStatus;
}

/** The last rule update as the daemon recorded it (NET-191 slice 2). */
export interface RuleUpdateStatus {
	state: 'active' | 'prepared' | 'failed' | 'interrupted' | 'unknown';
	attempt: string | null;
	exit_code: number | null;
	reason: string;
	last_success: string | null;
	last_activation: string | null;
	/** No successful update in 48 hours. */
	stale: boolean;
	/** A restore of the last good rules isn't confirmed yet. */
	recovery_pending: boolean;
}

/** The ET Pro code's status (GET /api/suricata/rules/commercial). The code itself is never returned. */
export interface EtProStatus {
	configured: boolean;
	active: boolean;
	last_update_ok: boolean | null;
	/** Suricata is restarting with a new or removed code. */
	applying: boolean;
	activation: null | {
		state: 'active' | 'failed' | 'timeout';
		finished_at: string;
		rules_loaded: number | null;
		rules_failed: number | null;
		etpro_rules: number;
		enabled_sources: string[];
		update_state: string;
		message: string;
	};
}

/** What saving or removing the ET Pro code answered; `error` is the daemon's plain-English reason. */
export interface EtProChange {
	ok: boolean;
	status: number;
	error?: string;
	saved?: boolean;
	cleared?: boolean;
	applying?: boolean;
}

export interface RuleSource {
	id: string;
	enabled: boolean;
	description: string;
}

export interface RuleSourcesResponse {
	sources: RuleSource[];
	count: number;
	last_update: string | null;
}

export interface RuleUpdateResult {
	success: boolean;
	output: string;
	reload_output: string;
	status?: RuleUpdateStatus;
	/** Still running when the daemon stopped waiting (HTTP 202). */
	running?: boolean;
}

export interface RuleStats {
	total_rules: number;
	enabled_sources: number;
	total_sources: number;
	categories: Record<string, number>;
	category_prefixes: Record<string, string>;
}

export interface UpdateSchedule {
	interval: string;
	enabled: boolean;
}

export interface CustomRulesResult {
	success: boolean;
	rules_written: number;
	file: string;
}

// OLD CODE START — NET-191 slice 2: Snort Subscriber is retired; the ET Pro code has EtProStatus
// export interface CommercialConfig {
// 	configured: boolean;
// 	source_type?: string;
// 	license_key_masked?: string;
// 	configured_at?: string;
// }
// OLD CODE END

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

/**
 * Get all rule sources with their enabled/disabled status.
 */
export async function getRuleSources(): Promise<RuleSourcesResponse> {
	const res = await fetch('/api/suricata/rules/sources');

	if (!res.ok) {
		return { sources: [], count: 0, last_update: null };
	}

	return res.json();
}

/**
 * Enable a rule source by ID.
 */
export async function enableRuleSource(id: string): Promise<boolean> {
	const res = await fetch(`/api/suricata/rules/sources/${encodeURIComponent(id)}/enable`, {
		method: 'POST',
	});

	return res.ok;
}

/**
 * Disable a rule source by ID.
 */
export async function disableRuleSource(id: string): Promise<boolean> {
	const res = await fetch(`/api/suricata/rules/sources/${encodeURIComponent(id)}/disable`, {
		method: 'POST',
	});

	return res.ok;
}

/**
 * Trigger an immediate rule update.
 */
export async function updateRulesNow(): Promise<RuleUpdateResult> {
	const res = await fetch('/api/suricata/rules/update', {
		method: 'POST',
	});

	// OLD CODE START — NET-191 slice 2: every non-OK read "Request failed", losing the daemon's reason
	// if (!res.ok) {
	// 	return { success: false, output: 'Request failed', reload_output: '' };
	// }
	//
	// return res.json();
	// OLD CODE END
	// 500 (failed) and 202 (still running) carry the daemon's own body; a proxy error carries `error`
	const body = await res.json().catch(() => ({}));
	return {
		...body,
		success: res.ok && body?.success === true,
		output: typeof body?.output === 'string' ? body.output : (body?.error ?? `Request failed (HTTP ${res.status})`),
		reload_output: body?.reload_output ?? '',
	};
}

/**
 * Get rule statistics by category.
 */
export async function getRuleStats(): Promise<RuleStats> {
	const res = await fetch('/api/suricata/rules/stats');

	if (!res.ok) {
		return { total_rules: 0, enabled_sources: 0, total_sources: 0, categories: {}, category_prefixes: {} };
	}

	return res.json();
}

/**
 * Get current auto-update schedule.
 */
export async function getUpdateSchedule(): Promise<UpdateSchedule> {
	const res = await fetch('/api/suricata/rules/schedule');

	if (!res.ok) {
		return { interval: 'daily', enabled: true };
	}

	return res.json();
}

/**
 * Set auto-update schedule interval.
 */
export async function setUpdateSchedule(interval: string): Promise<UpdateSchedule> {
	const res = await fetch('/api/suricata/rules/schedule', {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ interval }),
	});

	if (!res.ok) {
		return { interval: 'daily', enabled: true };
	}

	return res.json();
}

/**
 * Upload custom rules.
 */
export async function uploadCustomRules(content: string): Promise<CustomRulesResult> {
	const res = await fetch('/api/suricata/rules/custom', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ content }),
	});

	if (!res.ok) {
		return { success: false, rules_written: 0, file: '' };
	}

	return res.json();
}

/**
 * Get current custom rules content.
 */
export async function getCustomRules(): Promise<string> {
	const res = await fetch('/api/suricata/rules/custom');

	// OLD CODE START — #96: a failure showed an empty editor, as if no custom rules were saved
	// if (!res.ok) {
	// 	return '';
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Custom rules failed: HTTP ${res.status}`);

	const data = await res.json();
	return data.content || '';
}

// OLD CODE START — NET-191 slice 2: Snort Subscriber is retired; saveEtProCode, clearEtProCode and getEtProStatus replace these
// /**
//  * Configure commercial rule source (ET Pro / Snort Subscriber).
//  */
// export async function configureCommercial(
// 	sourceType: string,
// 	licenseKey: string
// ): Promise<{ success: boolean }> {
// 	const res = await fetch('/api/suricata/rules/commercial', {
// 		method: 'POST',
// 		headers: { 'Content-Type': 'application/json' },
// 		body: JSON.stringify({ source_type: sourceType, license_key: licenseKey }),
// 	});
//
// 	if (!res.ok) {
// 		return { success: false };
// 	}
//
// 	return res.json();
// }
//
// /**
//  * Get current commercial config (key masked).
//  */
// export async function getCommercialConfig(): Promise<CommercialConfig> {
// 	const res = await fetch('/api/suricata/rules/commercial');
//
// 	// OLD CODE START — #96: a failure read as "no commercial license configured"
// 	// if (!res.ok) {
// 	// 	return { configured: false };
// 	// }
// 	// OLD CODE END
// 	if (!res.ok) throw new Error(`Commercial config failed: HTTP ${res.status}`);
//
// 	return res.json();
// }
// OLD CODE END

/** Whether an ET Pro code is saved and in use. Throws on a failed request, so the page never reads "Not set" for "unknown". */
export async function getEtProStatus(): Promise<EtProStatus> {
	const res = await fetch('/api/suricata/rules/commercial');
	if (!res.ok) throw new Error(`ET Pro status failed: HTTP ${res.status}`);
	return res.json();
}

/** Never throws on a 4xx/5xx: the daemon's `error` says why, and never contains the code. */
async function changeEtPro(init: RequestInit): Promise<EtProChange> {
	const res = await fetch('/api/suricata/rules/commercial', init);
	const body = await res.json().catch(() => ({}));
	if (res.ok) return { ...body, ok: true, status: res.status };
	const error = typeof body?.error === 'string' && body.error ? body.error : `The request failed (HTTP ${res.status}).`;
	return { ...body, ok: false, status: res.status, error };
}

/** Save the ET Pro code (the daemon checks it with Proofpoint first, then restarts Suricata). */
export function saveEtProCode(code: string): Promise<EtProChange> {
	return changeEtPro({
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ code }),
	});
}

/** Remove the ET Pro code; Suricata restarts on ET Open. */
export function clearEtProCode(): Promise<EtProChange> {
	return changeEtPro({ method: 'DELETE' });
}

/**
 * Rule counts, last refresh, sources and schedule Suricata really uses.
 * Throws with the daemon's error text when Suricata could not be read, so the
 * page never shows 0 rules for "unknown".
 */
export async function getLiveRuleStatus(): Promise<LiveRuleStatus> {
	const res = await fetch('/api/suricata/rules/live');
	const data = await res.json().catch(() => ({}));
	if (!res.ok || data?.available !== true) {
		throw new Error(typeof data?.error === 'string' && data.error ? data.error : `HTTP ${res.status}`);
	}
	return data as LiveRuleStatus;
}
