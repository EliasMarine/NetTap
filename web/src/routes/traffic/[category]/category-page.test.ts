import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { readable } from 'svelte/store';
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
		const card = (await screen.findByText('% of Network')).closest('.stat-card');
		expect(card).toHaveTextContent('—');
		expect(card).not.toHaveTextContent('0.0%');
		expect(screen.getByText("Couldn't load bandwidth over time: the request failed.")).toBeInTheDocument();
	});
});
