/**
 * The page refresh contract against the real Connections loader (PLAN.md §5.5): what each
 * load reports, and the load guard that keeps an older response from overwriting a newer one.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { readable, get } from 'svelte/store';
import { getConnections, getConnectionStats, getConnectionSankey, getConnectionTimeline } from '$api/traffic';
import type { ConnectionsResponse, ConnectionStatsResponse } from '$api/traffic';
import { getLiveDashboard } from '$api/live';
import type { LiveDashboardResponse } from '$api/live';
import { getRegistryDevices, type RegistryDevice } from '$api/devices-registry';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import Page from './+page.svelte';

vi.mock('$app/stores', () => ({
	page: readable({ url: new URL('http://localhost/connections') }),
}));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$api/traffic', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/traffic')>()),
	getConnections: vi.fn(),
	getConnectionStats: vi.fn(),
	getConnectionSankey: vi.fn(),
	getConnectionTimeline: vi.fn(),
}));
vi.mock('$api/live', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/live')>()),
	getLiveDashboard: vi.fn(),
}));
vi.mock('$api/devices-registry', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/devices-registry')>()),
	getRegistryDevices: vi.fn(),
}));

vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });

function deferred<T>() {
	let resolve!: (v: T) => void;
	let reject!: (e: unknown) => void;
	const promise = new Promise<T>((res, rej) => {
		resolve = res;
		reject = rej;
	});
	return { promise, resolve, reject };
}

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

const stats = (sessions: number): ConnectionStatsResponse => ({
	from: '', to: '', total_sessions: sessions, bytes_in: 2048, bytes_out: 1024, alert_sessions: 0,
	protocols: [], top_sources: [], top_destinations: [],
});

const table = (id: string): ConnectionsResponse => ({
	from: '', to: '', page: 1, size: 50, total: 1, total_pages: 1,
	connections: [{ _id: id, _index: 'zeek-conn', '@timestamp': '2026-11-03T10:00:00Z', source: { ip: `10.0.0.${id.length}` }, destination: { ip: '8.8.8.8' } }],
});

const live = (devices: number) => ({ stats: { active_devices: devices } }) as unknown as LiveDashboardResponse;

/** The Sessions figure in the summary strip. */
const sessions = () =>
	[...document.querySelectorAll('.stat')].find((el) => el.querySelector('.stat-k')?.textContent === 'Sessions')
		?.querySelector('.stat-v')?.textContent;

/** Row ids shown in the table, by the row button's label. */
const rowLabels = () => screen.queryAllByRole('button', { name: /^Open connection from/ }).map((b) => b.getAttribute('aria-label'));

function allSucceed() {
	vi.mocked(getConnectionStats).mockResolvedValue(stats(5));
	vi.mocked(getConnectionSankey).mockResolvedValue({ from: '', to: '', nodes: { sources: [], protocols: [], destinations: [] }, links: [] });
	vi.mocked(getConnectionTimeline).mockResolvedValue({ from: '', to: '', interval: '5m', buckets: [] } as never);
	vi.mocked(getLiveDashboard).mockResolvedValue(live(3));
	vi.mocked(getConnections).mockResolvedValue(table('a'));
	vi.mocked(getRegistryDevices).mockResolvedValue({ devices: [], total: 0 });
}

beforeEach(() => {
	vi.resetAllMocks();
	allSucceed();
});

afterEach(() => {
	vi.resetAllMocks();
});

describe('Connections refresh contract: results', () => {
	it('every request succeeds: ok, and the top bar advances "Updated"', async () => {
		render(Page);
		await flush();
		expect(get(pageRefresh)).toMatchObject({ available: true, status: 'ok' });
		expect(get(pageRefresh).updatedAt).not.toBeNull();
		expect(await refreshPage()).toBe('ok');
	});

	it('one request fails: partial, and "Updated" does not move', async () => {
		render(Page);
		await flush();
		const before = get(pageRefresh).updatedAt;
		vi.mocked(getConnectionSankey).mockRejectedValue(new Error('HTTP 503'));
		expect(await refreshPage()).toBe('partial');
		expect(get(pageRefresh)).toMatchObject({ status: 'partial', updatedAt: before });
	});

	it('every request fails: failed', async () => {
		render(Page);
		await flush();
		for (const fn of [getConnectionStats, getConnectionSankey, getConnectionTimeline, getLiveDashboard, getConnections]) {
			vi.mocked(fn).mockRejectedValue(new Error('HTTP 503'));
		}
		expect(await refreshPage()).toBe('failed');
		expect(get(pageRefresh).status).toBe('failed');
	});

	it('a request still pending: the loader has not returned', async () => {
		render(Page);
		await flush();
		const pending = deferred<ConnectionStatsResponse>();
		vi.mocked(getConnectionStats).mockReturnValue(pending.promise);
		let settled = false;
		const run = refreshPage().then((r) => {
			settled = true;
			return r;
		});
		await flush();
		expect(settled).toBe(false);
		pending.resolve(stats(9));
		expect(await run).toBe('ok');
		expect(sessions()).toBe('9');
	});

	it('device names are cosmetic: a failed registry load is not a failed refresh', async () => {
		render(Page);
		await flush();
		vi.mocked(getRegistryDevices).mockRejectedValue(new Error('HTTP 503'));
		expect(await refreshPage()).toBe('ok');
	});
});

describe('Connections network flow names', () => {
	const ipad = {
		mac: 'aa:bb:cc:00:00:01', ips: ['192.168.1.10'], hostnames: [], manufacturer: 'Apple, Inc.', friendly_name: null,
		display_name: 'Kitchen iPad', category: 'phone', first_seen: '', last_seen: '2026-11-05T00:00:00Z', is_new: false,
	} satisfies RegistryDevice;

	it('shows registry names in the flow, and keeps them when a later registry load fails', async () => {
		vi.mocked(getConnectionSankey).mockResolvedValue({
			from: '', to: '',
			nodes: {
				sources: [{ id: '192.168.1.10', label: '192.168.1.10', value: 10 }, { id: '192.168.1.20', label: '192.168.1.20', value: 5 }],
				protocols: [{ id: 'tcp', label: 'TCP', value: 15 }],
				destinations: [{ id: 'Unknown', label: 'Unknown', value: 15 }],
			},
			links: [
				{ source: '192.168.1.10', target: 'tcp', value: 10 },
				{ source: '192.168.1.20', target: 'tcp', value: 5 },
				{ source: 'tcp', target: 'Unknown', value: 15 },
			],
		});
		vi.mocked(getRegistryDevices).mockResolvedValue({ devices: [ipad], total: 1 });
		render(Page);
		await flush();
		// jsdom has no layout, so the flow shows as its table
		expect(screen.getByRole('button', { name: 'Kitchen iPad' })).toBeTruthy();
		expect(screen.getByRole('button', { name: '192.168.1.20' })).toBeTruthy();
		vi.mocked(getRegistryDevices).mockRejectedValue(new Error('HTTP 503'));
		await refreshPage();
		await flush();
		expect(screen.getByRole('button', { name: 'Kitchen iPad' })).toBeTruthy();
	});
});

describe('Connections card states', () => {
	it('loading: every card says what it is loading', async () => {
		for (const fn of [getConnectionStats, getConnectionSankey, getConnectionTimeline, getLiveDashboard, getConnections]) {
			vi.mocked(fn).mockReturnValue(new Promise(() => {}) as never);
		}
		render(Page);
		await flush();
		const loading = screen.getAllByRole('status').map((el) => el.textContent?.trim());
		for (const what of ['connection stats', 'protocols', 'the flow diagram', 'top sources', 'top destinations', 'connections']) {
			expect(loading).toContain(`Loading ${what}`);
		}
	});

	it('empty: each card names what will appear, not zeros', async () => {
		vi.mocked(getConnections).mockResolvedValue({ ...table('a'), connections: [], total: 0, total_pages: 0 });
		render(Page);
		await flush();
		for (const title of ['No protocols in this window', 'No flows in this window', 'No sources in this window', 'No destinations in this window', 'No connections']) {
			expect(screen.getByRole('heading', { name: title })).toBeInTheDocument();
		}
	});

	it('error: each card offers Try again, which reloads', async () => {
		vi.mocked(getConnectionStats).mockRejectedValue(new Error('HTTP 503'));
		vi.mocked(getConnectionSankey).mockRejectedValue(new Error('HTTP 503'));
		vi.mocked(getConnections).mockRejectedValue(new Error('HTTP 503'));
		render(Page);
		await flush();
		const alerts = screen.getAllByRole('alert').map((el) => el.querySelector('h3')?.textContent);
		expect(alerts).toEqual(
			expect.arrayContaining([
				"Couldn't load the protocol split: the request failed.",
				"Couldn't load the flow diagram: the request failed.",
				"Couldn't load top sources: the request failed.",
				"Couldn't load top destinations: the request failed.",
				"Couldn't load connections: the request failed.",
			]),
		);
		vi.mocked(getConnections).mockClear();
		await fireEvent.click(screen.getAllByRole('button', { name: 'Try again' }).at(-1)!);
		expect(getConnections).toHaveBeenCalledTimes(1);
	});
});

describe('Connections refresh contract: the load guard', () => {
	it('responses in reverse order: a slow 24 h load does not overwrite a newer 4 h one', async () => {
		render(Page);
		await flush();
		const day = { stats: deferred<ConnectionStatsResponse>(), rows: deferred<ConnectionsResponse>() };
		const four = { stats: deferred<ConnectionStatsResponse>(), rows: deferred<ConnectionsResponse>() };
		vi.mocked(getConnectionStats).mockReturnValueOnce(day.stats.promise).mockReturnValueOnce(four.stats.promise);
		vi.mocked(getConnections).mockReturnValueOnce(day.rows.promise).mockReturnValueOnce(four.rows.promise);

		await fireEvent.click(screen.getByRole('button', { name: '24h' }));
		await fireEvent.click(screen.getByRole('button', { name: '4h' }));
		four.stats.resolve(stats(40));
		four.rows.resolve(table('four'));
		await flush();
		day.stats.resolve(stats(2400));
		day.rows.resolve(table('day-old'));
		await flush();

		expect(sessions()).toBe('40');
		expect(rowLabels()).toEqual(['Open connection from 10.0.0.4 to 8.8.8.8']);
		expect(screen.getByRole('button', { name: '4h' })).toHaveAttribute('aria-pressed', 'true');
	});

	it('a filter change during a refresh: the older table is dropped, and the pills and rows agree', async () => {
		render(Page);
		await flush();
		const old = deferred<ConnectionsResponse>();
		const filtered = deferred<ConnectionsResponse>();
		vi.mocked(getConnections).mockReturnValueOnce(old.promise).mockReturnValueOnce(filtered.promise);

		const run = refreshPage();
		await fireEvent.click(screen.getByRole('button', { name: 'Rejected' }));
		expect(getConnections).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, state: 'rejected' }));
		filtered.resolve(table('rejected'));
		await flush();
		old.resolve(table('old'));
		// the summary still counts: only the table part was superseded
		expect(await run).toBe('ok');

		expect(rowLabels()).toEqual(['Open connection from 10.0.0.8 to 8.8.8.8']);
		expect(screen.getByRole('button', { name: 'Rejected' })).toHaveAttribute('aria-pressed', 'true');
	});

	it('navigation before completion: nothing is written and "Updated" never moves', async () => {
		const slow = deferred<ConnectionStatsResponse>();
		vi.mocked(getConnectionStats).mockReturnValue(slow.promise);
		const { unmount } = render(Page);
		await flush();
		expect(get(pageRefresh).available).toBe(true);

		unmount();
		slow.resolve(stats(77));
		await flush();

		expect(get(pageRefresh)).toMatchObject({ available: false, updatedAt: null, status: null });
		expect(await refreshPage()).toBe('skipped');
	});
});

// NET-166: byte figures are decimal (the page's own 1,024-based copy read 976.6 KB for 10^6 bytes)
describe('Connections byte figures', () => {
	it('shows each row and the summary in decimal units', async () => {
		vi.mocked(getConnectionStats).mockResolvedValue({ ...stats(5), bytes_in: 1_000_000, bytes_out: 500_000 });
		vi.mocked(getConnections).mockResolvedValue({
			...table('a'),
			connections: [{ _id: 'a', _index: 'zeek-conn', '@timestamp': '2026-11-03T10:00:00Z',
				source: { ip: '10.0.0.1', bytes: 1_000_000 }, destination: { ip: '8.8.8.8', bytes: 1_500 } }],
		});
		render(Page);
		await flush();

		const row = screen.getByRole('button', { name: /^Open connection from/ }).closest('tr')!;
		const cells = [...row.querySelectorAll('.bytes > span:first-child')].map((el) => el.textContent);
		expect(cells).toEqual(['1.0 MB', '1.5 KB']);
		const data = [...document.querySelectorAll('.stat')].find((el) => el.querySelector('.stat-k')?.textContent === 'Data');
		expect(data?.querySelector('.stat-v')?.textContent).toBe('1.5 MB');
		expect(screen.getByText(/1\.0 MB sent by source, 500\.0 KB sent by destination/)).toBeInTheDocument();
	});
});
