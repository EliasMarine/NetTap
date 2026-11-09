import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { get, type Writable } from 'svelte/store';
import { goto } from '$app/navigation';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import { customRange } from '$lib/utils/drilldown';
import Page from './+page.svelte';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
// NET-160 slice 2b-3: the page reads its window and tab from the URL
const pageStore = vi.hoisted(() => ({ value: null as unknown as Writable<{ url: URL }> }));
vi.mock('$app/stores', async () => {
	const { writable } = await import('svelte/store');
	pageStore.value = writable({ url: new URL('http://localhost/devices') });
	return { page: pageStore.value };
});
/** Navigate the mocked page store to /devices with this query. */
const goTo = (query = '') => pageStore.value.set({ url: new URL(`http://localhost/devices${query}`) });

describe('Devices', () => {
	it('should export a Svelte component', async () => {
		const module = await import('./+page.svelte');
		expect(module.default).toBeDefined();
	});
});

/** Replies by path; any path not listed answers 503. Returns the fetch mock. */
function stubDaemon(replies: Record<string, unknown>): ReturnType<typeof vi.fn> {
	const f = vi.fn(async (url: string) => {
		const body = replies[url.split('?')[0]];
		return body
			? { ok: true, status: 200, json: async () => body }
			: { ok: false, status: 503, json: async () => ({}) };
	});
	vi.stubGlobal('fetch', f);
	return f;
}

// #96: a failed device list read as "0 devices seen on the network" and "No devices seen yet."
describe('Devices — failed request', () => {
	afterEach(() => vi.unstubAllGlobals());

	function stubDevices(reply: { ok: boolean; status: number; body?: unknown }): void {
		vi.stubGlobal('fetch', vi.fn(async () => ({ ok: reply.ok, status: reply.status, json: async () => reply.body })));
	}

	it('says the list failed instead of "No devices seen yet"', async () => {
		stubDevices({ ok: false, status: 503 });
		render(Page);
		expect(await screen.findByText("Couldn't load devices: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('No devices seen yet.')).not.toBeInTheDocument();
		expect(screen.queryByText(/0 devices seen/)).not.toBeInTheDocument();
	});

	it('still says "No devices seen yet." when the network really has none', async () => {
		// OLD CODE: body { from: '', to: '', limit: 200, devices: [] } (slice 2b-3: the page refuses a reply without its reading)
		stubDevices({ ok: true, status: 200, body: listReply([]) });
		render(Page);
		expect(await screen.findByText('No devices seen yet.')).toBeInTheDocument();
	});
});

const DEVICE = {
	ip: '192.168.1.10', mac: null, hostname: 'laptop', manufacturer: null, os_hint: null,
	first_seen: '', last_seen: '', total_bytes: 1000, connection_count: 5, protocols: [], alert_count: 0,
};

/** A KPI card's number, found by its label. */
function kpiValue(label: string): string | null | undefined {
	return screen.getByText(label).closest('.kpi')?.querySelector('.kpi-num')?.textContent;
}

/** A device list reply: the rows plus the reading's four fields (NET-160 slice 2b-3). */
function listReply(devices: unknown[], extra: Record<string, unknown> = {}) {
	return {
		from: '', to: '', limit: 500, devices, total: devices.length, online_total: 0,
		as_of: '2026-11-06T12:00:00.000Z', online_since: '2026-11-06T11:55:00.000Z', ...extra,
	};
}

// Total Devices was the length of a 200-row list, so a bigger network read 200.
describe('Devices — Total Devices is the exact count', () => {
	afterEach(() => vi.unstubAllGlobals());

	// OLD CODE START — NET-160 slice 2b-3: the total came from /api/devices/count, a separate reading
	// stubDaemon({ '/api/devices': { from: '', to: '', limit: 200, devices: [DEVICE] }, '/api/devices/count': { from: '', to: '', count: 350 } });
	// OLD CODE END
	it('shows the device count, not the length of the list', async () => {
		stubDaemon({ '/api/devices': listReply([DEVICE], { total: 350 }) });
		render(Page);
		expect(await screen.findByText(/350 devices seen on the network · showing the 1 busiest/)).toBeInTheDocument();
		expect(kpiValue('Total devices')).toBe('350');
	});

	it('shows the same count as the list when the network is small', async () => {
		stubDaemon({ '/api/devices': listReply([DEVICE], { total: 1 }) });
		render(Page);
		expect(await screen.findByText(/^1 devices seen on the network/)).toBeInTheDocument();
		expect(kpiValue('Total devices')).toBe('1');
		expect(screen.queryByText(/busiest/)).not.toBeInTheDocument();
	});

	// OLD CODE START — NET-160 slice 2b-3: the count failed on its own while the list loaded; one reply answers both now
	// it("shows '—' and says so when the count fails, never the list length", async () => {
	// 	stubDaemon({ '/api/devices': { from: '', to: '', limit: 200, devices: [DEVICE] } });
	// 	…"Couldn't load the device count: the request failed.", Total '—', no "1 devices seen on the network"
	// OLD CODE END
	it("shows '—' and says so when the list fails, never 0", async () => {
		stubDaemon({});
		render(Page);
		expect(await screen.findByText("Couldn't load the device count: the request failed.")).toBeInTheDocument();
		expect(kpiValue('Total devices')).toBe('—');
		expect(kpiValue('Online now')).toBe('—');
		expect(screen.queryByText(/devices seen on the network/)).not.toBeInTheDocument();
	});
});

// "New (24h)" filtered the list on first_seen, the first record in the page's own 24 h window, so
// every device was new (54 of 54 on the G11); "Online Now" counted only inside the listed devices.
describe('Devices — Online Now and New (24h) are exact', () => {
	afterEach(() => vi.unstubAllGlobals());

	const recent = new Date(Date.now() - 60 * 60 * 1000).toISOString();
	const DEVICES = [1, 2, 3].map((n) => ({
		ip: `192.168.1.${n}`, mac: null, hostname: `d${n}`, manufacturer: null, os_hint: null,
		first_seen: recent, last_seen: new Date().toISOString(), total_bytes: 1000 * n, connection_count: 5, protocols: [], alert_count: 0,
	}));

	function stub(newCount: { ok: boolean; count?: number }): ReturnType<typeof vi.fn> {
		const f = vi.fn(async (url: string) => {
			const [path] = url.split('?');
			const reply = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
			// OLD CODE START — NET-160 slice 2b-3: the totals came from /api/devices/count
			// if (path === '/api/devices') return reply({ from: '', to: '', limit: 500, devices: DEVICES });
			// // OLD CODE START — NET-158: Online now asked a 5-minute from/to range
			// // if (path === '/api/devices/count') return reply({ from: '', to: '', count: query.includes('from=') ? 7 : 350 });
			// // OLD CODE END
			// if (path === '/api/devices/count') return reply({ from: '', to: '', count: query.includes('active_since=') ? 7 : 350 });
			// OLD CODE END
			// one reading: the online cutoff is a minute ago's daemon clock less 5 minutes, so every listed row is Online
			if (path === '/api/devices') {
				const asOf = Date.now();
				return reply(listReply(DEVICES, {
					total: 350, online_total: 7, as_of: new Date(asOf).toISOString(), online_since: new Date(asOf - 5 * 60_000).toISOString(),
				}));
			}
			if (path === '/api/devices/registry/new-count' && newCount.ok) return reply({ count: newCount.count, since: '' });
			return { ok: false, status: 503, json: async () => ({}) };
		});
		vi.stubGlobal('fetch', f);
		return f;
	}

	it('counts devices NetTap first saw in 24 h and devices with traffic in the last 5 min', async () => {
		const f = stub({ ok: true, count: 0 });
		render(Page);
		await screen.findByText(/350 devices seen/);
		await vi.waitFor(() => expect(kpiValue('New in 24 h')).toBe('0'));
		expect(kpiValue('Online now')).toBe('7');
		// OLD CODE START — NET-160 slice 2b-3: Online now was its own count request
		// const online = f.mock.calls.map((c) => String(c[0])).find((u) => u.startsWith('/api/devices/count?'));
		// const q = new URLSearchParams(online?.split('?')[1]);
		// // OLD CODE START — NET-158: a 5-minute range needed 3 records in it; the table needs one
		// // expect(Date.parse(q.get('to') ?? '') - Date.parse(q.get('from') ?? '')).toBe(5 * 60 * 1000);
		// // OLD CODE END
		// // the table's population (the list's 24 h range) whose newest record is under 5 minutes old
		// expect(q.has('from')).toBe(false);
		// expect(Date.now() - Date.parse(q.get('active_since') ?? '')).toBeGreaterThanOrEqual(5 * 60 * 1000);
		// expect(Date.now() - Date.parse(q.get('active_since') ?? '')).toBeLessThan(6 * 60 * 1000);
		// OLD CODE END
		// Online now is the list reply's online_total; no count request is made
		expect(f.mock.calls.some((c) => String(c[0]).startsWith('/api/devices/count'))).toBe(false);
		expect(screen.getAllByText('Online').length).toBe(3); // the same rule on every listed row
		// the list holds 3 of 350 devices, so the category pills say whose counts they are
		expect(screen.getByText('counts for the 3 busiest devices')).toBeInTheDocument();
	});

	it("shows '—' and says so when the new-device count fails", async () => {
		stub({ ok: false });
		render(Page);
		expect(await screen.findByText("Couldn't load the new-device count: the request failed.")).toBeInTheDocument();
		expect(kpiValue('New in 24 h')).toBe('—');
	});
});

// Capture modes and a registry device for the table and refresh tests (By type: devices-by-type.test.ts)

const MIRROR = { mode: 'mirror', interface: 'enp1s0' };
const BRIDGE = { mode: 'bridge', interface: 'br0' };
const LIST_FROM = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();

function reg(mac: string, ip: string, category: string, extra: Record<string, unknown> = {}) {
	return {
		mac, ips: [ip], hostnames: [], manufacturer: 'Acme', friendly_name: null, display_name: `dev-${mac}`,
		category, first_seen: '2026-11-01T00:00:00Z', last_seen: new Date().toISOString(), is_new: false, ...extra,
	};
}

const PHONE = reg('aa:01', '192.168.1.21', 'phone', { display_name: 'Kitchen iPad', is_new: true });
const LIST = listReply([{ ...DEVICE, ip: '192.168.1.21', hostname: 'ipad', total_bytes: 2048, connection_count: 12 }], { from: LIST_FROM });

describe('Devices — All devices table', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.clearAllMocks();
	});

	const TWO = listReply([
		{ ...DEVICE, ip: '192.168.1.10', hostname: 'laptop', category: 'computer', total_bytes: 5000 },
		{ ...DEVICE, ip: '192.168.1.9', hostname: 'phone', category: 'phone', total_bytes: 100 },
	], { from: LIST_FROM });

	it('sorts on every column, filters by type, and opens a device', async () => {
		stubDaemon({ '/api/capture/mode': BRIDGE, '/api/devices': TWO, '/api/devices/count': { count: 2 } });
		render(Page);
		const table = await screen.findByRole('table', { name: 'All devices' });

		const headers = within(table).getAllByRole('columnheader');
		expect(headers).toHaveLength(10);
		for (const th of headers) expect(within(th).getByRole('button')).toBeInTheDocument();
		// busiest first
		expect(within(table).getAllByRole('row')[1]).toHaveTextContent('192.168.1.10');

		await fireEvent.click(screen.getByRole('button', { name: 'Phones 1' }));
		expect(within(table).getAllByRole('row')).toHaveLength(2);
		expect(within(table).getAllByRole('row')[1]).toHaveTextContent('192.168.1.9');

		await fireEvent.click(screen.getByRole('button', { name: 'Open phone' }));
		expect(goto).toHaveBeenCalledWith('/devices/192.168.1.9');
	});

	it('says when no device matches and resets the filters', async () => {
		stubDaemon({ '/api/capture/mode': BRIDGE, '/api/devices': TWO, '/api/devices/count': { count: 2 } });
		render(Page);
		await screen.findByRole('table', { name: 'All devices' });

		await fireEvent.input(screen.getByLabelText('Search devices'), { target: { value: 'nothing-like-this' } });
		expect(screen.getByText('No devices match these filters')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Reset filters' }));
		expect(screen.getByRole('table', { name: 'All devices' })).toBeInTheDocument();
	});

	// NET-200: the owner's name heads the Name cell (over the UniFi name, with no UniFi tag) and search finds it
	it("shows the owner's name in the Name cell and finds the device by it", async () => {
		const named = listReply([
			{ ...DEVICE, ip: '192.168.1.10', hostname: 'eli-mbp', custom_name: 'Work laptop', unifi_name: 'MacBook', category: 'computer', total_bytes: 5000 },
			{ ...DEVICE, ip: '192.168.1.9', hostname: 'phone', category: 'phone', total_bytes: 100 },
		], { from: LIST_FROM });
		stubDaemon({ '/api/capture/mode': BRIDGE, '/api/devices': named, '/api/devices/count': { count: 2 } });
		render(Page);
		const table = await screen.findByRole('table', { name: 'All devices' });
		const row = within(table).getAllByRole('row')[1];
		expect(row).toHaveTextContent('Work laptop');
		expect(within(row).queryByText('UniFi')).not.toBeInTheDocument();

		await fireEvent.input(screen.getByLabelText('Search devices'), { target: { value: 'work lap' } });
		expect(within(table).getAllByRole('row')).toHaveLength(2);
		expect(within(table).getAllByRole('row')[1]).toHaveTextContent('192.168.1.10');
	});

	// the IPv6 notes only: in bridge mode NET-225 also shows its own note about devices behind NAT
	const ipv6Notes = () => screen.queryAllByRole('note').filter((n) => !n.textContent?.includes('inline bridge mode'));

	// NET-226: the type and OS are guesses; the figures count both directions and IPv6 by MAC
	it('shows the type and OS as guesses with what they came from, and what the figures count', async () => {
		const guessed = listReply([
			{ ...DEVICE, ip: '192.168.1.10', category: 'computer', category_basis: 'os', os_hint: 'Windows', os_basis: 'web traffic', total_bytes: 5000 },
			{ ...DEVICE, ip: '192.168.1.9', hostname: 'thing', category: 'unknown', category_basis: null, total_bytes: 100 },
		], { from: LIST_FROM });
		stubDaemon({ '/api/capture/mode': BRIDGE, '/api/devices': guessed, '/api/devices/count': { count: 2 } });
		render(Page);
		const table = await screen.findByRole('table', { name: 'All devices' });
		const [, guess, unknown] = within(table).getAllByRole('row');

		expect(within(guess).getByText('Likely computer')).toBeInTheDocument();
		expect(within(guess).getByText('from its OS')).toBeInTheDocument();
		expect(within(guess).getByText('Likely Windows')).toBeInTheDocument();
		expect(within(guess).getByText('from web traffic')).toBeInTheDocument();
		expect(within(unknown).getByText('Unknown')).toBeInTheDocument();
		expect(within(unknown).queryByText(/^from /)).not.toBeInTheDocument();
		expect(
			screen.getByText('Traffic and connections count both directions and include IPv6, matched to each device by its MAC address.'),
		).toBeInTheDocument();
		expect(ipv6Notes()).toHaveLength(0);
	});

	it.each([
		['router', "The device at 192.168.1.1 forwards other devices' traffic (it's the router), so only its link-local IPv6 is counted."],
		['no_gateway', "IPv6 traffic other than link-local isn't counted for this period: no internet traffic showed which device is the router."],
	])('says what IPv6 the list left out when the reason is %s', async (reason, text) => {
		const rows = listReply([
			{ ...DEVICE, ip: '192.168.1.1', ipv6_left_out: 30, ipv6_left_out_reason: reason, total_bytes: 5000 },
			{ ...DEVICE, ip: '192.168.1.9', ipv6_left_out: reason === 'no_gateway' ? 4 : 0, ipv6_left_out_reason: reason === 'no_gateway' ? reason : null },
		], { from: LIST_FROM });
		stubDaemon({ '/api/capture/mode': BRIDGE, '/api/devices': rows, '/api/devices/count': { count: 2 } });
		render(Page);
		await screen.findByRole('table', { name: 'All devices' });
		// one notice per reason, however many devices share it
		expect(ipv6Notes()).toHaveLength(1);
		expect(ipv6Notes()[0]).toHaveTextContent(text);
	});
});

// PLAN.md §5.5: the top bar's Refresh and "Updated" go through the page's loader
describe('Devices — page refresh contract', () => {
	afterEach(() => vi.unstubAllGlobals());

	const ALL = {
		'/api/capture/mode': MIRROR,
		'/api/devices/registry': { devices: [PHONE], total: 1 },
		'/api/devices': LIST,
		'/api/devices/count': { from: '', to: '', count: 1 },
		'/api/devices/registry/new-count': { count: 0, since: '' },
	};

	it('registers its loader and reports ok when every request succeeds', async () => {
		stubDaemon(ALL);
		const { unmount } = render(Page);
		expect(get(pageRefresh).available).toBe(true);
		await screen.findByRole('region', { name: 'Phones and tablets' });
		expect(await refreshPage()).toBe('ok');
		unmount();
		expect(get(pageRefresh).available).toBe(false);
	});

	it('reports partial when one request fails', async () => {
		stubDaemon({ ...ALL, '/api/devices/registry': undefined });
		render(Page);
		await screen.findByText("Couldn't load devices: the request failed.");
		expect(await refreshPage()).toBe('partial');
	});

	it('reports failed when every request fails', async () => {
		stubDaemon({});
		render(Page);
		await screen.findByText("Couldn't load devices: the request failed.");
		expect(await refreshPage()).toBe('failed');
	});
});

// NET-160 slice 2b-3: Home's Devices card opens this page over the card's own window. The page
// reads range / from+to / view from the URL, and one list reply answers the table, Total devices
// and Online now, with the status column read off that reply's clock.
describe('Devices — the URL window and one reading', () => {
	const NOW = new Date('2026-11-06T12:00:30.000Z');
	const FROM = '2026-11-01T08:00:00.000Z';
	const TO = '2026-11-01T20:00:00.000Z';
	const MIN = 60_000;

	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
		vi.mocked(goto).mockClear();
		goTo('');
	});

	let listCalls: URL[] = [];
	/** The daemon: bridge mode, no new devices, and `list` for /api/devices (undefined → 503). */
	function stub(list: (url: URL) => unknown): ReturnType<typeof vi.fn> {
		listCalls = [];
		const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
		const f = vi.fn(async (input: string) => {
			const url = new URL(input, 'http://localhost');
			if (url.pathname === '/api/devices') {
				listCalls.push(url);
				const body = await list(url);
				return body ? ok(body) : { ok: false, status: 502, json: async () => ({}) };
			}
			if (url.pathname === '/api/capture/mode') return ok(BRIDGE);
			if (url.pathname === '/api/devices/registry/new-count') return ok({ count: 0, since: '' });
			return { ok: false, status: 503, json: async () => ({}) };
		});
		vi.stubGlobal('fetch', f);
		return f;
	}

	/** A reply echoing the asked window, read at `asOf` (daemon clock, ms). */
	function reading(url: URL, devices: unknown[], extra: Record<string, unknown> = {}, asOf = NOW.getTime()) {
		return listReply(devices, {
			from: url.searchParams.get('from'), to: url.searchParams.get('to'),
			as_of: new Date(asOf).toISOString(), online_since: new Date(asOf - 5 * MIN).toISOString(), ...extra,
		});
	}

	const kpi = (label: string) => screen.getByText(label).closest('.kpi') as HTMLElement;
	const note = (label: string) => kpi(label).querySelector('.kpi-meta')?.textContent?.trim();
	const sub = (label: string) => kpi(label).querySelector('.kpi-sub')?.textContent?.trim();
	/** The status a table row shows, by the row's IP. */
	async function statusOf(ip: string): Promise<string | null | undefined> {
		const table = await screen.findByRole('table', { name: 'All devices' });
		return within(table).getAllByRole('row').find((r) => r.textContent?.includes(ip))?.querySelector('.res')?.textContent;
	}
	const hoursAsked = (u: URL) => (Date.parse(u.searchParams.get('to')!) - Date.parse(u.searchParams.get('from')!)) / 3_600_000;
	const pressed = (name: string) => screen.getByRole('button', { name }).getAttribute('aria-pressed');

	it('asks for the range in the URL, ending now, and says so on every figure', async () => {
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(NOW);
		goTo('?range=7d');
		const f = stub((url) => reading(url, [DEVICE]));
		render(Page);
		await vi.waitFor(() => expect(kpiValue('Total devices')).toBe('1'));
		expect(hoursAsked(listCalls[0])).toBe(168);
		expect(listCalls[0].searchParams.get('to')).toBe(NOW.toISOString());
		expect(listCalls[0].searchParams.get('limit')).toBe('500');
		expect(pressed('7d')).toBe('true');
		expect(note('Total devices')).toBe('Last 7 days');
		expect(note('Top consumer')).toBe('Last 7 days');
		expect(note('New in 24 h')).toBe('Last 24 hours'); // its own window
		expect(screen.getByText('Busiest first · traffic in the last 7 days')).toBeInTheDocument();
		expect(f.mock.calls.some((c) => String(c[0]).startsWith('/api/devices/count'))).toBe(false);
	});

	it("opens an exact from/to as Custom and passes it exactly", async () => {
		goTo(`?from=${FROM}&to=${TO}&range=24h`);
		stub((url) => reading(url, [DEVICE]));
		render(Page);
		await vi.waitFor(() => expect(kpiValue('Total devices')).toBe('1'));
		expect(listCalls[0].searchParams.get('from')).toBe(FROM);
		expect(listCalls[0].searchParams.get('to')).toBe(TO);
		expect(pressed('Custom')).toBe('true');
		const words = customRange(FROM, TO)!.words;
		expect(note('Total devices')).toBe(words.charAt(0).toUpperCase() + words.slice(1));
		expect(screen.getByText(`Busiest first · traffic in the ${words}`)).toBeInTheDocument();
	});

	it('reads an unknown range as 24 hours, with no Custom pill', async () => {
		goTo('?range=2h');
		stub((url) => reading(url, [DEVICE]));
		render(Page);
		await vi.waitFor(() => expect(kpiValue('Total devices')).toBe('1'));
		expect(hoursAsked(listCalls[0])).toBe(24);
		expect(pressed('24h')).toBe('true');
		expect(screen.queryByRole('button', { name: 'Custom' })).not.toBeInTheDocument();
		expect(note('Total devices')).toBe('Last 24 hours');
	});

	// NET-195: the list derives its range from the URL; with none, the fallback is the saved default
	describe('the saved default range (NET-195)', () => {
		beforeEach(() => {
			localStorage.clear();
			localStorage.setItem('nettap-display-settings', JSON.stringify({ defaultRange: '7d' }));
		});
		afterEach(() => localStorage.clear());

		it('opens on the saved range when the link has none, with one reading', async () => {
			stub((url) => reading(url, [DEVICE]));
			render(Page);
			await vi.waitFor(() => expect(kpiValue('Total devices')).toBe('1'));
			expect(listCalls.map(hoursAsked)).toEqual([168]);
			expect(pressed('7d')).toBe('true');
			expect(note('Total devices')).toBe('Last 7 days');
		});

		it("opens on the link's range over the saved one", async () => {
			goTo('?range=1h');
			stub((url) => reading(url, [DEVICE]));
			render(Page);
			await vi.waitFor(() => expect(kpiValue('Total devices')).toBe('1'));
			expect(listCalls.map(hoursAsked)).toEqual([1]);
			expect(pressed('1h')).toBe('true');
		});
	});

	it('opens All devices from view=all, even in mirror mode', async () => {
		goTo('?view=all&range=24h');
		stubDaemon({
			'/api/capture/mode': MIRROR,
			'/api/devices/registry': { devices: [PHONE], total: 1 },
			'/api/devices': LIST,
		});
		render(Page);
		expect(await screen.findByRole('table', { name: 'All devices' })).toBeInTheDocument();
		expect(screen.getByRole('tab', { name: 'All devices' })).toHaveAttribute('aria-selected', 'true');
	});

	it('a range pill keeps the tab and drops the exact window', async () => {
		goTo(`?view=all&from=${FROM}&to=${TO}&range=24h`);
		stub((url) => reading(url, [DEVICE]));
		render(Page);
		await vi.waitFor(() => expect(kpiValue('Total devices')).toBe('1'));
		await fireEvent.click(screen.getByRole('button', { name: '7d' }));
		expect(goto).toHaveBeenCalledTimes(1);
		const [href] = vi.mocked(goto).mock.calls[0];
		const target = new URL(String(href), 'http://localhost');
		expect(target.pathname).toBe('/devices');
		expect(Object.fromEntries(target.searchParams)).toEqual({ range: '7d', view: 'all' });
	});

	it('Total devices and Online now come from the list reply, and the partial note from its total', async () => {
		const f = stub((url) => reading(url, [DEVICE], { total: 3, online_total: 2 }));
		render(Page);
		await vi.waitFor(() => expect(kpiValue('Total devices')).toBe('3'));
		expect(kpiValue('Online now')).toBe('2');
		expect(sub('Online now')).toBe('Traffic in the last 5 minutes');
		expect(screen.getByText('counts for the 1 busiest devices')).toBeInTheDocument();
		const paths = f.mock.calls.map((c) => String(c[0]).split('?')[0]);
		expect(paths.filter((p) => p === '/api/devices')).toHaveLength(1); // one device request
		expect(paths).not.toContain('/api/devices/count');
	});

	it('a row last seen exactly at online_since is Online, even when the reply took 3 seconds', async () => {
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(NOW);
		const asOf = NOW.getTime();
		stub((url) => {
			vi.setSystemTime(asOf + 3_000); // the reply lands 3 s after the daemon read its clock
			return reading(url, [{ ...DEVICE, last_seen: new Date(asOf - 5 * MIN).toISOString() }], { online_total: 1 }, asOf);
		});
		render(Page);
		expect(await statusOf(DEVICE.ip)).toBe('Online');
		expect(kpiValue('Online now')).toBe('1');
	});

	it("marks the rows the daemon counted, to the millisecond of its clock", async () => {
		const rows = [
			['192.168.1.1', '2026-11-06T11:55:00.123Z'], // = online_since: online
			['192.168.1.2', '2026-11-06T11:55:00.122Z'], // a millisecond older: idle
			['192.168.1.3', '2026-11-06T11:00:00.123Z'], // = as_of − 1 h: idle
			['192.168.1.4', '2026-11-06T11:00:00.122Z'], // older: offline
		].map(([ip, last_seen]) => ({ ...DEVICE, ip, last_seen }));
		stub((url) => reading(url, rows, { as_of: '2026-11-06T12:00:00.123Z', online_since: '2026-11-06T11:55:00.123Z', online_total: 1 }));
		render(Page);
		expect(await statusOf('192.168.1.1')).toBe('Online');
		expect(await statusOf('192.168.1.2')).toBe('Idle');
		expect(await statusOf('192.168.1.3')).toBe('Idle');
		expect(await statusOf('192.168.1.4')).toBe('Offline');
		expect(kpiValue('Online now')).toBe('1');
	});

	it("shows Online now as '—' for a Custom window that ended before the last 5 minutes", async () => {
		goTo(`?from=${FROM}&to=${TO}`);
		stub((url) => reading(url, [DEVICE], { online_total: 0 }));
		render(Page);
		await vi.waitFor(() => expect(kpiValue('Total devices')).toBe('1'));
		expect(kpiValue('Online now')).toBe('—');
		expect(sub('Online now')).toBe('This window ended before the last 5 minutes');
		// PR #191 review: the rows can't say Online, Idle or Offline for a window that ended either
		expect(await statusOf(DEVICE.ip)).toBe('—');
	});

	// PR #191 review: back to the last good window after a failed one kept the failed one's error
	it('going back to a loaded window after a failed one shows loading, not the error', async () => {
		let answer: 'ok' | 'fail' | 'hold' = 'ok';
		stub((url) => (answer === 'ok' ? reading(url, [DEVICE], { total: 4 }) : answer === 'fail' ? undefined : new Promise(() => {})));
		render(Page);
		await vi.waitFor(() => expect(kpiValue('Total devices')).toBe('4'));
		answer = 'fail';
		goTo('?range=7d');
		expect(await screen.findByText("Couldn't load devices: the request failed.")).toBeInTheDocument();
		answer = 'hold';
		goTo('');
		await vi.waitFor(() => expect(screen.getByText('Loading devices')).toBeInTheDocument());
		expect(screen.queryByText("Couldn't load devices: the request failed.")).not.toBeInTheDocument();
		expect(sub('Total devices')).toBe('Seen on the network');
	});

	it('reads a list reply without the reading (an older daemon) as a failed load, not all offline', async () => {
		stub((url) => ({ from: url.searchParams.get('from'), to: url.searchParams.get('to'), limit: 500, devices: [DEVICE] }));
		render(Page);
		expect(await screen.findByText("Couldn't load devices: the request failed.")).toBeInTheDocument();
		expect(kpiValue('Total devices')).toBe('—');
		expect(screen.queryByRole('table', { name: 'All devices' })).not.toBeInTheDocument();
	});

	it('a failed refresh of the same window keeps the list and its total together', async () => {
		let fail = false;
		stub((url) => (fail ? undefined : reading(url, [DEVICE], { total: 4, online_total: 1 })));
		render(Page);
		await vi.waitFor(() => expect(kpiValue('Total devices')).toBe('4'));
		fail = true;
		expect(await refreshPage()).toBe('partial');
		expect(kpiValue('Total devices')).toBe('4');
		expect(kpiValue('Online now')).toBe('1');
		expect(sub('Total devices')).toBe("Couldn't refresh the device count; showing the last figures loaded.");
		expect(await statusOf(DEVICE.ip)).toBeDefined();
		expect(screen.getByText("Couldn't refresh devices; showing the last figures loaded.")).toBeInTheDocument();
	});

	it('a failed window change shows the error with neither the old list nor its total', async () => {
		let fail = false;
		stub((url) => (fail ? undefined : reading(url, [DEVICE], { total: 4 })));
		render(Page);
		await vi.waitFor(() => expect(kpiValue('Total devices')).toBe('4'));
		fail = true;
		goTo('?range=7d');
		expect(await screen.findByText("Couldn't load devices: the request failed.")).toBeInTheDocument();
		expect(kpiValue('Total devices')).toBe('—');
		expect(kpiValue('Online now')).toBe('—');
		expect(screen.queryByRole('table', { name: 'All devices' })).not.toBeInTheDocument();
		expect(note('Total devices')).toBe('Last 7 days');
	});

	it('clears the figures on a window change and drops a late reply for the old window', async () => {
		const pending: { url: URL; answer: (body: unknown) => void }[] = [];
		stub((url) => new Promise((answer) => pending.push({ url, answer })));
		render(Page);
		await vi.waitFor(() => expect(pending).toHaveLength(1));
		pending[0].answer(reading(pending[0].url, [DEVICE], { total: 24 }));
		await vi.waitFor(() => expect(kpiValue('Total devices')).toBe('24'));

		void refreshPage(); // a 24 h refresh, still out when the window changes
		await vi.waitFor(() => expect(pending).toHaveLength(2));
		goTo('?range=7d');
		await vi.waitFor(() => expect(pending).toHaveLength(3));
		expect(hoursAsked(pending[2].url)).toBe(168);
		// the 24 h figures go at once: nothing shows under the 7 d words until 7 d answers
		expect(kpiValue('Total devices')).toBe('—');
		expect(note('Total devices')).toBe('Last 7 days');
		expect(screen.getByText('Loading devices')).toBeInTheDocument();

		pending[2].answer(reading(pending[2].url, [DEVICE], { total: 168 }));
		await vi.waitFor(() => expect(kpiValue('Total devices')).toBe('168'));
		pending[1].answer(reading(pending[1].url, [DEVICE], { total: 999 }));
		await new Promise((r) => setTimeout(r, 0));
		expect(kpiValue('Total devices')).toBe('168');
		expect(note('Total devices')).toBe('Last 7 days');
	});
});
