<!--
  Sparkline (KPI card feet): an accent line, an optional accent band over a window of
  indices, and ring dots at both ends of the band (or of the line when there is no band).
  Decorative (aria-hidden) unless given an aria-label. Redraws to its container's width
  unless a width is given.
-->
<script lang="ts">
	import { monotonePath, type Point } from './geometry';
	import { observeWidth } from './resize';

	let {
		values,
		band,
		ariaLabel,
		width,
		height = 52,
	}: { values: number[]; band?: [number, number]; ariaLabel?: string; width?: number; height?: number } = $props();

	const FALLBACK_WIDTH = 240;
	const uid = $props.id();
	let measured = $state(0);

	const w = $derived(width ?? (Math.round(measured) || FALLBACK_WIDTH));
	const n = $derived(values.length);
	const max = $derived(Math.max(0, ...values.filter(Number.isFinite)) * 1.2 || 1);
	const X = (i: number) => (n > 1 ? 4 + ((w - 8) * i) / (n - 1) : w / 2);
	const Y = (v: number) => height - 6 - ((height - 14) * v) / max;
	const pts = $derived(values.map((v, i): Point => [X(i), Y(v)]).filter(([, y]) => Number.isFinite(y)));
	const win = $derived.by(() => {
		if (!band) return null;
		const [a, b] = band.map((i) => Math.max(0, Math.min(n - 1, Math.round(i))));
		return a < b ? [a, b] : null;
	});
	const ends = $derived(
		[...new Set(win ?? [0, n - 1])].filter((i) => Number.isFinite(values[i])).map((i): Point => [X(i), Y(values[i])]),
	);
</script>

{#if n > 0}
	<div class="spark" {@attach observeWidth((v) => (measured = v))}>
		<svg
			viewBox="0 0 {w} {height}"
			width={w}
			{height}
			role={ariaLabel ? 'img' : undefined}
			aria-label={ariaLabel}
			aria-hidden={ariaLabel ? undefined : 'true'}
		>
			{#if win}
				<defs>
					<linearGradient id="{uid}-band" class="g-band" x1="0" y1="0" x2="0" y2="1">
						<stop offset="0" class="st-top" />
						<stop offset="1" class="st-bot" />
					</linearGradient>
				</defs>
				<rect x={X(win[0]).toFixed(1)} y="0" width={(X(win[1]) - X(win[0])).toFixed(1)} {height} rx="8" fill="url(#{uid}-band)" />
			{/if}
			<line class="gl dash" x1="0" x2={w} y1={height - 6} y2={height - 6} />
			<path class="line ln-spark" d={monotonePath(pts)} />
			{#each ends as [x, y], k (k)}
				<circle class="ring-dot" cx={x.toFixed(1)} cy={y.toFixed(1)} r="4" />
			{/each}
		</svg>
	</div>
{/if}

<style>
	/* Layout glue: the measured box spans the KPI foot */
	.spark {
		width: 100%;
		min-width: 0;
	}
</style>
