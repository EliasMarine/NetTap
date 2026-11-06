<!--
  NetworkFlowTable: the Network flow as a table, for narrow cards and for figures that don't
  add up (NetworkFlow.svelte picks it). One tab per column; every column sorts. The table has
  no row activation (DataTable would make every row a button, Other included): the Name cell
  holds a real button for rows that do something, and plain text for Other.
-->
<script lang="ts">
	import Pills from './ui/Pills.svelte';
	import DataTable, { type Column } from './ui/DataTable.svelte';
	import { formatBytes } from '$api/logs';
	import { share, splitText, type FlowData, type FlowEntry, type FlowKind } from './ui/charts/flow';

	type Tab = 'sources' | 'protocols' | 'destinations';

	let {
		data,
		names,
		isPressed,
		onNodeClick,
	}: {
		data: FlowData;
		names: Map<string, string>;
		isPressed: (kind: FlowKind, id: string) => boolean;
		onNodeClick?: (kind: FlowKind, id: string) => void;
	} = $props();

	const uid = $props.id();
	const TABS: { value: Tab; label: string }[] = [
		{ value: 'sources', label: 'Devices' },
		{ value: 'protocols', label: 'Protocols' },
		{ value: 'destinations', label: 'Destinations' },
	];
	let tab = $state<Tab>('sources');

	const rows = $derived(data[tab]);
	const total = $derived(rows.reduce((a, r) => a + r.value, 0));
	const max = $derived(Math.max(0, ...rows.map((r) => r.value)));
	const nameOf = (row: FlowEntry) => (row.kind === 'source' ? (names.get(row.id) ?? row.id) : row.label);

	function sub(row: FlowEntry): string {
		if (row.other) return 'Everywhere outside the top 10';
		if (row.kind === 'source') return names.has(row.id) ? row.id : '';
		return row.country ?? '';
	}

	const columns: Column<FlowEntry>[] = [
		{ key: 'name', label: 'Name', sortValue: (r) => nameOf(r).toLowerCase(), cell: nameCell, class: 'flow-name' },
		{ key: 'value', label: 'Data', numeric: true, cell: dataCell },
		{ key: 'share', label: 'Share', numeric: true, sortValue: (r) => r.value, cell: shareCell },
	];
</script>

{#snippet nameCell(row: FlowEntry)}
	<div class="nm">
		{#if row.other}
			<span class="nm-main other">{row.label}</span>
		{:else}
			<button
				type="button"
				class="nm-main"
				class:mono={row.kind === 'source' && !names.has(row.id)}
				aria-pressed={row.kind === 'source' ? undefined : isPressed(row.kind, row.id)}
				onclick={() => onNodeClick?.(row.kind, row.id)}>{nameOf(row)}</button
			>
		{/if}
		{#if sub(row)}<span class="nm-sub" class:mono={row.kind === 'source'}>{sub(row)}</span>{/if}
		<span class="split" aria-hidden="true" style:--w="{max > 0 ? (row.value / max) * 100 : 0}%">
			{#each row.split as s (s.protocol)}
				<span class="c-d{data.colours.get(s.protocol) ?? 5}" style:flex-grow={s.value}></span>
			{/each}
		</span>
		{#if row.kind !== 'protocol'}<span class="sr-only">{splitText(row, data.protocols)}</span>{/if}
	</div>
{/snippet}

{#snippet dataCell(row: FlowEntry)}{formatBytes(row.value)}{/snippet}
{#snippet shareCell(row: FlowEntry)}{share(row.value, total)}{/snippet}

<div class="flow-table">
	<Pills mode="tabs" idPrefix={uid} ariaLabel="Network flow column" options={TABS} value={tab} onchange={(v) => (tab = v)} />
	<div role="tabpanel" id="{uid}-panel-{tab}" aria-labelledby="{uid}-tab-{tab}">
		<DataTable
			{columns}
			{rows}
			ariaLabel="Network flow: {TABS.find((t) => t.value === tab)?.label}"
			rowKey={(r) => r.id}
			initialSort={{ key: 'value', dir: 'desc' }}
		/>
	</div>
</div>

<style>
	.flow-table {
		display: flex;
		flex-direction: column;
		gap: var(--sp-3);
	}
	/* The name column takes the room left by Data and Share, and its text ellipsises on phones */
	.flow-table :global(td.flow-name) {
		width: 100%;
		max-width: 0;
	}
	.nm {
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
		min-width: 0;
	}
	.nm-main {
		align-self: flex-start;
		max-width: 100%;
		padding: 0;
		border: 0;
		background: none;
		color: var(--text-1);
		font-weight: 600;
		text-align: left;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		cursor: pointer;
	}
	.nm-main[aria-pressed='true'] {
		color: var(--accent-strong);
	}
	.nm-main.other {
		color: var(--text-3);
		cursor: default;
	}
	.nm-sub {
		font-size: var(--text-micro);
		color: var(--text-3);
	}
	.split {
		display: flex;
		width: var(--w);
		height: var(--sp-1);
		border-radius: var(--r-pill);
		overflow: hidden;
	}
	.split > span {
		flex-basis: 0;
		background: var(--c);
	}
</style>
