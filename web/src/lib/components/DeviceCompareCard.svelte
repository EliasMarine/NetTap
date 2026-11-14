<!--
  DeviceCompareCard: the connections one device started in two equal periods, by destination
  (NET-265). It asks only when Compare is pressed; the page's own loader never runs it.
  NET-269: the MAC page passes the device's `ips`; the card compares one of them and says which.
-->
<script lang="ts">
	import { getDeviceCompare, type CompareChange, type CompareDestination, type DeviceCompareResponse } from '$api/device-compare';
	import { COMPARE_LENGTHS, COMPARE_SCOPE, compareSummary, defaultStarts, lengthMs, periods, periodWords, type CompareLength } from '$lib/utils/device-compare';
	import { formatBytes } from '$lib/api/logs';
	import IPAddress from '$components/IPAddress.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { untrack } from 'svelte';

	// OLD CODE: let { ip }: { ip: string } = $props(); (NET-269: the MAC page passes every address it has used)
	let { ip, ips = [] }: { ip: string; ips?: string[] } = $props();

	/** The owner's pick from `ips`; a refresh that drops it falls back to the page's default `ip`. */
	let picked = $state<string | null>(null);
	const address = $derived(picked !== null && ips.includes(picked) ? picked : ip);

	let length = $state<CompareLength>('24h');
	const starts = defaultStarts(lengthMs('24h'), Date.now());
	let aStart = $state(starts.a);
	let bStart = $state(starts.b);
	let result = $state.raw<DeviceCompareResponse | null>(null);
	let loading = $state(false);
	let error = $state<string | null>(null);

	/** A result on screen always belongs to the inputs on screen. */
	function clear() {
		result = null;
		error = null;
	}

	function resetStarts() {
		const d = defaultStarts(lengthMs(length), Date.now());
		aStart = d.a;
		bStart = d.b;
		clear();
	}

	// a result or error on screen is for the address on screen
	$effect(() => {
		void address;
		untrack(clear);
	});

	async function run() {
		if (loading) return;
		// OLD CODE: const query = periods(ip, aStart, bStart, lengthMs(length)); (NET-269: the address picked)
		const asked = address;
		const query = periods(asked, aStart, bStart, lengthMs(length));
		if (!query) {
			error = 'Pick when each period starts.';
			result = null;
			return;
		}
		// one at a time: the controls are off while it runs, and the page keys this card by device
		loading = true;
		error = null;
		// OLD CODE START — NET-269: a reply for an address the card no longer shows was kept
		// try {
		// 	result = await getDeviceCompare(query);
		// } catch (e) {
		// 	result = null;
		// 	error = e instanceof Error ? e.message : String(e);
		// } finally {
		// OLD CODE END
		try {
			const reply = await getDeviceCompare(query);
			if (asked === address) result = reply;
		} catch (e) {
			if (asked === address) {
				result = null;
				error = e instanceof Error ? e.message : String(e);
			}
		} finally {
			loading = false;
		}
	}

	const destColumn = { key: 'ip', label: 'Destination', cell: destCell } satisfies Column<CompareDestination>;
	const newColumns: Column<CompareDestination>[] = [destColumn, { key: 'bytes', label: 'Second period', numeric: true, cell: bytesCell }];
	const goneColumns: Column<CompareDestination>[] = [destColumn, { key: 'bytes', label: 'First period', numeric: true, cell: bytesCell }];
	const changeColumns: Column<CompareChange>[] = [
		{ key: 'ip', label: 'Destination', cell: destCell },
		{ key: 'a_bytes', label: 'First period', numeric: true, cell: aCell },
		{ key: 'b_bytes', label: 'Second period', numeric: true, cell: bCell },
		{ key: 'delta', label: 'Change', numeric: true, cell: deltaCell },
	];
	// OLD CODE: const shown = $derived(result?.ip === ip ? result : null);
	const shown = $derived(result?.ip === address ? result : null);
	const quiet = $derived(shown !== null && shown.a.total_bytes === 0 && shown.b.total_bytes === 0 && shown.a.destinations === 0 && shown.b.destinations === 0);
</script>

{#snippet destCell(r: { ip: string; org: string | null })}
	<span class="dest"><span class="mono"><IPAddress ip={r.ip} /></span>{#if r.org}<span class="dim org">{r.org}</span>{/if}</span>
{/snippet}
{#snippet bytesCell(r: CompareDestination)}{formatBytes(r.bytes)}{/snippet}
{#snippet aCell(r: CompareChange)}{formatBytes(r.a_bytes)}{/snippet}
{#snippet bCell(r: CompareChange)}{formatBytes(r.b_bytes)}{/snippet}
{#snippet deltaCell(r: CompareChange)}
	<span class="delta"><Icon name={r.delta > 0 ? 'up' : 'down'} />{r.delta > 0 ? '+' : '−'}{formatBytes(Math.abs(r.delta))}</span>
{/snippet}
{#snippet more(list: { total: number; items: unknown[] }, atLeast = false)}
	{#if list.total > list.items.length}<p class="dim more">and {atLeast ? 'at least ' : ''}{(list.total - list.items.length).toLocaleString('en-GB')} more</p>{/if}
{/snippet}

<Card class="c-12" title="Compare periods" sub="Bytes by destination · connections this device started">
	<form class="cmp-form" onsubmit={(e) => { e.preventDefault(); void run(); }}>
		{#if ips.length > 1}
			<div class="field">
				<label class="label" for="cmp-ip">Address</label>
				<select id="cmp-ip" class="select mono" value={address} onchange={(e) => (picked = e.currentTarget.value)} disabled={loading}>
					{#each ips as a (a)}<option value={a}>{a}</option>{/each}
				</select>
			</div>
		{/if}
		<div class="field">
			<label class="label" for="cmp-length">Length</label>
			<select id="cmp-length" class="select" bind:value={length} onchange={resetStarts} disabled={loading}>
				{#each COMPARE_LENGTHS as l (l.value)}<option value={l.value}>{l.label}</option>{/each}
			</select>
		</div>
		<div class="field">
			<label class="label" for="cmp-a">First period starts</label>
			<input id="cmp-a" class="input" type="datetime-local" bind:value={aStart} oninput={clear} disabled={loading} />
		</div>
		<div class="field">
			<label class="label" for="cmp-b">Second period starts</label>
			<input id="cmp-b" class="input" type="datetime-local" bind:value={bStart} oninput={clear} disabled={loading} />
		</div>
		<button class="btn primary" type="submit" disabled={loading}>Compare</button>
	</form>
	<p class="dim scope">{COMPARE_SCOPE}</p>
	{#if ips.length > 0}
		<p class="dim scope">Compares <span class="mono">{address}</span> in both periods. The device's other addresses aren't counted, and this address may have belonged to another device before.</p>
	{/if}

	{#if loading}
		<CardState state="loading" title="Comparing the two periods" />
	{:else if error}
		<CardState state="error" title="Couldn't compare these periods" message={error} />
	{:else if shown}
		<p class="dim periods">First period {periodWords(shown.a.from, shown.a.to)} · second period {periodWords(shown.b.from, shown.b.to)}</p>
		{#if quiet}
			<CardState state="empty" icon="connections" title="This device started no connections in either period." />
		{:else}
			<p class="summary" role="status">{compareSummary(shown)}</p>
			{#if shown.new && shown.gone}
				<div class="lists">
					<section>
						<h3 class="list-title">New in the second period</h3>
						<p class="dim list-sub">Not seen in the first period</p>
						<DataTable ariaLabel="New in the second period" rows={shown.new.items} rowKey={(r) => r.ip} columns={newColumns} initialSort={{ key: 'bytes', dir: 'desc' }}>
							{#snippet empty()}No new destinations{/snippet}
						</DataTable>
						{@render more(shown.new)}
					</section>
					<section>
						<h3 class="list-title">No longer seen</h3>
						<p class="dim list-sub">Seen in the first period, not in the second</p>
						<DataTable ariaLabel="No longer seen" rows={shown.gone.items} rowKey={(r) => r.ip} columns={goneColumns} initialSort={{ key: 'bytes', dir: 'desc' }}>
							{#snippet empty()}Every destination was seen again{/snippet}
						</DataTable>
						{@render more(shown.gone)}
					</section>
				</div>
			{/if}
			{#if shown.changed}
				{@const title = shown.changed.partial ? 'Largest changes among destinations listed in both periods' : 'Largest changes'}
				<section>
					<h3 class="list-title">{title}</h3>
					<p class="dim list-sub">
						{shown.changed.partial ? 'Some destinations were left off a list, so other changes may be missing' : 'Destinations seen in both periods, by the size of the change'}
					</p>
					<DataTable ariaLabel={title} rows={shown.changed.items} rowKey={(r) => r.ip} columns={changeColumns}>
						{#snippet empty()}No destination seen in both periods changed{/snippet}
					</DataTable>
					{@render more(shown.changed, shown.changed.partial)}
				</section>
			{/if}
		{/if}
	{/if}
</Card>

<style>
	.cmp-form {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(12rem, 100%), 1fr));
		gap: var(--sp-3);
		align-items: end;
	}
	.scope,
	.periods,
	.list-sub,
	.more {
		font-size: var(--text-sm);
		margin: var(--sp-2) 0 0;
	}
	.summary {
		color: var(--text-1);
		margin: var(--sp-4) 0 var(--sp-3);
	}
	.lists {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(20rem, 100%), 1fr));
		gap: var(--sp-4);
		margin-bottom: var(--sp-4);
	}
	.list-title {
		font-size: var(--text-base);
		color: var(--text-1);
		margin: 0;
	}
	.list-sub {
		margin: 0 0 var(--sp-2);
	}
	.dest {
		display: inline-flex;
		flex-direction: column;
		min-width: 0;
	}
	.org {
		font-size: var(--text-xs);
	}
	.delta {
		display: inline-flex;
		align-items: center;
		gap: var(--sp-1);
	}
</style>
