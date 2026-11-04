import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { readable, get } from 'svelte/store';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import CategoryPage from './+page.svelte';

vi.mock('$app/stores', () => ({
	page: readable({ url: new URL('http://localhost/traffic/streaming'), params: { category: 'streaming' } }),
}));

// #96: a failed category request read as "No traffic data for Streaming", and a failed network
// total read as "0.0%" of the network.

const EMPTY = { category: 'streaming', label: 'Streaming', device_count: 0, total_bytes: 0, connection_count: 0, devices: [], services: [] };
const BUSY = {
	...EMPTY,
	device_count: 1,
	total_bytes: 4096,
	connection_count: 3,
	devices: [{ ip: '192.168.1.20', hostname: null, total_bytes: 4096, download_bytes: 4000, upload_bytes: 96, connections: 3, percent: 100 }],
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

	it('shows the KPIs with their trend, the chart, the services and the device table', async () => {
		const prevBusy = { ...BUSY, total_bytes: 2048, connection_count: 6 };
		const series = [
			{ timestamp: '2026-11-03T09:00:00Z', download_bytes: 1000, upload_bytes: 50, total_bytes: 1050, connections: 1 },
			{ timestamp: '2026-11-03T10:00:00Z', download_bytes: 3000, upload_bytes: 46, total_bytes: 3046, connections: 2 },
		];
		let detailCalls = 0;
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				const path = url.split('?')[0];
				const body =
					path === '/api/traffic/categories/streaming' ? (detailCalls++ === 0 ? { ...BUSY, services: [{ name: 'Netflix', bytes: 4096, connections: 3 }] } : prevBusy)
					: path === '/api/traffic/categories/streaming/bandwidth' ? { category: 'streaming', from: '', to: '', interval: '15m', series }
					: path === '/api/traffic/summary' ? { total_bytes: 8192 }
					: null;
				return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 503, json: async () => ({}) };
			}),
		);
		render(CategoryPage);
		const total = (await screen.findByText('Total bandwidth')).closest('.kpi');
		expect(total).toHaveTextContent('4.0 KB');
		expect(total).toHaveTextContent('+100.0%');
		expect(total).toHaveTextContent('vs previous 24 h');
		expect(screen.getByText('Share of network').closest('.kpi')).toHaveTextContent('50.0%');
		expect(screen.getByRole('img', { name: /^Busiest at .*, with 3\.0 KB$/ })).toBeInTheDocument();
		expect(screen.getByText('Netflix')).toBeInTheDocument();
		expect(screen.getByRole('table', { name: 'Per-device breakdown' })).toHaveTextContent('192.168.1.20');
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
