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
				disk_usage_percent: 42, disk_total_bytes: 100, disk_used_bytes: 42, disk_free_bytes: 58, retention: null,
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
			'/api/system/health': { uptime: 60, timestamp: '2026-11-02T00:00:00Z', healthy: true, opensearch_reachable: true },
			'/api/storage/status': { disk_usage_percent: 42, disk_total_bytes: 100, disk_used_bytes: 42, disk_free_bytes: 58, retention: null },
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
	'/api/system/health': { uptime: 3600, timestamp: '2026-11-02T00:00:00Z', healthy: true, opensearch_reachable: true },
	'/api/storage/status': { disk_usage_percent: 42, disk_total_bytes: 100, disk_used_bytes: 42, disk_free_bytes: 58, retention: null, total_indices: 7 },
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

		expect(stage('NetTap')).toEqual({ word: 'Healthy', detail: 'Up 1h' });
		expect(stage('OpenSearch')).toEqual({ word: 'Healthy', detail: 'Connected' });
		expect(stage('Storage')).toEqual({ word: 'Healthy', detail: '42.0% used · 58 B free' });
		expect(stage('Drive')).toEqual({ word: 'Healthy', detail: 'SMART checks pass' });
	});

	it('marks a full disk and an unreachable OpenSearch failing', async () => {
		stubReplies({
			...OK_REPLIES,
			'/api/system/health': { uptime: 60, timestamp: '2026-11-02T00:00:00Z', healthy: false, opensearch_reachable: false },
			'/api/storage/status': { disk_usage_percent: 91.5, disk_total_bytes: 100, disk_used_bytes: 91, disk_free_bytes: 9, retention: null },
		});
		render(SystemPage);
		await screen.findByText('91.5% used');

		expect(stage('NetTap').word).toBe('Failing');
		expect(stage('OpenSearch')).toEqual({ word: 'Failing', detail: 'Not reachable' });
		expect(stage('Storage').word).toBe('Failing');
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
