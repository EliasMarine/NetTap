import { describe, it, expect, vi, afterEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/svelte';
import type { Writable } from 'svelte/store';
// OLD CODE: import { page } from '$app/stores'; (kit 3 removed it; the mock below keeps the store in pageHolder; NET-315)
import Page from './+page.svelte';

// NET-331: Watch on the MAC page saves by the registry's MAC through the page's save, and the page
// keeps the committed watch from the reply (null included), so reopening the panel shows it.

// kit 3: $app/stores → $app/state; the store mock below now backs a $app/state page (NET-315)
const pageHolder = vi.hoisted(() => ({ store: null as unknown as Writable<unknown> }));
vi.mock('$app/state', async () => (await import('../../../../tests/app-navigation.svelte')).stateFromStores(async () => {
	const { writable } = await import('svelte/store');
	const mac = 'D0:21:F9:5E:35:32';
	pageHolder.store = writable({ url: new URL(`http://localhost/devices/mac/${mac}`), params: { mac } });
	return { page: pageHolder.store as Writable<{ url: URL; params: Record<string, string> }> };
}));
// the live bandwidth card polls its own endpoint; here it stays loading, out of this test's fetch
vi.mock('$api/live-bandwidth', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/live-bandwidth')>()),
	getLiveBandwidth: vi.fn(() => new Promise<never>(() => {})),
}));

const MAC = 'D0:21:F9:5E:35:32';
const DETAILS = `/api/devices/registry/${encodeURIComponent(MAC)}/details`;
const dev = (watch: number | null) => ({
	mac: MAC, ips: ['192.168.1.20'], hostnames: [], manufacturer: null, friendly_name: null, display_name: 'NAS',
	category: 'computer', first_seen: '2026-11-01T00:00:00Z', last_seen: '2026-11-02T00:00:00Z', is_new: false, watch_after_min: watch,
});
const TRAFFIC = { traffic: { mac: MAC, total_bytes: 0, inbound_bytes: 0, outbound_bytes: 0, connection_count: 0, top_destinations: [], top_protocols: [] } };

/** The registry answers `loaded` until a PUT, whose reply is `saved`. */
function stub(loaded: number | null, saved: number | null) {
	const fn = vi.fn(async (url: string, init?: RequestInit) => {
		if (init?.method === 'PUT') return { ok: true, status: 200, json: async () => ({ device: dev(saved) }) };
		if (url.split('?')[0].endsWith('/traffic')) return { ok: true, status: 200, json: async () => TRAFFIC };
		return { ok: true, status: 200, json: async () => ({ device: dev(loaded) }) };
	});
	vi.stubGlobal('fetch', fn);
	return fn;
}

const watchBox = () => screen.getByLabelText('Tell me when it goes quiet for') as HTMLSelectElement;
const chosen = () => watchBox().selectedOptions[0].textContent;

async function pick(label: string) {
	await fireEvent.click(await screen.findByRole('button', { name: 'Watch' }));
	const option = Array.from(watchBox().options).find((o) => o.textContent === label)!;
	await fireEvent.change(watchBox(), { target: { value: option.value } });
	await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
}

function deferred<T>() {
	let resolve!: (v: T) => void;
	const promise = new Promise<T>((r) => (resolve = r));
	return { promise, resolve };
}

describe('Device by MAC page — Watch (NET-331)', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('saves the watch by the registry MAC, and reopening shows the saved time', async () => {
		const fn = stub(null, 60);
		render(Page);
		await vi.waitFor(() => expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('NAS'));
		await pick('1 hour');
		expect(await screen.findByText('Watch saved.')).toBeInTheDocument();
		const put = fn.mock.calls.find(([, init]) => init?.method === 'PUT');
		expect(put?.[0]).toBe(DETAILS);
		expect(put?.[1]?.body).toBe('{"watch_after_min":60}');

		await fireEvent.click(screen.getByRole('button', { name: 'Watch' }));
		expect(chosen()).toBe('1 hour');
	});

	it('clears the watch, and reopening shows Off', async () => {
		stub(240, null);
		render(Page);
		await fireEvent.click(await screen.findByRole('button', { name: 'Watch' }));
		expect(chosen()).toBe('4 hours');
		await fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
		await pick('Off');
		expect(await screen.findByText('Watch turned off.')).toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: 'Watch' }));
		expect(chosen()).toBe('Off');
	});

	// review M5: the same-device guard, for a watch
	it('shows the next device with its own watch when a save for the last one lands after moving on', async () => {
		const B = 'A4:83:E7:00:00:01';
		const save = deferred<{ ok: boolean; status: number; json: () => Promise<unknown> }>();
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string, init?: RequestInit) => {
				if (init?.method === 'PUT') return save.promise;
				const path = url.split('?')[0];
				if (path.endsWith('/traffic')) return { ok: true, status: 200, json: async () => TRAFFIC };
				const isB = path === `/api/devices/registry/${encodeURIComponent(B)}`;
				return { ok: true, status: 200, json: async () => ({ device: isB ? { ...dev(30), mac: B, display_name: 'Laptop B' } : dev(null) }) };
			}),
		);
		render(Page);
		await vi.waitFor(() => expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('NAS'));
		await pick('1 day'); // A's save hangs

		// OLD CODE: (page as unknown as Writable<unknown>).set(…); (kit 3: the store now lives in pageHolder; NET-315)
		pageHolder.store.set({ url: new URL(`http://localhost/devices/mac/${B}`), params: { mac: B } });
		await vi.waitFor(() => expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Laptop B'));
		save.resolve({ ok: true, status: 200, json: async () => ({ device: dev(1440) }) });
		await new Promise((r) => setTimeout(r, 0)); // every hop of the save (fetch, json, onsave) has run

		await fireEvent.click(await screen.findByRole('button', { name: 'Watch' }));
		expect(chosen()).toBe('30 minutes');
	});
});
