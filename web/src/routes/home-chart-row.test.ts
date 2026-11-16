import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import HomePage from './+page.svelte';

// Chart resize: the bandwidth chart drew at 300 px, then grew when the taller Network protocols card
// beside it settled (later on the G11 at every range). It is now written once that card has settled.

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

describe('Home — the bandwidth chart and the protocols card beside it', () => {
	it('draws the chart only once the protocols card has settled, so it never redraws taller', async () => {
		let release!: (v: unknown) => void;
		const held = new Promise((resolve) => (release = resolve));
		stubDaemon({ '/api/traffic/bandwidth': { from: '', to: '', interval: '1h', series: [point(1, 5), point(2, 7), point(3, 6)] }, '/api/traffic/protocols': held });
		render(HomePage);
		expect(await screen.findByText('Loading network protocols')).toBeInTheDocument();
		// the bandwidth reply is in, but the row is not complete yet
		await new Promise((r) => setTimeout(r, 20));
		expect(screen.getByText('Loading bandwidth over time')).toBeInTheDocument();
		expect(chart()).not.toBeInTheDocument();
		release(PROTOCOLS);
		await waitFor(() => expect(chart()).toBeInTheDocument());
		expect(screen.queryByText('Loading network protocols')).not.toBeInTheDocument();
	});

	it('still draws the chart when the protocols request fails', async () => {
		stubDaemon({ '/api/traffic/bandwidth': { from: '', to: '', interval: '1h', series: [point(1, 5), point(2, 7)] } });
		render(HomePage);
		await waitFor(() => expect(chart()).toBeInTheDocument());
		expect(screen.getByText("Couldn't load network protocols: the request failed.")).toBeInTheDocument();
	});
});
