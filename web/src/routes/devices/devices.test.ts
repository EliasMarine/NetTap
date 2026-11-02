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
