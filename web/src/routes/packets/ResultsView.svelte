<!--
  ResultsView.svelte: a search's answer (NET-188, Main.dc and Phone.dc). The question card, then
  either the search's state (working, failed, changed, busy, out of memory) or its packets:
  KPIs, the table with its drawer, the chart and who sent what. The page keys it by search.
-->
<script lang="ts">
	import type { CapturesResponse, PacketRow, PacketSearchResult } from '$lib/api/packets';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { packetStats, serverNames, type Noticed } from '$lib/utils/packet-stats';
	import { packetsUrl, type PacketUrlState } from '$lib/utils/packet-query';
	import DownloadForm from './DownloadForm.svelte';
	import PacketDrawer from './PacketDrawer.svelte';
	import PacketTable from './PacketTable.svelte';
	import ResultCharts from './ResultCharts.svelte';
	import ResultKpis from './ResultKpis.svelte';
	import ResultQuestion from './ResultQuestion.svelte';
	import { conversationFilter, plural, type SearchProblem } from './packets-view';

	interface Props {
		query: PacketUrlState;
		result: PacketSearchResult | null;
		problem: SearchProblem | null;
		/** Seconds since the running search started; null when none is running. */
		elapsed: number | null;
		captures: CapturesResponse | null;
		devices: ReadonlyMap<string, string>;
		onsearch: (query: PacketUrlState) => void;
		onrerun: () => void;
	}

	let { query, result, problem, elapsed, captures, devices, onsearch, onrerun }: Props = $props();

	// Kept by identity, not by object: a refresh brings new rows, and the same packet is found
	// again by its frame number and checksum, or the drawer closes because it's gone
	let picked = $state<Pick<PacketRow, 'n' | 'md5'> | null>(null);
	let activeKey = $state<Pick<Noticed, 'severity' | 'group' | 'message'> | null>(null);

	const rows = $derived(result?.rows ?? []);
	const stats = $derived(result ? packetStats(rows, query.device) : null);
	const sites = $derived(serverNames(rows));
	const deviceName = $derived(query.device ? (devices.get(query.device) ?? null) : null);
	const selected = $derived.by(() => {
		const p = picked;
		return p ? (rows.find((r) => r.n === p.n && r.md5 === p.md5) ?? null) : null;
	});
	const active = $derived.by(() => {
		const k = activeKey;
		return k ? (stats?.noticed.find((x) => x.severity === k.severity && x.group === k.group && x.message === k.message) ?? null) : null;
	});
	const activeFrames = $derived(active ? new Set(active.frames) : null);
	const shown = $derived(activeFrames ? rows.filter((r) => activeFrames.has(r.n)) : rows);
	const position = $derived(selected ? rows.indexOf(selected) + 1 : 0);
	// Same window, so the same files: a stream number means nothing outside the read that gave it
	const conversation = $derived(selected ? conversationFilter(selected) : null);
	const conversationHref = $derived(conversation ? packetsUrl({ ...query, filter: conversation, limit: 1000, conn: null }) : null);

	const problemTitle = $derived.by(() => {
		if (!problem) return '';
		if (problem.kind === 'changed') return 'The capture files behind this search have changed';
		if (problem.kind === 'busy') return /index/i.test(problem.message) ? 'NetTap is still indexing capture files' : 'The packet reader is busy';
		if (problem.kind === 'memory') return 'The search ran out of memory';
		if (problem.kind === 'refused') return "TShark couldn't run this search";
		return "Couldn't search the saved captures";
	});
	const problemHint = $derived(
		problem?.kind === 'memory'
			? ' Try a shorter stretch of time or a narrower filter.'
			: problem?.kind === 'refused'
				? ' Edit the filter above and search again.'
				: '',
	);

	/** Says exactly what was searched, so a miss never reads as "no traffic" to a site. */
	const emptyMessage = $derived.by(() => {
		if (!result) return '';
		if (result.message) return result.message;
		if (result.termination === 'deadline') return 'The search stopped at its time limit before it found a match; packets later in the window may still match.';
		if (!result.complete) return 'Some capture files couldn’t be read; see the list above.';
		const site = result.filter.includes('extensions_server_name == "') ? ' A site name has to match exactly: www.example.com is a different name from example.com.' : '';
		return `${result.filter ? `No packet in this window matches ${result.filter}.` : 'No packet was saved in this window.'}${site} Try a longer stretch of time or a wider filter.`;
	});

	const emptyTitle = $derived(
		result?.termination === 'deadline' ? 'No match found before the search stopped' : result?.complete ? 'No packets match' : 'No packets found in the files read',
	);
</script>

<div class="grid">
	<ResultQuestion {query} {result} {captures} {deviceName} {onsearch} />

	{#if problem}
		<Card class="c-12" title="Packets" sub="The search didn't finish">
			<CardState
				state="error"
				title={problemTitle}
				message={`${problem.message}${problemHint}`}
				actionLabel={problem.kind === 'changed' ? 'Run the search again' : 'Try again'}
				onaction={problem.kind === 'refused' ? undefined : onrerun}
			/>
		</Card>
	{:else if !result}
		<Card class="c-12" title="Packets" sub="Reading the saved captures">
			<CardState state="loading" title="Searching the saved captures" />
			<p class="working" role="status">
				Searching… {elapsed !== null ? `${elapsed} s so far. ` : ''}A search reads every packet in the window and can take up to about 45 seconds.
			</p>
		</Card>
	{:else if rows.length === 0}
		<Card class="c-12" title="Packets" sub="No packets in the files read">
			<CardState
				state="empty"
				icon="pcap"
				title={emptyTitle}
				message={emptyMessage}
			/>
		</Card>
	{:else if stats}
		<ResultKpis {result} {stats} device={query.device} {deviceName} />
	{/if}
</div>

{#if result && stats && rows.length}
	<div class="grid alert-layout" class:no-drawer={!selected}>
		<Card
			class="c-8 alert-list-card"
			title="Packets"
			sub={`${plural(rows.length, 'packet')} · in time order · select one to see inside it`}
		>
			{#snippet actions()}
				<div class="head-actions">
					<DownloadForm manifest={result.manifest} />
					<a class="btn" href="/pcap"><Icon name="pcap" />Open PCAP Search</a>
				</div>
			{/snippet}
			{#if active}
				<p class="notice" role="status">
					Showing the {plural(shown.length, 'packet')} TShark marked “{active.message}”, of the {rows.length.toLocaleString('en-GB')} shown.
					<button class="btn" type="button" onclick={() => (activeKey = null)}>Show all</button>
				</p>
			{/if}
			<PacketTable rows={shown} firstT={rows[0].t} {devices} {sites} selected={selected?.n ?? null} onopen={(r) => (picked = { n: r.n, md5: r.md5 })} />
		</Card>
		{#if selected}
			{@const open = selected}
			{#key open.n}
				<PacketDrawer
					manifest={result.manifest}
					row={open}
					{position}
					total={rows.length}
					firstT={rows[0].t}
					{devices}
					{sites}
					{conversationHref}
					onclose={() => (picked = null)}
					{onrerun}
				/>
			{/key}
		{/if}
	</div>

	<div class="grid">
		<ResultCharts {stats} {devices} {sites} {active} onfilter={(n) => (activeKey = n && { severity: n.severity, group: n.group, message: n.message })} />
	</div>
{/if}

<style>
	/* Layout glue */
	.working { font-size: var(--text-sm); color: var(--text-2); margin: 0; }
	.notice { align-items: center; flex-wrap: wrap; margin-bottom: var(--sp-3); }
</style>
