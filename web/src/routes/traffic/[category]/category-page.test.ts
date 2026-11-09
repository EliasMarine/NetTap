import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { readable, get } from 'svelte/store';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import CategoryPage from './+page.svelte';
import { expectNoNestedInteractive } from '../../../tests/nested-interactive';
import { SETTLE_MS } from '$lib/utils/window-trend';

vi.mock('$app/stores', () => ({
	page: readable({ url: new URL('http://localhost/traffic/streaming'), params: { category: 'streaming' } }),
}));

// #96: a failed category request read as "No traffic data for Streaming", and a failed network
// total read as "0.0%" of the network.

const EMPTY = { category: 'streaming', label: 'Streaming', device_count: 0, total_bytes: 0, connection_count: 0, devices: [], services: [] };
const BUSY = {
	...EMPTY,
	device_count: 1,
	// decimal units (NET-166): 4,000 bytes is 4.0 KB (4,096 bytes would read 4.1 KB)
	total_bytes: 4000,
	connection_count: 3,
	devices: [{ ip: '192.168.1.20', hostname: null, total_bytes: 4000, download_bytes: 3904, upload_bytes: 96, connections: 3, percent: 100 }],
};

/** Replies by path; any path not listed answers 503. */
function stubDaemon(replies: Record<string, unknown>): void {
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			const body = replies[url.split('?')[0]];
			return body
				? { ok: true, status: 200, json: async () => body }
				: { ok: false, status: 503, json: async () => ({}) };
		}),
	);
}

const STEP: Record<string, number> = { '5m': 300_000, '30m': 1_800_000, '1h': 3_600_000, '12h': 43_200_000, '1d': 86_400_000 };
const isTrendWindow = (u: URL) => Date.parse(u.searchParams.get('to') ?? '') <= Date.now() - SETTLE_MS;

/** A slot per step from `from` plus the one holding `to`, as time_slots replies; figures by half. */
function trendSeries(u: URL, shape: (half: 'older' | 'newer', i: number) => { bytes: number; connections: number }) {
	const from = Date.parse(u.searchParams.get('from')!);
	const to = Date.parse(u.searchParams.get('to')!);
	const step = STEP[u.searchParams.get('interval')!];
	const out = [];
	for (let t = from, i = 0; t <= to; t += step, i++) {
		const { bytes, connections } = shape(t < from + (to - from) / 2 ? 'older' : 'newer', i);
		out.push({ timestamp: new Date(t).toISOString(), download_bytes: bytes, upload_bytes: 0, total_bytes: bytes, connections });
	}
	return out;
}

/** BUSY with a service, a network total of 8,000 B, and the category's series from `bandwidth` (null fails it). */
function stubCategory(bandwidth: (u: URL) => unknown[] | null): void {
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			const u = new URL(url, 'http://x');
			const series = u.pathname === '/api/traffic/categories/streaming/bandwidth' ? bandwidth(u) : null;
			const body =
				u.pathname === '/api/traffic/categories/streaming' ? { ...BUSY, services: [{ name: 'Netflix', bytes: 4000, connections: 3 }] }
				: series ? { category: 'streaming', from: '', to: '', interval: u.searchParams.get('interval'), series }
				: u.pathname === '/api/traffic/summary' ? { total_bytes: 8000 }
				: null;
			return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 503, json: async () => ({}) };
		}),
	);
}

/** The Connections KPI (the device table has a Connections column too) */
const connectionsKpi = () => screen.getAllByText('Connections').map((e) => e.closest('.kpi')).find(Boolean);

describe('Traffic category page', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('says the category failed to load instead of "No traffic data"', async () => {
		stubDaemon({});
		render(CategoryPage);
		expect(await screen.findByText("Couldn't load Streaming traffic: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText(/No traffic data for/)).not.toBeInTheDocument();
	});

	it('still says there is no traffic when the category really has none', async () => {
		stubDaemon({ '/api/traffic/categories/streaming': EMPTY });
		render(CategoryPage);
		expect(await screen.findByText('No traffic data for Streaming')).toBeInTheDocument();
	});

	it('shows a dash, not 0.0%, when the network total failed', async () => {
		stubDaemon({ '/api/traffic/categories/streaming': BUSY });
		render(CategoryPage);
		// OLD CODE START: const card = (await screen.findByText('% of Network')).closest('.stat-card'); (now a KpiCard, "Share of network") OLD CODE END
		const card = (await screen.findByText('Share of network')).closest('.kpi');
		expect(card).toHaveTextContent('—');
		expect(card).not.toHaveTextContent('0.0%');
		expect(screen.getByText("Couldn't load bandwidth over time: the request failed.")).toBeInTheDocument();
	});

	it('loading: says it is loading the category', async () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(CategoryPage);
		expect(await screen.findByRole('status')).toHaveTextContent('Loading category data');
	});

	// OLD CODE START — NET-228 (audit TRF-6): the trend compared a second detail reply for the window before
	// it('shows the KPIs with their trend, the chart, the services and the device table', async () => {
	// 	const prevBusy = { ...BUSY, total_bytes: 2000, connection_count: 6 };
	// 	const series = [
	// 		{ timestamp: '2026-11-03T09:00:00Z', download_bytes: 1000, upload_bytes: 50, total_bytes: 1050, connections: 1 },
	// 		{ timestamp: '2026-11-03T10:00:00Z', download_bytes: 3000, upload_bytes: 46, total_bytes: 3046, connections: 2 },
	// 	];
	// 	let detailCalls = 0;
	// 	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	// 	vi.stubGlobal(
	// 		'fetch',
	// 		vi.fn(async (url: string) => {
	// 			const path = url.split('?')[0];
	// 			const body =
	// 				path === '/api/traffic/categories/streaming' ? (detailCalls++ === 0 ? { ...BUSY, services: [{ name: 'Netflix', bytes: 4000, connections: 3 }] } : prevBusy)
	// 				: path === '/api/traffic/categories/streaming/bandwidth' ? { category: 'streaming', from: '', to: '', interval: '15m', series }
	// 				: path === '/api/traffic/summary' ? { total_bytes: 8000 }
	// 				: null;
	// 			return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 503, json: async () => ({}) };
	// 		}),
	// 	);
	// 	render(CategoryPage);
	// 	const total = (await screen.findByText('Total bandwidth')).closest('.kpi');
	// 	expect(total).toHaveTextContent('4.0 KB');
	// 	expect(total).toHaveTextContent('+100.0%');
	// 	// OLD CODE: expect(total).toHaveTextContent('vs previous 24 h'); (NET-196: the list's words; the old text is a prefix of the new, so it no longer pinned anything)
	// 	expect(total).toHaveTextContent(/vs previous 24 hours$/);
	// 	expect(screen.getByText('Share of network').closest('.kpi')).toHaveTextContent('50.0%');
	// 	expect(screen.getByRole('img', { name: /^Busiest at .*, with 3\.0 KB$/ })).toBeInTheDocument();
	// 	expect(screen.getByText('Netflix')).toBeInTheDocument();
	// 	expect(screen.getByRole('table', { name: 'Per-device breakdown' })).toHaveTextContent('192.168.1.20');
	// });
	// OLD CODE END
	it('shows the KPIs with their trend, the chart, the services and the device table', async () => {
		const series = [
			{ timestamp: '2026-11-03T09:00:00Z', download_bytes: 1000, upload_bytes: 50, total_bytes: 1050, connections: 1 },
			{ timestamp: '2026-11-03T10:00:00Z', download_bytes: 3000, upload_bytes: 46, total_bytes: 3046, connections: 2 },
		];
		stubCategory((u) => (isTrendWindow(u) ? trendSeries(u, (half) => ({ bytes: half === 'older' ? 1000 : 2000, connections: half === 'older' ? 2 : 3 })) : series));
		render(CategoryPage);
		const total = (await screen.findByText('Total bandwidth')).closest('.kpi');
		expect(total).toHaveTextContent('4.0 KB');
		expect(total).toHaveTextContent('+100.0%');
		expect(total).toHaveTextContent(/vs previous 24 hours, up to \d\d:\d\d$/);
		expect(connectionsKpi()).toHaveTextContent('+50.0%');
		// distinct devices don't add up across slots, so there is no devices delta, only the window
		expect(screen.getByText('Active devices').closest('.kpi')).toHaveTextContent(/Last 24 hours$/);
		expect(screen.getByText('Share of network').closest('.kpi')).toHaveTextContent('50.0%');
		expect(screen.getByRole('img', { name: /^Busiest at .*, with 3\.0 KB$/ })).toBeInTheDocument();
		expect(screen.getByText('Netflix')).toBeInTheDocument();
		expect(screen.getByRole('table', { name: 'Per-device breakdown' })).toHaveTextContent('192.168.1.20');
	});

	it('the trend reads two equal settled windows, and a slot with no connections is not enough data (NET-228)', async () => {
		const asked: URL[] = [];
		stubCategory((u) => {
			asked.push(u);
			return trendSeries(u, (half, i) => ({ bytes: 1000, connections: i === 5 ? 0 : 2 }));
		});
		render(CategoryPage);
		await vi.waitFor(() => expect(screen.getByText('Total bandwidth').closest('.kpi')).toHaveTextContent(/Not enough data to compare$/));
		expect(connectionsKpi()).toHaveTextContent(/Not enough data to compare$/);
		const trend = asked.find(isTrendWindow)!;
		expect(trend.searchParams.get('interval')).toBe('1h');
		expect(Date.parse(trend.searchParams.get('to')!) - Date.parse(trend.searchParams.get('from')!)).toBe(48 * 3_600_000);
	});

	it('a refresh whose trend request fails says so instead of keeping the last trend (NET-228)', async () => {
		let failTrend = false;
		stubCategory((u) => (isTrendWindow(u) && failTrend ? null : trendSeries(u, (half) => ({ bytes: half === 'older' ? 1000 : 2000, connections: 2 }))));
		render(CategoryPage);
		const total = () => screen.getByText('Total bandwidth').closest('.kpi');
		await vi.waitFor(() => expect(total()).toHaveTextContent('+100.0%'));
		failTrend = true;
		await refreshPage();
		expect(total()).not.toHaveTextContent('+100.0%');
		expect(total()).toHaveTextContent(/Couldn't load the comparison$/);
	});

	// NET-160: the device row is already one link, so its address renders as plain text inside it
	it('keeps the address plain inside the device link, with nothing nested', async () => {
		stubDaemon({ '/api/traffic/categories/streaming': BUSY });
		const { container } = render(CategoryPage);
		const link = await screen.findByRole('link', { name: /192\.168\.1\.20/ });
		expect(link).toHaveAttribute('href', '/devices/192.168.1.20');
		expect(link.querySelector('a, button, [role], [tabindex]')).toBeNull();
		expectNoNestedInteractive(container);
	});

	it('the device filter says when nothing matches', async () => {
		stubDaemon({ '/api/traffic/categories/streaming': BUSY });
		render(CategoryPage);
		const search = await screen.findByRole('searchbox', { name: 'Filter devices' });
		await fireEvent.input(search, { target: { value: '10.9.9.9' } });
		expect(screen.getByRole('heading', { name: 'No devices matching "10.9.9.9"' })).toBeInTheDocument();
	});

	it('refresh contract: partial when some requests fail', async () => {
		stubDaemon({ '/api/traffic/categories/streaming': BUSY });
		render(CategoryPage);
		await screen.findByText('Total bandwidth');
		// bandwidth and the network total answer 503
		expect(await refreshPage()).toBe('partial');
		expect(get(pageRefresh).status).toBe('partial');
	});
});
