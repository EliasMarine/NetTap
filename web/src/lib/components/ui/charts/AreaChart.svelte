<!--
  AreaChart: one or two monotone lines over gradient fills (design system Charts preview).
  The headline point gets a band, ringed dots and the pill tooltip; hovering moves the
  tooltip with a dashed guide, and leaving restores the headline. Hover is a mouse extra:
  the chart is role="img" and its aria-label carries the headline. Empty series render nothing.
-->
<script lang="ts" module>
	export interface AreaSeries {
		key: string;
		label: string;
		/** The `--data-N` token: 1 download, 2 upload. */
		colour: 1 | 2;
		points: { t: number | string; v: number }[];
	}
</script>

<script lang="ts">
	import { monotonePath, finiteRuns, fitAxis, fitByteAxis, labelStep, nearestIndex, tipBox, type Point } from './geometry';
	import { observeWidth } from './resize';

	let {
		series,
		formatX = String,
		formatY,
		formatTip,
		highlightIndex,
		ariaLabel,
		height = 220,
		bytes = false,
		gaps = false,
	}: {
		series: AreaSeries[];
		formatX?: (t: number | string) => string;
		formatY: (v: number) => string;
		/** Tooltip text for point `i` across all series, e.g. "21:00 · ↓ 4.7 GB · ↑ 380 MB". */
		formatTip: (i: number) => string;
		highlightIndex?: number;
		ariaLabel: string;
		/** Minimum height; in a `col` card the chart grows to fill the card. */
		height?: number;
		/** Values are bytes: ticks land on round decimal units (1 GB = 10^9 bytes), like the byte formatters. */
		bytes?: boolean;
		/** Break the line and fill at a non-finite value, so a missing point shows as a gap (NET-205). Off: drawn across it. */
		gaps?: boolean;
	} = $props();

	const PAD = { l: 50, r: 12, t: 18, b: 28 };
	const FALLBACK_WIDTH = 640;
	const MIN_WIDTH = 280;
	const uid = $props.id();

	let measured = $state(0);
	let measuredH = $state(0);
	let hoverIndex = $state<number | null>(null);

	const w = $derived(Math.max(MIN_WIDTH, Math.round(measured) || FALLBACK_WIDTH));
	const h = $derived(Math.max(height, Math.round(measuredH)));
	const iw = $derived(w - PAD.l - PAD.r);
	const ih = $derived(h - PAD.t - PAD.b);
	const n = $derived(Math.max(0, ...series.map((s) => s.points.length)));
	const ts = $derived(series.find((s) => s.points.length === n)?.points.map((p) => p.t) ?? []);
	const peak = $derived(Math.max(0, ...series.flatMap((s) => s.points.map((p) => p.v)).filter(Number.isFinite)));
	const axis = $derived(bytes ? fitByteAxis(peak) : fitAxis(peak));
	// "Nov 4, 04:00 PM" needs more room than "21:00": space labels by the longest, at tipBox's 6.2 px a character
	const labelGap = $derived(Math.max(64, Math.max(0, ...ts.map((t) => formatX(t).length)) * 6.2 + 16));
	const every = $derived(labelStep(n, iw, labelGap));
	const slot = $derived(n > 1 ? iw / (n - 1) : iw);
	const highlight = $derived(
		highlightIndex !== undefined && highlightIndex >= 0 && highlightIndex < n ? highlightIndex : null,
	);
	const active = $derived(hoverIndex ?? highlight);

	const X = (i: number) => PAD.l + (n > 1 ? slot * i : iw / 2);
	const Y = (v: number) => PAD.t + ih * (1 - v / axis.top);

	// OLD CODE START — NET-205: one path per series, joined across missing points; `gaps` splits it
	// const paths = $derived(
	// 	series.map((s, k) => {
	// 		const pts: Point[] = s.points.map((p, i) => [X(i), Y(p.v)] as const).filter(([, y]) => Number.isFinite(y));
	// 		const line = monotonePath(pts);
	// 		const base = Y(0).toFixed(1);
	// 		const area = pts.length ? `${line}L${pts.at(-1)![0].toFixed(1)},${base}L${pts[0][0].toFixed(1)},${base}Z` : '';
	// 		return { k, colour: s.colour, line, area };
	// 	}),
	// );
	// OLD CODE END
	function segment(pts: Point[]) {
		const line = monotonePath(pts);
		const base = Y(0).toFixed(1);
		const area = pts.length ? `${line}L${pts.at(-1)![0].toFixed(1)},${base}L${pts[0][0].toFixed(1)},${base}Z` : '';
		return { line, area };
	}
	// a lone sample between two gaps: the line's round cap on a zero-length line draws a dot; no fill
	const dot = (pts: Point[]) => ({ line: `${monotonePath(pts)}h0`, area: '' });

	const paths = $derived(
		series.map((s, k) => {
			const all: Point[] = s.points.map((p, i) => [X(i), Y(p.v)] as const);
			// without gaps: one run of every finite point, exactly as before
			const runs = gaps ? finiteRuns(all) : [all.filter(([, y]) => Number.isFinite(y))];
			const parts = runs.map((run) => (gaps && run.length === 1 ? dot(run) : segment(run)));
			return { k, colour: s.colour, line: parts.map((p) => p.line).join(''), area: parts.map((p) => p.area).join('') };
		}),
	);

	function marker(i: number) {
		const dots = series
			.filter((s) => Number.isFinite(s.points[i]?.v))
			.map((s) => ({ colour: s.colour, x: X(i), y: Y(s.points[i].v) }));
		if (dots.length === 0) return null;
		const text = formatTip(i);
		return { dots, text, tip: tipBox(X(i), Math.min(...dots.map((d) => d.y)), text, w) };
	}
	const mark = $derived(active === null ? null : marker(active));

	function onpointermove(e: PointerEvent) {
		const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
		if (rect.width === 0) return;
		hoverIndex = nearestIndex((e.clientX - rect.left) * (w / rect.width), PAD.l, iw, n);
	}
</script>

{#if n > 0}
	<div
		class="chart"
		style:min-height="{height}px"
		{@attach observeWidth((width, ht) => {
			measured = width;
			measuredH = ht;
		})}
	>
		<svg
			viewBox="0 0 {w} {h}"
			width={w}
			height={h}
			role="img"
			aria-label={ariaLabel}
			{onpointermove}
			onpointerleave={() => (hoverIndex = null)}
		>
			<defs>
				{#each series as s, k (k)}
					<linearGradient id="{uid}-g{k}" class="g-{s.colour}" x1="0" y1="0" x2="0" y2="1">
						<stop offset="0" class="st-top" />
						<stop offset="1" class="st-bot" />
					</linearGradient>
				{/each}
			</defs>
			{#each axis.values as v, k (k)}
				<line class="gl" class:dash={v > 0} x1={PAD.l} x2={w - PAD.r} y1={Y(v).toFixed(1)} y2={Y(v).toFixed(1)} />
				<text class="ax" x={PAD.l - 10} y={(Y(v) + 4).toFixed(1)} text-anchor="end">{formatY(v)}</text>
			{/each}
			{#each ts as t, i (i)}
				{#if i % every === 0}
					<text class="ax" x={X(i).toFixed(1)} y={h - 6} text-anchor="middle">{formatX(t)}</text>
				{/if}
			{/each}
			{#if highlight !== null}
				{@const bw = Math.min(slot * 1.6, iw)}
				<rect class="band" x={(X(highlight) - bw / 2).toFixed(1)} y={PAD.t} width={bw.toFixed(1)} height={ih} rx="10" />
			{/if}
			<!-- series 1 is drawn last so it sits on top -->
			{#each [...paths].reverse() as { k, colour, line, area } (k)}
				<path d={area} fill="url(#{uid}-g{k})" />
				<path class="line ln-{colour}" d={line} />
			{/each}
			{#if hoverIndex !== null}
				<line class="guide" x1={X(hoverIndex).toFixed(1)} x2={X(hoverIndex).toFixed(1)} y1={PAD.t} y2={PAD.t + ih} />
			{/if}
			{#if mark}
				{#each mark.dots as d, k (k)}
					<circle class="dot dot-{d.colour}" cx={d.x.toFixed(1)} cy={d.y.toFixed(1)} r="4.5" />
				{/each}
				<rect class="tip-bg" x={mark.tip.x.toFixed(1)} y={mark.tip.y.toFixed(1)} width={mark.tip.width} height="24" rx="12" />
				<text class="tip-tx" x={(mark.tip.x + mark.tip.width / 2).toFixed(1)} y={(mark.tip.y + 16).toFixed(1)} text-anchor="middle"
					>{mark.text}</text
				>
			{/if}
		</svg>
	</div>
{/if}

<style>
	/* The svg is taken out of flow so the box's height comes from the card, not the svg:
	   in a `col` card the chart fills the space a taller neighbour gives the row. */
	.chart {
		position: relative;
		flex: 1 0 auto;
	}
	.chart svg {
		position: absolute;
		top: 0;
		left: 0;
	}
</style>
