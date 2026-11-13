<!--
  MomentDevices: the moment page's Top devices card (NET-249). The ranking and the totals are
  /api/devices' own accounting for the window; under each device, the destinations, names and apps
  of the connections it started there. Byte figures are plain text: a device's totals include IPv6
  credited to it by MAC, which a Log Explorer search by its address can't reproduce, so its
  "Connection records" link is navigation and carries no count.
-->
<script lang="ts">
	import Card from '$components/ui/Card.svelte';
	import CardState from '$components/ui/CardState.svelte';
	import DataTable, { type Column } from '$components/ui/DataTable.svelte';
	import Icon from '$components/ui/Icon.svelte';
	import type { MomentDevice, MomentDevicesResponse } from '$api/moment';
	import { formatBytes } from '$api/logs';
	import { domainHref, ipHref } from '$lib/stores/lan';
	import { fmt, logsHrefForIp, type DrillRangeValue, type DrillWindow } from '$lib/utils/drilldown';
	import { ipv6LeftOutText } from '$lib/utils/ipv6-coverage';
	import { loadFailed } from '$lib/utils/load-failed';

	let {
		reply,
		error,
		window: win,
		range,
		words,
		onretry,
	}: {
		/** The reply on screen, or null before one lands */
		reply: MomentDevicesResponse | null;
		/** The last request's failure reason; undefined when it didn't fail */
		error: string | undefined;
		window: DrillWindow;
		range: DrillRangeValue;
		words: string;
		onretry: () => void;
	} = $props();

	const rows = $derived(reply?.devices ?? []);
	const columns: Column<MomentDevice>[] = [
		{ key: 'device', label: 'Device', cell: deviceCell, sortValue: (d) => d.name ?? d.ip },
		{ key: 'download', label: 'Downloaded', numeric: true, cell: downCell, sortValue: (d) => d.download_bytes },
		{ key: 'upload', label: 'Uploaded', numeric: true, cell: upCell, sortValue: (d) => d.upload_bytes },
		{ key: 'total', label: 'Total', numeric: true, cell: totalCell, sortValue: (d) => d.total_bytes },
		{ key: 'connections', label: 'Connections', numeric: true, cell: connCell, sortValue: (d) => d.connection_count },
	];
	const leftOut = (d: MomentDevice) =>
		`${fmt(d.ipv6_left_out)} IPv6 ${d.ipv6_left_out === 1 ? 'connection' : 'connections'} left out of these totals. ${ipv6LeftOutText(d.ipv6_left_out_reason) ?? ''}`.trim();
</script>

{#snippet downCell(d: MomentDevice)}{formatBytes(d.download_bytes)}{/snippet}
{#snippet upCell(d: MomentDevice)}{formatBytes(d.upload_bytes)}{/snippet}
{#snippet totalCell(d: MomentDevice)}{formatBytes(d.total_bytes)}{/snippet}
{#snippet connCell(d: MomentDevice)}{fmt(d.connection_count)}{/snippet}

{#snippet deviceCell(d: MomentDevice)}
	<div class="dev">
		<a href="/devices/{encodeURIComponent(d.ip)}">{d.name ?? d.ip}</a>
		{#if d.name}<span class="mono dim">{d.ip}</span>{/if}
		{#if d.destinations.length || d.apps.length}
			<p class="chips"><span class="dim">Talked to</span>{#each d.destinations as x (x.ip)}<a class="chip mono" href={$ipHref(x.ip)}>{x.ip}</a>{/each}</p>
			{#if d.apps.length}<p class="chips"><span class="dim">Apps</span>{#each d.apps as x (x.protocol)}<span class="chip">{x.protocol}</span>{/each}</p>{/if}
		{:else}
			<p class="dim">Started no connections in this window.</p>
		{/if}
		{#if d.domains.length}
			<p class="chips"><span class="dim">Looked up</span>{#each d.domains as x (x.domain)}<a class="chip" href={domainHref(x.domain)}>{x.domain}</a>{/each}</p>
		{/if}
		{#if d.ipv6_left_out > 0}<p class="dim">{leftOut(d)}</p>{/if}
		<a class="link" href={logsHrefForIp(d.ip, range, win, 'zeek.conn')}>Connection records for {d.ip}</a>
	</div>
{/snippet}

<Card
	title="Top devices"
	sub="By bytes{reply ? ` · top ${fmt(rows.length)} of ${fmt(reply.total_devices)}` : ''} · {words}"
	class="c-8"
>
	{#if rows.length}
		{#if error !== undefined}
			<p class="notice is-warn" role="status"><Icon name="warn" /><span>{loadFailed('top devices', true)}</span></p>
		{/if}
		<DataTable {columns} {rows} ariaLabel="Top devices in this window" rowKey={(d) => d.ip} initialSort={{ key: 'total', dir: 'desc' }} />
		<p class="card-sub foot">
			Each list ranks the connections the device started (top 5), not counts that add up. IPv6 matched to a device is in its totals but
			not in its lists.
		</p>
	{:else if error !== undefined}
		<CardState state="error" title={loadFailed('top devices')} message={error || 'Check that the daemon is running on the System page, then try again.'} onaction={onretry} />
	{:else if !reply}
		<CardState state="loading" title="Loading top devices" />
	{:else}
		<CardState state="empty" title="No devices seen in this window" message="Devices appear here once NetTap sees their traffic." />
	{/if}
</Card>

<style>
	/* Layout glue the system lacks */
	.dev { display: flex; flex-direction: column; align-items: flex-start; gap: var(--sp-1); min-width: 0; }
	.chips { display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-1); margin: 0; }
	.chips .dim { margin-right: var(--sp-1); }
	.dim { color: var(--text-3); margin: 0; }
	.foot { margin-top: var(--sp-3); }
</style>
