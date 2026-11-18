import type {
	BandwidthCap,
	DailyUsageResponse,
	DeviceUsageResponse,
	HeatmapResponse,
	MonthlyUsage,
} from '../../../src/lib/api/bandwidth.ts';
import type { UsageDay, UsageMonth } from '../../../src/lib/api/usage.ts';
import { DAY, NOW, iso, type FixtureRoute } from './types.ts';
import { GB, HOURLY_WEIGHTS, LAN_DEVICES, WINDOW, sum, totalBytes } from './net-world.ts';

const DAILY_ORIG = sum(LAN_DEVICES.map((d) => d.origBytes));
const DAILY_TOTAL = DAILY_ORIG + sum(LAN_DEVICES.map((d) => d.respBytes));
const DAILY_CONNECTIONS = sum(LAN_DEVICES.map((d) => d.connections));
const ORIG_SHARE = DAILY_ORIG / DAILY_TOTAL;

const CAP_BYTES = 2048 * GB;

function monthly(): MonthlyUsage {
	const now = new Date(NOW);
	const daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
	const daysElapsed = now.getDate();
	// A steady daily rate, so the projection is simply rate x days in the month.
	const totalSoFar = DAILY_TOTAL * daysElapsed;
	const orig = Math.round(totalSoFar * ORIG_SHARE);
	const projected = DAILY_TOTAL * daysInMonth;
	return {
		year: now.getFullYear(),
		month: now.getMonth() + 1,
		total_bytes: totalSoFar,
		orig_bytes: orig,
		resp_bytes: totalSoFar - orig,
		upload_bytes: orig,
		download_bytes: totalSoFar - orig,
		local_bytes: 0,
		projection: {
			year: now.getFullYear(),
			month: now.getMonth() + 1,
			current_bytes: totalSoFar,
			projected_bytes: projected,
			days_elapsed: daysElapsed,
			days_in_month: daysInMonth,
			daily_rate_bytes: DAILY_TOTAL,
			cap_bytes: CAP_BYTES,
			usage_percent: Math.round((totalSoFar / CAP_BYTES) * 1000) / 10,
			projected_percent: Math.round((projected / CAP_BYTES) * 1000) / 10,
			exceeds_cap: projected > CAP_BYTES,
		},
	};
}

const emptyMonthly = (): MonthlyUsage => {
	const now = new Date(NOW);
	const daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
	return {
		year: now.getFullYear(),
		month: now.getMonth() + 1,
		total_bytes: 0,
		orig_bytes: 0,
		resp_bytes: 0,
		upload_bytes: 0,
		download_bytes: 0,
		local_bytes: 0,
		projection: {
			year: now.getFullYear(),
			month: now.getMonth() + 1,
			current_bytes: 0,
			projected_bytes: 0,
			days_elapsed: now.getDate(),
			days_in_month: daysInMonth,
			daily_rate_bytes: 0,
			cap_bytes: CAP_BYTES,
			usage_percent: 0,
			projected_percent: 0,
			exceeds_cap: false,
		},
	};
};

// Each day's volume relative to the 24 h figure, oldest first: busier weekends and a quiet day.
const DAY_FACTORS = [0.92, 1.1, 1.18, 0.95, 0.88, 1.0, 1.05, 0.9, 0.97, 1.12, 1.2, 0.35, 0.99, 1.0];

const daily = (): DailyUsageResponse => ({
	...WINDOW,
	daily: DAY_FACTORS.map((factor, i) => {
		const total = Math.round(DAILY_TOTAL * factor);
		const orig = Math.round(total * ORIG_SHARE);
		return {
			date: iso((DAY_FACTORS.length - 1 - i) * DAY).slice(0, 10),
			total_bytes: total,
			orig_bytes: orig,
			resp_bytes: total - orig,
			upload_bytes: orig,
			download_bytes: total - orig,
			local_bytes: 0,
			connections: Math.round(DAILY_CONNECTIONS * factor),
		};
	}),
});

const devices = (): DeviceUsageResponse => ({
	...WINDOW,
	devices: [...LAN_DEVICES]
		.sort((a, b) => totalBytes(b) - totalBytes(a))
		.map((d) => ({
			ip: d.ip,
			total_bytes: totalBytes(d),
			// OLD CODE: orig_bytes: d.origBytes, resp_bytes: d.respBytes, (NET-226)
			upload_bytes: d.origBytes,
			download_bytes: d.respBytes,
			connection_count: d.connections,
			percent_of_total: Math.round((totalBytes(d) / DAILY_TOTAL) * 1000) / 10,
		})),
});

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const HOURS = Array.from({ length: 24 }, (_, hour) => hour);
const WEEKDAY_FACTORS = [0.9, 0.95, 0.9, 1.0, 1.1, 1.3, 1.25];
const WEIGHT_TOTAL = sum(HOURLY_WEIGHTS);

const heatmap = (): HeatmapResponse => ({
	...WINDOW,
	tz: 'UTC',
	days: DAYS,
	hours: HOURS,
	matrix: WEEKDAY_FACTORS.map((factor) =>
		HOURLY_WEIGHTS.map((weight) => Math.round((DAILY_TOTAL * factor * weight) / WEIGHT_TOTAL)),
	),
});

// ---------------------------------------------------------------------------
// The usage ledger (F4, NET-329): this UTC month, counted in UTC. Populated: every day so far counted,
// today up to now. Empty: a new install, so only today is counted from, and it isn't counted yet.
// ---------------------------------------------------------------------------

function usageDays(populated: boolean): UsageDay[] {
	const now = new Date(NOW);
	const [y, m, today] = [now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()];
	return Array.from({ length: new Date(Date.UTC(y, m + 1, 0)).getUTCDate() }, (_, i) => {
		const start = Date.UTC(y, m, i + 1);
		const day = { date: new Date(start).toISOString().slice(0, 10), start: new Date(start).toISOString(), end: new Date(start + DAY).toISOString() };
		const none = { download: null, upload: null, local: null, total: null, cutoff: null, counted_at: null };
		if (i + 1 > today) return { ...day, ...none, status: 'future' };
		if (!populated) return { ...day, ...none, status: i + 1 === today ? 'pending' : 'not_counted' };
		// total is what crossed the ISP link (download + upload); local, between your devices, is beside it
		const total = Math.round(DAILY_TOTAL * DAY_FACTORS[i % DAY_FACTORS.length] * (i + 1 === today ? (NOW - start) / DAY : 1));
		const upload = Math.round(total * ORIG_SHARE);
		const local = Math.round(total * 0.08);
		return { ...day, download: total - upload, upload, local, total, status: 'counted', cutoff: i + 1 === today ? iso(0) : day.end, counted_at: iso(0) };
	});
}

function usageMonth(populated: boolean): UsageMonth {
	const days = usageDays(populated);
	const shown = days.filter((d) => d.status !== 'future');
	const add = (key: 'download' | 'upload' | 'local' | 'total') => sum(shown.map((d) => d[key] ?? 0));
	const bytes = { download: add('download'), upload: add('upload'), local: add('local'), total: add('total') };
	const now = new Date(NOW);
	const start = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1);
	const end = Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 1);
	// the ledger's rule: real seconds since the month began, and nothing until every elapsed day is counted
	const elapsed = (NOW - start) / 1000;
	const rate = populated && elapsed >= 3600 ? bytes.total / elapsed : null;
	return {
		tz: 'UTC',
		pending_tz: null,
		since: populated ? days[0].date : iso(0).slice(0, 10),
		generation: 1,
		updated_at: iso(0),
		days,
		bytes,
		complete: populated,
		gaps: shown.filter((d) => d.status !== 'counted').map((d) => ({ date: d.date, reason: d.status })),
		year: now.getUTCFullYear(),
		month: now.getUTCMonth() + 1,
		month_start: new Date(start).toISOString(),
		month_end: new Date(end).toISOString(),
		projected: rate === null ? null : Math.round((rate * (end - start)) / 1000),
		daily_rate: rate === null ? null : Math.round(rate * 86_400),
		days_remaining: rate === null ? null : (end - NOW) / DAY,
		sweep: { id: 1, cursor: null, chunks_done: 5, chunks_failed: 0, finished_at: iso(0) },
	};
}

const cap = (populated: boolean): BandwidthCap => {
	const used = populated ? usageMonth(true).bytes.total : 0;
	return { monthly_cap_bytes: CAP_BYTES, monthly_cap_gb: CAP_BYTES / GB, enabled: true, current_usage_bytes: used, usage_percent: Math.round((used / CAP_BYTES) * 1000) / 10 };
};

export const BANDWIDTH_ROUTES: FixtureRoute[] = [
	{ path: '/api/usage/month', empty: usageMonth(false), populated: usageMonth(true) },
	{ path: '/api/bandwidth/cap', method: 'GET', empty: cap(false), populated: cap(true) },
	{
		path: '/api/bandwidth/monthly',
		empty: emptyMonthly(),
		populated: monthly(),
	},
	{
		path: '/api/bandwidth/daily',
		empty: { ...WINDOW, daily: [] } satisfies DailyUsageResponse,
		populated: daily(),
	},
	{
		path: '/api/bandwidth/devices',
		empty: { ...WINDOW, devices: [] } satisfies DeviceUsageResponse,
		populated: devices(),
	},
	{
		path: '/api/bandwidth/heatmap',
		empty: {
			...WINDOW,
			tz: 'UTC',
			days: DAYS,
			hours: HOURS,
			matrix: DAYS.map(() => HOURS.map(() => 0)),
		} satisfies HeatmapResponse,
		populated: heatmap(),
	},
];
