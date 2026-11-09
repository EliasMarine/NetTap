/**
 * Client-side API helpers for bandwidth monitoring endpoints.
 */

import type { Ipv6LeftOutReason } from '$lib/utils/ipv6-coverage';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MonthlyUsage {
	year: number;
	month: number;
	total_bytes: number;
	orig_bytes: number;
	resp_bytes: number;
	/** NET-226: bytes to the internet, from the internet, and between your own devices; they add up to total_bytes */
	upload_bytes: number;
	download_bytes: number;
	local_bytes: number;
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
	/** NET-226: as on MonthlyUsage */
	upload_bytes: number;
	download_bytes: number;
	local_bytes: number;
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
	// OLD CODE START — NET-226: the originator's bytes, so a device's answers read as download
	// orig_bytes: number;
	// resp_bytes: number;
	// OLD CODE END
	/** NET-226: bytes the device sent and received, on connections it started and answered */
	upload_bytes: number;
	download_bytes: number;
	connection_count: number;
	/** Share of the sum of every device's total: a connection between two of your devices counts for both */
	percent_of_total: number;
	ipv6_left_out?: number;
	ipv6_left_out_reason?: Ipv6LeftOutReason | null;
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
	/** IANA zone the hours and weekdays are in; absent from daemons that only bucket in UTC */
	tz?: string;
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

/**
 * "This month" as the daemon counts it: the UTC calendar month containing `now`, from its first
 * instant to `now`. One window for every request on the page, so the KPI, chart and table agree.
 */
export function utcMonthWindow(now: Date): { year: number; month: number; from: string; to: string } {
	const year = now.getUTCFullYear();
	const month = now.getUTCMonth();
	return { year, month: month + 1, from: new Date(Date.UTC(year, month, 1)).toISOString(), to: now.toISOString() };
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

	// OLD CODE START — #96: a failed request read as 0.0 GB this month
	// if (!res.ok) {
	// 	const now = new Date();
	// 	return {
	// 		year: opts.year ?? now.getFullYear(),
	// 		month: opts.month ?? now.getMonth() + 1,
	// 		total_bytes: 0,
	// 		orig_bytes: 0,
	// 		resp_bytes: 0,
	// 		projection: {
	// 			year: opts.year ?? now.getFullYear(),
	// 			month: opts.month ?? now.getMonth() + 1,
	// 			current_bytes: 0,
	// 			projected_bytes: 0,
	// 			days_elapsed: 0,
	// 			days_in_month: 30,
	// 			daily_rate_bytes: 0,
	// 			cap_bytes: 0,
	// 			usage_percent: 0,
	// 			projected_percent: 0,
	// 			exceeds_cap: false,
	// 		},
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Monthly usage failed: HTTP ${res.status}`);

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

	// OLD CODE START — #96: a failed request read as no daily usage
	// if (!res.ok) {
	// 	return { from: '', to: '', daily: [] };
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Daily usage failed: HTTP ${res.status}`);

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

	// OLD CODE START — #96: a failed request read as no devices
	// if (!res.ok) {
	// 	return { from: '', to: '', devices: [] };
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Device usage failed: HTTP ${res.status}`);

	return res.json();
}

/**
 * Get hour-of-day x day-of-week heatmap matrix.
 */
export async function getHeatmap(
	opts: { from?: string; to?: string } = {}
): Promise<HeatmapResponse> {
	// OLD CODE START — the daemon bucketed hours and weekdays in UTC, so a Pacific evening showed after midnight
	// const query = buildQuery({ from: opts.from, to: opts.to });
	// OLD CODE END
	// Bucket in the viewer's zone; with no zone the daemon keeps UTC
	const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || undefined;
	const query = buildQuery({ from: opts.from, to: opts.to, tz });
	const res = await fetch(`/api/bandwidth/heatmap${query}`);

	// OLD CODE START — #96: a failed request read as an all-zero heatmap
	// if (!res.ok) {
	// 	return {
	// 		from: '',
	// 		to: '',
	// 		days: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
	// 		hours: Array.from({ length: 24 }, (_, i) => i),
	// 		matrix: Array.from({ length: 7 }, () => Array(24).fill(0)),
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Heatmap failed: HTTP ${res.status}`);

	return res.json();
}

/**
 * Get configured bandwidth cap.
 */
export async function getBandwidthCap(): Promise<BandwidthCap> {
	const res = await fetch('/api/bandwidth/cap');

	// OLD CODE START — #96: a failed request read as no cap set
	// if (!res.ok) {
	// 	return {
	// 		monthly_cap_bytes: 0,
	// 		monthly_cap_gb: 0,
	// 		enabled: false,
	// 		current_usage_bytes: 0,
	// 		usage_percent: 0,
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`Bandwidth cap failed: HTTP ${res.status}`);

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
