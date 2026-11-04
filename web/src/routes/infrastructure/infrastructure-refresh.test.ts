import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import InfrastructurePage from './+page.svelte';

// The page refresh contract (PLAN §5.5) with the page's four poll cadences: bridge and capture
// every 10 s, Logstash/OpenSearch/rates every 15 s, UniFi every 30 s, storage every 60 s.

const READINGS: Record<string, unknown> = {
	'/api/capture/mode': { mode: 'bridge', interface: '' },
	'/api/capture/stats': { capture_interface: 'br0', drop_rate_pct: 0, rx_packets: 1, tx_packets: 1, link_speed_mbps: 1000 },
	'/api/capture/health': { mode: 'bridge', status: 'normal', capture_interface: 'br0', link_up: true, promisc_enabled: true, issues: [] },
	'/api/bridge/health': { bridge_state: 'up', wan_link: true, lan_link: true, bypass_active: false, latency_us: 100, uptime_seconds: 60, issues: [] },
	'/api/system/health': { uptime: 60, healthy: true, opensearch_reachable: true },
	'/api/storage/status': { disk_usage_percent: 10 },
	'/api/opensearch/cluster': { status: 'green', number_of_nodes: 1, total_size_bytes: 0 },
	'/api/opensearch/indices': { indices: [], count: 0 },
	'/api/opensearch/templates': { templates: [], count: 0 },
	'/api/logstash/stats': { events_in: 10 },
	'/api/logstash/pipelines': { pipelines: [] },
	'/api/traffic/summary': { connection_count: 300 },
	'/api/alerts/count': { counts: { total: 0, high: 0, medium: 0, low: 0 } },
	'/api/integrations/unifi/status': { configured: false },
};

const GROUP_PATHS = {
	capture: ['/api/bridge/health', '/api/capture/stats', '/api/capture/mode', '/api/capture/health'],
	pipeline: ['/api/logstash/stats', '/api/opensearch/cluster', '/api/traffic/summary', '/api/alerts/count'],
	unifi: ['/api/integrations/unifi/status'],
	storage: ['/api/system/health', '/api/storage/status'],
};

type Reply = { ok: boolean; status: number; json: () => Promise<unknown> };
const ok = (body: unknown): Reply => ({ ok: true, status: 200, json: async () => body });
const down = (): Reply => ({ ok: false, status: 503, json: async () => ({}) });

/** Answer from `replies` by path (query string ignored); a path that maps to a function decides per call. */
function stubFetch(replies: Record<string, unknown | (() => Promise<Reply>)>) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			const reply = replies[url.split('?')[0]];
			if (typeof reply === 'function') return (reply as () => Promise<Reply>)();
			return reply === undefined ? down() : ok(reply);
		}),
	);
}

const paths = () => vi.mocked(fetch).mock.calls.map(([url]) => String(url).split('?')[0]);
const callsTo = (path: string) => paths().filter((p) => p === path).length;
const settle = () => new Promise((r) => setTimeout(r, 0));
const card = (title: string) => screen.getByRole('heading', { level: 2, name: title }).closest('article') as HTMLElement;

describe('Infrastructure — page refresh contract', () => {
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
	});

	it('registers its loader while mounted and unregisters on unmount', async () => {
		stubFetch(READINGS);
		const { unmount } = render(InfrastructurePage);
		expect(get(pageRefresh).available).toBe(true);
		unmount();
		expect(get(pageRefresh).available).toBe(false);
	});

	it("returns 'ok' when every request answers, and advances Updated", async () => {
		stubFetch(READINGS);
		render(InfrastructurePage);
		expect(await refreshPage()).toBe('ok');
		expect(get(pageRefresh).updatedAt).not.toBeNull();
	});

	it("returns 'partial' when one request fails", async () => {
		const { '/api/storage/status': _gone, ...rest } = READINGS;
		stubFetch(rest);
		render(InfrastructurePage);
		expect(await refreshPage()).toBe('partial');
	});

	it("returns 'failed' when every request fails", async () => {
		stubFetch({});
		render(InfrastructurePage);
		expect(await refreshPage()).toBe('failed');
		expect(get(pageRefresh).updatedAt).toBeNull();
	});

	it('re-fetches only the groups that are due on each poll tick', async () => {
		vi.useFakeTimers();
		stubFetch(READINGS);
		render(InfrastructurePage);
		await vi.advanceTimersByTimeAsync(0);
		vi.mocked(fetch).mockClear();

		await vi.advanceTimersByTimeAsync(5_000); // nothing due yet
		expect(paths()).toEqual([]);

		await vi.advanceTimersByTimeAsync(5_000); // 10 s: bridge and capture only
		expect(new Set(paths())).toEqual(new Set(GROUP_PATHS.capture));

		vi.mocked(fetch).mockClear();
		await vi.advanceTimersByTimeAsync(5_000); // 15 s: Logstash, OpenSearch and the rates
		for (const path of GROUP_PATHS.pipeline) expect(callsTo(path)).toBe(1);
		for (const path of [...GROUP_PATHS.capture, ...GROUP_PATHS.unifi, ...GROUP_PATHS.storage]) expect(callsTo(path)).toBe(0);

		await vi.advanceTimersByTimeAsync(10_000);
		vi.mocked(fetch).mockClear();
		await vi.advanceTimersByTimeAsync(5_000); // 30 s: UniFi is due with the 10 s and 15 s groups; storage is not
		for (const path of [...GROUP_PATHS.capture, ...GROUP_PATHS.pipeline, ...GROUP_PATHS.unifi]) expect(callsTo(path)).toBe(1);
		for (const path of GROUP_PATHS.storage) expect(callsTo(path)).toBe(0);

		await vi.advanceTimersByTimeAsync(25_000);
		vi.mocked(fetch).mockClear();
		await vi.advanceTimersByTimeAsync(5_000); // 60 s: storage at last
		for (const path of GROUP_PATHS.storage) expect(callsTo(path)).toBe(1);
	});

	it('keeps a slow OpenSearch reply: other ticks neither supersede nor restart it', async () => {
		vi.useFakeTimers();
		let release: (r: Reply) => void = () => {};
		const cluster = new Promise<Reply>((resolve) => (release = resolve));
		stubFetch({ ...READINGS, '/api/opensearch/cluster': () => cluster });
		render(InfrastructurePage);

		await vi.advanceTimersByTimeAsync(20_000); // two capture ticks and the pipeline's 15 s slot pass
		expect(callsTo('/api/opensearch/cluster')).toBe(1);
		expect(callsTo('/api/bridge/health')).toBeGreaterThanOrEqual(3);
		expect(within(card('OpenSearch cluster')).getByRole('status')).toBeInTheDocument();

		release(ok({ status: 'green', number_of_nodes: 1, total_size_bytes: 0 }));
		await vi.advanceTimersByTimeAsync(0);
		expect(within(card('OpenSearch cluster')).getByText('Green')).toBeInTheDocument();
	});

	it('writes nothing after unmount and stops polling', async () => {
		vi.useFakeTimers();
		let release: (r: Reply) => void = () => {};
		const cluster = new Promise<Reply>((resolve) => (release = resolve));
		stubFetch({ ...READINGS, '/api/opensearch/cluster': () => cluster });
		const { unmount } = render(InfrastructurePage);
		const pending = refreshPage();

		unmount();
		release(ok({ status: 'green', number_of_nodes: 1, total_size_bytes: 0 }));
		expect(await pending).toBe('skipped');
		expect(get(pageRefresh)).toMatchObject({ available: false, updatedAt: null });

		vi.mocked(fetch).mockClear();
		await vi.advanceTimersByTimeAsync(60_000);
		expect(paths()).toEqual([]);
	});
});

describe('Infrastructure — card states', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('shows each stage card loading until its first reply', async () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(InfrastructurePage);
		await settle();

		for (const title of ['Bridge', 'Packet capture', 'Filebeat log shipper', 'Logstash pipeline', 'OpenSearch cluster']) {
			expect(within(card(title)).getByRole('status')).toHaveAttribute('aria-busy', 'true');
		}
	});

	it('says which card could not load, with a retry, instead of empty figures', async () => {
		stubFetch({ '/api/capture/mode': { mode: 'bridge', interface: '' } });
		render(InfrastructurePage);
		await settle();

		const bridge = within(card('Bridge'));
		expect(bridge.getByRole('alert')).toHaveTextContent("Couldn't load the bridge status: the request failed.");
		expect(bridge.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
		expect(within(card('Logstash pipeline')).getByRole('alert')).toBeInTheDocument();
		expect(within(card('OpenSearch cluster')).getByRole('alert')).toBeInTheDocument();
		// the capture mode answered, so the capture card shows what it knows
		expect(within(card('Packet capture')).queryByRole('alert')).toBeNull();
	});

	it('says there are no indices yet when the index list loads empty', async () => {
		stubFetch(READINGS);
		render(InfrastructurePage);
		await settle();

		expect(within(card('OpenSearch cluster')).getByText(/^No indices yet/)).toBeInTheDocument();
	});

	it('lists the indices in a sortable table when there are some', async () => {
		stubFetch({
			...READINGS,
			'/api/opensearch/indices': {
				indices: [
					{ index: 'arkime_sessions3-261101', health: 'green', status: 'open', docs_count: '9', pri_store_size: '1.2gb', store_size: '1.2gb' },
					{ index: 'arkime_sessions3-261102', health: 'yellow', status: 'open', docs_count: '10', pri_store_size: '100mb', store_size: '100mb' },
				],
				count: 2,
			},
		});
		render(InfrastructurePage);

		const table = await screen.findByRole('table', { name: 'OpenSearch indices' });
		expect(within(table).getAllByRole('columnheader')).toHaveLength(5);
		expect(within(table).getByText('Yellow')).toBeInTheDocument();
	});
});
