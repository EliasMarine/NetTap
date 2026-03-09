/**
 * Client-side API helpers for bandwidth monitoring endpoints.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MonthlyUsage {
	year: number;
	month: number;
	total_bytes: number;
	orig_bytes: number;
	resp_bytes: number;
	projection: {
		year: number;
		month: number;
		current_bytes: number;
		projected_bytes: number;
		days_elapsed: number;
		days_in_month: number;
		daily_rate_bytes: number;
		cap_bytes: number;
		usage_percent: number;
		projected_percent: number;
		exceeds_cap: boolean;
	};
}

export interface DailyUsageEntry {
	date: string;
	total_bytes: number;
	orig_bytes: number;
	resp_bytes: number;
	connections: number;
}

export interface DailyUsageResponse {
	from: string;
	to: string;
	daily: DailyUsageEntry[];
}

export interface DeviceUsage {
	ip: string;
	total_bytes: number;
	orig_bytes: number;
	resp_bytes: number;
	connection_count: number;
	percent_of_total: number;
}

export interface DeviceUsageResponse {
	from: string;
	to: string;
	devices: DeviceUsage[];
}

export interface HeatmapResponse {
	from: string;
	to: string;
	days: string[];
	hours: number[];
	matrix: number[][];
}

export interface BandwidthCap {
	monthly_cap_bytes: number;
	monthly_cap_gb: number;
	enabled: boolean;
	current_usage_bytes: number;
	usage_percent: number;
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
 * Get monthly bandwidth usage with projection.
 */
export async function getMonthlyUsage(
	opts: { year?: number; month?: number } = {}
): Promise<MonthlyUsage> {
	const query = buildQuery({ year: opts.year, month: opts.month });
	const res = await fetch(`/api/bandwidth/monthly${query}`);

	if (!res.ok) {
		const now = new Date();
		return {
			year: opts.year ?? now.getFullYear(),
			month: opts.month ?? now.getMonth() + 1,
			total_bytes: 0,
			orig_bytes: 0,
			resp_bytes: 0,
			projection: {
				year: opts.year ?? now.getFullYear(),
				month: opts.month ?? now.getMonth() + 1,
				current_bytes: 0,
				projected_bytes: 0,
				days_elapsed: 0,
				days_in_month: 30,
				daily_rate_bytes: 0,
				cap_bytes: 0,
				usage_percent: 0,
				projected_percent: 0,
				exceeds_cap: false,
			},
		};
	}

	return res.json();
}

/**
 * Get daily bandwidth usage totals.
 */
export async function getDailyUsage(
	opts: { from?: string; to?: string } = {}
): Promise<DailyUsageResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/bandwidth/daily${query}`);

	if (!res.ok) {
		return { from: '', to: '', daily: [] };
	}

	return res.json();
}

/**
 * Get per-device bandwidth breakdown.
 */
export async function getDeviceUsage(
	opts: { from?: string; to?: string; limit?: number } = {}
): Promise<DeviceUsageResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to, limit: opts.limit });
	const res = await fetch(`/api/bandwidth/devices${query}`);

	if (!res.ok) {
		return { from: '', to: '', devices: [] };
	}

	return res.json();
}

/**
 * Get hour-of-day x day-of-week heatmap matrix.
 */
export async function getHeatmap(
	opts: { from?: string; to?: string } = {}
): Promise<HeatmapResponse> {
	const query = buildQuery({ from: opts.from, to: opts.to });
	const res = await fetch(`/api/bandwidth/heatmap${query}`);

	if (!res.ok) {
		return {
			from: '',
			to: '',
			days: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
			hours: Array.from({ length: 24 }, (_, i) => i),
			matrix: Array.from({ length: 7 }, () => Array(24).fill(0)),
		};
	}

	return res.json();
}

/**
 * Get configured bandwidth cap.
 */
export async function getBandwidthCap(): Promise<BandwidthCap> {
	const res = await fetch('/api/bandwidth/cap');

	if (!res.ok) {
		return {
			monthly_cap_bytes: 0,
			monthly_cap_gb: 0,
			enabled: false,
			current_usage_bytes: 0,
			usage_percent: 0,
		};
	}

	return res.json();
}

/**
 * Set monthly bandwidth cap.
 */
export async function setBandwidthCap(
	capGb: number
): Promise<{ result: string; monthly_cap_gb: number; monthly_cap_bytes: number }> {
	const res = await fetch('/api/settings/bandwidth-cap', {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ monthly_cap_gb: capGb }),
	});

	if (!res.ok) {
		throw new Error(`Failed to set bandwidth cap: ${res.status}`);
	}

	return res.json();
}
