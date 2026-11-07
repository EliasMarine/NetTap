<!--
  SeverityGauge: 36 radial ticks over 270°, coloured by each severity's share
  (allocateTicks: largest remainder, every non-zero level gets one). A zero total draws 36
  neutral ticks and a 0. Buckets come from severityBuckets(); the caller shows the error state.
-->
<script lang="ts">
	import { allocateTicks, polar } from './geometry';
	import type { SeverityBucket } from '$lib/utils/severity';
	import { fitCount } from '$lib/utils/drilldown';

	let {
		buckets,
		total,
		centreLabel = 'alerts',
		ariaLabel,
	}: { buckets: SeverityBucket[]; total: number; centreLabel?: string; ariaLabel: string } = $props();

	const SIZE = 160;
	const TICKS = 36;
	const c = SIZE / 2;
	const R_OUT = c - 6;
	const R_IN = R_OUT - 15;
	const WORD = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low', info: 'Info' } as const;

	const counts = $derived(allocateTicks(buckets.map((b) => b.count), TICKS));
	// one entry per tick, clockwise from the lower left: the level's class, or neutral
	const ticks = $derived.by(() => {
		const levels = counts.flatMap((n, i) => Array<string>(n).fill(`sevs-${buckets[i].level}`));
		return Array.from({ length: TICKS }, (_, k) => {
			const deg = 135 + (270 * k) / (TICKS - 1);
			return { cls: levels[k] ?? 'track', a: polar(c, c, R_IN, deg), b: polar(c, c, R_OUT, deg) };
		});
	});
	const shown = $derived(Number.isFinite(total) && total > 0 ? total : 0);
	const pct = (n: number) => (shown > 0 ? `${Math.round((n / shown) * 100)}%` : '');
</script>

<div class="gauge-wrap">
	<div class="chart gauge-box">
		<svg viewBox="0 0 {SIZE} {SIZE}" width={SIZE} height={SIZE} role="img" aria-label={ariaLabel}>
			{#each ticks as t, k (k)}
				<line class="tick {t.cls}" x1={t.a[0].toFixed(1)} y1={t.a[1].toFixed(1)} x2={t.b[0].toFixed(1)} y2={t.b[1].toFixed(1)} />
			{/each}
			<!-- OLD CODE: {shown.toLocaleString('en-GB')} (NET-192: "214,000" ran into the tick ring; the aria-label keeps the exact figure) -->
			<text class="d-num" x={c} y={c + 6} text-anchor="middle">{fitCount(shown)}</text>
			<text class="d-lbl" x={c} y={c + 26} text-anchor="middle">{centreLabel}</text>
		</svg>
	</div>
	<!-- shortcut: swatch + word stand in for SeverityPill (built in parallel); swap it in when it lands -->
	<ul class="kv">
		{#each buckets as b (b.level)}
			<li>
				<span class="sw" style:--c="var(--sev-{b.level})"></span><span>{WORD[b.level]}</span><b
					>{b.count.toLocaleString('en-GB')}</b
				><span class="pct">{pct(b.count)}</span>
			</li>
		{/each}
	</ul>
</div>
