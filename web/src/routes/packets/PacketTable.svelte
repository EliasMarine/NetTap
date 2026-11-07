<!--
  PacketTable.svelte: the search's packets (NET-188, Main.dc "Packets"). Sorted over every row
  before a page is cut. "What happened" is describePacket's sentence with TShark's Info under it,
  or the Info line alone when the packet isn't unambiguous. All of it renders as text.
-->
<script lang="ts">
	import type { PacketRow } from '$lib/api/packets';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import { describePacket } from '$lib/utils/packet-describe';
	import { sortRows, type SortDir } from '$lib/utils/table-sort.svelte';
	import { sourceOf } from '$lib/utils/packet-stats';
	import { addressName, clockTime, destinationOf, dstPortOf, sinceFirst } from './packets-view';

	interface Props {
		rows: readonly PacketRow[];
		firstT: string;
		devices: ReadonlyMap<string, string>;
		sites: ReadonlyMap<string, string>;
		selected: number | null;
		onopen: (row: PacketRow) => void;
	}

	let { rows, firstT, devices, sites, selected, onopen }: Props = $props();

	const PAGE_SIZE = 50;
	let page = $state(1);
	let sortKey = $state('n');
	let sortDir = $state<SortDir>('asc');

	interface Line {
		row: PacketRow;
		from: string;
		to: string;
		sentence: string | null;
	}

	// A device's own name first, then the site its Client Hello named (as addressName does)
	const named = $derived(new Map([...sites, ...devices]));

	const lines = $derived(
		rows.map((row): Line => {
			const dst = destinationOf(row);
			const port = dstPortOf(row);
			return {
				row,
				from: addressName(sourceOf(row), devices, sites),
				to: `${addressName(dst, devices, sites)}${port ? `:${port}` : ''}`,
				sentence: describePacket(row, named),
			};
		}),
	);

	const SORT: Record<string, (l: Line) => unknown> = {
		n: (l) => l.row.n,
		// Frame numbers run in time order, exactly; the time text as a float would round
		time: (l) => l.row.n,
		from: (l) => l.from,
		kind: (l) => l.row.protocol,
		size: (l) => l.row.len,
		what: (l) => l.sentence ?? l.row.info,
	};

	const sorted = $derived(sortRows(lines, SORT[sortKey] ?? SORT.n, sortDir));
	const pageCount = $derived(Math.max(1, Math.ceil(sorted.length / PAGE_SIZE)));
	const current = $derived(Math.min(page, pageCount));
	const shown = $derived(sorted.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE));

	const columns: Column<Line>[] = [
		{ key: 'n', label: 'No.', numeric: true, cell: nCell },
		{ key: 'time', label: 'Time', cell: timeCell },
		{ key: 'from', label: 'Sent by', cell: fromCell },
		{ key: 'kind', label: 'Kind', cell: kindCell },
		{ key: 'size', label: 'Size', numeric: true, cell: sizeCell },
		{ key: 'what', label: 'What happened', cell: whatCell },
	];

	function changeSort(key: string, dir: SortDir) {
		sortKey = key;
		sortDir = dir;
		page = 1;
	}
</script>

{#snippet nCell(l: Line)}{l.row.n.toLocaleString('en-GB')}{/snippet}
{#snippet timeCell(l: Line)}
	<span class="two"><span class="mono">{clockTime(l.row.t)}</span><small>{sinceFirst(l.row.t, firstT)}</small></span>
{/snippet}
{#snippet fromCell(l: Line)}
	<span class="two"><span class="name">{l.from}</span><small class="to">to {l.to}</small></span>
{/snippet}
{#snippet kindCell(l: Line)}<span class="tag">{l.row.protocol}</span>{/snippet}
{#snippet sizeCell(l: Line)}{l.row.len.toLocaleString('en-GB')} B{/snippet}
{#snippet whatCell(l: Line)}
	{#if l.sentence}
		<span class="two what"><b>{l.sentence}</b><small class="mono info">{l.row.info}</small></span>
	{:else}
		<span class="mono info what">{l.row.info}</span>
	{/if}
{/snippet}

<DataTable
	{columns}
	rows={shown}
	ariaLabel="Packets"
	rowKey={(l) => l.row.n}
	initialSort={{ key: sortKey, dir: sortDir }}
	onsortchange={changeSort}
	onrowactivate={(l) => onopen(l.row)}
	rowLabel={(l) => `Open packet ${l.row.n}`}
	selectedKey={selected ?? undefined}
	pager={pageCount > 1
		? { page: current, pageCount, total: sorted.length, from: (current - 1) * PAGE_SIZE + 1, to: (current - 1) * PAGE_SIZE + shown.length, onpage: (p) => (page = p) }
		: undefined}
/>

<style>
	/* Layout glue: a main line with a small second line */
	.two { display: inline-flex; flex-direction: column; line-height: 1.3; min-width: 0; }
	small { color: var(--text-3); font-size: var(--text-xs); }
	.name, .info { overflow-wrap: anywhere; }
	.info { font-size: var(--text-xs); }
	/* Table cells don't wrap (system.css); the "to" line and What happened do, so a docked
	   drawer doesn't push them off the card, as on PCAP Search. Names stay on one line. */
	.to, .what { white-space: normal; }
	.what { min-width: 10rem; overflow-wrap: anywhere; }
	b { font-weight: 600; }
</style>
