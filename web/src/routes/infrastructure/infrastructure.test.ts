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

// ---------------------------------------------------------------------------
// Rendered page: a mirror box shows its mirror port, not an unconfigured bridge (#38)
// ---------------------------------------------------------------------------

describe('Infrastructure pipeline in mirror mode', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	const HEALTH = {
		mode: 'mirror', status: 'normal', capture_interface: 'enp4s0', link_up: true, promisc_enabled: true,
		issues: [], management_interface: 'eno1', carrier: true, has_ip: false,
	};

	function stubFetch(mode: string, health: Record<string, unknown>) {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				if (url === '/api/capture/mode') return { ok: true, status: 200, json: async () => ({ mode, interface: 'enp4s0' }) };
				if (url === '/api/capture/health') return { ok: true, status: 200, json: async () => health };
				if (url === '/api/bridge/health') {
					return { ok: true, status: 200, json: async () => ({ bridge_state: 'not_configured', wan_link: false, lan_link: false, bypass_active: false }) };
				}
				return { ok: false, status: 503, json: async () => ({}) };
			}),
		);
	}

	async function renderPage() {
		render(InfrastructurePage);
		await vi.waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/capture/health'));
		await new Promise((r) => setTimeout(r, 0));
	}

	it('shows the mirror port instead of "Bridge not_configured"', async () => {
		stubFetch('mirror', HEALTH);
		await renderPage();

		expect(screen.getByText('Mirror Port')).toBeInTheDocument();
		expect(screen.getByText(/enp4s0 UP/)).toBeInTheDocument();
		expect(screen.queryByText('not_configured')).not.toBeInTheDocument();
		expect(screen.queryByText(/WAN/)).not.toBeInTheDocument();

		await fireEvent.click(document.querySelector('[data-node="bridge"]') as HTMLElement);
		expect(screen.getByText(/Mirror Port — enp4s0/)).toBeInTheDocument();
		expect(screen.getByText('eno1')).toBeInTheDocument();
		expect(screen.queryByText(/Bridge — br0/)).not.toBeInTheDocument();
	});

	it('reports the real promiscuous state on the Capture node', async () => {
		stubFetch('mirror', { ...HEALTH, promisc_enabled: false, status: 'degraded', issues: ['Promiscuous mode is off'] });
		await renderPage();

		expect(screen.getByText(/Not promiscuous/)).toBeInTheDocument();
		await fireEvent.click(document.querySelector('[data-node="bridge"]') as HTMLElement);
		expect(screen.getByText('Promiscuous mode is off')).toBeInTheDocument();
	});

	it('keeps the bridge node in bridge mode', async () => {
		stubFetch('bridge', { ...HEALTH, mode: 'bridge' });
		await renderPage();

		expect(screen.getByText('Bridge')).toBeInTheDocument();
		expect(screen.queryByText('Mirror Port')).not.toBeInTheDocument();
	});
});

// ---------------------------------------------------------------------------
// Index count: real indices only, split into data and system (#39)
// ---------------------------------------------------------------------------

describe('Infrastructure index count', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	function stubFetch(indexNames: string[]) {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				if (url.startsWith('/api/opensearch/indices')) {
					const indices = indexNames.map((index) => ({ index, health: 'green', status: 'open', docs_count: '1', store_size: '1kb' }));
					return { ok: true, status: 200, json: async () => ({ indices, count: indices.length }) };
				}
				if (url.startsWith('/api/opensearch/cluster')) {
					return { ok: true, status: 200, json: async () => ({ status: 'green', number_of_nodes: 1, active_primary_shards: 42 }) };
				}
				return { ok: false, status: 503, json: async () => ({}) };
			}),
		);
	}

	async function renderPage() {
		render(InfrastructurePage);
		await vi.waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/opensearch/indices')));
		await new Promise((r) => setTimeout(r, 0));
	}

	it('splits the count the way the System page counts', async () => {
		stubFetch(['.kibana_1', '.opendistro-job-scheduler-lock', 'arkime_sessions3-261101', 'arkime_sessions3-261102']);
		await renderPage();

		expect(screen.getByText('2 data · 2 system')).toBeInTheDocument();
	});

	it('never shows the primary shard count as an index count', async () => {
		stubFetch([]);
		await renderPage();

		expect(screen.queryByText('42')).not.toBeInTheDocument();
	});
});
