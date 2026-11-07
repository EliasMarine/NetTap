<!--
  SavedCaptures.svelte: the capture files on disk (NET-188, Start.dc "Saved captures").
  The strip draws each indexed file from its first packet to its last, height by size, and makes
  no claim about the gaps between files. The table lists every file; "Search this file's time
  span" opens a normal window search, so other files from the same minutes are read too.
-->
<script lang="ts">
	import type { CaptureFile, CapturesResponse } from '$lib/api/packets';
	import { captureFileUrl } from '$lib/api/packets';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import { loadFailed } from '$lib/utils/load-failed';
	import { sortRows, type SortDir } from '$lib/utils/table-sort.svelte';
	import { formatBytes } from '$lib/api/logs';
	import { epochNs } from '$lib/utils/packet-query';
	import { clockTime, fileSpanWindow, plural, whenText } from './packets-view';

	interface Props {
		captures: CapturesResponse | null;
		error: string | null;
		onretry: () => void;
		/** The /packets link for a file's time span; null until the file is indexed. */
		spanHref: (file: CaptureFile) => string | null;
	}

	let { captures, error, onretry, spanHref }: Props = $props();

	const PAGE_SIZE = 25;
	let page = $state(1);
	let sortKey = $state('first');
	let sortDir = $state<SortDir>('desc');

	const files = $derived(captures?.files ?? []);

	const SORT: Record<string, (f: CaptureFile) => unknown> = {
		// A number: the file being written has no first packet yet, and its ISO time mustn't sort as text
		first: (f) => Number(f.first ?? Date.parse(f.modified) / 1000),
		// The file being written is the newest; a finished file not yet indexed has none (blanks sort last)
		last: (f) => (f.recent ? Infinity : f.last === null ? null : Number(f.last)),
		size: (f) => f.size_bytes,
		name: (f) => f.name,
		link: (f) => f.encapsulation ?? '',
		actions: (f) => f.state,
	};

	const sorted = $derived(sortRows(files, SORT[sortKey] ?? SORT.first, sortDir));
	const pageCount = $derived(Math.max(1, Math.ceil(sorted.length / PAGE_SIZE)));
	const current = $derived(Math.min(page, pageCount));
	const rows = $derived(sorted.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE));

	const columns: Column<CaptureFile>[] = [
		{ key: 'first', label: 'First packet', cell: firstCell },
		{ key: 'last', label: 'Last packet', cell: lastCell },
		{ key: 'size', label: 'Size', numeric: true, cell: sizeCell },
		{ key: 'name', label: 'File', cell: nameCell },
		{ key: 'link', label: 'Link type', cell: linkCell },
		{ key: 'actions', label: 'Actions', cell: actionsCell },
	];

	// The strip: indexed files only, positioned by packet time
	const strip = $derived.by(() => {
		const drawn = files
			.map((f) => ({ f, a: epochNs(f.first ?? ''), b: epochNs(f.last ?? '') }))
			.filter((x): x is { f: CaptureFile; a: bigint; b: bigint } => x.a !== null && x.b !== null);
		if (drawn.length === 0) return null;
		const min = drawn.reduce((m, x) => (x.a < m ? x.a : m), drawn[0].a);
		const max = drawn.reduce((m, x) => (x.b > m ? x.b : m), drawn[0].b);
		const span = Number(max - min) || 1;
		const biggest = Math.max(1, ...drawn.map((x) => x.f.size_bytes));
		return {
			min,
			max,
			bars: drawn.map(({ f, a, b }) => ({
				id: f.id,
				left: (Number(a - min) / span) * 100,
				width: Math.max(0.15, (Number(b - a) / span) * 100),
				height: Math.max(8, (f.size_bytes / biggest) * 100),
				recent: f.recent,
			})),
			undrawn: files.length - drawn.length,
		};
	});

	const stripLabel = $derived(
		strip
			? `${plural(strip.bars.length, 'indexed capture file')} from ${whenText(String(strip.min / 1_000_000_000n))} to ${whenText(String(strip.max / 1_000_000_000n))}, each drawn from its first packet to its last, height by size${strip.undrawn ? `; ${plural(strip.undrawn, 'file')} not drawn until indexed` : ''}.`
			: '',
	);

	const sub = $derived(
		captures
			? `${plural(captures.count, 'file')} · ${formatBytes(captures.bytes_total)} · a file's first and last packet come from reading it`
			: 'Capture files on disk',
	);

	function changeSort(key: string, dir: SortDir) {
		sortKey = key;
		sortDir = dir;
		page = 1;
	}
</script>

{#snippet firstCell(f: CaptureFile)}
	{#if f.first}<span class="num">{whenText(f.first)}</span>{:else}<span class="dim">Indexing…</span>{/if}
{/snippet}
{#snippet lastCell(f: CaptureFile)}
	{#if f.recent}
		<span class="chip is-ok">Being written</span>
	{:else if f.state === 'failed'}
		<span class="chip is-bad" title={f.error ?? undefined}>Can't be read</span>
	{:else if f.last}
		<span class="num">{clockTime(f.last, false)}</span>{#if f.cut_short}<span class="dim"> · cut short</span>{/if}
	{:else}
		<span class="dim">Indexing…</span>
	{/if}
{/snippet}
{#snippet sizeCell(f: CaptureFile)}{formatBytes(f.size_bytes)}{/snippet}
{#snippet nameCell(f: CaptureFile)}<span class="mono name">{f.name}</span>{/snippet}
{#snippet linkCell(f: CaptureFile)}{#if f.encapsulation}<span class="mono">{f.encapsulation}</span>{:else}<span class="dim">—</span>{/if}{/snippet}
{#snippet actionsCell(f: CaptureFile)}
	{@const href = spanHref(f)}
	<span class="acts">
		<!-- A file longer than one search's 30 minutes is searched from its start, and the link says so -->
		{#if href}<a {href} title="Other files from the same minutes are included">{fileSpanWindow(f)?.cut ? "Search this file's first 30 minutes" : "Search this file's time span"}</a>{/if}
		<a href={captureFileUrl(f.id)} download>Download</a>
	</span>
{/snippet}

<Card class="c-12" title="Saved captures" {sub}>
	{#snippet actions()}<a class="btn" href="/pcap">Open PCAP Search</a>{/snippet}
	{#if error && !captures}
		<CardState state="error" title={loadFailed('the capture files')} message={error} onaction={onretry} />
	{:else if !captures}
		<CardState state="loading" title="Loading the capture files" />
	{:else if files.length === 0}
		<CardState state="empty" icon="pcap" title="No capture files yet" message="Files appear here while capture is on. Turn it on from PCAP Search." href="/pcap" actionLabel="Open PCAP Search" />
	{:else}
		{#if error}<p class="notice is-warn" role="status">{loadFailed('the capture files', true)}</p>{/if}
		{#if strip}
			<div class="strip" role="img" aria-label={stripLabel}>
				{#each strip.bars as bar (bar.id)}
					<i class:recent={bar.recent} style:left="{bar.left}%" style:width="{bar.width}%" style:height="{bar.height}%"></i>
				{/each}
			</div>
			<div class="axis" aria-hidden="true"><span>{whenText(String(strip.min / 1_000_000_000n))}</span><span>{whenText(String(strip.max / 1_000_000_000n))}</span></div>
		{/if}
		<DataTable
			{columns}
			{rows}
			ariaLabel="Capture files"
			rowKey={(f) => f.id}
			initialSort={{ key: sortKey, dir: sortDir }}
			onsortchange={changeSort}
			pager={pageCount > 1 ? { page: current, pageCount, total: sorted.length, from: (current - 1) * PAGE_SIZE + 1, to: (current - 1) * PAGE_SIZE + rows.length, onpage: (p) => (page = p) } : undefined}
		/>
	{/if}
</Card>

<style>
	/* Layout glue: the strip is a row of bars on a time axis */
	.strip { position: relative; height: calc(var(--sp-8) * 2); margin-bottom: var(--sp-1); border-bottom: 1px solid var(--line); }
	.strip i { position: absolute; bottom: 0; background: var(--data-1); border-radius: var(--r-xs) var(--r-xs) 0 0; opacity: 0.8; }
	.strip i.recent { background: var(--ok); }
	.axis { display: flex; justify-content: space-between; font-size: var(--text-xs); color: var(--text-3); margin-bottom: var(--sp-4); }
	.acts { display: inline-flex; flex-wrap: wrap; gap: var(--sp-1) var(--sp-3); }
	.name { overflow-wrap: anywhere; }
	.dim { color: var(--text-3); }
</style>
