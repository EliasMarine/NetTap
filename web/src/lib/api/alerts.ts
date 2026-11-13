/**
 * Client-side API helpers for alert/IDS endpoints.
 * These functions call the SvelteKit server proxy routes which in turn
 * forward requests to the nettap-storage-daemon.
 */
import { formatCompactNumber } from './logs';
import type { BaselineInfo } from './threats';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Time range options shared by alert queries. */
export interface TimeRangeParams {
	from?: string;
	to?: string;
}

export interface AlertSeverityCounts {
	total: number;
	high: number;
	medium: number;
	low: number;
}

export interface AlertCountResponse {
	from: string;
	to: string;
	counts: AlertSeverityCounts;
}

export interface Alert {
	_id: string;
	_index: string;
	timestamp: string;
	alert?: {
		signature?: string;
		signature_id?: number;
		severity?: number;
		category?: string;
		/** The stored rule.category values that pass the daemon's name check, which the list's `suricata_category` matches (NET-160 slice 2b-2) */
		rule_category?: string[];
	};
	src_ip?: string;
	src_port?: number;
	dest_ip?: string;
	dest_port?: number;
	proto?: string;
	/** The raw rule name the list's `signature` filter matches (the shown signature can differ) */
	rule?: { name?: string };
	acknowledged: boolean;
	acknowledged_at?: string;
	[key: string]: unknown;
}

export interface AlertsListResponse {
	from: string;
	to: string;
	page: number;
	size: number;
	total: number;
	total_pages: number;
	alerts: Alert[];
}

export interface AlertDetailResponse {
	alert: Alert;
}

export interface AlertAcknowledgeResponse {
	result: string;
	alert_id: string;
	acknowledged_at: string;
	acknowledged_by: string;
}

export interface AlertTimelineBucket {
	timestamp: string;
	high: number;
	medium: number;
	low: number;
	/** alerts without Suricata severity 1-3, as the Info tile counts them (I1); absent on an older daemon */
	info?: number;
}

export interface AlertTimelineResponse {
	from: string;
	to: string;
	interval: string;
	buckets: AlertTimelineBucket[];
}

export interface AlertSignature {
	// OLD CODE: signature: string; (NET-160: alerts with no rule.name come back as their own null row)
	/** The rule.name; null for the alerts that have none ("" and "Unknown" are rows of their own). */
	signature: string | null;
	count: number;
	severity: number;
}

export interface AlertTopSignaturesResponse {
	from: string;
	to: string;
	signatures: AlertSignature[];
	/** false: too many rule names to read them all, so the rows are the busiest among those read (NET-160) */
	complete: boolean;
	/** Rule names read; every distinct one when complete */
	examined: number;
}

export interface AlertIpEntry {
	ip: string;
	count: number;
}

export interface AlertTopIpsResponse {
	from: string;
	to: string;
	// OLD CODE: direction: string; (NET-160: the daemon answers one of the two)
	direction: 'src' | 'dest';
	ips: AlertIpEntry[];
	/** false: too many addresses to read them all, so the rows are the busiest among those read (NET-160) */
	complete: boolean;
	/** Addresses read; every distinct one when complete */
	examined: number;
}

export interface AlertCategoryEntry {
	category: string;
	count: number;
}

export interface AlertCategoriesResponse {
	from: string;
	to: string;
	categories: AlertCategoryEntry[];
}

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function buildQuery(params: Record<string, string | number | undefined>): string {
	const qs = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (value !== undefined && value !== '') {
			qs.set(key, String(value));
		}
	}
	const str = qs.toString();
	return str ? `?${str}` : '';
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

/** The alert tables' columns the daemon sorts on; severity "desc" is the most severe first (#146). */
export type AlertSort = 'time' | 'severity' | 'signature' | 'source' | 'destination' | 'dest_port' | 'proto' | 'category';

/**
 * Get paginated alert list with optional severity filter.
 * Severity: 1=high, 2=medium, 3=low.
 */
// OLD CODE START — #146: no sort, so the alert tables ordered only the page of rows they had
// export async function getAlerts(
// 	opts: TimeRangeParams & {
// 		severity?: number;
// 		page?: number;
// 		size?: number;
// 		ip?: string;
// 		signature?: string;
// 		category?: string;
// 	} = {}
// ): Promise<AlertsListResponse> {
// 	const query = buildQuery({
// 		from: opts.from,
// 		to: opts.to,
// 		severity: opts.severity,
// 		page: opts.page,
// 		size: opts.size,
// 		ip: opts.ip,
// 		signature: opts.signature,
// 		category: opts.category,
// 	});
// OLD CODE END
export async function getAlerts(
	opts: TimeRangeParams & {
		/** 1, 2 or 3, or 'info' for anything else (I1) */
		severity?: number | 'info';
		page?: number;
		size?: number;
		ip?: string;
		/** the alert's source and destination address (a smart alert's pair, NET-160 slice 2b-1) */
		src?: string;
		dst?: string;
		signature?: string;
		category?: string;
		/** a sub-category of `category` (#147) */
		sub?: string;
		/** one raw Suricata category, an exact match on rule.category (NET-160 slice 2b-2) */
		suricata_category?: string;
		sort?: AlertSort;
		order?: 'asc' | 'desc';
		/** list the activity alerts (ET rates them informational or unknown, never counted) instead (NET-191) */
		activity?: boolean;
		/** only the alerts with no rule name, a Top signatures bar's null row (NET-185) */
		no_rule_name?: boolean;
	} = {}
): Promise<AlertsListResponse> {
	const query = buildQuery({
		from: opts.from,
		to: opts.to,
		severity: opts.severity,
		page: opts.page,
		size: opts.size,
		ip: opts.ip,
		src: opts.src,
		dst: opts.dst,
		signature: opts.signature,
		category: opts.category,
		sub: opts.sub,
		suricata_category: opts.suricata_category,
		sort: opts.sort,
		order: opts.order,
		activity: opts.activity ? 'true' : undefined,
		no_rule_name: opts.no_rule_name ? 'true' : undefined,
	});
	const res = await fetch(`/api/alerts${query}`);

	// OLD CODE START — #96: a failure read as "No Alerts"
	// if (!res.ok) {
	// 	return {
	// 		from: '',
	// 		to: '',
	// 		page: opts.page ?? 1,
	// 		size: opts.size ?? 50,
	// 		total: 0,
	// 		total_pages: 0,
	// 		alerts: [],
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Alerts failed: HTTP ${res.status}`);

	return res.json();
}

/**
 * Get alert counts grouped by severity.
 */
// OLD CODE START — NET-191: counted alerts only
// export async function getAlertCount(
// 	opts: TimeRangeParams = {}
// ): Promise<AlertCountResponse> {
// 	const query = buildQuery({ from: opts.from, to: opts.to });
// OLD CODE END
export async function getAlertCount(
	/** `activity`: count the activity alerts (ET rates them informational or unknown) instead */
	opts: TimeRangeParams & { activity?: boolean } = {}
): Promise<AlertCountResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to, activity: opts.activity ? 'true' : undefined });
	const res = await fetch(`/api/alerts/count${query}`);

	// OLD CODE START — #96: a failure read as zero alerts
	// if (!res.ok) {
	// 	return {
	// 		from: '',
	// 		to: '',
	// 		counts: { total: 0, high: 0, medium: 0, low: 0 },
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Alert count failed: HTTP ${res.status}`);

	return res.json();
}

/**
 * Get a single alert detail by OpenSearch _id.
 */
export async function getAlertDetail(id: string): Promise<AlertDetailResponse | null> {
	const res = await fetch(`/api/alerts/${encodeURIComponent(id)}`);

	// OLD CODE START — #96: a failed request read the same as "no such alert"
	// if (!res.ok) {
	// 	return null;
	// }
	// OLD CODE END
	if (res.status === 404) return null;
	if (!res.ok) throw new Error(`Alert detail failed: HTTP ${res.status}`);

	return res.json();
}

/**
 * Mark an alert as acknowledged.
 */
export async function acknowledgeAlert(
	id: string,
	acknowledgedBy?: string
): Promise<AlertAcknowledgeResponse | null> {
	const body: Record<string, string> = {};
	if (acknowledgedBy) {
		body.acknowledged_by = acknowledgedBy;
	}

	const res = await fetch(`/api/alerts/${encodeURIComponent(id)}`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body),
	});

	if (!res.ok) {
		return null;
	}

	return res.json();
}

/**
 * Get alert timeline (date_histogram bucketed by severity).
 */
export async function getAlertTimeline(
	opts: TimeRangeParams & { interval?: string } = {}
): Promise<AlertTimelineResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to, interval: opts.interval });
	const res = await fetch(`/api/alerts/timeline${query}`);

	// OLD CODE START — #96: a failure read as "No timeline data available"
	// if (!res.ok) {
	// 	return { from: '', to: '', interval: opts.interval || '1h', buckets: [] };
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Alert timeline failed: HTTP ${res.status}`);

	return res.json();
}

/**
 * Get top triggered alert signatures.
 */
export async function getAlertTopSignatures(
	opts: TimeRangeParams & { limit?: number } = {}
): Promise<AlertTopSignaturesResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to, limit: opts.limit });
	const res = await fetch(`/api/alerts/top-signatures${query}`);

	// OLD CODE START — #96: a failure read as "No signatures found"
	// if (!res.ok) {
	// 	return { from: '', to: '', signatures: [] };
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Top signatures failed: HTTP ${res.status}`);

	return res.json();
}

/**
 * Get top IPs seen in alerts (source or destination).
 */
export async function getAlertTopIps(
	// OLD CODE: opts: TimeRangeParams & { limit?: number; direction?: string } = {} (NET-160: src or dest only)
	opts: TimeRangeParams & { limit?: number; direction?: 'src' | 'dest' } = {}
): Promise<AlertTopIpsResponse> {
	const query = buildQuery({
		from: opts.from,
		to: opts.to,
		limit: opts.limit,
		direction: opts.direction,
	});
	const res = await fetch(`/api/alerts/top-ips${query}`);

	// OLD CODE START — #96: a failure read as "No source/destination IPs found"
	// if (!res.ok) {
	// 	return { from: '', to: '', direction: opts.direction || 'dest', ips: [] };
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Top alert IPs failed: HTTP ${res.status}`);

	return res.json();
}

/**
 * Get alert counts grouped by rule category.
 */
export async function getAlertCategories(
	opts: TimeRangeParams = {}
): Promise<AlertCategoriesResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/alerts/categories${query}`);

	// OLD CODE START — #96: a failure read as no alert categories
	// if (!res.ok) {
	// 	return { from: '', to: '', categories: [] };
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Alert categories failed: HTTP ${res.status}`);

	return res.json();
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

/**
 * Format a number with compact notation (e.g. 1.2K, 3.4M).
 */
// OLD CODE START — one compact format for the app (NET-192 PR 4): formatCompactNumber in $lib/api/logs
// export function formatNumber(n: number): string {
// 	if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
// 	if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
// 	return String(n);
// }
// OLD CODE END
export const formatNumber = formatCompactNumber;

/**
 * Severity number to human label.
 */
export function severityLabel(severity: number | undefined): string {
	switch (severity) {
		case 1:
			return 'HIGH';
		case 2:
			return 'MEDIUM';
		case 3:
			return 'LOW';
		default:
			return 'INFO';
	}
}

/**
 * Severity number to CSS badge class.
 */
export function severityBadgeClass(severity: number | undefined): string {
	switch (severity) {
		case 1:
			return 'badge severity-high';
		case 2:
			return 'badge severity-medium';
		case 3:
			return 'badge severity-low';
		default:
			return 'badge severity-info';
	}
}

// ---------------------------------------------------------------------------
// Smart Alert types & helpers (alert intelligence layer)
// ---------------------------------------------------------------------------

/** A grouped, deduplicated, severity-ranked smart alert. */
export interface SmartAlert {
	signature_id: number;
	signature: string;
	suricata_category: string;
	severity: number;
	severity_label: string;
	category: string;
	category_label: string;
	source_ip: string;
	destination_ip: string;
	count: number;
	first_seen: string;
	last_seen: string;
	trend: string;
	assessment: string;
	destination_port?: number;
	/**
	 * The group's own bucket values, null when the alerts had none: the exact Alerts list for this
	 * ×N (NET-160 slice 2b-1). `signature` above can be the sample's display name instead.
	 * Absent from an older daemon.
	 */
	key?: SmartAlertKey;
	/** ET rates the group's alerts informational or unknown: activity, not counted (NET-191). Absent from an older daemon. */
	activity?: boolean;
}

export interface SmartAlertKey {
	rule_name: string | null;
	source_ip: string | null;
	destination_ip: string | null;
}

export interface SmartAlertsResponse {
	from: string;
	to: string;
	device_ip: string | null;
	alerts: SmartAlert[];
	total: number;
}

/**
 * NET-164: how the threat score is worked out, as daemon/services/alert_intelligence.py does it
 * (get_smart_alert_summary). Its rules are pinned by tests in daemon/tests/test_smart_alert_paging.py.
 */
// OLD CODE START — NET-209: the score now counts findings (one signature on one device), caps inbound attempts and skips blocklist hits devices did not start
// export const THREAT_SCORE_HOW =
// 	'Each alert group adds 10 (critical), 5 (high), 2 (medium) or 0.5 (low), rounded down and capped at 100. A busier-than-usual window adds 15 while the score is under 75. The level never exceeds the worst alert.';
// OLD CODE END
// OLD CODE START — NET-225 (ALR-3): left out the alerts no device is charged with, which _finding_points scores at full weight
// export const THREAT_SCORE_HOW =
// 	'Each finding, one signature on one device, adds 10 (critical), 5 (high), 2 (medium) or 0.5 (low). An attempt from the internet against a device adds at most 0.5, and blocklist hits your devices did not start are not counted. Rounded down and capped at 100. A busier-than-usual window adds 15 while the score is under 75. The level never exceeds the worst alert.';
// OLD CODE END
export const THREAT_SCORE_HOW =
	"Each finding, one signature on one device, adds 10 (critical), 5 (high), 2 (medium) or 0.5 (low). An attempt from the internet against a device adds at most 0.5, and blocklist hits your devices did not start are not counted. An alert with neither address in NetTap's LAN subnets (all IPv6 traffic, for example) can't be charged to a device, so neither rule applies: it adds its full weight once per signature, source and destination. Rounded down and capped at 100. A busier-than-usual window adds 15 while the score is under 75. The level never exceeds the worst alert.";

/** NET-225 (ALR-3): what the score counts when NetTap sits after the router's address translation. */
export const THREAT_SCORE_BRIDGE =
	"Inline bridge mode: your router's address translation hides your devices behind its IPv4 address, so alerts can't be charged to the device behind it. An alert with neither address in NetTap's LAN subnets adds its full weight, once per signature, source and destination, even for unsolicited scans from the internet that your router blocks.";

export interface SmartAlertSummary {
	from: string;
	to: string;
	threat_score: number;
	threat_level: string;
	total_groups: number;
	total_events: number;
	/** Alerts rated informational (STUN, DoH, ...) and left out of the groups above */
	informational_events?: number;
	categories: Record<string, { label: string; groups: number; events: number }>;
	top_threats: SmartAlert[];
	/** NET-239: null for one device's view or a failed baseline update */
	baseline?: BaselineInfo | null;
	/** NET-239: scoring findings left out by suppressions or false-positive marks. Absent from an older daemon. */
	suppressed_findings?: number;
	/** NET-239: 15 when the busier-than-usual +15 applied, else 0. Absent from an older daemon. */
	busier_window_points?: number;
}

/** Earlier hours the daemon needs before it compares a window with them (_MIN_BASELINE_HOURS). */
const BASELINE_MIN_HOURS = 6;

/**
 * NET-239: the score's two hidden inputs, in words for under THREAT_SCORE_HOW: findings that
 * suppressions left out, and whether the busier-than-usual +15 applied. A reply without the
 * fields (an older daemon) says nothing rather than a guess.
 */
export function scoreInputs(
	summary: Pick<SmartAlertSummary, 'baseline' | 'suppressed_findings' | 'busier_window_points'>
): string[] {
	return [
		suppressedSentence(summary.suppressed_findings),
		baselineSentence(summary.baseline, summary.busier_window_points)
	].filter((s): s is string => s !== null);
}

function suppressedSentence(n: number | undefined): string | null {
	if (typeof n !== 'number' || n <= 0) return null;
	return n === 1
		? '1 finding in this window was left out by your suppressions or false-positive marks.'
		: `${formatNumber(n)} findings in this window were left out by your suppressions or false-positive marks.`;
}

function baselineSentence(b: BaselineInfo | null | undefined, points: number | undefined): string | null {
	if (!b || typeof b.ready !== 'boolean' || typeof b.earlier_hours !== 'number' || typeof points !== 'number') {
		return null;
	}
	if (!b.ready) {
		return `Still learning what's usual: ${b.earlier_hours} of ${BASELINE_MIN_HOURS} earlier hours recorded, so no +15 yet.`;
	}
	const usual = `the usual ${formatNumber(b.avg_events)} events`;
	// the daemon's is_anomalous is deviation > 2, so 1.9× is busier, just not enough
	if (!b.is_anomalous) return `Not busy enough for the +15 (${b.deviation}× ${usual}; it takes more than 2×).`;
	return points === 15
		? `Busier than usual (${b.deviation}× ${usual}), so +15.`
		: `Busier than usual (${b.deviation}×), but the score was already 75 or more, so no +15.`;
}

/**
 * Get grouped smart alerts with optional device filter.
 */
export async function getSmartAlerts(
	opts: {
		from?: string;
		to?: string;
		device_ip?: string;
		include_info?: boolean;
		limit?: number;
	} = {}
): Promise<SmartAlertsResponse> {
	const qs = new URLSearchParams();
	if (opts.from) qs.set('from', opts.from);
	if (opts.to) qs.set('to', opts.to);
	if (opts.device_ip) qs.set('device_ip', opts.device_ip);
	if (opts.include_info) qs.set('include_info', 'true');
	if (opts.limit) qs.set('limit', String(opts.limit));
	const query = qs.toString() ? `?${qs.toString()}` : '';
	const res = await fetch(`/api/alerts/smart${query}`);

	// OLD CODE START — #96: a failure read as "No actionable alerts"
	// if (!res.ok) {
	// 	return { from: '', to: '', device_ip: null, alerts: [], total: 0 };
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Smart alerts failed: HTTP ${res.status}`);

	return res.json();
}

/**
 * Get smart alert summary with threat score, categories, and top threats.
 */
export async function getSmartAlertSummary(
	opts: {
		from?: string;
		to?: string;
		device_ip?: string;
	} = {}
): Promise<SmartAlertSummary> {
	const qs = new URLSearchParams();
	if (opts.from) qs.set('from', opts.from);
	if (opts.to) qs.set('to', opts.to);
	if (opts.device_ip) qs.set('device_ip', opts.device_ip);
	const query = qs.toString() ? `?${qs.toString()}` : '';
	const res = await fetch(`/api/alerts/smart/summary${query}`);

	// OLD CODE START — #96: a failure read as threat level "none" with nothing to review
	// if (!res.ok) {
	// 	return {
	// 		from: '',
	// 		to: '',
	// 		threat_score: 0,
	// 		threat_level: 'none',
	// 		total_groups: 0,
	// 		total_events: 0,
	// 		categories: {},
	// 		top_threats: [],
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Smart alert summary failed: HTTP ${res.status}`);

	return res.json();
}

/**
 * Suppress a specific alert signature (optionally scoped to a device IP).
 */
export async function suppressAlert(
	signatureId: number,
	deviceIp?: string,
	reason?: string
): Promise<void> {
	// OLD CODE START — ignored the response, so a failed suppress looked like it worked
	// await fetch('/api/alerts/suppress', {
	// 	method: 'POST',
	// 	headers: { 'Content-Type': 'application/json' },
	// 	body: JSON.stringify({ signature_id: signatureId, device_ip: deviceIp, reason }),
	// });
	// OLD CODE END
	const res = await fetch('/api/alerts/suppress', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ signature_id: signatureId, device_ip: deviceIp, reason }),
	});
	if (!res.ok) await throwActionError(res, 'Suppress failed');
}

/** Throw with the daemon's error message when it sent one. */
async function throwActionError(res: Response, fallback: string): Promise<never> {
	const data = await res.json().catch(() => ({}));
	throw new Error(data?.error || `${fallback}: ${res.status}`);
}

/**
 * Mark a signature as a false positive.
 */
export async function markFalsePositive(
	signatureId: number,
	reason?: string
): Promise<void> {
	// OLD CODE START — ignored the response, so a failed mark looked like it worked
	// await fetch('/api/alerts/false-positive', {
	// 	method: 'POST',
	// 	headers: { 'Content-Type': 'application/json' },
	// 	body: JSON.stringify({ signature_id: signatureId, reason }),
	// });
	// OLD CODE END
	const res = await fetch('/api/alerts/false-positive', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ signature_id: signatureId, reason }),
	});
	if (!res.ok) await throwActionError(res, 'Mark false positive failed');
}

// ---------------------------------------------------------------------------
// Enhanced Category Types (v3 — severity, trends, MITRE, sub-categories)
// ---------------------------------------------------------------------------

/** Alerts by Suricata severity (1 high, 2 medium, 3 low; info is the rest), as the tiles count them (I4). */
export interface CategorySeverityBreakdown {
	// OLD CODE START — I4: NetTap's regraded scale had a critical level; the daemon no longer sends it
	// critical: number;
	// OLD CODE END
	critical?: number;
	high: number;
	medium: number;
	low: number;
	info: number;
}

export interface SubCategory {
	id: string;
	label: string;
	count: number;
}

export interface CategoryTrend {
	// OLD CODE: direction: 'increasing' | 'decreasing' | 'stable'; (NET-228: the daemon can say there isn't enough data)
	direction: 'increasing' | 'decreasing' | 'stable' | 'not_enough_data';
	percentage: number;
}

export interface AlertCategory {
	id: string;
	label: string;
	icon: string;
	color: string;
	description: string;
	count: number;
	severity_breakdown: CategorySeverityBreakdown;
	trend: CategoryTrend;
	sparkline: number[];
	sub_categories: SubCategory[];
}

export interface EnhancedCategoriesResponse {
	from: string;
	to: string;
	categories: AlertCategory[];
}

export interface MitreTechnique {
	id: string;
	name: string;
	description: string;
	count?: number;
}

export interface MitreTactic {
	id: string;
	name: string;
}

export interface CategoryDetailDevice {
	ip: string;
	count: number;
	hostname?: string;
	severity?: string;
}

export interface CategoryDetailSignature {
	// OLD CODE: signature: string; (NET-185: alerts with no rule name are their own null row)
	signature: string | null;
	count: number;
	last_seen: string;
}

export interface CategoryDetailResponse {
	category: {
		id: string;
		label: string;
		description: string;
		color: string;
		icon: string;
		// OLD CODE START — the daemon never sends a tactic; the badge it fed was dead
		// mitre_tactic: MitreTactic | null;
		// OLD CODE END
	};
	stats: {
		total: number;
		unique_sources: number;
		unique_targets: number;
		affected_devices: number;
	};
	severity_breakdown: CategorySeverityBreakdown;
	sub_categories: SubCategory[];
	affected_devices: CategoryDetailDevice[];
	top_signatures: CategoryDetailSignature[];
	mitre_techniques: MitreTechnique[];
	from: string;
	to: string;
}

export interface CategoryTimelinePoint {
	timestamp: string;
	total: number;
	sub_categories: Record<string, number>;
}

export interface CategoryTimelineResponse {
	category: string;
	from: string;
	to: string;
	interval: string;
	series: CategoryTimelinePoint[];
}

// ---------------------------------------------------------------------------
// Enhanced Category Fetch helpers
// ---------------------------------------------------------------------------

/**
 * Get enhanced alert categories with severity breakdowns, trends, and sparklines.
 */
export async function getEnhancedCategories(
	opts: TimeRangeParams = {}
): Promise<EnhancedCategoriesResponse> {
	const q = buildQuery(opts as Record<string, string | number | undefined>);
	// OLD CODE START — #96: any failure (HTTP, timeout, network) read as "No category data available"
	// try {
	// 	const res = await fetch(`/api/alerts/categories${q}`, { signal: AbortSignal.timeout(15_000) });
	// 	if (!res.ok) throw new Error(`${res.status}`);
	// 	const data = await res.json();
	// 	const categories: Record<string, unknown>[] = Array.isArray(data?.categories) ? data.categories : [];
	// 	return { ...data, categories: categories.map(normaliseCategory) };
	// } catch {
	// 	return { from: '', to: '', categories: [] };
	// }
	// OLD CODE END
	const res = await fetch(`/api/alerts/categories${q}`, { signal: AbortSignal.timeout(15_000) });
	if (!res.ok) throw new Error(`Alert categories failed: HTTP ${res.status}`);
	// OLD CODE START — passed the daemon payload through, but the daemon sends `trend`
	// as a bare string and `sparkline` as [{timestamp, count}], so every card showed
	// "stable" and the sparkline polyline was NaN
	// return await res.json();
	// OLD CODE END
	const data = await res.json();
	const categories: Record<string, unknown>[] = Array.isArray(data?.categories) ? data.categories : [];
	return { ...data, categories: categories.map(normaliseCategory) };
}

// OLD CODE: const TREND_DIRECTIONS: … = ['increasing', 'decreasing', 'stable']; (NET-228)
const TREND_DIRECTIONS: CategoryTrend['direction'][] = ['increasing', 'decreasing', 'stable', 'not_enough_data'];

/**
 * Map a daemon category (`trend: "increasing"`, `sparkline: [{timestamp, count}]`)
 * onto AlertCategory. The daemon computes direction only, so percentage is 0.
 */
function normaliseCategory(raw: Record<string, unknown>): AlertCategory {
	const direction = TREND_DIRECTIONS.find((d) => d === raw.trend) ?? 'stable';
	const points = Array.isArray(raw.sparkline) ? (raw.sparkline as { count?: unknown }[]) : [];
	return {
		...(raw as unknown as AlertCategory),
		trend: { direction, percentage: 0 },
		sparkline: points.map((p) => (typeof p?.count === 'number' ? p.count : 0)),
		sub_categories: Array.isArray(raw.sub_categories) ? (raw.sub_categories as SubCategory[]) : [],
	};
}

/**
 * Get detailed information for a single alert category.
 * Includes stats, affected devices, top signatures, and MITRE techniques.
 */
export async function getAlertCategoryDetail(
	category: string,
	opts: TimeRangeParams = {}
): Promise<CategoryDetailResponse> {
	const q = buildQuery(opts as Record<string, string | number | undefined>);
	// OLD CODE START — #96: any failure read as "No alerts in <category>"
	// try {
	// 	const res = await fetch(`/api/alerts/categories/${encodeURIComponent(category)}${q}`, { signal: AbortSignal.timeout(15_000) });
	// 	if (!res.ok) throw new Error(`${res.status}`);
	// 	return await res.json();
	// } catch {
	// 	return {
	// 		// OLD CODE START — mitre_tactic removed from the type (never sent by the daemon)
	// 		// category: { id: category, label: category, description: '', color: 'muted', icon: 'info', mitre_tactic: null },
	// 		// OLD CODE END
	// 		category: { id: category, label: category, description: '', color: 'muted', icon: 'info' },
	// 		stats: { total: 0, unique_sources: 0, unique_targets: 0, affected_devices: 0 },
	// 		severity_breakdown: { critical: 0, high: 0, medium: 0, low: 0, info: 0 },
	// 		sub_categories: [], affected_devices: [], top_signatures: [], mitre_techniques: [],
	// 		from: '', to: '',
	// 	};
	// }
	// OLD CODE END
	const res = await fetch(`/api/alerts/categories/${encodeURIComponent(category)}${q}`, { signal: AbortSignal.timeout(15_000) });
	if (!res.ok) throw new Error(`Alert category failed: HTTP ${res.status}`);
	return res.json();
}

/**
 * Get time-series data for a single alert category, broken down by sub-categories.
 */
export async function getAlertCategoryTimeline(
	category: string,
	opts: TimeRangeParams & { interval?: string } = {}
): Promise<CategoryTimelineResponse> {
	const q = buildQuery(opts as Record<string, string | number | undefined>);
	// OLD CODE START — #96: any failure read as an empty timeline
	// try {
	// 	const res = await fetch(`/api/alerts/categories/${encodeURIComponent(category)}/timeline${q}`, { signal: AbortSignal.timeout(15_000) });
	// 	if (!res.ok) throw new Error(`${res.status}`);
	// 	return await res.json();
	// } catch {
	// 	return { category, from: '', to: '', interval: opts.interval ?? '1h', series: [] };
	// }
	// OLD CODE END
	const res = await fetch(`/api/alerts/categories/${encodeURIComponent(category)}/timeline${q}`, { signal: AbortSignal.timeout(15_000) });
	if (!res.ok) throw new Error(`Alert category timeline failed: HTTP ${res.status}`);
	return res.json();
}
