<!--
  ResultKpis.svelte: Packets, Lasted, Data and TShark noticed (NET-188, Main.dc). Every figure is
  counted over the rows the search returned and says so; the Packets chip says "All of them" only
  for a complete read.
-->
<script lang="ts">
	import type { PacketSearchResult } from '$lib/api/packets';
	import type { PacketStats } from '$lib/utils/packet-stats';
	import Icon from '$lib/components/ui/Icon.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import { formatBytes } from '$lib/api/logs';
	import { clockTime, coverage, coverageNote, dayWords, durationParts, plural } from './packets-view';

	interface Props {
		result: PacketSearchResult;
		stats: PacketStats;
		/** The direction anchor and its name */
		device: string | null;
		deviceName: string | null;
	}

	let { result, stats, device, deviceName }: Props = $props();

	/** Above TShark's "chat": the SYN and FIN notes it adds to every connection stay out of the count. */
	const PROBLEMS = new Set(['error', 'warning', 'note']);

	const cover = $derived(coverage(result));
	const first = $derived(result.rows[0]?.t ?? null);
	const last = $derived(result.rows.at(-1)?.t ?? null);
	const lasted = $derived(stats.lastedSeconds === null ? null : durationParts(stats.lastedSeconds));
	const data = $derived(formatBytes(stats.bytes).split(' '));
	const who = $derived(deviceName ?? device ?? '');

	const directionText = $derived.by(() => {
		const d = stats.direction;
		if (!d) return `from ${plural(stats.senders.length, 'sender')}`;
		return `${d.out.toLocaleString('en-GB')} from ${who} · ${d.in.toLocaleString('en-GB')} to it${d.other ? ` · ${d.other.toLocaleString('en-GB')} other` : ''}`;
	});

	// Matched by the same rule as the packet counts (trimmed, any letter case), in packetStats' own loop
	const sentByDevice = $derived(stats.direction?.outBytes ?? null);

	const problems = $derived(stats.noticed.filter((n) => PROBLEMS.has(n.severity)));
	const flagged = $derived(new Set(problems.flatMap((n) => n.frames)).size);
</script>

{#snippet coverFoot()}
	<div class="foot">
		<span class={['chip', cover.complete ? 'is-ok' : 'is-caution']}><Icon name={cover.complete ? 'check' : 'warn'} />{cover.text}</span>
		<span class="note">{coverageNote(result)}</span>
	</div>
{/snippet}

<KpiCard class="c-3" label="Packets" icon="pcap" value={result.rows.length.toLocaleString('en-GB')} sub={directionText} foot={coverFoot} />
<KpiCard
	class="c-3"
	label="Lasted"
	icon="changelog"
	value={lasted?.value ?? '—'}
	unit={lasted?.unit}
	note={first && last ? `${clockTime(first, false)} to ${clockTime(last, false)} · ${dayWords(first)}` : undefined}
	sub={lasted ? 'First packet to last, in the packets shown' : 'Needs two packets or more'}
/>
<KpiCard
	class="c-3"
	label="Data"
	icon="bandwidth"
	value={data[0]}
	unit={data[1]}
	note={sentByDevice !== null ? `${formatBytes(sentByDevice)} sent by ${who} · ${formatBytes(stats.bytes - sentByDevice)} by others` : undefined}
	sub="Whole packets, headers included, in the packets shown"
/>
<KpiCard
	class="c-3"
	label="TShark noticed"
	icon="warn"
	value={flagged.toLocaleString('en-GB')}
	note={problems.length ? problems.slice(0, 2).map((n) => `${n.count.toLocaleString('en-GB')} ${n.message}`).join(' · ') : 'Nothing above a routine note'}
	sub="Packets TShark marked with a note, warning or error, in the packets shown"
/>

<style>
	.foot { display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-2); }
	.note { font-size: var(--text-xs); color: var(--text-3); }
</style>
