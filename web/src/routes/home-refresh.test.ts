import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';
import HomePage from './+page.svelte';
import { pageRefresh, refreshPage, type LoadResult } from '$lib/stores/pageRefresh';
import { _configure } from '$lib/stores/alertSnapshot';

// The page refresh contract (PLAN.md §5.5) against Home's real loader: it awaits every request,
// reports ok / partial / failed, and a load that is no longer current writes nothing.

// Every load Home starts goes through its registered handle's run(); record what each returns.
const recorded = vi.hoisted(() => ({ runs: [] as Promise<LoadResult>[] }));
vi.mock('$lib/stores/pageRefresh', async (importOriginal) => {
	const real = await importOriginal<typeof import('$lib/stores/pageRefresh')>();
	return {
		...real,
		registerPageRefresh: (...args: Parameters<typeof real.registerPageRefresh>) => {
			const handle = real.registerPageRefresh(...args);
			const run = () => {
				const p = handle.run();
				recorded.runs.push(p);
				return p;
			};
			return { ...handle, run };
		},
	};
});

const HOUR = 3_600_000;
/** Home makes 15 requests per load. */
const REQUESTS = 15;

interface Call {
	path: string;
	url: URL;
	reply: (body?: unknown) => void;
	fail: () => void;
}
let calls: Call[] = [];

/** A valid reply for each daemon path Home calls; the traffic summary scales with the window. */
function body(url: URL): unknown {
	const from = url.searchParams.get('from') ?? '';
	const to = url.searchParams.get('to') ?? '';
	const hours = from && to ? (new Date(to).getTime() - new Date(from).getTime()) / HOUR : 0;
	switch (url.pathname) {
		case '/api/traffic/summary':
			return { from, to, total_bytes: hours * 1024 ** 3, orig_bytes: 0, resp_bytes: 0, upload_bytes: 0, download_bytes: hours * 1024 ** 3, local_bytes: 0, packet_count: 0, connection_count: hours, top_protocol: 'tcp' };
		case '/api/traffic/bandwidth':
			return { from, to, interval: '1h', series: [{ timestamp: from, orig_bytes: 10, resp_bytes: 20, upload_bytes: 10, download_bytes: 20, local_bytes: 0, total_bytes: 30, connections: 1 }] };
		case '/api/traffic/protocols':
			return { from, to, protocols: [{ name: 'tcp', count: 9 }], services: [{ name: 'dns', count: 3 }] };
		case '/api/traffic/categories':
			return { from, to, categories: [{ name: 'streaming', label: 'Streaming', total_bytes: 5_000_000, connection_count: 4, device_count: 1 }] };
		case '/api/devices/count':
			return { from, to, count: 3 };
		case '/api/devices/registry/new-count':
			return { count: 0, since: url.searchParams.get('since') };
		case '/api/alerts/timeline':
			return { from, to, interval: url.searchParams.get('interval') ?? '1h', buckets: [] };
		case '/api/alerts/count':
			return { from, to, counts: { total: 4, high: 1, medium: 1, low: 1 } };
		case '/api/system/health':
			return { uptime: 60, timestamp: '', storage: null, smart: null, healthy: true, opensearch_reachable: true };
		case '/api/alerts/smart':
			return { from, to, device_ip: null, alerts: [], total: 0 };
		case '/api/alerts/smart/summary':
			return { from, to, threat_score: 0, threat_level: 'none', total_groups: 0, total_events: 0, categories: {}, top_threats: [] };
		case '/api/devices':
			return { from, to, limit: 5, devices: [] };
		case '/api/capture/health':
			return { mode: 'bridge', status: 'normal', capture_interface: 'br0', link_up: true, promisc_enabled: true, issues: [] };
		case '/api/capture/stats':
			return { capture_interface: 'br0', rx_bytes: 0, tx_bytes: 0, rx_packets: 10, tx_packets: 0, rx_dropped: 0, rx_missed_errors: 0, link_speed_mbps: 1000, drop_rate_pct: 0 };
		default:
			throw new Error(`unexpected request ${url.pathname}`);
	}
}

/** Every request waits until the test replies to it or fails it. */
function stubDaemon(): void {
	calls = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(
			(input: string) =>
				new Promise((resolve) => {
					const url = new URL(input, 'http://x');
					calls.push({
						path: url.pathname,
						url,
						reply: (b = body(url)) => resolve({ ok: true, status: 200, json: async () => b }),
						fail: () => resolve({ ok: false, status: 503, json: async () => ({}) }),
					});
				}),
		),
	);
}

const replyAll = (batch: Call[]) => batch.forEach((c) => c.reply());
const summaryCall = (batch: Call[]) => batch.find((c) => c.path === '/api/traffic/summary')!;
const otherThanSummary = (batch: Call[]) => batch.filter((c) => c !== summaryCall(batch));
const summaryReply = (c: Call, connections: number) => c.reply({ ...(body(c.url) as object), connection_count: connections });

/** The Connections KPI's number. */
const connections = () =>
	screen.getByText('Connections', { selector: '.kpi-top > span' }).closest('.kpi')?.querySelector('.kpi-num')?.textContent?.trim();

async function firstLoad(): Promise<Call[]> {
	render(HomePage);
	await vi.waitFor(() => expect(calls).toHaveLength(REQUESTS));
	return calls.slice();
}

describe('Home — page refresh contract', () => {
	beforeEach(() => {
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		recorded.runs = [];
		_configure({}); // a fresh alert snapshot store, so no request is shared between tests
		stubDaemon();
	});

	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
	});

	it('returns ok when every request succeeds, and moves "Updated"', async () => {
		replyAll(await firstLoad());
		expect(await recorded.runs[0]).toBe('ok');
		expect(get(pageRefresh)).toMatchObject({ status: 'ok' });
		expect(get(pageRefresh).updatedAt).not.toBeNull();
	});

	it('returns partial when one request fails, and keeps the last "Updated"', async () => {
		const batch = await firstLoad();
		batch.forEach((c) => (c.path === '/api/traffic/categories' ? c.fail() : c.reply()));
		expect(await recorded.runs[0]).toBe('partial');
		expect(get(pageRefresh)).toMatchObject({ status: 'partial', updatedAt: null });
	});

	it('returns failed when every request fails', async () => {
		(await firstLoad()).forEach((c) => c.fail());
		expect(await recorded.runs[0]).toBe('failed');
		expect(get(pageRefresh)).toMatchObject({ status: 'failed', updatedAt: null });
		expect(screen.getByText(/Unable to reach the monitoring daemon/)).toBeInTheDocument();
	});

	it('has not returned while a request is still pending', async () => {
		const batch = await firstLoad();
		let settled = false;
		void recorded.runs[0].then(() => (settled = true));
		otherThanSummary(batch).forEach((c) => c.reply());
		await new Promise((r) => setTimeout(r, 0));
		expect(settled).toBe(false);

		summaryCall(batch).reply();
		expect(await recorded.runs[0]).toBe('ok');
	});

	it('shows only the newest data when responses complete in reverse order', async () => {
		const older = await firstLoad();
		const newerRun = refreshPage();
		// OLD CODE START — a refresh used to join the older load's snapshot request for the same window
		// await vi.waitFor(() => expect(calls.length).toBe(REQUESTS * 2 - 1));
		// OLD CODE END
		// a refresh starts a new alert snapshot window, so the newer load asks for its own count
		await vi.waitFor(() => expect(calls.length).toBe(REQUESTS * 2));
		const newer = calls.slice(REQUESTS);

		summaryReply(summaryCall(newer), 222);
		otherThanSummary(newer).forEach((c) => c.reply());
		otherThanSummary(older).forEach((c) => c.reply());
		expect(await newerRun).toBe('ok');
		expect(connections()).toBe('222');

		summaryReply(summaryCall(older), 111);
		expect(await recorded.runs[0]).toBe('skipped');
		expect(connections()).toBe('222');
	});

	it('drops the older result when the range changes mid-refresh; the pills and the data agree', async () => {
		const older = await firstLoad();
		await fireEvent.click(screen.getByRole('button', { name: '1h' }));
		await vi.waitFor(() => expect(calls).toHaveLength(REQUESTS * 2));
		const newer = calls.slice(REQUESTS);
		expect(new URL(summaryCall(newer).url).searchParams.get('from')).not.toBe(summaryCall(older).url.searchParams.get('from'));

		summaryReply(summaryCall(older), 111);
		otherThanSummary(older).forEach((c) => c.reply());
		expect(await recorded.runs[0]).toBe('skipped');
		expect(connections()).toBe('—'); // the 24 h figures never land on the 1 h view

		summaryReply(summaryCall(newer), 222);
		otherThanSummary(newer).forEach((c) => c.reply());
		expect(await recorded.runs[1]).toBe('ok');
		expect(connections()).toBe('222');
		expect(screen.getByRole('button', { name: '1h' })).toHaveAttribute('aria-pressed', 'true');
		expect(screen.getByRole('button', { name: '24h' })).toHaveAttribute('aria-pressed', 'false');
		expect(screen.getByText('Traffic, alerts and capture health · last hour')).toBeInTheDocument();
	});

	it('writes nothing after the page has gone', async () => {
		render(HomePage).unmount();
		await vi.waitFor(() => expect(calls).toHaveLength(REQUESTS));
		replyAll(calls);
		expect(await recorded.runs[0]).toBe('skipped');
		expect(get(pageRefresh)).toMatchObject({ available: false, updatedAt: null, status: null });
	});

	it('a Refresh moves the shared alert count to a new window, as Alerts does', async () => {
		let clock = Date.parse('2026-11-03T12:00:30Z');
		_configure({ now: () => clock });
		try {
			replyAll(await firstLoad());
			await recorded.runs[0];
			const snapshotTo = (batch: Call[]) => batch.filter((c) => c.path === '/api/alerts/count').map((c) => c.url.searchParams.get('to'));
			expect(snapshotTo(calls)).toContain('2026-11-03T12:00:00.000Z');

			clock += 2 * 60_000;
			const again = refreshPage();
			await vi.waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(REQUESTS * 2 - 1));
			expect(snapshotTo(calls.slice(REQUESTS))).toContain('2026-11-03T12:02:00.000Z');
			replyAll(calls.slice(REQUESTS));
			expect(await again).toBe('ok');
		} finally {
			_configure({ now: Date.now });
		}
	});

	it('runs the 30 s Auto refresh through the same loader, and stops it when paused', async () => {
		vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
		replyAll(await firstLoad());
		await recorded.runs[0];

		vi.advanceTimersByTime(30_000);
		expect(recorded.runs).toHaveLength(2);
		await vi.waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(REQUESTS * 2 - 1));
		replyAll(calls.slice(REQUESTS));
		await recorded.runs[1];

		await fireEvent.click(screen.getByRole('button', { name: 'Auto' }));
		expect(screen.getByRole('button', { name: 'Paused' })).toBeInTheDocument();
		const afterToggle = recorded.runs.length; // toggling loads once, as before
		vi.advanceTimersByTime(60_000);
		expect(recorded.runs).toHaveLength(afterToggle);
	});
});
