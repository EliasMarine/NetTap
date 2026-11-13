<script lang="ts">
	/**
	 * LAN throughput test (NET-266): iperf3 from NetTap to a peer running `iperf3 -s`.
	 *
	 * "Run test" runs upload, then download (one daemon request each, so the first result shows
	 * while the second runs). The interface the test used sits above the results; earlier runs
	 * this session go in a table below (page state only).
	 */
	import { throughput } from '$api/tools';
	import type { ThroughputDirection, ThroughputResult } from '$api/tools';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import { formatTime } from '$lib/utils/time';
	import { mirrorNote, pathLine, rate, retransmitsText } from './throughput-summary';

	type Side = { state: 'idle' | 'loading' | 'done' | 'error' | 'skipped'; result?: ThroughputResult; error?: string };
	interface RunRow {
		id: number;
		at: Date;
		peer: string;
		upload: number | null;
		download: number | null;
		retransmits: number | null;
		via: string | null;
	}

	let host = $state('');
	const DEFAULT_DURATION = 10; // the daemon's default too: an emptied field sends null
	let port = $state(5201);
	let duration = $state(DEFAULT_DURATION);
	let running = $state(false);
	let upload = $state<Side>({ state: 'idle' });
	let download = $state<Side>({ state: 'idle' });
	let history = $state<RunRow[]>([]);
	let runs = 0;

	let shown = $derived(upload.result ?? download.result);
	let started = $derived(upload.state !== 'idle');

	async function side(peer: string, direction: ThroughputDirection): Promise<Side> {
		try {
			const result = await throughput(peer, port, duration, direction);
			return result.error ? { state: 'error', result, error: result.error } : { state: 'done', result };
		} catch (e) {
			return { state: 'error', error: e instanceof Error ? e.message : 'Throughput test failed' };
		}
	}

	async function runTest() {
		const peer = host.trim();
		if (!peer || running) return;
		running = true;
		upload = { state: 'loading' };
		download = { state: 'idle' };
		upload = await side(peer, 'upload');
		// the same peer and port: once the upload fails, the download would fail the same way
		if (upload.state === 'done') {
			download = { state: 'loading' };
			download = await side(peer, 'download');
		} else {
			download = { state: 'skipped' };
		}
		history = [
			{
				id: ++runs,
				at: new Date(),
				peer,
				upload: upload.result?.bits_per_second ?? null,
				download: download.result?.bits_per_second ?? null,
				retransmits: upload.result?.retransmits ?? null,
				via: (upload.result ?? download.result)?.path?.interface ?? null,
			},
			...history,
		];
		running = false;
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') runTest();
	}

	const directions = [
		{ key: 'upload', label: 'Upload', icon: 'up', sub: 'NetTap to the peer' },
		{ key: 'download', label: 'Download', icon: 'down', sub: 'The peer to NetTap' },
	] as const;

	const historyColumns: Column<RunRow>[] = [
		{ key: 'at', label: 'Time', sortValue: (r) => r.at.getTime(), cell: rowTime },
		{ key: 'peer', label: 'Peer', cell: rowPeer },
		{ key: 'upload', label: 'Upload', numeric: true, cell: rowUpload },
		{ key: 'download', label: 'Download', numeric: true, cell: rowDownload },
		{ key: 'retransmits', label: 'Retransmits', numeric: true, cell: rowRetransmits },
		{ key: 'via', label: 'Interface', cell: rowVia },
	];
</script>

{#snippet rowTime(r: RunRow)}{formatTime(r.at, 'clock')}{/snippet}
{#snippet rowPeer(r: RunRow)}<span class="mono">{r.peer}</span>{/snippet}
{#snippet rowUpload(r: RunRow)}{rate(r.upload)}{/snippet}
{#snippet rowDownload(r: RunRow)}{rate(r.download)}{/snippet}
{#snippet rowRetransmits(r: RunRow)}{r.retransmits ?? '—'}{/snippet}
{#snippet rowVia(r: RunRow)}<span class="mono">{r.via ?? '—'}</span>{/snippet}

<svelte:head>
	<title>LAN throughput test | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<a class="back" href="/tools"><Icon name="back" />Tools</a>
		<h1 class="page-title">LAN throughput test</h1>
		<p class="page-sub">Measure how fast NetTap sends to and receives from another device on your network.</p>
	</div>
</div>

<div class="grid">
	<Card title="Peer" sub="A device on your network running iperf3 -s · private, CGNAT/VPN or ULA addresses" class="c-12">
		<div class="form-grid">
			<div class="field">
				<label class="label" for="tp-host">Peer</label>
				<input id="tp-host" type="text" class="input mono" placeholder="IP or host name" bind:value={host} onkeydown={handleKeydown} />
			</div>
			<div class="field">
				<label class="label" for="tp-port">Port</label>
				<input id="tp-port" type="number" class="input" bind:value={port} min="1" max="65535" />
			</div>
			<div class="field">
				<label class="label" for="tp-duration">Duration (seconds)</label>
				<input id="tp-duration" type="number" class="input" bind:value={duration} min="1" max="30" />
			</div>
		</div>
		<p class="field-help">Test traffic can appear in NetTap's own traffic figures if it crosses the mirrored link.</p>
		<div class="form-actions">
			<button class="btn primary" type="button" onclick={runTest} disabled={running || !host.trim()}>
				<Icon name="bandwidth" />{running ? 'Testing…' : 'Run test'}
			</button>
		</div>
	</Card>

	{#if shown?.path}
		<Card title="Source interface" sub="The way out of NetTap to {shown.resolved_ip}" class="c-12">
			<p class="path-line">{pathLine(shown)}</p>
			{#if mirrorNote(shown)}
				<p class="notice" role="note"><Icon name="infra" /><span>{mirrorNote(shown)}</span></p>
			{/if}
		</Card>
	{/if}

	{#if !started}
		<Card title="Results" sub="Mbit/s each way" class="c-12">
			<CardState state="empty" icon="bandwidth" title="No results yet" message="Start iperf3 -s on the peer, then choose Run test." />
		</Card>
	{:else}
		{#each directions as d (d.key)}
			{@const s = d.key === 'upload' ? upload : download}
			{#if s.state === 'done' && s.result}
				<KpiCard
					label={d.label}
					icon={d.icon}
					value={rate(s.result.bits_per_second)}
					sub={d.key === 'upload' ? `${d.sub} · ${retransmitsText(s.result.retransmits)}` : d.sub}
					class="c-6"
				/>
			{:else}
				<Card title={d.label} sub={d.sub} class="c-6">
					{#if s.state === 'loading'}
						<CardState state="loading" title="Testing {d.label.toLowerCase()} for {duration || DEFAULT_DURATION} seconds" />
					{:else if s.state === 'error'}
						<CardState state="error" title="{d.label} test failed" message={s.error} />
					{:else if s.state === 'skipped'}
						<CardState state="empty" icon={d.icon} title="Not run" message="The download runs after a successful upload." />
					{:else}
						<CardState state="empty" icon={d.icon} title="Waiting" message="Runs after the upload." />
					{/if}
				</Card>
			{/if}
		{/each}
	{/if}

	{#if history.length > 0}
		<Card title="Earlier runs" sub="This session only · cleared when you leave the page" class="c-12">
			<DataTable columns={historyColumns} rows={history} ariaLabel="Earlier throughput runs" rowKey={(r) => r.id} />
		</Card>
	{/if}
</div>

<style>
	.path-line { margin: 0 0 var(--sp-3); color: var(--text-1); font-size: var(--text-md); }
</style>
