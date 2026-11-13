import { describe, expect, it } from 'vitest';
import { pickWindow } from './drilldown';
// OLD CODE: import { chartBucketWords, toTimeChart } from './chart-pick'; (chartBucketWords retired)
import { toTimeChart } from './chart-pick';

describe('toTimeChart (NET-249 slice 2)', () => {
	const win = { from: '2026-11-13T10:02:00.000Z', to: '2026-11-13T10:12:00.000Z' };
	const times = ['2026-11-13T10:00:00.000Z', '2026-11-13T10:05:00.000Z', '2026-11-13T10:10:00.000Z'];

	it("takes the bucket the reply echoes, and picks clip to the reply's window", () => {
		const chart = toTimeChart({ ...win, interval: '5m' }, times, [1, 2, 3]);
		expect(chart).toEqual({ ...win, times, values: [1, 2, 3], step: 300_000 });
		expect(pickWindow(chart!, 0, 0)).toEqual({ from: win.from, to: '2026-11-13T10:04:59.999Z' });
		expect(pickWindow(chart!, 2, 2)).toEqual({ from: '2026-11-13T10:10:00.000Z', to: win.to });
	});

	it.each([
		['an unknown bucket', { ...win, interval: '15m' }],
		['no bucket', { ...win }],
		['an inherited key', { ...win, interval: 'toString' }],
		['no window', { interval: '5m' }],
		['a window that is not two dates', { from: 'soon', to: win.to, interval: '5m' }],
	])('is null for %s, so the chart stays a picture', (_, reply) => {
		expect(toTimeChart(reply, times, [1, 2, 3])).toBeNull();
	});
});

// OLD CODE START — NET-249: chartBucketWords retired for narrow-page's bucketWords (tested in narrow-page.test.ts)
// describe('chartBucketWords (NET-249 slice 2)', () => {
// 	const win = { from: '2026-11-13T10:00:00.000Z', to: '2026-11-13T11:00:00.000Z' };
// 	it('names the bucket the reply used, not the one asked for', () => {
// 		expect(chartBucketWords(toTimeChart({ ...win, interval: '1h' }, [], []), '3 hours')).toBe('hour');
// 		expect(chartBucketWords(toTimeChart({ ...win, interval: '1m' }, [], []), '5 minutes')).toBe('minute');
// 	});
// 	it('keeps the asked words with no pickable reply, or a bucket outside the table', () => {
// 		expect(chartBucketWords(null, '3 hours')).toBe('3 hours');
// 		expect(chartBucketWords(toTimeChart({ ...win, interval: '1d' }, [], []), '3 hours')).toBe('3 hours');
// 	});
// });
// OLD CODE END
