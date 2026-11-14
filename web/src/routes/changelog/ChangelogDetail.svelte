<!--
  ChangelogDetail.svelte (NET-272): one changelog row's details, below the table.
  - Device rows: what it did over the loaded window, counted per address, and its top
    destinations from its busiest matched address (never the address it joined at).
  - Links keep the loaded window; the MAC page is the current overview.
  - The page calls `focus()` after opening it; Esc inside it, or Close, calls `onclose`.
-->
<script lang="ts">
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { getDeviceDetail, type DeviceDestination } from '$lib/api/devices';
	import { formatBytes } from '$lib/api/logs';
	import { fmt, logsHrefForIp, windowQuery, windowWords, type DrillRangeValue, type DrillWindow } from '$lib/utils/drilldown';
	import { formatTime } from '$lib/utils/time';
	import { eventLabels, MISSING_TEXT, PER_ADDRESS_NOTE, spanText, type ChangelogRow } from './changelog-rows';

	interface Props {
		row: ChangelogRow;
		/** The loaded window: the figures, the destinations and the links all use it. */
		win: DrillWindow;
		range: DrillRangeValue;
		onclose: () => void;
	}

	let { row, win, range, onclose }: Props = $props();

	const uid = $props.id();
	let heading = $state<HTMLHeadingElement>();

	/** Brings the panel into view and puts focus on its heading. */
	export function focus(): void {
		heading?.scrollIntoView({ block: 'start' });
		heading?.focus({ preventScroll: true });
	}

	const trafficIp = $derived(row.trafficIps[0] ?? null);
	const label = $derived(eventLabels[row.event.event_type] ?? row.event.event_type);
	const title = $derived(row.kind === 'device' ? (row.name ?? label) : row.event.title);
	const value = (n: number | null, show: (n: number) => string) => (n === null ? '—' : show(n));

	let destinations = $state<{ state: 'none' | 'loading' | 'error' | 'ok'; items: DeviceDestination[] }>({ state: 'none', items: [] });
	let attempt = $state(0);

	// A new row, a new load (a new row object and window) or a retry asks again; the cleanup drops
	// the answer it replaced, so a fast reselect or a reload never shows another device's destinations.
	$effect(() => {
		const ip = trafficIp;
		const { from, to } = win;
		void row;
		void attempt;
		if (!ip) {
			destinations = { state: 'none', items: [] };
			return;
		}
		let current = true;
		destinations = { state: 'loading', items: [] };
		// review L4: .catch also covers a reply the success handler can't read, so it never stays "loading"
		getDeviceDetail(ip, { from, to })
			.then((res) => {
				if (current) destinations = { state: 'ok', items: res.device?.top_destinations ?? [] };
			})
			.catch(() => {
				if (current) destinations = { state: 'error', items: [] };
			});
		return () => {
			current = false;
		};
	});

	function onkeydown(event: KeyboardEvent) {
		if (event.key !== 'Escape') return;
		event.stopPropagation();
		onclose();
	}

	const destColumns: Column<DeviceDestination>[] = [
		{ key: 'ip', label: 'Destination', cell: destCell },
		{ key: 'bytes', label: 'Data', numeric: true, cell: destBytesCell },
		{ key: 'connections', label: 'Connections', numeric: true, cell: destConnCell },
	];
</script>

{#snippet destCell(d: DeviceDestination)}<a class="mono" href="/address/{encodeURIComponent(d.ip)}">{d.ip}</a>{/snippet}
{#snippet destBytesCell(d: DeviceDestination)}{formatBytes(d.bytes)}{/snippet}
{#snippet destConnCell(d: DeviceDestination)}{fmt(d.connections)}{/snippet}

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<!-- Esc closes the panel from anywhere inside it; Close is the pointer and Tab path -->
<article class="card c-12" aria-labelledby="{uid}-title" {onkeydown}>
	<div class="card-head">
		<div>
			<h2 class="card-title" id="{uid}-title" tabindex="-1" bind:this={heading}>{title}</h2>
			<p class="card-sub">{label} · {formatTime(row.event['@timestamp'])}</p>
		</div>
		<button class="btn" type="button" onclick={onclose}><Icon name="close" />Close</button>
	</div>

	{#if row.kind === 'system'}
		{#if row.event.description}<p class="desc">{row.event.description}</p>{/if}
		{#if row.event.metadata && Object.keys(row.event.metadata).length > 0}
			<div class="chips">
				{#each Object.entries(row.event.metadata) as [key, val] (key)}
					<span class="chip">{key}: <span class="mono">{String(val)}</span></span>
				{/each}
			</div>
		{/if}
	{:else}
		<dl class="facts">
			<dt>Name</dt><dd>{row.name ?? '—'}</dd>
			<dt>MAC</dt><dd class="mono">{row.mac ?? '—'}</dd>
			<dt>Vendor</dt><dd>{row.vendor ?? '—'}</dd>
			<dt>Joined at</dt><dd class="mono">{row.eventIp ?? '—'}</dd>
			<dt>Counted from</dt><dd class="mono">{row.trafficIps.length ? row.trafficIps.join(', ') : '—'}</dd>
			<dt>First seen</dt><dd class="num">{formatTime(row.firstSeen)}</dd>
			<dt>Last seen in this range</dt><dd class="num">{formatTime(row.lastSeen)}</dd>
			<dt title="From the first to the last record in this range, gaps included">Seen over</dt><dd class="num">{spanText(row.spanMs)}</dd>
			<dt>Sent</dt><dd class="num">{value(row.sent, formatBytes)}</dd>
			<dt>Received</dt><dd class="num">{value(row.received, formatBytes)}</dd>
			<dt>Total</dt><dd class="num">{value(row.total, formatBytes)}</dd>
			<dt>Connections</dt><dd class="num">{value(row.connections, fmt)}</dd>
			<dt>Alerts</dt><dd class="num">{value(row.alerts, fmt)}</dd>
		</dl>
		{#if row.missing}
			<p class="notice" role="status"><Icon name="empty" /><span>{MISSING_TEXT[row.missing]}</span></p>
		{:else}
			<p class="card-sub note">{PER_ADDRESS_NOTE}</p>
		{/if}
		{#each row.ipv6Notes as note (note)}
			<p class="notice" role="status"><Icon name="warn" /><span>{note}</span></p>
		{/each}

		<ul class="links">
			{#if trafficIp}
				<li><a class="link" href="/devices/{encodeURIComponent(trafficIp)}?{windowQuery(win)}">This device in this range</a></li>
				<li><a class="link" href={logsHrefForIp(trafficIp, range, win)}>Its records in this range</a></li>
			{/if}
			{#if row.mac}
				<li><a class="link" href="/devices/mac/{encodeURIComponent(row.mac)}">Device overview (now, not this range)</a></li>
			{/if}
		</ul>

		<h3 class="sub-title">{trafficIp ? `Top destinations from ${trafficIp}` : 'Top destinations'}</h3>
		<p class="card-sub">By bytes · connections it started · {windowWords(win.from, win.to)}</p>
		{#if destinations.state === 'none'}
			<CardState state="empty" icon="connections" title="No destinations: no traffic figures for this device in this range." />
		{:else if destinations.state === 'loading'}
			<CardState state="loading" title="Loading destinations" />
		{:else if destinations.state === 'error'}
			<CardState
				state="error"
				title="Couldn't load destinations: the request failed."
				message="Check that NetTap is running on the System page, then try again."
				onaction={() => (attempt += 1)}
			/>
		{:else if destinations.items.length === 0}
			<CardState state="empty" icon="connections" title="No destinations for connections it started in this range." />
		{:else}
			<DataTable
				ariaLabel="Top destinations from {trafficIp}"
				rows={destinations.items.slice(0, 10)}
				rowKey={(d) => d.ip}
				initialSort={{ key: 'bytes', dir: 'desc' }}
				columns={destColumns}
			/>
		{/if}
	{/if}
</article>

<style>
	/* Layout glue the system lacks: the focused heading's ring, and the panel's sections */
	.card-title:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; border-radius: var(--r-xs); }
	.desc { color: var(--text-2); font-size: var(--text-sm); overflow-wrap: anywhere; margin-bottom: var(--sp-3); }
	.note { margin-top: var(--sp-2); }
	.notice { margin-top: var(--sp-3); }
	.links { list-style: none; margin: var(--sp-4) 0 0; padding: 0; display: flex; flex-wrap: wrap; gap: var(--sp-2) var(--sp-4); }
	.sub-title { font: 500 var(--text-base)/1.3 var(--font-display); margin-top: var(--sp-5); }
</style>
