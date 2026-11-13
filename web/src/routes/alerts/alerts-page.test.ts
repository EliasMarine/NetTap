/**
 * /alerts after the redesign: the refresh contract against the real loader (PLAN.md §5.5),
 * the shared severity snapshot (§4.1), every card's states, and the drawer column's
 * preservation checklist (§5.3: Related events, Raw JSON, copy buttons, acknowledge /
 * suppress / false positive and their errors, and the destination links).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
// OLD CODE START: import { readable, get } from 'svelte/store'; — the page mock no longer uses readable OLD CODE END
import { get } from 'svelte/store';
import {
	getAlerts,
	getAlertCount,
	getAlertTimeline,
	getAlertTopSignatures,
	getAlertTopIps,
	getEnhancedCategories,
	getSmartAlertSummary,
	acknowledgeAlert,
	suppressAlert,
	markFalsePositive,
	type Alert,
	type AlertsListResponse,
	THREAT_SCORE_HOW,
	THREAT_SCORE_BRIDGE,
} from '$api/alerts';
import { getSystemHealth, type SystemHealth } from '$api/system';
import { _configure as resetAlertSnapshots, alertSnapshots, loadAlertSnapshot } from '$lib/stores/alertSnapshot';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import { goto } from '$app/navigation';
import Page from './+page.svelte';
import { captureMode } from '$lib/stores/captureMode';
import { expectNoNestedInteractive } from '../../tests/nested-interactive';

/** NET-160: the daemon's LAN policy, so LAN addresses link to their device page. */
const LAN_POLICY = { version: 'v1', subnets: ['192.168.1.0/24'], source: 'env', ipv6: 'not-lan' };
const lanReply = () => Promise.resolve({ ok: true, status: 200, json: async () => LAN_POLICY });

// OLD CODE START — a fixed URL, so ?range= couldn't be tested
// vi.mock('$app/stores', () => ({
// 	page: readable({ url: new URL('http://localhost/alerts') }),
// }));
// OLD CODE END
// OLD CODE START — slice 2a: the URL never changed after the first read, and goto went nowhere
// const nav = vi.hoisted(() => ({ url: new URL('http://localhost/alerts') }));
// vi.mock('$app/stores', () => ({
// 	page: { subscribe: (fn: (v: { url: URL }) => void) => (fn({ url: nav.url }), () => {}) },
// }));
// vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
// OLD CODE END
/** The page's URL: setting `nav.url` is a same-route navigation, and goto() sets it as SvelteKit would. */
const nav = vi.hoisted(() => {
	let url = new URL('http://localhost/alerts');
	const readers = new Set<(v: { url: URL }) => void>();
	return {
		get url() {
			return url;
		},
		set url(next: URL) {
			url = next;
			for (const fn of readers) fn({ url });
		},
		subscribe(fn: (v: { url: URL }) => void) {
			readers.add(fn);
			fn({ url });
			return () => readers.delete(fn);
		},
	};
});
vi.mock('$app/stores', () => ({ page: { subscribe: nav.subscribe } }));
vi.mock('$app/navigation', () => ({
	goto: vi.fn(async (href: string) => {
		nav.url = new URL(href, nav.url);
	}),
}));
vi.mock('$api/alerts', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/alerts')>()),
	getAlerts: vi.fn(),
	getAlertCount: vi.fn(),
	getAlertTimeline: vi.fn(),
	getAlertTopSignatures: vi.fn(),
	getAlertTopIps: vi.fn(),
	getEnhancedCategories: vi.fn(),
	getSmartAlertSummary: vi.fn(),
	acknowledgeAlert: vi.fn(),
	suppressAlert: vi.fn(),
	markFalsePositive: vi.fn(),
}));

// NET-228: the page reads the pipeline's state for its zero messages
vi.mock('$api/system', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/system')>()),
	getSystemHealth: vi.fn(),
}));

/** A health reply whose pipeline is `state` (fresh by default). */
function healthWith(state: NonNullable<SystemHealth['pipeline']>['state'] = 'fresh', over: Partial<NonNullable<SystemHealth['pipeline']>> = {}): SystemHealth {
	return {
		uptime: 1, timestamp: '', storage: null, smart: null, opensearch_reachable: true, status: 'healthy', healthy: true,
		pipeline: { state, newest_record_at: '', age_seconds: 40, threshold_seconds: 900, sensors: {}, checked_at: '', ...over },
	};
}

vi.stubGlobal(
	'ResizeObserver',
	class {
		observe() {}
		unobserve() {}
		disconnect() {}
	},
);

function deferred<T>() {
	let resolve!: (v: T) => void;
	let reject!: (e: unknown) => void;
	const promise = new Promise<T>((res, rej) => {
		resolve = res;
		reject = rej;
	});
	return { promise, resolve, reject };
}

// OLD CODE START — slice 2a: the pills carried the counts ("High 3"); they are labels only now
// /** A severity filter pill (its label carries the count). */
// const severityPill = (word: string) =>
// 	within(screen.getByRole('group', { name: 'Severity' })).getByRole('button', { name: new RegExp(`^${word} `) });
// OLD CODE END
/** A severity filter pill. */
const severityPill = (word: string) => within(screen.getByRole('group', { name: 'Severity' })).getByRole('button', { name: word });
/** The counted-alerts count requests (the severity card's), leaving out the activity count (NET-191). */
const countedCalls = () => vi.mocked(getAlertCount).mock.calls.filter(([opts]) => !opts?.activity);

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

const range = { from: '', to: '' };

// OLD CODE: function alert(id: string, over: Partial<Alert> & { severity?: number; signature?: string; sid?: number; category?: string } = {}): Alert { (slice 2b-2: rule_category)
function alert(id: string, over: Partial<Alert> & { severity?: number; signature?: string; sid?: number; category?: string; rule_category?: string[] } = {}): Alert {
	// OLD CODE: const { severity = 2, signature = `Sig ${id}`, sid = 2000, category = 'Potentially Bad Traffic', ...rest } = over; (slice 2b-2)
	const { severity = 2, signature = `Sig ${id}`, sid = 2000, category = 'Potentially Bad Traffic', rule_category, ...rest } = over;
	return {
		_id: id,
		_index: 'suricata-x',
		timestamp: '2026-11-03T10:00:00Z',
		// OLD CODE: alert: { signature, signature_id: sid, severity, category }, (slice 2b-2: the daemon nests rule_category here)
		alert: { signature, signature_id: sid, severity, category, ...(rule_category ? { rule_category } : {}) },
		// Malcolm's rule.name, which the list's signature filter matches (slice 2b-1); override with `rule`
		rule: { name: signature },
		src_ip: '192.168.1.42',
		src_port: 51842,
		dest_ip: '203.0.113.45',
		dest_port: 8080,
		proto: 'tcp',
		acknowledged: false,
		...rest,
	};
}

function list(alerts: Alert[], page = 1, total = alerts.length): AlertsListResponse {
	return { ...range, page, size: 50, total, total_pages: Math.max(1, Math.ceil(total / 50)), alerts };
}

/** Every request succeeds with a small, real-shaped answer. */
function succeedAll(rows: Alert[] = [alert('a1')]) {
	vi.mocked(getAlerts).mockResolvedValue(list(rows));
	vi.mocked(getAlertCount).mockResolvedValue({ ...range, counts: { total: 40, high: 3, medium: 7, low: 20 } });
	vi.mocked(getAlertTimeline).mockResolvedValue({
		...range,
		interval: '1h',
		buckets: [
			{ timestamp: '2026-11-03T09:00:00Z', high: 1, medium: 2, low: 3 },
			{ timestamp: '2026-11-03T10:00:00Z', high: 2, medium: 5, low: 17 },
		],
	});
	vi.mocked(getAlertTopSignatures).mockResolvedValue({ ...range, signatures: [{ signature: 'ET SCAN Port sweep', count: 12, severity: 2 }], complete: true, examined: 1 });
	vi.mocked(getAlertTopIps).mockResolvedValue({ ...range, direction: 'dest', ips: [{ ip: '192.168.1.42', count: 9 }], complete: true, examined: 1 });
	vi.mocked(getEnhancedCategories).mockResolvedValue({
		...range,
		categories: [
			{
				id: 'malware_c2', label: 'Malware & C2', icon: 'alert', color: 'red', description: '', count: 5,
				severity_breakdown: { critical: 0, high: 5, medium: 0, low: 0, info: 0 },
				trend: { direction: 'increasing', percentage: 0 }, sparkline: [], sub_categories: [],
			},
		],
	});
	vi.mocked(getSmartAlertSummary).mockResolvedValue({
		...range, threat_score: 42, threat_level: 'medium', total_groups: 6, total_events: 40,
		categories: { 'malware-c2': { label: 'Malware / C2', groups: 1, events: 5 } }, top_threats: [],
	});
}

function failAll() {
	const fail = () => Promise.reject(new Error('HTTP 502'));
	// OLD CODE: for (const fn of [getAlerts, getAlertCount, getAlertTimeline, getAlertTopSignatures, getAlertTopIps, getEnhancedCategories, getSmartAlertSummary]) { (NET-228: and the health)
	for (const fn of [getAlerts, getAlertCount, getAlertTimeline, getAlertTopSignatures, getAlertTopIps, getEnhancedCategories, getSmartAlertSummary, getSystemHealth]) {
		vi.mocked(fn).mockImplementation(fail as never);
	}
}

beforeEach(() => {
	resetAlertSnapshots({});
	vi.clearAllMocks();
	vi.stubGlobal('fetch', vi.fn(lanReply));
	vi.mocked(getSystemHealth).mockResolvedValue(healthWith());
});

afterEach(() => {
	nav.url = new URL('http://localhost/alerts');
	vi.unstubAllGlobals();
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
});

// ---------------------------------------------------------------------------
// Refresh contract (PLAN.md §5.5), against the page's real loader
// ---------------------------------------------------------------------------

describe('Alerts — refresh contract', () => {
	it('reports ok when every request succeeds, and moves "Updated"', async () => {
		succeedAll();
		render(Page);
		await flush();
		expect(await refreshPage()).toBe('ok');
		expect(get(pageRefresh)).toMatchObject({ available: true, status: 'ok' });
		expect(get(pageRefresh).updatedAt).not.toBeNull();
	});

	it('reports partial when one request fails, and that card says so', async () => {
		succeedAll();
		vi.mocked(getAlertTimeline).mockRejectedValue(new Error('HTTP 502'));
		render(Page);
		await flush();
		expect(await refreshPage()).toBe('partial');
		expect(screen.getByText("Couldn't load the alert timeline: the request failed.")).toBeInTheDocument();
		expect(screen.getByText('Sig a1')).toBeInTheDocument();
	});

	it('reports failed when every request fails', async () => {
		failAll();
		render(Page);
		await flush();
		expect(await refreshPage()).toBe('failed');
		expect(get(pageRefresh).updatedAt).toBeNull();
	});

	it('has not returned while a request is still pending', async () => {
		succeedAll();
		const slow = deferred<ReturnType<typeof list>>();
		render(Page);
		await flush();
		vi.mocked(getAlerts).mockReturnValueOnce(slow.promise);
		let result: string | undefined;
		refreshPage().then((r) => (result = r));
		await flush();
		expect(result).toBeUndefined();
		slow.resolve(list([alert('a1')]));
		await flush();
		expect(result).toBe('ok');
	});

	it('shows only the newest range when an older range answers last', async () => {
		succeedAll();
		const day = deferred<ReturnType<typeof list>>();
		const hour = deferred<ReturnType<typeof list>>();
		vi.mocked(getAlerts).mockReturnValueOnce(day.promise).mockReturnValueOnce(hour.promise);
		vi.mocked(getAlertTimeline).mockImplementation(async (opts = {}) => ({
			...range,
			interval: opts.interval ?? '',
			buckets: [{ timestamp: '2026-11-03T10:00:00Z', high: opts.interval === '5m' ? 1 : 9, medium: 0, low: 0 }],
		}));
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: '1h' }));
		hour.resolve(list([alert('hour', { signature: 'Last hour alert' })]));
		await flush();
		day.resolve(list([alert('day', { signature: 'Last day alert' })]));
		await flush();

		expect(screen.getByText('Last hour alert')).toBeInTheDocument();
		expect(screen.queryByText('Last day alert')).not.toBeInTheDocument();
		expect(screen.getByRole('button', { name: '1h' })).toHaveAttribute('aria-pressed', 'true');
		expect(screen.getByRole('img', { name: /with 1 alerts/ })).toBeInTheDocument();
	});

	it('drops a refresh\'s list when the filter changed mid-refresh, and keeps the controls and rows in step', async () => {
		succeedAll([alert('first', { signature: 'First load' })]);
		render(Page);
		await flush();
		const stale = deferred<ReturnType<typeof list>>();
		const filtered = deferred<ReturnType<typeof list>>();
		vi.mocked(getAlerts).mockReturnValueOnce(stale.promise).mockReturnValueOnce(filtered.promise);

		const refreshed = refreshPage();
		await flush();
		await fireEvent.click(severityPill('High'));
		expect(getAlerts).toHaveBeenLastCalledWith(expect.objectContaining({ severity: 1, page: 1 }));
		filtered.resolve(list([alert('hi', { severity: 1, signature: 'Only high' })]));
		await flush();
		stale.resolve(list([alert('old', { signature: 'Unfiltered refresh' })]));
		await refreshed;
		await flush();

		expect(screen.getByText('Only high')).toBeInTheDocument();
		expect(screen.queryByText('Unfiltered refresh')).not.toBeInTheDocument();
		expect(severityPill('High')).toHaveAttribute('aria-pressed', 'true');
		// the rest of the refresh still landed
		expect(screen.getByText('Malware & C2')).toBeInTheDocument();
	});

	it('writes nothing after the page has gone', async () => {
		succeedAll();
		const slow = deferred<ReturnType<typeof list>>();
		vi.mocked(getAlerts).mockReturnValueOnce(slow.promise);
		const { unmount } = render(Page);
		await flush();
		unmount();
		expect(get(pageRefresh)).toMatchObject({ available: false, updatedAt: null });
		slow.resolve(list([alert('late')]));
		await flush();
		expect(get(pageRefresh)).toMatchObject({ available: false, updatedAt: null, status: null });
		expect(screen.queryByText('Sig late')).not.toBeInTheDocument();
	});
});

// ---------------------------------------------------------------------------
// Severity summary: the shared snapshot (PLAN.md §4.1)
// ---------------------------------------------------------------------------

describe('Alerts — window from a link (NET-160)', () => {
	const spanHours = () => {
		const opts = vi.mocked(getAlertTimeline).mock.calls.at(-1)![0]!;
		return (Date.parse(opts.to!) - Date.parse(opts.from!)) / 3_600_000;
	};

	it.each([
		['7d', 168, '6h'],
		['30d', 720, '1d'],
	])('opens on ?range=%s, so a count from the address page matches the list', async (value, hours, interval) => {
		nav.url = new URL(`http://localhost/alerts?ip=198.51.100.10&range=${value}`);
		succeedAll();
		render(Page);
		await flush();
		expect(screen.getByRole('button', { name: value })).toHaveAttribute('aria-pressed', 'true');
		expect(spanHours()).toBe(hours);
		expect(vi.mocked(getAlertTimeline).mock.calls.at(-1)![0]!.interval).toBe(interval);
	});

	it('keeps its own 24 hours for a range it does not offer', async () => {
		nav.url = new URL('http://localhost/alerts?range=90d');
		succeedAll();
		render(Page);
		await flush();
		expect(screen.getByRole('button', { name: '24h' })).toHaveAttribute('aria-pressed', 'true');
		expect(spanHours()).toBe(24);
	});
});

// NET-195: Alerts starts its range in the URL hand-off's first run, whose fallback is the saved default.
describe('Alerts — the saved default range (NET-195)', () => {
	const spans = () =>
		vi.mocked(getAlertTimeline).mock.calls.map(([opts]) => (Date.parse(opts!.to!) - Date.parse(opts!.from!)) / 3_600_000);

	beforeEach(() => {
		localStorage.clear();
		localStorage.setItem('nettap-display-settings', JSON.stringify({ defaultRange: '7d' }));
	});
	afterEach(() => localStorage.clear());

	it('opens on the saved range when the link has none, with one load', async () => {
		succeedAll();
		render(Page);
		await flush();
		expect(spans()).toEqual([168]);
		expect(screen.getByRole('button', { name: '7d' })).toHaveAttribute('aria-pressed', 'true');
	});

	it("opens on the link's range over the saved one", async () => {
		nav.url = new URL('http://localhost/alerts?range=1h');
		succeedAll();
		render(Page);
		await flush();
		expect(spans()).toEqual([1]);
		expect(screen.getByRole('button', { name: '1h' })).toHaveAttribute('aria-pressed', 'true');
	});
});

describe('Alerts — severity summary', () => {
	it('shares the sidebar\'s in-flight count instead of asking again, and shows the same numbers', async () => {
		succeedAll();
		const count = deferred<Awaited<ReturnType<typeof getAlertCount>>>();
		vi.mocked(getAlertCount).mockReturnValueOnce(count.promise);
		const sidebar = loadAlertSnapshot(24); // the shell loads the badge's 24 h window first
		render(Page);
		await flush();
		count.resolve({ ...range, counts: { total: 37, high: 2, medium: 5, low: 20 } });
		await sidebar;
		await flush();

		// OLD CODE: expect(getAlertCount).toHaveBeenCalledTimes(1); (NET-191: the page also counts the activity alerts)
		expect(countedCalls()).toHaveLength(1);
		expect(get(alertSnapshots)[24].data?.counts.total).toBe(37);
		const gauge = screen.getByRole('img', { name: /^37 alerts in the last 24 hours/ });
		expect(gauge).toHaveAccessibleName('37 alerts in the last 24 hours: 2 high, 5 medium, 20 low, 10 info');
		expect(screen.getByRole('button', { name: 'Show info alerts (10)' })).toBeInTheDocument();
		// OLD CODE: expect(severityPill('All')).toHaveTextContent('All 37'); (slice 2a: the pills show no counts)
	});

	it('a refresh starts a new snapshot window, so every reader moves together', async () => {
		succeedAll();
		render(Page);
		await flush();
		vi.mocked(getAlertCount).mockResolvedValue({ ...range, counts: { total: 50, high: 4, medium: 6, low: 30 } });
		await refreshPage();
		await flush();
		// OLD CODE: expect(getAlertCount).toHaveBeenCalledTimes(2); (NET-191: the page also counts the activity alerts)
		expect(countedCalls()).toHaveLength(2);
		expect(get(alertSnapshots)[24].data?.counts.total).toBe(50);
		expect(screen.getByRole('img', { name: /^50 alerts/ })).toBeInTheDocument();
	});

	it('a filter change leaves the global count alone', async () => {
		succeedAll();
		render(Page);
		await flush();
		await fireEvent.click(severityPill('Medium'));
		await flush();
		// OLD CODE: expect(getAlertCount).toHaveBeenCalledTimes(1); (NET-191: the page also counts the activity alerts)
		expect(countedCalls()).toHaveLength(1);
		expect(screen.getByRole('img', { name: /^40 alerts/ })).toBeInTheDocument();
	});

	it('a severity tile filters the list by that severity', async () => {
		succeedAll();
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'Show low alerts (20)' }));
		expect(getAlerts).toHaveBeenLastCalledWith(expect.objectContaining({ severity: 3, page: 1 }));
		expect(severityPill('Low')).toHaveAttribute('aria-pressed', 'true');
	});

	it('the Info filter asks for info alerts, not every alert (I1)', async () => {
		succeedAll();
		render(Page);
		await flush();
		await fireEvent.click(severityPill('Info'));
		expect(getAlerts).toHaveBeenLastCalledWith(expect.objectContaining({ severity: 'info', page: 1 }));
	});

	it('the timeline counts info alerts, so it adds up to the tiles (I1)', async () => {
		succeedAll();
		vi.mocked(getAlertTimeline).mockResolvedValue({
			...range,
			interval: '1h',
			buckets: [{ timestamp: '2026-11-03T09:00:00Z', high: 1, medium: 2, low: 3, info: 4 }],
		});
		render(Page);
		await flush();
		expect(screen.getByRole('img', { name: /^Busiest .*, with 10 alerts$/ })).toBeInTheDocument();
	});

	it('a failed count shows the error, never a gauge or zeros', async () => {
		succeedAll();
		vi.mocked(getAlertCount).mockRejectedValue(new Error('HTTP 502'));
		render(Page);
		await flush();
		expect(screen.getByText("Couldn't load the alert counts: the request failed.")).toBeInTheDocument();
		expect(screen.queryByRole('img', { name: /alerts in the last/ })).not.toBeInTheDocument();
		// OLD CODE: expect(severityPill('All')).toHaveTextContent('All —'); (slice 2a: the pills show no counts)
	});
});

// ---------------------------------------------------------------------------
// Card states
// ---------------------------------------------------------------------------

describe('Alerts — card states', () => {
	it('every card shows its loading state until its data arrives', async () => {
		const never = () => new Promise<never>(() => {});
		for (const fn of [getAlerts, getAlertCount, getAlertTimeline, getAlertTopSignatures, getAlertTopIps, getEnhancedCategories, getSmartAlertSummary]) {
			vi.mocked(fn).mockImplementation(never as never);
		}
		render(Page);
		await flush();
		const loading = screen.getAllByRole('status').map((el) => el.textContent?.trim());
		expect(loading).toEqual(
			expect.arrayContaining([
				'Loading alert counts',
				'Loading alerts',
				'Loading the alert timeline',
				'Loading the threat summary',
				'Loading alert categories',
				'Loading top signatures',
				'Loading affected devices',
				'Loading source IPs',
			]),
		);
	});

	it('the threat summary and categories cards say when their request failed', async () => {
		succeedAll();
		vi.mocked(getSmartAlertSummary).mockRejectedValue(new Error('HTTP 502'));
		vi.mocked(getEnhancedCategories).mockRejectedValue(new Error('HTTP 502'));
		render(Page);
		await flush();
		expect(screen.getByText("Couldn't load the threat summary: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load alert categories: the request failed.")).toBeInTheDocument();
		expect(screen.queryByRole('img', { name: /Threat score/ })).not.toBeInTheDocument();
	});

	// NET-225 (ALR-3): post-NAT, the score counts what the router's firewall blocks
	it('adds the bridge-mode line under the score only in bridge mode', async () => {
		succeedAll();
		// OLD CODE: captureMode.set('bridge'); (review M2: the loader asks again after this file's mode-less replies, so the daemon says bridge)
		vi.stubGlobal('fetch', vi.fn((url: string) =>
			String(url) === '/api/capture/mode' ? Promise.resolve({ ok: true, status: 200, json: async () => ({ mode: 'bridge', interface: 'br0' }) }) : lanReply(),
		));
		try {
			render(Page);
			await flush();
			expect(screen.getByText(THREAT_SCORE_BRIDGE)).toHaveClass('score-how');
		} finally {
			captureMode.set(null);
		}
	});

	// NET-239: what suppressions and the baseline changed is said under the score's method
	it('says under the score what suppressions and the baseline changed', async () => {
		succeedAll();
		vi.mocked(getSmartAlertSummary).mockResolvedValue({
			...range, threat_score: 57, threat_level: 'high', total_groups: 6, total_events: 40, categories: {}, top_threats: [],
			suppressed_findings: 2, busier_window_points: 15,
			baseline: { deviation: 2.4, avg_events: 12, avg_threat_score: 30, history_points: 9, is_anomalous: true, ready: true, earlier_hours: 8 },
		});
		render(Page);
		await flush();
		expect(screen.getByText('2 findings in this window were left out by your suppressions or false-positive marks.')).toHaveClass('score-how');
		expect(screen.getByText('Busier than usual (2.4× the usual 12 events), so +15.')).toHaveClass('score-how');
	});

	it('shows the loaded data: categories link to their page, the threat score and its level', async () => {
		succeedAll();
		const { container } = render(Page);
		await flush();
		// OLD CODE: expect(screen.getByRole('link', { name: 'Malware & C2' })).toHaveAttribute('href', '/alerts/malware_c2'); (NET-185: the bar carries its counts' window)
		const category = new URL(screen.getByRole('link', { name: 'Malware & C2' }).getAttribute('href')!, 'http://localhost');
		const counted = vi.mocked(getEnhancedCategories).mock.calls[0][0]!;
		expect([category.pathname, category.searchParams.get('from'), category.searchParams.get('to'), category.searchParams.get('range')]).toEqual([
			'/alerts/malware_c2', counted.from, counted.to, '24h',
		]);
		expect(screen.getByRole('img', { name: 'Threat score 42 of 100, level medium' })).toBeInTheDocument();
		// NET-164: the ring states its scale, and the card says how the score is worked out
		expect(screen.getByText('of 100')).toBeInTheDocument();
		expect(screen.queryByText('threat score')).not.toBeInTheDocument();
		// OLD CODE: expect(screen.getByText(/rounded down and capped at 100/)).toHaveTextContent(THREAT_SCORE_HOW); (NET-209: new wording)
		expect(screen.getByText(/Rounded down and capped at 100/)).toHaveTextContent(THREAT_SCORE_HOW);
		expect(screen.getByText('Malware / C2')).toBeInTheDocument();
		// NET-160: every 192.168.1.42 link (top affected devices, the table) goes to its device page
		const links = screen.getAllByRole('link', { name: '192.168.1.42' });
		expect(links.length).toBeGreaterThan(1);
		for (const link of links) expect(link).toHaveAttribute('href', '/devices/192.168.1.42');
		expectNoNestedInteractive(container);
	});

	it('a top signature filters the list, and selecting it again clears the filter', async () => {
		succeedAll();
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'Filter alerts by ET SCAN Port sweep' }));
		expect(getAlerts).toHaveBeenLastCalledWith(expect.objectContaining({ signature: 'ET SCAN Port sweep', page: 1 }));
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'Clear the filter for ET SCAN Port sweep' }));
		expect(getAlerts).toHaveBeenLastCalledWith(expect.objectContaining({ signature: undefined }));
	});
});

// ---------------------------------------------------------------------------
// By category: grouped AlertRows
// ---------------------------------------------------------------------------

describe('Alerts — by category', () => {
	it('groups the loaded alerts by category, worst first, one row per signature and source', async () => {
		succeedAll([
			alert('l1', { severity: 3, category: 'Misc activity', signature: 'Low one' }),
			alert('h1', { severity: 1, category: 'Trojan', signature: 'High one', sid: 1, timestamp: '2026-11-03T09:00:00Z' }),
			alert('h2', { severity: 1, category: 'Trojan', signature: 'High one', sid: 1, timestamp: '2026-11-03T10:30:00Z' }),
		]);
		const { container } = render(Page);
		await flush();
		const titles = [...container.querySelectorAll('.group-title')].map((h) => h.textContent);
		expect(titles).toEqual(['Trojan', 'Misc activity']);
		const trojan = container.querySelector('.alert-group')!;
		expect(within(trojan as HTMLElement).getByText('×2')).toBeInTheDocument();
		expect(within(trojan as HTMLElement).getByText('2 alerts')).toBeInTheDocument();
		expect(screen.getByText(/alerts 1 to 3, grouped/)).toBeInTheDocument();
	});
});

// ---------------------------------------------------------------------------
// The drawer column: the preservation checklist
// ---------------------------------------------------------------------------

describe('Alerts — drawer', () => {
	const enriched = alert('e1', {
		signature: 'ET MALWARE CnC Checkin',
		sid: 2900001,
		severity: 1,
		plain_description: 'A device contacted a server that controls infected computers.',
		risk_context: 'The device may be infected.',
		recommendation: 'Disconnect the device and run a malware scan.',
	});

	async function openFromRow() {
		succeedAll([enriched]);
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: /A device contacted a server/ }));
		return screen.getByRole('complementary', { name: 'Alert details' });
	}

	it('opens from a grouped row in the system order, with the advice and the facts', async () => {
		const drawer = await openFromRow();
		expect(within(drawer).getByRole('heading', { name: 'A device contacted a server that controls infected computers.' })).toBeInTheDocument();
		expect(within(drawer).getByText('ET MALWARE CnC Checkin')).toBeInTheDocument();
		expect(within(drawer).getByText('The device may be infected.')).toBeInTheDocument();
		expect(within(drawer).getByText('Disconnect the device and run a malware scan.')).toBeInTheDocument();
		expect(within(drawer).getByText('2900001')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: /A device contacted a server/ })).toHaveAttribute('aria-current', 'true');
		// NET-160 slice 2a: the signature opens the alerts list for it (no count here, so no window)
		expect(within(drawer).getByRole('link', { name: 'ET MALWARE CnC Checkin' })).toHaveAttribute('href', '/alerts?signature=ET+MALWARE+CnC+Checkin');
	});

	it('says there is no advice instead of inventing one, and titles by category without a description', async () => {
		succeedAll([alert('bare', { category: 'Misc activity', signature: 'ET INFO Bare' })]);
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: /Misc activity/ }));
		const drawer = screen.getByRole('complementary', { name: 'Alert details' });
		expect(within(drawer).getByRole('heading', { name: 'Misc activity' })).toBeInTheDocument();
		expect(within(drawer).getByText('No specific advice for this alert yet.')).toBeInTheDocument();
	});

	it('links to the connections, both devices and the Log Explorer', async () => {
		const drawer = await openFromRow();
		expect(within(drawer).getByRole('link', { name: 'View connections' })).toHaveAttribute('href', '/connections?ip=192.168.1.42');
		// OLD CODE START — NET-160: "View … device" sent internet addresses to a device page
		// expect(within(drawer).getByRole('link', { name: 'View source device' })).toHaveAttribute('href', '/devices/192.168.1.42');
		// expect(within(drawer).getByRole('link', { name: 'View destination device' })).toHaveAttribute('href', '/devices/203.0.113.45');
		// OLD CODE END
		expect(within(drawer).getByRole('link', { name: 'Open source device' })).toHaveAttribute('href', '/devices/192.168.1.42');
		expect(within(drawer).getByRole('link', { name: 'Open destination address' })).toHaveAttribute('href', '/address/203.0.113.45');
		expectNoNestedInteractive(drawer);
		const logs = within(drawer).getByRole('link', { name: 'View in Log Explorer' }).getAttribute('href')!;
		expect(decodeURIComponent(logs)).toBe('/logs?query=(source.ip:"192.168.1.42" OR destination.ip:"192.168.1.42") OR (source.ip:"203.0.113.45" OR destination.ip:"203.0.113.45")');
	});

	it('acknowledges, and says so when the daemon refuses', async () => {
		const drawer = await openFromRow();
		vi.mocked(acknowledgeAlert).mockResolvedValueOnce(null);
		await fireEvent.click(within(drawer).getByRole('button', { name: 'Acknowledge' }));
		await flush();
		expect(within(drawer).getByRole('alert')).toHaveTextContent('Not applied: the acknowledgement failed. Try again.');

		vi.mocked(acknowledgeAlert).mockResolvedValueOnce({ result: 'ok', alert_id: 'e1', acknowledged_at: '2026-11-03T11:00:00Z', acknowledged_by: 'me' });
		await fireEvent.click(within(drawer).getByRole('button', { name: 'Acknowledge' }));
		await flush();
		expect(acknowledgeAlert).toHaveBeenLastCalledWith('e1');
		expect(within(drawer).queryByRole('button', { name: 'Acknowledge' })).not.toBeInTheDocument();
		expect(within(drawer).getByText(/^Acknowledged/)).toBeInTheDocument();
		expect(within(drawer).queryByRole('alert')).not.toBeInTheDocument();
	});

	it('suppresses and marks a false positive from the drawer, with the daemon\'s reason on failure', async () => {
		const drawer = await openFromRow();
		vi.mocked(suppressAlert).mockResolvedValueOnce();
		await fireEvent.click(within(drawer).getByRole('button', { name: 'Suppress' }));
		await flush();
		expect(suppressAlert).toHaveBeenCalledWith(2900001);
		expect(getAlerts).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1 }));

		vi.mocked(markFalsePositive).mockRejectedValueOnce(new Error('Mark false positive failed: 500'));
		await fireEvent.click(within(drawer).getByRole('button', { name: 'False positive' }));
		await flush();
		expect(markFalsePositive).toHaveBeenCalledWith(2900001);
		expect(within(drawer).getByRole('alert')).toHaveTextContent('Not applied: Mark false positive failed: 500');
	});

	it('loads Related events when opened, and retries after a failure', async () => {
		const fetchMock = vi.fn()
			.mockResolvedValueOnce({ ok: false, status: 502, json: async () => ({}) })
			.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ hits: [{ _id: 'z1', _source: { '@timestamp': '2026-11-03T10:01:00Z', 'event.dataset': 'conn', 'source.ip': '192.168.1.42', 'destination.ip': '203.0.113.45' } }] }) });
		// NET-160: the address links fetch the LAN policy themselves, and the loader the capture mode; only the drawer's requests are counted
		// OLD CODE: … (String(url) === '/api/network/lan' ? lanReply() : fetchMock(url)) (review M2: an unknown mode is asked again each load)
		vi.stubGlobal('fetch', vi.fn((url: string) => (['/api/network/lan', '/api/capture/mode'].includes(String(url)) ? lanReply() : fetchMock(url))));
		const drawer = await openFromRow();
		expect(fetchMock).not.toHaveBeenCalled();
		await fireEvent.click(within(drawer).getByRole('button', { name: /Related events/ }));
		await flush();
		expect(String(fetchMock.mock.calls[0][0])).toMatch(/^\/api\/logs\/search\?/);
		expect(within(drawer).getByText('Failed to fetch related events')).toBeInTheDocument();
		await fireEvent.click(within(drawer).getByRole('button', { name: 'Retry' }));
		await flush();
		expect(within(drawer).getByText('conn')).toBeInTheDocument();
	});

	it('copies the raw JSON and the alert ID', async () => {
		const writeText = vi.fn().mockResolvedValue(undefined);
		vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
		const drawer = await openFromRow();
		await fireEvent.click(within(drawer).getByRole('button', { name: /Raw JSON/ }));
		await fireEvent.click(within(drawer).getByRole('button', { name: 'Copy JSON' }));
		expect(JSON.parse(writeText.mock.calls[0][0])).toMatchObject({ _id: 'e1', alert: { signature_id: 2900001 } });

		await fireEvent.click(within(drawer).getByRole('button', { name: /Metadata/ }));
		await fireEvent.click(within(drawer).getByRole('button', { name: /^e1/ }));
		expect(writeText).toHaveBeenLastCalledWith('e1');
	});

	it('closes with its close button and with Escape', async () => {
		let drawer = await openFromRow();
		await fireEvent.click(within(drawer).getByRole('button', { name: 'Close details' }));
		expect(screen.queryByRole('complementary', { name: 'Alert details' })).not.toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: /A device contacted a server/ }));
		drawer = screen.getByRole('complementary', { name: 'Alert details' });
		await fireEvent.keyDown(window, { key: 'Escape' });
		expect(screen.queryByRole('complementary', { name: 'Alert details' })).not.toBeInTheDocument();
	});

	it('table rows: Suppress and False positive work without opening the drawer; a row click opens it once', async () => {
		succeedAll([enriched]);
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'All alerts' }));

		vi.mocked(suppressAlert).mockResolvedValueOnce();
		await fireEvent.click(screen.getByRole('button', { name: 'Suppress' }));
		await flush();
		expect(suppressAlert).toHaveBeenCalledTimes(1);
		expect(screen.queryByRole('complementary', { name: 'Alert details' })).not.toBeInTheDocument();

		vi.mocked(markFalsePositive).mockRejectedValueOnce(new Error('Mark false positive failed: 500'));
		await fireEvent.click(screen.getByRole('button', { name: 'False positive' }));
		await flush();
		expect(markFalsePositive).toHaveBeenCalledTimes(1);
		expect(screen.getByRole('alert')).toHaveTextContent('Not applied: Mark false positive failed: 500');
		expect(screen.queryByRole('complementary', { name: 'Alert details' })).not.toBeInTheDocument();

		const row = screen.getByText('ET MALWARE CnC Checkin').closest('tr')!;
		await fireEvent.click(row);
		expect(screen.getByRole('complementary', { name: 'Alert details' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Open alert ET MALWARE CnC Checkin from 192.168.1.42' })).toHaveAttribute('aria-current', 'true');
	});

	it('keeps the sorted column marked after switching views and back', async () => {
		succeedAll([enriched]);
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'All alerts' }));
		const table = () => screen.getByRole('table', { name: /Alerts, newest first/ });
		await fireEvent.click(within(table()).getByRole('button', { name: /Severity/ }));
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'By category' }));
		await fireEvent.click(screen.getByRole('button', { name: 'All alerts' }));
		await flush();
		expect(within(table()).getByRole('columnheader', { name: /Severity/ })).toHaveAttribute('aria-sort');
		expect(within(table()).getByRole('columnheader', { name: /Time/ })).toHaveAttribute('aria-sort', 'none');
	});
});

// ---------------------------------------------------------------------------
// NET-160 slice 2a: the URL is the one source of the list's filters and window, and a count
// opens a list over that count's own window. Every test reads the outgoing request, not just hrefs.
// ---------------------------------------------------------------------------

describe('Alerts — URL hand-off and exact windows (NET-160 slice 2a)', () => {
	const FROM = '2026-11-01T08:00:00.000Z';
	const TO = '2026-11-01T20:00:00.000Z';
	const at = (query: string) => (nav.url = new URL(`http://localhost/alerts${query}`));
	const listCalls = () => vi.mocked(getAlerts).mock.calls.map(([opts]) => opts!);
	const spanHours = (o: { from?: string; to?: string }) => (Date.parse(o.to!) - Date.parse(o.from!)) / 3_600_000;
	/** The count answers for the window it was asked about, as the daemon does. */
	const echoCounts = (counts = { total: 40, high: 3, medium: 7, low: 20 }) =>
		vi.mocked(getAlertCount).mockImplementation(async (opts = {}) => ({ from: opts.from!, to: opts.to!, counts }));

	afterEach(() => {
		vi.useRealTimers();
		resetAlertSnapshots({ now: Date.now });
	});

	it('from page 8, a new signature and range send one page-1 request with both', async () => {
		succeedAll();
		vi.mocked(getAlerts).mockResolvedValue(list([alert('a1')], 8, 1000));
		render(Page);
		await flush();
		vi.mocked(getAlerts).mockClear();
		at('?signature=ET%20SCAN%20Nmap&range=7d');
		await flush();
		expect(listCalls()).toHaveLength(1);
		expect(listCalls()[0]).toMatchObject({ page: 1, signature: 'ET SCAN Nmap' });
		expect(spanHours(listCalls()[0])).toBe(168);
	});

	it('a new ip and window together send one request, on that window', async () => {
		succeedAll();
		render(Page);
		await flush();
		vi.mocked(getAlerts).mockClear();
		at(`?ip=192.168.1.42&from=${FROM}&to=${TO}`);
		await flush();
		expect(listCalls()).toEqual([expect.objectContaining({ page: 1, ip: '192.168.1.42', from: FROM, to: TO })]);
	});

	it('a window-only change sends one request', async () => {
		succeedAll();
		render(Page);
		await flush();
		vi.mocked(getAlerts).mockClear();
		at('?range=7d');
		await flush();
		expect(listCalls()).toHaveLength(1);
		expect(spanHours(listCalls()[0])).toBe(168);
	});

	it('a fresh severity=high link with from/to lists high alerts on exactly those bounds, as Custom', async () => {
		at(`?severity=high&from=${FROM}&to=${TO}&range=24h`);
		succeedAll();
		echoCounts({ total: 12, high: 5, medium: 4, low: 1 });
		render(Page);
		await flush();
		expect(listCalls()).toEqual([expect.objectContaining({ severity: 1, page: 1, from: FROM, to: TO })]);
		expect(screen.getByRole('button', { name: 'Custom' })).toHaveAttribute('aria-pressed', 'true');
		expect(severityPill('High')).toHaveAttribute('aria-pressed', 'true');
		// Custom counts are this page's own, over the same bounds, and the card shows them
		// OLD CODE: expect(getAlertCount).toHaveBeenCalledTimes(1); (NET-191: the page also counts the activity alerts)
		expect(countedCalls()).toHaveLength(1);
		// OLD CODE: expect(getAlertCount).toHaveBeenCalledWith({ from: FROM, to: TO }); (NET-191: the page also counts the activity alerts)
		expect(countedCalls()).toEqual([[{ from: FROM, to: TO }]]);
		expect(screen.getByRole('button', { name: 'Show high alerts (5)' })).toBeInTheDocument();
		expect(screen.getByRole('img', { name: /^12 alerts in the window / })).toBeInTheDocument();
	});

	it('High to Low on the same bounds sends exactly one page-1 list request', async () => {
		at(`?severity=high&from=${FROM}&to=${TO}`);
		succeedAll();
		render(Page);
		await flush();
		vi.mocked(getAlerts).mockClear();
		vi.mocked(getAlertCount).mockClear();
		at(`?severity=low&from=${FROM}&to=${TO}`);
		await flush();
		expect(listCalls()).toEqual([expect.objectContaining({ severity: 3, page: 1, from: FROM, to: TO })]);
		expect(getAlertCount).not.toHaveBeenCalled();
	});

	it('reads an unknown severity as all', async () => {
		at('?severity=critical');
		succeedAll();
		render(Page);
		await flush();
		expect(listCalls()[0].severity).toBeUndefined();
		expect(severityPill('All')).toHaveAttribute('aria-pressed', 'true');
	});

	it('a severity pill writes only severity to the URL, keeping signature, ip and the window', async () => {
		at(`?signature=ET%20SCAN%20Nmap&ip=192.168.1.42&from=${FROM}&to=${TO}&range=7d`);
		succeedAll();
		render(Page);
		await flush();
		await fireEvent.click(severityPill('High'));
		await flush();
		const q = nav.url.searchParams;
		expect([q.get('severity'), q.get('signature'), q.get('ip'), q.get('from'), q.get('to'), q.get('range')]).toEqual([
			'high', 'ET SCAN Nmap', '192.168.1.42', FROM, TO, '7d',
		]);
		expect(vi.mocked(goto).mock.calls.at(-1)![1]).toEqual({ replaceState: true, keepFocus: true, noScroll: true });
		expect(listCalls().at(-1)).toMatchObject({ severity: 1, signature: 'ET SCAN Nmap', ip: '192.168.1.42', from: FROM, to: TO });
	});

	it("clearing the IP chip keeps severity and signature", async () => {
		at('?severity=high&signature=ET%20SCAN%20Nmap&ip=192.168.1.42');
		succeedAll();
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'Clear IP filter' }));
		await flush();
		expect(nav.url.searchParams.get('ip')).toBeNull();
		expect(nav.url.searchParams.get('severity')).toBe('high');
		expect(nav.url.searchParams.get('signature')).toBe('ET SCAN Nmap');
		expect(listCalls().at(-1)).toMatchObject({ severity: 1, signature: 'ET SCAN Nmap', ip: undefined });
	});

	it('a top-signature toggle writes signature to the URL, and the list follows it', async () => {
		succeedAll();
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'Filter alerts by ET SCAN Port sweep' }));
		await flush();
		expect(nav.url.searchParams.get('signature')).toBe('ET SCAN Port sweep');
		expect(listCalls().at(-1)).toMatchObject({ signature: 'ET SCAN Port sweep', page: 1 });
		await fireEvent.click(screen.getByRole('button', { name: 'Clear the filter for ET SCAN Port sweep' }));
		await flush();
		expect(nav.url.searchParams.has('signature')).toBe(false);
	});

	it('a range pill writes range and drops a Custom window', async () => {
		at(`?from=${FROM}&to=${TO}&range=24h`);
		succeedAll();
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: '7d' }));
		await flush();
		expect(nav.url.search).toBe('?range=7d');
		expect(screen.queryByRole('button', { name: 'Custom' })).not.toBeInTheDocument();
		expect(spanHours(listCalls().at(-1)!)).toBe(168);
	});

	it('the severity pills are labels only: the counts are on the tiles', async () => {
		succeedAll();
		render(Page);
		await flush();
		const pills = within(screen.getByRole('group', { name: 'Severity' })).getAllByRole('button');
		expect(pills.map((p) => p.textContent?.trim())).toEqual(['All', 'High', 'Medium', 'Low', 'Info']);
	});

	it('a severity tile clears the signature filter and lists that level over the counts\' bounds', async () => {
		at('?signature=ET%20SCAN%20Nmap');
		succeedAll();
		echoCounts();
		render(Page);
		await flush();
		const shown = get(alertSnapshots)[24].data!;
		await fireEvent.click(screen.getByRole('button', { name: 'Show high alerts (3)' }));
		await flush();
		expect(nav.url.searchParams.has('signature')).toBe(false);
		expect(listCalls().at(-1)).toMatchObject({ severity: 1, signature: undefined, ip: undefined, from: shown.from, to: shown.to });
	});

	it('rolling: minutes after loading, High lists exactly the displayed counts\' window', async () => {
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(new Date('2026-11-06T12:00:30Z'));
		resetAlertSnapshots({ now: () => Date.now() });
		succeedAll();
		echoCounts();
		render(Page);
		await flush();
		const shown = get(alertSnapshots)[24].data!;
		vi.setSystemTime(new Date('2026-11-06T12:07:45Z'));
		await fireEvent.click(screen.getByRole('button', { name: 'Show high alerts (3)' }));
		await flush();
		expect(listCalls().at(-1)).toMatchObject({ severity: 1, page: 1, from: shown.from, to: shown.to });
		expect(shown.to).toBe('2026-11-06T12:00:00.000Z');
	});

	it('after a failed count refresh, High uses the older figures\' window, not the new attempt\'s', async () => {
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(new Date('2026-11-06T12:00:30Z'));
		resetAlertSnapshots({ now: () => Date.now() });
		succeedAll();
		echoCounts();
		render(Page);
		await flush();
		const older = get(alertSnapshots)[24].data!;
		vi.setSystemTime(new Date('2026-11-06T12:10:30Z'));
		vi.mocked(getAlertCount).mockRejectedValueOnce(new Error('HTTP 502'));
		await refreshPage();
		await flush();
		expect(get(alertSnapshots)[24]).toMatchObject({ status: 'error', to: '2026-11-06T12:10:00.000Z', data: older });
		await fireEvent.click(screen.getByRole('button', { name: 'Show high alerts (3)' }));
		await flush();
		expect(listCalls().at(-1)).toMatchObject({ severity: 1, from: older.from, to: older.to });
	});

	it('paging keeps the search\'s window after the clock moves', async () => {
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(new Date('2026-11-06T12:00:30Z'));
		succeedAll();
		vi.mocked(getAlerts).mockImplementation(async (opts = {}) => list([alert(`p${opts.page}`)], opts.page ?? 1, 250));
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'All alerts' }));
		const first = listCalls()[0];
		vi.setSystemTime(new Date('2026-11-06T12:06:00Z'));
		await fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
		await flush();
		expect(listCalls().at(-1)).toMatchObject({ page: 2, from: first.from, to: first.to });
	});

	// OLD CODE: 'a page change during a refresh pages through the rows on screen' expected page 2 to go out
	// mid-refresh; its request discarded the refresh's rows, so the pager now waits for them
	it('during a refresh the pager waits, then pages through the new rows\' window', async () => {
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(new Date('2026-11-06T12:00:30Z'));
		succeedAll();
		vi.mocked(getAlerts).mockImplementation(async (opts = {}) => list([alert(`p${opts.page}`)], opts.page ?? 1, 250));
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'All alerts' }));
		const held = deferred<ReturnType<typeof list>>();
		vi.mocked(getAlerts).mockImplementationOnce(() => held.promise);
		vi.setSystemTime(new Date('2026-11-06T12:06:00Z'));
		void refreshPage();
		await flush();
		const refreshed = listCalls().at(-1)!;
		const next = screen.getByRole('button', { name: 'Next page' });
		expect(next).toBeDisabled();
		const sent = listCalls().length;
		await fireEvent.click(next);
		await flush();
		expect(listCalls()).toHaveLength(sent);
		held.resolve(list([alert('r1')], 1, 250));
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
		await flush();
		expect(listCalls().at(-1)).toMatchObject({ page: 2, from: refreshed.from, to: refreshed.to });
	});

	it('a page asked for while a new search loads can\'t mix its filters with the old window or drop its rows', async () => {
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(new Date('2026-11-06T12:00:30Z'));
		succeedAll();
		vi.mocked(getAlerts).mockImplementation(async (opts = {}) => list([alert(`${opts.signature ?? 'all'}-${opts.page}`)], opts.page ?? 1, 250));
		at(`?signature=A&from=${FROM}&to=${TO}`);
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'All alerts' }));
		const held = deferred<ReturnType<typeof list>>();
		vi.mocked(getAlerts).mockImplementationOnce(() => held.promise);
		at('?signature=B&from=2026-11-02T08:00:00.000Z&to=2026-11-02T20:00:00.000Z');
		await flush();
		const sent = listCalls().length;
		await fireEvent.click(screen.getByRole('button', { name: 'Page 2' }));
		await flush();
		expect(listCalls()).toHaveLength(sent);
		held.resolve(list([alert('B-1')], 1, 250));
		await flush();
		expect(screen.getByRole('button', { name: 'Page 2' })).toBeEnabled();
		await fireEvent.click(screen.getByRole('button', { name: 'Page 2' }));
		await flush();
		expect(listCalls().at(-1)).toMatchObject({ page: 2, signature: 'B', from: '2026-11-02T08:00:00.000Z', to: '2026-11-02T20:00:00.000Z' });
	});

	it("the table's signature links to that signature over the list's own window", async () => {
		succeedAll([alert('a1', { signature: 'ET SCAN Nmap' })]);
		const { container } = render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'All alerts' }));
		const first = listCalls()[0];
		const href = screen.getByRole('link', { name: 'ET SCAN Nmap' }).getAttribute('href')!;
		const q = new URL(href, 'http://localhost').searchParams;
		expect([q.get('signature'), q.get('from'), q.get('to'), q.get('range')]).toEqual(['ET SCAN Nmap', first.from, first.to, '24h']);
		expectNoNestedInteractive(container);
	});

	it("while a new search is loading, the rows' signature links keep the rows' own window", async () => {
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(new Date('2026-11-06T12:00:30Z'));
		succeedAll([alert('a1', { signature: 'ET SCAN Nmap' })]);
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'All alerts' }));
		const first = listCalls()[0];
		const held = deferred<ReturnType<typeof list>>();
		vi.mocked(getAlerts).mockImplementationOnce(() => held.promise);
		vi.setSystemTime(new Date('2026-11-06T12:06:00Z'));
		await fireEvent.click(severityPill('High'));
		await flush();
		const pending = listCalls().at(-1)!;
		expect(pending.from).not.toBe(first.from);
		const linkFrom = () => new URL(screen.getByRole('link', { name: 'ET SCAN Nmap' }).getAttribute('href')!, 'http://localhost').searchParams.get('from');
		expect(linkFrom()).toBe(first.from);
		held.resolve(list([alert('a2', { signature: 'ET SCAN Nmap' })], 1, 1));
		await flush();
		expect(linkFrom()).toBe(pending.from);
	});
});

// ---------------------------------------------------------------------------
// NET-160 slice 2b-1: a smart alert's pair (src, dst) on the list, links by rule.name, and 6h
// ---------------------------------------------------------------------------

describe('Alerts — source, destination, rule-name links and 6h (NET-160 slice 2b-1)', () => {
	const FROM = '2026-11-01T08:00:00.000Z';
	const TO = '2026-11-01T20:00:00.000Z';
	const SRC = '192.168.1.42';
	const DST = '2001:db8::1';
	const at = (query: string) => (nav.url = new URL(`http://localhost/alerts${query}`));
	const listCalls = () => vi.mocked(getAlerts).mock.calls.map(([opts]) => opts!);
	const pairQuery = `?signature=ET%20SCAN%20Nmap&src=${SRC}&dst=${encodeURIComponent(DST)}&from=${FROM}&to=${TO}&range=24h`;

	it('a signature, source, destination and window link sends one request with all five, shown as chips', async () => {
		at(pairQuery);
		succeedAll();
		render(Page);
		await flush();
		expect(listCalls()).toEqual([expect.objectContaining({ page: 1, signature: 'ET SCAN Nmap', src: SRC, dst: DST, from: FROM, to: TO })]);
		expect(listCalls()[0].ip).toBeUndefined();
		expect(screen.getByRole('button', { name: 'Clear source filter' }).closest('.chip')).toHaveTextContent(`From ${SRC}`);
		expect(screen.getByRole('button', { name: 'Clear destination filter' }).closest('.chip')).toHaveTextContent(`To ${DST}`);
	});

	it('clearing the From chip keeps the destination, signature and window', async () => {
		at(pairQuery);
		succeedAll();
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'Clear source filter' }));
		await flush();
		const q = nav.url.searchParams;
		expect([q.get('src'), q.get('dst'), q.get('signature'), q.get('from'), q.get('to'), q.get('range')]).toEqual([null, DST, 'ET SCAN Nmap', FROM, TO, '24h']);
		expect(listCalls().at(-1)).toMatchObject({ src: undefined, dst: DST, signature: 'ET SCAN Nmap', from: FROM, to: TO });
		expect(screen.queryByRole('button', { name: 'Clear source filter' })).not.toBeInTheDocument();
	});

	it('a change of source alone is one page-1 list request, with no reload of the window', async () => {
		at(pairQuery);
		succeedAll();
		render(Page);
		await flush();
		vi.mocked(getAlerts).mockClear();
		vi.mocked(getAlertTimeline).mockClear();
		at(pairQuery.replace(SRC, '192.168.1.43'));
		await flush();
		expect(listCalls()).toEqual([expect.objectContaining({ page: 1, src: '192.168.1.43', dst: DST, from: FROM, to: TO })]);
		expect(getAlertTimeline).not.toHaveBeenCalled();
	});

	it('paging keeps the source and destination', async () => {
		at(pairQuery);
		succeedAll();
		vi.mocked(getAlerts).mockImplementation(async (opts = {}) => list([alert(`p${opts.page}`)], opts.page ?? 1, 250));
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'All alerts' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
		await flush();
		expect(listCalls().at(-1)).toMatchObject({ page: 2, src: SRC, dst: DST, signature: 'ET SCAN Nmap', from: FROM, to: TO });
	});

	it("the table links each row by its rule.name, never a different shown signature, and not at all without one", async () => {
		succeedAll([
			alert('a1', { signature: 'A shown name', rule: { name: 'ET SCAN Raw rule' } }),
			alert('a2', { signature: 'No rule here', rule: undefined }),
		]);
		const { container } = render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'All alerts' }));
		const href = screen.getByRole('link', { name: 'A shown name' }).getAttribute('href')!;
		expect(new URL(href, 'http://localhost').searchParams.get('signature')).toBe('ET SCAN Raw rule');
		expect(screen.queryByRole('link', { name: 'No rule here' })).not.toBeInTheDocument();
		expect(within(screen.getByRole('table', { name: /Alerts, newest first/ })).getByText('No rule here')).toBeInTheDocument();
		expectNoNestedInteractive(container);
	});

	it("the drawer's signature links by rule.name, and is plain text without one", async () => {
		succeedAll([
			alert('a1', { signature: 'A shown name', rule: { name: 'ET SCAN Raw rule' }, category: 'Shown category' }),
			alert('a2', { signature: 'No rule here', rule: undefined, category: 'Bare category' }),
		]);
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: /Shown category/ }));
		let drawer = screen.getByRole('complementary', { name: 'Alert details' });
		expect(within(drawer).getByRole('link', { name: 'A shown name' })).toHaveAttribute('href', '/alerts?signature=ET+SCAN+Raw+rule');
		await fireEvent.click(screen.getByRole('button', { name: /Bare category/ }));
		drawer = screen.getByRole('complementary', { name: 'Alert details' });
		expect(within(drawer).getByText('No rule here')).toBeInTheDocument();
		expect(within(drawer).queryByRole('link', { name: 'No rule here' })).not.toBeInTheDocument();
	});

	// NET-185: the same words as the "No rule name" bar; "Unknown" can be a real rule's name
	it('an alert with no rule name reads "No rule name" in the groups, the table, its row label and the drawer', async () => {
		succeedAll([alert('a1', { signature: '', rule: undefined, category: 'Bare category' })]);
		render(Page);
		await flush();
		expect(screen.getByText('No rule name')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: /Bare category/ }));
		const drawer = screen.getByRole('complementary', { name: 'Alert details' });
		expect(within(drawer).getByText('No rule name')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'All alerts' }));
		const table = screen.getByRole('table', { name: /Alerts, newest first/ });
		expect(within(table).getByText('No rule name')).toBeInTheDocument();
		expect(within(table).queryByRole('link', { name: 'No rule name' })).not.toBeInTheDocument();
		expect(within(table).getByRole('button', { name: 'Open alert with no rule name from 192.168.1.42' })).toBeInTheDocument();
		expect(screen.queryByText('Unknown')).not.toBeInTheDocument();
	});

	it('?range=6h opens the last 6 hours, with a 15-minute timeline', async () => {
		at('?range=6h');
		succeedAll();
		render(Page);
		await flush();
		expect(screen.getByRole('button', { name: '6h' })).toHaveAttribute('aria-pressed', 'true');
		expect(screen.getByText(/What Suricata flagged on your network · last 6 hours/)).toBeInTheDocument();
		const call = listCalls()[0];
		expect((Date.parse(call.to!) - Date.parse(call.from!)) / 3_600_000).toBe(6);
		expect(getAlertTimeline).toHaveBeenCalledWith(expect.objectContaining({ interval: '15m' }));
	});
});

// ---------------------------------------------------------------------------
// NET-160 slice 2b-2: a raw Suricata category on the list, its links, and Top signatures' window
// ---------------------------------------------------------------------------

describe('Alerts — Suricata category (NET-160 slice 2b-2)', () => {
	const FROM = '2026-11-01T08:00:00.000Z';
	const TO = '2026-11-01T20:00:00.000Z';
	const CAT = 'A/B & C';
	const at = (query: string) => (nav.url = new URL(`http://localhost/alerts${query}`));
	const listCalls = () => vi.mocked(getAlerts).mock.calls.map(([opts]) => opts!);
	const catQuery = `?suricata_category=${encodeURIComponent(CAT)}&severity=high&src=192.168.1.42&from=${FROM}&to=${TO}&range=7d`;
	const params = (href: string | null) => Object.fromEntries(new URL(href!, 'http://localhost').searchParams);

	it('passes suricata_category to the list with the other filters, shown as a chip', async () => {
		at(catQuery);
		succeedAll();
		render(Page);
		await flush();
		expect(listCalls()).toEqual([expect.objectContaining({ page: 1, suricata_category: CAT, severity: 1, src: '192.168.1.42', from: FROM, to: TO })]);
		expect(screen.getByRole('button', { name: 'Clear Suricata category filter' }).closest('.chip')).toHaveTextContent(`Suricata category: ${CAT}`);
	});

	it('clearing the Suricata category chip changes only its own parameter', async () => {
		at(catQuery);
		succeedAll();
		render(Page);
		await flush();
		vi.mocked(getAlertTimeline).mockClear();
		await fireEvent.click(screen.getByRole('button', { name: 'Clear Suricata category filter' }));
		await flush();
		const q = nav.url.searchParams;
		expect([q.get('suricata_category'), q.get('severity'), q.get('src'), q.get('from'), q.get('to'), q.get('range')]).toEqual([null, 'high', '192.168.1.42', FROM, TO, '7d']);
		expect(listCalls().at(-1)).toMatchObject({ suricata_category: undefined, severity: 1, src: '192.168.1.42', from: FROM, to: TO });
		// a filter, not a window: one list request, no reload
		expect(getAlertTimeline).not.toHaveBeenCalled();
		expect(screen.queryByRole('button', { name: 'Clear Suricata category filter' })).not.toBeInTheDocument();
	});

	// NET-185: a category's "No rule name" bar opens the alerts with no rule name
	it('passes no_rule_name to the list, shown as a chip that clears only it', async () => {
		at(`?no_rule_name=true&severity=high&from=${FROM}&to=${TO}&range=7d`);
		succeedAll();
		render(Page);
		await flush();
		expect(listCalls()).toEqual([expect.objectContaining({ page: 1, no_rule_name: true, severity: 1, from: FROM, to: TO })]);
		expect(screen.getByRole('button', { name: 'Clear the no rule name filter' }).closest('.chip')).toHaveTextContent('No rule name');
		await fireEvent.click(screen.getByRole('button', { name: 'Clear the no rule name filter' }));
		await flush();
		const q = nav.url.searchParams;
		expect([q.get('no_rule_name'), q.get('severity'), q.get('from'), q.get('to'), q.get('range')]).toEqual([null, 'high', FROM, TO, '7d']);
		expect(listCalls().at(-1)).toMatchObject({ no_rule_name: undefined, severity: 1, from: FROM, to: TO });
	});

	it("a Top signatures row opens exactly its count: that signature over the card's window, every other filter cleared", async () => {
		at(`?suricata_category=${encodeURIComponent(CAT)}&src=192.168.1.42`);
		succeedAll();
		render(Page);
		await flush();
		const counted = vi.mocked(getAlertTopSignatures).mock.calls[0][0]!;
		await fireEvent.click(screen.getByRole('button', { name: 'Filter alerts by ET SCAN Port sweep' }));
		await flush();
		expect(Object.fromEntries(nav.url.searchParams)).toEqual({ signature: 'ET SCAN Port sweep', from: counted.from, to: counted.to, range: '24h' });
		expect(listCalls().at(-1)).toMatchObject({ signature: 'ET SCAN Port sweep', suricata_category: undefined, src: undefined, from: counted.from, to: counted.to, page: 1 });
		// selecting it again still clears only the signature
		await fireEvent.click(screen.getByRole('button', { name: 'Clear the filter for ET SCAN Port sweep' }));
		await flush();
		expect(nav.url.searchParams.has('signature')).toBe(false);
		expect([nav.url.searchParams.get('from'), nav.url.searchParams.get('to')]).toEqual([counted.from, counted.to]);
	});

	it("links a row's category to its page over the list's window only when rule.category holds it", async () => {
		succeedAll([
			alert('a1', { category: 'Misc activity', rule_category: ['Misc activity', 'Discovery'] }),
			alert('a2', { category: 'From another field', rule_category: ['Something else'] }),
			alert('a3', { category: 'No stored values' }),
		]);
		const { container } = render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'All alerts' }));
		const first = listCalls()[0];
		const table = screen.getByRole('table', { name: /Alerts, newest first/ });
		const link = within(table).getByRole('link', { name: 'Misc activity' });
		expect(new URL(link.getAttribute('href')!, 'http://localhost').pathname).toBe('/alerts/suricata/Misc%20activity');
		expect(params(link.getAttribute('href'))).toEqual({ from: first.from, to: first.to, range: '24h' });
		for (const plain of ['From another field', 'No stored values']) {
			expect(within(table).getByText(plain).closest('a')).toBeNull();
		}
		expectNoNestedInteractive(container);
	});

	it('links a By category heading only when every alert under it carries the title, with its count plain', async () => {
		succeedAll([
			alert('t1', { category: 'Trojan', rule_category: ['Trojan'], signature: 'One' }),
			alert('t2', { category: 'Trojan', rule_category: ['Trojan', 'Command_And_Control'], signature: 'Two' }),
			alert('m1', { category: 'Misc activity', rule_category: ['Misc activity'], signature: 'Three' }),
			alert('m2', { category: 'Misc activity', signature: 'Four' }),
		]);
		const { container } = render(Page);
		await flush();
		const first = listCalls()[0];
		const trojan = screen.getByRole('link', { name: 'Trojan' });
		expect(trojan).toHaveAttribute('title', "Every alert in this Suricata category over the list's window");
		expect(new URL(trojan.getAttribute('href')!, 'http://localhost').pathname).toBe('/alerts/suricata/Trojan');
		expect(params(trojan.getAttribute('href'))).toEqual({ from: first.from, to: first.to, range: '24h' });
		expect(trojan.closest('.alert-group')!.querySelector('.group-head .num')!.closest('a')).toBeNull();
		// one alert under Misc activity has no stored rule.category, so the page wouldn't list it
		const misc = [...container.querySelectorAll('.group-title')].find((h) => h.textContent === 'Misc activity')!;
		expect(misc.querySelector('a')).toBeNull();
		expectNoNestedInteractive(container);
	});

	it("the drawer's Category links with no window, and only when rule.category holds it", async () => {
		succeedAll([
			alert('a1', { signature: 'Linked', category: 'Misc activity', rule_category: ['Misc activity'] }),
			alert('a2', { signature: 'Plain', category: 'Other field', rule_category: [] }),
		]);
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: /Misc activity/ }));
		let drawer = screen.getByRole('complementary', { name: 'Alert details' });
		expect(within(drawer).getByRole('link', { name: 'Misc activity' })).toHaveAttribute('href', '/alerts/suricata/Misc%20activity');
		await fireEvent.click(screen.getByRole('button', { name: /Other field/ }));
		drawer = screen.getByRole('complementary', { name: 'Alert details' });
		// the title reads the category too; the fact is the one that could link
		expect(within(drawer.querySelector('.facts') as HTMLElement).getByText('Other field').closest('a')).toBeNull();
	});
});

// ---------------------------------------------------------------------------
// NET-160: exact top lists. A row with no rule name can't be listed, and a partial list says so
// ---------------------------------------------------------------------------

describe('Alerts — exact top lists (NET-160)', () => {
	const sigTable = () => screen.getByRole('table', { name: 'Top signatures' });
	const sub = (title: string) => screen.getByRole('heading', { name: title }).closest('.card')!.querySelector('.card-sub')!;

	it('a Top signatures row with no rule name or an empty one is plain; a literal "Unknown" filters', async () => {
		succeedAll();
		vi.mocked(getAlertTopSignatures).mockResolvedValue({
			...range,
			complete: true,
			examined: 4,
			signatures: [
				{ signature: 'ET SCAN Port sweep', count: 12, severity: 2 },
				{ signature: null, count: 7, severity: 3 },
				{ signature: '', count: 2, severity: 3 },
				{ signature: 'Unknown', count: 1, severity: 3 },
			],
		});
		const { container } = render(Page);
		await flush();
		const plain = within(sigTable()).getAllByText('No rule name');
		expect(plain).toHaveLength(2);
		for (const cell of plain) {
			expect(cell.closest('button')).toBeNull();
			expect(cell.closest('tr')).not.toHaveClass('is-activatable');
		}
		const before = nav.url.href;
		await fireEvent.click(plain[0].closest('tr')!);
		await fireEvent.click(plain[1].closest('tr')!);
		await flush();
		expect(nav.url.href).toBe(before);
		await fireEvent.click(screen.getByRole('button', { name: 'Filter alerts by Unknown' }));
		await flush();
		expect(nav.url.searchParams.get('signature')).toBe('Unknown');
		expect(listCallsOf().at(-1)).toMatchObject({ signature: 'Unknown', page: 1 });
		expectNoNestedInteractive(container);
	});

	it('says a partial list holds the highest counts among those read, not "N rules"', async () => {
		succeedAll();
		vi.mocked(getAlertTopSignatures).mockResolvedValue({ ...range, complete: false, examined: 5000, signatures: [{ signature: 'ET SCAN Port sweep', count: 12, severity: 2 }] });
		vi.mocked(getAlertTopIps).mockImplementation(async (opts = {}) => ({
			...range,
			direction: opts.direction ?? 'dest',
			ips: [{ ip: '192.168.1.42', count: 9 }],
			complete: opts.direction !== 'src',
			examined: opts.direction === 'src' ? 2500 : 1,
		}));
		render(Page);
		await flush();
		expect(sub('Top signatures')).toHaveTextContent(/^Highest counts among the 5,000 rules read; the full set was too large to read · alerts per rule/);
		expect(sub('Top signatures')).not.toHaveTextContent('1 rules');
		expect(sub('Top source IPs')).toHaveTextContent('Alerts per source · Highest counts among the 2,500 addresses read; the full set was too large to read · last 24 hours');
		// the destination list is complete, so it says nothing extra
		expect(sub('Top affected devices')).toHaveTextContent(/^Alerts per destination · last 24 hours$/);
	});
});

const listCallsOf = () => vi.mocked(getAlerts).mock.calls.map(([opts]) => opts!);

// ---------------------------------------------------------------------------
// Activity: alerts ET rates informational or unknown, stored but never counted (NET-191)
// ---------------------------------------------------------------------------

describe('Alerts — activity (NET-191)', () => {
	const FROM = '2026-11-01T08:00:00.000Z';
	const TO = '2026-11-01T20:00:00.000Z';
	// OLD CODE: const NOTE = 'ET rates these informational. They are not counted as alerts.'; (NET-228: Informational or Unknown)
	const NOTE = 'ET rates these rules Informational or Unknown. They are not counted as alerts.';
	const at = (query: string) => (nav.url = new URL(`http://localhost/alerts${query}`));
	const listCalls = () => vi.mocked(getAlerts).mock.calls.map(([opts]) => opts!);
	const listSub = () => screen.getByRole('heading', { name: /^(Alerts by category|All alerts)$/ }).closest('.card')!.querySelector('.card-sub')!;
	// OLD CODE: const notCounted = () => screen.queryByRole('button', { name: /informational events? not counted/ }); (NET-228)
	const notCounted = () => screen.queryByRole('button', { name: /not counted: ET rates/ });
	const params = (href: string | null) => Object.fromEntries(new URL(href!, 'http://localhost').searchParams);
	/** The severity card's counted figures, and `activity` (a number, or a failure) for the activity count. */
	function counts(activity: number | Error, high = 0) {
		vi.mocked(getAlertCount).mockImplementation(async (opts = {}) => {
			if (!opts.activity) return { ...range, counts: { total: 40, high: 3, medium: 7, low: 20 } };
			if (activity instanceof Error) throw activity;
			return { ...range, counts: { total: activity, high, medium: 0, low: 0 } };
		});
	}

	it('lists the activity alerts when the URL asks, with a chip and the note; the counts stay counted', async () => {
		at(`?activity=true&from=${FROM}&to=${TO}`);
		succeedAll();
		render(Page);
		await flush();
		expect(listCalls()).toEqual([expect.objectContaining({ page: 1, activity: true, from: FROM, to: TO })]);
		expect(screen.getByRole('button', { name: 'Clear activity filter' }).closest('.chip')).toHaveTextContent('Activity: rated Informational or Unknown by ET');
		expect(listSub()).toHaveTextContent(NOTE);
		expect(countedCalls()).toEqual([[{ from: FROM, to: TO }]]);
	});

	it('an empty activity list says no activity, not that Suricata has never alerted', async () => {
		at(`?activity=true&from=${FROM}&to=${TO}`);
		succeedAll([]);
		render(Page);
		await flush();
		expect(screen.getByText('No activity')).toBeInTheDocument();
		expect(screen.queryByText('No alerts')).not.toBeInTheDocument();
	});

	it('without the parameter the list asks for counted alerts, with no chip or note', async () => {
		succeedAll();
		render(Page);
		await flush();
		expect(listCalls()[0].activity).toBeUndefined();
		expect(screen.queryByRole('button', { name: 'Clear activity filter' })).not.toBeInTheDocument();
		expect(listSub()).not.toHaveTextContent(NOTE);
	});

	it('keeps activity across pages and a new range; clearing its chip drops only activity', async () => {
		at('?activity=true&severity=low');
		succeedAll();
		vi.mocked(getAlerts).mockImplementation(async (opts = {}) => list([alert(`p${opts.page}`)], opts.page ?? 1, 250));
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'All alerts' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
		await flush();
		expect(listCalls().at(-1)).toMatchObject({ page: 2, activity: true, severity: 3 });

		await fireEvent.click(screen.getByRole('button', { name: '7d' }));
		await flush();
		expect([nav.url.searchParams.get('activity'), nav.url.searchParams.get('range')]).toEqual(['true', '7d']);
		expect(listCalls().at(-1)).toMatchObject({ page: 1, activity: true });

		await fireEvent.click(screen.getByRole('button', { name: 'Clear activity filter' }));
		await flush();
		expect([nav.url.searchParams.get('activity'), nav.url.searchParams.get('severity'), nav.url.searchParams.get('range')]).toEqual([null, 'low', '7d']);
		expect(listCalls().at(-1)).toMatchObject({ page: 1, activity: undefined, severity: 3 });
	});

	it('says how many informational events were not counted, and Show opens exactly them', async () => {
		at('?ip=192.168.1.42&severity=high');
		succeedAll();
		counts(1234);
		render(Page);
		await flush();
		const asked = vi.mocked(getAlertCount).mock.calls.find(([opts]) => opts?.activity)![0]!;
		expect(asked).toEqual({ from: expect.any(String), to: expect.any(String), activity: true });
		// the severity card still shows the counted figures
		expect(screen.getByRole('img', { name: /^40 alerts/ })).toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: '1,234 rule matches not counted: ET rates their rules Informational or Unknown · Show' }));
		await flush();
		expect(Object.fromEntries(nav.url.searchParams)).toEqual({ activity: 'true', from: asked.from, to: asked.to, range: '24h' });
		expect(listCalls().at(-1)).toMatchObject({ page: 1, activity: true, from: asked.from, to: asked.to, ip: undefined, severity: undefined });
	});

	it('says "event" for one', async () => {
		succeedAll();
		counts(1);
		render(Page);
		await flush();
		expect(notCounted()).toHaveAccessibleName('1 rule match not counted: ET rates its rule Informational or Unknown · Show');
	});

	// NET-228 (audit B-i): severity-1 rules left out of the count without the page saying so
	it('says how many of the matches left out have Suricata priority high', async () => {
		succeedAll();
		counts(6643, 6643);
		render(Page);
		await flush();
		expect(notCounted()).toHaveAccessibleName(
			'6,643 rule matches not counted: ET rates their rules Informational or Unknown (6,643 with Suricata priority high) · Show',
		);
	});

	it('hides the line when nothing was left out', async () => {
		succeedAll();
		counts(0);
		render(Page);
		await flush();
		expect(notCounted()).not.toBeInTheDocument();
		expect(screen.getByRole('img', { name: /^40 alerts/ })).toBeInTheDocument();
	});

	it('a rule link from the activity list stays in it, and nothing links to a counted-only category page', async () => {
		at(`?activity=true&from=${FROM}&to=${TO}`);
		succeedAll([alert('i1', { signature: 'ET INFO STUN Binding Request', category: 'Misc activity', rule_category: ['Misc activity'] })]);
		const { container } = render(Page);
		await flush();
		const heading = [...container.querySelectorAll('.group-title')].find((h) => h.textContent === 'Misc activity')!;
		expect(heading.querySelector('a')).toBeNull();

		await fireEvent.click(screen.getByRole('button', { name: /Misc activity/ }));
		const drawer = screen.getByRole('complementary', { name: 'Alert details' });
		expect(params(within(drawer).getByRole('link', { name: 'ET INFO STUN Binding Request' }).getAttribute('href'))).toMatchObject({ activity: 'true' });
		expect(within(drawer).getByText('Misc activity', { selector: 'dd' }).querySelector('a')).toBeNull();
		await fireEvent.click(within(drawer).getByRole('button', { name: /close/i }));

		await fireEvent.click(screen.getByRole('button', { name: 'All alerts' }));
		const table = screen.getByRole('table', { name: /Alerts, newest first/ });
		expect(params(within(table).getByRole('link', { name: 'ET INFO STUN Binding Request' }).getAttribute('href'))).toEqual({
			signature: 'ET INFO STUN Binding Request',
			activity: 'true',
			from: FROM,
			to: TO,
			range: '24h',
		});
		expect(within(table).getByText('Misc activity').closest('a')).toBeNull();
	});

	it("a new window hides the last window's line until its own count arrives", async () => {
		succeedAll();
		counts(1234);
		render(Page);
		await flush();
		expect(notCounted()).toBeInTheDocument();

		const later = new Promise<never>(() => {});
		vi.mocked(getAlertCount).mockImplementation(async (opts = {}) => (opts.activity ? later : { ...range, counts: { total: 40, high: 3, medium: 7, low: 20 } }));
		await fireEvent.click(screen.getByRole('button', { name: '7d' }));
		await flush();
		expect(notCounted()).not.toBeInTheDocument();
	});

	it('a failed refresh of the same window keeps the last count, as the cards above keep theirs', async () => {
		succeedAll();
		counts(1234);
		render(Page);
		await flush();
		counts(new Error('HTTP 502'));
		expect(await refreshPage()).toBe('partial');
		await flush();
		expect(notCounted()).toHaveAccessibleName('1,234 rule matches not counted: ET rates their rules Informational or Unknown · Show');
	});

	it('hides the line when its count fails, and the counted figures still show', async () => {
		succeedAll();
		counts(new Error('HTTP 502'));
		render(Page);
		await flush();
		expect(notCounted()).not.toBeInTheDocument();
		expect(screen.getByRole('img', { name: /^40 alerts/ })).toBeInTheDocument();
	});
});

// ---------------------------------------------------------------------------
// NET-228 (audit B5): a zero says what it can mean, beside the pipeline's current state
// ---------------------------------------------------------------------------

describe('Alerts — zero alerts and the pipeline (NET-228)', () => {
	const severityCard = () => screen.getByRole('heading', { name: 'Alerts by severity' }).closest('.card') as HTMLElement;
	function zeroCounts() {
		succeedAll([]);
		vi.mocked(getAlertCount).mockResolvedValue({ ...range, counts: { total: 0, high: 0, medium: 0, low: 0 } });
	}

	it("a zero with Suricata stopped reads \"can't tell\", as a warning, in the counts and the list", async () => {
		zeroCounts();
		vi.mocked(getSystemHealth).mockResolvedValue(healthWith('sensor_stopped', { sensors: { 'nettap-suricata-live': 'exited' } }));
		render(Page);
		await flush();
		const note = within(severityCard()).getByText("Can't tell if any rule matched · Data pipeline now: Suricata stopped");
		expect(note.closest('p')).toHaveClass('notice', 'is-warn');
		expect(screen.getByRole('heading', { name: "Can't tell if any rule matched" })).toBeInTheDocument();
		expect(screen.queryByText('No alerts')).not.toBeInTheDocument();
	});

	it('a zero with data arriving says no counted rule matched, and how fresh the data is', async () => {
		zeroCounts();
		render(Page);
		await flush();
		expect(within(severityCard()).getByText('No counted rule matches in this period · Data pipeline now: Newest record 40 s ago').closest('p')).not.toHaveClass('is-warn');
		expect(screen.getByRole('heading', { name: 'No counted rule matches in this period' })).toBeInTheDocument();
	});

	// OLD CODE: it('a failed health check is a partial load, and the zero reads "can\'t tell"', async () => { (review L7)
	// OLD CODE: expect(await refreshPage()).toBe('partial'); (review L7: the health marks only the lines that read it)
	it('a failed health check leaves the page loaded, and only the zero reads "can\'t tell"', async () => {
		zeroCounts();
		vi.mocked(getSystemHealth).mockRejectedValue(new Error('HTTP 502'));
		render(Page);
		await flush();
		expect(await refreshPage()).toBe('ok');
		expect(within(severityCard()).getByText("Can't tell if any rule matched · Data pipeline now: Couldn't check")).toBeInTheDocument();
	});

	it('an empty list under a filter says the filters matched nothing (HON-29)', async () => {
		nav.url = new URL('http://localhost/alerts?severity=high');
		succeedAll([]);
		render(Page);
		await flush();
		expect(screen.getByRole('heading', { name: 'No alerts match these filters' })).toBeInTheDocument();
		expect(screen.queryByText(/once Suricata is running/)).not.toBeInTheDocument();
	});

	it("the threat summary with no groups names the pipeline's state", async () => {
		succeedAll();
		vi.mocked(getSmartAlertSummary).mockResolvedValue({
			...range, threat_score: 0, threat_level: 'none', total_groups: 0, total_events: 0, categories: {}, top_threats: [],
		});
		vi.mocked(getSystemHealth).mockResolvedValue(healthWith('stale', { age_seconds: 47 * 60 }));
		render(Page);
		await flush();
		expect(screen.getByText("Can't tell if anything needs review · Data pipeline now: No new records for 47 min")).toBeInTheDocument();
	});
});

// NET-242: with older alerts still listed, a stopped sensor is said at the top of the page
describe('Alerts — the data pipeline now (NET-242)', () => {
	const line = /^Data pipeline now:/;
	const stopped = () => healthWith('sensor_stopped', { sensors: { 'nettap-suricata-live': 'exited' } });

	it('says Suricata stopped while it still lists older alerts', async () => {
		succeedAll();
		vi.mocked(getSystemHealth).mockResolvedValue(stopped());
		render(Page);
		await flush();
		const note = screen.getByText(line);
		expect(note).toHaveTextContent('Data pipeline now: Suricata stopped. What this page shows may be out of date. See System for details.');
		expect(note.closest('p')).toHaveClass('notice', 'is-warn');
		expect(screen.getByRole('link', { name: 'System' })).toHaveAttribute('href', '/system');
	});

	it('says nothing while data is arriving', async () => {
		succeedAll();
		render(Page);
		await flush();
		expect(screen.queryByText(line)).not.toBeInTheDocument();
	});

	it("keeps a warning when the next check fails, by the request or by the daemon", async () => {
		succeedAll();
		vi.mocked(getSystemHealth).mockResolvedValue(stopped());
		render(Page);
		await flush();
		expect(screen.getByText(line)).toHaveTextContent('Suricata stopped');
		vi.mocked(getSystemHealth).mockRejectedValue(new Error('HTTP 502'));
		await refreshPage();
		await flush();
		expect(screen.getByText(line)).toHaveTextContent("Data pipeline now: Couldn't check.");
		vi.mocked(getSystemHealth).mockResolvedValue(healthWith('unknown', { age_seconds: null }));
		await refreshPage();
		await flush();
		expect(screen.getByText(line)).toHaveTextContent("Data pipeline now: Couldn't check.");
	});
});

// NET-228: the daemon says when a category's halves are too thin, or too uneven, to compare
describe('Alerts — category trend', () => {
	it('says "not enough data" instead of a direction', async () => {
		succeedAll([]);
		vi.mocked(getEnhancedCategories).mockResolvedValue({
			...range,
			categories: [
				{
					id: 'malware_c2', label: 'Malware & C2', icon: 'alert', color: 'red', description: '', count: 5,
					severity_breakdown: { critical: 0, high: 5, medium: 0, low: 0, info: 0 },
					trend: { direction: 'not_enough_data', percentage: 0 }, sparkline: [], sub_categories: [],
				},
			],
		});
		render(Page);
		await flush();
		const card = screen.getByRole('heading', { name: 'Alert categories' }).closest('.card') as HTMLElement;
		expect(within(card).getByText(/· not enough data$/)).toBeInTheDocument();
		expect(within(card).queryByText(/not_enough_data/)).not.toBeInTheDocument();
	});
});
