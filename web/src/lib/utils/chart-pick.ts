// OLD CODE START — NET-249 review: drilldown.ts isn't frozen as such; this slice adds TimeChart, stepMs and the pick helpers there
// /**
//  * A chart reply held for picking (NET-249 slice 2): the web-links half's one helper beside
//  * drilldown.ts, which is frozen for this slice.
//  */
// import { stepMs, type DrillWindow, type TimeChart } from './drilldown';
// OLD CODE END
/**
 * A chart reply held for picking (NET-249 slice 2), beside drilldown.ts's TimeChart, stepMs,
 * pickWindow and pickedTotal: shared by both halves of the slice, so its pages read a reply one way.
 */
import { DRILL_RANGES, stepMs, type DrillWindow, type TimeChart } from './drilldown';

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

/**
 * "5 minutes": the slot a chart's reply used, in words, so the subtitle names the bucket the chart
 * shows. `asked` (the requested bucket's words) until a pickable reply is in.
 */
export const chartBucketWords = (chart: TimeChart | null, asked: string): string =>
	(chart && DRILL_RANGES.find((r) => r.bucketMs === chart.step)?.bucketWords) || asked;
