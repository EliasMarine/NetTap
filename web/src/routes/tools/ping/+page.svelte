<script lang="ts">
	/**
	 * Ping & Traceroute — Test reachability, measure latency, trace routes.
	 *
	 * A form card (target, count, Ping and Traceroute), then tabs:
	 *   - Ping: four KPI cards, round-trip times as a BarList, and the replies in a DataTable
	 *   - Traceroute: the route as a strip of hops, and the hops in a DataTable
	 * Reads URL query params: ?target=X&tab=traceroute
	 */

	import { page } from '$app/stores';
	import { ping, traceroute } from '$api/tools';
	import type { PingReply, PingResult, TracerouteHop, TracerouteResult } from '$api/tools';
	import BarList from '$lib/components/ui/BarList.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let target = $state('');
	let count = $state(4);
	let activeTab = $state<'ping' | 'traceroute'>('ping');

	let pingResult = $state<PingResult | null>(null);
	let traceResult = $state<TracerouteResult | null>(null);
	let pingLoading = $state(false);
	let traceLoading = $state(false);
	let pingError = $state('');
	let traceError = $state('');

	// ---------------------------------------------------------------------------
	// Read URL query params on load
	// ---------------------------------------------------------------------------

	$effect(() => {
		const params = $page.url.searchParams;
		const t = params.get('target');
		const tab = params.get('tab');
		if (t) target = t;
		if (tab === 'traceroute') activeTab = 'traceroute';
	});

	// ---------------------------------------------------------------------------
	// Actions
	// ---------------------------------------------------------------------------

	async function runPing() {
		const trimmed = target.trim();
		if (!trimmed) return;
		pingLoading = true;
		pingError = '';
		pingResult = null;
		activeTab = 'ping';
		try {
			pingResult = await ping(trimmed, count);
			if (pingResult.error) pingError = pingResult.error;
		} catch (e) {
			pingError = e instanceof Error ? e.message : 'Ping failed';
		} finally {
			pingLoading = false;
		}
	}

	async function runTraceroute() {
		const trimmed = target.trim();
		if (!trimmed) return;
		traceLoading = true;
		traceError = '';
		traceResult = null;
		activeTab = 'traceroute';
		try {
			traceResult = await traceroute(trimmed, 30);
			if (traceResult.error) traceError = traceResult.error;
		} catch (e) {
			traceError = e instanceof Error ? e.message : 'Traceroute failed';
		} finally {
			traceLoading = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') runPing();
	}

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	// OLD CODE START — the RTT colours (green, amber, red by threshold) meant nothing without a word,
	// and the system keeps colour for severity; BarList scales the bars itself
	// function rttColor(ms: number): string {
	// 	if (ms < 50) return 'good';
	// 	if (ms < 200) return 'medium';
	// 	return 'bad';
	// }
	//
	// function traceRttColor(ms: number): string {
	// 	if (ms < 10) return 'good';
	// 	if (ms < 100) return 'medium';
	// 	return 'bad';
	// }
	//
	// function barHeight(ms: number, maxMs: number): number {
	// 	if (maxMs <= 0) return 10;
	// 	return Math.max(10, Math.round((ms / maxMs) * 80));
	// }
	//
	// let maxRtt = $derived(
	// 	pingResult?.replies?.length
	// 		? Math.max(...pingResult.replies.map((r) => r.time_ms))
	// 		: 1
	// );
	// OLD CODE END

	const tabs = [
		{ value: 'ping' as const, label: 'Ping results' },
		{ value: 'traceroute' as const, label: 'Traceroute' },
	];

	const TIMEOUT = '* * *';
	const isTimeout = (hop: TracerouteHop) => hop.host === TIMEOUT;
	const rtt = (hop: TracerouteHop, i: number): number | null => (!isTimeout(hop) && hop.rtts[i] != null && hop.rtts[i] > 0 ? hop.rtts[i] : null);

	/** S12: a round-trip figure only when a reply came back; 100% loss has none, not 0.0 ms. */
	const rttKpi = (r: PingResult, v: number | null): string | null => (r.packets_received > 0 && v != null ? v.toFixed(1) : null);

	// A reply has no id of its own (ping can report a duplicate seq), so each row carries its position
	type ReplyRow = PingReply & { i: number };
	let replyRows = $derived<ReplyRow[]>((pingResult?.replies ?? []).map((r, i) => ({ ...r, i })));

	let rttBars = $derived(
		replyRows.map((r) => ({ key: String(r.i), label: `#${r.seq}`, value: r.time_ms, display: `${r.time_ms.toFixed(1)} ms` }))
	);

	const replyColumns: Column<ReplyRow>[] = [
		{ key: 'seq', label: 'Seq', numeric: true },
		{ key: 'from', label: 'From', cell: replyFrom },
		{ key: 'bytes', label: 'Bytes', numeric: true },
		{ key: 'ttl', label: 'TTL', numeric: true },
		{ key: 'time_ms', label: 'Time', numeric: true, cell: replyTime },
	];

	const hopColumns: Column<TracerouteHop>[] = [
		{ key: 'hop', label: 'Hop', numeric: true },
		{ key: 'host', label: 'Host', cell: hopHost },
		{ key: 'ip', label: 'IP', sortValue: (h) => (isTimeout(h) ? null : h.ip), cell: hopIp },
		{ key: 'rtt0', label: 'RTT 1', numeric: true, sortValue: (h) => rtt(h, 0), cell: hopRtt0 },
		{ key: 'rtt1', label: 'RTT 2', numeric: true, sortValue: (h) => rtt(h, 1), cell: hopRtt1 },
		{ key: 'rtt2', label: 'RTT 3', numeric: true, sortValue: (h) => rtt(h, 2), cell: hopRtt2 },
	];
</script>

{#snippet replyFrom(r: ReplyRow)}<span class="mono">{r.from}</span>{/snippet}
{#snippet replyTime(r: ReplyRow)}{r.time_ms.toFixed(1)} ms{/snippet}
{#snippet hopHost(h: TracerouteHop)}{#if isTimeout(h)}<span class="dim mono">{TIMEOUT}</span>{:else}<span class="mono">{h.host}</span>{/if}{/snippet}
{#snippet hopIp(h: TracerouteHop)}{#if isTimeout(h)}<span class="dim">—</span>{:else}<span class="mono">{h.ip}</span>{/if}{/snippet}
{#snippet hopRtt0(h: TracerouteHop)}{@render hopRtt(h, 0)}{/snippet}
{#snippet hopRtt1(h: TracerouteHop)}{@render hopRtt(h, 1)}{/snippet}
{#snippet hopRtt2(h: TracerouteHop)}{@render hopRtt(h, 2)}{/snippet}
{#snippet hopRtt(h: TracerouteHop, i: number)}{@const v = rtt(h, i)}{#if v != null}{v.toFixed(3)} ms{:else}<span class="dim">*</span>{/if}{/snippet}

<svelte:head>
	<title>Ping and traceroute | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<a class="back" href="/tools"><Icon name="back" />Tools</a>
		<h1 class="page-title">Ping and traceroute</h1>
		<p class="page-sub">Test reachability, measure latency and trace the route packets take.</p>
	</div>
</div>

<div class="grid">
	<Card title="Target" sub="Host name or IP address · ping sends 1 to 10 packets" class="c-12">
		<div class="form-grid">
			<div class="field">
				<label class="label" for="ping-target">Target</label>
				<input id="ping-target" type="text" class="input mono" placeholder="IP or hostname" bind:value={target} onkeydown={handleKeydown} />
			</div>
			<div class="field">
				<label class="label" for="ping-count">Count</label>
				<input id="ping-count" type="number" class="input" bind:value={count} min="1" max="10" />
			</div>
		</div>
		<div class="form-actions">
			<button class="btn" type="button" onclick={runTraceroute} disabled={traceLoading || !target.trim()}>
				<Icon name="connections" />{traceLoading ? 'Tracing…' : 'Traceroute'}
			</button>
			<button class="btn primary" type="button" onclick={runPing} disabled={pingLoading || !target.trim()}>
				<Icon name="live" />{pingLoading ? 'Pinging…' : 'Ping'}
			</button>
		</div>
	</Card>
</div>

<Pills options={tabs} bind:value={activeTab} mode="tabs" idPrefix="ping" ariaLabel="Results" />

<div role="tabpanel" id="ping-panel-ping" aria-labelledby="ping-tab-ping" hidden={activeTab !== 'ping'}>
	<div class="grid">
		{#if pingLoading}
			<Card title="Ping results" sub="Round-trip time per reply, in ms" class="c-12">
				<CardState state="loading" title="Pinging {target.trim()}" />
			</Card>
		{:else if pingError}
			<Card title="Ping results" sub="Round-trip time per reply, in ms" class="c-12">
				<CardState state="error" title="Ping failed" message={pingError} />
			</Card>
		{:else if pingResult}
			<!-- OLD CODE START — 2026-11-06 (S12): no reply read as a 0.0 ms round trip
			<KpiCard label="Average RTT" icon="live" value={pingResult.rtt_avg.toFixed(1)} unit="ms" class="c-3" />
			<KpiCard label="Minimum RTT" icon="down" value={pingResult.rtt_min.toFixed(1)} unit="ms" class="c-3" />
			<KpiCard label="Maximum RTT" icon="up" value={pingResult.rtt_max.toFixed(1)} unit="ms" class="c-3" />
			OLD CODE END -->
			{@const avg = rttKpi(pingResult, pingResult.rtt_avg)}
			{@const min = rttKpi(pingResult, pingResult.rtt_min)}
			{@const max = rttKpi(pingResult, pingResult.rtt_max)}
			<KpiCard label="Packet loss" icon="connections" value={pingResult.packet_loss_pct} unit="%" class="c-3" />
			<KpiCard label="Average RTT" icon="live" value={avg ?? '—'} unit={avg ? 'ms' : undefined} class="c-3" />
			<KpiCard label="Minimum RTT" icon="down" value={min ?? '—'} unit={min ? 'ms' : undefined} class="c-3" />
			<KpiCard label="Maximum RTT" icon="up" value={max ?? '—'} unit={max ? 'ms' : undefined} class="c-3" />
			{#if pingResult.replies.length > 0}
				<Card title="Round-trip time" sub="ms per reply, by sequence number" class="c-5">
					<BarList items={rttBars} />
				</Card>
				<Card title="Replies" sub="{pingResult.replies.length} replies from {pingResult.target}" class="c-7">
					<DataTable columns={replyColumns} rows={replyRows} ariaLabel="Ping replies" rowKey={(r) => r.i} />
				</Card>
			{/if}
		{:else}
			<Card title="Ping results" sub="Round-trip time per reply, in ms" class="c-12">
				<CardState state="empty" icon="live" title="No results yet" message="Enter a target and choose Ping or Traceroute to begin." />
			</Card>
		{/if}
	</div>
</div>

<div role="tabpanel" id="ping-panel-traceroute" aria-labelledby="ping-tab-traceroute" hidden={activeTab !== 'traceroute'}>
	<div class="grid">
		{#if traceLoading}
			<Card title="Traceroute" sub="Up to 30 hops" class="c-12">
				<CardState state="loading" title="Tracing the route to {target.trim()}" />
			</Card>
		{:else if traceError}
			<Card title="Traceroute" sub="Up to 30 hops" class="c-12">
				<CardState state="error" title="Traceroute failed" message={traceError} />
			</Card>
		{:else if traceResult && traceResult.hops.length > 0}
			<Card title="Route" sub="{traceResult.total_hops} hops · first RTT per hop" class="c-12">
				<ol class="route">
					<li class="hop is-start"><span class="hop-dot"></span><span class="hop-name">NetTap</span><span class="hop-rtt">0 ms</span></li>
					{#each traceResult.hops as hop (hop.hop)}
						<li class={['hop', isTimeout(hop) && 'is-timeout', hop.hop === traceResult.total_hops && 'is-end']}>
							<span class="hop-dot"></span>
							<span class="hop-name mono">{isTimeout(hop) ? TIMEOUT : hop.host || hop.ip}</span>
							<span class="hop-rtt">{hop.rtts.length > 0 && hop.rtts[0] > 0 ? `${hop.rtts[0].toFixed(1)} ms` : 'timeout'}</span>
						</li>
					{/each}
				</ol>
			</Card>
			<Card title="Hops" sub="Three probes per hop, in ms" class="c-12">
				<DataTable columns={hopColumns} rows={traceResult.hops} ariaLabel="Traceroute hops" rowKey={(h) => h.hop} />
			</Card>
		{:else}
			<Card title="Traceroute" sub="Up to 30 hops" class="c-12">
				<CardState state="empty" icon="connections" title="No traceroute results" message="Enter a target and choose Traceroute to trace the route." />
			</Card>
		{/if}
	</div>
</div>

<style>
	/* Layout glue: the route as a row of hops joined by a line, scrolling sideways when long */
	.route { list-style: none; margin: 0; padding: 0 0 var(--sp-2); display: flex; overflow-x: auto; font-size: var(--text-xs); }
	.hop { position: relative; flex: 0 0 auto; min-width: 96px; max-width: 160px; display: flex; flex-direction: column; align-items: center; gap: var(--sp-1); padding: 0 var(--sp-2); text-align: center; }
	.hop::before { content: ""; position: absolute; top: 5px; left: 0; right: 50%; height: 2px; background: var(--accent); }
	.hop::after { content: ""; position: absolute; top: 5px; left: 50%; right: 0; height: 2px; background: var(--accent); }
	.hop.is-start::before, .hop:last-child::after { display: none; }
	.hop.is-timeout::before, .hop.is-timeout::after { background: var(--line-strong); }
	.hop-dot { position: relative; z-index: 1; width: 12px; height: 12px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 0 3px var(--bg); }
	.hop.is-start .hop-dot, .hop.is-end .hop-dot { background: var(--text-1); }
	.hop.is-timeout .hop-dot { background: var(--surface-3); border: 1px solid var(--line-strong); }
	.hop-name { color: var(--text-1); overflow-wrap: anywhere; }
	.hop.is-timeout .hop-name, .hop-rtt { color: var(--text-3); }
</style>
