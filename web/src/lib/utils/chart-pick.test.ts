import { describe, expect, it } from 'vitest';
import { pickWindow } from './drilldown';
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
