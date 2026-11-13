/**
 * A chart reply held for picking (NET-249 slice 2): the web-links half's one helper beside
 * drilldown.ts, which is frozen for this slice.
 */
import { stepMs, type DrillWindow, type TimeChart } from './drilldown';

/**
 * A reply's slots as a `TimeChart`, or null when a pick couldn't open its exact window: the bucket
 * it echoes isn't a known one, or its window isn't two dates (an older daemon). The chart then
 * stays a picture. Never the bucket the page asked for: only the one the daemon says it used.
 */
export function toTimeChart(
	reply: Partial<DrillWindow> & { interval?: string | null },
	times: readonly string[],
	values: readonly number[],
): TimeChart | null {
	const step = stepMs(reply.interval);
	const { from, to } = reply;
	if (step === null || !from || !to || !Number.isFinite(Date.parse(from)) || !Number.isFinite(Date.parse(to))) return null;
	return { from, to, times, values, step };
}
