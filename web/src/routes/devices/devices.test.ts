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
