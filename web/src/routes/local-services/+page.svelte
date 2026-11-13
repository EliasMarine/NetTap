<script lang="ts">
	/**
	 * Local services (NET-264): the services devices announce over mDNS and SSDP, one row per
	 * sender as the capture saw it (/api/local-services). A sender is not claimed to own what it
	 * announces: a router that repeats announcements between VLANs has rows of its own.
	 */
	import { onDestroy, onMount } from 'svelte';
	import { getLocalServices, type LocalServiceRow, type LocalServicesResponse } from '$lib/api/local-services';
	import { registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import { DRILL_RANGES, fmt, formatWhen } from '$lib/utils/drilldown';
	import { loadFailed } from '$lib/utils/load-failed';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import SearchField from '$lib/components/ui/SearchField.svelte';
	import IPAddress from '$lib/components/IPAddress.svelte';
	import { protocolWord, rowMatches, serviceName, ssdpPacketsHref, vlanWords } from './service-types';

	// the daemon reads at most 7 days
	const RANGES = DRILL_RANGES.filter((r) => r.hours <= 168);
	const WHAT = 'local services';

	let range = $state('24h');
	let loaded = $state<{ data: LocalServicesResponse; words: string; at: number } | null>(null);
	let failure = $state<string | null>(null);
	let loading = $state(true);
	let query = $state('');

	const rows = $derived((loaded?.data.rows ?? []).filter((r) => rowMatches(r, query)));

	const refresh = registerPageRefresh(load);
	onMount(() => void refresh.run());
	onDestroy(refresh.unregister);

	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const picked = RANGES.find((r) => r.value === range) ?? RANGES[2];
		const to = Date.now();
		loading = true;
		try {
			const data = await getLocalServices({ from: new Date(to - picked.hours * 3_600_000).toISOString(), to: new Date(to).toISOString() });
			if (!guard.current(g)) return 'skipped';
			loaded = { data, words: picked.words, at: to };
			failure = null;
			return 'ok';
		} catch (err) {
			if (!guard.current(g)) return 'skipped';
			failure = err instanceof Error ? err.message : String(err);
			return 'failed';
		} finally {
			if (guard.current(g)) loading = false;
		}
	}

	function pickRange(value: string): void {
		range = value;
		loaded = null; // rows from another window never stand in for this one
		void refresh.run();
	}

	const columns: Column<LocalServiceRow>[] = [
		{ key: 'service', label: 'Service', cell: serviceCell, sortValue: (r) => serviceName(r.protocol, r.service_type ?? '') },
		{ key: 'instance', label: 'Instance', cell: instanceCell, sortValue: (r) => r.instance ?? '' },
		{ key: 'sender', label: 'Announced by', cell: senderCell, sortValue: (r) => r.sender.name ?? r.sender.ip },
		{ key: 'protocol', label: 'Protocol', sortValue: protocolWord, cell: protocolCell },
		{ key: 'vlan', label: 'VLAN seen on', sortValue: (r) => vlanWords(r.sender), cell: vlanCell },
		{ key: 'last_seen', label: 'Last announcement', sortValue: (r) => r.last_seen, cell: seenCell },
	];
	// OLD CODE: a key from the row's fields (two unresolved flows from one IP can match on every field)
	// const rowKey = (r: LocalServiceRow) => `${r.protocol}|${r.service_type}|${r.instance}|${r.sender.ip}|${r.sender.mac}|${r.sender.vlan}|${r.sender.vlan_state}|${r.last_seen}`;
	const rowKey = (r: LocalServiceRow) => r.id;
</script>

{#snippet serviceCell(r: LocalServiceRow)}
	<b>{serviceName(r.protocol, r.service_type ?? '')}</b>
	{#if r.service_type && serviceName(r.protocol, r.service_type) !== r.service_type}<span class="mono dim raw">{r.service_type}</span>{/if}
{/snippet}
{#snippet instanceCell(r: LocalServiceRow)}
	{#if r.protocol === 'ssdp'}
		<a href={ssdpPacketsHref(r.sender.ip, loaded?.at ?? Date.now())}>See its announcements</a>
		<span class="dim raw">Last 30 minutes, if the capture still holds them</span>
	{:else}
		{r.instance}
	{/if}
{/snippet}
{#snippet senderCell(r: LocalServiceRow)}
	{#if r.sender.name}<b>{r.sender.name}</b>{/if}
	{#if r.sender.ip.includes(':')}<span class="mono">{r.sender.ip}</span>{:else}<IPAddress ip={r.sender.ip} />{/if}
	{#if r.sender.mac}<span class="mono dim raw">{r.sender.mac}</span>{/if}
{/snippet}
{#snippet protocolCell(r: LocalServiceRow)}<span class="tag">{protocolWord(r)}</span>{/snippet}
{#snippet vlanCell(r: LocalServiceRow)}
	{#if r.sender.vlan_state === 'unknown'}
		<span class="dim" title="Its connection record isn't written yet, so NetTap can't tell the sender's MAC or VLAN.">{vlanWords(r.sender)}</span>
	{:else}
		<span class="mono">{vlanWords(r.sender)}</span>
	{/if}
{/snippet}
{#snippet seenCell(r: LocalServiceRow)}<span class="mono">{formatWhen(r.last_seen)}</span>{/snippet}
{#snippet noMatch()}<span class="dim">No announcements match your search.</span>{/snippet}

<svelte:head>
	<title>Local services | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<h1 class="page-title">Local services</h1>
		<p class="page-sub">What your devices announce on the network over mDNS and SSDP: speakers, printers, casting, smart-home hubs and file shares.</p>
	</div>
	<Pills options={RANGES.map((r) => ({ value: r.value, label: r.label }))} value={range} onchange={pickRange} ariaLabel="Time range" />
</div>

<Card title="Announcements" sub={loaded ? `${fmt(loaded.data.rows.length)} seen · ${loaded.words}` : 'One row per sender'}>
	{#if loaded}
		<p class="lead">
			Each row is one service as one sender announced it. A router that repeats announcements between VLANs shows as a sender of its own, so the same service can
			appear twice.
		</p>
		{#if failure}
			<p class="notice is-warn" role="status"><Icon name="warn" /><span>{loadFailed(WHAT, true)}</span></p>
		{/if}
		{#if loaded.data.truncated}
			<p class="notice is-warn" role="status">
				<Icon name="warn" /><span
					>NetTap stopped at one of its limits (5,000 rows, 20,000 connections matched one by one, 1,000 names from one sender, 50 from one connection, or 100,000 names in all), so this list may not hold
					every announcement. Try a shorter time range.</span
				>
			</p>
		{/if}
		{#if loaded.data.rows.length === 0}
			<CardState
				state="empty"
				title="No announcements seen"
				message="NetTap saw no mDNS or SSDP announcements in this period. Multicast stays inside its VLAN, so NetTap only sees the VLANs the mirror carries."
			/>
		{:else}
			<div class="toolbar">
				<SearchField id="service-search" label="Search announcements" placeholder="Search by service, name, address or VLAN…" size="toolbar" bind:value={query} />
			</div>
			<DataTable
				{columns}
				{rows}
				ariaLabel="Local service announcements"
				{rowKey}
				initialSort={{ key: 'last_seen', dir: 'desc' }}
				empty={noMatch}
			/>
		{/if}
	{:else if failure}
		<CardState state="error" title={loadFailed(WHAT)} message={failure} actionLabel="Try again" onaction={() => void refresh.run()} />
	{:else if loading}
		<CardState state="loading" title="Loading local services" />
	{/if}
</Card>

<style>
	.raw {
		display: block;
		font-size: var(--text-xs);
	}
	.lead {
		margin: 0 0 var(--sp-3);
		color: var(--text-2);
		font-size: var(--text-sm);
	}
</style>
