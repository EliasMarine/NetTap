import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, within, cleanup } from '@testing-library/svelte';
import { goto } from '$app/navigation';
import Page from './+page.svelte';
import { refreshPage } from '$lib/stores/pageRefresh';
import { expectNoNestedInteractive } from '../../tests/nested-interactive';

// NET-272: the page reads range, type and the pick from the URL, and writes them back with goto
const nav = vi.hoisted(() => ({ set: (_query: string) => {} }));
vi.mock('$app/stores', async () => {
	const { writable } = await import('svelte/store');
	const at = (query: string) => ({ url: new URL(`http://localhost/changelog${query}`), params: {} });
	const page = writable(at(''));
	nav.set = (query) => page.set(at(query));
	return { page };
});
vi.mock('$app/navigation', () => ({ goto: vi.fn(async () => {}) }));

const EVENT = {
	'@timestamp': '2026-11-02T08:00:00Z', event_type: 'device_joined',
	title: 'New device 10.0.0.42', description: '', metadata: {},
};

// OLD CODE START — NET-272: the page also asks for the device list (and a row's detail), so the stub routes by path
// /** /api/changelog answers from `events()`; the event types always load. */
// function stubFetch(events: () => { ok: boolean; status: number; body: unknown }) {
// 	vi.stubGlobal(
// 		'fetch',
// 		vi.fn(async (url: string) => {
// 			if (url === '/api/changelog/types') {
// 				return { ok: true, status: 200, json: async () => ({ event_types: ['device_joined', 'alert_triggered'] }) };
// 			}
// 			const r = events();
// 			return { ok: r.ok, status: r.status, json: async () => r.body };
// 		}),
// 	);
// }
// OLD CODE END

type Reply = { ok: boolean; status: number; body: unknown };
const ok = (body: unknown): Reply => ({ ok: true, status: 200, body });
const NO_DEVICES = { from: '', to: '', limit: 500, devices: [], total: 0, as_of: '', online_since: '', online_total: 0 };
let urls: URL[] = [];

/**
 * /api/changelog answers from `events()`, /api/devices from `devices()`, /api/devices/<ip> from
 * `detail(ip)` (a promise, so a test can hold it); the event types always load.
 */
function stubFetch(
	events: () => Reply,
	devices: () => Reply = () => ok(NO_DEVICES),
	detail: (ip: string) => Promise<Reply> = async () => ok({ device: { top_destinations: [] } }),
) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (raw: string) => {
			const u = new URL(raw, 'http://localhost');
			urls.push(u);
			const r =
				u.pathname === '/api/changelog/types' ? ok({ event_types: ['device_joined', 'alert_triggered'] })
				: u.pathname === '/api/changelog' ? events()
				: u.pathname === '/api/devices' ? devices()
				: u.pathname.startsWith('/api/devices/') ? await detail(decodeURIComponent(u.pathname.slice('/api/devices/'.length)))
				: { ok: false, status: 404, body: {} };
			return { ok: r.ok, status: r.status, json: async () => r.body };
		}),
	);
}

beforeEach(() => {
	urls = [];
	nav.set('');
	vi.mocked(goto).mockClear();
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
});

describe('Changelog page (#96)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('says the events could not be loaded instead of "No events found"', async () => {
		stubFetch(() => ({ ok: false, status: 500, body: {} }));
		render(Page);

		// OLD CODE: expect(await screen.findByText("Couldn't load changelog events: the request failed.")).toBeInTheDocument(); (NET-272: the chart card says it too)
		expect((await screen.findAllByText("Couldn't load changelog events: the request failed.")).length).toBeGreaterThan(0);
		expect(screen.queryByText('No events found for the selected filters.')).not.toBeInTheDocument();
	});

	it('says "No events found" when the filter really matches nothing', async () => {
		stubFetch(() => ({ ok: true, status: 200, body: { events: [], count: 0 } }));
		render(Page);

		expect(await screen.findByText('No events found for the selected filters.')).toBeInTheDocument();
		expect(screen.queryByText(/Couldn't load/)).not.toBeInTheDocument();
	});

	// NET-158: it promised alerts, settings and devices leaving, none of which is recorded
	it('names only the events NetTap records', async () => {
		stubFetch(() => ({ ok: true, status: 200, body: { events: [], count: 0 } }));
		render(Page);

		// OLD CODE: 'Events appear here when a new device joins the network or a manual storage cleanup runs.' (NET-182)
		expect(
			await screen.findByText('Events appear here when a new device joins the network, a manual storage cleanup runs, or more LAN addresses send traffic than NetTap lists.'),
		).toBeInTheDocument();
		expect(screen.queryByText(/alerts fire|settings change/)).not.toBeInTheDocument();
	});

	// NET-182: the device cap's event names itself, not its raw type
	it('labels the device limit event', async () => {
		const cap = { ...EVENT, event_type: 'device_cap_reached', title: 'More than 20,000 LAN addresses in one window' };
		stubFetch(() => ({ ok: true, status: 200, body: { events: [cap], count: 1 } }));
		render(Page);
		expect(await screen.findByText('More than 20,000 LAN addresses in one window')).toBeInTheDocument();
		expect(screen.getByText('Device limit reached')).toBeInTheDocument();
	});

	it('says a failed filter change could not load, without showing the old filter\'s events', async () => {
		let ok = true;
		stubFetch(() => (ok
			? { ok: true, status: 200, body: { events: [EVENT], count: 1 } }
			: { ok: false, status: 502, body: {} }));
		render(Page);
		expect(await screen.findByText('New device 10.0.0.42')).toBeInTheDocument();

		ok = false;
		await fireEvent.change(screen.getByLabelText('Event type'), { target: { value: 'alert_triggered' } });

		// OLD CODE: expect(await screen.findByText("Couldn't load changelog events: the request failed.")).toBeInTheDocument(); (NET-272: the chart card says it too)
		expect((await screen.findAllByText("Couldn't load changelog events: the request failed.")).length).toBeGreaterThan(0);
		expect(screen.queryByText('New device 10.0.0.42')).not.toBeInTheDocument();
		expect(screen.queryByText('No events found for the selected filters.')).not.toBeInTheDocument();
	});
});

// PLAN §5.5: the page's loader is the top bar's Refresh, and an older load never wins.
describe('Changelog page — refresh contract', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('shows the loading state while the events are on their way', async () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(Page);
		// OLD CODE: expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'true'); (NET-272: the chart card loads too)
		expect(screen.getByText('Loading changelog events').closest('[role="status"]')).toHaveAttribute('aria-busy', 'true');
		expect(screen.getByText('Loading changelog events')).toBeInTheDocument();
	});

	it('tells the top bar whether the refresh worked', async () => {
		let ok = true;
		stubFetch(() => (ok ? { ok: true, status: 200, body: { events: [EVENT], count: 1 } } : { ok: false, status: 500, body: {} }));
		render(Page);
		expect(await screen.findByText('New device 10.0.0.42')).toBeInTheDocument();
		expect(await refreshPage()).toBe('ok');
		ok = false;
		expect(await refreshPage()).toBe('failed');
		// OLD CODE: expect(screen.getByText("Couldn't load changelog events: the request failed.")).toBeInTheDocument(); (NET-272: the chart card says it too)
		expect(screen.getAllByText("Couldn't load changelog events: the request failed.").length).toBeGreaterThan(0);
	});

	it("drops an older filter's slower answer", async () => {
		const pending: Array<(body: unknown) => void> = [];
		vi.stubGlobal(
			'fetch',
			vi.fn((url: string) => {
				if (url === '/api/changelog/types') {
					return Promise.resolve({ ok: true, status: 200, json: async () => ({ event_types: ['device_joined', 'alert_triggered'] }) });
				}
				// NET-272: the device list answers at once; only the events are held
				if (url.startsWith('/api/devices')) return Promise.resolve({ ok: true, status: 200, json: async () => NO_DEVICES });
				return new Promise((resolve) => pending.push((body) => resolve({ ok: true, status: 200, json: async () => body })));
			}),
		);
		render(Page);
		await vi.waitFor(() => expect(pending).toHaveLength(1));
		await fireEvent.change(screen.getByLabelText('Event type'), { target: { value: 'alert_triggered' } });
		await vi.waitFor(() => expect(pending).toHaveLength(2));

		pending[1]({ events: [{ ...EVENT, event_type: 'alert_triggered', title: 'Alert on 10.0.0.9' }], count: 1 });
		expect(await screen.findByText('Alert on 10.0.0.9')).toBeInTheDocument();
		pending[0]({ events: [EVENT], count: 1 });
		await new Promise((r) => setTimeout(r, 0));
		expect(screen.queryByText('New device 10.0.0.42')).not.toBeInTheDocument();
		expect(screen.getByText('Alert on 10.0.0.9')).toBeInTheDocument();
	});
});

// ---------------------------------------------------------------------------
// NET-272: what each device did, with drill-down
// ---------------------------------------------------------------------------

const NOW = Date.parse('2026-11-13T12:00:30.000Z');
const ago = (ms: number) => new Date(NOW - ms).toISOString();
const MIN = 60_000;
const MAC_A = 'aa:bb:cc:dd:ee:01';
const MAC_B = 'aa:bb:cc:dd:ee:02';
const joined = (id: string, mac: string, ip: string, msAgo: number) => ({
	_id: id, '@timestamp': ago(msAgo), event_type: 'device_joined', title: `New device ${mac}`,
	description: `First seen at ${ip} (source: dhcp)`, metadata: { mac, ip, source: 'dhcp' },
});
const listRow = (ip: string, mac: string, hostname: string, total: number) => ({
	ip, mac, hostname, manufacturer: 'Apple', os_hint: null, first_seen: ago(50 * MIN), last_seen: ago(5 * MIN),
	total_bytes: total, upload_bytes: total / 4, download_bytes: (3 * total) / 4, connection_count: 12, protocols: [], alert_count: 0,
});
const deviceList = (devices: unknown[], total = devices.length) => ok({ ...NO_DEVICES, devices, total });
const dest = (ip: string) => ok({ device: { top_destinations: [{ ip, bytes: 5000, connections: 3 }] } });

/** A promise the test resolves when it chooses. */
function held<T>() {
	let resolve!: (v: T) => void;
	const promise = new Promise<T>((r) => (resolve = r));
	return { promise, resolve };
}

const table = () => screen.getByRole('table', { name: 'Changelog events' });
const loadedTable = () => screen.findByRole('table', { name: 'Changelog events' });
/** jsdom's Blob has no text() */
const read = (b: Blob) => new Promise<string>((resolve) => {
	const r = new FileReader();
	r.onload = () => resolve(String(r.result));
	r.readAsText(b);
});
const rowButton = (name: RegExp) => within(table()).getByRole('button', { name });
const lastGoto = () => new URL(String(vi.mocked(goto).mock.calls.at(-1)?.[0]), 'http://localhost');
const devicesCall = () => urls.filter((u) => u.pathname === '/api/devices').at(-1)!;

describe('Changelog v2 (NET-272)', () => {
	beforeEach(() => {
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(NOW);
	});
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
	});

	it('joins each new device to what it did over the loaded window', async () => {
		stubFetch(() => ok({ events: [joined('a', MAC_A, '192.168.1.10', 40 * MIN)], count: 1 }), () => deviceList([listRow('192.168.1.20', MAC_A, 'Kitchen iPad', 4e6)]));
		const { container } = render(Page);
		const row = within(await loadedTable()).getByText('Kitchen iPad').closest('tr')!;
		expect(within(row).getByText('192.168.1.10')).toBeInTheDocument();
		expect(within(row).getByText('1.0 MB')).toBeInTheDocument();
		expect(within(row).getByText('3.0 MB')).toBeInTheDocument();
		expect(within(row).getByText('12')).toBeInTheDocument();
		// the events and the device list asked for one window
		const events = urls.find((u) => u.pathname === '/api/changelog')!;
		expect(events.searchParams.get('limit')).toBe('1000');
		expect(devicesCall().searchParams.get('limit')).toBe('500');
		expect(devicesCall().searchParams.get('from')).toBe(events.searchParams.get('from'));
		expect(devicesCall().searchParams.get('to')).toBe(events.searchParams.get('to'));
		expect(screen.getAllByText('4.0 MB')).toHaveLength(2); // Data moved by new devices, and the busiest one
		expect(screen.getAllByText('1 of 1 matched')).toHaveLength(2);
		expectNoNestedInteractive(container);
	});

	it('keeps the events when the device list fails, and says the figures are missing', async () => {
		stubFetch(() => ok({ events: [joined('a', MAC_A, '192.168.1.10', 40 * MIN)], count: 1 }), () => ({ ok: false, status: 503, body: {} }));
		render(Page);
		expect(await screen.findByText('Traffic figures unavailable: the device list failed.')).toBeInTheDocument();
		expect(within(table()).getByText(MAC_A)).toBeInTheDocument();
		expect(await refreshPage()).toBe('partial');
	});

	// 1,000 table rows take ~1 s here and over 5 s on a CI runner, so the capped tests get more time
	it('says when the newest 1,000 events are all it has', { timeout: 30_000 }, async () => {
		const many = Array.from({ length: 1000 }, (_, i) => ({ ...EVENT, _id: `e${i}`, '@timestamp': ago(i * MIN), title: `Event ${i}` }));
		stubFetch(() => ok({ events: many, count: 1000 }));
		render(Page);
		expect(await screen.findByText("Showing the newest 1,000 events: the oldest part of this range isn't counted. Pick a shorter range.")).toBeInTheDocument();
		expect(screen.getAllByText('In the newest 1,000')).toHaveLength(2);
	});

	it('sorts by every column, both ways', async () => {
		stubFetch(() => ok({ events: [joined('a', MAC_A, '192.168.1.10', 40 * MIN), { ...EVENT, _id: 's', '@timestamp': ago(MIN) }], count: 2 }));
		render(Page);
		await screen.findByText('New device 10.0.0.42');
		const headers = within(table()).getAllByRole('columnheader');
		expect(headers.map((h) => h.textContent?.trim())).toEqual(['When', 'Event', 'What', 'IP (joined at)', 'First seen', 'Last seen', 'Seen over', 'Sent', 'Received', 'Connections']);
		for (const th of headers) {
			const button = within(th).getByRole('button');
			await fireEvent.click(button);
			if (th.textContent?.trim() !== 'When') expect(th).toHaveAttribute('aria-sort', 'descending');
			await fireEvent.click(button);
			expect(th).toHaveAttribute('aria-sort', th.textContent?.trim() === 'When' ? 'descending' : 'ascending');
		}
	});

	it('moves focus to the details and back to the row on Esc or Close', async () => {
		stubFetch(() => ok({ events: [joined('a', MAC_A, '192.168.1.10', 40 * MIN)], count: 1 }), () => deviceList([listRow('192.168.1.10', MAC_A, 'Kitchen iPad', 4e6)]));
		render(Page);
		await loadedTable();
		const opener = rowButton(/Open details: Kitchen iPad/);

		await fireEvent.click(opener);
		const heading = await screen.findByRole('heading', { name: 'Kitchen iPad', level: 2 });
		await vi.waitFor(() => expect(document.activeElement).toBe(heading));
		await fireEvent.keyDown(heading, { key: 'Escape' });
		await vi.waitFor(() => expect(document.activeElement).toBe(rowButton(/Open details: Kitchen iPad/)));
		expect(screen.queryByRole('heading', { name: 'Kitchen iPad', level: 2 })).not.toBeInTheDocument();

		await fireEvent.click(rowButton(/Open details: Kitchen iPad/));
		await fireEvent.click(await screen.findByRole('button', { name: 'Close' }));
		await vi.waitFor(() => expect(document.activeElement).toBe(rowButton(/Open details: Kitchen iPad/)));
	});

	it('asks for destinations from the busiest matched address, not where it joined, and links over the loaded window', async () => {
		const detail = vi.fn(async (ip: string) => dest(`dest-of-${ip}`));
		stubFetch(() => ok({ events: [joined('a', MAC_A, '192.168.1.10', 40 * MIN)], count: 1 }), () => deviceList([listRow('192.168.1.20', MAC_A, 'Kitchen iPad', 4e6)]), detail);
		const { container } = render(Page);
		await loadedTable();
		await fireEvent.click(rowButton(/Open details: Kitchen iPad/));

		expect(await screen.findByRole('heading', { name: 'Top destinations from 192.168.1.20' })).toBeInTheDocument();
		expect(await screen.findByText('dest-of-192.168.1.20')).toBeInTheDocument();
		expect(detail).toHaveBeenCalledWith('192.168.1.20');
		const win = devicesCall().searchParams;
		const asked = urls.find((u) => u.pathname === '/api/devices/192.168.1.20')!.searchParams;
		expect([asked.get('from'), asked.get('to')]).toEqual([win.get('from'), win.get('to')]);

		const from = encodeURIComponent(win.get('from')!);
		const to = encodeURIComponent(win.get('to')!);
		expect(screen.getByRole('link', { name: 'This device in this range' })).toHaveAttribute('href', `/devices/192.168.1.20?from=${from}&to=${to}`);
		const logs = screen.getByRole('link', { name: 'Its records in this range' }).getAttribute('href')!;
		expect(logs).toContain('source.ip%3A%22192.168.1.20%22');
		expect(logs).toContain(`&from=${from}&to=${to}`);
		expect(screen.getByRole('link', { name: /Device overview/ })).toHaveAttribute('href', `/devices/mac/${encodeURIComponent(MAC_A)}`);
		expect(screen.getByRole('link', { name: 'dest-of-192.168.1.20' })).toHaveAttribute('href', '/address/dest-of-192.168.1.20');
		expect(screen.queryByRole('link', { name: /connections/i })).not.toBeInTheDocument();
		expectNoNestedInteractive(container);
	});

	it("never shows one device's destinations under another after a fast reselect", async () => {
		const slowA = held<Reply>();
		stubFetch(
			() => ok({ events: [joined('a', MAC_A, '192.168.1.10', 40 * MIN), joined('b', MAC_B, '192.168.1.30', 30 * MIN)], count: 2 }),
			() => deviceList([listRow('192.168.1.10', MAC_A, 'Device A', 4e6), listRow('192.168.1.30', MAC_B, 'Device B', 2e6)]),
			(ip) => (ip === '192.168.1.10' ? slowA.promise : Promise.resolve(dest('dest-of-b'))),
		);
		render(Page);
		await fireEvent.click(await screen.findByRole('button', { name: /Open details: Device A/ }));
		await fireEvent.click(rowButton(/Open details: Device B/));
		expect(await screen.findByText('dest-of-b')).toBeInTheDocument();

		slowA.resolve(dest('dest-of-a'));
		await new Promise((r) => setTimeout(r, 0));
		expect(screen.queryByText('dest-of-a')).not.toBeInTheDocument();
		expect(screen.getByText('dest-of-b')).toBeInTheDocument();
	});

	it("drops a detail answer from before a reload, and asks again over the new window", async () => {
		const answers: Array<ReturnType<typeof held<Reply>>> = [];
		stubFetch(
			() => ok({ events: [joined('a', MAC_A, '192.168.1.10', 40 * MIN)], count: 1 }),
			() => deviceList([listRow('192.168.1.10', MAC_A, 'Device A', 4e6)]),
			() => {
				answers.push(held<Reply>());
				return answers.at(-1)!.promise;
			},
		);
		render(Page);
		await fireEvent.click(await screen.findByRole('button', { name: /Open details: Device A/ }));
		await vi.waitFor(() => expect(answers).toHaveLength(1));

		vi.setSystemTime(NOW + 5000);
		expect(await refreshPage()).toBe('ok');
		await vi.waitFor(() => expect(answers).toHaveLength(2));
		const details = urls.filter((u) => u.pathname === '/api/devices/192.168.1.10');
		expect(details[1].searchParams.get('to')).toBe(devicesCall().searchParams.get('to'));
		expect(details[1].searchParams.get('to')).not.toBe(details[0].searchParams.get('to'));

		answers[1].resolve(dest('from-the-new-window'));
		expect(await screen.findByText('from-the-new-window')).toBeInTheDocument();
		answers[0].resolve(dest('from-the-old-window'));
		await new Promise((r) => setTimeout(r, 0));
		expect(screen.queryByText('from-the-old-window')).not.toBeInTheDocument();
		expect(screen.getByText('from-the-new-window')).toBeInTheDocument();
	});

	it('reads the range and type from the URL on mount', async () => {
		nav.set('?range=24h&type=device_joined');
		stubFetch(() => ok({ events: [], count: 0 }));
		render(Page);
		await screen.findByText('No events found for the selected filters.');
		const events = urls.find((u) => u.pathname === '/api/changelog')!.searchParams;
		expect(events.get('type')).toBe('device_joined');
		expect(Date.parse(events.get('to')!) - Date.parse(events.get('from')!)).toBe(24 * 3_600_000);
		expect(screen.getByRole('button', { name: '24h' })).toHaveAttribute('aria-pressed', 'true');
		expect(screen.getByLabelText('Event type')).toHaveValue('device_joined');
	});

	it('a pick narrows the loaded rows; it survives a reload, and clearing it restores the whole range', async () => {
		nav.set('?range=1h');
		const events = [
			{ ...EVENT, _id: 'late', '@timestamp': ago(20_000), title: 'Late event' },
			{ ...EVENT, _id: 'early', '@timestamp': ago(30 * MIN), title: 'Early event' },
		];
		stubFetch(() => ok({ events, count: 2 }));
		render(Page);
		await screen.findByText('Early event');

		const fetched = urls.length;
		const chart = screen.getByRole('group', { name: /^Most events at/ });
		await fireEvent.keyDown(chart, { key: 'End' });
		await fireEvent.keyDown(chart, { key: 'Enter' });
		expect(urls.length).toBe(fetched); // a pick never refetches
		expect(screen.queryByText('Early event')).not.toBeInTheDocument();
		expect(screen.getByText('Late event')).toBeInTheDocument();
		const picked = lastGoto();
		expect(picked.searchParams.get('pickFrom')).toBe('2026-11-13T12:00:00.000Z');
		expect(picked.searchParams.get('pickTo')).toBe(devicesCall().searchParams.get('to'));
		expect(picked.searchParams.get('range')).toBe('1h');

		// reload with that URL a second later
		cleanup();
		vi.setSystemTime(NOW + 1000);
		nav.set(picked.search);
		render(Page);
		expect(await screen.findByText('Late event')).toBeInTheDocument();
		expect(screen.queryByText('Early event')).not.toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: 'Show the whole range' }));
		expect(screen.getByText('Early event')).toBeInTheDocument();
		expect(lastGoto().searchParams.get('pickFrom')).toBeNull();
		expect(lastGoto().searchParams.get('range')).toBe('1h');
	});

	it('focus falls back to the events heading when a pick hid the open row', async () => {
		nav.set('?range=1h');
		const events = [
			{ ...EVENT, _id: 'late', '@timestamp': ago(20_000), title: 'Late event' },
			{ ...EVENT, _id: 'early', '@timestamp': ago(30 * MIN), title: 'Early event' },
		];
		stubFetch(() => ok({ events, count: 2 }));
		render(Page);
		await fireEvent.click(await screen.findByRole('button', { name: /Open details: Early event/ }));
		const chart = screen.getByRole('group', { name: /^Most events at/ });
		await fireEvent.keyDown(chart, { key: 'End' });
		await fireEvent.keyDown(chart, { key: 'Enter' });
		await fireEvent.click(screen.getByRole('button', { name: 'Close' }));
		await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Events', level: 2 })));
	});

	it('refuses a pick on the uncounted part of a capped range, and forgets the refusal on a new range', { timeout: 30_000 }, async () => {
		nav.set('?range=1h');
		const many = Array.from({ length: 1000 }, (_, i) => ({ ...EVENT, _id: `e${i}`, '@timestamp': ago(i * 1000), title: `Event ${i}` }));
		let events = many;
		stubFetch(() => ok({ events, count: events.length }));
		render(Page);
		await screen.findByText('Event 0');
		const chart = screen.getByRole('group', { name: /Most events at/ });
		await fireEvent.keyDown(chart, { key: 'Home' });
		await fireEvent.keyDown(chart, { key: 'Enter' });
		const refusal = "That part of the range isn't counted: pick a shorter range to see it.";
		expect(screen.getByText(refusal)).toBeInTheDocument();
		expect(vi.mocked(goto).mock.calls.some(([url]) => String(url).includes('pickFrom'))).toBe(false);
		// review M1: the note belonged to the old range's chart
		events = many.slice(0, 3);
		await fireEvent.click(screen.getByRole('button', { name: '24h' }));
		// wait for the new range's rows (the loading state hides the old ones, and the note, meanwhile)
		await vi.waitFor(() => expect(screen.getByText('Event 2')).toBeInTheDocument());
		expect(screen.queryByText('Event 3')).not.toBeInTheDocument();
		expect(screen.queryByText(refusal)).not.toBeInTheDocument();
	});

	it('exports the joined columns, spreadsheet-safe', async () => {
		const blobs: Blob[] = [];
		vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: (b: Blob) => (blobs.push(b), 'blob:x'), revokeObjectURL: () => {} }));
		const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
		stubFetch(() => ok({ events: [joined('a', MAC_A, '192.168.1.10', 40 * MIN)], count: 1 }), () => deviceList([listRow('192.168.1.10', MAC_A, '=HYPERLINK("x")', 4e6)]));
		render(Page);
		await screen.findAllByText('=HYPERLINK("x")');

		await fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }));
		const csv = await read(blobs[0]);
		expect(csv.split('\n')[0]).toContain('"Device name","MAC"');
		expect(csv).toContain(`"'=HYPERLINK(""x"")","${MAC_A}"`);
		expect((click.mock.contexts[0] as HTMLAnchorElement).download).toBe('nettap-changelog-2026-11-13.csv');

		await fireEvent.click(screen.getByRole('button', { name: 'Export JSON' }));
		expect(JSON.parse(await read(blobs[1]))[0]).toMatchObject({ _id: 'a', joined: { name: '=HYPERLINK("x")', total: 4e6 } });
		click.mockRestore();
	});
});
