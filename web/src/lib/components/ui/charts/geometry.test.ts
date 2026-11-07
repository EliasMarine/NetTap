import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
	niceAxis,
	monotonePath,
	donutSegments,
	allocateTicks,
	inPolygon,
	fitAxis,
	fitByteAxis,
	labelStep,
	nearestIndex,
	tipBox,
	segmentDash,
	polar,
	polygonsOf,
	landDots,
	project,
	arcPath,
	mapLabels,
	MAP_TOP,
	MAP_BOTTOM,
	type Point,
} from './geometry';

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

describe('fitByteAxis', () => {
	// OLD CODE START — 2026-11-06 (NET-166): the axis used 1024-based units
	// const GiB = 1024 ** 3;
	//
	// it('puts ticks on round 1024-based units', () => {
	// 	expect(fitByteAxis(28 * GiB)).toEqual({ top: 30 * GiB, values: [0, 10, 20, 30].map((v) => v * GiB) });
	// 	expect(fitByteAxis(GiB).values.at(-1)).toBe(GiB);
	// });
	// OLD CODE END
	const GB = 1e9;

	it('puts ticks on whole decimal GB, as formatBytes prints them (NET-166)', () => {
		expect(fitByteAxis(28e9)).toEqual({ top: 30 * GB, values: [0, 10, 20, 30].map((v) => v * GB) });
		expect(fitByteAxis(GB).values.at(-1)).toBe(GB);
	});

	it('puts ticks on whole decimal MB below 1 GB', () => {
		expect(fitByteAxis(470e6)).toEqual({ top: 500e6, values: [0, 100, 200, 300, 400, 500].map((v) => v * 1e6) });
	});

	it('matches fitAxis below 1 KB', () => {
		expect(fitByteAxis(500)).toEqual(fitAxis(500));
		expect(fitByteAxis(0)).toEqual(fitAxis(0));
	});
});

describe('fitAxis', () => {
	it('stops at the first round value that covers the peak', () => {
		expect(fitAxis(4.7)).toEqual({ top: 5, values: [0, 1, 2, 3, 4, 5] });
		expect(fitAxis(5.2).values).toEqual([0, 2, 4, 6]);
	});

	it.each([0.3, 1, 37, 182406])('keeps round steps and covers %s', (max) => {
		const { top, values } = fitAxis(max);
		expect(top).toBeGreaterThanOrEqual(max);
		expect(values.at(-1)).toBe(top);
		expect(isRoundStep(values[1] - values[0])).toBe(true);
	});

	it('falls back to the plain axis for zero and NaN', () => {
		for (const v of [0, Number.NaN]) {
			const { top, values } = fitAxis(v);
			expect(top).toBeGreaterThan(0);
			expect(values.every(Number.isFinite)).toBe(true);
		}
	});
});

describe('labelStep', () => {
	it.each([
		[24, 600],
		[24, 220],
		[168, 1100],
		[7, 900],
	])('keeps %s labels over %spx at least 64px apart', (count, width) => {
		const step = labelStep(count, width);
		expect((width / (count - 1)) * step).toBeGreaterThanOrEqual(64);
	});

	it('labels every point when they fit, and survives one point or no width', () => {
		expect(labelStep(5, 900)).toBe(1);
		expect(labelStep(1, 900)).toBe(1);
		expect(labelStep(24, 0)).toBe(1);
	});
});

describe('nearestIndex', () => {
	it('snaps to the closest point and clamps outside the plot', () => {
		expect(nearestIndex(50, 50, 230, 24)).toBe(0);
		expect(nearestIndex(50 + 230 * (21 / 23) + 3, 50, 230, 24)).toBe(21);
		expect(nearestIndex(-100, 50, 230, 24)).toBe(0);
		expect(nearestIndex(9999, 50, 230, 24)).toBe(23);
	});

	it('returns 0 for one point, no width or a NaN position', () => {
		expect(nearestIndex(10, 0, 100, 1)).toBe(0);
		expect(nearestIndex(10, 0, 0, 5)).toBe(0);
		expect(nearestIndex(Number.NaN, 0, 100, 5)).toBe(0);
	});
});

describe('tipBox', () => {
	it('centres on the point and stays inside the chart', () => {
		const mid = tipBox(300, 100, '21:00 · 4.7 GB', 600);
		expect(mid.x + mid.width / 2).toBeCloseTo(300);
		expect(mid.y).toBe(62);
		expect(tipBox(0, 10, 'long tooltip text', 600).x).toBe(2);
		const right = tipBox(600, 10, 'long tooltip text', 600);
		expect(right.x + right.width).toBe(598);
		expect(right.y).toBe(0);
	});
});

describe('segmentDash', () => {
	const C = 2 * Math.PI * 68;

	it('draws each dash at its offset, one dash per turn', () => {
		const segs = donutSegments([3, 1], C, 4, 12);
		const [a, b] = segs.map((s) => segmentDash(s, C));
		const [dashA, gapA] = a.dasharray.split(' ').map(Number);
		expect(dashA + gapA).toBeCloseTo(C, 1);
		expect(Number(a.dashoffset)).toBeCloseTo(-segs[0].offset, 1);
		expect(Number(b.dashoffset)).toBeLessThan(Number(a.dashoffset));
	});

	it('draws a single segment as the full ring', () => {
		const [seg] = donutSegments([5], C, 4, 12);
		expect(segmentDash(seg, C)).toEqual({ dasharray: `${Math.round(C * 100) / 100} 0`, dashoffset: '0' });
	});
});

describe('polar', () => {
	it('measures clockwise from 3 o’clock in SVG space', () => {
		const near = (p: Point, q: Point) => p.forEach((v, i) => expect(v).toBeCloseTo(q[i]));
		near(polar(50, 50, 10, 0), [60, 50]);
		near(polar(50, 50, 10, 90), [50, 60]);
		near(polar(50, 50, 10, -90), [50, 40]);
	});
});

describe('world map', () => {
	const world = JSON.parse(readFileSync(resolve(process.cwd(), 'static/geo/countries-110m.geojson'), 'utf8'));
	const polygons = polygonsOf(world);
	const dots = landDots(polygons);
	const isLand = (lng: number, lat: number) =>
		polygons.some((p) => inPolygon(lng, lat, p) || inPolygon(lng + 360, lat, p));

	it('reads every polygon from the bundled file', () => {
		expect(polygons.length).toBeGreaterThan(200);
	});

	it.each([
		['Paris', 2.35, 48.85, true],
		['Denver', -104.99, 39.74, true],
		['Nairobi', 36.82, -1.29, true],
		['Sydney', 150.9, -33.8, true],
		['the mid-Atlantic', -30, 30, false],
		['the Pacific', -150, 0, false],
		['the Norwegian Sea', 0, 66, false],
	])('knows %s', (_name, lng, lat, land) => {
		expect(isLand(lng, lat)).toBe(land);
	});

	it('keeps antimeridian rings from smearing land across the map', () => {
		// Before unwrapping, Chukotka's ring filled the latitude rows from Alaska to Norway
		expect(dots.some(([lng, lat]) => lng > -10 && lng < 4 && lat > 63 && lat < 70)).toBe(false);
		expect(isLand(177, 65)).toBe(true);
	});

	it('lays a grid of land dots inside the map band', () => {
		expect(dots.length).toBeGreaterThan(1500);
		expect(dots.length).toBeLessThan(3000);
		for (const [lng, lat] of dots) {
			expect(Math.abs(lng)).toBeLessThanOrEqual(180);
			expect(lat).toBeLessThanOrEqual(MAP_TOP);
			expect(lat).toBeGreaterThanOrEqual(MAP_BOTTOM);
		}
	});

	it('skips malformed input instead of throwing', () => {
		expect(polygonsOf(null)).toEqual([]);
		expect(polygonsOf({ features: 'x' })).toEqual([]);
		expect(polygonsOf({ features: [null, { geometry: { type: 'Point', coordinates: [1, 2] } }, {}] })).toEqual([]);
		expect(landDots([])).toEqual([]);
	});
});

describe('project', () => {
	it('maps the band edges onto the map edges', () => {
		expect(project(-180, MAP_TOP, 900, 400)).toEqual([0, 0]);
		expect(project(180, MAP_BOTTOM, 900, 400)).toEqual([900, 400]);
		expect(project(0, 12, 900, 400)[0]).toBe(450);
	});
});

describe('arcPath', () => {
	it('bows a quadratic arc upward between the two points', () => {
		expect(arcPath([0, 100], [100, 100])).toBe('M0,100 Q50,68 100,100');
		expect(arcPath([10, 10], [10, 10])).not.toMatch(/NaN/);
	});
});

describe('mapLabels (NET-192)', () => {
	const spot = (x: number, y: number, text = 'Germany 40') => ({ x, y, r: 5, text });

	it('labels the busiest spots up to the limit', () => {
		expect(mapLabels([spot(100, 100), spot(100, 200), spot(100, 300)], 900, 2)).toEqual([true, true, false]);
	});

	it('leaves off a label that would overlap one already placed, keeping the busier one', () => {
		// Germany and the Netherlands sit a few pixels apart: the second label would print over the first
		expect(mapLabels([spot(480, 120), spot(476, 116, 'Netherlands 12'), spot(100, 300)], 900, 5)).toEqual([true, false, true]);
	});

	it('flips labels left near the right edge, so a right-edge label clears a spot to its left', () => {
		expect(mapLabels([spot(860, 100), spot(700, 100)], 900, 5)).toEqual([true, true]);
	});
});
