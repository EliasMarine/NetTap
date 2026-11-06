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
}

export const DRILL_RANGES: readonly DrillRange[] = [
	{ value: '24h', label: '24h', hours: 24, words: 'last 24 hours' },
	{ value: '7d', label: '7d', hours: 168, words: 'last 7 days' },
	{ value: '30d', label: '30d', hours: 720, words: 'last 30 days' },
];

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

/** The observed certificates for a site and/or server in a window (the Certificates page's filter). */
export function certificatesHref(opts: { site?: string | null; server?: string | null; from: string; to: string }): string {
	const q = new URLSearchParams();
	if (opts.site) q.set('site', opts.site);
	if (opts.server) q.set('server', opts.server);
	q.set('from', opts.from);
	q.set('to', opts.to);
	return `/certificates?${q.toString()}`;
}

/** Log Explorer, searching both sides for an address (quoted, so IPv6 colons aren't query syntax). */
export function logsHrefForIp(ip: string): string {
	return `/logs?query=${encodeURIComponent(`(source.ip:"${ip}" OR destination.ip:"${ip}")`)}`;
}
