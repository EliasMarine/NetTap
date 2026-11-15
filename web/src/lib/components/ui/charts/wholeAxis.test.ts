import { describe, it, expect } from 'vitest';
import { fitAxis, niceAxis } from './geometry';

// NET-286: a count axis (packets, files, alerts) must only have whole-number ticks.
const shown = (values: number[]) => values.map((v) => String(Math.round(v)));

describe('count axes (NET-286)', () => {
	it('root cause: the fractional ticks of a small peak round to repeated labels', () => {
		expect(shown(fitAxis(1).values)).toEqual(['0', '0', '0', '1', '1', '1']);
		expect(shown(fitAxis(2).values)).toEqual(['0', '1', '1', '2', '2']);
		// 2.5 rounds up, so the "3" label sits at 2.5
		expect(shown(fitAxis(12).values)).toEqual(['0', '3', '5', '8', '10', '13']);
	});

	it.each([1, 2, 11, 12])('whole: a peak of %s gets whole, distinct ticks', (max) => {
		const { top, values } = fitAxis(max, 5, true);
		expect(values.every(Number.isInteger)).toBe(true);
		expect(new Set(shown(values)).size).toBe(values.length);
		expect(top).toBeGreaterThanOrEqual(max);
		expect(values.at(-1)).toBe(top);
	});

	it('whole: the tightest whole axis', () => {
		expect(fitAxis(1, 5, true)).toEqual({ top: 1, values: [0, 1] });
		expect(fitAxis(2, 5, true)).toEqual({ top: 2, values: [0, 1, 2] });
		expect(fitAxis(12, 5, true)).toEqual({ top: 15, values: [0, 5, 10, 15] });
	});

	it('whole: a count peak that was already whole keeps its axis', () => {
		for (const max of [0, 3, 4, 5, 7, 10, 37, 125, 182406]) {
			expect(fitAxis(max, 5, true)).toEqual(fitAxis(max, 5));
		}
	});

	it('whole: niceAxis never steps by a fraction, even below 1', () => {
		for (const max of [0.3, 1, 2, 11]) expect(Number.isInteger(niceAxis(max, 4, true).step)).toBe(true);
	});

	it('default: a fractional axis is unchanged', () => {
		expect(fitAxis(1).values).toEqual([0, 0.2, 0.4, 0.6, 0.8, 1]);
		expect(fitAxis(4.7)).toEqual({ top: 5, values: [0, 1, 2, 3, 4, 5] });
	});
});
