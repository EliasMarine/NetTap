<!--
  DataTable.svelte: the system's sortable table (nettap-design-system/components/DataTable).
  - Every column sorts (header buttons, aria-sort). Sorting uses utils/table-sort.
  - With `onsortchange` the table is server-sorted: it reports the new sort and shows it,
    but keeps `rows` in the order given.
  - With `onrowactivate` the first cell holds a real <button> (named by `rowLabel`), so Tab,
    Enter and Space work. A click elsewhere on the row is forwarded to it, except from a
    nested control or while text is selected (PLAN.md §5.3). The first column's cell must
    not hold links or buttons of its own, because they would sit inside that button.
    `rowActivatable` leaves out the rows it rejects: no button, no forwarding, a plain row.
  - `selectedKey` marks the row whose details are open with aria-current="true", the
    AlertRow convention; aria-selected only means something inside a grid widget.
  - With `resizeKey` (NET-318) every header has a resize handle (drag, or arrow keys,
    Home, End), the WAI-ARIA window-splitter pattern. The first resize freezes every
    column at its measured width (table-layout: fixed). Widths are saved in this browser
    under the key, and "Reset column widths" goes back to automatic widths.
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
		/** Every page button off, e.g. while the rows on screen are being replaced. */
		disabled?: boolean;
	}
</script>

<script lang="ts" generics="T">
	// OLD CODE: import { untrack } from 'svelte'; (NET-318: resizing measures on mount and after a reset)
	import { onMount, tick, untrack } from 'svelte';
	import Icon from './Icon.svelte';
	import { TableSort, type SortDir } from '$lib/utils/table-sort.svelte';
	import { fmt } from '$lib/utils/drilldown';

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
		/** With `onrowactivate`: false makes that row plain (nothing to open). Every row by default. */
		rowActivatable?: (row: T) => boolean;
		selectedKey?: string | number;
		pager?: TablePager;
		/** Shown in a full-width row when there are no rows. */
		empty?: Snippet;
		/** NET-318: the columns are resizable, and their widths are saved in this browser under this key. */
		resizeKey?: string;
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
		rowActivatable,
		selectedKey,
		pager,
		empty,
		resizeKey,
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

	// OLD CODE: const fmt = (n: number) => n.toLocaleString('en-GB'); (NET-192 PR 4: one fmt, from utils/drilldown)

	// NET-318: resizable columns. 72 px holds the cell padding, MacAddress's 24 px Copy button,
	// its two gaps and the Private tag's padding, so Copy is never clipped.
	const MIN_COL = 72;
	const MAX_COL = 960;
	const STEP = 16;
	const clamp = (width: number) => Math.round(Math.min(MAX_COL, Math.max(MIN_COL, width)));
	const storageKey = $derived(`nettap-col-widths:${resizeKey}`);

	/** null: automatic widths. Once frozen, every column has a clamped width. */
	let widths = $state<Record<string, number> | null>(null);
	/** Header widths in automatic layout, for the handles' aria-valuenow. */
	let measured = $state<Record<string, number>>({});
	const heads: Record<string, HTMLTableCellElement | undefined> = {};
	let drag: { pointerId: number; key: string; startX: number; startWidth: number } | null = null;

	// rounded up: a column frozen half a pixel short of its content shows a stray ellipsis
	const measure = () =>
		Object.fromEntries(columns.map((c) => [c.key, clamp(Math.ceil(heads[c.key]?.getBoundingClientRect().width ?? 0))]));
	const remeasure = () => {
		if (!widths) measured = measure();
	};
	const valueNow = (key: string) => widths?.[key] ?? measured[key] ?? MIN_COL;
	const tableWidth = $derived(widths ? `${Object.values(widths).reduce((sum, w) => sum + w, 0)}px` : undefined);

	/** The frozen widths, freezing every column at its measured (clamped) width first. */
	function freeze(): Record<string, number> {
		widths ??= measure();
		return widths;
	}

	function setWidth(key: string, width: number) {
		widths = { ...freeze(), [key]: clamp(width) };
	}

	function save() {
		try {
			if (widths) localStorage.setItem(storageKey, JSON.stringify(widths));
		} catch {
			// blocked storage: the widths last for this visit
		}
	}

	/** Saved widths, only when they hold a number for every current column. */
	function saved(): Record<string, number> | null {
		try {
			const value: unknown = JSON.parse(localStorage.getItem(storageKey) ?? 'null');
			if (!value || typeof value !== 'object') return null;
			const out: Record<string, number> = {};
			for (const { key } of columns) {
				const width = (value as Record<string, unknown>)[key];
				if (typeof width !== 'number' || !Number.isFinite(width)) return null;
				out[key] = clamp(width);
			}
			return out;
		} catch {
			return null;
		}
	}

	onMount(() => {
		if (!resizeKey) return;
		widths = saved();
		remeasure();
	});

	function startDrag(event: PointerEvent, key: string) {
		// one drag at a time: a second finger or handle is ignored until it ends
		if (drag || !event.isPrimary || event.button !== 0) return;
		event.preventDefault();
		drag = { pointerId: event.pointerId, key, startX: event.clientX, startWidth: freeze()[key] };
		(event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
	}

	function moveDrag(event: PointerEvent) {
		if (!drag || event.pointerId !== drag.pointerId) return;
		setWidth(drag.key, drag.startWidth + event.clientX - drag.startX);
	}

	/** Up, cancel or lost capture: the width reached stays, and is saved. */
	function endDrag(event: PointerEvent) {
		if (!drag || event.pointerId !== drag.pointerId) return;
		drag = null;
		save();
	}

	function keyResize(event: KeyboardEvent, key: string) {
		const step = event.key === 'ArrowLeft' ? -STEP : event.key === 'ArrowRight' ? STEP : 0;
		const target = event.key === 'Home' ? MIN_COL : event.key === 'End' ? MAX_COL : step ? freeze()[key] + step : null;
		if (target === null) return;
		event.preventDefault();
		setWidth(key, target);
		save();
	}

	async function resetWidths() {
		widths = null;
		try {
			localStorage.removeItem(storageKey);
		} catch {
			// blocked storage: nothing was saved
		}
		await tick();
		remeasure();
		// the button is gone now, so focus goes to the first handle rather than the page
		heads[columns[0]?.key]?.querySelector<HTMLElement>('.col-resize')?.focus();
	}
</script>

{#snippet content(column: Column<T>, row: T)}
	{#if column.cell}{@render column.cell(row)}{:else}{raw(row, column.key) ?? ''}{/if}
{/snippet}

<div class="tbl-wrap">
	<!-- OLD CODE: <table aria-label={ariaLabel}> (NET-318: resizable columns) -->
	<table aria-label={ariaLabel} class={[resizeKey && 'has-resize', widths && 'is-resized']} style:width={tableWidth}>
		{#if widths}
			<colgroup>
				{#each columns as column (column.key)}<col style:width="{widths[column.key]}px" />{/each}
			</colgroup>
		{/if}
		<thead>
			<tr>
				{#each columns as column (column.key)}
					<th
						scope="col"
						class={[column.numeric && 'num', column.class]}
						aria-sort={ariaSort(column.key)}
						aria-label={resizeKey ? column.label : undefined}
						bind:this={heads[column.key]}
					>
						<!-- With handles the header names itself: otherwise "Resize … column" joins its name -->
						<button class="th-btn" type="button" title={column.title} onclick={() => toggle(column.key)}
							>{column.label}<Icon name="sort" class="s-none" /><Icon name="chevdown" class="s-dir" /></button
						>
						{#if resizeKey}
							{@const now = valueNow(column.key)}
							<!-- A focusable separator is the WAI-ARIA window splitter, an interactive widget; Svelte lists separator as non-interactive -->
							<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
							<span
								class="col-resize"
								role="separator"
								aria-orientation="vertical"
								aria-label="Resize {column.label} column"
								aria-valuemin={MIN_COL}
								aria-valuemax={MAX_COL}
								aria-valuenow={now}
								aria-valuetext="{now} pixels"
								tabindex="0"
								title="Drag, or use the arrow keys, to resize"
								onpointerdown={(event) => startDrag(event, column.key)}
								onpointermove={moveDrag}
								onpointerup={endDrag}
								onpointercancel={endDrag}
								onlostpointercapture={endDrag}
								onkeydown={(event) => keyResize(event, column.key)}
								onfocus={remeasure}
							></span>
						{/if}
					</th>
				{/each}
			</tr>
		</thead>
		<tbody>
			{#each shown as row (rowKey(row))}
				{@const current = selectedKey !== undefined && rowKey(row) === selectedKey ? 'true' : undefined}
				{@const active = !!onrowactivate && (rowActivatable?.(row) ?? true)}
				<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
				<!-- The keyboard path is the row's own button; this only widens the mouse target -->
				<!-- OLD CODE: class={[onrowactivate && 'is-activatable']} … onclick={onrowactivate ? forwardRowClick : undefined}, and {#if i === 0 && onrowactivate} (slice 2b-2: rowActivatable) -->
				<tr
					class={[active && 'is-activatable']}
					aria-current={current}
					onclick={active ? forwardRowClick : undefined}
				>
					{#each columns as column, i (column.key)}
						<td class={[column.numeric && 'num', column.class]}>
							{#if i === 0 && active}
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
			<button type="button" aria-label="Previous page" disabled={pg.disabled || pg.page <= 1} onclick={() => pg.onpage(pg.page - 1)}
				><Icon name="back" /></button
			>
			{#each pages as p (p)}
				<button
					type="button"
					aria-label="Page {p}"
					aria-current={p === pg.page ? 'page' : undefined}
					disabled={pg.disabled}
					onclick={() => pg.onpage(p)}>{p}</button
				>
			{/each}
			<button
				type="button"
				aria-label="Next page"
				disabled={pg.disabled || pg.page >= pg.pageCount}
				onclick={() => pg.onpage(pg.page + 1)}><Icon name="back" class="chev" /></button
			>
		</div>
	</div>
{/if}

{#if resizeKey && widths}
	<div class="tbl-foot">
		<button type="button" class="btn" onclick={resetWidths}>Reset column widths</button>
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
	/* NET-318: the handle fills the header's right padding only, so it never covers a sort button */
	.has-resize th { position: relative; }
	.col-resize { position: absolute; inset-block: 0; inset-inline-end: 0; width: var(--sp-3); cursor: col-resize; touch-action: none; }
	.col-resize::after { content: ''; position: absolute; inset-block: var(--sp-2); inset-inline-start: 50%; border-inline-start: 1px solid var(--line-strong); }
	.col-resize:hover::after, .col-resize:focus-visible::after { border-color: var(--focus); }
	.col-resize:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; border-radius: var(--r-xs); }
	/* frozen widths: a narrowed cell clips its content, and the row button's ring stays inside it */
	.is-resized { table-layout: fixed; }
	.is-resized th, .is-resized td { overflow: hidden; text-overflow: ellipsis; }
	.is-resized .row-btn:focus-visible { outline-offset: -2px; }
</style>
