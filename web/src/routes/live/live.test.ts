import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import Page from './+page.svelte';
import LiveConnectionDrawerContent from '$components/drawer/content/LiveConnectionDrawerContent.svelte';

describe('Live Monitor', () => {
	it('should export a Svelte component', async () => {
		const module = await import('./+page.svelte');
		expect(module.default).toBeDefined();
	});
});

// #96: a failed dashboard request replaced the live view with zeros, and a failed connection
// detail read as "No alerts for this connection".
describe('Live Monitor — failed requests', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.restoreAllMocks();
	});

	it('says live data failed to load instead of showing 0 connections', async () => {
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		// jsdom has no canvas; the geo map only needs calls on its 2D context to succeed
		const ctx = new Proxy({}, { get: () => () => ({}) });
		vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(ctx as never);
		vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}) })));
		render(Page);
		expect((await screen.findAllByText("Couldn't load live data: the request failed.")).length).toBeGreaterThan(0);
		expect(screen.queryByText('Live Connections')).not.toBeInTheDocument();
	});

	it('says a connection\'s alerts failed to load instead of "No alerts"', () => {
		const connection = { source_ip: '192.168.1.20', dest_ip: '8.8.8.8', dest_port: 53, protocol: 'udp' };
		render(LiveConnectionDrawerContent, {
			connection: connection as never,
			detail: null,
			detailLoading: false,
			detailFailed: true,
			activeTab: 'alerts',
		});
		expect(screen.getByText("Couldn't load alerts for this connection: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('No alerts for this connection')).not.toBeInTheDocument();
	});
});

describe('Live Monitor — duration', () => {
	it('rounds before splitting, so 1 h 59.99 min reads "2h 0m", not "1h 60m"', () => {
		const connection = { source_ip: '192.168.1.20', dest_ip: '8.8.8.8', dest_port: 443, protocol: 'tcp', duration: 7199.6 };
		render(LiveConnectionDrawerContent, {
			connection: connection as never,
			detail: null,
			detailLoading: false,
			detailFailed: false,
			activeTab: 'details',
		});
		expect(screen.getByText('2h 0m')).toBeInTheDocument();
	});
});
