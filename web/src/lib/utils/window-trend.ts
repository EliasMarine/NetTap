/**
 * NET-228 (audit TRF-6): a KPI's trend compares two equal back-to-back windows made of whole,
 * settled slots, or says it can't. Zeek writes a connection when it ends, stamped with its start, so
 * the newest minutes of a window ending now are still filling in, and a window reaching back before
 * NetTap had data compares against a gap. The same rule as the Alerts page's category trend
 * (daemon/api/alerts.py category_trend).
 */

/** Zeek's TCP inactivity timeout is 5 min; with the Logstash and Filebeat flushes, 15 min settles most connections. */
export const SETTLE_MS = 15 * 60_000;

/** Intervals every series endpoint accepts (traffic bandwidth, category bandwidth, alert timeline). */
const INTERVALS: [string, number][] = [
	['1m', 60_000],
	['5m', 300_000],
	['10m', 600_000],
	['15m', 900_000],
	['30m', 1_800_000],
	['1h', 3_600_000],
	['6h', 21_600_000],
	['12h', 43_200_000],
	['1d', 86_400_000],
];

export interface TrendWindow {
	/** ISO times of the two windows' span: [from, to) is the older window, then the newer one. */
	from: string;
	to: string;
	interval: string;
	stepMs: number;
}

/** Two windows of `hours` each, back to back, ending at the last slot boundary settled by now. */
export function trendWindow(hours: number, nowMs: number): TrendWindow {
	const windowMs = hours * 3_600_000;
	// at least 12 slots a window, so with a connection in every slot no trend rests on a handful
	const [interval, stepMs] = INTERVALS.filter(([, ms]) => ms <= windowMs / 12).at(-1) ?? INTERVALS[0];
	// slots align to the UTC epoch, as the daemon's time_slots does
	const end = Math.floor((nowMs - SETTLE_MS) / stepMs) * stepMs;
	return { from: new Date(end - 2 * windowMs).toISOString(), to: new Date(end).toISOString(), interval, stepMs };
}

export interface SlotValue {
	/** Slot start, an ISO time as the series replies carry it */
	timestamp: string;
	value: number;
	/** Connections in the slot: a slot with none may be a slot with no data */
	connections: number;
}

export type HalvesResult = { older: number; newer: number } | 'not_enough_data';

/**
 * The two windows' totals from the series' whole slots in [from, to), or "not_enough_data": a slot
 * missing or without connections (NetTap off, or not installed yet), or, with `zeroIsUnknown`, a half
 * whose total is 0 (alerts: Zeek coverage doesn't prove Suricata's).
 */
export function compareHalves(points: SlotValue[], win: TrendWindow, zeroIsUnknown = false): HalvesResult {
	const from = Date.parse(win.from);
	const to = Date.parse(win.to);
	const slots = points.filter((p) => {
		const t = Date.parse(p.timestamp);
		return t >= from && t < to;
	});
	const expected = (to - from) / win.stepMs;
	// an odd count (an hours value the intervals don't split evenly) has no equal halves
	if (expected % 2 !== 0 || slots.length !== expected || slots.some((p) => p.connections <= 0)) return 'not_enough_data';
	const mid = expected / 2;
	const sum = (part: SlotValue[]) => part.reduce((n, p) => n + p.value, 0);
	const older = sum(slots.slice(0, mid));
	const newer = sum(slots.slice(mid));
	if (zeroIsUnknown && (older === 0 || newer === 0)) return 'not_enough_data';
	return { older, newer };
}
