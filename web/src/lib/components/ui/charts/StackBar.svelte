<!--
  StackBar (KPI card feet): rounded segments, 6px minimum, and a legend. Items go through
  topSeries() here, so past six the last segment is "Everything else". The bar is role="img"
  and the caller's aria-label states the breakdown; the legend repeats it visually (aria-hidden).
  Zero items stay in the legend but draw no segment.
-->
<script lang="ts">
	import { topSeries, type SeriesItem } from '$lib/utils/series';

	let {
		items,
		formatValue,
		ariaLabel,
	}: { items: readonly SeriesItem[]; formatValue: (v: number) => string; ariaLabel: string } = $props();

	const series = $derived(topSeries(items));
</script>

{#if series.some((s) => s.value > 0)}
	<div class="stackbar" role="img" aria-label={ariaLabel}>
		<div class="sb-track">
			{#each series as s, i (i)}
				{#if s.value > 0}
					<span class="c-d{s.colour}" style:flex={s.value}></span>
				{/if}
			{/each}
		</div>
		<ul class="sb-legend" aria-hidden="true">
			{#each series as s, i (i)}
				<li><span class="sw c-d{s.colour}"></span>{s.label} <b>{formatValue(s.value)}</b></li>
			{/each}
		</ul>
	</div>
{/if}
