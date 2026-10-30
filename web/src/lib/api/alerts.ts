/**
 * Client-side API helpers for alert/IDS endpoints.
 * These functions call the SvelteKit server proxy routes which in turn
 * forward requests to the nettap-storage-daemon.
 */

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
	};
	src_ip?: string;
	src_port?: number;
	dest_ip?: string;
	dest_port?: number;
	proto?: string;
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
}

export interface AlertTimelineResponse {
	from: string;
	to: string;
	interval: string;
	buckets: AlertTimelineBucket[];
}

export interface AlertSignature {
	signature: string;
	count: number;
	severity: number;
}

export interface AlertTopSignaturesResponse {
	from: string;
	to: string;
	signatures: AlertSignature[];
}

export interface AlertIpEntry {
	ip: string;
	count: number;
}

export interface AlertTopIpsResponse {
	from: string;
	to: string;
	direction: string;
	ips: AlertIpEntry[];
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

/**
 * Get paginated alert list with optional severity filter.
 * Severity: 1=high, 2=medium, 3=low.
 */
export async function getAlerts(
	opts: TimeRangeParams & {
		severity?: number;
		page?: number;
		size?: number;
		ip?: string;
		signature?: string;
		category?: string;
	} = {}
): Promise<AlertsListResponse> {
	const query = buildQuery({
		from: opts.from,
		to: opts.to,
		severity: opts.severity,
		page: opts.page,
		size: opts.size,
		ip: opts.ip,
		signature: opts.signature,
		category: opts.category,
	});
	const res = await fetch(`/api/alerts${query}`);

	if (!res.ok) {
		return {
			from: '',
			to: '',
			page: opts.page ?? 1,
			size: opts.size ?? 50,
			total: 0,
			total_pages: 0,
			alerts: [],
		};
	}

	return res.json();
}

/**
 * Get alert counts grouped by severity.
 */
export async function getAlertCount(
	opts: TimeRangeParams = {}
): Promise<AlertCountResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/alerts/count${query}`);

	if (!res.ok) {
		return {
			from: '',
			to: '',
			counts: { total: 0, high: 0, medium: 0, low: 0 },
		};
	}

	return res.json();
}

/**
 * Get a single alert detail by OpenSearch _id.
 */
export async function getAlertDetail(id: string): Promise<AlertDetailResponse | null> {
	const res = await fetch(`/api/alerts/${encodeURIComponent(id)}`);

	if (!res.ok) {
		return null;
	}

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

	if (!res.ok) {
		return { from: '', to: '', interval: opts.interval || '1h', buckets: [] };
	}

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

	if (!res.ok) {
		return { from: '', to: '', signatures: [] };
	}

	return res.json();
}

/**
 * Get top IPs seen in alerts (source or destination).
 */
export async function getAlertTopIps(
	opts: TimeRangeParams & { limit?: number; direction?: string } = {}
): Promise<AlertTopIpsResponse> {
	const query = buildQuery({
		from: opts.from,
		to: opts.to,
		limit: opts.limit,
		direction: opts.direction,
	});
	const res = await fetch(`/api/alerts/top-ips${query}`);

	if (!res.ok) {
		return { from: '', to: '', direction: opts.direction || 'dest', ips: [] };
	}

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

	if (!res.ok) {
		return { from: '', to: '', categories: [] };
	}

	return res.json();
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

/**
 * Format a number with compact notation (e.g. 1.2K, 3.4M).
 */
export function formatNumber(n: number): string {
	if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
	if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
	return String(n);
}

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
}

export interface SmartAlertsResponse {
	from: string;
	to: string;
	device_ip: string | null;
	alerts: SmartAlert[];
	total: number;
}

export interface SmartAlertSummary {
	from: string;
	to: string;
	threat_score: number;
	threat_level: string;
	total_groups: number;
	total_events: number;
	categories: Record<string, { label: string; groups: number; events: number }>;
	top_threats: SmartAlert[];
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

	if (!res.ok) {
		return { from: '', to: '', device_ip: null, alerts: [], total: 0 };
	}

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

	if (!res.ok) {
		return {
			from: '',
			to: '',
			threat_score: 0,
			threat_level: 'none',
			total_groups: 0,
			total_events: 0,
			categories: {},
			top_threats: [],
		};
	}

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
	await fetch('/api/alerts/suppress', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ signature_id: signatureId, device_ip: deviceIp, reason }),
	});
}

/**
 * Mark a signature as a false positive.
 */
export async function markFalsePositive(
	signatureId: number,
	reason?: string
): Promise<void> {
	await fetch('/api/alerts/false-positive', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ signature_id: signatureId, reason }),
	});
}

// ---------------------------------------------------------------------------
// Enhanced Category Types (v3 — severity, trends, MITRE, sub-categories)
// ---------------------------------------------------------------------------

export interface CategorySeverityBreakdown {
	critical: number;
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
	direction: 'increasing' | 'decreasing' | 'stable';
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
	signature: string;
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
		mitre_tactic: MitreTactic | null;
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
	try {
		const res = await fetch(`/api/alerts/categories${q}`, { signal: AbortSignal.timeout(15_000) });
		if (!res.ok) throw new Error(`${res.status}`);
		return await res.json();
	} catch {
		return { from: '', to: '', categories: [] };
	}
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
	try {
		const res = await fetch(`/api/alerts/categories/${encodeURIComponent(category)}${q}`, { signal: AbortSignal.timeout(15_000) });
		if (!res.ok) throw new Error(`${res.status}`);
		return await res.json();
	} catch {
		return {
			category: { id: category, label: category, description: '', color: 'muted', icon: 'info', mitre_tactic: null },
			stats: { total: 0, unique_sources: 0, unique_targets: 0, affected_devices: 0 },
			severity_breakdown: { critical: 0, high: 0, medium: 0, low: 0, info: 0 },
			sub_categories: [], affected_devices: [], top_signatures: [], mitre_techniques: [],
			from: '', to: '',
		};
	}
}

/**
 * Get time-series data for a single alert category, broken down by sub-categories.
 */
export async function getAlertCategoryTimeline(
	category: string,
	opts: TimeRangeParams & { interval?: string } = {}
): Promise<CategoryTimelineResponse> {
	const q = buildQuery(opts as Record<string, string | number | undefined>);
	try {
		const res = await fetch(`/api/alerts/categories/${encodeURIComponent(category)}/timeline${q}`, { signal: AbortSignal.timeout(15_000) });
		if (!res.ok) throw new Error(`${res.status}`);
		return await res.json();
	} catch {
		return { category, from: '', to: '', interval: opts.interval ?? '1h', series: [] };
	}
}
