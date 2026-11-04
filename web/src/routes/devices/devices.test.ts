import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { goto } from '$app/navigation';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import Page from './+page.svelte';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

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
		stubDevices({ ok: true, status: 200, body: { from: '', to: '', limit: 200, devices: [] } });
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

// Total Devices was the length of a 200-row list, so a bigger network read 200.
describe('Devices — Total Devices is the exact count', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('shows the device count, not the length of the list', async () => {
		stubDaemon({
			'/api/devices': { from: '', to: '', limit: 200, devices: [DEVICE] },
			'/api/devices/count': { from: '', to: '', count: 350 },
		});
		render(Page);
		expect(await screen.findByText(/350 devices seen on the network · showing the 1 busiest/)).toBeInTheDocument();
		expect(kpiValue('Total devices')).toBe('350');
	});

	it('shows the same count as the list when the network is small', async () => {
		stubDaemon({
			'/api/devices': { from: '', to: '', limit: 200, devices: [DEVICE] },
			'/api/devices/count': { from: '', to: '', count: 1 },
		});
		render(Page);
		expect(await screen.findByText(/^1 devices seen on the network/)).toBeInTheDocument();
		expect(kpiValue('Total devices')).toBe('1');
		expect(screen.queryByText(/busiest/)).not.toBeInTheDocument();
	});

	it("shows '—' and says so when the count fails, never the list length", async () => {
		stubDaemon({ '/api/devices': { from: '', to: '', limit: 200, devices: [DEVICE] } });
		render(Page);
		expect(await screen.findByText("Couldn't load the device count: the request failed.")).toBeInTheDocument();
		expect(kpiValue('Total devices')).toBe('—');
		expect(screen.queryByText(/1 devices seen on the network/)).not.toBeInTheDocument();
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
			const [path, query = ''] = url.split('?');
			const reply = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
			if (path === '/api/devices') return reply({ from: '', to: '', limit: 500, devices: DEVICES });
			if (path === '/api/devices/count') return reply({ from: '', to: '', count: query.includes('from=') ? 7 : 350 });
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
		const online = f.mock.calls.map((c) => String(c[0])).find((u) => u.startsWith('/api/devices/count?'));
		const q = new URLSearchParams(online?.split('?')[1]);
		expect(Date.parse(q.get('to') ?? '') - Date.parse(q.get('from') ?? '')).toBe(5 * 60 * 1000);
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
const LIST = {
	from: LIST_FROM, to: '', limit: 500,
	devices: [{ ...DEVICE, ip: '192.168.1.21', hostname: 'ipad', total_bytes: 2048, connection_count: 12 }],
};

describe('Devices — All devices table', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.clearAllMocks();
	});

	const TWO = {
		from: LIST_FROM, to: '', limit: 500,
		devices: [
			{ ...DEVICE, ip: '192.168.1.10', hostname: 'laptop', category: 'computer', total_bytes: 5000 },
			{ ...DEVICE, ip: '192.168.1.9', hostname: 'phone', category: 'phone', total_bytes: 100 },
		],
	};

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
