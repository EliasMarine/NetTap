/**
 * Pages that narrow themselves to a pick (NET-249 slice 2, plan §1a): the Alert category, DNS,
 * domain, traffic category and device pages. No list page can hold their charts' scope, so a pick
 * reopens the same page over the picked window (`from`/`to`, shown as Custom) with the figure
 * picked, and every card follows that window. The shared receiver then compares that figure with
 * the narrowed chart's own total, from the one reply on screen.
 */
import { goto } from '$app/navigation';
import { formatBytes } from '$lib/api/logs';
import { countDifference, DRILL_RANGES, RECORDS_CHANGE, type CountWords, type DrillWindow, type TimeChart } from './drilldown';

/** The figure a pick carries: `count` for records, `bytes` for bandwidth. */
export type PickedKey = 'count' | 'bytes';

/** The hint under a chart whose pick narrows its own page. */
export const NARROW_HINT = 'Click a point or drag across the chart to see this page for that time.';

/** Why a device's narrowed total can differ from the figure picked; it names no single cause (devices.py, device_accounting.py). */
export const DEVICE_IPV6_NOTE =
	'Which IPv6 addresses belong to this device is worked out again for each window, from its activity, its MAC address and the gateway check, so a shorter window can count different traffic.';

// OLD CODE START — merge of slice 2: the same helper as chart-pick.ts toTimeChart, which both halves now use
// /** A chart reply as a TimeChart, or null when it echoes no window or no bucket a pick can use: the chart stays a picture. */
// export function timeChart(reply: DrillWindow & { interval?: string | null }, times: string[], values: number[]): TimeChart | null {
// 	const step = stepMs(reply.interval);
// 	const windowed = Number.isFinite(Date.parse(reply.from)) && Number.isFinite(Date.parse(reply.to));
// 	return step === null || !windowed ? null : { from: reply.from, to: reply.to, times, values, step };
// }
// OLD CODE END

/**
 * Reopen this page over a pick's window: its own URL with `from`/`to`, the figure picked (any
 * earlier figure dropped) and `range`, the words a link falls back to: the URL's own when it has
 * one, else the page's. The history entry is replaced only when the window is already on screen.
 */
export function narrowTo(url: URL, shown: DrillWindow | null, win: DrillWindow, range: string, key: PickedKey, figure: number): Promise<void> {
	const q = new URLSearchParams(url.searchParams);
	q.delete('count');
	q.delete('bytes');
	q.set('from', win.from);
	q.set('to', win.to);
	if (!DRILL_RANGES.some((r) => r.value === q.get('range'))) q.set('range', range);
	q.set(key, String(figure));
	const same = shown !== null && shown.from === win.from && shown.to === win.to;
	return goto(`${url.pathname}?${q.toString()}`, { replaceState: same, keepFocus: true, noScroll: true });
}

/** This page's URL with its Custom window and picked figure dropped, for a range pill. */
export function withoutWindow(url: URL): string {
	const q = new URLSearchParams(url.searchParams);
	for (const key of ['from', 'to', 'range', 'count', 'bytes']) q.delete(key);
	const rest = q.toString();
	return rest ? `${url.pathname}?${rest}` : url.pathname;
}

/**
 * The shared receiver's line: the figure picked against this page's chart total over the same
 * window. Null when they agree, or when there is nothing to compare: no figure, or no chart reply
 * for this window (still loading, failed, or superseded by a newer request).
 */
export function pickedLine(picked: number | null, chart: TimeChart | null, unit: CountWords | 'bytes'): string | null {
	if (picked === null || !chart) return null;
	const observed = chart.values.reduce((sum, v) => sum + v, 0);
	if (unit !== 'bytes') return countDifference(picked, observed, unit);
	if (observed === picked) return null;
	const gap = formatBytes(Math.abs(observed - picked));
	return `You clicked ${formatBytes(picked)}. This window now shows ${formatBytes(observed)} (${gap} ${observed > picked ? 'more' : 'less'}). ${RECORDS_CHANGE}`;
}
