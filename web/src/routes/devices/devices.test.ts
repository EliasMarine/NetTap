import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import Page from './+page.svelte';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

describe('Devices', () => {
	it('should export a Svelte component', async () => {
		const module = await import('./+page.svelte');
		expect(module.default).toBeDefined();
	});
});

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

// Total Devices was the length of a 200-row list, so a bigger network read 200.
describe('Devices — Total Devices is the exact count', () => {
	afterEach(() => vi.unstubAllGlobals());

	const DEVICE = {
		ip: '192.168.1.10', mac: null, hostname: 'laptop', manufacturer: null, os_hint: null,
		first_seen: '', last_seen: '', total_bytes: 1000, connection_count: 5, protocols: [], alert_count: 0,
	};

	/** Replies by path; any path not listed answers 503. */
	function stubDaemon(replies: Record<string, unknown>): void {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				const body = replies[url.split('?')[0]];
				return body
					? { ok: true, status: 200, json: async () => body }
					: { ok: false, status: 503, json: async () => ({}) };
			}),
		);
	}

	function totalValue(): string | null | undefined {
		return screen.getByText('Total Devices').closest('.stat-card')?.querySelector('.stat-value')?.textContent;
	}

	it('shows the device count, not the length of the list', async () => {
		stubDaemon({
			'/api/devices': { from: '', to: '', limit: 200, devices: [DEVICE] },
			'/api/devices/count': { from: '', to: '', count: 350 },
		});
		render(Page);
		expect(await screen.findByText(/350 devices seen on the network · showing the 1 busiest/)).toBeInTheDocument();
		expect(totalValue()).toBe('350');
	});

	it('shows the same count as the list when the network is small', async () => {
		stubDaemon({
			'/api/devices': { from: '', to: '', limit: 200, devices: [DEVICE] },
			'/api/devices/count': { from: '', to: '', count: 1 },
		});
		render(Page);
		expect(await screen.findByText(/^1 devices seen on the network/)).toBeInTheDocument();
		expect(totalValue()).toBe('1');
		expect(screen.queryByText(/busiest/)).not.toBeInTheDocument();
	});

	it("shows '—' and says so when the count fails, never the list length", async () => {
		stubDaemon({ '/api/devices': { from: '', to: '', limit: 200, devices: [DEVICE] } });
		render(Page);
		expect(await screen.findByText("Couldn't load the device count: the request failed.")).toBeInTheDocument();
		expect(totalValue()).toBe('—');
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

	function card(label: string): Element | null | undefined {
		return screen.getByText(label).closest('.stat-card');
	}

	it('counts devices NetTap first saw in 24 h and devices with traffic in the last 5 min', async () => {
		const f = stub({ ok: true, count: 0 });
		render(Page);
		await screen.findByText(/350 devices seen/);
		await vi.waitFor(() => expect(card('New (24h)')?.querySelector('.stat-value')?.textContent).toBe('0'));
		expect(card('Online Now')?.querySelector('.stat-value')?.textContent).toBe('7');
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
		expect(card('New (24h)')?.querySelector('.stat-value')?.textContent).toBe('—');
	});
});
