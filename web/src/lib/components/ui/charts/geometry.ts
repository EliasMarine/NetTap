/**
 * Pure chart maths for the hand-drawn SVG charts (PLAN.md §5.4). No DOM, no Svelte.
 */

export type Point = readonly [number, number];

const STEP_MULTIPLIERS = [1, 2, 2.5, 5, 10] as const;

/**
 * Round axis: the smallest 1/2/2.5/5 × 10ⁿ step whose `ticks` steps cover `max`.
 * `whole` (NET-286, a count axis): the step is a whole number, so no tick is a fraction a label would round.
 */
export function niceAxis(max: number, ticks = 4, whole = false): { step: number; top: number; values: number[] } {
	if (!Number.isFinite(max) || max <= 0) return { step: 1, top: ticks, values: range(ticks, 1) };
	// raw lies in [10ⁿ, 10ⁿ⁺¹), so one of these multipliers always covers it
	// OLD CODE START — NET-286: the scale went below 1, so a peak of 1 or 2 got steps of 0.2 or 0.5
	// const scale = 10 ** Math.floor(Math.log10(max / ticks));
	// const step = STEP_MULTIPLIERS.map((m) => m * scale).find((s) => s * ticks >= max) ?? 10 * scale;
	// OLD CODE END
	const scale = Math.max(whole ? 1 : 0, 10 ** Math.floor(Math.log10(max / ticks)));
	const step =
		STEP_MULTIPLIERS.map((m) => m * scale)
			.filter((s) => !whole || Number.isInteger(s))
			.find((s) => s * ticks >= max) ?? 10 * scale;
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

/** The runs of points with a finite y, so a missing value stays a gap instead of a line across it (NET-205). */
export function finiteRuns(points: readonly Point[]): Point[][] {
	const breaks = points.flatMap(([, y], i) => (Number.isFinite(y) ? [] : [i]));
	const bounds = [-1, ...breaks, points.length];
	return bounds
		.slice(1)
		.map((end, k) => points.slice(bounds[k] + 1, end))
		.filter((run) => run.length > 0);
}

/** The inclusive index runs [first, last] where `has(i)` is false: the stretches a gaps chart marks "No data". */
export function emptyRuns(n: number, has: (i: number) => boolean): [number, number][] {
	const runs: [number, number][] = [];
	for (let i = 0; i < n; i++) {
		if (has(i)) continue;
		const last = runs.at(-1);
		if (last && last[1] === i - 1) runs[runs.length - 1] = [last[0], i];
		else runs.push([i, i]);
	}
	return runs;
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

/**
 * niceAxis trimmed to the first round value that covers `max`, so a 4.7 GB peak gets a
 * 0–5 axis instead of 0–8 and the line fills the plot.
 */
export function fitAxis(max: number, ticks = 5, whole = false): { top: number; values: number[] } {
	// OLD CODE: const { top, values } = niceAxis(max, ticks); (NET-286: a count axis passes `whole`)
	const { top, values } = niceAxis(max, ticks, whole);
	const cover = values.find((v) => v > 0 && v >= max);
	if (!(max > 0) || cover === undefined) return { top, values };
	return { top: cover, values: values.filter((v) => v <= cover) };
}

/**
 * fitAxis in the decimal unit the byte formatters print (1 GB = 10^9 bytes, NET-166), so a
 * 28 GB peak gets 0, 10, 20, 30 GB ticks, each a whole multiple of the unit.
 */
export function fitByteAxis(max: number, ticks = 5): { top: number; values: number[] } {
	// OLD CODE START — 2026-11-06 (NET-166): 1024-based units, while the formatters now divide by 1,000
	// // log2 is exact on powers of two, so 1 GiB lands on the GiB unit, not MiB
	// const unit = max >= 1024 ? 1024 ** Math.floor(Math.log2(max) / 10) : 1;
	// OLD CODE END
	// log10 is exact on powers of ten, so 1 GB lands on the GB unit, not MB
	const unit = max >= 1000 ? 1000 ** Math.floor(Math.log10(max) / 3) : 1;
	const { top, values } = fitAxis(max / unit, ticks);
	return { top: top * unit, values: values.map((v) => v * unit) };
}

/** Label every Nth point so neighbouring x labels sit at least `minGap` px apart. */
export function labelStep(count: number, plotWidth: number, minGap = 64): number {
	if (count <= 1 || !(plotWidth > 0)) return 1;
	const fit = Math.max(2, Math.floor(plotWidth / minGap));
	return Math.max(1, Math.ceil(count / fit));
}

/**
 * The points that get an x label (NET-354). Distinct labels: every `every`th point, as before.
 * Labels that repeat (a day label on hourly points): only where the text changes, the first point
 * of each day, kept at least `minGap` px apart from left to right. Point 0 counts as a change only
 * when `firstIsChange` (the point before it would read differently), so a partial first day is not
 * labelled while a later day starts on the chart.
 * shortcut: a day label sits on its day's first bucket, up to one bucket (≤ 3 h) after local
 * midnight; interpolate calendar ticks if chart buckets ever grow past 3 h.
 */
export function labelIndices(texts: readonly string[], every: number, slot: number, minGap: number, firstIsChange: boolean): number[] {
	const repeats = texts.some((t, i) => i > 0 && t === texts[i - 1]);
	if (!repeats) return texts.flatMap((_, i) => (i % every === 0 ? [i] : []));
	const changes = texts.flatMap((t, i) => ((i === 0 ? firstIsChange : t !== texts[i - 1]) ? [i] : []));
	if (changes.length === 0) return texts.length ? [0] : [];
	return changes.reduce<number[]>((kept, i) => (kept.length && (i - kept[kept.length - 1]) * slot < minGap ? kept : [...kept, i]), []);
}

/** Index of the evenly spaced point nearest to `x`, clamped to the data. */
export function nearestIndex(x: number, left: number, plotWidth: number, count: number): number {
	if (count <= 1 || !(plotWidth > 0) || !Number.isFinite(x)) return 0;
	const i = Math.round(((x - left) / plotWidth) * (count - 1));
	return Math.max(0, Math.min(count - 1, i));
}

// OLD CODE START — one line however long: a long reason ran past a phone-width chart (chart gaps, round 1)
// /** The pill tooltip's box: width estimated from the text, kept inside the chart. */
// export function tipBox(x: number, y: number, text: string, chartWidth: number): { x: number; y: number; width: number } {
// 	const width = Math.round(text.length * 6.2 + 24);
// 	return { x: Math.max(2, Math.min(x - width / 2, chartWidth - width - 2)), y: Math.max(y - 38, 0), width };
// }
// OLD CODE END

/** A tooltip character's estimated width (px), its side padding together, its line step, and its most lines. */
const TIP_CHAR = 6.2;
const TIP_PAD = 24;
const TIP_LINE = 14;
const TIP_MAX_LINES = 3;

/** Words wrapped greedily to `max` characters, at most TIP_MAX_LINES lines, the last cut with "…". */
function wrapTip(text: string, max: number): string[] {
	const lines: string[] = [];
	let rest = text.trim();
	while (rest && lines.length < TIP_MAX_LINES) {
		if (rest.length <= max) {
			lines.push(rest);
			rest = '';
			break;
		}
		const space = rest.lastIndexOf(' ', max);
		const end = space > 0 ? space : max; // one word longer than a line is cut where the line ends
		lines.push(rest.slice(0, end).trimEnd());
		rest = rest.slice(end).trimStart();
	}
	if (rest) lines[lines.length - 1] = `${lines[lines.length - 1].slice(0, max - 1).trimEnd()}…`;
	return lines.length ? lines : [''];
}

/** The pill tooltip's box: width estimated from the text, wrapped to fit and kept inside the chart. One line is 24 px tall. */
export function tipBox(
	x: number,
	y: number,
	text: string,
	chartWidth: number,
): { x: number; y: number; width: number; height: number; lines: string[] } {
	const lines = wrapTip(text, Math.max(8, Math.floor((chartWidth - 4 - TIP_PAD) / TIP_CHAR)));
	const width = Math.round(Math.max(...lines.map((l) => l.length)) * TIP_CHAR + TIP_PAD);
	const height = 24 + TIP_LINE * (lines.length - 1);
	return { x: Math.max(2, Math.min(x - width / 2, chartWidth - width - 2)), y: Math.max(y - 14 - height, 0), width, height, lines };
}

/** A map label sits left of its dot once the dot is past this share of the width. */
export const LABEL_FLIP = 0.82;

export interface LabelSpot {
	x: number;
	y: number;
	r: number;
	text: string;
}

/**
 * Which hotspots get a visible map label (NET-192): the first `max` in the order given (busiest
 * first), skipping any whose label box, estimated from its text like tipBox, overlaps one already
 * placed. A skipped hotspot keeps its dot and tooltip.
 */
export function mapLabels(spots: readonly LabelSpot[], width: number, max: number): boolean[] {
	const placed: { l: number; r: number; t: number; b: number }[] = [];
	return spots.map((s, i) => {
		if (i >= max) return false;
		const w = s.text.length * 6.2;
		const x0 = s.x > width * LABEL_FLIP ? s.x - s.r - 6 - w : s.x + s.r + 6;
		const box = { l: x0, r: x0 + w, t: s.y - 8, b: s.y + 6 };
		if (placed.some((p) => box.l < p.r && p.l < box.r && box.t < p.b && p.t < box.b)) return false;
		placed.push(box);
		return true;
	});
}

/**
 * SVG dash attributes for a donutSegments() segment on a `<circle>` rotated -90°, so the
 * ring starts at 12 o'clock and runs clockwise. A negative offset moves the dash forward.
 */
export function segmentDash(seg: DonutSegment, circumference: number): { dasharray: string; dashoffset: string } {
	return {
		dasharray: `${fmt(seg.dash)} ${fmt(Math.max(0, circumference - seg.dash))}`,
		dashoffset: fmt(-seg.offset),
	};
}

/** The point `deg` degrees clockwise from 3 o'clock (SVG's y axis points down). */
export function polar(cx: number, cy: number, r: number, deg: number): Point {
	const a = (deg * Math.PI) / 180;
	return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}

export type Rings = readonly (readonly Point[])[];

/**
 * Every polygon (outer ring + holes) in a GeoJSON FeatureCollection; anything malformed is
 * skipped. Rings that cross the antimeridian (Fiji, Chukotka) move to 0–360° so they don't
 * smear land across the whole map.
 */
export function polygonsOf(geojson: unknown): Rings[] {
	const features = (geojson as { features?: unknown } | null)?.features;
	if (!Array.isArray(features)) return [];
	const polygons: Rings[] = features.flatMap((f) => {
		const g = (f as { geometry?: { type?: string; coordinates?: unknown } } | null)?.geometry;
		if (!Array.isArray(g?.coordinates)) return [];
		if (g.type === 'Polygon') return [g.coordinates as Rings];
		if (g.type === 'MultiPolygon') return g.coordinates as Rings[];
		return [];
	});
	return polygons.filter(Array.isArray).map((rings) => rings.filter(Array.isArray).map(unwrapRing));
}

/** A ring that crosses 180°, moved onto 0–360°; any other ring is returned as it is (the same array). */
export function unwrapRing(ring: readonly Point[]): readonly Point[] {
	const crosses = ring.some((p, i) => i > 0 && Math.abs(p[0] - ring[i - 1][0]) > 180);
	return crosses ? ring.map(([x, y]) => [x < 0 ? x + 360 : x, y] as const) : ring;
}

/** The map's latitude band: everything inhabited, with Antarctica and the far Arctic left out. */
export const MAP_TOP = 80;
export const MAP_BOTTOM = -56;

/** Land dots as [lng, lat] on a fixed grid: point-in-polygon, run once per map. */
export function landDots(polygons: readonly Rings[], step = 2.6): Point[] {
	const boxes = polygons.map((rings) => {
		const outer = rings[0] ?? [];
		const xs = outer.map((p) => p[0]);
		const ys = outer.map((p) => p[1]);
		return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)] as const;
	});
	const hit = (lng: number, lat: number) =>
		polygons.some((rings, i) => {
			const [x0, y0, x1, y1] = boxes[i];
			return lng >= x0 && lng <= x1 && lat >= y0 && lat <= y1 && inPolygon(lng, lat, rings);
		});
	const dots: Point[] = [];
	for (let row = 0; MAP_TOP - 2 - row * step >= MAP_BOTTOM; row++) {
		const lat = MAP_TOP - 2 - row * step;
		for (let col = 0; -178 + col * step <= 178; col++) {
			const lng = -178 + col * step;
			// unwrapped rings live past 180°, so test the same spot one turn east too
			if (hit(lng, lat) || hit(lng + 360, lat)) dots.push([lng, lat]);
		}
	}
	return dots;
}

/** Equirectangular projection of the MAP_TOP..MAP_BOTTOM band onto width × height. */
export function project(lng: number, lat: number, width: number, height: number): Point {
	return [((lng + 180) / 360) * width, ((MAP_TOP - lat) / (MAP_TOP - MAP_BOTTOM)) * height];
}

/** A quadratic arc from `a` to `b` that bows upward by a third of its length. */
export function arcPath([ax, ay]: Point, [bx, by]: Point): string {
	const lift = Math.hypot(bx - ax, by - ay) * 0.32;
	return `M${fmt(ax)},${fmt(ay)} Q${fmt((ax + bx) / 2)},${fmt((ay + by) / 2 - lift)} ${fmt(bx)},${fmt(by)}`;
}
