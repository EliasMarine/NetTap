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
		// OLD CODE START — GeoMap drew on a canvas; DotMap is SVG
		// // jsdom has no canvas; the geo map only needs calls on its 2D context to succeed
		// const ctx = new Proxy({}, { get: () => () => ({}) });
		// vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(ctx as never);
		// OLD CODE END
		vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}) })));
		render(Page);
		expect((await screen.findAllByText("Couldn't load live data: the request failed.")).length).toBeGreaterThan(0);
		// OLD CODE START: expect(screen.queryByText('Live Connections')).not.toBeInTheDocument(); (the card keeps its head now; the table is what must not show) OLD CODE END
		expect(screen.queryByRole('table', { name: 'Live connections' })).not.toBeInTheDocument();
		expect(screen.queryByText(/^0 connections/)).not.toBeInTheDocument();
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

// NET-160 slice 2a: an alert's signature opens the alerts list for it (no count here, so no window)
describe('Live Monitor — signature links', () => {
	it('links each alert signature to /alerts?signature=…', () => {
		const connection = { source_ip: '192.168.1.20', dest_ip: '8.8.8.8', dest_port: 53, protocol: 'udp' };
		const detail = { alerts: [{ timestamp: '2026-11-06T10:00:00Z', severity: 2, signature: 'ET DNS Query', category: 'Misc' }] };
		render(LiveConnectionDrawerContent, {
			connection: connection as never,
			detail: detail as never,
			detailLoading: false,
			detailFailed: false,
			activeTab: 'alerts',
		});
		expect(screen.getByRole('link', { name: 'ET DNS Query' })).toHaveAttribute('href', '/alerts?signature=ET+DNS+Query');
	});
});

// NET-160 slice 2b-2: an alert's category opens its page only when rule.category holds it
describe('Live Monitor — category links', () => {
	it('links the category to its page with no window, and leaves one from another field plain', () => {
		const connection = { source_ip: '192.168.1.20', dest_ip: '8.8.8.8', dest_port: 53, protocol: 'udp' };
		const detail = {
			alerts: [
				{ timestamp: '2026-11-06T10:00:00Z', severity: 2, signature: 'ET DNS Query', category: 'A/B & C', rule_category: ['A/B & C', 'Discovery'] },
				{ timestamp: '2026-11-06T10:01:00Z', severity: 3, signature: 'ET INFO x', category: 'Other field', rule_category: [] },
			],
		};
		render(LiveConnectionDrawerContent, {
			connection: connection as never,
			detail: detail as never,
			detailLoading: false,
			detailFailed: false,
			activeTab: 'alerts',
		});
		expect(screen.getByRole('link', { name: 'A/B & C' })).toHaveAttribute('href', '/alerts/suricata/A%2FB%20%26%20C');
		expect(screen.getByText('Other field').closest('a')).toBeNull();
	});
});
