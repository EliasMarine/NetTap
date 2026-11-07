<script lang="ts">
	/**
	 * Device Detail Page (MAC-based) — Shows comprehensive info for a single
	 * device from the device registry, keyed by MAC address.
	 *
	 * - Device name, IP(s), MAC, manufacturer, category, first/last seen
	 * - Traffic breakdown: top destinations, protocols, bandwidth over time
	 * - DNS queries made by this device
	 * - Suricata alerts for this device
	 *
	 * No trust ring: the registry has no score for a device (PLAN.md §4.1, left out, not faked).
	 */

	import { page } from '$app/stores';
	import { onDestroy, untrack } from 'svelte';
	import { getRegistryDevice, getDeviceTraffic, isNewDevice } from '$api/devices-registry';
	import type { RegistryDevice, DeviceTraffic } from '$api/devices-registry';
	import IPAddress from '$components/IPAddress.svelte';
	import { loadFailed } from '$lib/utils/load-failed';
	import { suricataLevel } from '$lib/utils/severity';
	import { registerPageRefresh, outcome, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import BarList from '$lib/components/ui/BarList.svelte';
	import SeverityPill from '$lib/components/ui/SeverityPill.svelte';
	import DeviceTile from '$lib/components/ui/DeviceTile.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import { domainHref } from '$lib/stores/lan';
	import { alertsHrefForSignature, chartTime as timeLabel, DRILL_RANGES, fmt, rangeWindow, type DrillRangeValue } from '$lib/utils/drilldown';
	import { formatTime } from '$lib/utils/time';
	import AreaChart from '$lib/components/ui/charts/AreaChart.svelte';

	type Destination = DeviceTraffic['top_destinations'][number];
	type DnsQuery = NonNullable<DeviceTraffic['dns_queries']>[number];
	// keyed by position: two alerts can share a timestamp and a signature
	type TrafficAlert = NonNullable<DeviceTraffic['alerts']>[number] & { key: string };

	let device = $state<RegistryDevice | null>(null);
	let traffic = $state<DeviceTraffic | null>(null);
	let loading = $state(true);
	let error = $state(false);
	// #96: a failed request is not "Device not found"
	let deviceFailed = $state(false);
	let trafficFailed = $state(false);

	let mac = $derived($page.params.mac);

	// NET-192 PR 4: the same range pills as devices/[ip] (it read only the daemon's default 24 hours)
	let rangeValue = $state<DrillRangeValue>('24h');
	// OLD CODE: ?? DRILL_RANGES[2] (NET-192 PR 4: the default by value, not by position)
	const range = $derived(DRILL_RANGES.find((r) => r.value === rangeValue) ?? DRILL_RANGES.find((r) => r.value === '24h')!);
	const RANGE_OPTIONS = DRILL_RANGES.map((r) => ({ value: r.value, label: r.label }));
	/** The device and range the traffic on screen was read for; another one must not show it. */
	let trafficView = '';

	// OLD CODE START — 2026-11-03 UI redesign: the loader goes through the page refresh contract
	// (PLAN.md §5.5) with a load guard; the requests are unchanged
	// async function fetchData() {
	// 	if (!mac) return;
	// 	loading = true;
	// 	error = false;
	// 	try {
	// 		const [d, t] = await Promise.allSettled([getRegistryDevice(mac), getDeviceTraffic(mac)]);
	// 		if (d.status === 'fulfilled') device = d.value;
	// 		if (t.status === 'fulfilled') traffic = t.value;
	// 		deviceFailed = d.status === 'rejected';
	// 		trafficFailed = t.status === 'rejected';
	// 		if (d.status === 'fulfilled' && !device) error = true;
	// 	} catch {
	// 		error = true;
	// 	} finally {
	// 		loading = false;
	// 	}
	// }
	// $effect(() => { fetchData(); });
	// OLD CODE END
	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const m = mac;
		const r = range;
		if (!m) return 'skipped';
		const view = `${m}|${r.value}`;
		if (view !== trafficView) traffic = null;
		loading = true;
		error = false;
		// OLD CODE: const results = await Promise.allSettled([getRegistryDevice(m), getDeviceTraffic(m)]); (NET-192 PR 4: the range's window)
		const results = await Promise.allSettled([getRegistryDevice(m), getDeviceTraffic(m, rangeWindow(r.hours))]);
		if (!guard.current(g)) return 'skipped';
		const [d, t] = results;
		// OLD CODE START — #96: any failure read as "Device not found"
		// device = d.status === 'fulfilled' ? d.value : null;
		// traffic = t.status === 'fulfilled' ? t.value : null;
		// if (!device) error = true;
		// OLD CODE END
		// getRegistryDevice resolves null only for a real 404; a failed refresh keeps the last data
		if (d.status === 'fulfilled') device = d.value;
		// OLD CODE: if (t.status === 'fulfilled') traffic = t.value; (NET-192 PR 4: remember which range it is)
		if (t.status === 'fulfilled') {
			traffic = t.value;
			trafficView = view;
		}
		deviceFailed = d.status === 'rejected';
		trafficFailed = t.status === 'rejected';
		if (d.status === 'fulfilled' && !device) error = true;
		loading = false;
		return outcome(results);
	}

	const refresh = registerPageRefresh(load);
	onDestroy(() => refresh.unregister());
	$effect(() => {
		void mac; // reload for another device
		void rangeValue; // or another range
		untrack(() => refresh.run());
	});

	function formatBytes(bytes: number): string {
		if (!bytes || bytes <= 0) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		// OLD CODE START — 2026-11-06 (NET-166): 1024-based under decimal labels
		// const i = Math.floor(Math.log(bytes) / Math.log(1024));
		// const value = bytes / Math.pow(1024, i);
		// OLD CODE END
		const i = Math.floor(Math.log(bytes) / Math.log(1000));
		const value = bytes / Math.pow(1000, i);
		return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[i]}`;
	}

	function formatBytesShort(bytes: number): string {
		if (!bytes || bytes <= 0) return '0';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		// OLD CODE START — 2026-11-06 (NET-166): 1024-based under decimal labels
		// const i = Math.floor(Math.log(bytes) / Math.log(1024));
		// const value = bytes / Math.pow(1024, i);
		// OLD CODE END
		const i = Math.floor(Math.log(bytes) / Math.log(1000));
		const value = bytes / Math.pow(1000, i);
		return `${value.toFixed(value >= 10 ? 0 : 1)}${units[i]}`;
	}

	// OLD CODE START — 2026-11-03 UI redesign: legacy badge classes; SeverityPill carries colour, shape and word
	// function severityBadge(severity: number): { label: string; cls: string } {
	// 	switch (severity) {
	// 		case 1: return { label: 'HIGH', cls: 'badge severity-high' };
	// 		case 2: return { label: 'MEDIUM', cls: 'badge severity-medium' };
	// 		case 3: return { label: 'LOW', cls: 'badge severity-low' };
	// 		default: return { label: 'INFO', cls: 'badge severity-info' };
	// 	}
	// }
	// function categoryBadgeClass(cat: string): string {
	// 	switch (cat) {
	// 		case 'computer': return 'badge badge-info';
	// 		case 'phone': return 'badge badge-success';
	// 		case 'iot': return 'badge badge-warning';
	// 		case 'infrastructure': return 'badge badge-accent';
	// 		default: return 'badge badge-muted';
	// 	}
	// }
	// let chartData = $derived(traffic?.bandwidth_series?.map((p) => ({ time: p.timestamp, value: p.bytes })) ?? []);
	// let maxDestBytes = $derived(traffic?.top_destinations?.length ? Math.max(...traffic.top_destinations.map((d) => d.bytes)) : 1);
	// OLD CODE END

	// OLD CODE START — the same mapping now lives once in $lib/utils/severity (NET-146)
	// /** Suricata severity: 1 high, 2 medium, 3 low, anything else info (as the old badges read it). */
	// function alertLevel(severity: number): SeverityLevel {
	// 	if (severity === 1) return 'high';
	// 	if (severity === 2) return 'medium';
	// 	if (severity === 3) return 'low';
	// 	return 'info';
	// }
	// OLD CODE END
	const alertLevel = suricataLevel;

	const series = $derived(traffic?.bandwidth_series ?? []);
	const busiest = $derived(series.reduce((best, p, i) => (p.bytes > (series[best]?.bytes ?? -1) ? i : best), -1));
	// OLD CODE: const chartTime = (t: number | string) => new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); (NET-192 PR 4: the browser's locale printed "07:00 PM")
	const chartTime = (t: number | string) => timeLabel(t, range.hours);
	const alertRows = $derived((traffic?.alerts ?? []).slice(0, 20).map((a, i): TrafficAlert => ({ ...a, key: `${a.timestamp}-${i}` })));
	const totalParts = $derived(traffic ? formatBytes(traffic.total_bytes).split(' ') : null);

	const destColumns: Column<Destination>[] = [
		{ key: 'ip', label: 'Destination', cell: destCell },
		{ key: 'bytes', label: 'Data', numeric: true, cell: destBytesCell },
		{ key: 'connections', label: 'Connections', numeric: true, cell: destConnCell },
	];
	const dnsColumns: Column<DnsQuery>[] = [
		{ key: 'domain', label: 'Domain', cell: domainCell },
		{ key: 'count', label: 'Count', numeric: true, cell: dnsCountCell },
	];
	const alertColumns: Column<TrafficAlert>[] = [
		// higher is worse, so the first (descending) click puts the worst on top
		{ key: 'severity', label: 'Severity', cell: sevCell, sortValue: (a) => -a.severity },
		{ key: 'signature', label: 'Signature', cell: sigCell },
		{ key: 'timestamp', label: 'Time', cell: timeCell, sortValue: (a) => Date.parse(a.timestamp) },
	];
</script>

{#snippet destCell(d: Destination)}<span class="mono"><IPAddress ip={d.ip} /></span>{/snippet}
{#snippet destBytesCell(d: Destination)}{formatBytesShort(d.bytes)}{/snippet}
{#snippet destConnCell(d: Destination)}{fmt(d.connections)}{/snippet}
<!-- OLD CODE START: {#snippet domainCell(q: DnsQuery)}<span class="mono trunc" title={q.domain}>{q.domain}</span>{/snippet} (NET-160: not a link) OLD CODE END -->
{#snippet domainCell(q: DnsQuery)}<a class="mono trunc" href={domainHref(q.domain)} title={q.domain}>{q.domain}</a>{/snippet}
{#snippet dnsCountCell(q: DnsQuery)}{fmt(q.count)}{/snippet}
{#snippet sevCell(a: TrafficAlert)}<SeverityPill level={alertLevel(a.severity)} />{/snippet}
<!-- OLD CODE: {#snippet sigCell(a: TrafficAlert)}<span class="sig trunc" title={a.signature}>{a.signature}</span>{/snippet} (slice 2a: not a link) -->
{#snippet sigCell(a: TrafficAlert)}<a class="sig trunc" href={alertsHrefForSignature(a.signature)} title={a.signature}>{a.signature}</a>{/snippet}
{#snippet timeCell(a: TrafficAlert)}<span class="mono">{formatTime(a.timestamp)}</span>{/snippet}

<svelte:head>
	<title>{device?.display_name || mac} | NetTap</title>
</svelte:head>

<a href="/devices" class="back"><Icon name="back" />Devices</a>

<!-- Identity hero: the h1 is here in every state, so loading and errors keep the page's heading -->
<article class="card hero">
	<div class="ident">
		<DeviceTile size="lg" category={device?.category} />
		<div>
			<h1 class={['page-title', !device?.display_name && 'mono']}>{device?.display_name || device?.mac || mac}</h1>
			{#if device}
				<div class="chips">
					<span class="chip">{device.category || 'unknown'}</span>
					<!-- OLD CODE START — NET-158: is_new clears on the device's next update, so the chip rarely showed -->
					<!-- {#if device.is_new}<span class="chip is-ok">New</span>{/if} -->
					<!-- OLD CODE END -->
					{#if isNewDevice(device)}<span class="chip is-ok">New</span>{/if}
				</div>
			{/if}
		</div>
		<div class="head-actions">
			<Pills ariaLabel="Time range" options={RANGE_OPTIONS} bind:value={rangeValue} />
		</div>
	</div>
	{#if device}
		<dl class="ident-meta">
			<div><dt class="meta-k">MAC address</dt><dd class="meta-v mono">{device.mac}</dd></div>
			<div><dt class="meta-k">IP addresses</dt><dd class="meta-v mono">{device.ips.length > 0 ? device.ips.join(', ') : '—'}</dd></div>
			<div><dt class="meta-k">Manufacturer</dt><dd class="meta-v">{device.manufacturer ?? '—'}</dd></div>
			<div><dt class="meta-k">Hostnames</dt><dd class="meta-v mono">{device.hostnames.length > 0 ? device.hostnames.join(', ') : '—'}</dd></div>
			<div><dt class="meta-k">First seen</dt><dd class="meta-v">{formatTime(device.first_seen)}</dd></div>
			<div><dt class="meta-k">Last seen</dt><dd class="meta-v">{formatTime(device.last_seen)}</dd></div>
			{#if device.friendly_name}
				<div><dt class="meta-k">Friendly name</dt><dd class="meta-v">{device.friendly_name}</dd></div>
			{/if}
		</dl>
	{:else if loading}
		<CardState state="loading" title="Loading device details" />
	{:else if deviceFailed}
		<CardState state="error" title={loadFailed(`device ${mac}`)} onaction={() => refresh.run()} />
	{:else}
		<CardState state="empty" icon="devices" title="Device not found" message="The device with MAC address {mac} could not be found in the registry." actionLabel="Return to devices" href="/devices" />
	{/if}
</article>

{#if device && !error}
	<div class="grid">
		<KpiCard
			class="c-6"
			label="Traffic"
			icon="bandwidth"
			value={totalParts?.[0] ?? '—'}
			unit={totalParts?.[1]}
			sub={trafficFailed
				? loadFailed('traffic', traffic !== null)
				: traffic
					? `${formatBytesShort(traffic.inbound_bytes)} in / ${formatBytesShort(traffic.outbound_bytes)} out`
					: 'No traffic recorded'}
			note={range.words}
		/>
		<KpiCard
			class="c-6"
			label="Connections"
			icon="connections"
			value={traffic ? fmt(traffic.connection_count) : '—'}
			note={range.words}
		/>
		<!-- NET-158: the daemon matches the MAC or any of the device's addresses over the whole range -->
		<p class="c-12 dim">Traffic matching its MAC or any address it has used; another device may have used one since.</p>

		<!-- the daemon doesn't send a bandwidth series yet; the card shows once it does -->
		{#if traffic?.bandwidth_series}
			<Card class="c-12" hero title="Bandwidth over time" sub="Bytes per interval · {range.words}">
				{#if busiest >= 0}
					<AreaChart
						bytes
						series={[{ key: 'bytes', label: 'Bytes', colour: 1, points: series.map((p) => ({ t: p.timestamp, v: p.bytes })) }]}
						formatX={chartTime}
						formatY={formatBytesShort}
						formatTip={(i) => `${chartTime(series[i].timestamp)} · ${formatBytes(series[i].bytes)}`}
						highlightIndex={busiest}
						ariaLabel="Busiest at {chartTime(series[busiest].timestamp)}, with {formatBytes(series[busiest].bytes)}"
					/>
				{:else}
					<CardState state="empty" icon="bandwidth" title="No traffic in the {range.words}" />
				{/if}
			</Card>
		{/if}

		<Card class="c-6" title="Top destinations" sub="By bytes · {range.words}">
			{#if traffic?.top_destinations?.length}
				<DataTable
					ariaLabel="Top destinations"
					rows={traffic.top_destinations.slice(0, 8)}
					rowKey={(d) => d.ip}
					initialSort={{ key: 'bytes', dir: 'desc' }}
					columns={destColumns}
				/>
			{:else if trafficFailed && !traffic}
				<CardState state="error" title={loadFailed('traffic')} onaction={() => refresh.run()} />
			{:else}
				<CardState state="empty" icon="connections" title="No destinations in the {range.words}" />
			{/if}
		</Card>

		<Card class="c-6" title="Protocols" sub="Connections by protocol · {range.words}">
			{#if traffic?.top_protocols?.length}
				<BarList
					items={traffic.top_protocols.map((p, i) => ({
						key: `${p.name}-${i}`,
						label: p.name,
						value: p.count,
						display: fmt(p.count),
					}))}
				/>
			{:else if trafficFailed && !traffic}
				<CardState state="error" title={loadFailed('traffic')} onaction={() => refresh.run()} />
			{:else}
				<CardState state="empty" icon="connections" title="No protocols in the {range.words}" />
			{/if}
		</Card>

		<!-- the daemon doesn't send DNS queries or alerts yet; their cards show once it does -->
		{#if traffic?.dns_queries}
			<Card class="c-6" title="DNS queries" sub="Lookups by domain · {range.words}">
				{#if traffic.dns_queries.length}
					<DataTable ariaLabel="DNS queries" rows={traffic.dns_queries.slice(0, 15)} rowKey={(q) => q.domain} initialSort={{ key: 'count', dir: 'desc' }} columns={dnsColumns} />
				{:else}
					<CardState state="empty" icon="dns" title="No DNS queries in the {range.words}" />
				{/if}
			</Card>
		{/if}

		{#if traffic?.alerts}
			<Card class="c-12" title="Alerts" sub="{traffic.alerts.length} alert{traffic.alerts.length !== 1 ? 's' : ''} · {range.words}">
				{#if traffic.alerts.length}
					<DataTable
						ariaLabel="Alerts"
						rows={alertRows}
						rowKey={(a) => a.key}
						columns={alertColumns}
					/>
				{:else}
					<CardState state="empty" icon="alerts" title="No alerts in the {range.words}" />
				{/if}
			</Card>
		{/if}
	</div>
{/if}

<style>
	/* Layout glue the system lacks */
	/* OLD CODE: .ident { grid-template-columns: auto minmax(0, 1fr); } (NET-192 PR 4: the range pills take the system's third column) */
	.ident-meta > div { min-width: 0; }
	.ident-meta dd { margin: 0; }
</style>
