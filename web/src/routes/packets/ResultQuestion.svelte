<!--
  ResultQuestion.svelte: "What you're looking at" (NET-188, Main.dc). The search as the URL holds
  it, the files the daemon actually read (with the ones still being written and the ones it
  couldn't read), and for a connection from Connections its segment, with Previous and Next.
  "Edit filter" changes the filter or the count over the same window.
-->
<script lang="ts">
	import type { CapturesResponse, PacketRowLimit, PacketSearchResult } from '$lib/api/packets';
	import Card from '$lib/components/ui/Card.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import { formatBytes } from '$lib/api/logs';
	import { connectionSegments, packetsUrl, type PacketUrlState } from '$lib/utils/packet-query';
	import FilterEditor from './FilterEditor.svelte';
	import { clockTime, dayWords, LIMIT_OPTIONS, plural, whenText } from './packets-view';

	interface Props {
		query: PacketUrlState;
		result: PacketSearchResult | null;
		captures: CapturesResponse | null;
		deviceName: string | null;
		onsearch: (query: PacketUrlState) => void;
	}

	let { query, result, captures, deviceName, onsearch }: Props = $props();

	const FILES_LISTED = 3;

	let editing = $state(false);
	let draft = $state('');
	let draftLimit = $state('250');

	const segments = $derived.by(() => {
		if (!query.conn) return null;
		try {
			return connectionSegments(query.conn.start, query.conn.duration);
		} catch {
			return null;
		}
	});
	const segment = $derived(segments && query.conn ? (segments[query.conn.segment] ?? null) : null);
	const segmentHref = (index: number): string | null => {
		const seg = segments?.[index];
		return seg && query.conn ? packetsUrl({ ...query, from: seg.from, to: seg.to, conn: { ...query.conn, segment: index } }) : null;
	};

	const shownWindow = $derived(result?.window.effective ?? { from: query.from, to: query.to });
	const endMoved = $derived(!!result && result.window.effective.to !== result.window.requested.to);
	const byId = $derived(new Map((captures?.files ?? []).map((f) => [f.id, f])));
	const writing = $derived(new Set(result?.manifest.files.filter((f) => f.recent).map((f) => f.id) ?? []));
	const readBytes = $derived(result?.files.reduce((n, f) => n + f.size_bytes, 0) ?? 0);

	function startEdit() {
		draft = query.filter;
		draftLimit = String(query.limit);
		editing = true;
	}

	function run() {
		const filter = draft.trim();
		// A changed filter no longer describes the connection, so its segment controls go
		onsearch({ ...query, filter, limit: Number(draftLimit) as PacketRowLimit, conn: filter === query.filter ? query.conn : null });
		editing = false;
	}
</script>

<Card class="c-12" title="What you're looking at" sub="Change the filter or the number of packets and search again · the window stays the same">
	{#snippet actions()}<a class="btn" href="/packets"><Icon name="search" />New search</a>{/snippet}

	{#if query.conn}
		<div class="conn">
			<span><Icon name="connections" />Opened from a connection on Connections · <a href="/connections">Back to Connections</a></span>
			{#if segment && segments}
				<span class="seg">
					{segments.length > 1 ? `Segment ${segment.index + 1} of ${segments.length}: ` : ''}{segment.label}
				</span>
				{#if !query.conn.exact}
					<span class="field-help">The record had no ports, so this is all traffic between these two addresses (no exact connection).</span>
				{/if}
				{#if segments.length > 1}
					<span class="seg-nav">
						{#if segmentHref(segment.index - 1)}<a class="btn" href={segmentHref(segment.index - 1)}><Icon name="back" />Previous segment</a>{/if}
						{#if segmentHref(segment.index + 1)}<a class="btn" href={segmentHref(segment.index + 1)}>Next segment<Icon name="back" class="chev" /></a>{/if}
					</span>
				{/if}
			{/if}
		</div>
	{/if}

	<p class="sentence">
		{query.filter ? 'Packets matching the filter below' : 'Every packet'} from <b>{clockTime(shownWindow.from)}</b> to <b>{clockTime(shownWindow.to)}</b>
		{dayWords(shownWindow.from)}, up to {query.limit.toLocaleString('en-GB')}.
		{#if query.device}In and out are counted from {deviceName ?? query.device}{deviceName ? ` (${query.device})` : ''}.{/if}
	</p>
	{#if endMoved && result}<p class="field-help">The end was moved to the time of the search, {clockTime(result.window.effective.to)}: nothing after it was saved yet.</p>{/if}

	<div class="line">
		<span class="k">Filter</span>
		{#if query.filter}<code class="filter">{query.filter}</code>{:else}<span class="dim">none: every packet</span>{/if}
		{#if !editing}<button class="btn" type="button" onclick={startEdit}>Edit filter</button>{/if}
	</div>

	{#if editing}
		<div class="edit">
			<FilterEditor bind:value={draft} onsubmit={run} />
			<div class="edit-row">
				<Pills options={LIMIT_OPTIONS} bind:value={draftLimit} ariaLabel="Packets to show" />
				<button class="btn" type="button" onclick={() => (editing = false)}>Cancel</button>
				<button class="btn primary" type="button" onclick={run}><Icon name="search" />Find packets</button>
			</div>
		</div>
	{/if}

	{#if result}
		<div class="line">
			<span class="k">Read</span>
			<span>
				<b>{plural(result.files.length, 'capture file')}</b>, {formatBytes(readBytes)}, in {result.seconds.toLocaleString('en-GB', { maximumFractionDigits: 1 })} s:
				{#each result.files.slice(0, FILES_LISTED) as f, i (f.id)}
					{@const known = byId.get(f.id)}
					{i > 0 ? '; ' : ''}<span class="mono">{known?.name ?? f.id}</span>
					({f.first ? `first packet ${whenText(f.first)}` : 'not indexed yet'}{f.last && !writing.has(f.id) ? `, last ${clockTime(f.last, false)}` : ''}{writing.has(f.id) ? ', still being written' : ''}{f.cut_short ? ', cut short' : ''})
				{/each}
				{#if result.files.length > FILES_LISTED}and {plural(result.files.length - FILES_LISTED, 'more')}{/if}
			</span>
		</div>
		{#if result.provisional}
			<p class="notice is-warn"><Icon name="warn" />A capture file in this window was written to in the last 2 minutes, so its newest packets may not all be saved yet.</p>
		{/if}
		{#if result.skipped_files.length}
			<div class="notice is-warn" role="status">
				<Icon name="warn" />
				<div>
					{plural(result.skipped_files.length, 'capture file')} couldn't be read, so these packets may not be all of them:
					<ul>
						{#each result.skipped_files as f (f.id)}
							<li><span class="mono">{byId.get(f.id)?.name ?? f.id}</span>: {f.error ?? 'no reason given'}</li>
						{/each}
					</ul>
				</div>
			</div>
		{/if}
		{#if result.message}<p class="notice is-warn"><Icon name="warn" />{result.message}</p>{/if}
	{/if}
</Card>

<style>
	/* Layout glue */
	.conn { display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-2) var(--sp-4); margin-bottom: var(--sp-3); font-size: var(--text-sm); color: var(--text-2); }
	.conn > span:first-child { display: inline-flex; align-items: center; gap: var(--sp-1); }
	.seg { font-weight: 600; color: var(--text-1); }
	.seg-nav { display: inline-flex; gap: var(--sp-2); }
	.sentence { font-size: var(--text-base); color: var(--text-1); margin: 0 0 var(--sp-3); }
	.line { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--sp-2) var(--sp-3); font-size: var(--text-sm); color: var(--text-2); margin-top: var(--sp-2); }
	.k { font-weight: 600; color: var(--text-3); min-width: calc(var(--sp-8) * 1.5); }
	.filter { font-family: var(--font-mono); color: var(--text-1); background: var(--surface-2); border: 1px solid var(--line); border-radius: var(--r-sm); padding: 2px var(--sp-2); overflow-wrap: anywhere; }
	.dim { color: var(--text-3); }
	.edit { display: flex; flex-direction: column; gap: var(--sp-3); margin-top: var(--sp-3); padding: var(--sp-4); border: 1px solid var(--line); border-radius: var(--r-md); }
	.edit-row { display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-2); }
	.notice { margin-top: var(--sp-3); }
	.notice ul { margin: var(--sp-1) 0 0; padding-left: var(--sp-5); }
</style>
