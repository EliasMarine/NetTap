import { describe, expect, it } from 'vitest';
import { compareHalves, SETTLE_MS, trendWindow, withCoverage, type SlotValue } from './window-trend';

const NOW = Date.parse('2026-11-09T14:07:30Z');

/** time_slots' reply: one slot per step from `from`, plus the extra one holding `to` */
function series(win: ReturnType<typeof trendWindow>, values: number[], connections = 10): SlotValue[] {
	const from = Date.parse(win.from);
	return [...values, 999].map((value, i) => ({
		timestamp: new Date(from + i * win.stepMs).toISOString(),
		value,
		connections,
	}));
}

describe('trendWindow', () => {
	it('picks at least 12 slots a window from the intervals every series accepts', () => {
		expect(trendWindow(1, NOW).interval).toBe('5m');
		expect(trendWindow(6, NOW).interval).toBe('30m');
		expect(trendWindow(24, NOW).interval).toBe('1h');
		expect(trendWindow(168, NOW).interval).toBe('12h');
		expect(trendWindow(720, NOW).interval).toBe('1d');
	});

	it('ends at the last slot boundary settled by now, with two equal windows before it', () => {
		const w = trendWindow(24, NOW);
		// now − 15 min is 13:52:30, so the last settled hour boundary is 13:00
		expect(w.to).toBe('2026-11-09T13:00:00.000Z');
		expect(w.from).toBe('2026-11-07T13:00:00.000Z');
		expect(Date.parse(w.to)).toBeLessThanOrEqual(NOW - SETTLE_MS);
	});
});

describe('compareHalves', () => {
	const win = trendWindow(1, NOW); // 24 slots of 5 min

	it('sums the older and newer windows and drops the extra slot holding `to`', () => {
		const values = [...Array(12).fill(1), ...Array(12).fill(3)];
		expect(compareHalves(series(win, values), win)).toEqual({ older: 12, newer: 36 });
	});

	it('is not enough data when a slot is missing (NetTap off, or before it was installed)', () => {
		const points = series(win, Array(24).fill(1)).slice(1);
		expect(compareHalves(points, win)).toBe('not_enough_data');
	});

	it('is not enough data when a slot has no connections', () => {
		const points = series(win, Array(24).fill(1)).map((p, i) => (i === 3 ? { ...p, connections: 0 } : p));
		expect(compareHalves(points, win)).toBe('not_enough_data');
	});

	it('is not enough data when the window has no equal halves', () => {
		const odd = trendWindow(75, NOW); // 75 h in 6 h slots: 25 slots
		expect(compareHalves(series(odd, Array(25).fill(1)), odd)).toBe('not_enough_data');
	});

	it('keeps a real zero half as a comparison, unless zero is unknown (alerts)', () => {
		const values = [...Array(12).fill(0), ...Array(12).fill(2)];
		expect(compareHalves(series(win, values), win)).toEqual({ older: 0, newer: 24 });
		expect(compareHalves(series(win, values), win, true)).toBe('not_enough_data');
	});
});

describe('withCoverage', () => {
	it("takes each slot's coverage from all traffic by time, and a slot all traffic lacks has none", () => {
		const points = [{ timestamp: '2026-11-09T10:00:00Z', n: 0 }, { timestamp: '2026-11-09T11:00:00Z', n: 4 }];
		const coverage = [{ timestamp: '2026-11-09T10:00:00.000Z', connections: 7 }];
		expect(withCoverage(points, (p) => p.n, coverage)).toEqual([
			{ timestamp: '2026-11-09T10:00:00Z', value: 0, connections: 7 },
			{ timestamp: '2026-11-09T11:00:00Z', value: 4, connections: 0 },
		]);
	});
});
