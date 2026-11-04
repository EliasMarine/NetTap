<!--
  Donut: 12px segments with gaps, the total in the centre and a .kv legend beside it.
  Pass raw items: the donut runs them through topSeries() itself, so no caller can show more
  than six colours. Past six, "Everything else" (__rest__) is a toggle that lists its members.
  With onselect, legend rows are buttons that pass back the original item (its key and source),
  members of "Everything else" included. Segments stay decorative: one tab stop per item.
  Nothing renders when every value is zero.
-->
<script lang="ts" generics="T">
	import { donutSegments, segmentDash } from './geometry';
	import { topSeries, REST_KEY, type SeriesItem } from '$lib/utils/series';

	let {
		items,
		total,
		centreLabel,
		formatValue,
		onselect,
		ariaLabel,
	}: {
		items: readonly SeriesItem<T>[];
		/** The centre number; the sum of the items when absent. */
		total?: number;
		centreLabel: string;
		formatValue: (v: number) => string;
		onselect?: (item: SeriesItem<T>) => void;
		ariaLabel: string;
	} = $props();

	const SIZE = 160;
	const STROKE = 12;
	const GAP = 4;
	const c = SIZE / 2;
	const r = c - STROKE / 2 - 2;
	const C = 2 * Math.PI * r;
	const uid = $props.id();

	let restOpen = $state(false);

	const series = $derived(topSeries(items));
	const sum = $derived(series.reduce((a, s) => a + s.value, 0));
	const segs = $derived(donutSegments(series.map((s) => s.value), C, GAP, STROKE));
	const pct = (v: number) => `${Math.round((v / sum) * 100)}%`;
</script>

{#snippet cells(item: SeriesItem<T>, colour?: number)}
	<span class="sw {colour ? `c-d${colour}` : ''}"></span><span>{item.label}</span><b>{formatValue(item.value)}</b><span
		class="pct">{pct(item.value)}</span
	>
{/snippet}

{#snippet row(item: SeriesItem<T>, colour?: number)}
	{#if onselect}
		<button type="button" class="kv-row" onclick={() => onselect(item)}>{@render cells(item, colour)}</button>
	{:else}
		{@render cells(item, colour)}
	{/if}
{/snippet}

{#if sum > 0}
	<div class="donut-wrap">
		<div class="chart donut-box">
			<svg viewBox="0 0 {SIZE} {SIZE}" width={SIZE} height={SIZE} role="img" aria-label={ariaLabel}>
				{#each segs as seg (seg.index)}
					{@const dash = segmentDash(seg, C)}
					<circle
						class="seg ln-{series[seg.index].colour}"
						style:stroke-linecap={seg.round ? undefined : 'butt'}
						cx={c}
						cy={c}
						r={r.toFixed(2)}
						stroke-dasharray={dash.dasharray}
						stroke-dashoffset={dash.dashoffset}
						transform="rotate(-90 {c} {c})"
					/>
				{/each}
				<text class="d-num" x={c} y={c + 6} text-anchor="middle">{formatValue(Number.isFinite(total) ? total! : sum)}</text>
				<text class="d-lbl" x={c} y={c + 26} text-anchor="middle">{centreLabel}</text>
			</svg>
		</div>
		<ul class="kv">
			{#each series as s, i (i)}
				<li>
					{#if s.key === REST_KEY}
						<button
							type="button"
							class="kv-row"
							aria-expanded={restOpen}
							aria-controls="{uid}-rest"
							onclick={() => (restOpen = !restOpen)}>{@render cells(s, s.colour)}</button
						>
						{#if restOpen}
							<ul class="kv kv-members" id="{uid}-rest">
								{#each s.members ?? [] as m, j (j)}
									<li>{@render row(m)}</li>
								{/each}
							</ul>
						{/if}
					{:else}
						{@render row(s, s.colour)}
					{/if}
				</li>
			{/each}
		</ul>
	</div>
{/if}

<style>
	/* Layout glue the system lacks: a legend row as a button that keeps the .kv columns */
	.kv-row {
		grid-column: 1 / -1;
		display: grid;
		grid-template-columns: subgrid;
		align-items: center;
		padding: 0;
		border: 0;
		border-radius: var(--r-sm);
		background: none;
		text-align: left;
		cursor: pointer;
	}
	.kv-row:hover {
		background: var(--row-hover);
	}
	.kv-members {
		grid-column: 1 / -1;
		padding-left: var(--sp-4);
		color: var(--text-2);
	}
</style>
