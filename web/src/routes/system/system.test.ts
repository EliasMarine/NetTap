import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import SystemPage from './+page.svelte';

/** Every request fails except /api/capture/mode; returns the list of requested URLs. */
function stubFetch(mode: string): string[] {
	const urls: string[] = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: RequestInfo | URL) => {
			const url = String(input);
			urls.push(url);
			if (url === '/api/capture/mode') {
				return new Response(JSON.stringify({ mode, interface: 'enp1s0' }), { status: 200 });
			}
			return new Response(JSON.stringify({ error: 'not under test' }), { status: 503 });
		})
	);
	return urls;
}

describe('System page bridge panel', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it.each(['dhcp_gateway', 'mirror'])('hides BridgeStatus and never polls /api/bridge in %s mode', async (mode) => {
		const urls = stubFetch(mode);

		const { container } = render(SystemPage);
		await vi.waitFor(() => expect(urls).toContain('/api/capture/mode'));
		await new Promise((r) => setTimeout(r, 0));

		expect(container.querySelector('.bridge-card')).toBeNull();
		expect(urls.filter((u) => u.startsWith('/api/bridge'))).toEqual([]);
	});

	it('shows BridgeStatus and fetches bridge health in bridge mode', async () => {
		const urls = stubFetch('bridge');

		const { container } = render(SystemPage);

		await vi.waitFor(() => expect(container.querySelector('.bridge-card')).not.toBeNull());
		await vi.waitFor(() => expect(urls.some((u) => u.startsWith('/api/bridge'))).toBe(true));
	});

	it('says the capture mode could not be read instead of assuming bridge (#96)', async () => {
		const urls = stubFetch('unused');
		vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
			urls.push(String(input));
			return new Response(JSON.stringify({ error: 'down' }), { status: 503 });
		});

		const { container } = render(SystemPage);

		expect(await screen.findByText("Couldn't read the capture mode, so bridge status isn't shown.")).toBeInTheDocument();
		expect(container.querySelector('.bridge-card')).toBeNull();
	});
});

describe('System page when status requests fail (#96)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('says each card could not be loaded instead of "Degraded" or "requires smartmontools"', async () => {
		stubFetch('mirror');

		render(SystemPage);

		expect(await screen.findByText("Couldn't load system health: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load storage status: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load drive health: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('Degraded')).not.toBeInTheDocument();
		expect(screen.queryByText('Disconnected')).not.toBeInTheDocument();
		expect(screen.queryByText(/requires smartmontools/)).not.toBeInTheDocument();
		expect(screen.queryByText(/% used/)).not.toBeInTheDocument();
		// TShark and CyberChef: a failed status check is not "Not Deployed"
		expect(screen.getAllByText("couldn't check")).toHaveLength(2);
		// OLD CODE START — the redesign writes the label in sentence case
		// expect(screen.queryByText('Not Deployed')).not.toBeInTheDocument();
		// OLD CODE END
		expect(screen.queryByText('Not deployed')).not.toBeInTheDocument();
	});

	it('shows the daemon\'s unknown drive health and unreadable index count, not Healthy or 0', async () => {
		const replies: Record<string, unknown> = {
			'/api/capture/mode': { mode: 'mirror', interface: 'enp4s0' },
			'/api/smart/health': {
				device: '/dev/nvme0', device_type: 'nvme', model: 'X', serial: 'S', temperature_c: null, percentage_used: null,
				power_on_hours: null, total_bytes_written: null, total_bytes_read: null, media_errors: null, reallocated_sectors: null,
				healthy: null, error: 'SMART health could not be read from /dev/nvme0', warnings: [], timestamp: '2026-11-02T00:00:00Z',
			},
			'/api/storage/status': {
				disk_usage_percent: 42, disk_total_bytes: 100, disk_used_bytes: 42, disk_free_bytes: 58, disk_threshold_percent: 80, emergency_threshold_percent: 90, retention: null,
				index_counts: null, total_indices: null, indices_error: 'Could not list indices: timeout',
			},
		};
		vi.stubGlobal(
			'fetch',
			vi.fn(async (input: RequestInfo | URL) => {
				const body = replies[String(input)];
				return body ? new Response(JSON.stringify(body), { status: 200 }) : new Response('{}', { status: 503 });
			}),
		);

		render(SystemPage);

		expect(await screen.findByText('Drive health unknown: SMART health could not be read from /dev/nvme0')).toBeInTheDocument();
		expect(screen.queryByText('Healthy')).not.toBeInTheDocument();
		expect(screen.queryByText('Degraded')).not.toBeInTheDocument();
		expect(screen.getByText("Couldn't read indices")).toBeInTheDocument();
	});

	it('still shows Healthy and the disk usage when the requests succeed', async () => {
		const replies: Record<string, unknown> = {
			'/api/capture/mode': { mode: 'mirror', interface: 'enp4s0' },
			'/api/system/health': { uptime: 60, timestamp: '2026-11-02T00:00:00Z', status: 'healthy', healthy: true, opensearch_reachable: true },
			'/api/storage/status': { disk_usage_percent: 42, disk_total_bytes: 100, disk_used_bytes: 42, disk_free_bytes: 58, disk_threshold_percent: 80, emergency_threshold_percent: 90, retention: null },
		};
		vi.stubGlobal(
			'fetch',
			vi.fn(async (input: RequestInfo | URL) => {
				const body = replies[String(input)];
				return body ? new Response(JSON.stringify(body), { status: 200 }) : new Response('{}', { status: 503 });
			}),
		);

		render(SystemPage);

		expect(await screen.findByText('Healthy')).toBeInTheDocument();
		expect(screen.getByText('42.0% used')).toBeInTheDocument();
		expect(screen.queryByText("Couldn't load system health: the request failed.")).not.toBeInTheDocument();
	});
});

// ---------------------------------------------------------------------------
// Redesign: card states, the health strip and the page refresh contract (PLAN.md §5.5)
// ---------------------------------------------------------------------------

const OK_REPLIES: Record<string, unknown> = {
	'/api/capture/mode': { mode: 'mirror', interface: 'enp4s0' },
	'/api/system/health': { uptime: 3600, timestamp: '2026-11-02T00:00:00Z', status: 'healthy', healthy: true, opensearch_reachable: true },
	'/api/storage/status': { disk_usage_percent: 42, disk_total_bytes: 100, disk_used_bytes: 42, disk_free_bytes: 58, disk_threshold_percent: 80, emergency_threshold_percent: 90, retention: null, total_indices: 7 },
	'/api/smart/health': {
		device: '/dev/nvme0', device_type: 'nvme', model: 'X', serial: 'S', temperature_c: 40, percentage_used: 3,
		power_on_hours: 10, total_bytes_written: 1, total_bytes_read: 1, media_errors: 0, reallocated_sectors: null,
		healthy: true, warnings: [], timestamp: '2026-11-02T00:00:00Z',
	},
	'/api/tshark/status': { available: true, version: '4.2.2' },
	'/api/cyberchef/status': { available: true, version: '10.5.2' },
};

/** Answer each URL from `replies`; anything missing is a 503. */
function stubReplies(replies: Record<string, unknown>) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: RequestInfo | URL) => {
			const body = replies[String(input)];
			return body ? new Response(JSON.stringify(body), { status: 200 }) : new Response('{}', { status: 503 });
		}),
	);
}

describe('System page card states', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('shows each card loading while its request is pending', async () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => {})));

		render(SystemPage);

		for (const name of ['Loading system health', 'Loading OpenSearch status', 'Loading storage', 'Loading drive health', 'Loading services']) {
			expect(screen.getByText(name).closest('[role="status"]')).toHaveAttribute('aria-busy', 'true');
		}
	});

	it('shows an error state with Try again for each failed card, and the retry reloads', async () => {
		stubFetch('mirror');

		render(SystemPage);

		await screen.findByText("Couldn't load drive health: the request failed.");
		const errors = screen.getAllByRole('alert');
		expect(errors.map((e) => e.querySelector('h3')?.textContent)).toEqual([
			"Couldn't load system health: the request failed.",
			"Couldn't check OpenSearch: the system health and storage requests failed.",
			"Couldn't load storage status: the request failed.",
			"Couldn't load drive health: the request failed.",
		]);
		const before = vi.mocked(fetch).mock.calls.length;
		await fireEvent.click(within(errors[0]).getByRole('button', { name: 'Try again' }));
		await vi.waitFor(() => expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(before));
	});

	it('shows the empty drive state when the daemon finds no SMART device', async () => {
		stubReplies({ ...OK_REPLIES, '/api/smart/health': { device: '', device_type: '', healthy: true, warnings: [] } });

		render(SystemPage);

		expect(await screen.findByText('SMART data unavailable')).toBeInTheDocument();
		expect(screen.getByText('Drive health monitoring requires smartmontools.')).toBeInTheDocument();
	});

	it('keeps the last reading and says the refresh failed when a later load fails', async () => {
		stubReplies(OK_REPLIES);
		render(SystemPage);
		expect(await screen.findByText('42.0% used')).toBeInTheDocument();

		stubReplies({ ...OK_REPLIES, '/api/storage/status': undefined });
		await refreshPage();

		expect(await screen.findByText("Couldn't refresh storage status; showing the last figures loaded.")).toBeInTheDocument();
		expect(screen.getByText('42.0% used')).toBeInTheDocument();
	});
});

describe('System page health strip', () => {
	afterEach(() => vi.unstubAllGlobals());

	const stage = (label: string) => {
		const item = [...document.querySelectorAll('.pipe-item')].find((el) => el.querySelector('.pipe-k')?.textContent?.trim() === label);
		return { word: item?.querySelector('[role="img"]')?.getAttribute('aria-label'), detail: item?.querySelector('.pipe-v')?.textContent?.trim() };
	};

	it('marks each part healthy from its reading', async () => {
		stubReplies(OK_REPLIES);
		render(SystemPage);
		await screen.findByText('42.0% used');

		// OLD CODE: detail 'Up 1h' (S4: the uptime is the appliance's, not the daemon's)
		expect(stage('NetTap')).toEqual({ word: 'Healthy', detail: 'Appliance up 1h' });
		expect(stage('OpenSearch')).toEqual({ word: 'Healthy', detail: 'Connected' });
		expect(stage('Storage')).toEqual({ word: 'Healthy', detail: '42.0% used · 58 B free' });
		expect(stage('Drive')).toEqual({ word: 'Healthy', detail: 'SMART checks pass' });
	});

	it('marks a full disk and an unreachable OpenSearch failing', async () => {
		stubReplies({
			...OK_REPLIES,
			'/api/system/health': { uptime: 60, timestamp: '2026-11-02T00:00:00Z', status: 'problem', healthy: false, opensearch_reachable: false },
			'/api/storage/status': { disk_usage_percent: 91.5, disk_total_bytes: 100, disk_used_bytes: 91, disk_free_bytes: 9, disk_threshold_percent: 80, emergency_threshold_percent: 90, retention: null },
		});
		render(SystemPage);
		await screen.findByText('91.5% used');

		expect(stage('NetTap').word).toBe('Failing');
		expect(stage('OpenSearch')).toEqual({ word: 'Failing', detail: 'Not reachable' });
		expect(stage('Storage').word).toBe('Failing');
		expect(stage('Storage').detail).toBe('91.5% used · 9 B free · above the 90% emergency line');
	});

	it("judges the disk by the daemon's own pruning lines, not a threshold of its own (S6)", async () => {
		stubReplies({
			...OK_REPLIES,
			'/api/storage/status': { disk_usage_percent: 82, disk_total_bytes: 100, disk_used_bytes: 82, disk_free_bytes: 18, disk_threshold_percent: 70, emergency_threshold_percent: 80, retention: null },
		});
		render(SystemPage);
		await screen.findByText('82.0% used');
		// the old fixed 85% line called this fine; the configured 80% emergency line says otherwise
		expect(stage('Storage')).toEqual({ word: 'Failing', detail: '82.0% used · 18 B free · above the 80% emergency line' });
	});

	it('says incomplete, not degraded, when a check could not run (S5)', async () => {
		stubReplies({ ...OK_REPLIES, '/api/system/health': { uptime: 60, timestamp: '2026-11-02T00:00:00Z', status: 'incomplete', healthy: null, opensearch_reachable: true } });
		render(SystemPage);
		await screen.findByText('42.0% used');
		// OLD CODE: expect(stage('NetTap')).toEqual({ word: 'Unknown', … }) (NET-168: amber now)
		expect(stage('NetTap')).toEqual({ word: 'Warning', detail: "Incomplete · some checks couldn't run" });
		expect(screen.getByText('Incomplete')).toHaveClass('chip', 'is-caution');
		expect(screen.queryByText('Degraded')).not.toBeInTheDocument();
	});

	it('says unknown when a daemon older than the web app sends no status', async () => {
		stubReplies({ ...OK_REPLIES, '/api/system/health': { uptime: 60, timestamp: '2026-11-02T00:00:00Z', healthy: true, opensearch_reachable: true } });
		render(SystemPage);
		await screen.findByText('42.0% used');
		expect(stage('NetTap')).toEqual({ word: 'Unknown', detail: 'Unknown' });
		expect(screen.getByText('Unknown', { selector: '.chip' })).toBeInTheDocument();
	});

	// F2: the same words as Home's Data stage
	it('says which sensor stopped in the Data and sensors row', async () => {
		const sensors = { 'nettap-zeek-live': 'running', 'nettap-suricata-live': 'exited', 'nettap-logstash': 'running', 'nettap-filebeat': 'running' };
		const pipeline = { state: 'sensor_stopped', newest_record_at: null, age_seconds: 30, threshold_seconds: 900, sensors, checked_at: '2026-11-08T21:00:00Z' };
		stubReplies({ ...OK_REPLIES, '/api/system/health': { uptime: 60, timestamp: '2026-11-08T21:00:00Z', status: 'problem', healthy: false, opensearch_reachable: true, pipeline } });
		render(SystemPage);
		await screen.findByText('42.0% used');
		expect(stage('Data and sensors')).toEqual({ word: 'Failing', detail: 'Suricata stopped' });
		expect(stage('NetTap').word).toBe('Failing');
	});

	it('says unknown for the Data and sensors row when the daemon sends no pipeline', async () => {
		stubReplies(OK_REPLIES);
		render(SystemPage);
		await screen.findByText('42.0% used');
		expect(stage('Data and sensors')).toEqual({ word: 'Unknown', detail: 'Unknown' });
	});

	it('says unknown, never healthy, for a part whose request failed', async () => {
		stubFetch('mirror');
		render(SystemPage);
		await screen.findByText("Couldn't load drive health: the request failed.");

		for (const label of ['NetTap', 'OpenSearch', 'Storage', 'Drive']) {
			expect(stage(label)).toEqual({ word: 'Unknown', detail: 'Request failed' });
		}
	});
});

describe('System page refresh contract', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('registers its loader and reports ok when every request answers', async () => {
		stubReplies(OK_REPLIES);
		render(SystemPage);

		expect(get(pageRefresh).available).toBe(true);
		expect(await refreshPage()).toBe('ok');
	});

	it('reports partial when one request fails', async () => {
		stubReplies({ ...OK_REPLIES, '/api/smart/health': undefined });
		render(SystemPage);

		expect(await refreshPage()).toBe('partial');
	});

	it('reports failed when every request fails', async () => {
		stubReplies({});
		render(SystemPage);

		expect(await refreshPage()).toBe('failed');
	});

	it('writes nothing after the page has gone', async () => {
		const pending: (() => void)[] = [];
		vi.stubGlobal(
			'fetch',
			vi.fn(
				(input: RequestInfo | URL) =>
					new Promise<Response>((resolve) => {
						pending.push(() => resolve(new Response(JSON.stringify(OK_REPLIES[String(input)] ?? {}), { status: 200 })));
					}),
			),
		);
		const { unmount, container } = render(SystemPage);
		unmount();
		pending.forEach((answer) => answer());
		await new Promise((r) => setTimeout(r, 0));

		expect(get(pageRefresh).available).toBe(false);
		expect(container.textContent).not.toContain('% used');
	});
});

// ---------------------------------------------------------------------------
// Accuracy audit 2026-11-06 (S4, S7, S10, S12)
// ---------------------------------------------------------------------------

describe('System page figures', () => {
	afterEach(() => vi.unstubAllGlobals());

	it("labels the uptime as this appliance's, not the daemon's (S4)", async () => {
		stubReplies(OK_REPLIES);
		render(SystemPage);
		expect(await screen.findByText('This appliance · uptime and last check')).toBeInTheDocument();
		expect(screen.queryByText(/NetTap daemon/)).not.toBeInTheDocument();
	});

	it('names each retention setting as Settings does, never the raw key (S7)', async () => {
		stubReplies({
			...OK_REPLIES,
			'/api/storage/status': {
				disk_usage_percent: 42, disk_total_bytes: 100, disk_used_bytes: 42, disk_free_bytes: 58, disk_threshold_percent: 80,
				emergency_threshold_percent: 90, retention: { hot_days: 90, warm_days: 180, cold_days: 30 },
			},
		});
		render(SystemPage);
		expect(await screen.findByText('Hot tier (Zeek metadata and Suricata alerts)')).toBeInTheDocument();
		expect(screen.getByText('90 days')).toBeInTheDocument();
		expect(screen.getByText(/180 days · this install doesn't create them; alerts follow the hot tier/)).toBeInTheDocument();
		expect(screen.getByText(/30 days · or sooner, once PCAP passes its share of the disk/)).toBeInTheDocument();
		expect(screen.queryByText('hot_days')).not.toBeInTheDocument();
	});

	it("shows SMART totals in decimal units, as smartctl does (S10)", async () => {
		stubReplies({
			...OK_REPLIES,
			'/api/smart/health': { ...(OK_REPLIES['/api/smart/health'] as object), total_bytes_written: 18_400_000_000_000, total_bytes_read: 0 },
		});
		render(SystemPage);
		// 18.4 × 10^12 bytes is 18.40 TB to smartctl; the 1024-based figure read 16.7 TB
		expect(await screen.findByText('18.40 TB')).toBeInTheDocument();
		expect(screen.getByText('0 B')).toBeInTheDocument();
	});

	// NET-166: decimal units, so a 1 TB drive reads 1.0 TB (the 1,024-based copy read 931.3 GB)
	it('shows the disk total, used and free in decimal units', async () => {
		stubReplies({
			...OK_REPLIES,
			'/api/storage/status': {
				disk_usage_percent: 40, disk_total_bytes: 1e12, disk_used_bytes: 400e9, disk_free_bytes: 600e9, disk_threshold_percent: 80,
				emergency_threshold_percent: 90, retention: null,
			},
		});
		render(SystemPage);
		const fact = async (label: string) => (await screen.findByText(label, { selector: 'dt' })).nextElementSibling?.textContent;
		// OLD CODE: expect(await fact('Total')).toBe('1.0 TB'); (STO-3: the usable size, reserved blocks out)
		expect(await fact('Usable')).toBe('1.0 TB');
		expect(await fact('Used')).toBe('400.0 GB');
		expect(await fact('Free')).toBe('600.0 GB');
	});

	it('marks a passing drive with warnings amber, not a green Healthy (S12)', async () => {
		stubReplies({
			...OK_REPLIES,
			'/api/smart/health': { ...(OK_REPLIES['/api/smart/health'] as object), warnings: ['Temperature 72°C is above the 70°C warning line'] },
		});
		render(SystemPage);
		expect(await screen.findByText('Warnings')).toHaveClass('chip', 'is-warn');
		const drive = [...document.querySelectorAll('.pipe-item')].find((el) => el.querySelector('.pipe-k')?.textContent?.trim() === 'Drive');
		expect(drive?.querySelector('.pipe-v')?.textContent?.trim()).toBe('SMART checks pass · 1 warning');
	});
});
