<!--
  AlertEvidence.svelte (NET-355): the evidence behind an alert, near the top of its drawer.
  What Suricata saw and recorded comes from the alert itself; the Zeek records sharing its
  community ID load on open (one log search); the packets near the alert time load on a click
  (one packet search), so browsing alerts never holds the packet reader. Each part says only what
  its data shows. Rules and their reasons: alert-evidence.ts.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import type { Alert } from '$api/alerts';
	import { downloadPackets, getCaptures, searchPackets, type PacketRow, type PacketSearchResult } from '$api/packets';
	import Icon from '$lib/components/ui/Icon.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import IPAddress from '$components/IPAddress.svelte';
	import { getField } from '$lib/utils/tshark-filter';
	import { packetsUrl } from '$lib/utils/packet-query';
	import { clockTime, coverage, coverageNote, dstPortOf, field, planFiles, searchProblem, srcPortOf, type SearchProblem } from '../packets/packets-view';
	import { beforeWindow, emptyResultText, packetPreview, pcapName, recordedFields, trafficOf, zeekQuery } from './alert-evidence';

	let { alert }: { alert: Alert } = $props();

	const traffic = $derived(trafficOf(alert));
	const recorded = $derived(recordedFields(alert));
	const zeek = $derived(zeekQuery(alert));
	const preview = $derived(packetPreview(alert));
	const before = $derived(beforeWindow(alert));

	interface ZeekRow {
		id: string;
		time: string;
		dataset: string;
		uid: string;
		detail: string;
	}

	/** Newest first: a community ID reused all day (NTP 123↔123) would otherwise list the day-old records */
	const ZEEK_SIZE = 10;
	const ZEEK_FIELDS = ['@timestamp', 'event.dataset', 'zeek.uid', 'zeek.ssl.server_name', 'zeek.dns.query', 'zeek.http.host', 'zeek.http.uri', 'zeek.conn.conn_state'];
	let zeekState = $state<{ status: 'loading' | 'ok' | 'error'; rows: ZeekRow[]; total: number; message: string }>({ status: 'loading', rows: [], total: 0, message: '' });

	const str = (v: unknown): string => (Array.isArray(v) ? String(v[0] ?? '') : v == null ? '' : String(v));
	const when = (iso: string) => {
		const d = new Date(iso);
		return Number.isFinite(d.getTime()) ? d.toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : iso;
	};

	function zeekRow(hit: { _id?: string; _source?: Record<string, unknown> }, i: number): ZeekRow {
		const src = hit._source ?? {};
		const f = (path: string) => str(getField(src, path));
		const http = [f('zeek.http.host'), f('zeek.http.uri')].filter(Boolean).join('');
		const state = f('zeek.conn.conn_state');
		return {
			id: hit._id ?? String(i),
			time: f('@timestamp'),
			dataset: f('event.dataset').toUpperCase() || 'Record',
			uid: f('zeek.uid') || '—',
			detail: f('zeek.ssl.server_name') || f('zeek.dns.query') || http || (state ? `state ${state}` : ''),
		};
	}

	async function loadZeek() {
		if (!zeek) return;
		try {
			const params = new URLSearchParams({ query: zeek.query, from: zeek.from, to: zeek.to, size: String(ZEEK_SIZE), sort: '@timestamp:desc', fields: ZEEK_FIELDS.join(',') });
			const res = await fetch(`/api/logs/search?${params}`);
			if (!res.ok) throw new Error(`NetTap couldn't search the Zeek records (HTTP ${res.status}).`);
			const data = await res.json();
			const hits = Array.isArray(data?.hits) ? data.hits : [];
			zeekState = { status: 'ok', rows: hits.map(zeekRow), total: typeof data?.total === 'number' ? data.total : hits.length, message: '' };
		} catch (err) {
			zeekState = { status: 'error', rows: [], total: 0, message: err instanceof Error ? err.message : "NetTap couldn't search the Zeek records." };
		}
	}

	onMount(() => void loadZeek());

	const zeekColumns: Column<ZeekRow>[] = [
		{ key: 'time', label: 'Time', sortValue: (r) => Date.parse(r.time), cell: zeekTimeCell },
		{ key: 'dataset', label: 'Record' },
		{ key: 'uid', label: 'Connection ID', class: 'mono' },
		{ key: 'detail', label: 'Detail' },
	];

	// --- Packets near the alert time ---
	let running = $state(false);
	let result = $state<PacketSearchResult | null>(null);
	let problem = $state<SearchProblem | null>(null);
	let captureNote = $state('');
	let downloading = $state(false);
	let downloadError = $state('');

	async function showPackets() {
		if ('problem' in preview || running) return;
		running = true;
		problem = null;
		captureNote = '';
		downloadError = '';
		try {
			result = await searchPackets({ filter: preview.filter, from: preview.from, to: preview.to, limit: 100 });
			if (result.rows.length === 0) captureNote = await captureContext(preview.from, preview.to);
		} catch (err) {
			result = null;
			problem = searchProblem(err);
		} finally {
			running = false;
		}
	}

	/** A fetch, not the Packets page's form post: a failure must stay in the drawer, not replace the page. */
	async function download() {
		if (!result || downloading) return;
		downloading = true;
		downloadError = '';
		try {
			const url = URL.createObjectURL(await downloadPackets(result.manifest));
			const a = document.createElement('a');
			a.href = url;
			a.download = pcapName(alert);
			a.click();
			setTimeout(() => URL.revokeObjectURL(url), 0);
		} catch (err) {
			const p = searchProblem(err);
			if (p.kind === 'changed') result = null; // the manifest is stale: offer Show packets again
			downloadError = p.kind === 'changed' ? 'The capture files changed since the search. Show the packets again.' : p.message;
		} finally {
			downloading = false;
		}
	}

	/** What the capture index says about the window: an observation, never "no longer saved". */
	async function captureContext(from: string, to: string): Promise<string> {
		try {
			const captures = await getCaptures();
			const plan = planFiles(captures.files, from, to);
			if (plan && (plan.failed.length || plan.unindexed)) return "Some capture files couldn't be read or aren't indexed yet, so coverage is unknown.";
			if (plan && plan.read.length === 0) {
				const oldest = captures.oldest_packet ? ` The earliest indexed packet is from ${when(new Date(Number(captures.oldest_packet) * 1000).toISOString())}.` : '';
				return `No saved capture covers this window.${oldest}`;
			}
			return '';
		} catch {
			return '';
		}
	}

	const status = $derived.by(() => {
		if (!result) return '';
		if (result.rows.length === 0) return result.message || emptyResultText(result);
		const c = coverage(result);
		return `${c.text} (${coverageNote(result)}).`;
	});
	const shownWindow = $derived(result ? `${clockTime(result.window.effective.from, false)} to ${clockTime(result.window.effective.to, false)}` : '');
	const packetsHref = $derived(
		result && !('problem' in preview) ? packetsUrl({ filter: preview.filter, from: result.window.effective.from, to: result.window.effective.to, limit: 1000, device: null, conn: null }) : '',
	);
	const beforeHref = $derived(before && !('problem' in preview) ? packetsUrl({ filter: preview.filter, from: before.from, to: before.to, limit: 1000, device: null, conn: null }) : '');

	const addr = (row: PacketRow, side: 'src' | 'dst') => field(row, `ip.${side}`) ?? field(row, `ipv6.${side}`) ?? '';
	const portOf = (row: PacketRow, side: 'src' | 'dst') => (side === 'src' ? srcPortOf(row) : dstPortOf(row)) ?? '';
	const packetColumns: Column<PacketRow>[] = [
		{ key: 't', label: 'Time', sortValue: (r) => Number(r.t), cell: timeCell },
		{ key: 'from', label: 'From', sortValue: (r) => addr(r, 'src'), cell: fromCell },
		{ key: 'to', label: 'To', sortValue: (r) => addr(r, 'dst'), cell: toCell },
		{ key: 'protocol', label: 'Protocol' },
		{ key: 'len', label: 'Length', numeric: true },
		{ key: 'info', label: 'Info', class: 'wrap' },
	];
</script>

{#snippet zeekTimeCell(row: ZeekRow)}<span class="num">{when(row.time)}</span>{/snippet}
{#snippet timeCell(row: PacketRow)}<span class="num">{clockTime(row.t)}</span>{/snippet}
{#snippet endCell(row: PacketRow, side: 'src' | 'dst')}
	{#if addr(row, side)}<IPAddress ip={addr(row, side)} />{#if portOf(row, side)}<span class="mono dim">:{portOf(row, side)}</span>{/if}{:else}<span class="dim">—</span>{/if}
{/snippet}
{#snippet fromCell(row: PacketRow)}{@render endCell(row, 'src')}{/snippet}
{#snippet toCell(row: PacketRow)}{@render endCell(row, 'dst')}{/snippet}

<section class="evidence" aria-label="Evidence">
	<h3 class="eyebrow">What Suricata saw</h3>
	{#if traffic}
		<p class="saw">
			Suricata saw {traffic.app ? `${traffic.app} ` : ''}traffic from <IPAddress ip={traffic.from.ip} />{#if traffic.from.port !== null}{' '}<span class="dim">port {traffic.from.port}</span>{/if}
			to <IPAddress ip={traffic.to.ip} />{#if traffic.to.port !== null}{' '}<span class="dim">port {traffic.to.port}</span>{/if}.
			{#if traffic.from.owner}<span class="owner">{traffic.from.ip} is {traffic.from.owner}.</span>{/if}
			{#if traffic.to.owner}<span class="owner">{traffic.to.ip} is {traffic.to.owner}.</span>{/if}
		</p>
	{:else}
		<p class="dim">This alert doesn't carry two IP addresses.</p>
	{/if}

	<h3 class="eyebrow">Fields Suricata recorded</h3>
	{#if recorded.length}
		<dl class="facts">
			{#each recorded as r (r.label)}
				<dt>{r.label}</dt>
				<dd class="mono wrap">{r.value}</dd>
			{/each}
		</dl>
	{:else}
		<p class="dim">None of the protocol fields shown here are in this alert. The alert doesn't say which bytes matched the rule; the packets near the alert time may show them.</p>
	{/if}

	<h3 class="eyebrow">Zeek records sharing this community ID</h3>
	{#if !zeek}
		<p class="dim">This alert has no community ID to look up.</p>
	{:else if zeekState.status === 'loading'}
		<p class="dim" role="status">Looking up Zeek records…</p>
	{:else if zeekState.status === 'error'}
		<p class="notice is-error" role="alert"><Icon name="warn" />{zeekState.message}</p>
	{:else if zeekState.rows.length === 0}
		<p class="dim">No Zeek records share this community ID from {when(zeek.from)} to {when(zeek.to)}.</p>
	{:else}
		<div class="scroller">
			<DataTable columns={zeekColumns} rows={zeekState.rows} rowKey={(r) => r.id} ariaLabel="Zeek records sharing this alert's community ID" />
		</div>
		<p class="note">
			Showing {zeekState.rows.length.toLocaleString('en-GB')} of {zeekState.total.toLocaleString('en-GB')} records from {when(zeek.from)} to {when(zeek.to)}.
			A community ID repeats when the same addresses and ports are reused, so these may include other connections.
		</p>
	{/if}
	{#if zeek}<p class="links"><a href={zeek.href}><Icon name="logs" />Open all in Log Explorer</a></p>{/if}

	<h3 class="eyebrow">Packets near the alert time</h3>
	{#if 'problem' in preview}
		<p class="dim">{preview.problem}</p>
	{:else}
		<p class="note">{preview.label}.</p>
		{#if !result && !problem}
			<button class="btn primary" type="button" disabled={running} onclick={showPackets}>
				<Icon name="filter" />{running ? 'Searching the capture…' : 'Show packets'}
			</button>
		{/if}
		{#if downloadError}<p class="notice is-error" role="alert"><Icon name="warn" />{downloadError}</p>{/if}
		{#if problem}
			<p class="notice is-error" role="alert"><Icon name="warn" />{problem.message}</p>
			{#if problem.kind === 'refused'}
				<p class="links"><a href="/packets">Choose a shorter window on Packets</a></p>
			{:else}
				<button class="btn" type="button" disabled={running} onclick={showPackets}>{running ? 'Searching the capture…' : 'Try again'}</button>
			{/if}
		{/if}
		{#if result}
			<p class="note" role="status">{status} Searched {shownWindow}.</p>
			{#if captureNote}<p class="note">{captureNote}</p>{/if}
			{#if result.rows.length}
				<div class="scroller">
					<DataTable columns={packetColumns} rows={result.rows} rowKey={(r) => r.n} ariaLabel="Packets near the alert time" />
				</div>
			{/if}
			<div class="actions">
				<a class="btn" href={packetsHref}><Icon name="filter" />Open in Packets</a>
				{#if result.rows.length}
					<button class="btn" type="button" disabled={downloading} onclick={download}>
						<Icon name="download" />{downloading ? 'Downloading…' : `Download ${result.rows.length === 1 ? 'this packet' : `these ${result.rows.length.toLocaleString('en-GB')} packets`}`}
					</button>
				{/if}
			</div>
		{/if}
		{#if beforeHref}
			<p class="note">If Suricata raised this alert when the connection timed out, its packets are earlier: <a href={beforeHref}>search the 11 minutes before</a>.</p>
		{/if}
	{/if}
</section>

<style>
	.evidence { display: grid; gap: var(--sp-2); border-top: 1px solid var(--line); padding-top: var(--sp-3); }
	.evidence h3 { margin: var(--sp-2) 0 0; }
	.saw { margin: 0; color: var(--text-1); }
	.owner { display: block; color: var(--text-2); font-size: var(--text-sm); }
	.note { margin: 0; color: var(--text-2); font-size: var(--text-sm); }
	.links { margin: 0; font-size: var(--text-sm); }
	.links a { display: inline-flex; align-items: center; gap: var(--sp-1); }
	/* about twelve rows, so the facts and actions below stay in reach */
	.scroller { max-height: calc(var(--sp-8) * 7); overflow: auto; }
	.evidence .btn { justify-self: start; }
</style>
