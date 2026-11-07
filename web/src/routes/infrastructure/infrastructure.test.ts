import { describe, it, expect, vi, afterEach } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/svelte';
import { LOSS_SCOPE } from '$api/capture';
import InfrastructurePage from './+page.svelte';

/** A capture-pipeline stage by its label (the strip replaced the clickable topology nodes). */
function stage(label: string): HTMLElement {
	const item = [...document.querySelectorAll<HTMLElement>('.pipe-item')].find(
		(el) => el.querySelector('.pipe-k')?.textContent?.trim() === label,
	);
	if (!item) throw new Error(`No pipeline stage "${label}"`);
	return item;
}

/** A card by its title (the detail panels became always-visible cards). */
const card = (title: string) => screen.getByRole('heading', { level: 2, name: title }).closest('article') as HTMLElement;

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
	}

	it('labels dhcp_gateway mode instead of bridge/br0', async () => {
		stubFetch('dhcp_gateway', 'enp1s0');

		await openCaptureDetail();

		const capture = within(card('Packet capture'));
		expect(capture.getByText('DHCP gateway')).toBeInTheDocument();
		expect(capture.getByText('DHCP gateway on enp1s0')).toBeInTheDocument();
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

		expect(screen.getByText('Promiscuous mode on br0 · bridge capture')).toBeInTheDocument();
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

		expect(within(stage('Mirror port')).getByText(/enp4s0 up/)).toBeInTheDocument();
		expect(screen.queryByText('not_configured')).not.toBeInTheDocument();
		expect(screen.queryByText(/WAN/)).not.toBeInTheDocument();

		expect(within(card('Mirror port')).getByText('enp4s0')).toBeInTheDocument();
		expect(screen.getByText('eno1')).toBeInTheDocument();
		expect(screen.queryByRole('heading', { name: 'Bridge' })).not.toBeInTheDocument();
	});

	it('reports the real promiscuous state on the Capture node', async () => {
		stubFetch('mirror', { ...HEALTH, promisc_enabled: false, status: 'degraded', issues: ['Promiscuous mode is off'] });
		await renderPage();

		expect(within(stage('Capture')).getByText(/Not promiscuous/)).toBeInTheDocument();
		expect(within(card('Mirror port')).getByText('Promiscuous mode is off')).toBeInTheDocument();
	});

	it('shows the gateway port, not a br0 bridge, in DHCP gateway mode', async () => {
		stubFetch('dhcp_gateway', {
			mode: 'dhcp_gateway', status: 'normal', capture_interface: 'enp4s0', link_up: true, promisc_enabled: true,
			issues: [], subnet: '10.77.0.0/24', routing_active: true, dhcp_server_running: true, lease_count: 14,
		});
		await renderPage();

		expect(within(stage('Gateway port')).getByText(/enp4s0 up/)).toBeInTheDocument();
		expect(screen.queryByText('Bridge')).not.toBeInTheDocument();
		expect(screen.queryByText(/WAN/)).not.toBeInTheDocument();

		const detail = within(card('Gateway port'));
		expect(detail.getByText('enp4s0')).toBeInTheDocument();
		expect(detail.getByText('10.77.0.0/24')).toBeInTheDocument();
		expect(detail.getByText('14')).toBeInTheDocument();
		expect(detail.getByText('Running')).toBeInTheDocument();
		expect(screen.queryByText('IP on mirror port')).not.toBeInTheDocument();
		expect(screen.queryByRole('heading', { name: 'Bridge' })).not.toBeInTheDocument();
	});

	it('says the mirror port IP check could not run instead of "None"', async () => {
		stubFetch('mirror', { ...HEALTH, has_ip: null, status: 'degraded', issues: ['Could not check whether enp4s0 has an IP address'] });
		await renderPage();

		const detail = within(card('Mirror port'));
		expect(detail.getByText("Couldn't check")).toBeInTheDocument();
		expect(detail.queryByText('None')).not.toBeInTheDocument();
	});

	it('shows "None" when the mirror port really has no IP', async () => {
		stubFetch('mirror', HEALTH);
		await renderPage();

		const detail = within(card('Mirror port'));
		expect(detail.getByText('None')).toBeInTheDocument();
		expect(detail.queryByText("Couldn't check")).not.toBeInTheDocument();
	});

	it('keeps the bridge node in bridge mode', async () => {
		stubFetch('bridge', { ...HEALTH, mode: 'bridge' });
		await renderPage();

		expect(stage('Bridge')).toBeInTheDocument();
		expect(screen.queryByText('Mirror port')).not.toBeInTheDocument();
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
					// OLD CODE: …, store_size: '1kb' (NET-166: the daemon sends bytes)
					const indices = indexNames.map((index) => ({ index, health: 'green', status: 'open', docs_count: '1', store_size: 1000 }));
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

		expect(within(card('OpenSearch cluster')).getByText('Cluster status unknown')).toBeInTheDocument();
	});

	it('shows real readings, with no failure banner, when every request answers', async () => {
		stubFetch({
			'/api/capture/mode': { mode: 'bridge', interface: '' },
			'/api/capture/stats': { capture_interface: 'br0', drop_rate_pct: 0, rx_packets: 1, tx_packets: 1, rx_dropped: 0, rx_missed_errors: 0, link_speed_mbps: 1000 },
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
		expect(within(stage('OpenSearch')).getByText(/^Green/)).toBeInTheDocument();
		expect(within(card('OpenSearch cluster')).getByText('Green')).toBeInTheDocument();
		// OLD CODE START — 2026-11-06 (S8): one reading of the since-start counter was a verdict
		// expect(within(stage('Filebeat')).getByText('Idle')).toBeInTheDocument();
		// expect(within(card('Filebeat log shipper')).getByText('Idle')).toBeInTheDocument();
		// OLD CODE END
		expect(within(stage('Filebeat')).getByText('Measuring…')).toBeInTheDocument();
		expect(within(card('Filebeat log shipper')).getAllByText('Measuring…')).toHaveLength(2);
	});
});

// ---------------------------------------------------------------------------
// Accuracy audit 2026-11-06 (S4, S8, S9, S12)
// ---------------------------------------------------------------------------

describe('Infrastructure figures', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	const READINGS: Record<string, unknown> = {
		'/api/capture/mode': { mode: 'mirror', interface: 'enp4s0' },
		'/api/capture/stats': {
			capture_interface: 'enp4s0', drop_rate_pct: 0.0000099, rx_packets: 101_000_000, tx_packets: 0, rx_dropped: 0,
			rx_missed_errors: 10, link_speed_mbps: 1000,
			// NET-167: the loss figures read this validated block, not the rx_* counters above
			loss_window: {
				state: 'ok', interface: 'enp4s0',
				window: { seconds: 3480, arrived: 101_000_010, lost: 10, drop_rate_pct: 0.0000099 },
				cumulative: { arrived: 101_000_010, lost: 10, drop_rate_pct: 0.0000099 },
			},
		},
		'/api/system/health': { uptime: 7200, status: 'healthy', healthy: true, opensearch_reachable: true },
		'/api/bridge/health': {
			bridge_state: 'up', wan_link: true, lan_link: true, bypass_active: false, latency_us: null, uptime_seconds: 999_999,
			// OLD CODE: rx_bytes_per_sec: 102_400 (read 100.0 KB/s in 1024-based units; NET-166)
			rx_bytes_delta: 3_072_000, tx_bytes_delta: 0, rx_bytes_per_sec: 100_000, tx_bytes_per_sec: null, issues: [],
		},
	};

	function stubFetch(replies: Record<string, unknown | (() => unknown)>) {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				const key = Object.keys(replies).find((prefix) => url.startsWith(prefix));
				if (!key) return { ok: false, status: 503, json: async () => ({}) };
				const body = replies[key];
				return { ok: true, status: 200, json: async () => (typeof body === 'function' ? body() : body) };
			}),
		);
	}

	async function renderPage() {
		render(InfrastructurePage);
		await vi.waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/logstash/stats'));
		await new Promise((r) => setTimeout(r, 0));
	}

	it('counts NIC misses as lost packets and never rounds a real loss to 0 (S9)', async () => {
		stubFetch(READINGS);
		await renderPage();

		const kpi = screen.getByText('Packet loss', { selector: '.kpi-top span' }).closest('.kpi') as HTMLElement;
		expect(within(kpi).getByText('< 0.01%')).toBeInTheDocument();
		// OLD CODE: expect(within(kpi).getByText('Cumulative kernel interface counters; reset time unknown')).toBeInTheDocument();
		expect(within(kpi).getByText('< 0.01% lost in the last 58 min · 10 packets')).toBeInTheDocument();
		expect(within(card('Packet capture')).getByText('10 · < 0.01%')).toBeInTheDocument();
		expect(within(stage('Capture')).getByText(/< 0\.01% lost/)).toBeInTheDocument();
	});

	it("labels the uptime as the appliance's and never uses the bridge's (S4)", async () => {
		stubFetch(READINGS);
		await renderPage();
		await vi.waitFor(() => expect(screen.getByText(/appliance up 2h 0m/)).toBeInTheDocument());
		expect(screen.queryByText(/NetTap up/)).not.toBeInTheDocument();
	});

	it("shows the bridge's measured byte rate, not the per-check delta (S12)", async () => {
		stubFetch({ ...READINGS, '/api/capture/mode': { mode: 'bridge', interface: '' } });
		await renderPage();

		const bridge = within(card('Bridge'));
		expect(bridge.getByText('RX rate').nextElementSibling?.textContent).toBe('100.0 KB/s');
		expect(bridge.getByText('TX rate').nextElementSibling?.textContent).toBe('--');
	});

	it('NET-166: index sizes are bytes in decimal units, sorted by bytes, with unknown sizes last', async () => {
		const idx = (index: string, bytes: number | null) =>
			({ index, health: 'green', status: 'open', docs_count: '1', pri_store_size: bytes, store_size: bytes });
		stubFetch({
			...READINGS,
			'/api/opensearch/cluster': { status: 'green', number_of_nodes: 1 },
			'/api/opensearch/indices': {
				indices: [idx('a-half-mib', 524_288), idx('b-empty', 0), idx('c-unknown', null), idx('d-two-mb', 2_000_000)],
				count: 4,
			},
		});
		await renderPage();

		const table = await screen.findByRole('table', { name: 'OpenSearch indices' });
		const sizes = () => within(table).getAllByRole('row').slice(1).map((r) => {
			const cells = within(r).getAllByRole('cell');
			return `${cells[1].textContent} ${cells.at(-1)?.textContent}`;
		});
		// 524,288 bytes is 524.3 KB (it read "512kb" from OpenSearch); 0 is a real 0 B; null is unknown
		expect(sizes()).toEqual(['a-half-mib 524.3 KB', 'b-empty 0 B', 'c-unknown --', 'd-two-mb 2.0 MB']);

		const sortBy = (label: string) => within(table).getByRole('button', { name: label }).click();
		sortBy('Total size');
		await vi.waitFor(() => expect(sizes()).toEqual(['d-two-mb 2.0 MB', 'a-half-mib 524.3 KB', 'b-empty 0 B', 'c-unknown --']));
		sortBy('Total size');
		await vi.waitFor(() => expect(sizes()).toEqual(['b-empty 0 B', 'a-half-mib 524.3 KB', 'd-two-mb 2.0 MB', 'c-unknown --']));
	});

	it("NET-166: Logstash's heap is in decimal units too (-Xmx1g reads 1.1 GB)", async () => {
		stubFetch({ ...READINGS, '/api/logstash/stats': { heap_used_bytes: 612_000_000, heap_max_bytes: 2 ** 30, events_in: 1 } });
		await renderPage();

		expect(await screen.findByText('612.0 MB used · 1.1 GB max')).toBeInTheDocument();
	});

	it('says Shipping only when events reach Logstash between two polls (S8)', async () => {
		let eventsIn = 5_000_000;
		stubFetch({ ...READINGS, '/api/logstash/stats': () => ({ events_in: eventsIn }) });
		const { getByText } = within(document.body);
		await renderPage();

		// one reading of a since-start counter proves nothing
		expect(within(stage('Filebeat')).getByText('Measuring…')).toBeInTheDocument();
		expect(getByText('Events in since start')).toBeInTheDocument();

		// the same count at the next poll: nothing new arrived
		const { refreshPage } = await import('$lib/stores/pageRefresh');
		await new Promise((r) => setTimeout(r, 5));
		await refreshPage();
		expect(within(stage('Filebeat')).getByText('No new events since the last check')).toBeInTheDocument();

		eventsIn += 300;
		await new Promise((r) => setTimeout(r, 5));
		await refreshPage();
		expect(within(stage('Filebeat')).getByText(/^Shipping · [\d,.]+ events\/s into Logstash$/)).toBeInTheDocument();
	});
});

// The daemon now sends latency_us: null (with latency_note) instead of a made-up 50 µs; the page read "-- ms".
describe('Infrastructure bridge latency', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	const NOTE = "Not measured: NetTap can't time packets through the bridge";

	function stubBridge(latency: Record<string, unknown>) {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				if (url === '/api/capture/mode') return { ok: true, status: 200, json: async () => ({ mode: 'bridge', interface: '' }) };
				if (url === '/api/bridge/health') {
					return { ok: true, status: 200, json: async () => ({ bridge_state: 'up', wan_link: true, lan_link: true, bypass_active: false, uptime_seconds: 60, issues: [], ...latency }) };
				}
				return { ok: false, status: 503, json: async () => ({}) };
			}),
		);
	}

	async function latencyCard() {
		render(InfrastructurePage);
		await vi.waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/bridge/health'));
		await new Promise((r) => setTimeout(r, 0));
		return screen.getByText('Latency', { selector: '.kpi-top span' }).closest('.kpi') as HTMLElement;
	}

	it('says Not measured, with the reason, instead of "-- ms"', async () => {
		stubBridge({ latency_us: null, latency_note: NOTE });
		const card = await latencyCard();

		// OLD CODE: expect(within(card).getByText('Not measured')).toBeInTheDocument(); (NET-192: the figure is a dash, the words are in the sub)
		expect(within(card).getByText('—')).toBeInTheDocument();
		// the KPI card shows the reason under the figure; the bridge card keeps it as the title
		expect(within(card).getByText(NOTE)).toBeInTheDocument();
		expect(screen.getByText('Not measured', { selector: '[title]' })).toHaveAttribute('title', NOTE);
		expect(card.textContent).not.toContain('ms');
	});

	it('still shows a measured latency in ms', async () => {
		stubBridge({ latency_us: 1500 });
		const card = await latencyCard();

		expect(card.textContent?.replace(/\s+/g, '')).toBe('Latency1.5ms');
	});
});

// ---------------------------------------------------------------------------
// NET-167: packet loss over the last hour; the cumulative count is a labelled secondary
// ---------------------------------------------------------------------------

describe('Infrastructure packet loss window', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	const QUIET = { seconds: 3480, arrived: 98_765, lost: 0, drop_rate_pct: 0 };
	const CUMULATIVE = { arrived: 123_456_789, lost: 345, drop_rate_pct: 0.000279 };
	const lossWindow = (over: Record<string, unknown> = {}) => ({
		state: 'ok', interface: 'br0', window: QUIET, cumulative: CUMULATIVE, ...over,
	});
	const statsWith = (loss_window?: unknown) => ({
		capture_interface: 'br0', drop_rate_pct: 0, rx_packets: 1, tx_packets: 1, rx_dropped: 0, rx_missed_errors: 0,
		link_speed_mbps: 1000, ...(loss_window === undefined ? {} : { loss_window }),
	});
	const BRIDGE = { bridge_state: 'up', wan_link: true, lan_link: true, bypass_active: false, latency_us: 100, uptime_seconds: 60, issues: [] };
	const HEALTH = { mode: 'bridge', status: 'normal', capture_interface: 'br0', link_up: true, promisc_enabled: true, issues: [] };

	const readings = (stats: unknown, over: Record<string, unknown> = {}) => ({
		'/api/capture/mode': { mode: 'bridge', interface: '' },
		'/api/capture/stats': stats,
		'/api/capture/health': HEALTH,
		'/api/bridge/health': BRIDGE,
		...over,
	});

	/** Answers by path; a function decides per call, and undefined is a failed request. */
	function stubFetch(replies: Record<string, unknown>) {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				const reply = replies[url.split('?')[0]];
				const body = typeof reply === 'function' ? reply() : reply;
				return body === undefined
					? { ok: false, status: 503, json: async () => ({}) }
					: { ok: true, status: 200, json: async () => body };
			}),
		);
	}

	async function renderPage() {
		render(InfrastructurePage);
		await vi.waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/capture/stats'));
		await new Promise((r) => setTimeout(r, 0));
	}

	async function refresh() {
		const { refreshPage } = await import('$lib/stores/pageRefresh');
		await new Promise((r) => setTimeout(r, 5));
		await refreshPage();
	}

	const kpi = () => screen.getByText('Packet loss', { selector: '.kpi-top span' }).closest('.kpi') as HTMLElement;
	const kpiValue = () => kpi().querySelector('.kpi-num')?.textContent;
	const captureStatus = () => within(stage('Capture')).getByRole('img').getAttribute('aria-label');
	const lostSinceReset = () =>
		within(card('Packet capture')).getByText('Packets lost since the counters reset').nextElementSibling?.textContent?.trim();

	it.each([
		['a loss over 0.1 %', lossWindow({ window: { seconds: 3480, arrived: 293_810, lost: 1_234, drop_rate_pct: 0.42 } }), '0.42%', '0.42% lost in the last 58 min · 1,234 packets'],
		['no loss', lossWindow(), '0.00%', 'No packets lost in the last 58 min · 98,765 received'],
		['no arrivals', lossWindow({ window: { seconds: 3480, arrived: 0, lost: 0, drop_rate_pct: null } }), '--', 'No packets in the last 58 min'],
		['measuring', lossWindow({ state: 'measuring', window: null }), '--', 'Measuring recent loss…'],
		['an old daemon with no loss_window', undefined, '--', 'Loss counters unavailable'],
	])('Packet loss KPI: %s', async (_case, loss_window, value, sub) => {
		stubFetch(readings(statsWith(loss_window)));
		await renderPage();

		expect(kpiValue()).toBe(value);
		expect(within(kpi()).getByText(sub)).toBeInTheDocument();
		// a percentage only shows when the window has one
		if (value === '--') expect(kpi().textContent).not.toMatch(/%/);
	});

	it('a failed refresh reads the loss as unavailable, not the old window; the next good one shows the new window', async () => {
		let reply: unknown = statsWith(lossWindow());
		stubFetch(readings(() => reply));
		await renderPage();
		expect(within(kpi()).getByText('No packets lost in the last 58 min · 98,765 received')).toBeInTheDocument();
		expect(lostSinceReset()).toBe('345 · < 0.01%');

		reply = undefined;
		await refresh();
		expect(kpiValue()).toBe('--');
		expect(within(kpi()).getByText("Couldn't refresh the loss figures")).toBeInTheDocument();
		expect(within(stage('Capture')).getByText(/Couldn't refresh the loss figures/)).toBeInTheDocument();
		expect(screen.queryAllByText(/last 58 min/)).toHaveLength(0);
		expect(lostSinceReset()).toBe('Unavailable');
		// the rest of the card keeps its last good reading
		expect(within(card('Packet capture')).getByText('RX packets').nextElementSibling?.textContent).toBe('1');

		reply = statsWith(lossWindow({ window: { seconds: 3540, arrived: 120_000, lost: 0, drop_rate_pct: 0 } }));
		await refresh();
		expect(within(kpi()).getByText('No packets lost in the last 59 min · 120,000 received')).toBeInTheDocument();
		expect(lostSinceReset()).toBe('345 · < 0.01%');
	});

	it('capture stage: a loss over 0.1 % turns an ok stage failing', async () => {
		stubFetch(readings(statsWith(lossWindow({ window: { seconds: 3480, arrived: 293_810, lost: 1_234, drop_rate_pct: 0.42 } }))));
		await renderPage();
		expect(captureStatus()).toBe('Failing');
		expect(within(stage('Capture')).getByText('Promiscuous · 0.42% lost in the last 58 min · 1,234 packets')).toBeInTheDocument();
	});

	it('capture stage: a healthy window never turns bypass ok', async () => {
		stubFetch(readings(statsWith(lossWindow()), { '/api/bridge/health': { ...BRIDGE, bypass_active: true } }));
		await renderPage();
		expect(captureStatus()).toBe('Failing');
		expect(within(stage('Capture')).getByText('Bypass · No packets lost in the last 58 min · 98,765 received')).toBeInTheDocument();
	});

	it('capture stage: a healthy window never turns promiscuous-off ok', async () => {
		stubFetch(
			readings(statsWith(lossWindow({ interface: 'enp4s0' })), {
				'/api/capture/mode': { mode: 'mirror', interface: 'enp4s0' },
				'/api/capture/health': { ...HEALTH, mode: 'mirror', capture_interface: 'enp4s0', promisc_enabled: false },
			}),
		);
		await renderPage();
		expect(captureStatus()).toBe('Failing');
		expect(within(stage('Capture')).getByText('Not promiscuous · No packets lost in the last 58 min · 98,765 received')).toBeInTheDocument();
	});

	it('capture stage: a healthy window and a healthy bridge stay ok', async () => {
		stubFetch(readings(statsWith(lossWindow())));
		await renderPage();
		expect(captureStatus()).toBe('Healthy');
	});

	it('details: the validated count since the counters reset, its rate only when there is one, else Unavailable', async () => {
		stubFetch(readings(statsWith(lossWindow())));
		await renderPage();
		const label = within(card('Packet capture')).getByText('Packets lost since the counters reset');
		expect(label).toHaveAttribute('title', LOSS_SCOPE);
		expect(lostSinceReset()).toBe('345 · < 0.01%');
		cleanup();

		// lost > arrived: the daemon sends no rate, and the page makes none up
		stubFetch(readings(statsWith(lossWindow({ cumulative: { arrived: 100, lost: 150, drop_rate_pct: null } }))));
		await renderPage();
		expect(lostSinceReset()).toBe('150');
		cleanup();

		// the rx_* counters read 0 on error, so they never stand in for a missing block
		stubFetch(readings(statsWith(lossWindow({ state: 'unavailable', window: null, cumulative: null }))));
		await renderPage();
		expect(lostSinceReset()).toBe('Unavailable');
	});
});
