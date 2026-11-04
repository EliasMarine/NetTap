import { describe, it, expect } from 'vitest';
import { niceAxis, monotonePath, donutSegments, allocateTicks, inPolygon, type Point } from './geometry';

const ROUND = [1, 2, 2.5, 5];
const isRoundStep = (s: number) => ROUND.some((m) => Math.abs(s / 10 ** Math.floor(Math.log10(s)) - m) < 1e-9);

describe('niceAxis', () => {
	it.each([0.3, 1, 4.7, 9.99, 37, 182406, 5_000_000_000])('covers %s with a 1/2/2.5/5 step', (max) => {
		const { step, top, values } = niceAxis(max);
		expect(isRoundStep(step)).toBe(true);
		expect(top).toBeGreaterThanOrEqual(max);
		expect(values[0]).toBe(0);
		expect(values.at(-1)).toBeCloseTo(top);
	});

	it('picks the tightest step', () => {
		expect(niceAxis(4.7).step).toBe(2);
		expect(niceAxis(5).step).toBe(2);
		expect(niceAxis(9).step).toBe(2.5);
	});

	it('handles zero, negative and NaN without NaN output', () => {
		for (const v of [0, -3, Number.NaN]) {
			const { values } = niceAxis(v);
			expect(values.every(Number.isFinite)).toBe(true);
		}
	});
});

/** Sample a cubic-bezier path string and return every y it reaches. */
function sampledYs(d: string): number[] {
	const nums = d.match(/-?\d+(\.\d+)?/g)!.map(Number);
	const ys: number[] = [];
	let [x0, y0] = [nums[0], nums[1]];
	for (let i = 2; i + 5 < nums.length + 1; i += 6) {
		const [c1y, c2y, y1] = [nums[i + 1], nums[i + 3], nums[i + 5]];
		for (let t = 0; t <= 1; t += 0.05) {
			const u = 1 - t;
			ys.push(u * u * u * y0 + 3 * u * u * t * c1y + 3 * u * t * t * c2y + t * t * t * y1);
		}
		[x0, y0] = [nums[i + 4], y1];
	}
	void x0;
	return ys;
}

describe('monotonePath', () => {
	it('never overshoots below the data minimum (SVG y grows downward, so check the max y)', () => {
		const baseline = 100;
		const series = [0, 0, 80, 0, 0, 5, 90, 0];
		const pts: Point[] = series.map((v, i) => [i * 10, baseline - v]);
		const ys = sampledYs(monotonePath(pts));
		expect(Math.max(...ys)).toBeLessThanOrEqual(baseline + 1e-6);
		expect(Math.min(...ys)).toBeGreaterThanOrEqual(baseline - 90 - 1e-6);
	});

	it('draws nothing for an empty series and a move for one point', () => {
		expect(monotonePath([])).toBe('');
		expect(monotonePath([[5, 7]])).toBe('M5,7');
	});

	it('produces no NaN for constant, gapped or duplicate-x series', () => {
		const cases: Point[][] = [
			[[0, 50], [10, 50], [20, 50]],
			[[0, 10], [10, Number.NaN], [20, 30]],
			[[0, 10], [0, 20], [10, 30]],
		];
		for (const pts of cases) expect(monotonePath(pts)).not.toMatch(/NaN|Infinity/);
	});
});

describe('donutSegments', () => {
	const C = 2 * Math.PI * 70;
	const STROKE = 12;
	const GAP = 6;

	function extents(segs: ReturnType<typeof donutSegments>) {
		return segs.map((s) => {
			const cap = s.round ? STROKE / 2 : 0;
			return [s.offset - cap, s.offset + s.dash + cap] as const;
		});
	}

	it('keeps every visual extent inside its share, so neighbours never overlap', () => {
		const values = [500, 1, 0, 0.5, 300, 2];
		const segs = donutSegments(values, C, GAP, STROKE);
		const total = values.reduce((a, b) => a + b, 0);
		let start = 0;
		const shares = values.map((v) => {
			const s = [start, start + (C * v) / total] as const;
			start += (C * v) / total;
			return s;
		});
		for (const [seg, [lo, hi]] of segs.map((s, k) => [s, extents(segs)[k]] as const)) {
			const [shareLo, shareHi] = shares[seg.index];
			expect(seg.dash).toBeGreaterThanOrEqual(0);
			expect(Number.isFinite(seg.offset)).toBe(true);
			expect(lo).toBeGreaterThanOrEqual(shareLo - 1e-9);
			expect(hi).toBeLessThanOrEqual(shareHi + 1e-9);
		}
	});

	it('skips zeros but keeps the original indices', () => {
		expect(donutSegments([0, 5, 0, 5], C, GAP, STROKE).map((s) => s.index)).toEqual([1, 3]);
	});

	it('uses butt caps on segments too short for round caps', () => {
		const segs = donutSegments([1000, 1], C, GAP, STROKE);
		expect(segs[0].round).toBe(true);
		expect(segs[1].round).toBe(false);
	});

	it('draws a single segment as the full ring and all-zero as nothing', () => {
		expect(donutSegments([0, 7, 0], C, GAP, STROKE)).toEqual([{ index: 1, dash: C, offset: 0, round: false }]);
		expect(donutSegments([0, 0], C, GAP, STROKE)).toEqual([]);
	});
});

describe('allocateTicks', () => {
	const sum = (a: number[]) => a.reduce((x, y) => x + y, 0);

	it.each([
		[[10, 5, 3, 1, 0]],
		[[1, 1, 1, 1, 1]],
		[[1000, 1, 1, 1, 1]],
		[[7, 0, 0, 0, 0]],
		[[3, 3, 3]],
	])('sums to 36 and gives every non-zero bucket a tick: %j', (counts) => {
		const ticks = allocateTicks(counts);
		expect(sum(ticks)).toBe(36);
		counts.forEach((c, i) => expect(ticks[i] > 0).toBe(c > 0));
	});

	it('returns all zeros for an all-zero input (caller draws neutral ticks)', () => {
		expect(allocateTicks([0, 0, 0])).toEqual([0, 0, 0]);
	});
});

describe('inPolygon', () => {
	const square: Point[] = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]];
	const hole: Point[] = [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]];

	it('finds points inside, outside and in a hole', () => {
		expect(inPolygon(2, 2, [square])).toBe(true);
		expect(inPolygon(12, 2, [square])).toBe(false);
		expect(inPolygon(5, 5, [square, hole])).toBe(false);
		expect(inPolygon(2, 5, [square, hole])).toBe(true);
	});
});
