<!--
  AreaChart: one or two monotone lines over gradient fills (design system Charts preview).
  The headline point gets a band, ringed dots and the pill tooltip; hovering moves the
  tooltip with a dashed guide, and leaving restores the headline. Hover is a mouse extra:
  the chart is role="img" and its aria-label carries the headline. Empty series render nothing.
  With `onpick` (NET-249) the chart is a focusable group: a click or tap picks a point, a drag
  picks a range, and the arrow keys (Shift for a range) and Enter do the same from the keyboard.
-->
<script lang="ts" module>
	export interface AreaSeries {
		key: string;
		label: string;
		/** The `--data-N` token: 1 download, 2 upload, 3 local (NET-226). */
		colour: 1 | 2 | 3;
		points: { t: number | string; v: number }[];
	}
</script>

<script lang="ts">
	import { untrack } from 'svelte';
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
		onpick,
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
		/** Points `from..to` (inclusive indices into `series`) were picked by click, drag or keyboard (NET-249). Without it the chart is a picture. */
		onpick?: (from: number, to: number) => void;
	} = $props();

	const PAD = { l: 50, r: 12, t: 18, b: 28 };
	const FALLBACK_WIDTH = 640;
	const MIN_WIDTH = 280;
	const uid = $props.id();

	let measured = $state(0);
	let measuredH = $state(0);
	let hoverIndex = $state<number | null>(null);
	/** NET-249 picking: the keyboard's point and range anchor, and a pointer drag in progress. */
	let focusIndex = $state<number | null>(null);
	let anchor = $state<number | null>(null);
	/** `id`: the pointer that started it; a second finger or pen never moves or ends it */
	let drag = $state<{ start: number; end: number; x0: number; id: number } | null>(null);
	/** A drag shorter than this (px) is a click, so a shaky tap still picks one point. */
	const CLICK_SLOP = 4;
	const KEY_HELP = 'Use the left and right arrow keys to choose a point, Shift with an arrow key to choose a range, and Enter to open it.';

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
	// OLD CODE: const active = $derived(hoverIndex ?? highlight); (NET-249: the keyboard's point shows its tooltip too)
	const active = $derived(hoverIndex ?? focusIndex ?? highlight);
	/** The range being picked (a drag, or Shift+arrows from an anchor); null for none or a single point. */
	const picking = $derived.by(() => {
		const [a, b] = drag ? [drag.start, drag.end] : anchor !== null && focusIndex !== null ? [anchor, focusIndex] : [null, null];
		return a === null || b === null || a === b ? null : { lo: Math.min(a, b), hi: Math.max(a, b) };
	});
	const liveText = $derived(
		picking ? `from ${formatTip(picking.lo)} to ${formatTip(picking.hi)}` : focusIndex !== null ? formatTip(focusIndex) : '',
	);

	// A pick uses indices into the series on screen: new data (a refresh, another range) cancels a
	// drag or a keyboard range, and keeps the keyboard's point inside the new series.
	$effect.pre(() => {
		void series;
		untrack(() => {
			drag = null;
			anchor = null;
			if (focusIndex !== null) focusIndex = n > 0 ? Math.min(focusIndex, n - 1) : null;
		});
	});

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

	// OLD CODE START — NET-249: the index maths is shared with picking
	// function onpointermove(e: PointerEvent) {
	// 	const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
	// 	if (rect.width === 0) return;
	// 	hoverIndex = nearestIndex((e.clientX - rect.left) * (w / rect.width), PAD.l, iw, n);
	// }
	// OLD CODE END
	function indexAt(e: PointerEvent): number | null {
		const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
		return rect.width === 0 ? null : nearestIndex((e.clientX - rect.left) * (w / rect.width), PAD.l, iw, n);
	}

	function onpointermove(e: PointerEvent) {
		const i = indexAt(e);
		if (!e.isPrimary || i === null) return;
		hoverIndex = i;
		if (drag?.id === e.pointerId) drag = { ...drag, end: i };
	}

	function onpointerdown(e: PointerEvent) {
		const i = indexAt(e);
		if (!onpick || !e.isPrimary || e.button !== 0 || i === null) return;
		(e.currentTarget as SVGSVGElement).setPointerCapture?.(e.pointerId);
		drag = { start: i, end: i, x0: e.clientX, id: e.pointerId };
	}

	function onpointerup(e: PointerEvent) {
		if (!drag || !onpick || drag.id !== e.pointerId) return;
		const { start, x0 } = drag;
		const end = indexAt(e) ?? drag.end;
		drag = null;
		if (Math.abs(e.clientX - x0) < CLICK_SLOP || start === end) onpick(start, start);
		else onpick(Math.min(start, end), Math.max(start, end));
	}

	/** Escape, or focus leaving the chart: no point, range or drag left behind (the tooltip goes back to the headline) */
	function clearPick() {
		drag = null;
		anchor = null;
		focusIndex = null;
	}

	const MOVES: Record<string, (i: number) => number> = {
		ArrowLeft: (i) => i - 1,
		ArrowRight: (i) => i + 1,
		Home: () => 0,
		End: () => n - 1,
	};

	function onkeydown(e: KeyboardEvent) {
		if (!onpick || n === 0) return;
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			if (e.repeat) return; // a held key opens one moment, not one per repeat
			const point = focusIndex ?? highlight;
			if (point === null) return;
			if (picking) onpick(picking.lo, picking.hi);
			else onpick(point, point);
			return;
		}
		if (e.key === 'Escape') return clearPick();
		const move = MOVES[e.key];
		if (!move) return;
		e.preventDefault();
		// from nothing chosen, the first step lands next to the headline, or on the first point
		const current = focusIndex ?? highlight ?? -1;
		anchor = e.shiftKey ? (anchor ?? Math.max(0, current)) : null;
		focusIndex = Math.max(0, Math.min(n - 1, move(current)));
	}
</script>

{#if n > 0}
	<!-- OLD CODE START — NET-249: a picture only; with onpick the box is a focusable group
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
	OLD CODE END -->
	<!-- a picked chart is one keyboard stop that moves between its points, as DotMap's hotspots are buttons -->
	<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
	<div
		class="chart"
		class:pickable={!!onpick}
		style:min-height="{height}px"
		role={onpick ? 'group' : undefined}
		tabindex={onpick ? 0 : undefined}
		aria-label={onpick ? `${ariaLabel.replace(/\.?$/, '.')} ${KEY_HELP}` : undefined}
		onkeydown={onpick ? onkeydown : undefined}
		onblur={onpick ? clearPick : undefined}
		{@attach observeWidth((width, ht) => {
			measured = width;
			measuredH = ht;
		})}
	>
		<svg
			viewBox="0 0 {w} {h}"
			width={w}
			height={h}
			role={onpick ? undefined : 'img'}
			aria-label={onpick ? undefined : ariaLabel}
			aria-hidden={onpick ? 'true' : undefined}
			{onpointermove}
			{onpointerdown}
			{onpointerup}
			onpointercancel={(e) => {
				if (drag?.id === e.pointerId) drag = null;
			}}
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
			{#if picking}
				{@const x0 = Math.max(PAD.l, X(picking.lo) - slot / 2)}
				<rect class="band pick" x={x0.toFixed(1)} y={PAD.t} width={(Math.min(PAD.l + iw, X(picking.hi) + slot / 2) - x0).toFixed(1)} height={ih} rx="10" />
			{/if}
			<!-- series 1 is drawn last so it sits on top -->
			{#each [...paths].reverse() as { k, colour, line, area } (k)}
				<path d={area} fill="url(#{uid}-g{k})" />
				<path class="line ln-{colour}" d={line} />
			{/each}
			<!-- OLD CODE: {#if hoverIndex !== null} (NET-249: the keyboard's point gets the guide too) -->
			{#if hoverIndex !== null || focusIndex !== null}
				{@const gi = (hoverIndex ?? focusIndex)!}
				<line class="guide" x1={X(gi).toFixed(1)} x2={X(gi).toFixed(1)} y1={PAD.t} y2={PAD.t + ih} />
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
		{#if onpick}<span class="sr-only" aria-live="polite">{liveText}</span>{/if}
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
	/* NET-249: a picked chart; a vertical swipe still scrolls the page, a sideways drag picks a range */
	.chart.pickable svg { cursor: pointer; touch-action: pan-y; user-select: none; }
	.chart.pickable:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; border-radius: var(--r-md); }
	/* NET-226: a third series; system.css colours the gradient and dot of 1 and 2 only */
	.chart :global(.g-3 stop) { stop-color: var(--data-3); }
	.chart :global(.dot-3) { fill: var(--data-3); }
</style>
