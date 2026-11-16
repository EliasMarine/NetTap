import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import HomePage from './+page.svelte';

// Chart gaps: a slot with no connection record is "No data", not 0 B.

const point = (hour: number, connections: number, bytes = 1_000_000) => ({
	timestamp: `2026-11-15T${String(hour).padStart(2, '0')}:00:00.000Z`,
	orig_bytes: 0, resp_bytes: 0, upload_bytes: bytes / 10, download_bytes: connections ? bytes : 0, local_bytes: 0,
	total_bytes: connections ? bytes + bytes / 10 : 0, connections,
});
const PROTOCOLS = { from: '', to: '', protocols: [{ name: 'tcp', count: 900 }, { name: 'udp', count: 100 }], services: [] };

/** Replies by path: a body, a promise of one (a reply held back), or nothing for a 503. */
function stubDaemon(replies: Record<string, unknown>): void {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			const body = await replies[url.split('?')[0]];
			return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 503, json: async () => ({}) };
		}),
	);
}

const chart = () => screen.queryByRole('group', { name: /^Bandwidth over the/ });

beforeEach(() => {
	// jsdom has no ResizeObserver; the bandwidth chart needs one to mount
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(() => vi.unstubAllGlobals());

describe('Home — slots with no connection record', () => {
	it('draws a slot with no record as a "No data" band, and its tooltip says so', async () => {
		stubDaemon({ '/api/traffic/bandwidth': { from: '', to: '', interval: '1h', series: [point(1, 0), point(2, 0), point(3, 5), point(4, 7)] }, '/api/traffic/protocols': PROTOCOLS });
		const { container } = render(HomePage);
		await waitFor(() => expect(chart()).toBeInTheDocument());
		expect(container.querySelectorAll('rect.nodata')).toHaveLength(1);
		await fireEvent.keyDown(chart()!, { key: 'Home' });
		expect(container.querySelector('.tip-tx')?.textContent).toMatch(/ · no data$/);
	});

	it('shows the empty state for a window with no record at all, not a hatched chart', async () => {
		stubDaemon({ '/api/traffic/bandwidth': { from: '', to: '', interval: '1h', series: [point(1, 0), point(2, 0)] }, '/api/traffic/protocols': PROTOCOLS });
		const { container } = render(HomePage);
		expect(await screen.findByText('No bandwidth data for this window')).toBeInTheDocument();
		expect(chart()).not.toBeInTheDocument();
		expect(container.querySelector('rect.nodata')).toBeNull();
	});
});
