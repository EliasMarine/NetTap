import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { readable, get } from 'svelte/store';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import Page from './+page.svelte';

// #89: the daemon wraps both replies ({device}, {from, to, traffic}); the page read the wrappers,
// crashed on device.ips.length and stayed on its loader. Its in/out and destination bytes were
// missing from the traffic reply too, so they would have read 0.

const { MAC } = vi.hoisted(() => ({ MAC: 'D0:21:F9:5E:35:32' }));
vi.mock('$app/stores', () => ({
	page: readable({ url: new URL(`http://localhost/devices/mac/${MAC}`), params: { mac: MAC } }),
}));

const REPLIES: Record<string, unknown> = {
	[`/api/devices/registry/${encodeURIComponent(MAC)}`]: {
		device: {
			mac: MAC,
			ips: ['192.168.1.1'],
			hostnames: ['gateway'],
			manufacturer: 'Ubiquiti Inc',
			friendly_name: null,
			display_name: 'Ubiquiti gateway',
			category: 'infrastructure',
			first_seen: '2026-11-01T00:00:00Z',
			last_seen: '2026-11-02T00:00:00Z',
			is_new: false,
		},
	},
	[`/api/devices/registry/${encodeURIComponent(MAC)}/traffic`]: {
		from: '',
		to: '',
		traffic: {
			mac: MAC,
			total_bytes: 3 * 1024 * 1024,
			inbound_bytes: 2 * 1024 * 1024,
			outbound_bytes: 1024 * 1024,
			connection_count: 1234,
			protocols: ['udp'],
			top_protocols: [{ name: 'udp', count: 1234 }],
			top_destinations: [{ ip: '192.168.1.174', connections: 600, bytes: 512 * 1024 }],
		},
	},
};

describe('Device by MAC page', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('loads with the daemon replies and shows real in/out and destination bytes', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				const body = REPLIES[url.split('?')[0]];
				return body
					? { ok: true, status: 200, json: async () => body }
					: { ok: false, status: 404, json: async () => ({}) };
			}),
		);

		render(Page);

		await vi.waitFor(() => expect(screen.getByText('2.0MB in / 1.0MB out')).toBeInTheDocument());
		expect(screen.getAllByText('1,234')).toHaveLength(2); // connections and the UDP count
		expect(screen.getByText('512KB')).toBeInTheDocument();
		// OLD CODE START — 2026-11-03 UI redesign: the spinner's class; the loading state is now a CardState status
		// expect(document.querySelector('.loading-state')).toBeNull();
		// OLD CODE END
		expect(screen.queryByRole('status')).not.toBeInTheDocument();
	});

	// NET-158: the figures match the MAC or any address the device used, over the whole range,
	// and the "New" chip read is_new (cleared on the next update) instead of first_seen
	it('says what its traffic matches and marks New by first seen in the last 24 hours', async () => {
		const reg = REPLIES[`/api/devices/registry/${encodeURIComponent(MAC)}`] as { device: Record<string, unknown> };
		const fresh = { device: { ...reg.device, first_seen: new Date(Date.now() - 60 * 60 * 1000).toISOString(), is_new: false } };
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				const path = url.split('?')[0];
				const body = path === `/api/devices/registry/${encodeURIComponent(MAC)}` ? fresh : REPLIES[path];
				return { ok: true, status: 200, json: async () => body };
			}),
		);

		render(Page);

		expect(
			await screen.findByText('Traffic matching its MAC or any address it has used; another device may have used one since.'),
		).toBeInTheDocument();
		expect(screen.getByText('New')).toBeInTheDocument();
	});

	it('shows no New chip for a device first seen days ago, even with is_new still set', async () => {
		const reg = REPLIES[`/api/devices/registry/${encodeURIComponent(MAC)}`] as { device: Record<string, unknown> };
		const old = { device: { ...reg.device, is_new: true } };
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				const path = url.split('?')[0];
				const body = path === `/api/devices/registry/${encodeURIComponent(MAC)}` ? old : REPLIES[path];
				return { ok: true, status: 200, json: async () => body };
			}),
		);

		render(Page);

		await screen.findByText('Ubiquiti gateway');
		expect(screen.queryByText('New')).not.toBeInTheDocument();
	});
});

// #96: every failure read as "Device not found"
describe('Device by MAC page — failed request', () => {
	afterEach(() => vi.unstubAllGlobals());

	function stubStatus(status: number): void {
		vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status, json: async () => ({}) })));
	}

	it('says the device failed to load when the daemon errors', async () => {
		stubStatus(503);
		render(Page);
		expect(await screen.findByText(`Couldn't load device ${MAC}: the request failed.`)).toBeInTheDocument();
		expect(screen.queryByText('Device not found')).not.toBeInTheDocument();
	});

	it('still says "Device not found" when the registry has no such device', async () => {
		stubStatus(404);
		render(Page);
		expect(await screen.findByText('Device not found')).toBeInTheDocument();
	});
});

// PLAN.md §5.5: the top bar's Refresh goes through this page's loader
describe('Device by MAC page — page refresh contract', () => {
	afterEach(() => vi.unstubAllGlobals());

	/** The daemon replies above, minus the paths in `fail` (those answer 503). */
	function stub(fail: string[] = []): void {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				const path = url.split('?')[0];
				const body = fail.some((f) => path.endsWith(f)) ? undefined : REPLIES[path];
				return body
					? { ok: true, status: 200, json: async () => body }
					: { ok: false, status: 503, json: async () => ({}) };
			}),
		);
	}

	it('reports ok when both requests succeed, and unregisters on unmount', async () => {
		stub();
		const { unmount } = render(Page);
		await screen.findByText('2.0MB in / 1.0MB out');
		expect(await refreshPage()).toBe('ok');
		unmount();
		expect(get(pageRefresh).available).toBe(false);
	});

	it('reports partial and says so when only the traffic fails', async () => {
		stub(['/traffic']);
		render(Page);
		expect(await screen.findAllByText("Couldn't load traffic: the request failed.")).not.toHaveLength(0);
		expect(screen.getByRole('heading', { level: 1, name: 'Ubiquiti gateway' })).toBeInTheDocument();
		expect(await refreshPage()).toBe('partial');
	});

	it('reports failed when both fail, keeping the MAC as the heading', async () => {
		stub([`/${encodeURIComponent(MAC)}`, '/traffic']);
		render(Page);
		await screen.findByText(`Couldn't load device ${MAC}: the request failed.`);
		expect(screen.getByRole('heading', { level: 1, name: MAC })).toBeInTheDocument();
		expect(await refreshPage()).toBe('failed');
	});

	it('shows the loading state while the device loads', () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(Page);
		expect(screen.getByRole('status')).toHaveTextContent('Loading device details');
	});
});
