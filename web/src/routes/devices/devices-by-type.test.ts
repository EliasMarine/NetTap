import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import Page from './+page.svelte';

// By type: Home's device cards, moved here (PLAN.md §3, §5.6). The first describe is
// routes/home-device-cards.test.ts ported from Home's markup to this view; the second pins the
// mirror-mode condition and the failure messages Home used.

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

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
			from: FROM, to: '2026-11-02T22:00:00Z', limit: 500,
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
				from: FROM, to: '', limit: 500,
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
	from: LIST_FROM, to: '', limit: 500,
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
