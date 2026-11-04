<!--
  DataTable.svelte: the system's sortable table (nettap-design-system/components/DataTable).
  - Every column sorts (header buttons, aria-sort). Sorting uses utils/table-sort.
  - With `onsortchange` the table is server-sorted: it reports the new sort and shows it,
    but keeps `rows` in the order given.
  - With `onrowactivate` the first cell holds a real <button> (named by `rowLabel`), so Tab,
    Enter and Space work. A click elsewhere on the row is forwarded to it, except from a
    nested control or while text is selected (PLAN.md §5.3). The first column's cell must
    not hold links or buttons of its own, because they would sit inside that button.
  - `selectedKey` marks the row whose details are open with aria-current="true", the
    AlertRow convention; aria-selected only means something inside a grid widget.
-->
<script module lang="ts">
	import type { Snippet } from 'svelte';

	export interface Column<T> {
		key: string;
		label: string;
		numeric?: boolean;
		/** Defaults to row[key]. */
		sortValue?: (row: T) => unknown;
		/** Defaults to row[key] as text. */
		cell?: Snippet<[T]>;
		/** Added to the column's th and td. */
		class?: string;
		/** Hover text on the header, such as a field's description. */
		title?: string;
	}

	export interface TablePager {
		page: number;
		pageCount: number;
		total: number;
		from: number;
		to: number;
		onpage: (page: number) => void;
	}
</script>

<script lang="ts" generics="T">
	import { untrack } from 'svelte';
	import Icon from './Icon.svelte';
	import { TableSort, type SortDir } from '$lib/utils/table-sort.svelte';

	interface Props {
		columns: Column<T>[];
		rows: readonly T[];
		ariaLabel: string;
		rowKey: (row: T) => string | number;
		initialSort?: { key: string; dir: SortDir };
		onsortchange?: (key: string, dir: SortDir) => void;
		onrowactivate?: (row: T) => void;
		/** The activation button's accessible name: "Open connection from Kitchen iPad". */
		rowLabel?: (row: T) => string;
		selectedKey?: string | number;
		pager?: TablePager;
		/** Shown in a full-width row when there are no rows. */
		empty?: Snippet;
	}

	let {
		columns,
		rows,
		ariaLabel,
		rowKey,
		initialSort,
		onsortchange,
		onrowactivate,
		rowLabel,
		selectedKey,
		pager,
		empty,
	}: Props = $props();

	// '' = unsorted: rows keep the order they arrived in until a header is clicked
	const sort = new TableSort<string>(untrack(() => initialSort?.key ?? ''), untrack(() => initialSort?.dir ?? 'desc'));

	const raw = (row: T, key: string): unknown => (row as Record<string, unknown>)[key];
	const sortValue = (row: T, key: string): unknown => {
		const column = columns.find((c) => c.key === key);
		return column?.sortValue ? column.sortValue(row) : raw(row, key);
	};

	const shown = $derived(onsortchange || !sort.key ? rows : sort.apply(rows, sortValue));

	function toggle(key: string) {
		sort.toggle(key);
		onsortchange?.(sort.key, sort.dir);
	}

	function ariaSort(key: string): 'ascending' | 'descending' | 'none' {
		if (sort.key !== key) return 'none';
		return sort.dir === 'asc' ? 'ascending' : 'descending';
	}

	const NESTED = 'a, button, input, select, textarea, label, [role=button], [role=link], [tabindex]';

	function forwardRowClick(event: MouseEvent) {
		const row = event.currentTarget as HTMLTableRowElement;
		const target = event.target as Element;
		const button = row.querySelector<HTMLButtonElement>('.row-btn');
		// The activation button is itself a nested button, so its own clicks (and the
		// forwarded one) stop here too
		const nested = target.closest(NESTED);
		if (event.defaultPrevented || !button || (nested && row.contains(nested))) return;
		if (window.getSelection()?.toString()) return;
		button.click();
	}

	const PAGE_WINDOW = 5;
	const pages = $derived.by(() => {
		if (!pager) return [];
		const count = Math.max(1, pager.pageCount);
		const start = Math.min(Math.max(1, pager.page - 2), Math.max(1, count - PAGE_WINDOW + 1));
		return Array.from({ length: Math.min(PAGE_WINDOW, count) }, (_, i) => start + i);
	});

	const fmt = (n: number) => n.toLocaleString('en-GB');
</script>

{#snippet content(column: Column<T>, row: T)}
	{#if column.cell}{@render column.cell(row)}{:else}{raw(row, column.key) ?? ''}{/if}
{/snippet}

<div class="tbl-wrap">
	<table aria-label={ariaLabel}>
		<thead>
			<tr>
				{#each columns as column (column.key)}
					<th scope="col" class={[column.numeric && 'num', column.class]} aria-sort={ariaSort(column.key)}>
						<button class="th-btn" type="button" title={column.title} onclick={() => toggle(column.key)}
							>{column.label}<Icon name="sort" class="s-none" /><Icon name="chevdown" class="s-dir" /></button
						>
					</th>
				{/each}
			</tr>
		</thead>
		<tbody>
			{#each shown as row (rowKey(row))}
				{@const current = selectedKey !== undefined && rowKey(row) === selectedKey ? 'true' : undefined}
				<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
				<!-- The keyboard path is the row's own button; this only widens the mouse target -->
				<tr
					class={[onrowactivate && 'is-activatable']}
					aria-current={current}
					onclick={onrowactivate ? forwardRowClick : undefined}
				>
					{#each columns as column, i (column.key)}
						<td class={[column.numeric && 'num', column.class]}>
							{#if i === 0 && onrowactivate}
								<button
									class="row-btn"
									type="button"
									aria-label={rowLabel?.(row)}
									aria-current={current}
									onclick={() => onrowactivate?.(row)}>{@render content(column, row)}</button
								>
							{:else}
								{@render content(column, row)}
							{/if}
						</td>
					{/each}
				</tr>
			{:else}
				{#if empty}
					<tr><td colspan={columns.length}>{@render empty()}</td></tr>
				{/if}
			{/each}
		</tbody>
	</table>
</div>

{#if pager}
	{@const pg = pager}
	<div class="tbl-foot">
		<span>Showing {fmt(pg.from)} to {fmt(pg.to)} of {fmt(pg.total)}</span>
		<div class="pager" role="group" aria-label="Pages">
			<button type="button" aria-label="Previous page" disabled={pg.page <= 1} onclick={() => pg.onpage(pg.page - 1)}
				><Icon name="back" /></button
			>
			{#each pages as p (p)}
				<button
					type="button"
					aria-label="Page {p}"
					aria-current={p === pg.page ? 'page' : undefined}
					onclick={() => pg.onpage(p)}>{p}</button
				>
			{/each}
			<button
				type="button"
				aria-label="Next page"
				disabled={pg.page >= pg.pageCount}
				onclick={() => pg.onpage(pg.page + 1)}><Icon name="back" class="chev" /></button
			>
		</div>
	</div>
{/if}

<style>
	/* Layout glue the system lacks: the row's activation button looks like its cell text */
	.row-btn { all: unset; display: inline-block; max-width: 100%; cursor: pointer; }
	.row-btn:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; border-radius: var(--r-xs); }
	tr.is-activatable { cursor: pointer; }
	/* The open row: the same surface-2 step as a selected AlertRow (bundle.css:357) */
	tr[aria-current='true'] td { background: var(--surface-2); }
	.pager button:disabled { cursor: default; color: var(--text-3); }
</style>
