<!--
  ChangelogTable.svelte (NET-272): the events with what each device did over the loaded range.
  Every column sorts both ways and an empty ("—") cell sorts last. A row opens its details
  (`onactivate`); its first cell holds DataTable's row button, so it has no links of its own.
-->
<script lang="ts">
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Bytes from '$lib/components/ui/Bytes.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { formatBytes } from '$lib/api/logs';
	import { fmt } from '$lib/utils/drilldown';
	import { formatTime } from '$lib/utils/time';
	import { eventIcons, eventLabels, MISSING_TEXT, spanText, type ChangelogRow } from './changelog-rows';

	interface Props {
		rows: readonly ChangelogRow[];
		selectedId: string | null;
		onactivate: (row: ChangelogRow) => void;
	}

	let { rows, selectedId, onactivate }: Props = $props();

	const label = (r: ChangelogRow) => eventLabels[r.event.event_type] ?? r.event.event_type;
	const what = (r: ChangelogRow) => (r.kind === 'device' ? r.name : r.event.title);
	const ms = (iso: string | null) => (iso ? Date.parse(iso) : null);
	const maxSent = $derived(Math.max(0, ...rows.map((r) => r.sent ?? 0)));
	const maxReceived = $derived(Math.max(0, ...rows.map((r) => r.received ?? 0)));

	const columns: Column<ChangelogRow>[] = [
		{ key: 'when', label: 'When', sortValue: (r) => r.t, cell: whenCell },
		{ key: 'event', label: 'Event', sortValue: label, cell: eventCell },
		{ key: 'what', label: 'What', sortValue: what, cell: whatCell },
		{ key: 'eventIp', label: 'IP (joined at)', cell: ipCell, title: 'The address the device joined at, from the event' },
		{ key: 'firstSeen', label: 'First seen', sortValue: (r) => ms(r.firstSeen), cell: firstCell },
		{ key: 'lastSeen', label: 'Last seen', sortValue: (r) => ms(r.lastSeen), cell: lastCell, title: 'Last seen in this range' },
		{ key: 'spanMs', label: 'Seen over', numeric: true, cell: spanCell, title: 'From the first to the last record in this range, gaps included' },
		{ key: 'sent', label: 'Sent', numeric: true, cell: sentCell },
		{ key: 'received', label: 'Received', numeric: true, cell: receivedCell },
		{ key: 'connections', label: 'Connections', numeric: true, cell: connectionsCell },
	];
</script>

{#snippet none(r: ChangelogRow)}<span class="dim" title={r.missing ? MISSING_TEXT[r.missing] : undefined}>—</span>{/snippet}
{#snippet whenCell(r: ChangelogRow)}<time class="num" datetime={r.event['@timestamp']}>{formatTime(r.event['@timestamp'], 'short')}</time>{/snippet}
{#snippet eventCell(r: ChangelogRow)}<span class="ev"><Icon name={eventIcons[r.event.event_type] ?? 'changelog'} />{label(r)}</span>{/snippet}
{#snippet whatCell(r: ChangelogRow)}
	{#if r.kind === 'device'}
		<span class="what">{r.name}{#if r.mac && r.name !== r.mac}<span class="mono dim">{r.mac}</span>{/if}</span>
	{:else}
		<span class="what">{r.event.title}</span>
	{/if}
{/snippet}
{#snippet ipCell(r: ChangelogRow)}{#if r.eventIp}<span class="mono">{r.eventIp}</span>{:else}{@render none(r)}{/if}{/snippet}
{#snippet firstCell(r: ChangelogRow)}{#if r.firstSeen}<span class="num">{formatTime(r.firstSeen, 'short')}</span>{:else}{@render none(r)}{/if}{/snippet}
{#snippet lastCell(r: ChangelogRow)}{#if r.lastSeen}<span class="num">{formatTime(r.lastSeen, 'short')}</span>{:else}{@render none(r)}{/if}{/snippet}
{#snippet spanCell(r: ChangelogRow)}{#if r.spanMs !== null}{spanText(r.spanMs)}{:else}{@render none(r)}{/if}{/snippet}
{#snippet sentCell(r: ChangelogRow)}{#if r.sent !== null}<Bytes value={r.sent} max={maxSent} display={formatBytes(r.sent)} />{:else}{@render none(r)}{/if}{/snippet}
{#snippet receivedCell(r: ChangelogRow)}{#if r.received !== null}<Bytes value={r.received} max={maxReceived} display={formatBytes(r.received)} />{:else}{@render none(r)}{/if}{/snippet}
{#snippet connectionsCell(r: ChangelogRow)}{#if r.connections !== null}{fmt(r.connections)}{:else}{@render none(r)}{/if}{/snippet}

<DataTable
	ariaLabel="Changelog events"
	{rows}
	{columns}
	rowKey={(r) => r.id}
	initialSort={{ key: 'when', dir: 'desc' }}
	onrowactivate={onactivate}
	rowLabel={(r) => `Open details: ${what(r) ?? label(r)}, ${formatTime(r.event['@timestamp'], 'short')}`}
	selectedKey={selectedId ?? undefined}
/>

<style>
	/* Layout glue the system lacks: the event type's icon beside its label, and a name over its MAC */
	.ev { display: inline-flex; align-items: center; gap: var(--sp-2); white-space: nowrap; }
	.what { display: inline-flex; flex-direction: column; gap: var(--sp-1); overflow-wrap: anywhere; }
	.what .mono { font-size: var(--text-xs); }
</style>
