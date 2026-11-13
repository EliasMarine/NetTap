<script lang="ts">
	/**
	 * DHCP lease timeline (NET-263): every DHCP transaction NetTap saw for one device, from Zeek's
	 * dhcp.log (/api/dhcp/timeline). The device is `?mac=` in the URL; the window is the standard
	 * range pills, or a link's exact `?from=&to=` as Custom. Each row says in plain English what
	 * was observed (dhcp-summary.ts), never an order of events.
	 */
	import { onDestroy, onMount, untrack } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { getDhcpTimeline, type DhcpTimeline, type DhcpTransaction } from '$lib/api/dhcp-timeline';
	import { HttpError } from '$lib/api/drilldown';
	import { getRegistryDevices, type RegistryDevice } from '$lib/api/devices-registry';
	import { outcome, registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import { customRange, DRILL_RANGES, rangeWindow, startRange } from '$lib/utils/drilldown';
	import { loadFailed } from '$lib/utils/load-failed';
	import { formatTime } from '$lib/utils/time';
	import IPAddress from '$components/IPAddress.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import { deviceName, leaseWords, messagesText, OUTCOME, packetsHref, pickedMac, summary } from './dhcp-summary';

	const CHECK_DAEMON = 'Check that NetTap is running on the System page, then try again.';

	const params = $derived($page.url.searchParams);
	const mac = $derived(params.get('mac')?.trim() ?? '');
	const custom = $derived(customRange(params.get('from'), params.get('to')));
	const baseRange = $derived(DRILL_RANGES.find((r) => r.value === params.get('range')) ?? DRILL_RANGES.find((r) => r.value === startRange('24h'))!);
	const range = $derived(custom ?? baseRange);
	const view = $derived(`${mac}|${baseRange.value}|${custom?.from ?? ''}|${custom?.to ?? ''}`);

	/** The reply on screen, with the window words it answers. */
	let loaded = $state<{ data: DhcpTimeline; words: string } | null>(null);
	let failure = $state<string | null>(null);
	/** The daemon said the MAC is wrong (a 400): no retry, the message says what to fix */
	let badInput = $state(false);
	/** The view of the reply on screen (not reactive: only the loader reads it) */
	let loadedView = '';
	let devices = $state<RegistryDevice[]>([]);
	let devicesFailed = $state(false);
	let typed = $state('');

	const data = $derived(loaded?.data ?? null);
	const words = $derived(loaded?.words ?? range.words);
	const name = $derived(data ? deviceName(data.mac, devices, data.transactions) : null);

	const refresh = registerPageRefresh(load);
	onDestroy(refresh.unregister);
	// OLD CODE START — PR #263 review: a range pill also threw away what was typed
	// $effect(() => {
	// 	void view; // another device or window
	// 	untrack(() => {
	// 		typed = mac;
	// 		void refresh.run();
	// 	});
	// });
	// OLD CODE END
	$effect(() => {
		typed = mac; // only when the URL's device changes
	});
	$effect(() => {
		void view; // another device or window
		untrack(() => void refresh.run());
	});
	onMount(() => {
		// suggestions and names only: without them a typed MAC still works
		getRegistryDevices({ limit: 500 }).then(
			(r) => (devices = r.devices),
			() => (devicesFailed = true),
		);
	});

	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const [m, r, v] = [mac, range, view];
		if (v !== loadedView) {
			loaded = null;
			failure = null;
			badInput = false;
			loadedView = '';
		}
		if (!m) return 'skipped';
		const win = custom ? { from: custom.from, to: custom.to } : rangeWindow(r.hours);
		const results = await Promise.allSettled([getDhcpTimeline({ mac: m, ...win })]);
		if (!guard.current(g)) return 'skipped';
		const [res] = results;
		if (res.status === 'fulfilled') {
			loaded = { data: res.value, words: r.words };
			loadedView = v;
			failure = null;
			badInput = false;
		} else {
			// OLD CODE: failure = res.reason instanceof Error ? res.reason.message : ''; (PR #263 review: '' read as still loading)
			failure = res.reason instanceof Error && res.reason.message ? res.reason.message : CHECK_DAEMON;
			badInput = res.reason instanceof HttpError && res.reason.status === 400;
		}
		return outcome(results);
	}

	function urlFor(next: { mac?: string; range?: string }): string {
		const q = new URLSearchParams({ mac: next.mac ?? mac, range: next.range ?? baseRange.value });
		// a range pill ends a link's exact window; another device keeps it
		if (custom && !next.range) {
			q.set('from', custom.from);
			q.set('to', custom.to);
		}
		return `${$page.url.pathname}?${q.toString()}`;
	}
	function pickRange(value: string) {
		if (value !== 'custom') void goto(urlFor({ range: value }), { replaceState: true, keepFocus: true, noScroll: true });
	}
	function show(e: SubmitEvent) {
		e.preventDefault();
		const picked = pickedMac(typed, devices);
		// the same device again: the URL can't change, so load it again here
		if (picked === mac) void refresh.run();
		else if (picked) void goto(urlFor({ mac: picked }), { keepFocus: true, noScroll: true });
	}

	type Row = DhcpTransaction & { key: number };
	const rows = $derived((data?.transactions ?? []).map((t, i): Row => ({ ...t, key: i })));
	const columns: Column<Row>[] = [
		{ key: 'ts', label: 'Time', sortValue: (t) => Date.parse(t.ts) || 0, cell: timeCell },
		{ key: 'outcome', label: 'Outcome', sortValue: (t) => OUTCOME[t.outcome].label, cell: outcomeCell },
		{ key: 'summary', label: 'What NetTap saw', sortValue: summary, cell: summaryCell },
		{ key: 'messages', label: 'Messages seen', title: 'Zeek records which message types it saw, not their order', sortValue: messagesText, cell: messagesCell },
		{ key: 'requested_ip', label: 'Requested', sortValue: (t) => t.requested_ip ?? '', cell: requestedCell },
		{ key: 'assigned_ip', label: 'Assigned', sortValue: (t) => t.assigned_ip ?? '', cell: assignedCell },
		// OLD CODE: label: 'Servers', (PR #263 review: the addresses that appeared, not who served)
		{ key: 'server_endpoints', label: 'Server endpoints', sortValue: (t) => t.server_endpoints.join(' '), cell: serversCell },
	];
	const emptyTitle = $derived(`No DHCP messages from this device in the ${words}`);
</script>

{#snippet timeCell(t: Row)}<span class="num">{formatTime(t.ts)}</span>{/snippet}
{#snippet outcomeCell(t: Row)}
	{@const look = OUTCOME[t.outcome]}
	<span class={['chip', look.tone && `is-${look.tone}`]}>{#if look.tone}<Icon name={look.tone === 'ok' ? 'check' : 'warn'} />{/if}{look.label}</span>
{/snippet}
{#snippet summaryCell(t: Row)}
	{@const href = data ? packetsHref(t, data.mac) : null}
	<p class="line">{summary(t)}</p>
	{#if href}<a class="small" {href} aria-label="See the captured packets from {formatTime(t.ts)}">See the captured packets</a><span class="dim small"> Shows which server sent what, if the capture still holds the packets.</span>{/if}
{/snippet}
{#snippet messagesCell(t: Row)}<span class="mono">{messagesText(t)}</span>{/snippet}
{#snippet requestedCell(t: Row)}{#if t.requested_ip}<IPAddress ip={t.requested_ip} />{:else}<span class="dim">—</span>{/if}{/snippet}
{#snippet assignedCell(t: Row)}
	{#if t.assigned_ip}<IPAddress ip={t.assigned_ip} />{:else}<span class="dim">—</span>{/if}
	{#if t.lease_time !== null}<div class="dim small">for {leaseWords(t.lease_time)}</div>{/if}
{/snippet}
{#snippet serversCell(t: Row)}
	{#each t.server_endpoints as ip (ip)}<div><IPAddress {ip} /></div>{:else}<span class="dim">—</span>{/each}
	{#if t.zeek_server && (t.server_endpoints.length !== 1 || t.server_endpoints[0] !== t.zeek_server)}<div class="dim small">Zeek recorded {t.zeek_server}</div>{/if}
{/snippet}

<svelte:head>
	<title>DHCP lease timeline | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<a class="back" href="/tools"><Icon name="back" />Tools</a>
		<h1 class="page-title">DHCP lease timeline</h1>
		<!-- OLD CODE: …, and which servers took part · {words} (PR #263 review: what appeared, not who took part) -->
		<p class="page-sub">Every DHCP transaction NetTap saw for one device: what it asked for, what it was given, and which server addresses appeared · {words}</p>
	</div>
	<div class="head-actions">
		<Pills options={[...DRILL_RANGES, ...(custom ? [custom] : [])].map((r) => ({ value: r.value, label: r.label }))} value={range.value} onchange={pickRange} ariaLabel="Time range" />
	</div>
</div>

<div class="grid">
	<Card class="c-12" title="Device" sub="A name, IP address or MAC address">
		<form class="pick" onsubmit={show}>
			<div class="field">
				<label class="label" for="dhcp-device">Device</label>
				<input id="dhcp-device" class="input mono" list="dhcp-devices" autocomplete="off" placeholder="aa:bb:cc:dd:ee:ff" aria-describedby="dhcp-device-help" bind:value={typed} />
				<datalist id="dhcp-devices">
					{#each devices as d (d.mac)}<option value={d.mac.toLowerCase()}>{d.display_name}{d.ips[0] ? ` · ${d.ips[0]}` : ''}</option>{/each}
				</datalist>
				<span class="field-help" id="dhcp-device-help">
					{devicesFailed ? "Couldn't load your devices for suggestions; type a MAC address instead." : 'Pick a suggestion, or type a MAC address in any common format.'}
				</span>
			</div>
			<div class="form-actions">
				<button class="btn primary" type="submit" disabled={!typed.trim()}><Icon name="search" />Show history</button>
			</div>
		</form>
	</Card>

	<!-- OLD CODE: sub="… Newest first · …" (PR #263 review: the table re-sorts) -->
	<Card class="c-12" title={name ?? 'DHCP transactions'} sub="{data ? `${data.mac} · ` : ''}{words} · message order not recorded">
		{#if !mac}
			<CardState state="empty" icon="devices" title="Pick a device" message="Choose a device or type its MAC address to see its DHCP history." />
		{:else if !data && !failure}
			<CardState state="loading" title="Loading the DHCP history" />
		{:else if !data && badInput}
			<CardState state="error" title={failure ?? ''} message="Check the device or MAC address above, then choose Show history." />
		{:else if !data}
			<CardState state="error" title={loadFailed('the DHCP history')} message={failure ?? CHECK_DAEMON} onaction={() => refresh.run()} />
		{:else}
			{#if failure}<p class="notice is-warn" role="status"><Icon name="warn" /><span>{loadFailed('the DHCP history', true)} {failure}</span></p>{/if}
			{#if rows.length === 0}
				<CardState
					state="empty"
					icon="devices"
					title={emptyTitle}
					message="NetTap saw no DHCP messages from this device in this period. DHCP between a device and its router only reaches NetTap if it crosses the mirrored link. Phones with a private Wi-Fi address use a different MAC on each network."
				/>
			{:else}
				{#if data.truncated}<p class="notice is-warn" role="status"><Icon name="warn" /><span>Showing the newest 200 transactions. Pick a shorter range to see the rest.</span></p>{/if}
				<DataTable {columns} {rows} ariaLabel="DHCP transactions for {name}" rowKey={(t) => t.key} initialSort={{ key: 'ts', dir: 'desc' }} />
			{/if}
		{/if}
	</Card>
</div>

<style>
	/* Layout glue the system lacks */
	.pick { display: flex; flex-wrap: wrap; align-items: flex-end; gap: var(--sp-3); }
	.pick .field { flex: 1 1 var(--sp-8); min-width: 0; }
	.pick .form-actions { margin: 0; }
	.line { margin: 0; color: var(--text-1); }
	.small { font-size: var(--text-sm); }
	.notice { margin-bottom: var(--sp-3); }
</style>
