import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
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

	it('shows the gateway port, not a br0 bridge, in DHCP gateway mode', async () => {
		stubFetch('dhcp_gateway', {
			mode: 'dhcp_gateway', status: 'normal', capture_interface: 'enp4s0', link_up: true, promisc_enabled: true,
			issues: [], subnet: '10.77.0.0/24', routing_active: true, dhcp_server_running: true, lease_count: 14,
		});
		await renderPage();

		expect(screen.getByText('Gateway Port')).toBeInTheDocument();
		expect(screen.getByText(/enp4s0 UP/)).toBeInTheDocument();
		expect(screen.queryByText('Bridge')).not.toBeInTheDocument();
		expect(screen.queryByText(/WAN/)).not.toBeInTheDocument();

		await fireEvent.click(document.querySelector('[data-node="bridge"]') as HTMLElement);
		const detail = within(document.querySelector('.detail-panel') as HTMLElement);
		expect(detail.getByText(/Gateway Port — enp4s0/)).toBeInTheDocument();
		expect(detail.getByText('10.77.0.0/24')).toBeInTheDocument();
		expect(detail.getByText('14')).toBeInTheDocument();
		expect(detail.getByText('Running')).toBeInTheDocument();
		expect(screen.queryByText('IP on Mirror Port')).not.toBeInTheDocument();
		expect(screen.queryByText(/Bridge — br0/)).not.toBeInTheDocument();
	});

	it('says the mirror port IP check could not run instead of "None"', async () => {
		stubFetch('mirror', { ...HEALTH, has_ip: null, status: 'degraded', issues: ['Could not check whether enp4s0 has an IP address'] });
		await renderPage();

		await fireEvent.click(document.querySelector('[data-node="bridge"]') as HTMLElement);
		const detail = within(document.querySelector('.detail-panel') as HTMLElement);
		expect(detail.getByText("Couldn't check")).toBeInTheDocument();
		expect(detail.queryByText('None')).not.toBeInTheDocument();
	});

	it('shows "None" when the mirror port really has no IP', async () => {
		stubFetch('mirror', HEALTH);
		await renderPage();

		await fireEvent.click(document.querySelector('[data-node="bridge"]') as HTMLElement);
		const detail = within(document.querySelector('.detail-panel') as HTMLElement);
		expect(detail.getByText('None')).toBeInTheDocument();
		expect(detail.queryByText("Couldn't check")).not.toBeInTheDocument();
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

// ---------------------------------------------------------------------------
// Grafana link only when Grafana answers (off by default, #71)
// ---------------------------------------------------------------------------

describe('Infrastructure Grafana link', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	function stubFetch(grafana: { ok: boolean; status: number; json: () => Promise<unknown> }) {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => (url === '/grafana/api/health' ? grafana : { ok: false, status: 503, json: async () => ({}) })),
		);
	}

	async function renderPage() {
		render(InfrastructurePage);
		await vi.waitFor(() => expect(fetch).toHaveBeenCalledWith('/grafana/api/health'));
		await new Promise((r) => setTimeout(r, 0));
	}

	it('links Grafana when its health check answers', async () => {
		stubFetch({ ok: true, status: 200, json: async () => ({ database: 'ok', version: '10.4.2' }) });
		await renderPage();

		await vi.waitFor(() => expect(screen.getByText('Grafana')).toBeInTheDocument());
	});

	it('hides Grafana when it is off (nginx answers 503)', async () => {
		stubFetch({ ok: false, status: 503, json: async () => ({}) });
		await renderPage();

		expect(screen.queryByText('Grafana')).not.toBeInTheDocument();
		expect(screen.getByText('CyberChef')).toBeInTheDocument();
	});

	it('hides Grafana when the reply is the login page, not Grafana', async () => {
		stubFetch({ ok: true, status: 200, json: async () => { throw new SyntaxError('Unexpected token <'); } });
		await renderPage();

		expect(screen.queryByText('Grafana')).not.toBeInTheDocument();
	});
});

// ---------------------------------------------------------------------------
// A failed request is "couldn't load", never a red cluster or an idle pipeline (#96)
// ---------------------------------------------------------------------------

describe('Infrastructure when requests fail', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	/** Answer each URL prefix with its body; everything else is 503. */
	function stubFetch(replies: Record<string, unknown>) {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				const key = Object.keys(replies).find((prefix) => url.startsWith(prefix));
				if (key) return { ok: true, status: 200, json: async () => replies[key] };
				return { ok: false, status: 503, json: async () => ({}) };
			}),
		);
	}

	async function renderPage() {
		render(InfrastructurePage);
		await vi.waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/logstash/stats'));
		await new Promise((r) => setTimeout(r, 0));
	}

	it('says what could not be loaded instead of showing a red cluster and idle shipping', async () => {
		stubFetch({ '/api/capture/mode': { mode: 'bridge', interface: '' } });
		await renderPage();

		expect(screen.getByText(/Couldn't load .*OpenSearch cluster/)).toBeInTheDocument();
		expect(screen.getByText(/Couldn't load .*Logstash stats/)).toBeInTheDocument();
		expect(screen.queryByText('Red')).not.toBeInTheDocument();
		expect(screen.queryByText('Idle')).not.toBeInTheDocument();
		expect(screen.getByText(/Couldn't load .*bridge health/)).toBeInTheDocument();
		expect(screen.queryByText('Promiscuous')).not.toBeInTheDocument();

		await fireEvent.click(document.querySelector('[data-node="opensearch"]') as HTMLElement);
		expect(screen.getByText('Cluster status unknown')).toBeInTheDocument();
	});

	it('shows real readings, with no failure banner, when every request answers', async () => {
		stubFetch({
			'/api/capture/mode': { mode: 'bridge', interface: '' },
			'/api/capture/stats': { capture_interface: 'br0', drop_rate_pct: 0, rx_packets: 1, tx_packets: 1, link_speed_mbps: 1000 },
			'/api/capture/health': { mode: 'bridge', status: 'normal', capture_interface: 'br0', link_up: true, promisc_enabled: true, issues: [] },
			'/api/bridge/health': { bridge_state: 'up', wan_link: true, lan_link: true, bypass_active: false, latency_us: 100, uptime_seconds: 60, issues: [] },
			'/api/system/health': { uptime: 60, healthy: true, opensearch_reachable: true },
			'/api/storage/status': { disk_usage_percent: 10 },
			'/api/opensearch/cluster': { status: 'green', number_of_nodes: 1 },
			'/api/opensearch/indices': { indices: [], count: 0 },
			'/api/opensearch/templates': { templates: [], count: 0 },
			'/api/logstash/stats': { events_in: 0 },
			'/api/logstash/pipelines': { pipelines: [] },
			'/api/integrations/unifi/status': { configured: false },
		});
		await renderPage();

		expect(screen.queryByText(/Couldn't load/)).not.toBeInTheDocument();
		expect(screen.getByText('Green')).toBeInTheDocument();
		expect(screen.getByText('Idle')).toBeInTheDocument();
	});
});
