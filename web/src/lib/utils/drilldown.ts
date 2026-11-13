/**
 * Shared wording for the address and domain pages (NET-160): their windows, and figures that
 * say when they are partial or not measured instead of showing a number the data can't back.
 */
import type { ByteTotal } from '$lib/api/drilldown';
import type { SmartAlertKey } from '$lib/api/alerts';
import { formatBytes, formatCompactNumber } from '$lib/api/logs';
import type { BandwidthPoint } from '$lib/api/traffic';
import { formatTime } from './time';

// OLD CODE: export type DrillRangeValue = '24h' | '7d' | '30d'; (NET-192 PR 4: Home's five ranges)
export type DrillRangeValue = '1h' | '6h' | '24h' | '7d' | '30d';

export interface DrillRange {
	value: DrillRangeValue;
	label: string;
	hours: number;
	words: string;
	/** The timeline's bucket, as the daemon picks it for this window (up to 6 h: 10 min; 24 h: 1 h; 7 d: 6 h; longer: 1 day). */
	interval: string;
	/** NET-249: the bandwidth chart's bucket for this range (the owner's table), its length and its words. */
	bucket: DrillBucket;
	bucketMs: number;
	bucketWords: string;
}

/** A bandwidth bucket the daemon's /api/traffic/bandwidth accepts (NET-249). */
export type DrillBucket = '1m' | '5m' | '1h' | '3h';

const MINUTE_MS = 60_000;
const HOUR_MS = 3_600_000;

// OLD CODE START — NET-249: each range gains its bandwidth bucket
// /** One range set across the app (NET-192 PR 4): 1h 6h 24h 7d 30d, as on Home. */
// export const DRILL_RANGES: readonly DrillRange[] = [
// 	{ value: '1h', label: '1h', hours: 1, words: 'last hour', interval: '10 minutes' },
// 	{ value: '6h', label: '6h', hours: 6, words: 'last 6 hours', interval: '10 minutes' },
// 	{ value: '24h', label: '24h', hours: 24, words: 'last 24 hours', interval: 'hour' },
// 	{ value: '7d', label: '7d', hours: 168, words: 'last 7 days', interval: '6 hours' },
// 	{ value: '30d', label: '30d', hours: 720, words: 'last 30 days', interval: 'day' },
// ];
// OLD CODE END
/**
 * One range set across the app (NET-192 PR 4): 1h 6h 24h 7d 30d, as on Home. Buckets scale with
 * the range (owner, NET-249): 60, 72, 288, 168 and 240 points.
 */
export const DRILL_RANGES: readonly DrillRange[] = [
	{ value: '1h', label: '1h', hours: 1, words: 'last hour', interval: '10 minutes', bucket: '1m', bucketMs: MINUTE_MS, bucketWords: 'minute' },
	{ value: '6h', label: '6h', hours: 6, words: 'last 6 hours', interval: '10 minutes', bucket: '5m', bucketMs: 5 * MINUTE_MS, bucketWords: '5 minutes' },
	{ value: '24h', label: '24h', hours: 24, words: 'last 24 hours', interval: 'hour', bucket: '5m', bucketMs: 5 * MINUTE_MS, bucketWords: '5 minutes' },
	{ value: '7d', label: '7d', hours: 168, words: 'last 7 days', interval: '6 hours', bucket: '1h', bucketMs: HOUR_MS, bucketWords: 'hour' },
	{ value: '30d', label: '30d', hours: 720, words: 'last 30 days', interval: 'day', bucket: '3h', bucketMs: 3 * HOUR_MS, bucketWords: '3 hours' },
];

/**
 * The range whose bucket a custom window uses: the smallest standard range that covers it (the
 * longest for anything longer), the rule Alerts' rangeFor uses for its timeline.
 */
export function bucketFor(fromMs: number, toMs: number): DrillRange {
	return DRILL_RANGES.find((r) => r.hours * HOUR_MS >= toMs - fromMs) ?? DRILL_RANGES[DRILL_RANGES.length - 1];
}

/** Settings › Display's key in this browser's localStorage (NET-195). */
export const DISPLAY_SETTINGS_KEY = 'nettap-display-settings';

/**
 * A legacy `defaultTimeRange` someone must have picked. '1h' was Settings' own fallback, written by
 * any Display save, so it may be an accident; '15m' and '4h' are no longer offered.
 */
const LEGACY_PICKED: readonly string[] = ['6h', '24h', '7d', '30d'];

/**
 * The range Settings › Display saved, or null: nothing saved, a value not offered, bad JSON, storage
 * that throws, or the server (no localStorage). A legacy `defaultTimeRange` counts only when the new
 * `defaultRange` is absent, and only for a value that can't be an accident.
 */
export function savedDefaultRange(): DrillRangeValue | null {
	try {
		const saved = JSON.parse(localStorage.getItem(DISPLAY_SETTINGS_KEY) ?? 'null');
		if (saved === null || typeof saved !== 'object') return null;
		if ('defaultRange' in saved) return DRILL_RANGES.some((r) => r.value === saved.defaultRange) ? saved.defaultRange : null;
		return LEGACY_PICKED.includes(saved.defaultTimeRange) ? saved.defaultTimeRange : null;
	} catch {
		return null;
	}
}

/** How the Live page draws its map in this browser: the 3D globe, or the lighter flat map. */
export type LiveMap = 'globe' | 'flat';

/** Settings › Display's Live map choice; anything else (nothing saved, bad JSON, no storage) is the globe. */
export function savedLiveMap(): LiveMap {
	try {
		const saved = JSON.parse(localStorage.getItem(DISPLAY_SETTINGS_KEY) ?? 'null');
		return saved?.liveMap === 'flat' ? 'flat' : 'globe';
	} catch {
		return 'globe';
	}
}

/** The range a page opens on: the saved default, else the page's own. Read it where the page's range starts. */
export const startRange = (pageDefault: DrillRangeValue): DrillRangeValue => savedDefaultRange() ?? pageDefault;

/** A timeline label: the time within a day, day and time for a week of 6-hour buckets, the day beyond. */
export function chartTime(t: number | string, hours: number): string {
	const d = new Date(t);
	if (hours <= 24) return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
	if (hours <= 168) return d.toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
	return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

/** The window ending now, as ISO strings. */
export function rangeWindow(hours: number, now: Date = new Date()): { from: string; to: string } {
	return { from: new Date(now.getTime() - hours * 3_600_000).toISOString(), to: now.toISOString() };
}

export const fmt = (n: number): string => n.toLocaleString('en-GB');
/** Where one daemon scan stops (mirrors daemon/storage/all_buckets.py MAX_BUCKETS); a capped detection says so (NET-238). */
export const SCAN_CAP = 500_000;

// OLD CODE: const COMPACT = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }); (moved to formatCompactNumber in api/logs.ts, NET-192 PR 4)
/** A count in a small space (a gauge centre, a nav badge): exact below 100,000, "214K" above. */
export const fitCount = (n: number): string => (n < 100_000 ? fmt(n) : formatCompactNumber(n));

/**
 * A byte total as the page shows it: "Not measured" when no connection carried a byte count,
 * "at least 1.2 GB" when some didn't, the total otherwise. No connections is a measured 0 B.
 */
export function byteFigure(b: ByteTotal): string {
	if (b.connections > 0 && b.measured === 0) return 'Not measured';
	return b.partial ? `at least ${formatBytes(b.total)}` : formatBytes(b.total);
}

/** "118 of 120 connections measured" for a partial total; null when it is complete or unmeasured. */
export function measuredNote(b: ByteTotal): string | null {
	if (!b.partial || b.measured === 0) return null;
	return `${fmt(b.measured)} of ${fmt(b.connections)} ${b.connections === 1 ? 'connection' : 'connections'} measured`;
}

/** A name as the daemon matches it: trimmed, one trailing dot dropped, lower case. */
export function canonicalName(raw: string): string {
	return raw.trim().replace(/\.$/, '').toLowerCase();
}

const LABEL = /^[a-z0-9_-]{1,63}$/;
/** A host name by the daemon's rule (services/hostnames.py): labels of a-z, 0-9, _ and -, 253 characters at most. */
export function isHostName(raw: string): boolean {
	const name = canonicalName(raw);
	return name.length > 0 && name.length <= 253 && name.split('.').every((label) => LABEL.test(label));
}

/** The observed certificates for a site and/or server in a window (the Certificates page's filter). */
export function certificatesHref(opts: { site?: string | null; server?: string | null; from: string; to: string }): string {
	const q = new URLSearchParams();
	// OLD CODE START — the name went as recorded ("Example.com."); the filter takes the canonical name
	// if (opts.site) q.set('site', opts.site);
	// OLD CODE END
	if (opts.site) q.set('site', canonicalName(opts.site));
	if (opts.server) q.set('server', opts.server);
	q.set('from', opts.from);
	q.set('to', opts.to);
	return `/certificates?${q.toString()}`;
}

// OLD CODE START — Log Explorer opened on its own 24-hour window, whatever window the link came from
// /** Log Explorer, searching both sides for an address (quoted, so IPv6 colons aren't query syntax). */
// export function logsHrefForIp(ip: string): string {
// 	return `/logs?query=${encodeURIComponent(`(source.ip:"${ip}" OR destination.ip:"${ip}")`)}`;
// }
// OLD CODE END
// OLD CODE START — slice 2a: a range link re-anchored the window at click time, so the list could
// differ from the count by whatever arrived or expired meanwhile
// /** Log Explorer over `range`, searching both sides for an address (quoted, so IPv6 colons aren't query syntax). */
// export function logsHrefForIp(ip: string, range: DrillRangeValue): string {
// 	return `/logs?query=${encodeURIComponent(`(source.ip:"${ip}" OR destination.ip:"${ip}")`)}&range=${range}`;
// }
// OLD CODE END
// OLD CODE START — section D: every log type, while the address page's figure counts conn records only
// export function logsHrefForIp(ip: string, range: DrillRangeValue, win?: DrillWindow): string {
// 	const href = `/logs?query=${encodeURIComponent(`(source.ip:"${ip}" OR destination.ip:"${ip}")`)}&range=${range}`;
// 	return win ? `${href}&${windowQuery(win)}` : href;
// }
// OLD CODE END
/**
 * Log Explorer over `range`, searching both sides for an address (quoted, so IPv6 colons aren't
 * query syntax). With `win`, the list opens on that exact window (Custom), the count's own; with
 * `type`, on that log type only (e.g. `zeek.conn` for a connection count).
 */
export function logsHrefForIp(ip: string, range: DrillRangeValue, win?: DrillWindow, type?: string): string {
	let href = `/logs?query=${encodeURIComponent(`(source.ip:"${ip}" OR destination.ip:"${ip}")`)}&range=${range}`;
	if (type) href += `&type=${encodeURIComponent(type)}`;
	return win ? `${href}&${windowQuery(win)}` : href;
}

// ---------------------------------------------------------------------------
// Exact windows (NET-160 slice 2a): a count links to a list over the count's own window
// ---------------------------------------------------------------------------

/** The absolute window a figure was counted over, as ISO strings. */
export interface DrillWindow {
	from: string;
	to: string;
}

// OLD CODE START — NET-192 PR 4: the same output as formatTime's short style, so it is that
// export function formatWhen(iso: string | null | undefined): string {
// 	if (!iso) return '—';
// 	const d = new Date(iso);
// 	return Number.isFinite(d.getTime())
// 		? d.toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
// 		: iso;
// }
// OLD CODE END
/** A day and time, as the windows are written ("6 Nov, 13:02"). */
export const formatWhen = (iso: string | null | undefined): string => formatTime(iso, 'short');

/** A window a link brought (?from=&to=), shown as a "Custom" range. */
export interface CustomWindow extends DrillWindow {
	value: 'custom';
	label: 'Custom';
	hours: number;
	words: string;
}

// OLD CODE START — NET-249: a chart's trailing slot is a one-millisecond window (from == to), which
// this refused, so its link fell back to the page's own range; and an inclusive end (…:59.999) read a minute early
// /**
//  * The window from a drill-down link: the page the link came from passes the window its figure
//  * came from, so the list matches it. Null unless both ends are dates and `from` is before `to`.
//  */
// export function customRange(from: string | null, to: string | null): CustomWindow | null {
// 	if (!from || !to) return null;
// 	const start = new Date(from);
// 	const end = new Date(to);
// 	if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || start >= end) return null;
// 	return {
// 		value: 'custom',
// 		label: 'Custom',
// 		hours: (end.getTime() - start.getTime()) / 3_600_000,
// 		words: `window ${formatWhen(start.toISOString())} to ${formatWhen(end.toISOString())}`,
// 		from: start.toISOString(),
// 		to: end.toISOString(),
// 	};
// }
// OLD CODE END
/**
 * The window from a drill-down link: the page the link came from passes the window its figure
 * came from, so the list matches it. Null unless both ends are dates and `from` is not after `to`
 * (the daemon's rule): `from == to` is a chart's one-millisecond trailing slot (NET-249).
 */
export function customRange(from: string | null, to: string | null): CustomWindow | null {
	if (!from || !to) return null;
	const start = new Date(from);
	const end = new Date(to);
	if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || start > end) return null;
	return {
		value: 'custom',
		label: 'Custom',
		hours: (end.getTime() - start.getTime()) / 3_600_000,
		words: `window ${formatWhen(start.toISOString())} to ${formatWhen(new Date(shownEnd(end.getTime())).toISOString())}`,
		from: start.toISOString(),
		to: end.toISOString(),
	};
}

/** An inclusive end (a bucket's end − 1 ms, …:59.999) as the bucket end people read: 14:10, not 14:09. */
const shownEnd = (ms: number): number => (ms % 1000 === 999 ? ms + 1 : ms);

/**
 * A window in words for a page head (NET-249): "14:05 to 14:10, 13 Nov", with the day on each end
 * when they differ, seconds when an end isn't on the minute, and "at 14:05:00, 13 Nov" for a
 * one-millisecond window.
 */
export function windowWords(from: string, to: string): string {
	const a = Date.parse(from);
	const b = shownEnd(Date.parse(to));
	const day = (ms: number) => new Date(ms).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
	const time = (ms: number, seconds: boolean) =>
		new Date(ms).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', ...(seconds ? { second: '2-digit' } : {}) });
	if (Date.parse(to) <= a) return `at ${time(a, true)}, ${day(a)}`;
	const seconds = a % MINUTE_MS !== 0 || b % MINUTE_MS !== 0;
	if (day(a) === day(b)) return `${time(a, seconds)} to ${time(b, seconds)}, ${day(a)}`;
	return `${day(a)}, ${time(a, seconds)} to ${day(b)}, ${time(b, seconds)}`;
}

/**
 * The exact window of chart points `i..j` (inclusive, either order), as a link carries it (NET-249).
 * A slot is [start, start + step); the daemon's windows are `gte from, lte to`, so the end is the
 * slot end − 1 ms. Edge slots are clipped to the reply's own window, whose slots the daemon counted
 * only inside it. A trailing slot that starts at `reply.to` gives `from == to`, which is valid.
 */
export function bucketWindow(points: readonly { timestamp: string }[], i: number, j: number, stepMs: number, reply: DrillWindow): DrillWindow {
	const from = Math.max(Date.parse(points[Math.min(i, j)].timestamp), Date.parse(reply.from));
	const to = Math.min(Date.parse(points[Math.max(i, j)].timestamp) + stepMs, Date.parse(reply.to) + 1) - 1;
	return { from: new Date(from).toISOString(), to: new Date(to).toISOString() };
}

/** A bandwidth chart's reply, held whole so a pick's indices and its timestamps come from one answer (NET-249). */
export interface BandwidthChart extends DrillWindow {
	series: readonly Pick<BandwidthPoint, 'timestamp' | 'download_bytes' | 'upload_bytes' | 'local_bytes'>[];
	/** The bucket the request asked for, in ms. */
	step: number;
}

/**
 * The moment page for chart points `i..j`: their exact window, the figures clicked (summed per
 * direction, so the page can say when its own totals differ) and the chart's window for "Whole chart".
 */
export function momentHref(chart: BandwidthChart, i: number, j: number, range?: string, chartWin: DrillWindow = chart): string {
	const win = bucketWindow(chart.series, i, j, chart.step, chart);
	const picked = chart.series.slice(Math.min(i, j), Math.max(i, j) + 1);
	const sum = (key: 'download_bytes' | 'upload_bytes' | 'local_bytes') => String(picked.reduce((total, p) => total + p[key], 0));
	const q = new URLSearchParams({ from: win.from, to: win.to });
	if (range) q.set('range', range);
	q.set('down', sum('download_bytes'));
	q.set('up', sum('upload_bytes'));
	q.set('local', sum('local_bytes'));
	q.set('chart_from', chartWin.from);
	q.set('chart_to', chartWin.to);
	return `/moment?${q.toString()}`;
}

/** `from=…&to=…`, then `&range=…` when given (the window's words fall back to that range). */
export function windowQuery(win: DrillWindow, range?: string): string {
	const q = new URLSearchParams({ from: win.from, to: win.to });
	if (range) q.set('range', range);
	return q.toString();
}

// OLD CODE START — slice 2b-1: only `ip` could narrow the list, which matches either end, so a
// smart alert's link listed the device's other pairs too
// /**
//  * The alerts list for one signature (an exact match on rule.name), over the count's window when given.
//  * `ip` narrows it to alerts with that address at either end (the list's `ip` filter).
//  */
// export function alertsHrefForSignature(signature: string, win?: DrillWindow & { range?: string }, ip?: string): string {
// 	const q = new URLSearchParams(ip ? { signature, ip } : { signature });
// 	return win ? `/alerts?${q.toString()}&${windowQuery(win, win.range)}` : `/alerts?${q.toString()}`;
// }
// OLD CODE END
/**
 * The Alerts list's address filters: `ip` at either end, `src` the source, `dst` the destination.
 * `activity`: the list of alerts ET rates informational or unknown, which the counted list leaves out (NET-191).
 */
export interface AlertNarrow {
	ip?: string;
	src?: string;
	dst?: string;
	activity?: boolean;
}

/**
 * The alerts list for one signature (an exact match on rule.name), over the count's window when given.
 * A null signature is the alerts with no rule name (`no_rule_name=true`, NET-185).
 * `narrow` adds the address filters; empty ones are left out of the URL.
 */
// OLD CODE: export function alertsHrefForSignature(signature: string, win?: DrillWindow & { range?: string }, narrow: AlertNarrow = {}): string { (NET-185: null, no rule name)
export function alertsHrefForSignature(signature: string | null, win?: DrillWindow & { range?: string }, narrow: AlertNarrow = {}): string {
	// OLD CODE: const q = new URLSearchParams({ signature }); (NET-185)
	const q = new URLSearchParams(signature === null ? { no_rule_name: 'true' } : { signature });
	for (const key of ['ip', 'src', 'dst'] as const) {
		if (narrow[key]) q.set(key, narrow[key]);
	}
	if (narrow.activity) q.set('activity', 'true');
	return win ? `/alerts?${q.toString()}&${windowQuery(win, win.range)}` : `/alerts?${q.toString()}`;
}

/** Why a smart alert's ×N isn't a link. */
export const NO_EXACT_ALERT_LIST = "This group has no signature, source or destination recorded, so it can't be listed exactly";

/**
 * The Alerts list holding exactly a smart alert's ×N: its bucket's rule name, source and
 * destination over the window it was counted in, plus `device` when the groups were counted for
 * one (either end, as the count was). Null when a key part is missing or empty: dropping that
 * filter would list more than ×N. `activity`: the group is activity (NET-191), which the list
 * shows only with `activity=true`.
 */
// OLD CODE START — NET-191: an activity group's link opened the counted list, which leaves its alerts out
// export function smartAlertHref(key: SmartAlertKey | undefined, win: DrillWindow & { range?: string }, device?: string): string | null {
// 	if (!key?.rule_name || !key.source_ip || !key.destination_ip) return null;
// 	return alertsHrefForSignature(key.rule_name, win, { ip: device, src: key.source_ip, dst: key.destination_ip });
// }
// OLD CODE END
export function smartAlertHref(key: SmartAlertKey | undefined, win: DrillWindow & { range?: string }, device?: string, activity = false): string | null {
	if (!key?.rule_name || !key.source_ip || !key.destination_ip) return null;
	return alertsHrefForSignature(key.rule_name, win, { ip: device, src: key.source_ip, dst: key.destination_ip, activity });
}

/**
 * Log Explorer's conn records over a traffic summary's own window, leaving out the sources the
 * summary left out, so the list holds its connection count (Home's Connections and Bandwidth).
 */
export function connLogsHref(summary: DrillWindow & { excluded_ips?: string[] }, range: string): string {
	const q = new URLSearchParams({ type: 'zeek.conn' });
	if (summary.excluded_ips?.length) q.set('exclude_src', summary.excluded_ips.join(','));
	return `/logs?${q.toString()}&${windowQuery(summary, range)}`;
}

/**
 * Log Explorer's conn records behind one bar of /api/traffic/protocols' `services` (NET-249), with
 * the endpoint's whole predicate: ssl leaves out QUIC (`ssl_only`), `unknown` is the records with no
 * service label, and the sources the reply left out are left out here too.
 */
export function serviceLogsHref(name: string, win: DrillWindow, excluded: readonly string[], range?: string): string {
	const query =
		name === 'ssl'
			? 'network.protocol:"ssl" AND NOT network.protocol:"quic"'
			: name === 'unknown'
				? 'NOT _exists_:network.protocol'
				: `network.protocol:"${name.replace(/["\\]/g, '\\$&')}"`;
	const q = new URLSearchParams({ type: 'zeek.conn', query });
	if (excluded.length) q.set('exclude_src', excluded.join(','));
	return `/logs?${q.toString()}&${windowQuery(win, range)}`;
}

/**
 * Log Explorer for every clause at once (joined with AND), over the count's exact window. Each
 * clause is written by the caller to match the count's own filters; quote IP values (IPv6 colons).
 */
export function logsHrefForQuery(clauses: readonly string[], win: DrillWindow, range: DrillRangeValue): string {
	return `/logs?${new URLSearchParams({ query: clauses.join(' AND ') }).toString()}&${windowQuery(win, range)}`;
}

// ---------------------------------------------------------------------------
// Raw Suricata categories (NET-160 slice 2b-2): rule.category, matched exactly
// ---------------------------------------------------------------------------

/**
 * A raw Suricata category's own page, over `win` when given (the list's window), else its 24 hours.
 * Link only a value the row's `rule_category` holds: the page filters on rule.category.
 */
export function suricataCategoryHref(name: string, win?: DrillWindow & { range?: string }): string {
	// shortcut: a category named "." or ".." can't be a path segment (the browser resolves it); Suricata classtypes are words
	const path = `/alerts/suricata/${encodeURIComponent(name)}`;
	return win ? `${path}?${windowQuery(win, win.range)}` : path;
}

/**
 * A top list the daemon couldn't read in full: its rows are the highest counts among the keys it
 * read, not a true top N (NET-160). `examined` is how many keys it read, when the reply says.
 */
export function partialListNote(noun: string, examined?: number | null): string {
	const read = examined == null ? `the ${noun} read` : `the ${fmt(examined)} ${noun} read`;
	return `Highest counts among ${read}; the full set was too large to read`;
}

/** The Alerts list filters a Suricata category page's figures narrow by; empty ones are left out. */
export interface SuricataNarrow {
	severity?: string;
	signature?: string;
	src?: string;
	dst?: string;
}

/** The Alerts list for one Suricata category, narrowed like the figure it opens, over that figure's window. */
export function suricataAlertsHref(name: string, win: DrillWindow & { range?: string }, narrow: SuricataNarrow = {}): string {
	const q = new URLSearchParams();
	for (const [key, value] of Object.entries(narrow)) {
		if (value) q.set(key, value);
	}
	q.set('suricata_category', name);
	return `/alerts?${q.toString()}&${windowQuery(win, win.range)}`;
}

// ---------------------------------------------------------------------------
// The figure clicked (NET-160 section D, option A): a list says when its own total differs
// ---------------------------------------------------------------------------

/** `href` with `count=<n>` when `n` is a whole number of 0 or more; unchanged otherwise. */
export function withCount(href: string, n: number | null | undefined): string {
	if (typeof n !== 'number' || !Number.isSafeInteger(n) || n < 0) return href;
	return `${href}${href.includes('?') ? '&' : '?'}count=${n}`;
}

/** A link's `count` parameter: up to 15 digits and nothing else, or null (it is only informational). */
export function linkedCount(raw: string | null): number | null {
	return raw !== null && /^[0-9]{1,15}$/.test(raw) ? Number(raw) : null;
}

/** How a list names its own total: "This search now matches" + "1 alert" / "2 alerts". */
export interface CountWords {
	lead: string;
	one: string;
	many: string;
}

/**
 * The line a list shows when its total differs from the figure the user clicked, or null when they
 * agree. It states the net difference and the two ways it happens, not which records changed.
 */
/** Why a list's total can differ from the figure clicked (NET-160 section D). */
export const RECORDS_CHANGE =
	'Records can be logged after a figure is counted (a connection is logged when it ends), and old records are deleted to free disk space.';

export function countDifference(expected: number, observed: number, words: CountWords): string | null {
	if (expected === observed) return null;
	const gap = Math.abs(observed - expected);
	const direction = observed > expected ? 'more' : 'fewer';
	// OLD CODE: … + 'Records can be logged after … to free disk space.' (NET-249: the moment page says it once under its byte lines)
	return `You clicked ${fmt(expected)}. ${words.lead} ${fmt(observed)} ${observed === 1 ? words.one : words.many} (${fmt(gap)} ${direction}). ${RECORDS_CHANGE}`;
}

/**
 * One comparison, tied to the list request a counted link started: `gen` is that request's guard
 * generation, `observed` its total. Any other load replaces it with null.
 */
export interface LinkedCount {
	expected: number;
	gen: number | null;
	observed: number | null;
}
