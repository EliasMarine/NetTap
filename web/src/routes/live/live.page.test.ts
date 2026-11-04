/**
 * Live Monitor: the three feed filters (PLAN.md §5.6), the 3 s loop and the page refresh
 * contract against the real loader (§5.5), new-row flash, reduced motion and the card states.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { getLiveDashboard } from '$lib/api/live';
import type { LiveConnection, LiveDashboardResponse } from '$lib/api/live';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import Page from './+page.svelte';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$lib/api/live', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/live')>()),
	getLiveDashboard: vi.fn(),
	getLiveConnectionDetail: vi.fn().mockReturnValue(new Promise(() => {})),
}));

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

function conn(i: number, src: string, country: string, protocol: string, extra: Partial<LiveConnection> = {}): LiveConnection {
	return {
		timestamp: `2026-11-03T10:00:0${i}Z`, source_ip: src, source_port: 50_000 + i, dest_ip: `203.0.113.${i}`, dest_port: 443,
		protocol, service: '', bytes: 1000 * i, duration: 1, country, country_name: country, device_name: '',
		dest_lat: null, dest_lon: null, dest_city: '', dest_asn: null, dest_org: '', has_alert: false, ...extra,
	};
}

const CONNECTIONS = [
	conn(1, '192.168.1.20', 'NL', 'tcp', { device_name: 'Kitchen iPad' }),
	conn(2, '192.168.1.21', 'DE', 'udp'),
	conn(3, '192.168.1.20', 'DE', 'tcp', { device_name: 'Kitchen iPad' }),
	conn(4, '192.168.1.22', 'NL', 'udp'),
];

function dashboard(connections = CONNECTIONS, extra: Partial<LiveDashboardResponse> = {}): LiveDashboardResponse {
	return {
		connections,
		count: connections.length,
		stats: { connections_per_second: 1.5, bandwidth_bytes_per_second: 2_500_000, active_devices: 3, top_country: 'NL', connections_in_window: 40 },
		protocols: { tcp: 2, udp: 2 },
		top_talkers: [
			{ ip: '192.168.1.20', bytes: 4000, connections: 2 },
			{ ip: '192.168.1.22', bytes: 4000, connections: 1 },
			{ ip: '192.168.1.21', bytes: 2000, connections: 1 },
		],
		geo_arcs: [
			{ city: 'Amsterdam', country: 'Netherlands', country_code: 'NL', lat: 52.37, lon: 4.9, count: 2, bytes: 5000 },
			{ city: 'Frankfurt', country: 'Germany', country_code: 'DE', lat: 50.11, lon: 8.68, count: 2, bytes: 5000 },
		],
		...extra,
	};
}

/** Destination IPs in the feed, top to bottom. */
const feed = () =>
	screen.queryAllByRole('button', { name: /^Open connection from/ }).map((b) => b.getAttribute('aria-label')!.split(' to ')[1]);
const chips = () => screen.queryAllByRole('button', { name: /^Remove the / }).map((b) => b.textContent?.trim());
const hotspot = (country: string) => screen.getByRole('button', { name: new RegExp(`^${country}, `) });
const protocolPill = (label: string) => within(screen.getByRole('group', { name: 'Protocol' })).getByRole('button', { name: label });
const talker = (name: RegExp) => screen.getByRole('button', { name });

let reducedMotion = false;

beforeEach(() => {
	vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
	reducedMotion = false;
	vi.stubGlobal('matchMedia', (q: string) => ({ matches: reducedMotion && q.includes('reduce'), media: q }));
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	// DotMap's country outlines; without them it draws the hotspots on a blank background
	vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })));
	vi.spyOn(console, 'warn').mockImplementation(() => {});
	vi.mocked(getLiveDashboard).mockReset().mockResolvedValue(dashboard());
});

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

async function renderLive() {
	const view = render(Page);
	await flush();
	return view;
}

describe('Live filters', () => {
	it('country alone: a map hotspot narrows the feed and shows a chip', async () => {
		await renderLive();
		await fireEvent.click(hotspot('Netherlands'));
		expect(feed()).toEqual(['203.0.113.4', '203.0.113.1']);
		expect(chips()).toEqual(['Country: NL']);
		expect(hotspot('Netherlands')).toHaveAttribute('aria-pressed', 'true');
	});

	it('protocol alone: the feed pills use setProtocolFilter', async () => {
		await renderLive();
		await fireEvent.click(protocolPill('UDP'));
		expect(feed()).toEqual(['203.0.113.4', '203.0.113.2']);
		expect(chips()).toEqual(['Protocol: UDP']);
		expect(protocolPill('UDP')).toHaveAttribute('aria-pressed', 'true');
	});

	it('device alone: a top-talker row narrows the feed instead of navigating', async () => {
		await renderLive();
		await fireEvent.click(talker(/^Kitchen iPad/));
		expect(feed()).toEqual(['203.0.113.3', '203.0.113.1']);
		expect(chips()).toEqual(['Device: 192.168.1.20']);
		expect(talker(/^Kitchen iPad/)).toHaveAttribute('aria-pressed', 'true');
	});

	it('all three combined, then toggling one off, then clearing', async () => {
		await renderLive();
		await fireEvent.click(hotspot('Germany'));
		await fireEvent.click(protocolPill('TCP'));
		await fireEvent.click(talker(/^Kitchen iPad/));
		expect(feed()).toEqual(['203.0.113.3']);
		expect(chips()).toEqual(['Country: DE', 'Protocol: TCP', 'Device: 192.168.1.20']);
		expect(screen.getByText('1 of 4, filtered connections · newest first')).toBeInTheDocument();

		// the same hotspot again toggles the country off
		await fireEvent.click(hotspot('Germany'));
		expect(feed()).toEqual(['203.0.113.3', '203.0.113.1']);
		expect(chips()).toEqual(['Protocol: TCP', 'Device: 192.168.1.20']);

		// a chip removes its own filter
		await fireEvent.click(screen.getByRole('button', { name: 'Remove the protocol filter TCP' }));
		expect(chips()).toEqual(['Device: 192.168.1.20']);

		await fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
		expect(feed()).toHaveLength(4);
		expect(chips()).toEqual([]);
		expect(protocolPill('All')).toHaveAttribute('aria-pressed', 'true');
	});
});

describe('Live refresh contract', () => {
	it('ok, partial (the daemon reported an error) and failed', async () => {
		await renderLive();
		expect(get(pageRefresh)).toMatchObject({ available: true, status: 'ok' });

		vi.mocked(getLiveDashboard).mockResolvedValue(dashboard(CONNECTIONS, { _error: 'GeoIP lookups failed' }));
		expect(await refreshPage()).toBe('partial');
		expect(screen.getByText('GeoIP lookups failed')).toBeInTheDocument();

		vi.mocked(getLiveDashboard).mockRejectedValue(new Error('HTTP 503'));
		expect(await refreshPage()).toBe('failed');
		// the last good feed stays, marked stale
		expect(feed()).toHaveLength(4);
		expect(screen.getByText("Couldn't refresh live data; showing the last figures loaded.")).toBeInTheDocument();
	});

	it('a request still pending: the loader has not returned', async () => {
		await renderLive();
		const pending = deferred<LiveDashboardResponse>();
		vi.mocked(getLiveDashboard).mockReturnValue(pending.promise);
		let settled = false;
		const run = refreshPage().then((r) => ((settled = true), r));
		await flush();
		expect(settled).toBe(false);
		pending.resolve(dashboard());
		expect(await run).toBe('ok');
	});

	it('paused: the loader reports skipped and makes no request', async () => {
		await renderLive();
		await fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
		vi.mocked(getLiveDashboard).mockClear();
		expect(await refreshPage()).toBe('skipped');
		vi.advanceTimersByTime(9000);
		await flush();
		expect(getLiveDashboard).not.toHaveBeenCalled();
		expect(screen.getByText('Paused')).toBeInTheDocument();
	});

	it('the 3 s loop goes through the loader and waits while a load is running', async () => {
		await renderLive();
		const slow = deferred<LiveDashboardResponse>();
		vi.mocked(getLiveDashboard).mockClear().mockReturnValue(slow.promise);
		vi.advanceTimersByTime(3000);
		expect(getLiveDashboard).toHaveBeenCalledTimes(1);
		vi.advanceTimersByTime(6000);
		expect(getLiveDashboard).toHaveBeenCalledTimes(1);
		slow.resolve(dashboard());
		await flush();
		vi.advanceTimersByTime(3000);
		expect(getLiveDashboard).toHaveBeenCalledTimes(2);
	});

	it('responses in reverse order: the older one is dropped', async () => {
		await renderLive();
		const older = deferred<LiveDashboardResponse>();
		const newer = deferred<LiveDashboardResponse>();
		vi.mocked(getLiveDashboard).mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
		const first = refreshPage();
		const second = refreshPage();
		newer.resolve(dashboard([conn(7, '192.168.1.30', 'JP', 'tcp')]));
		expect(await second).toBe('ok');
		older.resolve(dashboard([conn(8, '192.168.1.31', 'BR', 'udp')]));
		expect(await first).toBe('skipped');
		expect(feed()).toEqual(['203.0.113.7']);
	});

	it('a filter change during a refresh: the new data arrives filtered, and the chip and rows agree', async () => {
		await renderLive();
		const pending = deferred<LiveDashboardResponse>();
		vi.mocked(getLiveDashboard).mockReturnValue(pending.promise);
		const run = refreshPage();
		await fireEvent.click(protocolPill('UDP'));
		pending.resolve(dashboard([...CONNECTIONS, conn(5, '192.168.1.23', 'US', 'udp'), conn(6, '192.168.1.23', 'US', 'tcp')]));
		expect(await run).toBe('ok');
		expect(feed()).toEqual(['203.0.113.5', '203.0.113.4', '203.0.113.2']);
		expect(chips()).toEqual(['Protocol: UDP']);
	});

	it('navigation before completion: nothing is written and "Updated" never moves', async () => {
		const pending = deferred<LiveDashboardResponse>();
		vi.mocked(getLiveDashboard).mockReturnValue(pending.promise);
		const { unmount } = await renderLive();
		unmount();
		pending.resolve(dashboard());
		await flush();
		expect(get(pageRefresh)).toMatchObject({ available: false, updatedAt: null, status: null });
	});
});

describe('Live feed motion', () => {
	it('flashes only the rows that arrived with the latest poll', async () => {
		const { container } = await renderLive();
		expect(container.querySelectorAll('.row-new')).toHaveLength(0);
		vi.mocked(getLiveDashboard).mockResolvedValue(dashboard([conn(9, '192.168.1.40', 'US', 'tcp'), ...CONNECTIONS]));
		await refreshPage();
		await flush();
		const flashed = [...container.querySelectorAll('.row-new')].map((el) => el.closest('tr')?.querySelector('.row-btn')?.getAttribute('aria-label'));
		expect(flashed).toEqual(['Open connection from 192.168.1.40 to 203.0.113.9']);
	});

	it('under reduced motion the feed loads once, then starts paused', async () => {
		reducedMotion = true;
		await renderLive();
		expect(getLiveDashboard).toHaveBeenCalledTimes(1);
		expect(feed()).toHaveLength(4);
		expect(screen.getByText('Paused')).toBeInTheDocument();
		vi.advanceTimersByTime(9000);
		await flush();
		expect(getLiveDashboard).toHaveBeenCalledTimes(1);
		expect(screen.getByRole('button', { name: 'Resume' })).toBeInTheDocument();
	});
});

describe('Live card states', () => {
	it('loading: each card says what it is loading', async () => {
		vi.mocked(getLiveDashboard).mockReturnValue(new Promise(() => {}));
		await renderLive();
		const loading = screen.getAllByRole('status').map((el) => el.textContent?.trim());
		expect(loading).toEqual(
			expect.arrayContaining(['Loading live data', 'Loading the map', 'Loading top talkers', 'Loading protocols', 'Loading live connections']),
		);
	});

	it('empty: each card names what will appear, not zeros', async () => {
		vi.mocked(getLiveDashboard).mockResolvedValue({ ...dashboard([]), protocols: {}, top_talkers: [], geo_arcs: [] });
		await renderLive();
		for (const title of ['No destinations yet', 'No devices talking yet', 'No protocols yet', 'No connections right now']) {
			expect(screen.getByRole('heading', { name: title })).toBeInTheDocument();
		}
	});

	it('error: each card says the request failed and offers Try again', async () => {
		vi.mocked(getLiveDashboard).mockRejectedValue(new Error('HTTP 503'));
		await renderLive();
		expect(screen.getAllByRole('alert')).toHaveLength(5);
		vi.mocked(getLiveDashboard).mockResolvedValue(dashboard());
		await fireEvent.click(screen.getAllByRole('button', { name: 'Try again' })[0]);
		await flush();
		expect(feed()).toHaveLength(4);
	});
});
