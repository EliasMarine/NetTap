import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';
import HomePage from './+page.svelte';
import { pageRefresh, refreshPage, type LoadResult } from '$lib/stores/pageRefresh';
import { _configure } from '$lib/stores/alertSnapshot';
import { resetNavigation } from '../tests/app-navigation.svelte';

// NET-357: a range pill only writes ?range=, so goto must move the URL the page reads its range from
vi.mock('$app/state', () => import('../tests/app-navigation.svelte'));
vi.mock('$app/navigation', () => import('../tests/app-navigation.svelte'));
beforeEach(() => resetNavigation('http://localhost/'));

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

// NET-348: every Home card keeps its last figures on a failed refresh of the same range and says when
// they loaded; a failure with nothing kept for this range shows the card's error state instead.
describe('Home — kept figures on a failed refresh (NET-348)', () => {
	const GROUP = {
		signature_id: 7, signature: 'ET SCAN Nmap probe', suricata_category: 'Attempted Information Leak', severity: 2,
		severity_label: 'medium', category: 'scan', category_label: 'Scanning', source_ip: '192.168.1.5',
		destination_ip: '203.0.113.9', count: 3, first_seen: '', last_seen: '', trend: 'stable', assessment: '',
		key: { rule_name: 'ET SCAN Nmap probe', source_ip: '192.168.1.5', destination_ip: '203.0.113.9' },
	};
	/** Replies with the alert group in the review list; every other path as `body`. */
	const replyWithGroup = (batch: Call[]) =>
		batch.forEach((c) => (c.path === '/api/alerts/smart' ? c.reply({ ...(body(c.url) as object), alerts: [GROUP], total: 1 }) : c.reply()));
	const kpiLink = (label: string) => screen.getByText(label, { selector: '.kpi-top > span' }).closest('a')!;
	const linkParam = (a: Element, key: string) => new URL(a.getAttribute('href')!, 'http://x').searchParams.get(key);
	/** Every request one load makes, once they have all started. */
	async function nextBatch(start: number): Promise<Call[]> {
		await vi.waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(start + REQUESTS - 1));
		await new Promise((r) => setTimeout(r, 0));
		return calls.slice(start);
	}

	beforeEach(() => {
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		recorded.runs = [];
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(new Date(2026, 10, 20, 20, 41, 30));
		_configure({ now: () => Date.now() }); // the store's clock follows the faked one
		stubDaemon();
	});

	afterEach(() => {
		_configure({ now: Date.now });
		vi.useRealTimers();
		vi.unstubAllGlobals();
	});

	it('a first load that fails shows each error state and never a kept-figures note', async () => {
		(await firstLoad()).forEach((c) => c.fail());
		expect(await recorded.runs[0]).toBe('failed');
		expect(await screen.findByText("Couldn't load bandwidth over time: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load traffic totals: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load the alert count: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load the severity summary: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load the alert summary: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText(/showing figures from|showing the last figures/)).not.toBeInTheDocument();
	});

	it('1h then 1h again a minute later: every card keeps its figures, says when they loaded, and links their own window', async () => {
		replyAll(await firstLoad());
		await recorded.runs[0];
		await fireEvent.click(screen.getByRole('button', { name: '1h' }));
		const hour = await nextBatch(REQUESTS);
		replyWithGroup(hour);
		expect(await recorded.runs[1]).toBe('ok');
		const summaryAsked = summaryCall(hour).url.searchParams;
		const countAsked = hour.find((c) => c.path === '/api/alerts/count')!.url.searchParams;
		expect(await screen.findByText('ET SCAN Nmap probe')).toBeInTheDocument();

		vi.setSystemTime(new Date(2026, 10, 20, 20, 42, 10));
		const start = calls.length;
		const again = refreshPage();
		const failing = await nextBatch(start);
		// the refresh asked for the new minute's window
		expect(summaryCall(failing).url.searchParams.get('to')).not.toBe(summaryAsked.get('to'));
		failing.forEach((c) => c.fail());
		expect(await again).toBe('failed');

		for (const what of ['traffic totals', 'connection totals', 'the alert count', 'the device count', 'bandwidth over time', 'network protocols', 'traffic categories', 'the severity summary', 'the alert groups']) {
			expect(await screen.findByText(`Couldn't refresh ${what}; showing figures from 20:41.`)).toBeInTheDocument();
		}
		expect(connections()).toBe('1');
		expect(screen.getByText('Streaming')).toBeInTheDocument();
		expect(screen.getByText('ET SCAN Nmap probe')).toBeInTheDocument();
		// links keep the window their figures were counted over, not the failed attempt's
		expect(linkParam(kpiLink('Connections'), 'to')).toBe(summaryAsked.get('to'));
		expect(linkParam(kpiLink('Alerts'), 'from')).toBe(countAsked.get('from'));
		expect(linkParam(kpiLink('Alerts'), 'to')).toBe(countAsked.get('to'));
	});

	it("1h then 24h failing: nothing from 1h stands in, each card shows its error state", async () => {
		(await firstLoad()).forEach((c) => c.fail()); // nothing kept for 24 hours
		await recorded.runs[0];
		await fireEvent.click(screen.getByRole('button', { name: '1h' }));
		replyWithGroup(await nextBatch(REQUESTS));
		expect(await recorded.runs[1]).toBe('ok');
		expect(await screen.findByText('ET SCAN Nmap probe')).toBeInTheDocument();

		const start = calls.length;
		await fireEvent.click(screen.getByRole('button', { name: '24h' }));
		(await nextBatch(start)).forEach((c) => c.fail());
		expect(await recorded.runs[2]).toBe('failed');

		expect(await screen.findByText("Couldn't load traffic categories: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load traffic totals: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load the device count: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load the alert summary: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load the severity summary: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText(/showing figures from|showing the last figures/)).not.toBeInTheDocument();
		expect(screen.queryByText('ET SCAN Nmap probe')).not.toBeInTheDocument();
		expect(screen.queryByText('Streaming')).not.toBeInTheDocument();
		expect(connections()).toBe('—');
	});
});
