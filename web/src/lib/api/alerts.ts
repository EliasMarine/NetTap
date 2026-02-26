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
	opts: TimeRangeParams & { severity?: number; page?: number; size?: number } = {}
): Promise<AlertsListResponse> {
	const query = buildQuery({
		from: opts.from,
		to: opts.to,
		severity: opts.severity,
		page: opts.page,
		size: opts.size,
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
