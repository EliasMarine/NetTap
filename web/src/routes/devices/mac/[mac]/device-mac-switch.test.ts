import { describe, it, expect, vi, afterEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/svelte';
import type { Writable } from 'svelte/store';
import { page } from '$app/stores';
import Page from './+page.svelte';

// NET-200 (PR #214 review): moving from device A to device B, a save made before B has loaded
// must not go to A under B's address; it is refused with a reason, and B then loads as usual.

vi.mock('$app/stores', async () => {
	const { writable } = await import('svelte/store');
	const mac = 'D0:21:F9:5E:35:32';
	return { page: writable({ url: new URL(`http://localhost/devices/mac/${mac}`), params: { mac } }) };
});

// NET-205: the live bandwidth card polls its own endpoint; here it stays loading, out of this test's fetch
const { getLiveBandwidth } = vi.hoisted(() => ({
	getLiveBandwidth: vi.fn((_key: { mac: string } | { ip: string }, _signal?: AbortSignal) => new Promise<never>(() => {})),
}));
vi.mock('$api/live-bandwidth', async (importOriginal) => ({ ...(await importOriginal<typeof import('$api/live-bandwidth')>()), getLiveBandwidth }));

const A = 'D0:21:F9:5E:35:32';
const B = 'A4:83:E7:00:00:01';
const dev = (mac: string, name: string) => ({
	device: {
		mac, ips: ['192.168.1.20'], hostnames: [], manufacturer: null, friendly_name: null,
		display_name: name, category: 'computer', first_seen: '2026-11-01T00:00:00Z', last_seen: '2026-11-02T00:00:00Z', is_new: false,
	},
});
const TRAFFIC = { traffic: { mac: A, total_bytes: 0, inbound_bytes: 0, outbound_bytes: 0, connection_count: 0, top_destinations: [], top_protocols: [] } };

describe('Device by MAC page — saving while another device loads', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('refuses the save until the next device has loaded', async () => {
		let releaseB: () => void = () => {};
		const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
			const path = url.split('?')[0];
			if (init?.method) return { ok: true, status: 200, json: async () => dev(A, 'Renamed A') };
			if (path.endsWith('/traffic')) return { ok: true, status: 200, json: async () => TRAFFIC };
			if (path === `/api/devices/registry/${encodeURIComponent(B)}`) {
				await new Promise<void>((resolve) => (releaseB = resolve));
				return { ok: true, status: 200, json: async () => dev(B, 'Laptop B') };
			}
			return { ok: true, status: 200, json: async () => dev(A, 'Phone A') };
		});
		vi.stubGlobal('fetch', fetchMock);
		render(Page);
		await vi.waitFor(() => expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Phone A'));

		(page as unknown as Writable<unknown>).set({ url: new URL(`http://localhost/devices/mac/${B}`), params: { mac: B } });
		await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledWith(`/api/devices/registry/${encodeURIComponent(B)}`));

		await fireEvent.click(screen.getByRole('button', { name: 'Rename' }));
		await fireEvent.input(screen.getByLabelText('Name'), { target: { value: 'Mine' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
		expect(await screen.findByRole('alert')).toHaveTextContent('This page is still loading another device. Try again in a moment.');
		expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PUT')).toBe(false);

		releaseB();
		await vi.waitFor(() => expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Laptop B'));
	});
});
