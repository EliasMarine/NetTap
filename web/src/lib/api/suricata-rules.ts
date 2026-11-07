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
	/** NET-191 slice 3: alert rules in the owner rules file as suricata-live sees it; null when that folder isn't mounted there. */
	owner_rules?: number | null;
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
	/** Configured sources suricata-update didn't enable in an otherwise good update, e.g. "ipfire/dbl"; [] when none. */
	missing_sources: string[];
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

// OLD CODE START — NET-191 slice 3: the owner rules editor replaces the unwired custom rules form
// export interface CustomRulesResult {
// 	success: boolean;
// 	rules_written: number;
// 	file: string;
// }
// OLD CODE END

/** The owner's own rules file (GET /api/suricata/rules/custom, NET-191 slice 3). */
export interface OwnerRules {
	content: string;
	rule_count: number;
	max_rules: number;
	max_bytes: number;
}

/** Why the validator or Suricata refused the rules; `line` is null for a file-wide problem. */
export interface OwnerRuleError {
	line: number | null;
	message: string;
}

/** What a successful save answers (POST /api/suricata/rules/custom, HTTP 200). */
export interface OwnerRulesSaveResult {
	saved: boolean;
	rule_count: number;
	engine: { loaded: number | null; failed: number | null };
}

/** What checking or saving the owner rules answered; `error` and `errors` are the daemon's reasons. */
export interface OwnerRulesReply extends Partial<OwnerRulesSaveResult> {
	ok: boolean;
	status: number;
	error?: string;
	errors: OwnerRuleError[];
	/** false when the web server got no answer from the daemon (timeout or unreachable): the save may or may not have happened. */
	daemonAvailable?: boolean;
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
	// a non-string `error` would break the page's output.slice()
	const error = typeof body?.error === 'string' ? body.error : `Request failed (HTTP ${res.status})`;
	return {
		...body,
		success: res.ok && body?.success === true,
		output: typeof body?.output === 'string' ? body.output : error,
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

// OLD CODE START — NET-191 slice 3: getOwnerRules, checkOwnerRules and saveOwnerRules replace these; the save now
// tests and loads the rules, and its reply has another shape
// /**
//  * Upload custom rules.
//  */
// export async function uploadCustomRules(content: string): Promise<CustomRulesResult> {
// 	const res = await fetch('/api/suricata/rules/custom', {
// 		method: 'POST',
// 		headers: { 'Content-Type': 'application/json' },
// 		body: JSON.stringify({ content }),
// 	});
//
// 	if (!res.ok) {
// 		return { success: false, rules_written: 0, file: '' };
// 	}
//
// 	return res.json();
// }
//
// /**
//  * Get current custom rules content.
//  */
// export async function getCustomRules(): Promise<string> {
// 	const res = await fetch('/api/suricata/rules/custom');
//
// 	// OLD CODE START — #96: a failure showed an empty editor, as if no custom rules were saved
// 	// if (!res.ok) {
// 	// 	return '';
// 	// }
// 	// OLD CODE END
// 	if (!res.ok) throw new Error(`Custom rules failed: HTTP ${res.status}`);
//
// 	const data = await res.json();
// 	return data.content || '';
// }
// OLD CODE END

/** The JSON object in a reply, or {} for anything else (an HTML page, an array, no body). */
async function replyObject(res: Response): Promise<Record<string, unknown>> {
	const body = await res.json().catch(() => null);
	return body && typeof body === 'object' && !Array.isArray(body) ? body : {};
}

/** What a 2xx that isn't a rules answer means: something other than the daemon replied. A lapsed session gets 401 (NET-197). */
const NOT_A_RULES_REPLY = "NetTap's reply wasn't about your rules. Reload the page; you may need to sign in again.";

/** The owner's own rules. Throws on a failed request, so the editor never reads "no rules" for "unknown". */
export async function getOwnerRules(): Promise<OwnerRules> {
	const res = await fetch('/api/suricata/rules/custom');
	const data = await replyObject(res);
	if (!res.ok) throw new Error(typeof data.error === 'string' && data.error ? data.error : `HTTP ${res.status}`);
	// a 2xx that isn't a rules answer must never read as "no rules yet"
	if (typeof data.content !== 'string' || !Number.isFinite(data.max_rules) || !Number.isFinite(data.max_bytes)) {
		throw new Error(NOT_A_RULES_REPLY);
	}
	return data as unknown as OwnerRules;
}

/** Never throws on a 4xx/5xx: `error` is the daemon's sentence and `errors` its per-line reasons. */
async function sendOwnerRules(url: string, content: string): Promise<OwnerRulesReply> {
	const res = await fetch(url, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ content }),
	});
	const body = await replyObject(res);
	// a malformed entry would print "Line undefined" or crash the list; a line that isn't a number reads as file-wide
	const errors: OwnerRuleError[] = Array.isArray(body.errors)
		? body.errors
				.filter((e) => typeof e?.message === 'string')
				.map((e) => ({ line: typeof e.line === 'number' ? e.line : null, message: e.message }))
		: [];
	const error = typeof body.error === 'string' && body.error ? body.error : undefined;
	// success only with the expected shape: a 200 HTML page or {} is not a save
	if (res.ok && (body.saved === true || body.ok === true) && error === undefined) {
		return { ...body, ok: true, status: res.status, errors };
	}
	const fallback = res.ok ? NOT_A_RULES_REPLY : `The request failed (HTTP ${res.status}).`;
	return { ...body, ok: false, status: res.status, error: error ?? fallback, errors };
}

/** Run the validator only: fast, and changes nothing. */
export function checkOwnerRules(content: string): Promise<OwnerRulesReply> {
	return sendOwnerRules('/api/suricata/rules/custom/check', content);
}

/** Validate, test with Suricata and load the rules; up to about 4 minutes. Empty content removes them all. */
export function saveOwnerRules(content: string): Promise<OwnerRulesReply> {
	return sendOwnerRules('/api/suricata/rules/custom', content);
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
