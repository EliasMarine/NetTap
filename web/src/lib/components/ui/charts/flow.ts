/**
 * Network flow: totals and layout for the device → protocol → destination chart
 * (NetworkFlow.svelte). Pure, so every rule here is unit-tested without a DOM.
 *
 * The daemon reports the top sources, their transports and their top destinations
 * (`/api/traffic/connections/sankey`). Everything those sources sent outside the top
 * destinations becomes one "Other destinations" node, so every column sums to the same total
 * and the chart is drawn on one scale. Reported figures are never adjusted: when the two
 * searches behind the endpoint disagree by more than rounding, `consistent` is false and the
 * component shows the reported values in a table instead.
 */
import type { SankeyLink, SankeyNode } from '$api/traffic';

export type FlowKind = 'source' | 'protocol' | 'destination';

export interface FlowInput {
	sources: SankeyNode[];
	protocols: SankeyNode[];
	destinations: SankeyNode[];
	links: SankeyLink[];
}

export interface FlowEntry {
	kind: FlowKind;
	id: string;
	label: string;
	value: number;
	country?: string;
	/** The synthetic "Other destinations" node: not filterable. */
	other?: boolean;
	/** Bytes by protocol id, largest first. */
	split: { protocol: string; value: number }[];
}

export interface FlowData {
	consistent: boolean;
	sources: FlowEntry[];
	protocols: FlowEntry[];
	destinations: FlowEntry[];
	/** Source → protocol links, then protocol → destination links (Other included). */
	left: SankeyLink[];
	right: SankeyLink[];
	/** Protocol id → the `--data-N` token it is drawn in. */
	colours: Map<string, number>;
}

export const OTHER_ID = '__other__';
export const FLOW_MIN_WIDTH = 640;

const FIXED_COLOURS: Record<string, number> = { tcp: 1, udp: 2, icmp: 5 };
const SPARE_COLOURS = [3, 4, 6];

const clean = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : 0);
const byValue = <T extends { value: number }>(a: T, b: T) => b.value - a.value;

function sumBy(links: SankeyLink[], key: 'source' | 'target'): Map<string, number> {
	return links.reduce((m, l) => m.set(l[key], (m.get(l[key]) ?? 0) + l.value), new Map<string, number>());
}

function splitOf(links: SankeyLink[], protocolKey: 'source' | 'target') {
	return links.map((l) => ({ protocol: l[protocolKey], value: l.value })).sort(byValue);
}

/** TCP, UDP and ICMP keep their colour in every time range; anything else takes a spare by size. */
function protocolColours(protocols: FlowEntry[]): Map<string, number> {
	const spare = protocols.filter((p) => !(p.id in FIXED_COLOURS)).sort(byValue);
	return new Map([
		...protocols.filter((p) => p.id in FIXED_COLOURS).map((p) => [p.id, FIXED_COLOURS[p.id]] as const),
		...spare.map((p, i) => [p.id, SPARE_COLOURS[i] ?? 5] as const),
	]);
}

/** Totals for both views. Node values come from the links, so every column adds up to the same total. */
export function flowData(input: FlowInput): FlowData {
	const ids = (nodes: SankeyNode[]) => new Set(nodes.map((n) => n.id));
	const [srcIds, protoIds, dstIds] = [ids(input.sources), ids(input.protocols), ids(input.destinations)];
	const links = input.links.map((l) => ({ ...l, value: clean(l.value) })).filter((l) => l.value > 0);
	const left = links.filter((l) => srcIds.has(l.source) && protoIds.has(l.target));
	const reportedRight = links.filter((l) => protoIds.has(l.source) && dstIds.has(l.target));

	const inflow = sumBy(left, 'target');
	const outflow = sumBy(reportedRight, 'source');
	// Two searches a few milliseconds apart: only rounding is forgiven, never a real difference
	const consistent = [...protoIds].every((p) => {
		const inP = inflow.get(p) ?? 0;
		return (outflow.get(p) ?? 0) <= inP + Math.max(1, inP * 1e-9);
	});

	const otherLinks = consistent
		? [...protoIds]
				.map((p) => ({ source: p, target: OTHER_ID, value: (inflow.get(p) ?? 0) - (outflow.get(p) ?? 0) }))
				.filter((l) => l.value >= 1)
		: [];
	const right = [...reportedRight, ...otherLinks];

	const entry = (kind: FlowKind, n: SankeyNode, value: number, split: FlowEntry['split']): FlowEntry => ({
		kind,
		id: n.id,
		label: n.label || n.id,
		value,
		...(n.country ? { country: n.country } : {}),
		split,
	});
	const srcTotals = sumBy(left, 'source');
	const dstTotals = sumBy(right, 'target');
	const pick = (reported: number, fromLinks: number | undefined) => (consistent ? (fromLinks ?? 0) : clean(reported));

	// A node with nothing to draw (no bytes, or no transport on any of its sessions) is left out
	const ranked = (entries: FlowEntry[]) => entries.filter((e) => e.value > 0).sort(byValue);

	const sources = ranked(
		input.sources.map((n) => entry('source', n, pick(n.value, srcTotals.get(n.id)), splitOf(left.filter((l) => l.source === n.id), 'target'))),
	);
	const protocols = ranked(
		input.protocols.map((n) => {
			const value = pick(n.value, inflow.get(n.id));
			return entry('protocol', n, value, [{ protocol: n.id, value }]);
		}),
	);
	const destinations = [
		...ranked(
			input.destinations.map((n) => entry('destination', n, pick(n.value, dstTotals.get(n.id)), splitOf(right.filter((l) => l.target === n.id), 'source'))),
		),
		...(otherLinks.length
			? [{ kind: 'destination' as const, id: OTHER_ID, label: 'Other destinations', value: dstTotals.get(OTHER_ID) ?? 0, other: true, split: splitOf(otherLinks, 'source') }]
			: []),
	];

	return { consistent, sources, protocols, destinations, left, right, colours: protocolColours(protocols) };
}

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

export interface FlowSizes {
	/** A source or destination label row's rendered height. */
	labelH: number;
	/** A protocol chip's rendered height. */
	chipH: number;
}

export const DEFAULT_SIZES: FlowSizes = { labelH: 16, chipH: 24 };

export interface PlacedNode extends FlowEntry {
	key: string;
	colour: number;
	/** The bar, exactly to scale. */
	x: number;
	w: number;
	y: number;
	h: number;
	/** The label's vertical centre, moved off the bar's centre when labels would overlap. */
	labelY: number;
	labelH: number;
	moved: boolean;
}

export interface PlacedRibbon {
	key: string;
	from: string;
	to: string;
	value: number;
	colour: number;
	d: string;
	/** The ribbon's midpoint, where its tooltip sits. */
	mx: number;
	my: number;
}

export interface FlowLayout {
	width: number;
	height: number;
	total: number;
	srcLabelW: number;
	dstLabelX: number;
	dstLabelW: number;
	chipX: number;
	/** Room for a protocol chip before the destination bars; a longer chip cuts its figures. */
	chipMaxW: number;
	sources: PlacedNode[];
	protocols: PlacedNode[];
	destinations: PlacedNode[];
	ribbons: PlacedRibbon[];
}

const GAP = { source: 14, protocol: 30, destination: 14 } as const;
const LABEL_GAP = 4;
const MOVED_PX = 3;
const BAR_W = 10;
const PROTO_W = 14;
const BAR_TO_LABEL = 12;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
export const nodeKey = (kind: FlowKind, id: string) => `${kind[0]}:${id}`;

/**
 * Label centres as close to their targets as the labels' real heights allow: neighbours at
 * least half their combined heights plus a gap apart, every label inside [0, height].
 * Fits whenever Σh + (n − 1)·gap ≤ height, which flowLayout guarantees by growing the chart.
 */
export function dodgeLabels(targets: number[], heights: number[], height: number, gap = LABEL_GAP): number[] {
	const sep = (i: number) => (heights[i - 1] + heights[i]) / 2 + gap;
	const down = targets.reduce<number[]>((acc, t, i) => {
		const own = clamp(t, heights[i] / 2, height - heights[i] / 2);
		return [...acc, i === 0 ? own : Math.max(own, acc[i - 1] + sep(i))];
	}, []);
	return down.reduceRight<number[]>((acc, y, i) => {
		const max = i === down.length - 1 ? height - heights[i] / 2 : acc[0] - sep(i + 1);
		return [Math.min(y, max), ...acc];
	}, []);
}

function ribbonPath(x0: number, y0: number, x1: number, y1: number, w: number): string {
	const f = (n: number) => n.toFixed(1);
	const xm = (x0 + x1) / 2;
	return (
		`M${f(x0)},${f(y0)} C${f(xm)},${f(y0)} ${f(xm)},${f(y1)} ${f(x1)},${f(y1)} ` +
		`L${f(x1)},${f(y1 + w)} C${f(xm)},${f(y1 + w)} ${f(xm)},${f(y0 + w)} ${f(x0)},${f(y0 + w)} Z`
	);
}

function stackColumn(nodes: FlowEntry[], kind: FlowKind, x: number, w: number, scale: number, height: number, labelH: number, colours: Map<string, number>): PlacedNode[] {
	const hs = nodes.map((n) => n.value * scale);
	const colH = hs.reduce((a, h) => a + h, 0) + Math.max(0, nodes.length - 1) * GAP[kind];
	const tops = hs.reduce<number[]>((acc, h, i) => [...acc, i === 0 ? (height - colH) / 2 : acc[i - 1] + hs[i - 1] + GAP[kind]], []);
	const centres = tops.map((y, i) => y + hs[i] / 2);
	const labels = dodgeLabels(centres, nodes.map(() => labelH), height);
	return nodes.map((n, i) => ({
		...n,
		key: nodeKey(kind, n.id),
		colour: kind === 'protocol' ? (colours.get(n.id) ?? 5) : 0,
		x,
		w,
		y: tops[i],
		h: hs[i],
		labelY: labels[i],
		labelH,
		moved: Math.abs(labels[i] - centres[i]) > MOVED_PX,
	}));
}

/** One scale for all three columns, so a gigabyte is the same height everywhere. */
export function flowLayout(data: FlowData, width: number, sizes: FlowSizes = DEFAULT_SIZES): FlowLayout {
	const { sources, protocols, destinations } = data;
	const total = protocols.reduce((a, p) => a + p.value, 0);
	const need = (n: number, h: number) => n * h + Math.max(0, n - 1) * LABEL_GAP;
	const maxN = Math.max(sources.length, destinations.length);
	const height = Math.ceil(
		Math.max(
			clamp(maxN * 46, 240, 520),
			need(sources.length, sizes.labelH),
			need(destinations.length, sizes.labelH),
			need(protocols.length, sizes.chipH),
		),
	);
	const budget = (n: number, gap: number) => height - Math.max(0, n - 1) * gap;
	const scale =
		total > 0
			? Math.max(0, Math.min(budget(sources.length, GAP.source), budget(protocols.length, GAP.protocol), budget(destinations.length, GAP.destination))) / total
			: 0;

	const srcLabelW = clamp(0.24 * width, 160, 260);
	const dstLabelW = clamp(0.24 * width, 160, 250);
	const srcX = srcLabelW + BAR_TO_LABEL;
	const protoX = width / 2 - PROTO_W / 2;
	const dstX = width - dstLabelW - BAR_TO_LABEL - BAR_W;

	const s = stackColumn(sources, 'source', srcX, BAR_W, scale, height, sizes.labelH, data.colours);
	const p = stackColumn(protocols, 'protocol', protoX, PROTO_W, scale, height, sizes.chipH, data.colours);
	const d = stackColumn(destinations, 'destination', dstX, BAR_W, scale, height, sizes.labelH, data.colours);

	const ribbons = [
		...side(data.left, s, p, 'source', 'protocol', scale, data.colours, srcX + BAR_W, protoX),
		...side(data.right, p, d, 'protocol', 'destination', scale, data.colours, protoX + PROTO_W, dstX),
	];
	const chipX = protoX + PROTO_W + 10;
	return {
		width,
		height,
		total,
		srcLabelW,
		dstLabelX: dstX + BAR_W + BAR_TO_LABEL,
		dstLabelW,
		chipX,
		chipMaxW: dstX - chipX - 8,
		sources: s,
		protocols: p,
		destinations: d,
		ribbons,
	};
}

/**
 * Ribbons between two columns, stacked flush: at each end, in the order of the far column
 * (the standard ordering, which keeps crossings down).
 */
function side(
	links: SankeyLink[],
	from: PlacedNode[],
	to: PlacedNode[],
	fromKind: FlowKind,
	toKind: FlowKind,
	scale: number,
	colours: Map<string, number>,
	x0: number,
	x1: number,
): PlacedRibbon[] {
	const rank = (nodes: PlacedNode[]) => new Map(nodes.map((n, i) => [n.id, i]));
	const [fromRank, toRank] = [rank(from), rank(to)];
	const fromNode = new Map(from.map((n) => [n.id, n]));
	const toNode = new Map(to.map((n) => [n.id, n]));
	const known = links.filter((l) => fromRank.has(l.source) && toRank.has(l.target));
	const offsets = (order: SankeyLink[], end: 'source' | 'target') =>
		order.reduce(
			(acc, l) => {
				const used = acc.used.get(l[end]) ?? 0;
				return { used: new Map(acc.used).set(l[end], used + l.value * scale), at: new Map(acc.at).set(l, used) };
			},
			{ used: new Map<string, number>(), at: new Map<SankeyLink, number>() },
		).at;
	const startAt = offsets([...known].sort((a, b) => toRank.get(a.target)! - toRank.get(b.target)!), 'source');
	const endAt = offsets([...known].sort((a, b) => fromRank.get(a.source)! - fromRank.get(b.source)!), 'target');
	return known.map((l) => {
		const w = l.value * scale;
		const y0 = fromNode.get(l.source)!.y + startAt.get(l)!;
		const y1 = toNode.get(l.target)!.y + endAt.get(l)!;
		const protocol = fromKind === 'protocol' ? l.source : l.target;
		return {
			key: `${nodeKey(fromKind, l.source)}>${nodeKey(toKind, l.target)}`,
			from: nodeKey(fromKind, l.source),
			to: nodeKey(toKind, l.target),
			value: l.value,
			colour: colours.get(protocol) ?? 5,
			d: ribbonPath(x0, y0, x1, y1, w),
			mx: (x0 + x1) / 2,
			my: (y0 + y1) / 2 + w / 2,
		};
	});
}

// ---------------------------------------------------------------------------
// Words
// ---------------------------------------------------------------------------

/** "37%", or "<1%" for a sliver that would otherwise read as nothing. */
export function share(value: number, total: number): string {
	if (!(total > 0) || !(value > 0)) return '0%';
	const p = (value / total) * 100;
	return p < 1 ? '<1%' : `${Math.round(p)}%`;
}

/** "TCP 70%, UDP 30%": an entry's bytes by protocol, largest first. */
export function splitText(entry: FlowEntry, protocols: readonly FlowEntry[]): string {
	const label = (id: string) => protocols.find((p) => p.id === id)?.label ?? id.toUpperCase();
	return entry.split.map((s) => `${label(s.protocol)} ${share(s.value, entry.value)}`).join(', ');
}
