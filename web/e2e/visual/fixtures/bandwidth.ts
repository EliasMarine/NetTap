import type {
	DailyUsageResponse,
	DeviceUsageResponse,
	HeatmapResponse,
	MonthlyUsage,
} from '../../../src/lib/api/bandwidth.ts';
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
			orig_bytes: d.origBytes,
			resp_bytes: d.respBytes,
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

export const BANDWIDTH_ROUTES: FixtureRoute[] = [
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
