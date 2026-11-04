/**
 * Pure chart maths for the hand-drawn SVG charts (PLAN.md §5.4). No DOM, no Svelte.
 */

export type Point = readonly [number, number];

const STEP_MULTIPLIERS = [1, 2, 2.5, 5, 10] as const;

/** Round axis: the smallest 1/2/2.5/5 × 10ⁿ step whose `ticks` steps cover `max`. */
export function niceAxis(max: number, ticks = 4): { step: number; top: number; values: number[] } {
	if (!Number.isFinite(max) || max <= 0) return { step: 1, top: ticks, values: range(ticks, 1) };
	// raw lies in [10ⁿ, 10ⁿ⁺¹), so one of these multipliers always covers it
	const scale = 10 ** Math.floor(Math.log10(max / ticks));
	const step = STEP_MULTIPLIERS.map((m) => m * scale).find((s) => s * ticks >= max) ?? 10 * scale;
	return { step, top: step * ticks, values: range(ticks, step) };
}

function range(ticks: number, step: number): number[] {
	return Array.from({ length: ticks + 1 }, (_, i) => +(i * step).toPrecision(12));
}

/**
 * Monotone cubic path (Fritsch–Carlson, the same curve as d3.curveMonotoneX):
 * never overshoots its data, so a non-negative series never dips below the baseline.
 */
export function monotonePath(points: readonly Point[]): string {
	const pts = points.filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
	if (pts.length === 0) return '';
	if (pts.length === 1) return `M${fmt(pts[0][0])},${fmt(pts[0][1])}`;
	const n = pts.length;
	const slopes = pts.slice(1).map(([x, y], i) => {
		const dx = x - pts[i][0];
		return dx === 0 ? 0 : (y - pts[i][1]) / dx;
	});
	const tangents = pts.map((_, i) => {
		if (i === 0) return slopes[0];
		if (i === n - 1) return slopes[n - 2];
		const a = slopes[i - 1];
		const b = slopes[i];
		if (a * b <= 0) return 0;
		const dxa = pts[i][0] - pts[i - 1][0];
		const dxb = pts[i + 1][0] - pts[i][0];
		// weighted harmonic mean keeps the curve monotone between points
		return (3 * (dxa + dxb)) / ((2 * dxb + dxa) / a + (dxb + 2 * dxa) / b);
	});
	let d = `M${fmt(pts[0][0])},${fmt(pts[0][1])}`;
	for (let i = 0; i < n - 1; i++) {
		const [x0, y0] = pts[i];
		const [x1, y1] = pts[i + 1];
		const h = (x1 - x0) / 3;
		d += `C${fmt(x0 + h)},${fmt(y0 + h * tangents[i])},${fmt(x1 - h)},${fmt(y1 - h * tangents[i + 1])},${fmt(x1)},${fmt(y1)}`;
	}
	return d;
}

function fmt(v: number): string {
	return String(Math.round(v * 100) / 100);
}

export interface DonutSegment {
	/** Index into the caller's original array (zero values keep their index but are not drawn). */
	index: number;
	dash: number;
	offset: number;
	round: boolean;
}

/**
 * Donut dashes with gaps that never overlap (PLAN.md §5.4, rules from c8267af:PLAN.md §6 PR 3).
 * `offset` is the distance along the ring where the dash starts.
 */
export function donutSegments(
	values: readonly number[],
	circumference: number,
	gap: number,
	strokeWidth: number,
): DonutSegment[] {
	const clean = values.map((v) => (Number.isFinite(v) && v > 0 ? v : 0));
	const total = clean.reduce((a, b) => a + b, 0);
	if (total === 0) return [];
	const live = clean.filter((v) => v > 0).length;
	const cap = strokeWidth / 2;
	const out: DonutSegment[] = [];
	let cumulative = 0;
	clean.forEach((v, index) => {
		if (v === 0) return;
		const share = (circumference * v) / total;
		const start = cumulative;
		cumulative += share;
		if (live === 1) {
			out.push({ index, dash: circumference, offset: 0, round: false });
			return;
		}
		const g = Math.min(gap, share / 2);
		const body = share - g;
		const round = body - 2 * cap >= 0.5;
		out.push({
			index,
			dash: round ? body - 2 * cap : body,
			offset: start + g / 2 + (round ? cap : 0),
			round,
		});
	});
	return out;
}

/**
 * Severity gauge ticks: `total` ticks split by share with largest-remainder rounding.
 * Every non-zero bucket gets at least one tick; an all-zero input returns all zeros
 * (the caller draws neutral ticks).
 */
export function allocateTicks(counts: readonly number[], total = 36): number[] {
	const clean = counts.map((c) => (Number.isFinite(c) && c > 0 ? c : 0));
	const sum = clean.reduce((a, b) => a + b, 0);
	if (sum === 0) return clean.map(() => 0);
	const nonZero = clean.filter((c) => c > 0).length;
	if (nonZero > total) throw new Error(`allocateTicks: ${nonZero} buckets need more than ${total} ticks`);
	const floors = clean.map((c) => (c > 0 ? Math.max(1, Math.floor((c / sum) * total)) : 0));
	let left = total - floors.reduce((a, b) => a + b, 0);
	const byRemainder = clean
		.map((c, i) => ({ i, r: (c / sum) * total - Math.floor((c / sum) * total) }))
		.filter(({ i }) => clean[i] > 0)
		.sort((a, b) => b.r - a.r || a.i - b.i);
	for (let k = 0; left > 0; k++, left--) floors[byRemainder[k % byRemainder.length].i]++;
	// The minimum-one rule can overshoot; take the excess back from the largest buckets.
	while (left < 0) {
		const i = floors.indexOf(Math.max(...floors));
		floors[i]--;
		left++;
	}
	return floors;
}

/** Ray-casting point-in-polygon over a GeoJSON ring list (first ring outer, the rest holes). */
export function inPolygon(lng: number, lat: number, rings: readonly (readonly Point[])[]): boolean {
	let inside = false;
	for (const ring of rings) {
		for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
			const [xi, yi] = ring[i];
			const [xj, yj] = ring[j];
			if (yi > lat !== yj > lat && lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
		}
	}
	return inside;
}
