<!--
  Radar: scored factors (0–100) on 3–8 spokes, with grid rings at 25/50/75/100, the accent
  area, a dot per score and "Label value" at each spoke end. Used only where a page already
  has scored factors. Fewer than three axes render nothing. Redraws to its container's width.
-->
<script lang="ts">
	import { polar, type Point } from './geometry';
	import { observeWidth } from './resize';

	let { axes, ariaLabel }: { axes: { key: string; label: string; value: number }[]; ariaLabel: string } = $props();

	const FALLBACK_WIDTH = 420;
	const RINGS = [0.25, 0.5, 0.75, 1];
	let measured = $state(0);

	const shown = $derived(axes.slice(0, 8));
	const w = $derived(Math.round(measured) || FALLBACK_WIDTH);
	const h = $derived(Math.round(Math.min(Math.max(w * 0.74, 260), 360)));
	const cx = $derived(w / 2);
	const cy = $derived(h / 2 + 2);
	const R = $derived(Math.max(56, Math.min(w / 2 - 96, h / 2 - 30)));
	const score = (v: number) => (Number.isFinite(v) ? Math.max(0, Math.min(100, v)) : 0);
	const deg = (i: number) => -90 + (360 * i) / shown.length;
	const at = (i: number, f: number): Point => polar(cx, cy, R * f, deg(i));
	const poly = (f: (i: number) => number) =>
		shown.map((_, i) => at(i, f(i)).map((v) => v.toFixed(1)).join(',')).join(' ');
	const label = (i: number) => {
		const [x, y] = polar(cx, cy, R + 12, deg(i));
		const cos = Math.cos((deg(i) * Math.PI) / 180);
		const sin = Math.sin((deg(i) * Math.PI) / 180);
		return {
			x: x.toFixed(1),
			y: (y + (sin > 0.5 ? 12 : sin < -0.5 ? -4 : 4)).toFixed(1),
			anchor: cos > 0.25 ? 'start' : cos < -0.25 ? 'end' : 'middle',
		};
	};
</script>

{#if shown.length >= 3}
	<div class="chart" {@attach observeWidth((v) => (measured = v))}>
		<svg viewBox="0 0 {w} {h}" width={w} height={h} role="img" aria-label={ariaLabel}>
			{#each RINGS as f (f)}
				<polygon class="radar-grid" points={poly(() => f)} />
			{/each}
			{#each shown as a, i (i)}
				{@const [x, y] = at(i, 1)}
				<line class="radar-spoke" x1={cx} y1={cy} x2={x.toFixed(1)} y2={y.toFixed(1)} />
			{/each}
			<polygon class="radar-area" points={poly((i) => score(shown[i].value) / 100)} />
			{#each shown as a, i (i)}
				{@const [x, y] = at(i, score(a.value) / 100)}
				<circle class="radar-pt pt-1" cx={x.toFixed(1)} cy={y.toFixed(1)} r="4" />
			{/each}
			{#each shown as a, i (i)}
				{@const l = label(i)}
				<text class="radar-lbl" x={l.x} y={l.y} text-anchor={l.anchor}
					>{a.label} <tspan class="radar-v">{Math.round(score(a.value))}</tspan></text
				>
			{/each}
		</svg>
	</div>
{/if}
