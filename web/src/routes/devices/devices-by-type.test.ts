import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within, cleanup } from '@testing-library/svelte';
import Page from './+page.svelte';
import { expectNoNestedInteractive } from '../../tests/nested-interactive';

// By type: Home's device cards, moved here (PLAN.md §3, §5.6). The first describe is
// routes/home-device-cards.test.ts ported from Home's markup to this view; the second pins the
// mirror-mode condition and the failure messages Home used.

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
// NET-160 slice 2b-3: the page reads its window from the URL; these tests use the default (24 hours)
vi.mock('$app/stores', async () => {
	const { readable } = await import('svelte/store');
	return { page: readable({ url: new URL('http://localhost/devices') }) };
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

const requested = (f: ReturnType<typeof vi.fn>, path: string) => f.mock.calls.some((c) => String(c[0]).split('?')[0] === path);

// ---- ported from routes/home-device-cards.test.ts --------------------------------------------
// On the G11 every Device Overview card read Traffic "--" and Connections "--": the registry
// carries no traffic, and Home never joined the device list's figures to it.

const FROM = '2026-11-01T22:00:00Z';

/** The list reply's reading (NET-160 slice 2b-3), read at `asOf`: the page refuses a reply without it. */
function reading(asOf: string = new Date().toISOString()) {
	return { online_total: 0, as_of: asOf, online_since: new Date(Date.parse(asOf) - 5 * 60_000).toISOString() };
}

function stubHomeDaemon(): void {
	stubDaemon({
		'/api/capture/mode': { mode: 'mirror', interface: 'enp4s0' },
		'/api/devices/registry': {
			count: 2,
			devices: [
				{ mac: 'D0:21:F9:5E:35:32', ips: ['192.168.1.1', '10.10.0.1'], hostnames: [], manufacturer: 'Ubiquiti Inc',
				  friendly_name: null, display_name: 'Gateway', category: 'infrastructure', first_seen: FROM,
				  last_seen: '2026-11-02T21:00:00+00:00', is_new: false },
				{ mac: 'AA:00:00:00:00:01', ips: ['192.168.1.9'], hostnames: [], manufacturer: null,
				  friendly_name: null, display_name: 'Old printer', category: 'infrastructure', first_seen: '2026-10-01T00:00:00Z',
				  last_seen: '2026-11-01T10:00:00+00:00', is_new: false },
			],
		},
		'/api/devices': {
			from: FROM, to: '2026-11-02T22:00:00Z', limit: 500, total: 2, ...reading('2026-11-02T22:00:00.000Z'),
			devices: [
				// decimal units (NET-166): the two IPs' 2,000,000 bytes read 2.0 MB (1.9 MB in 1024-based units)
				{ ip: '192.168.1.1', total_bytes: 1_000_000, connection_count: 1200, last_seen: '2026-11-02T21:50:00Z' },
				{ ip: '10.10.0.1', total_bytes: 1_000_000, connection_count: 34, last_seen: '2026-11-02T21:40:00Z' },
			].map((d) => ({ mac: null, hostname: null, manufacturer: null, os_hint: null, first_seen: FROM, protocols: [], alert_count: 0, ...d })),
		},
	});
}

// OLD CODE START — 2026-11-03 UI redesign: Home's DeviceGrid markup (.device-card, .stat-label)
// function stat(device: string, label: string): string | undefined {
// 	const card = screen.getByText(device).closest('.device-card');
// 	const labelEl = Array.from(card?.querySelectorAll('.stat-label') ?? []).find((el) => el.textContent?.trim() === label);
// 	return labelEl?.nextElementSibling?.textContent?.trim();
// }
// OLD CODE END
/** A By type card's figure, found by the card's device name and the figure's label. */
function stat(device: string, label: string): string | undefined {
	const card = screen.getByText(device).closest('.dev-card');
	const labelEl = Array.from(card?.querySelectorAll('.meta-k') ?? []).find((el) => el.textContent?.trim() === label);
	return labelEl?.nextElementSibling?.textContent?.trim();
}

describe('Devices By type — device cards carry the range traffic', () => {
	afterEach(() => vi.unstubAllGlobals());

	// slice 2b-3 review: completeness came from `length < 500`, so exactly 500 devices read as cut off
	it('reads a quiet device as 0 B when the list holds all of exactly 500 devices', async () => {
		stubDaemon({
			'/api/capture/mode': { mode: 'mirror', interface: 'enp4s0' },
			'/api/devices/registry': {
				devices: [
					{ mac: 'AA:00:00:00:00:01', ips: ['192.168.9.9'], hostnames: [], manufacturer: null,
					  friendly_name: null, display_name: 'Old printer', category: 'infrastructure', first_seen: '2026-10-01T00:00:00Z',
					  last_seen: '2026-11-01T10:00:00+00:00', is_new: false },
				],
				total: 1,
			},
			'/api/devices': {
				from: FROM, to: '2026-11-02T22:00:00Z', limit: 500, total: 500, ...reading('2026-11-02T22:00:00.000Z'),
				devices: Array.from({ length: 500 }, (_, i) => ({
					ip: `10.0.${Math.floor(i / 250)}.${(i % 250) + 1}`, total_bytes: 100, connection_count: 3, last_seen: '2026-11-02T21:00:00Z',
					mac: null, hostname: null, manufacturer: null, os_hint: null, first_seen: FROM, protocols: [], alert_count: 0,
				})),
			},
		});
		render(Page);
		await within(await screen.findByRole('tabpanel', { name: 'By type' })).findByText('Old printer');
		await vi.waitFor(() => expect(stat('Old printer', 'Traffic')).toBe('0 B'));
	});

	it("sums a device's IPs from the device list, and a device quiet all range reads 0 B", async () => {
		stubHomeDaemon();
		render(Page);
		await within(await screen.findByRole('tabpanel', { name: 'By type' })).findByText('Gateway');
		await vi.waitFor(() => expect(stat('Gateway', 'Traffic')).toBe('2.0 MB'));
		expect(stat('Gateway', 'Connections')).toBe((1234).toLocaleString());
		expect(stat('Old printer', 'Traffic')).toBe('0 B');
		expect(stat('Old printer', 'Connections')).toBe('0');
	});
});

// NET-158: the card's figure is the listed addresses' traffic; the page said nothing about it, and
// the "New" chip read is_new (cleared on the device's next update) while "New in 24 h" counts first_seen
describe('Devices By type — what a card counts', () => {
	afterEach(() => vi.unstubAllGlobals());

	const hourAgo = new Date(Date.now() - 60 * 60 * 1000).toISOString();

	function stubCards(): void {
		stubDaemon({
			'/api/capture/mode': { mode: 'mirror', interface: 'enp4s0' },
			'/api/devices/registry': {
				devices: [
					{ mac: 'D0:21:F9:5E:35:32', ips: ['192.168.1.1', '10.10.0.1', '192.168.1.200'], hostnames: [], manufacturer: null,
					  friendly_name: null, display_name: 'Gateway', category: 'infrastructure', first_seen: hourAgo,
					  last_seen: hourAgo, is_new: false },
					{ mac: 'AA:00:00:00:00:02', ips: ['192.168.1.30'], hostnames: [], manufacturer: null,
					  friendly_name: null, display_name: 'Old laptop', category: 'computer', first_seen: '2026-10-01T00:00:00Z',
					  last_seen: hourAgo, is_new: true },
				],
				total: 2,
			},
			'/api/devices': {
				from: FROM, to: '', limit: 500, total: 3, ...reading(),
				devices: [
					{ ip: '192.168.1.1', total_bytes: 1000, connection_count: 10, last_seen: hourAgo },
					{ ip: '10.10.0.1', total_bytes: 1000, connection_count: 5, last_seen: hourAgo },
					{ ip: '192.168.1.30', total_bytes: 512, connection_count: 3, last_seen: hourAgo },
				].map((d) => ({ mac: null, hostname: null, manufacturer: null, os_hint: null, first_seen: FROM, protocols: [], alert_count: 0, ...d })),
			},
		});
	}

	it('says the traffic is from the listed addresses, and how many of them were listed', async () => {
		stubCards();
		render(Page);
		await within(await screen.findByRole('tabpanel', { name: 'By type' })).findByText('Gateway');
		expect(screen.getByText('Traffic in the last 24 hours from the listed addresses each device has used.')).toBeInTheDocument();
		// the new-device banner links Gateway too, so read the card in the By type panel
		const gateway = within(screen.getByRole('tabpanel', { name: 'By type' })).getByRole('link', { name: /Gateway/ });
		expect(within(gateway).getByText('(2 of 3 addresses listed)')).toBeInTheDocument();
		const laptop = within(screen.getByRole('tabpanel', { name: 'By type' })).getByRole('link', { name: /Old laptop/ });
		expect(within(laptop).queryByText(/addresses listed/)).not.toBeInTheDocument();
	});

	it('marks New by first seen in the last 24 hours, the "New in 24 h" rule', async () => {
		stubCards();
		render(Page);
		await within(await screen.findByRole('tabpanel', { name: 'By type' })).findByText('Gateway');
		// the new-device banner links Gateway too, so read the card in the By type panel
		const gateway = within(screen.getByRole('tabpanel', { name: 'By type' })).getByRole('link', { name: /Gateway/ });
		expect(within(gateway).getByText('New')).toBeInTheDocument(); // is_new already cleared
		const laptop = within(screen.getByRole('tabpanel', { name: 'By type' })).getByRole('link', { name: /Old laptop/ });
		expect(within(laptop).queryByText('New')).not.toBeInTheDocument(); // first seen in October
	});
});

// ---- the mirror-mode condition and Home's failure messages ------------------------------------

const DEVICE = {
	ip: '192.168.1.10', mac: null, hostname: 'laptop', manufacturer: null, os_hint: null,
	first_seen: '', last_seen: '', total_bytes: 1000, connection_count: 5, protocols: [], alert_count: 0,
};
const MIRROR = { mode: 'mirror', interface: 'enp1s0' };
const BRIDGE = { mode: 'bridge', interface: 'br0' };
const LIST_FROM = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();

function reg(mac: string, ip: string, category: string, extra: Record<string, unknown> = {}) {
	return {
		mac, ips: [ip], hostnames: [], manufacturer: 'Acme', friendly_name: null, display_name: `dev-${mac}`,
		category, first_seen: '2026-11-01T00:00:00Z', last_seen: new Date().toISOString(), is_new: false, ...extra,
	};
}

// first seen an hour ago: new by the New chip's 24-hour rule, which the banner shares
const PHONE = reg('aa:01', '192.168.1.21', 'phone', { display_name: 'Kitchen iPad', is_new: true, first_seen: new Date(Date.now() - 3_600_000).toISOString() });
const PLUG = reg('aa:02', '192.168.1.22', 'iot', { display_name: 'Smart plug' });
const LIST = {
	from: LIST_FROM, to: '', limit: 500, total: 1, ...reading(),
	devices: [{ ...DEVICE, ip: '192.168.1.21', hostname: 'ipad', total_bytes: 2000, connection_count: 12 }],
};

describe('Devices — By type', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.clearAllMocks();
	});

	it('opens on By type in mirror mode, with the cards grouped by type and the list traffic merged', async () => {
		stubDaemon({
			'/api/capture/mode': MIRROR,
			'/api/devices/registry': { devices: [PHONE, PLUG], total: 2 },
			'/api/devices': LIST,
			'/api/devices/count': { from: '', to: '', count: 2 },
		});
		render(Page);

		const phones = await screen.findByRole('region', { name: 'Phones and tablets' });
		expect(screen.getByRole('tab', { name: 'By type' })).toHaveAttribute('aria-selected', 'true');
		expect(screen.getByRole('region', { name: 'IoT devices' })).toBeInTheDocument();
		const card = within(phones).getByRole('link');
		expect(card).toHaveAttribute('href', `/devices/mac/${encodeURIComponent('aa:01')}`);
		expect(within(card).getByText('Kitchen iPad')).toBeInTheDocument();
		expect(within(card).getByText('192.168.1.21')).toBeInTheDocument();
		// the list's traffic for its IP, as Home merged it
		expect(within(card).getByText('2.0 KB')).toBeInTheDocument();
		expect(within(card).getByText('12')).toBeInTheDocument();
		// the plug's IP isn't in a complete list and it was seen in range: still unknown, not 0
		const plug = within(screen.getByRole('region', { name: 'IoT devices' })).getByRole('link');
		expect(within(plug).getAllByText('—')).toHaveLength(2);
		// the new-device banner moved here from Home, fed from the same registry
		expect(screen.getByText('1 new device detected')).toBeInTheDocument();
	});

	it('does not ask for the registry outside mirror mode, and opens on All devices', async () => {
		const f = stubDaemon({ '/api/capture/mode': BRIDGE, '/api/devices': LIST, '/api/devices/count': { count: 1 } });
		render(Page);

		expect(await screen.findByRole('table', { name: 'All devices' })).toBeInTheDocument();
		expect(screen.getByRole('tab', { name: 'All devices' })).toHaveAttribute('aria-selected', 'true');
		expect(requested(f, '/api/devices/registry')).toBe(false);
		expect(screen.queryByText(/new device/)).not.toBeInTheDocument();

		await fireEvent.click(screen.getByRole('tab', { name: 'By type' }));
		expect(screen.getByText('Device cards by type show in mirror mode')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Show all devices' }));
		expect(screen.getByRole('table', { name: 'All devices' })).toBeInTheDocument();
	});

	// #96, as on Home: a failed registry is not "No devices detected yet"
	it('says the registry failed instead of showing no cards', async () => {
		stubDaemon({ '/api/capture/mode': MIRROR, '/api/devices': LIST });
		render(Page);

		const panel = await screen.findByRole('tabpanel', { name: 'By type' });
		expect(await within(panel).findByText("Couldn't load devices: the request failed.")).toBeInTheDocument();
		expect(within(panel).getByRole('button', { name: 'Try again' })).toBeInTheDocument();
		expect(within(panel).queryByText('No devices yet')).not.toBeInTheDocument();
	});

	// #96, as on Home: a failed refresh keeps the last cards and says so
	it('keeps the last cards and says so when a refresh of the registry fails', async () => {
		const replies: Record<string, unknown> = {
			'/api/capture/mode': MIRROR,
			'/api/devices/registry': { devices: [PHONE], total: 1 },
			'/api/devices': LIST,
		};
		stubDaemon(replies);
		render(Page);
		await screen.findByRole('region', { name: 'Phones and tablets' });

		const { refreshPage } = await import('$lib/stores/pageRefresh');
		stubDaemon({ ...replies, '/api/devices/registry': undefined });
		await refreshPage();
		expect(await screen.findByText("Couldn't refresh devices; showing the last figures loaded.")).toBeInTheDocument();
		expect(within(screen.getByRole('region', { name: 'Phones and tablets' })).getByText('Kitchen iPad')).toBeInTheDocument();
	});

	it('says the registry is empty when it really is', async () => {
		stubDaemon({ '/api/capture/mode': MIRROR, '/api/devices/registry': { devices: [], total: 0 }, '/api/devices': LIST });
		render(Page);
		expect(await screen.findByText('No devices yet')).toBeInTheDocument();
	});

	it('says the capture mode failed instead of guessing bridge', async () => {
		stubDaemon({ '/api/devices': LIST });
		render(Page);
		await screen.findByRole('table', { name: 'All devices' });

		await fireEvent.click(screen.getByRole('tab', { name: 'By type' }));
		expect(screen.getByText("Couldn't load the capture mode: the request failed.")).toBeInTheDocument();
	});

	it('shows a loading state while the requests are pending', async () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(Page);
		expect(screen.getByRole('status')).toHaveTextContent('Loading devices');
	});
});

// ---- NET-180: cards that line up, and a compact List layout ----------------------------------
// The owner: some cards had Traffic, Connections and Last seen higher than their neighbours (a card
// with no maker was a line shorter), and By type had no list view.

describe('Devices By type — cards line up, and a List layout with the same figures', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.clearAllMocks();
		vi.restoreAllMocks();
		localStorage.clear();
	});

	const MINUTE = 60_000;
	const ago = (ms: number) => new Date(Date.now() - ms).toISOString();
	const LAYOUT_FROM = ago(24 * 60 * MINUTE);

	function computer(mac: string, name: string, ips: string[], manufacturer: string | null, lastSeen: string) {
		return {
			mac, ips, hostnames: [], manufacturer, friendly_name: null, display_name: name, category: 'computer',
			first_seen: '2026-10-01T00:00:00Z', last_seen: lastSeen, is_new: false,
		};
	}

	// Most recent first, as the cards are: A, B, C, D, E. C has the most traffic.
	const A = 'DESKTOP-1H4Q4HV'; // no maker, the owner's screenshot
	const B = 'Work laptop'; // 2 of its 3 addresses listed
	const C = 'Media box';
	const D = 'Spare laptop'; // seen in range but not listed: unknown, not 0
	const E = 'Old printer'; // quiet all range: a real 0

	function listRow(ip: string, total_bytes: number, connection_count: number, last_seen: string) {
		return { ...DEVICE, ip, hostname: null, total_bytes, connection_count, last_seen, first_seen: LAYOUT_FROM };
	}

	const LAYOUT_REPLIES: Record<string, unknown> = {
		'/api/capture/mode': MIRROR,
		'/api/devices/registry': {
			total: 5,
			devices: [
				computer('aa:10', A, ['192.168.1.10'], null, ago(5 * MINUTE)),
				computer('aa:11', B, ['192.168.1.11', '10.0.0.11', '192.168.1.111'], 'Example Corp', ago(45 * MINUTE)),
				computer('aa:12', C, ['192.168.1.12'], 'Acme', ago(120 * MINUTE)),
				computer('aa:13', D, ['192.168.1.13'], 'Beta Labs', ago(180 * MINUTE)),
				computer('aa:14', E, ['192.168.1.14'], 'Zed Print', ago(48 * 60 * MINUTE)),
			],
		},
		'/api/devices': {
			from: LAYOUT_FROM, to: '', limit: 500, total: 4, ...reading(),
			devices: [
				listRow('192.168.1.12', 1024 * 1024, 10, ago(120 * MINUTE)),
				listRow('192.168.1.11', 1024, 600, ago(45 * MINUTE)),
				listRow('10.0.0.11', 1024, 600, ago(50 * MINUTE)),
				listRow('192.168.1.10', 512, 9, ago(5 * MINUTE)),
			],
		},
	};

	const panel = () => screen.getByRole('tabpanel', { name: 'By type' });
	const computers = () => screen.getByRole('region', { name: 'Computers' });
	const showList = () => fireEvent.click(within(screen.getByRole('group', { name: 'Layout' })).getByRole('button', { name: 'List' }));
	const showCards = () => fireEvent.click(within(screen.getByRole('group', { name: 'Layout' })).getByRole('button', { name: 'Cards' }));
	const listTable = () => screen.getByRole('table', { name: 'Computers, as a list' });
	const bodyRows = () => within(listTable()).getAllByRole('row').slice(1);
	const rowNames = () => bodyRows().map((r) => r.querySelector('.who-name')?.textContent);
	const cardNames = () => [...computers().querySelectorAll('.dev-card .dev-name')].map((el) => el.textContent);
	const card = (name: string) => within(panel()).getByRole('link', { name: new RegExp(name) });
	const row = (name: string) => within(listTable()).getByRole('button', { name: `Open ${name}` }).closest('tr')!;

	/** What a card says: maker line, address, the three figures. */
	function cardFigures(name: string) {
		const el = card(name);
		const fig = (label: string) =>
			[...el.querySelectorAll('.meta-k')].find((k) => k.textContent === label)?.nextElementSibling?.textContent?.trim();
		return {
			maker: el.querySelector('.dev-card-about > span')?.textContent?.trim(),
			address: el.querySelector('.dev-card-top .mono')?.textContent?.trim(),
			traffic: fig('Traffic'),
			connections: fig('Connections'),
			lastSeen: fig('Last seen'),
		};
	}

	/** What a List row says, in the same shape. */
	function rowFigures(name: string) {
		const cells = within(row(name)).getAllByRole('cell').map((c) => c.textContent?.trim());
		return {
			maker: cells[2],
			address: row(name).querySelector('td:nth-child(2) .mono')?.textContent?.trim(),
			traffic: cells[3],
			connections: cells[4],
			lastSeen: cells[5],
		};
	}

	async function openByType(replies = LAYOUT_REPLIES) {
		stubDaemon(replies);
		const view = render(Page);
		await within(await screen.findByRole('tabpanel', { name: 'By type' })).findByText(A);
		// the list's traffic has merged, in either layout
		await vi.waitFor(() => expect(within(panel()).getByText('1.0 MB')).toBeInTheDocument());
		return view;
	}

	it('gives every card the same rows: top, maker line ("Maker unknown" if none, then any addresses note), stats', async () => {
		await openByType();
		for (const el of computers().querySelectorAll('.dev-card')) {
			const rows = [...el.children].map((c) => ['dev-card-top', 'dev-card-about', 'dev-card-stats'].find((k) => c.classList.contains(k)));
			expect(rows).toEqual(['dev-card-top', 'dev-card-about', 'dev-card-stats']);
		}
		expect(within(card(A)).getByText('Maker unknown')).toBeInTheDocument();
		// the note sits above the stats, in the maker row
		const note = within(card(B)).getByText('(2 of 3 addresses listed)');
		expect(note.closest('.dev-card-about')).not.toBeNull();
		expect(note.compareDocumentPosition(card(B).querySelector('.dev-card-stats')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
	});

	it('shows the same devices in the same order with the same figures in List as in Cards', async () => {
		await openByType();
		const order = cardNames();
		// most recent first, though C has far more traffic than A
		expect(order).toEqual([A, B, C, D, E]);
		const figures = Object.fromEntries(order.map((n) => [n, cardFigures(n!)]));
		expect(figures[A]).toMatchObject({ maker: 'Maker unknown', traffic: '512 B', connections: '9' });
		expect(figures[D]).toMatchObject({ traffic: '—', connections: '—' }); // unknown, not 0
		expect(figures[E]).toMatchObject({ traffic: '0 B', connections: '0' }); // a real zero
		expect(figures[B]).toMatchObject({ traffic: '2.0 KB', connections: (1200).toLocaleString() });

		await showList();
		expect(screen.queryByRole('link', { name: new RegExp(A) })).not.toBeInTheDocument();
		// one table per type group, under the same group head
		expect(within(computers()).getByRole('table')).toBe(listTable());
		expect(rowNames()).toEqual(order);
		for (const name of order) expect(rowFigures(name!), name!).toEqual(figures[name!]);
		// partial address coverage: the first address, how many more, and how many were listed
		expect(row(B).querySelector('td:nth-child(2)')?.textContent).toBe('192.168.1.11 +2 · 2 of 3 listed');
		expect(row(A).querySelector('td:nth-child(2)')?.textContent).toBe('192.168.1.10');
	});

	it('sorts every List column both ways, figures by value, unknowns last', async () => {
		await openByType();
		await showList();
		expect(screen.getByRole('columnheader', { name: 'Last seen' })).toHaveAttribute('aria-sort', 'descending');
		// [header, descending, ascending]: Traffic by bytes, Connections by count, Last seen by time, not by their text
		const SORTS: [string, string[], string[]][] = [
			['Device', [B, D, E, C, A], [A, C, E, D, B]],
			['Address', [E, D, C, B, A], [A, B, C, D, E]],
			['Maker', [E, B, D, C, A], [C, D, B, E, A]],
			['Traffic', [C, B, A, E, D], [E, A, B, C, D]],
			['Connections', [B, C, A, E, D], [E, A, C, B, D]],
			['Last seen', [A, B, C, D, E], [E, D, C, B, A]],
		];
		for (const [label, desc, asc] of SORTS) {
			const header = screen.getByRole('columnheader', { name: label });
			await fireEvent.click(within(header).getByRole('button'));
			expect(header, label).toHaveAttribute('aria-sort', 'descending');
			expect(rowNames(), `${label} descending`).toEqual(desc);
			await fireEvent.click(within(header).getByRole('button'));
			expect(header, label).toHaveAttribute('aria-sort', 'ascending');
			expect(rowNames(), `${label} ascending`).toEqual(asc);
		}
	});

	it('opens the device page from a List row', async () => {
		const { goto } = await import('$app/navigation');
		await openByType();
		await showList();
		await fireEvent.click(within(listTable()).getByRole('button', { name: `Open ${B}` }));
		expect(goto).toHaveBeenCalledWith(`/devices/mac/${encodeURIComponent('aa:11')}`);
	});

	it('keeps the last figures on a failed refresh, the same in both layouts', async () => {
		await openByType();
		await showList();
		const before = Object.fromEntries([A, B, C, D, E].map((n) => [n, rowFigures(n)]));

		const { refreshPage } = await import('$lib/stores/pageRefresh');
		stubDaemon({ '/api/capture/mode': MIRROR });
		await refreshPage();
		expect(await within(panel()).findByText("Couldn't refresh devices; showing the last figures loaded.")).toBeInTheDocument();
		for (const name of [A, B, C, D, E]) expect(rowFigures(name), name).toEqual(before[name]);
		await showCards();
		for (const name of [A, B, C, D, E]) expect(cardFigures(name), name).toEqual(before[name]);
	});

	it('remembers the layout in this browser, and shows Cards when the stored value is unknown', async () => {
		const first = await openByType();
		await showList();
		expect(localStorage.getItem('nettap-devices-layout')).toBe('list');
		first.unmount();

		await openByType();
		expect(listTable()).toBeInTheDocument();
		expect(within(screen.getByRole('group', { name: 'Layout' })).getByRole('button', { name: 'List' })).toHaveAttribute('aria-pressed', 'true');
		cleanup();

		localStorage.setItem('nettap-devices-layout', 'grid');
		await openByType();
		expect(card(A)).toBeInTheDocument();
		expect(screen.queryByRole('table', { name: 'Computers, as a list' })).not.toBeInTheDocument();
	});

	it('falls back to Cards, and still switches, when storage is blocked', async () => {
		const blocked = () => {
			throw new DOMException('blocked', 'SecurityError');
		};
		vi.spyOn(Storage.prototype, 'getItem').mockImplementation(blocked);
		vi.spyOn(Storage.prototype, 'setItem').mockImplementation(blocked);
		await openByType();
		expect(card(A)).toBeInTheDocument();
		await showList();
		expect(listTable()).toBeInTheDocument();
	});

	it('nests no link or button inside another, in either layout', async () => {
		const { container } = await openByType();
		expectNoNestedInteractive(container);
		await showList();
		expectNoNestedInteractive(container);
	});

	// NET-200: the owner's photo on the card's tile and in the List row, which falls back to the icon when it fails
	it("shows the owner's photo on the card and in the List row, and the icon if it fails to load", async () => {
		const PHOTO = '/api/devices/registry/aa:10/picture?v=0123456789abcdef';
		const reg = LAYOUT_REPLIES['/api/devices/registry'] as { total: number; devices: Record<string, unknown>[] };
		const withPhoto = {
			...LAYOUT_REPLIES,
			'/api/devices/registry': { ...reg, devices: reg.devices.map((d) => (d.display_name === A ? { ...d, picture: PHOTO } : d)) },
		};
		await openByType(withPhoto);
		expect(card(A).querySelector('.tile img')).toHaveAttribute('src', PHOTO);
		await showList();
		const photo = row(A).querySelector('img.who-photo')!;
		expect(photo).toHaveAttribute('src', PHOTO);
		await fireEvent.error(photo);
		expect(row(A).querySelector('img.who-photo')).toBeNull();
		expect(row(A).querySelector('.who svg')).toBeInTheDocument();
	});
});
