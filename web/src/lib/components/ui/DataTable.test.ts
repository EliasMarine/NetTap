import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import DataTable, { type Column, type TablePager } from './DataTable.svelte';

interface Row {
	id: string;
	name: string;
	bytes: number;
	port: number | null;
}

const ROWS: Row[] = [
	{ id: 'a', name: 'Work laptop', bytes: 4800, port: 443 },
	{ id: 'b', name: 'Living-room TV', bytes: 2_410_000_000, port: 80 },
	{ id: 'c', name: 'Kitchen iPad', bytes: 6000, port: null },
];

const COLUMNS: Column<Row>[] = [
	{ key: 'name', label: 'Device' },
	{ key: 'bytes', label: 'Data', numeric: true },
	{ key: 'port', label: 'Port', numeric: true },
];

const rowKey = (row: Row) => row.id;
// render() can't infer a generic component's type parameter, so fix it to Row here
const Table = DataTable<Row>;

/** First-cell text of each body row, top to bottom. */
const order = () =>
	screen
		.getAllByRole('row')
		.slice(1)
		.map((row) => within(row).getAllByRole('cell')[0].textContent?.trim());

const header = (name: string) => screen.getByRole('columnheader', { name });

describe('DataTable rendering', () => {
	it('renders an aria-labelled table in a scroll wrapper with a sort button per column', () => {
		const { container } = render(Table, { columns: COLUMNS, rows: ROWS, ariaLabel: 'Connections', rowKey });
		expect(container.querySelector('.tbl-wrap > table')).toHaveAttribute('aria-label', 'Connections');
		expect(screen.getAllByRole('columnheader')).toHaveLength(3);
		for (const name of ['Device', 'Data', 'Port']) {
			expect(within(header(name)).getByRole('button', { name })).toHaveClass('th-btn');
		}
		expect(header('Data')).toHaveClass('num');
		expect(screen.getAllByRole('cell')[1]).toHaveClass('num');
	});

	it("puts a column's title on its header button", () => {
		const columns: Column<Row>[] = [{ key: 'name', label: 'Device', title: 'The name NetTap knows it by' }, COLUMNS[1]];
		render(Table, { columns, rows: ROWS, ariaLabel: 'Connections', rowKey });
		expect(within(header('Device')).getByRole('button')).toHaveAttribute('title', 'The name NetTap knows it by');
		expect(within(header('Data')).getByRole('button')).not.toHaveAttribute('title');
	});

	it('keeps the given order and marks every column unsorted without an initial sort', () => {
		render(Table, { columns: COLUMNS, rows: ROWS, ariaLabel: 'Connections', rowKey });
		expect(order()).toEqual(['Work laptop', 'Living-room TV', 'Kitchen iPad']);
		for (const name of ['Device', 'Data', 'Port']) expect(header(name)).toHaveAttribute('aria-sort', 'none');
	});

	it('renders a cell snippet and adds a column class to th and td', () => {
		const cell = createRawSnippet<[Row]>((row) => ({ render: () => `<b>${row().name.toUpperCase()}</b>` }));
		render(Table, {
			columns: [{ key: 'name', label: 'Device', cell, class: 'wide' }],
			rows: ROWS,
			ariaLabel: 'Connections',
			rowKey,
		});
		expect(screen.getByText('WORK LAPTOP').tagName).toBe('B');
		expect(header('Device')).toHaveClass('wide');
		expect(screen.getAllByRole('cell')[0]).toHaveClass('wide');
	});

	it('shows the empty snippet across all columns when there are no rows', () => {
		const empty = createRawSnippet(() => ({ render: () => '<p>No connections match.</p>' }));
		render(Table, { columns: COLUMNS, rows: [], ariaLabel: 'Connections', rowKey, empty });
		expect(screen.getByText('No connections match.').closest('td')).toHaveAttribute('colspan', '3');
	});
});

describe('DataTable sorting', () => {
	it('applies the initial sort and shows it with aria-sort', () => {
		render(Table, {
			columns: COLUMNS,
			rows: ROWS,
			ariaLabel: 'Connections',
			rowKey,
			initialSort: { key: 'bytes', dir: 'desc' },
		});
		expect(order()).toEqual(['Living-room TV', 'Kitchen iPad', 'Work laptop']);
		expect(header('Data')).toHaveAttribute('aria-sort', 'descending');
		expect(header('Device')).toHaveAttribute('aria-sort', 'none');
	});

	it('sorts a new column descending, then ascending on the second click', async () => {
		render(Table, { columns: COLUMNS, rows: ROWS, ariaLabel: 'Connections', rowKey });
		const button = screen.getByRole('button', { name: 'Device' });

		await fireEvent.click(button);
		expect(header('Device')).toHaveAttribute('aria-sort', 'descending');
		expect(order()).toEqual(['Work laptop', 'Living-room TV', 'Kitchen iPad']);

		await fireEvent.click(button);
		expect(header('Device')).toHaveAttribute('aria-sort', 'ascending');
		expect(order()).toEqual(['Kitchen iPad', 'Living-room TV', 'Work laptop']);
	});

	it('moves the sort to another column and resets the first to none', async () => {
		render(Table, { columns: COLUMNS, rows: ROWS, ariaLabel: 'Connections', rowKey });
		await fireEvent.click(screen.getByRole('button', { name: 'Device' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Data' }));
		expect(header('Device')).toHaveAttribute('aria-sort', 'none');
		expect(header('Data')).toHaveAttribute('aria-sort', 'descending');
		expect(order()).toEqual(['Living-room TV', 'Kitchen iPad', 'Work laptop']);
	});

	it('puts blank values last in both directions', async () => {
		render(Table, { columns: COLUMNS, rows: ROWS, ariaLabel: 'Connections', rowKey });
		const button = screen.getByRole('button', { name: 'Port' });
		await fireEvent.click(button);
		expect(order()).toEqual(['Work laptop', 'Living-room TV', 'Kitchen iPad']);
		await fireEvent.click(button);
		expect(order()).toEqual(['Living-room TV', 'Work laptop', 'Kitchen iPad']);
	});

	it('sorts by a column sortValue when given', async () => {
		const columns: Column<Row>[] = [{ key: 'name', label: 'Device', sortValue: (row) => row.name.length }];
		render(Table, { columns, rows: ROWS, ariaLabel: 'Connections', rowKey });
		await fireEvent.click(screen.getByRole('button', { name: 'Device' }));
		expect(order()).toEqual(['Living-room TV', 'Kitchen iPad', 'Work laptop']);
	});

	it('in server-sort mode reports each change and leaves the rows in the given order', async () => {
		const onsortchange = vi.fn();
		render(Table, { columns: COLUMNS, rows: ROWS, ariaLabel: 'Connections', rowKey, onsortchange });
		const button = screen.getByRole('button', { name: 'Data' });

		await fireEvent.click(button);
		expect(onsortchange).toHaveBeenLastCalledWith('bytes', 'desc');
		expect(header('Data')).toHaveAttribute('aria-sort', 'descending');
		expect(order()).toEqual(['Work laptop', 'Living-room TV', 'Kitchen iPad']);

		await fireEvent.click(button);
		expect(onsortchange).toHaveBeenLastCalledWith('bytes', 'asc');
		expect(header('Data')).toHaveAttribute('aria-sort', 'ascending');
		expect(order()).toEqual(['Work laptop', 'Living-room TV', 'Kitchen iPad']);
		expect(onsortchange).toHaveBeenCalledTimes(2);
	});
});

describe('DataTable row activation', () => {
	afterEach(() => window.getSelection()?.removeAllRanges());

	/** A table whose Data cell holds a Suppress button, a link and a span that cancels clicks. */
	function renderActivatable(extra: Record<string, unknown> = {}) {
		const onrowactivate = vi.fn();
		const onsuppress = vi.fn();
		const onlink = vi.fn(); // no preventDefault, so only the nested-control rule can stop forwarding
		const cell = createRawSnippet<[Row]>((row) => ({
			render: () =>
				`<span><button type="button">Suppress</button><a href="#pcap">Find in PCAP</a><span data-testid="cancel">${row().bytes}</span></span>`,
			setup: (el) => {
				el.querySelector('button')!.addEventListener('click', onsuppress);
				el.querySelector('a')!.addEventListener('click', onlink);
				el.querySelector('[data-testid="cancel"]')!.addEventListener('click', (e) => e.preventDefault());
			},
		}));
		const columns: Column<Row>[] = [
			{ key: 'name', label: 'Device' },
			{ key: 'bytes', label: 'Data', cell },
			{ key: 'port', label: 'Port' },
		];
		render(Table, {
			columns,
			rows: ROWS,
			ariaLabel: 'Connections',
			rowKey,
			onrowactivate,
			rowLabel: (row: Row) => `Open connection from ${row.name}`,
			...extra,
		});
		return { onrowactivate, onsuppress, onlink };
	}

	const firstRow = () => screen.getAllByRole('row')[1];

	it('puts a real button named by rowLabel in the first cell', () => {
		renderActivatable();
		const button = screen.getByRole('button', { name: 'Open connection from Work laptop' });
		expect(button).toHaveAttribute('type', 'button');
		expect(within(firstRow()).getAllByRole('cell')[0]).toContainElement(button);
	});

	it('activates exactly once when the button is clicked', async () => {
		const { onrowactivate } = renderActivatable();
		await fireEvent.click(screen.getByRole('button', { name: 'Open connection from Work laptop' }));
		expect(onrowactivate).toHaveBeenCalledTimes(1);
		expect(onrowactivate).toHaveBeenCalledWith(ROWS[0]);
	});

	it('activates exactly once from the keyboard', async () => {
		const { onrowactivate } = renderActivatable();
		const button = screen.getByRole('button', { name: 'Open connection from Kitchen iPad' });
		button.focus();
		expect(button).toHaveFocus();
		// A browser turns Enter or Space on a focused button into a click with detail 0
		await fireEvent.keyDown(button, { key: 'Enter' });
		await fireEvent.click(button, { detail: 0 });
		expect(onrowactivate).toHaveBeenCalledTimes(1);
		expect(onrowactivate).toHaveBeenCalledWith(ROWS[2]);
	});

	it('forwards a click elsewhere on the row to the button exactly once', async () => {
		const { onrowactivate } = renderActivatable();
		await fireEvent.click(within(firstRow()).getAllByRole('cell')[2]);
		expect(onrowactivate).toHaveBeenCalledTimes(1);
		expect(onrowactivate).toHaveBeenCalledWith(ROWS[0]);
	});

	it('lets a nested button fire only its own action', async () => {
		const { onrowactivate, onsuppress } = renderActivatable();
		await fireEvent.click(within(firstRow()).getByRole('button', { name: 'Suppress' }));
		expect(onsuppress).toHaveBeenCalledTimes(1);
		expect(onrowactivate).not.toHaveBeenCalled();
	});

	it('lets a nested link fire only its own action', async () => {
		const { onrowactivate, onlink } = renderActivatable();
		await fireEvent.click(within(firstRow()).getByRole('link', { name: 'Find in PCAP' }));
		expect(onlink).toHaveBeenCalledTimes(1);
		expect(onrowactivate).not.toHaveBeenCalled();
	});

	it('does not forward a click whose default was prevented', async () => {
		const { onrowactivate } = renderActivatable();
		await fireEvent.click(within(firstRow()).getByTestId('cancel'));
		expect(onrowactivate).not.toHaveBeenCalled();
	});

	it('does not activate while text in the row is selected', async () => {
		const { onrowactivate } = renderActivatable();
		const cell = within(firstRow()).getAllByRole('cell')[2];
		window.getSelection()!.selectAllChildren(cell);
		expect(window.getSelection()!.toString()).toBe('443');
		await fireEvent.click(cell);
		expect(onrowactivate).not.toHaveBeenCalled();
	});

	it('marks the selected row and its button with aria-current', () => {
		renderActivatable({ selectedKey: 'b' });
		const rows = screen.getAllByRole('row').slice(1);
		expect(rows[1]).toHaveAttribute('aria-current', 'true');
		expect(screen.getByRole('button', { name: 'Open connection from Living-room TV' })).toHaveAttribute(
			'aria-current',
			'true',
		);
		expect(rows[0]).not.toHaveAttribute('aria-current');
	});

	it('leaves a row rowActivatable rejects plain: no button, and a click on it does nothing', async () => {
		const { onrowactivate } = renderActivatable({ rowActivatable: (row: Row) => row.id !== 'b' });
		expect(screen.getByRole('button', { name: 'Open connection from Work laptop' })).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Open connection from Living-room TV' })).not.toBeInTheDocument();
		const plain = screen.getAllByRole('row')[2];
		expect(plain).not.toHaveClass('is-activatable');
		await fireEvent.click(within(plain).getAllByRole('cell')[2]);
		expect(onrowactivate).not.toHaveBeenCalled();
	});

	it('has no activation button or forwarding without onrowactivate', async () => {
		render(Table, { columns: COLUMNS, rows: ROWS, ariaLabel: 'Connections', rowKey });
		expect(screen.getAllByRole('button')).toHaveLength(3); // the three header buttons
	});
});

describe('DataTable pager', () => {
	function renderPager(over: Partial<TablePager> = {}) {
		const onpage = vi.fn();
		const pager: TablePager = { page: 1, pageCount: 13030, total: 182406, from: 1, to: 14, onpage, ...over };
		const { container } = render(Table, { columns: COLUMNS, rows: ROWS, ariaLabel: 'Connections', rowKey, pager });
		return { onpage, container };
	}

	// jsdom still runs a disabled button's click handler (browsers don't), so the page's own guard is tested there
	it('turns every page button off while disabled', () => {
		renderPager({ page: 2, disabled: true });
		const buttons = screen.getAllByRole('button', { name: /^(Page \d+|Previous page|Next page)$/ });
		expect(buttons.length).toBeGreaterThan(2);
		for (const b of buttons) expect(b).toBeDisabled();
	});

	it('shows the range and total in the table foot', () => {
		const { container } = renderPager();
		expect(container.querySelector('.tbl-foot')).toHaveTextContent('Showing 1 to 14 of 182,406');
	});

	it('marks the current page as the light pill and disables Previous on the first page', () => {
		renderPager();
		expect(screen.getByRole('button', { name: 'Page 1' })).toHaveAttribute('aria-current', 'page');
		expect(screen.getByRole('button', { name: 'Page 2' })).not.toHaveAttribute('aria-current');
		expect(screen.getByRole('button', { name: 'Previous page' })).toBeDisabled();
		expect(screen.getByRole('button', { name: 'Next page' })).toBeEnabled();
	});

	it('asks for the next, previous and a numbered page', async () => {
		const { onpage } = renderPager({ page: 5, from: 57, to: 70 });
		await fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
		expect(onpage).toHaveBeenLastCalledWith(6);
		await fireEvent.click(screen.getByRole('button', { name: 'Previous page' }));
		expect(onpage).toHaveBeenLastCalledWith(4);
		await fireEvent.click(screen.getByRole('button', { name: 'Page 7' }));
		expect(onpage).toHaveBeenLastCalledWith(7);
	});

	it('shows a window of five pages around the current one', () => {
		renderPager({ page: 5 });
		const pages = screen.getAllByRole('button', { name: /^Page / }).map((b) => b.textContent);
		expect(pages).toEqual(['3', '4', '5', '6', '7']);
	});

	it('clamps the window at the last page and disables Next there', () => {
		renderPager({ page: 3, pageCount: 3 });
		const pages = screen.getAllByRole('button', { name: /^Page / }).map((b) => b.textContent);
		expect(pages).toEqual(['1', '2', '3']);
		expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled();
	});
});

describe('DataTable resizable columns (NET-318)', () => {
	const KEY = 'nettap-col-widths:t';
	// jsdom has no layout: each header reports a width by its label
	const MEASURED: Record<string, number> = { Device: 200, Data: 1200, Port: 100 };

	/** A pointer event as a browser sends it; jsdom has no PointerEvent (as AreaChart.test.ts does). */
	function pointer(type: string, clientX: number, { pointerId = 1, isPrimary = true, button = 0 } = {}) {
		const e = new MouseEvent(type, { clientX, bubbles: true, cancelable: true, button });
		Object.defineProperties(e, { isPrimary: { value: isPrimary }, pointerId: { value: pointerId } });
		return e;
	}

	const handle = (label: string) => screen.getByRole('separator', { name: `Resize ${label} column` });
	const cols = (container: HTMLElement) => [...container.querySelectorAll('col')].map((c) => c.style.width);
	const stored = () => JSON.parse(localStorage.getItem(KEY) ?? 'null');
	const resizable = () => render(Table, { columns: COLUMNS, rows: ROWS, ariaLabel: 'Devices', rowKey, resizeKey: 't' });

	async function drag(label: string, from: number, to: number) {
		const el = handle(label);
		await fireEvent(el, pointer('pointerdown', from));
		await fireEvent(el, pointer('pointermove', to));
		await fireEvent(el, pointer('pointerup', to));
	}

	beforeEach(() => {
		localStorage.clear();
		vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
			return { width: MEASURED[this.querySelector('.th-btn')?.textContent ?? ''] ?? 0 } as DOMRect;
		});
	});
	afterEach(() => {
		vi.restoreAllMocks();
		localStorage.clear();
	});

	it('has no handles and no reset button without resizeKey', () => {
		render(Table, { columns: COLUMNS, rows: ROWS, ariaLabel: 'Devices', rowKey });
		expect(screen.queryAllByRole('separator')).toHaveLength(0);
		expect(screen.queryByRole('button', { name: 'Reset column widths' })).toBeNull();
	});

	it('names each handle and gives it the measured width, clamped, before any resize', () => {
		const { container } = resizable();
		expect(screen.getAllByRole('separator')).toHaveLength(3);
		const device = handle('Device');
		expect(device).toHaveAttribute('aria-orientation', 'vertical');
		expect(device).toHaveAttribute('aria-valuemin', '72');
		expect(device).toHaveAttribute('aria-valuemax', '960');
		expect(device).toHaveAttribute('aria-valuenow', '200');
		expect(device).toHaveAttribute('aria-valuetext', '200 pixels');
		expect(handle('Data')).toHaveAttribute('aria-valuenow', '960');
		expect(handle('Port')).toHaveAttribute('aria-valuenow', '100');
		// the handle's label stays out of the header's name
		expect(header('Device')).toBeInTheDocument();
		// automatic layout until the first resize
		expect(cols(container)).toEqual([]);
		expect(screen.getByRole('table')).not.toHaveClass('is-resized');
	});

	it('freezes every column on the first drag, follows the pointer, saves, and never sorts', async () => {
		const { container } = resizable();
		await drag('Device', 100, 160);
		expect(cols(container)).toEqual(['260px', '960px', '100px']);
		const table = screen.getByRole('table');
		expect(table).toHaveClass('is-resized');
		expect(table.style.width).toBe('1320px');
		expect(stored()).toEqual({ name: 260, bytes: 960, port: 100 });
		expect(handle('Device')).toHaveAttribute('aria-valuenow', '260');
		expect(header('Device')).toHaveAttribute('aria-sort', 'none');
		expect(order()).toEqual(['Work laptop', 'Living-room TV', 'Kitchen iPad']);
	});

	it('keeps a drag between 72 and 960 pixels', async () => {
		const { container } = resizable();
		await drag('Port', 500, 0);
		expect(cols(container)[2]).toBe('72px');
		await drag('Port', 0, 3000);
		expect(cols(container)[2]).toBe('960px');
	});

	it('ignores a second pointer while a drag runs, and a cancel or lost capture ends it', async () => {
		const { container } = resizable();
		const device = handle('Device');
		const port = handle('Port');
		await fireEvent(device, pointer('pointerdown', 100, { pointerId: 1 }));
		await fireEvent(port, pointer('pointerdown', 50, { pointerId: 2, isPrimary: false }));
		await fireEvent(port, pointer('pointerdown', 50, { pointerId: 3 }));
		await fireEvent(port, pointer('pointermove', 400, { pointerId: 3 }));
		await fireEvent(device, pointer('pointermove', 400, { pointerId: 2 }));
		await fireEvent(device, pointer('pointerup', 400, { pointerId: 2 }));
		expect(cols(container)).toEqual(['200px', '960px', '100px']);
		await fireEvent(device, pointer('pointermove', 140, { pointerId: 1 }));
		expect(cols(container)[0]).toBe('240px');
		await fireEvent(device, pointer('pointercancel', 140, { pointerId: 1 }));
		await fireEvent(device, pointer('pointermove', 300, { pointerId: 1 }));
		expect(cols(container)[0]).toBe('240px');
		expect(stored()).toEqual({ name: 240, bytes: 960, port: 100 });
		// a new drag can start after the cancel; losing capture ends it too
		await fireEvent(port, pointer('pointerdown', 0, { pointerId: 4 }));
		await fireEvent(port, pointer('pointermove', 20, { pointerId: 4 }));
		await fireEvent(port, pointer('lostpointercapture', 20, { pointerId: 4 }));
		await fireEvent(port, pointer('pointermove', 200, { pointerId: 4 }));
		expect(cols(container)[2]).toBe('120px');
	});

	it('resizes from the keyboard: arrows by 16, Home and End to the bounds, each saved', async () => {
		const { container } = resizable();
		const device = handle('Device');
		await fireEvent.keyDown(device, { key: 'ArrowRight' });
		expect(cols(container)[0]).toBe('216px');
		await fireEvent.keyDown(device, { key: 'ArrowLeft' });
		await fireEvent.keyDown(device, { key: 'ArrowLeft' });
		expect(cols(container)[0]).toBe('184px');
		expect(stored().name).toBe(184);
		await fireEvent.keyDown(device, { key: 'Home' });
		expect(cols(container)[0]).toBe('72px');
		await fireEvent.keyDown(device, { key: 'End' });
		expect(cols(container)[0]).toBe('960px');
		expect(stored().name).toBe(960);
		// other keys pass through
		expect(await fireEvent.keyDown(device, { key: 'Tab' })).toBe(true);
	});

	it('freezes an untouched column measured past 960 at 960 in its width, its value and storage, also after a remount', async () => {
		const first = resizable();
		await fireEvent.keyDown(handle('Port'), { key: 'ArrowRight' });
		expect(cols(first.container)[1]).toBe('960px');
		expect(handle('Data')).toHaveAttribute('aria-valuenow', '960');
		expect(stored().bytes).toBe(960);
		first.unmount();
		const again = resizable();
		expect(cols(again.container)).toEqual(['200px', '960px', '116px']);
		expect(handle('Data')).toHaveAttribute('aria-valuenow', '960');
	});

	it('shows Reset column widths once resized; it restores automatic widths, clears storage and focuses the first handle', async () => {
		const { container } = resizable();
		expect(screen.queryByRole('button', { name: 'Reset column widths' })).toBeNull();
		await fireEvent.keyDown(handle('Port'), { key: 'ArrowRight' });
		await fireEvent.click(screen.getByRole('button', { name: 'Reset column widths' }));
		await vi.waitFor(() => expect(document.activeElement).toBe(handle('Device')));
		expect(cols(container)).toEqual([]);
		expect(screen.getByRole('table')).not.toHaveClass('is-resized');
		expect(localStorage.getItem(KEY)).toBeNull();
		expect(screen.queryByRole('button', { name: 'Reset column widths' })).toBeNull();
		expect(handle('Port')).toHaveAttribute('aria-valuenow', '100');
	});

	it('applies saved widths on mount, clamped to 72..960', () => {
		localStorage.setItem(KEY, JSON.stringify({ name: 10, bytes: 5000, port: 90 }));
		const { container } = resizable();
		expect(cols(container)).toEqual(['72px', '960px', '90px']);
		expect(screen.getByRole('button', { name: 'Reset column widths' })).toBeInTheDocument();
	});

	it.each([
		['a column missing', '{"name":300,"bytes":400}'],
		['a width that is not a number', '{"name":"wide","bytes":400,"port":90}'],
		['not JSON', 'not json'],
		['not an object', '42'],
	])('ignores saved widths with %s', (_, value) => {
		localStorage.setItem(KEY, value);
		const { container } = resizable();
		expect(cols(container)).toEqual([]);
	});

	it('still resizes, for this visit, when storage is blocked', async () => {
		vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
			throw new Error('blocked');
		});
		vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
			throw new Error('blocked');
		});
		const { container } = resizable();
		await fireEvent.keyDown(handle('Device'), { key: 'ArrowRight' });
		expect(cols(container)[0]).toBe('216px');
	});
});
