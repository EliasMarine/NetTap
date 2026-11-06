/**
 * Shared wording for the address and domain pages (NET-160): their windows, and figures that
 * say when they are partial or not measured instead of showing a number the data can't back.
 */
import type { ByteTotal } from '$lib/api/drilldown';
import { formatBytes } from '$lib/api/logs';

export type DrillRangeValue = '24h' | '7d' | '30d';

export interface DrillRange {
	value: DrillRangeValue;
	label: string;
	hours: number;
	words: string;
	/** The timeline's bucket, as the daemon picks it for this window (up to 24 h: 1 h; 7 d: 6 h; longer: 1 day). */
	interval: string;
}

export const DRILL_RANGES: readonly DrillRange[] = [
	{ value: '24h', label: '24h', hours: 24, words: 'last 24 hours', interval: 'hour' },
	{ value: '7d', label: '7d', hours: 168, words: 'last 7 days', interval: '6 hours' },
	{ value: '30d', label: '30d', hours: 720, words: 'last 30 days', interval: 'day' },
];

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
/**
 * Log Explorer over `range`, searching both sides for an address (quoted, so IPv6 colons aren't
 * query syntax). With `win`, the list opens on that exact window (Custom), the count's own.
 */
export function logsHrefForIp(ip: string, range: DrillRangeValue, win?: DrillWindow): string {
	const href = `/logs?query=${encodeURIComponent(`(source.ip:"${ip}" OR destination.ip:"${ip}")`)}&range=${range}`;
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

/** A day and time, as the windows are written ("6 Nov, 13:02"). */
export function formatWhen(iso: string | null | undefined): string {
	if (!iso) return '—';
	const d = new Date(iso);
	return Number.isFinite(d.getTime())
		? d.toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
		: iso;
}

/** A window a link brought (?from=&to=), shown as a "Custom" range. */
export interface CustomWindow extends DrillWindow {
	value: 'custom';
	label: 'Custom';
	hours: number;
	words: string;
}

/**
 * The window from a drill-down link: the page the link came from passes the window its figure
 * came from, so the list matches it. Null unless both ends are dates and `from` is before `to`.
 */
export function customRange(from: string | null, to: string | null): CustomWindow | null {
	if (!from || !to) return null;
	const start = new Date(from);
	const end = new Date(to);
	if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || start >= end) return null;
	return {
		value: 'custom',
		label: 'Custom',
		hours: (end.getTime() - start.getTime()) / 3_600_000,
		words: `window ${formatWhen(start.toISOString())} to ${formatWhen(end.toISOString())}`,
		from: start.toISOString(),
		to: end.toISOString(),
	};
}

/** `from=…&to=…`, then `&range=…` when given (the window's words fall back to that range). */
export function windowQuery(win: DrillWindow, range?: string): string {
	const q = new URLSearchParams({ from: win.from, to: win.to });
	if (range) q.set('range', range);
	return q.toString();
}

/** The alerts list for one signature (an exact match on rule.name), over the count's window when given. */
export function alertsHrefForSignature(signature: string, win?: DrillWindow & { range?: string }): string {
	const q = new URLSearchParams({ signature });
	return win ? `/alerts?${q.toString()}&${windowQuery(win, win.range)}` : `/alerts?${q.toString()}`;
}

/**
 * Log Explorer for every clause at once (joined with AND), over the count's exact window. Each
 * clause is written by the caller to match the count's own filters; quote IP values (IPv6 colons).
 */
export function logsHrefForQuery(clauses: readonly string[], win: DrillWindow, range: DrillRangeValue): string {
	return `/logs?${new URLSearchParams({ query: clauses.join(' AND ') }).toString()}&${windowQuery(win, range)}`;
}
