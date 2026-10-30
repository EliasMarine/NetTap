import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import InfrastructurePage from './+page.svelte';

describe('Infrastructure', () => {
	it('should export a Svelte component', async () => {
		const module = await import('./+page.svelte');
		expect(module.default).toBeDefined();
	});
});

// ---------------------------------------------------------------------------
// Rendered page: capture detail labels the capture mode (CR-247)
// ---------------------------------------------------------------------------

describe('Infrastructure capture detail', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	function stubFetch(mode: string, iface: string) {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				if (url === '/api/capture/mode') {
					return { ok: true, status: 200, json: async () => ({ mode, interface: iface }) };
				}
				// Every other endpoint is down; the page has fallbacks for all of them.
				return { ok: false, status: 503, json: async () => ({}) };
			}),
		);
	}

	async function openCaptureDetail() {
		render(InfrastructurePage);
		await vi.waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/capture/mode'));
		await new Promise((r) => setTimeout(r, 0));
		await fireEvent.click(document.querySelector('[data-node="capture"]') as HTMLElement);
	}

	it('labels dhcp_gateway mode instead of bridge/br0', async () => {
		stubFetch('dhcp_gateway', 'enp1s0');

		await openCaptureDetail();

		expect(screen.getByText('DHCP Gateway')).toBeInTheDocument();
		expect(screen.getByText('DHCP gateway on enp1s0')).toBeInTheDocument();
		expect(screen.queryByText(/Promiscuous mode on br0/)).not.toBeInTheDocument();
	});

	it('does not fall back to br0 in dhcp_gateway mode', async () => {
		stubFetch('dhcp_gateway', '');

		await openCaptureDetail();

		expect(screen.getByText('DHCP gateway on the LAN port')).toBeInTheDocument();
		expect(screen.queryByText('br0')).not.toBeInTheDocument();
	});

	it('keeps the bridge labels in bridge mode', async () => {
		stubFetch('bridge', '');

		await openCaptureDetail();

		expect(screen.getByText('Promiscuous mode on br0 — Bridge capture')).toBeInTheDocument();
		expect(screen.getByText('br0')).toBeInTheDocument();
	});
});
