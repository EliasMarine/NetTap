import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import { previewCleanup, executeCleanup } from '$lib/api/storage';
import Page from './+page.svelte';

vi.mock('$lib/api/storage', () => ({
	previewCleanup: vi.fn(),
	executeCleanup: vi.fn(),
}));

describe('Settings', () => {
	it('should export a Svelte component', async () => {
		const module = await import('./+page.svelte');
		expect(module.default).toBeDefined();
	});
});

// ---------------------------------------------------------------------------
// Rendered page tests
// ---------------------------------------------------------------------------

type FetchRoute = (init?: RequestInit) => { status?: number; body: unknown };

/** Stub fetch: URLs in `routes` get their body, everything else a 500. */
function stubFetch(routes: Record<string, FetchRoute> = {}) {
	const fn = vi.fn(async (url: string, init?: RequestInit) => {
		const route = routes[url.split('?')[0]];
		if (!route) return { ok: false, status: 500, json: async () => ({}) };
		const { status = 200, body } = route(init);
		return { ok: status < 400, status, json: async () => body };
	});
	vi.stubGlobal('fetch', fn);
	return fn;
}

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

const PREVIEW = {
	cutoff_date: '2026-09-01T00:00:00Z',
	older_than_days: 30,
	indices: [],
	pcap_files: [],
	total_indices: 3,
	total_pcap_files: 2,
	estimated_freed_bytes: 1_500_000,
};

describe('Settings — manual cleanup', () => {
	beforeEach(() => {
		stubFetch();
		vi.mocked(previewCleanup).mockResolvedValue(PREVIEW as never);
		vi.mocked(executeCleanup).mockResolvedValue({
			deleted_indices: 3,
			deleted_pcap_files: 2,
			freed_bytes_estimate: 1_500_000,
			errors: [],
		} as never);
	});

	afterEach(() => {
		vi.clearAllMocks();
		vi.unstubAllGlobals();
	});

	async function openPreview(days: string) {
		render(Page);
		await fireEvent.click(screen.getByRole('tab', { name: 'Retention' }));
		const input = screen.getByLabelText('Delete data older than (days)');
		await fireEvent.input(input, { target: { value: days } });
		await fireEvent.click(screen.getByRole('button', { name: 'Preview cleanup' }));
		await flush();
		return input;
	}

	it('deletes with the days that were previewed', async () => {
		await openPreview('30');
		expect(previewCleanup).toHaveBeenCalledWith(30);
		// decimal units (NET-166): 1,500,000 bytes is 1.5 MB (1.4 MB in 1024-based units)
		expect(screen.getByText('1.5 MB')).toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: 'Delete data' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Confirm delete' }));
		await flush();

		expect(executeCleanup).toHaveBeenCalledWith(30);
	});

	it('drops the preview and its delete button when the days change', async () => {
		const input = await openPreview('30');
		expect(screen.getByRole('button', { name: 'Delete data' })).toBeInTheDocument();

		await fireEvent.input(input, { target: { value: '5' } });

		expect(screen.queryByRole('button', { name: 'Delete data' })).not.toBeInTheDocument();
		expect(screen.queryByText('Cleanup preview')).not.toBeInTheDocument();
		expect(executeCleanup).not.toHaveBeenCalled();
	});
});

describe('Settings — retention save', () => {
	afterEach(() => {
		vi.clearAllMocks();
		vi.unstubAllGlobals();
	});

	async function saveWith(status: number, body: unknown) {
		stubFetch({ '/api/setup/storage': (init) => (init?.method === 'POST' ? { status, body } : { body: {} }) });
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('tab', { name: 'Retention' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Save retention settings' }));
		await flush();
	}

	it('says "Not saved" when the daemon is unreachable', async () => {
		await saveWith(502, { saved: false, error: 'Daemon unreachable: ECONNREFUSED' });

		expect(screen.getByText('Not saved: Daemon unreachable: ECONNREFUSED')).toBeInTheDocument();
		expect(screen.queryByText(/settings saved/i)).not.toBeInTheDocument();
	});

	it('says the outcome is unknown when the daemon timed out', async () => {
		await saveWith(504, { saved: false, outcome_unknown: true, error: 'The daemon did not answer in time.' });

		expect(screen.getByText(/^Outcome unknown — check again\./)).toBeInTheDocument();
		expect(screen.queryByText(/settings saved/i)).not.toBeInTheDocument();
	});

	it('describes PCAP as continuous capture, not alert-triggered', async () => {
		stubFetch({});
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('tab', { name: 'Retention' }));

		expect(screen.getByText(/Raw packet captures of all traffic/)).toBeInTheDocument();
		expect(screen.queryByText(/alert-triggered/)).not.toBeInTheDocument();
	});

	it('says Suricata alerts follow the Hot tier, not the Warm tier', async () => {
		stubFetch({});
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('tab', { name: 'Retention' }));

		expect(screen.getByLabelText('Hot tier (Zeek metadata and Suricata alerts)')).toBeInTheDocument();
		expect(screen.getByLabelText('Warm tier (separate Suricata indices)')).toBeInTheDocument();
		expect(screen.getByText(/Alerts follow the Hot tier/)).toBeInTheDocument();
	});

	it('will not save the built-in defaults when the daemon did not answer', async () => {
		stubFetch({ '/api/setup/storage': () => ({ body: { source: 'mock', hot_days: 90 } }) });
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('tab', { name: 'Retention' }));

		expect(screen.getByRole('button', { name: 'Save retention settings' })).toBeDisabled();
		expect(screen.getByText(/Could not load the current retention settings/)).toBeInTheDocument();
	});
});

describe('Settings — About', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('shows the daemon version and a readable uptime', async () => {
		stubFetch({
			'/api/system/health': () => ({ body: { uptime: 21970.08 } }),
			'/api/system/versions': () => ({
				body: { versions: [{ name: 'nettap-web', current_version: 'latest' }, { name: 'nettap-daemon', current_version: '0.4.0' }] },
			}),
		});
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('tab', { name: 'About' }));

		expect(screen.getByText('0.4.0')).toBeInTheDocument();
		expect(screen.getByText('6h 6m')).toBeInTheDocument();
		expect(screen.queryByText('0.3.0')).not.toBeInTheDocument();
		expect(screen.queryByText('21970.08')).not.toBeInTheDocument();
	});

	it('hides the Build row when the daemon sends no build, rather than claim a development build (S11)', async () => {
		stubFetch({
			'/api/system/health': () => ({ body: { uptime: 60 } }),
			'/api/system/versions': () => ({ body: { versions: [{ name: 'nettap-daemon', current_version: '0.4.0' }] } }),
		});
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('tab', { name: 'About' }));

		expect(screen.getByText('0.4.0')).toBeInTheDocument();
		expect(screen.queryByText('Build')).not.toBeInTheDocument();
		expect(screen.queryByText('Development build')).not.toBeInTheDocument();
	});

	it('shows the build when the daemon sends one', async () => {
		stubFetch({
			'/api/system/health': () => ({ body: { uptime: 60 } }),
			'/api/system/versions': () => ({ body: { versions: [], build: 'abc1234' } }),
		});
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('tab', { name: 'About' }));

		expect(screen.getByText('abc1234')).toBeInTheDocument();
	});
});

describe('Settings — retention health', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('words a single synced ILM policy naturally', async () => {
		stubFetch({
			'/api/storage/status': () => ({
				body: { disk_usage_percent: 6.8, last_prune_at: new Date().toISOString(),
					ilm_status: { synced: true, last_applied: 'x', pending_retry: false, policies: { 'nettap-hot-policy': 'updated' } } },
			}),
		});
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('tab', { name: 'Retention' }));

		expect(screen.getByText(/Policy synced/)).toBeInTheDocument();
		expect(screen.queryByText(/All 1 synced/)).not.toBeInTheDocument();
	});

	// a failed /api/storage/status read showed "Loading..." forever, "Never (daemon starting...)" and a Problem badge
	it('says the storage status could not be read instead of guessing', async () => {
		stubFetch();
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('tab', { name: 'Retention' }));

		expect(screen.getByText("Couldn't load the storage status: the request failed.")).toBeInTheDocument();
		expect(screen.getByText('Unknown', { selector: '.chip' })).toBeInTheDocument();
		expect(screen.queryByText('Problem')).not.toBeInTheDocument();
		expect(screen.queryByText('Loading the storage status')).not.toBeInTheDocument();
		expect(screen.queryByText('Never (daemon starting…)')).not.toBeInTheDocument();
	});

	it('still reads Healthy when the storage status loads in sync', async () => {
		stubFetch({
			'/api/storage/status': () => ({
				body: { disk_usage_percent: 6.8, last_prune_at: new Date().toISOString(),
					ilm_status: { synced: true, last_applied: 'x', pending_retry: false, policies: { a: 'updated', b: 'updated' } } },
			}),
		});
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('tab', { name: 'Retention' }));

		expect(screen.getByText('Healthy', { selector: '.chip' })).toBeInTheDocument();
		expect(screen.getByText(/2 policies synced/)).toBeInTheDocument();
		expect(screen.queryByText(/Couldn't load the storage status/)).not.toBeInTheDocument();
	});
});

describe('Settings — capture status label', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('does not claim "capturing packets" while the container is stopped', async () => {
		stubFetch({
			'/api/capture/status': () => ({
				body: { enabled: true, maxFileSizeMB: 100, containerRunning: false, containerStatus: 'exited' },
			}),
		});
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('tab', { name: 'Capture' }));

		expect(screen.getByText('Enabled — capture container not running')).toBeInTheDocument();
		expect(screen.queryByText('Enabled — capturing packets')).not.toBeInTheDocument();
	});

	it('shows the size netsniff really rotates at, and the time limit', async () => {
		stubFetch({
			'/api/capture/status': () => ({
				body: { enabled: true, maxFileSizeMB: 4096, rotateMinutes: 10, containerRunning: true, containerStatus: 'running' },
			}),
		});
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('tab', { name: 'Capture' }));

		expect(screen.getByDisplayValue('4096')).toBeInTheDocument();
		expect(screen.getByText(/or every 10 minutes, whichever comes first/)).toBeInTheDocument();
		expect(screen.queryByText(/Default: 100 MB/)).not.toBeInTheDocument();
	});

	// NET-166: netsniff-ng counts PCAP_ROTATE_MB in MiB, and the PCAP page shows decimal MB
	it('labels the max file size in MiB and says how it reads on the PCAP page', async () => {
		stubFetch({
			'/api/capture/status': () => ({
				body: { enabled: true, maxFileSizeMB: 256, containerRunning: true, containerStatus: 'running' },
			}),
		});
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('tab', { name: 'Capture' }));

		const field = screen.getByLabelText('Max file size').closest('.field') as HTMLElement;
		expect(within(field).getByText('MiB')).toBeInTheDocument();
		expect(field).toHaveTextContent('Range: 10–10,000 MiB.');
		expect(field).toHaveTextContent('1 MiB is 1,048,576 bytes, so a 256 MiB file shows as 268.4 MB on the PCAP page.');
		expect(within(field).queryByText('MB')).not.toBeInTheDocument();
	});
});

describe('Settings — a failed load never saves blanks over real settings', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('Capture: no toggle or Save when the status cannot be read', async () => {
		stubFetch({ '/api/capture/status': () => ({ status: 502, body: { error: 'Daemon unreachable' } }) });
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('tab', { name: 'Capture' }));

		expect(screen.getByText(/Could not load the current capture settings/)).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Save capture settings' })).not.toBeInTheDocument();
		expect(screen.queryByDisplayValue('100')).not.toBeInTheDocument();
	});

	it('Notifications: Save is off when the config cannot be read', async () => {
		stubFetch(); // every call 500s
		render(Page);
		await flush();

		expect(screen.getByText(/Could not load the current notification settings/)).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Save notification settings' })).toBeDisabled();
	});

	it('Notifications: Save works once the config has loaded', async () => {
		stubFetch({
			'/api/notifications/config': () => ({
				body: { severityThreshold: 'high', email: { enabled: false, recipients: [] }, webhook: { url: 'https://hooks.example.com/x' } },
			}),
		});
		render(Page);
		await flush();

		expect(screen.queryByText(/Could not load the current notification settings/)).not.toBeInTheDocument();
		expect(screen.getByDisplayValue('https://hooks.example.com/x')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Save notification settings' })).toBeEnabled();
	});

	it('Network: no list editor or Save when the excluded IPs cannot be read', async () => {
		stubFetch();
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('tab', { name: 'Network' }));

		expect(screen.getByText(/Could not load the excluded IP list/)).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Save excluded IPs' })).not.toBeInTheDocument();
		expect(screen.queryByText(/No IPs excluded/)).not.toBeInTheDocument();
	});

	it('Network: shows the saved list when it loads', async () => {
		stubFetch({ '/api/settings/excluded-ips': () => ({ body: { excluded_ips: ['99.10.70.92'] } }) });
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('tab', { name: 'Network' }));

		expect(screen.getByText('99.10.70.92')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Save excluded IPs' })).toBeEnabled();
	});
});

describe('Settings — UniFi integration', () => {
	afterEach(() => {
		vi.clearAllMocks();
		vi.unstubAllGlobals();
	});

	function status(overrides: Record<string, unknown> = {}) {
		return {
			configured: true,
			controller_url: 'https://192.168.1.1',
			site_id: null,
			connected: true,
			last_poll_time: Date.now() / 1000 - 30,
			cache_counts: { clients: 4, devices: 2 },
			last_error: null,
			...overrides,
		};
	}

	async function openIntegrations() {
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('tab', { name: 'Integrations' }));
	}

	it('shows connected state and last poll from the daemon status fields', async () => {
		stubFetch({ '/api/integrations/unifi/status': () => ({ body: status({ site_id: 'site-a' }) }) });

		await openIntegrations();

		expect(screen.getByText('Connected')).toBeInTheDocument();
		expect(screen.getByText('Last poll')).toBeInTheDocument();
		expect(screen.getByText(/^\d+s ago$/)).toBeInTheDocument();
		expect(screen.getByLabelText('Site')).toHaveValue('site-a');
	});

	it('shows disconnected and no last poll before the first successful poll', async () => {
		stubFetch({
			'/api/integrations/unifi/status': () => ({ body: status({ connected: false, last_poll_time: 0 }) }),
		});

		await openIntegrations();

		expect(screen.getByText('Disconnected')).toBeInTheDocument();
		expect(screen.queryByText('Last poll')).not.toBeInTheDocument();
	});

	it('does not post a blank site_id', async () => {
		const fetchMock = stubFetch({
			'/api/integrations/unifi/status': () => ({ body: status() }),
			'/api/integrations/unifi/configure': () => ({ body: { status: 'configured' } }),
			'/api/integrations/unifi/test': () => ({ body: { success: true, status: status() } }),
		});

		await openIntegrations();
		await fireEvent.input(screen.getByLabelText('Site'), { target: { value: '   ' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }));
		await flush();

		const call = fetchMock.mock.calls.find(([url]) => url === '/api/integrations/unifi/configure');
		expect(call).toBeDefined();
		const body = JSON.parse(String(call?.[1]?.body));
		expect(body).toEqual({ controller_url: 'https://192.168.1.1' });
	});
});

// ---------------------------------------------------------------------------
// Redesign: section tabs (Pills tabs mode), the switch, load states, no page refresh
// ---------------------------------------------------------------------------

describe('Settings — links to its own pages (NET-199)', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('links Suricata rules, Notification channels and Backup and restore from the page head, on every tab', async () => {
		stubFetch();
		render(Page);

		const nav = screen.getByRole('navigation', { name: 'More settings' });
		const links = within(nav).getAllByRole('link');
		expect(links.map((a) => [a.textContent?.trim(), a.getAttribute('href')])).toEqual([
			['Suricata rules', '/settings/suricata-rules'],
			['Notification channels', '/settings/notifications'],
			['Backup and restore', '/settings/backup'],
		]);

		// The links sit outside the tab panel, so another tab keeps them
		await fireEvent.click(screen.getByRole('tab', { name: 'Display' }));
		expect(within(screen.getByRole('navigation', { name: 'More settings' })).getAllByRole('link')).toHaveLength(3);
	});
});

describe('Settings — section tabs', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('wires each tab to its panel and opens Notifications first', async () => {
		stubFetch();
		render(Page);

		const tablist = screen.getByRole('tablist', { name: 'Settings sections' });
		const tabs = within(tablist).getAllByRole('tab');
		expect(tabs.map((t) => t.textContent?.trim())).toEqual([
			'Notifications', 'Retention', 'Capture', 'API keys', 'Network', 'Integrations', 'Display', 'About',
		]);
		const first = screen.getByRole('tab', { name: 'Notifications' });
		expect(first).toHaveAttribute('aria-selected', 'true');
		const panel = screen.getByRole('tabpanel');
		expect(panel).toHaveAttribute('id', 'settings-panel-notifications');
		expect(panel).toHaveAttribute('aria-labelledby', first.id);
		expect(first).toHaveAttribute('aria-controls', panel.id);
		expect(within(panel).getByText('Notification preferences')).toBeInTheDocument();
	});

	it('moves between sections with the arrow, Home and End keys', async () => {
		stubFetch();
		render(Page);

		await fireEvent.keyDown(screen.getByRole('tab', { name: 'Notifications' }), { key: 'ArrowRight' });
		expect(screen.getByRole('tab', { name: 'Retention' })).toHaveAttribute('aria-selected', 'true');
		expect(screen.getByRole('tabpanel')).toHaveAttribute('id', 'settings-panel-retention');

		await fireEvent.keyDown(screen.getByRole('tab', { name: 'Retention' }), { key: 'End' });
		expect(screen.getByRole('tabpanel')).toHaveAttribute('id', 'settings-panel-about');

		await fireEvent.keyDown(screen.getByRole('tab', { name: 'About' }), { key: 'ArrowRight' });
		expect(screen.getByRole('tabpanel')).toHaveAttribute('id', 'settings-panel-notifications');

		await fireEvent.keyDown(screen.getByRole('tab', { name: 'Notifications' }), { key: 'Home' });
		expect(screen.getByRole('tabpanel')).toHaveAttribute('id', 'settings-panel-notifications');
	});

	// OLD CODE START — NET-192 PR 4: the top bar's Refresh re-reads the status sections
	// it('registers no page refresh, so the top bar hides Refresh (forms-only page)', async () => {
	// 	stubFetch();
	// 	render(Page);
	// 	await flush();
	//
	// 	expect(get(pageRefresh).available).toBe(false);
	// });
	// OLD CODE END
	it("the top bar's Refresh re-reads the status sections and keeps an unsaved form edit", async () => {
		const fetchFn = stubFetch({
			'/api/setup/storage': () => ({ body: { source: 'daemon', hot_days: 90, warm_days: 180, cold_days: 30, disk_threshold_percent: 80, emergency_threshold_percent: 90 } }),
			'/api/storage/status': () => ({ body: { disk_usage_percent: 42 } }),
		});
		const reads = (path: string) => fetchFn.mock.calls.filter(([url]) => url === path).length;
		const { unmount } = render(Page);
		await flush();
		expect(get(pageRefresh).available).toBe(true);

		await fireEvent.click(screen.getByRole('tab', { name: 'Retention' }));
		const hotDays = screen.getByLabelText('Hot tier (Zeek metadata and Suricata alerts)') as HTMLInputElement;
		await vi.waitFor(() => expect(hotDays.value).toBe('90'));
		await fireEvent.input(hotDays, { target: { value: '120' } });
		expect([reads('/api/setup/storage'), reads('/api/storage/status')]).toEqual([1, 1]);

		// About's reads answer 500 here, so the refresh is partial
		expect(await refreshPage()).toBe('partial');
		await flush();
		expect(reads('/api/storage/status')).toBe(2);
		expect(reads('/api/setup/storage')).toBe(1);
		expect(hotDays.value).toBe('120');
		unmount();
		expect(get(pageRefresh).available).toBe(false);
	});
});

describe('Settings — load states', () => {
	afterEach(() => vi.unstubAllGlobals());

	/** Every request waits forever, so each card stays in its loading state. */
	function stubPending() {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
	}

	it.each([
		['Retention', 'Loading the storage status'],
		['Capture', 'Loading capture settings'],
		['API keys', 'Loading API key status'],
		['Network', 'Loading the excluded IP list'],
		['Integrations', 'Loading UniFi status'],
	])('%s shows a loading card while its request runs', async (tab, text) => {
		stubPending();
		render(Page);
		await fireEvent.click(screen.getByRole('tab', { name: tab }));

		expect(screen.getByText(text).closest('[role="status"]')).toHaveAttribute('aria-busy', 'true');
	});

	it('shows the error card, with no form, when the excluded IP list fails', async () => {
		stubFetch();
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('tab', { name: 'Network' }));

		expect(screen.getByRole('alert')).toHaveTextContent(/Could not load the excluded IP list/);
		expect(screen.queryByLabelText('IP address to exclude')).not.toBeInTheDocument();
	});

	it('shows the capture error card instead of the switch', async () => {
		stubFetch();
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('tab', { name: 'Capture' }));

		expect(screen.getByRole('alert')).toHaveTextContent(/Could not load the current capture settings/);
		expect(screen.queryByRole('switch')).not.toBeInTheDocument();
	});

	it('shows an empty excluded list as text, with the editor still there', async () => {
		stubFetch({ '/api/settings/excluded-ips': () => ({ body: { excluded_ips: [] } }) });
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('tab', { name: 'Network' }));

		expect(screen.getByText('No IPs excluded. All IPs appear in device views.')).toBeInTheDocument();
		expect(screen.getByLabelText('IP address to exclude')).toBeInTheDocument();
	});
});

describe('Settings — PCAP collection switch', () => {
	afterEach(() => vi.unstubAllGlobals());

	const STATUS = { enabled: true, maxFileSizeMB: 100, containerRunning: true, containerStatus: 'running' };

	async function openCapture(toggle: FetchRoute) {
		const fetchMock = stubFetch({ '/api/capture/status': () => ({ body: STATUS }), '/api/capture/toggle': toggle });
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('tab', { name: 'Capture' }));
		return fetchMock;
	}

	it('follows the answer from the daemon', async () => {
		const fetchMock = await openCapture(() => ({ body: { enabled: false, containerRunning: false, containerStatus: 'exited' } }));
		const toggle = screen.getByRole('switch', { name: 'PCAP collection' });
		expect(toggle).toBeChecked();

		await fireEvent.click(toggle);
		await flush();

		const call = fetchMock.mock.calls.find(([url]) => url === '/api/capture/toggle');
		expect(JSON.parse(String(call?.[1]?.body))).toEqual({ enabled: false });
		expect(toggle).not.toBeChecked();
		expect(screen.getByText('PCAP capture disabled')).toBeInTheDocument();
	});

	it('stays on when the toggle fails', async () => {
		await openCapture(() => ({ status: 502, body: { error: 'Daemon unreachable' } }));
		const toggle = screen.getByRole('switch', { name: 'PCAP collection' });

		await fireEvent.click(toggle);
		await flush();

		expect(toggle).toBeChecked();
		expect(screen.getByRole('alert')).toHaveTextContent('Daemon unreachable');
	});
});

describe('Settings — API keys: one place for the ET Pro code (NET-191)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('has no ET Pro key field, and links to Settings › Suricata rules instead', async () => {
		stubFetch({ '/api/settings/api-keys': () => ({ body: { keys: { MAXMIND_LICENSE_KEY: false } } }) });
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('tab', { name: 'API keys' }));

		expect(screen.getByLabelText('MaxMind licence key')).toBeInTheDocument();
		expect(screen.queryByLabelText('Emerging Threats Pro key')).not.toBeInTheDocument();
		expect(document.getElementById('et-pro-key')).toBeNull();
		expect(screen.getByRole('link', { name: 'Settings › Suricata rules' })).toHaveAttribute('href', '/settings/suricata-rules');
	});
});

describe('Settings — Display: the default time range (NET-195)', () => {
	const KEY = 'nettap-display-settings';
	beforeEach(() => localStorage.clear());
	afterEach(() => {
		localStorage.clear();
		vi.unstubAllGlobals();
	});

	async function openDisplay() {
		stubFetch();
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('tab', { name: 'Display' }));
		return screen.getByLabelText('Default time range') as HTMLSelectElement;
	}

	it("offers each page's own first, then the five ranges, and saves the pick as defaultRange", async () => {
		const select = await openDisplay();
		expect(Array.from(select.options, (o) => o.textContent?.trim())).toEqual([
			"Each page's own (most open on 24 hours)", 'Last hour', 'Last 6 hours', 'Last 24 hours', 'Last 7 days', 'Last 30 days',
		]);
		expect(select.value).toBe('');

		await fireEvent.change(select, { target: { value: '7d' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save display settings' }));
		expect(JSON.parse(localStorage.getItem(KEY)!)).toEqual({ defaultRange: '7d' });
		expect(screen.getByText('Display settings saved.')).toBeInTheDocument();
	});

	it("removes the key when each page's own is saved", async () => {
		localStorage.setItem(KEY, JSON.stringify({ defaultRange: '7d', autoRefresh: '30', timezone: 'local' }));
		const select = await openDisplay();
		await fireEvent.change(select, { target: { value: '' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save display settings' }));
		expect(localStorage.getItem(KEY)).toBeNull();
	});

	it('shows a saved range selected', async () => {
		localStorage.setItem(KEY, JSON.stringify({ defaultRange: '30d' }));
		expect((await openDisplay()).value).toBe('30d');
	});

	it("shows each page's own for a legacy 1h, which any old Display save wrote", async () => {
		localStorage.setItem(KEY, JSON.stringify({ autoRefresh: '30', timezone: 'utc', defaultTimeRange: '1h' }));
		expect((await openDisplay()).value).toBe('');
	});

	it('has no auto-refresh or timezone control', async () => {
		await openDisplay();
		expect(screen.queryByLabelText('Auto-refresh interval')).not.toBeInTheDocument();
		expect(screen.queryByLabelText('Timezone')).not.toBeInTheDocument();
	});
});
