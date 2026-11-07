<!--
  ResultCharts.svelte: "The conversation over time" and "Who sent what" with TShark's notes
  (NET-188, Main.dc). All of it is worked out from the rows shown. "Show them" filters the rows
  already on screen; it never searches again.
-->
<script lang="ts">
	import BarList, { type BarItem } from '$lib/components/ui/BarList.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import AreaChart from '$lib/components/ui/charts/AreaChart.svelte';
	import { ipHref } from '$lib/stores/lan';
	import { formatBytes } from '$lib/api/logs';
	import { epochNs, nsEpoch } from '$lib/utils/packet-query';
	import type { Noticed, PacketStats } from '$lib/utils/packet-stats';
	import { addressName, clockTime, durationParts, expertWord, isIp, plural } from './packets-view';

	interface Props {
		stats: PacketStats;
		devices: ReadonlyMap<string, string>;
		sites: ReadonlyMap<string, string>;
		active: Noticed | null;
		onfilter: (n: Noticed | null) => void;
	}

	let { stats, devices, sites, active, onfilter }: Props = $props();

	const TOP_SENDERS = 8;
	const ROUTINE = new Set(['chat', 'comment']);

	const timeline = $derived(stats.timeline);
	const step = $derived.by(() => {
		const a = epochNs(timeline[0]?.t ?? '');
		const b = epochNs(timeline[1]?.t ?? '');
		if (a === null || b === null) return null;
		const d = durationParts(nsEpoch(b - a));
		return `${d.value} ${d.unit}`;
	});
	const busiest = $derived(timeline.reduce((best, b, i) => (b.packets > (timeline[best]?.packets ?? -1) ? i : best), 0));
	const span = $derived(timeline.length ? `${clockTime(timeline[0].t, false)} to ${clockTime(timeline.at(-1)!.t, false)}` : '');

	const senders = $derived(
		stats.senders.slice(0, TOP_SENDERS).map(
			(s): BarItem => ({
				key: s.address || '(none)',
				label: s.address ? addressName(s.address, devices, sites) : 'No address',
				value: s.bytes,
				display: formatBytes(s.bytes),
				detail: plural(s.packets, 'packet'),
				href: isIp(s.address) ? $ipHref(s.address) : undefined,
			}),
		),
	);

	const problems = $derived(stats.noticed.filter((n) => !ROUTINE.has(n.severity)));
	const routine = $derived(stats.noticed.filter((n) => ROUTINE.has(n.severity)));
</script>

{#snippet notes(items: Noticed[])}
	<ul class="noticed">
		{#each items as n (n.message + n.severity)}
			<li>
				<div class="line">
					<span class="tag">{expertWord(n.severity)}</span>
					<b>{n.message}</b>
					<button class="btn" type="button" aria-pressed={active === n} onclick={() => onfilter(active === n ? null : n)}
						>{active === n ? 'Show all' : `Show ${n.count === 1 ? 'it' : `the ${n.count.toLocaleString('en-GB')}`}`}</button
					>
				</div>
				<span class="dim">{plural(n.count, 'packet')}{n.group ? ` · ${n.group}` : ''}</span>
			</li>
		{/each}
	</ul>
{/snippet}

<Card class="c-8" hero title="The conversation over time" sub={step ? `Packets per ${step} · ${span} · the ${plural(stats.packets, 'packet')} shown` : `The ${plural(stats.packets, 'packet')} shown`}>
	{#if timeline.length < 2}
		<CardState state="empty" title="Too few packets for a chart" message="The chart needs packets at two different times or more." />
	{:else}
		<AreaChart
			series={[{ key: 'packets', label: 'Packets', colour: 1, points: timeline.map((b) => ({ t: b.t, v: b.packets })) }]}
			formatX={(t) => clockTime(String(t), false)}
			formatY={(v) => v.toLocaleString('en-GB')}
			formatTip={(i) => `${clockTime(timeline[i].t)} · ${plural(timeline[i].packets, 'packet')} · ${formatBytes(timeline[i].bytes)}`}
			highlightIndex={busiest}
			ariaLabel={`Busiest at ${clockTime(timeline[busiest].t)}, with ${plural(timeline[busiest].packets, 'packet')} in ${step}`}
		/>
	{/if}
</Card>

<Card class="c-4" title="Who sent what" sub={`Bytes and packets · the ${plural(stats.packets, 'packet')} shown${stats.senders.length > TOP_SENDERS ? ` · top ${TOP_SENDERS} of ${stats.senders.length.toLocaleString('en-GB')} senders` : ''}`}>
	{#if senders.length}<BarList items={senders} />{/if}
	<h3 class="sub-title">TShark noticed</h3>
	{#if stats.noticed.length === 0}
		<p class="dim">TShark added no notes to these packets.</p>
	{:else}
		{#if problems.length}{@render notes(problems)}{:else}<p class="dim">No notes, warnings or errors.</p>{/if}
		{#if routine.length}
			<details>
				<summary>Routine notes ({routine.length.toLocaleString('en-GB')})</summary>
				{@render notes(routine)}
			</details>
		{/if}
	{/if}
</Card>

<style>
	/* Layout glue */
	.sub-title { font: 500 var(--text-base)/1.3 var(--font-display); margin: var(--sp-5) 0 var(--sp-2); }
	.noticed { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--sp-3); }
	.noticed li { display: flex; flex-direction: column; gap: 2px; font-size: var(--text-sm); }
	.line { display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-2); }
	.line b { flex: 1 1 12em; overflow-wrap: anywhere; font-weight: 600; }
	.dim { color: var(--text-3); font-size: var(--text-xs); }
	details { margin-top: var(--sp-3); }
	summary { cursor: pointer; font-size: var(--text-sm); color: var(--text-2); }
	.btn[aria-pressed='true'] { border-color: var(--accent); }
</style>
