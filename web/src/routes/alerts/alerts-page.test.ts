/**
 * /alerts after the redesign: the refresh contract against the real loader (PLAN.md §5.5),
 * the shared severity snapshot (§4.1), every card's states, and the drawer column's
 * preservation checklist (§5.3: Related events, Raw JSON, copy buttons, acknowledge /
 * suppress / false positive and their errors, and the destination links).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { readable, get } from 'svelte/store';
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
} from '$api/alerts';
import { _configure as resetAlertSnapshots, alertSnapshots, loadAlertSnapshot } from '$lib/stores/alertSnapshot';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import Page from './+page.svelte';
import { expectNoNestedInteractive } from '../../tests/nested-interactive';

/** NET-160: the daemon's LAN policy, so LAN addresses link to their device page. */
const LAN_POLICY = { version: 'v1', subnets: ['192.168.1.0/24'], source: 'env', ipv6: 'not-lan' };
const lanReply = () => Promise.resolve({ ok: true, status: 200, json: async () => LAN_POLICY });

vi.mock('$app/stores', () => ({
	page: readable({ url: new URL('http://localhost/alerts') }),
}));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
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

/** A severity filter pill (its label carries the count). */
const severityPill = (word: string) =>
	within(screen.getByRole('group', { name: 'Severity' })).getByRole('button', { name: new RegExp(`^${word} `) });

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

const range = { from: '', to: '' };

function alert(id: string, over: Partial<Alert> & { severity?: number; signature?: string; sid?: number; category?: string } = {}): Alert {
	const { severity = 2, signature = `Sig ${id}`, sid = 2000, category = 'Potentially Bad Traffic', ...rest } = over;
	return {
		_id: id,
		_index: 'suricata-x',
		timestamp: '2026-11-03T10:00:00Z',
		alert: { signature, signature_id: sid, severity, category },
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
	vi.mocked(getAlertTopSignatures).mockResolvedValue({ ...range, signatures: [{ signature: 'ET SCAN Port sweep', count: 12, severity: 2 }] });
	vi.mocked(getAlertTopIps).mockResolvedValue({ ...range, direction: 'dest', ips: [{ ip: '192.168.1.42', count: 9 }] });
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
	for (const fn of [getAlerts, getAlertCount, getAlertTimeline, getAlertTopSignatures, getAlertTopIps, getEnhancedCategories, getSmartAlertSummary]) {
		vi.mocked(fn).mockImplementation(fail as never);
	}
}

beforeEach(() => {
	resetAlertSnapshots({});
	vi.clearAllMocks();
	vi.stubGlobal('fetch', vi.fn(lanReply));
});

afterEach(() => {
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

		expect(getAlertCount).toHaveBeenCalledTimes(1);
		expect(get(alertSnapshots)[24].data?.counts.total).toBe(37);
		const gauge = screen.getByRole('img', { name: /^37 alerts in the last 24 hours/ });
		expect(gauge).toHaveAccessibleName('37 alerts in the last 24 hours: 2 high, 5 medium, 20 low, 10 info');
		expect(screen.getByRole('button', { name: 'Show info alerts (10)' })).toBeInTheDocument();
		expect(severityPill('All')).toHaveTextContent('All 37');
	});

	it('a refresh starts a new snapshot window, so every reader moves together', async () => {
		succeedAll();
		render(Page);
		await flush();
		vi.mocked(getAlertCount).mockResolvedValue({ ...range, counts: { total: 50, high: 4, medium: 6, low: 30 } });
		await refreshPage();
		await flush();
		expect(getAlertCount).toHaveBeenCalledTimes(2);
		expect(get(alertSnapshots)[24].data?.counts.total).toBe(50);
		expect(screen.getByRole('img', { name: /^50 alerts/ })).toBeInTheDocument();
	});

	it('a filter change leaves the global count alone', async () => {
		succeedAll();
		render(Page);
		await flush();
		await fireEvent.click(severityPill('Medium'));
		await flush();
		expect(getAlertCount).toHaveBeenCalledTimes(1);
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
		expect(severityPill('All')).toHaveTextContent('All —');
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

	it('shows the loaded data: categories link to their page, the threat score and its level', async () => {
		succeedAll();
		const { container } = render(Page);
		await flush();
		expect(screen.getByRole('link', { name: 'Malware & C2' })).toHaveAttribute('href', '/alerts/malware_c2');
		expect(screen.getByRole('img', { name: 'Threat score 42 of 100, level medium' })).toBeInTheDocument();
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
		// NET-160: the address links fetch the LAN policy themselves; only the drawer's requests are counted
		vi.stubGlobal('fetch', vi.fn((url: string) => (String(url) === '/api/network/lan' ? lanReply() : fetchMock(url))));
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
