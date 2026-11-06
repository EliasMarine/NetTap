/**
 * /alerts/[category] after the redesign: the refresh contract against the real loader
 * (PLAN.md §5.5), the severity summary from the category's own breakdown, and the drawer
 * column with the category page's device-scoped Suppress.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { readable, get } from 'svelte/store';
import {
	getAlertCategoryDetail,
	getAlertCategoryTimeline,
	getAlerts,
	suppressAlert,
	acknowledgeAlert,
	type Alert,
	type AlertsListResponse,
	type CategoryDetailResponse,
} from '$api/alerts';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import Page from './+page.svelte';
import { expectNoNestedInteractive } from '../../../tests/nested-interactive';

/** NET-160: the daemon's LAN policy, so LAN addresses link to their device page. */
const LAN_POLICY = { version: 'v1', subnets: ['192.168.1.0/24'], source: 'env', ipv6: 'not-lan' };

vi.mock('$app/stores', () => ({
	page: readable({ url: new URL('http://localhost/alerts/scan'), params: { category: 'scan' } }),
}));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$api/alerts', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/alerts')>()),
	getAlertCategoryDetail: vi.fn(),
	getAlertCategoryTimeline: vi.fn(),
	getAlerts: vi.fn(),
	suppressAlert: vi.fn(),
	markFalsePositive: vi.fn(),
	acknowledgeAlert: vi.fn(),
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
	const promise = new Promise<T>((r) => (resolve = r));
	return { promise, resolve };
}

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

const DETAIL: CategoryDetailResponse = {
	category: { id: 'scan', label: 'Scanning', description: 'Probes looking for open services.', color: 'amber', icon: 'radar' },
	stats: { total: 10, unique_sources: 2, unique_targets: 3, affected_devices: 1 },
	// OLD CODE START: severity_breakdown: { critical: 1, high: 2, medium: 3, low: 4, info: 0 }, (I4: the daemon sends Suricata's 1/2/3 now, no critical) OLD CODE END
	severity_breakdown: { high: 2, medium: 3, low: 4, info: 1 },
	sub_categories: [{ id: 'port_scan', label: 'Port Scan', count: 6 }],
	affected_devices: [{ ip: '192.168.1.57', count: 6, hostname: 'office-pc', severity: 'high' }],
	top_signatures: [{ signature: 'ET SCAN Port sweep', count: 6, last_seen: '2026-11-03T10:00:00Z' }],
	mitre_techniques: [{ id: 'T1046', name: 'Network Service Discovery', description: 'Port scanning.', count: 6 }],
	from: '',
	to: '',
};

const row = (id: string, signature = `Sig ${id}`): Alert => ({
	_id: id, _index: 'x', timestamp: '2026-11-03T10:00:00Z',
	alert: { signature, signature_id: 2900010, severity: 2, category: 'Detection of a Network Scan' },
	src_ip: '192.168.1.57', dest_ip: '192.0.2.88', dest_port: 22, proto: 'tcp', acknowledged: false,
});

const list = (alerts: Alert[], page = 1): AlertsListResponse => ({ from: '', to: '', page, size: 25, total: 60, total_pages: 3, alerts });

function succeedAll() {
	vi.mocked(getAlertCategoryDetail).mockResolvedValue(DETAIL);
	vi.mocked(getAlertCategoryTimeline).mockResolvedValue({
		category: 'scan', from: '', to: '', interval: '1h',
		series: [{ timestamp: '2026-11-03T09:00:00Z', total: 4, sub_categories: {} }, { timestamp: '2026-11-03T10:00:00Z', total: 6, sub_categories: {} }],
	});
	vi.mocked(getAlerts).mockResolvedValue(list([row('a1')]));
}

beforeEach(() => {
	vi.clearAllMocks();
	vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => LAN_POLICY })));
});
afterEach(() => vi.mocked(getAlerts).mockReset());

describe('Alert category page — refresh contract', () => {
	it('reports ok, partial and failed from what actually loaded', async () => {
		succeedAll();
		render(Page);
		await flush();
		expect(await refreshPage()).toBe('ok');

		vi.mocked(getAlertCategoryTimeline).mockRejectedValueOnce(new Error('HTTP 502'));
		expect(await refreshPage()).toBe('partial');

		const fail = new Error('HTTP 502');
		vi.mocked(getAlertCategoryDetail).mockRejectedValueOnce(fail);
		vi.mocked(getAlertCategoryTimeline).mockRejectedValueOnce(fail);
		vi.mocked(getAlerts).mockRejectedValueOnce(fail);
		expect(await refreshPage()).toBe('failed');
		expect(get(pageRefresh).status).toBe('failed');
	});

	it('a refresh keeps the page the user is on', async () => {
		succeedAll();
		render(Page);
		await flush();
		vi.mocked(getAlerts).mockResolvedValueOnce(list([row('p2')], 2));
		await fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
		await flush();
		await refreshPage();
		expect(getAlerts).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, category: 'scan' }));
	});

	it('shows only the newest range when an older range answers last', async () => {
		succeedAll();
		render(Page);
		await flush();
		const day = deferred<CategoryDetailResponse>();
		const week = deferred<CategoryDetailResponse>();
		vi.mocked(getAlertCategoryDetail).mockReturnValueOnce(day.promise).mockReturnValueOnce(week.promise);
		refreshPage();
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: '7d' }));
		week.resolve({ ...DETAIL, stats: { ...DETAIL.stats, total: 70 } });
		await flush();
		day.resolve({ ...DETAIL, stats: { ...DETAIL.stats, total: 10 } });
		await flush();
		expect(screen.getByText('70 alerts')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: '7d' })).toHaveAttribute('aria-pressed', 'true');
	});

	it('paging mid-refresh drops only the refresh\'s stale list', async () => {
		succeedAll();
		render(Page);
		await flush();
		const stale = deferred<AlertsListResponse>();
		const paged = deferred<AlertsListResponse>();
		vi.mocked(getAlerts).mockReturnValueOnce(stale.promise).mockReturnValueOnce(paged.promise);
		const refreshed = refreshPage();
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'Page 3' }));
		paged.resolve(list([row('p3', 'Third page')], 3));
		await flush();
		stale.resolve(list([row('s1', 'Stale first page')], 1));
		expect(await refreshed).toBe('ok');
		await flush();
		expect(screen.getByText('Third page')).toBeInTheDocument();
		expect(screen.queryByText('Stale first page')).not.toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Page 3' })).toHaveAttribute('aria-current', 'page');
	});

	it('writes nothing after the page has gone', async () => {
		succeedAll();
		const slow = deferred<CategoryDetailResponse>();
		vi.mocked(getAlertCategoryDetail).mockReturnValueOnce(slow.promise);
		const { unmount } = render(Page);
		await flush();
		unmount();
		slow.resolve(DETAIL);
		await flush();
		expect(get(pageRefresh)).toMatchObject({ available: false, updatedAt: null, status: null });
	});
});

describe('Alert category page — cards', () => {
	it('shows the loading state while the category loads', async () => {
		vi.mocked(getAlertCategoryDetail).mockReturnValue(new Promise(() => {}));
		vi.mocked(getAlertCategoryTimeline).mockReturnValue(new Promise(() => {}));
		vi.mocked(getAlerts).mockReturnValue(new Promise(() => {}));
		render(Page);
		await flush();
		expect(screen.getByRole('status')).toHaveTextContent('Loading Scan');
	});

	// OLD CODE START — I4: the breakdown is Suricata's severity, as on the alert tiles; there is no critical
	// it('takes the severity summary from the category breakdown, critical included', async () => {
	// 	succeedAll();
	// 	render(Page);
	// 	await flush();
	// 	expect(screen.getByRole('img', { name: '10 Scanning alerts in the last 24 hours: 1 critical, 2 high, 3 medium, 4 low, 0 info' })).toBeInTheDocument();
	// OLD CODE END
	it('takes the severity summary from the category breakdown, on the alert tiles\' scale (I4)', async () => {
		succeedAll();
		const { container } = render(Page);
		await flush();
		expect(screen.getByRole('img', { name: '10 Scanning alerts in the last 24 hours: 2 high, 3 medium, 4 low, 1 info' })).toBeInTheDocument();
		expect(screen.getByText('Unique targets').closest('.kpi')).toHaveTextContent('3');
		// OLD CODE START — NET-160: "View device" for every address
		// expect(screen.getByRole('link', { name: 'View device' })).toHaveAttribute('href', '/devices/192.168.1.57');
		// OLD CODE END
		await vi.waitFor(() => expect(screen.getByRole('link', { name: 'Open device' })).toHaveAttribute('href', '/devices/192.168.1.57'));
		for (const link of screen.getAllByRole('link', { name: '192.168.1.57' })) expect(link).toHaveAttribute('href', '/devices/192.168.1.57');
		expectNoNestedInteractive(container);
		expect(screen.getByRole('link', { name: 'T1046' })).toHaveAttribute('href', 'https://attack.mitre.org/techniques/T1046/');
	});

	it('says when the sub-category list and the alert table are empty', async () => {
		succeedAll();
		vi.mocked(getAlertCategoryDetail).mockResolvedValue({ ...DETAIL, sub_categories: [], affected_devices: [], top_signatures: [] });
		vi.mocked(getAlerts).mockResolvedValue({ ...list([]), total: 0, total_pages: 0 });
		render(Page);
		await flush();
		expect(screen.getByText('No sub-categories')).toBeInTheDocument();
		// OLD CODE START: expect(screen.getByText('No affected devices found')).toBeInTheDocument(); (I10) OLD CODE END
		expect(screen.getByText('No addresses found')).toBeInTheDocument();
		expect(screen.getByText('No signatures found')).toBeInTheDocument();
		expect(screen.getByText('No alerts found in this time range.')).toBeInTheDocument();
	});
});

describe('Alert category page — drawer', () => {
	it('opens from a row, suppresses for that device only, and acknowledges', async () => {
		succeedAll();
		render(Page);
		await flush();
		await fireEvent.click(screen.getByText('Sig a1').closest('tr')!);
		const drawer = screen.getByRole('complementary', { name: 'Alert details' });
		expect(within(drawer).getByRole('heading', { name: 'Detection of a Network Scan' })).toBeInTheDocument();

		vi.mocked(suppressAlert).mockResolvedValueOnce();
		await fireEvent.click(within(drawer).getByRole('button', { name: 'Suppress' }));
		await flush();
		expect(suppressAlert).toHaveBeenCalledWith(2900010, '192.168.1.57');

		vi.mocked(acknowledgeAlert).mockResolvedValueOnce({ result: 'ok', alert_id: 'a1', acknowledged_at: '2026-11-03T11:00:00Z', acknowledged_by: 'me' });
		await fireEvent.click(within(drawer).getByRole('button', { name: 'Acknowledge' }));
		await flush();
		expect(acknowledgeAlert).toHaveBeenCalledWith('a1');
	});

	it('a row\'s own Suppress button suppresses without opening the drawer', async () => {
		succeedAll();
		render(Page);
		await flush();
		vi.mocked(suppressAlert).mockResolvedValueOnce();
		await fireEvent.click(screen.getByRole('button', { name: 'Suppress' }));
		await flush();
		expect(suppressAlert).toHaveBeenCalledWith(2900010, '192.168.1.57');
		expect(screen.queryByRole('complementary', { name: 'Alert details' })).not.toBeInTheDocument();
	});
});

describe('Alert category page — addresses and caps (I10)', () => {
	it('counts addresses, not devices, and says when the list is capped', async () => {
		succeedAll();
		const devices = Array.from({ length: 20 }, (_, i) => ({ ip: `198.51.100.${i + 1}`, count: 1, severity: 'low' }));
		const signatures = Array.from({ length: 20 }, (_, i) => ({ signature: `ET SCAN ${i}`, count: 1, last_seen: '2026-11-03T10:00:00Z' }));
		vi.mocked(getAlertCategoryDetail).mockResolvedValue({
			...DETAIL, stats: { ...DETAIL.stats, affected_devices: 412 }, affected_devices: devices, top_signatures: signatures,
		});
		render(Page);
		await flush();
		expect(screen.getByText('Addresses involved', { selector: '.kpi *' }).closest('.kpi')).toHaveTextContent('412');
		expect(screen.queryByText('Devices on your network')).not.toBeInTheDocument();
		expect(screen.getByText(/^Top 20 of 412 addresses · alerts per address/)).toBeInTheDocument();
		expect(screen.getByText(/^The 20 most common · alerts per rule/)).toBeInTheDocument();
	});

	it('gives the plain count when nothing is capped', async () => {
		succeedAll();
		render(Page);
		await flush();
		expect(screen.getByText(/^1 address · alerts per address/)).toBeInTheDocument();
		expect(screen.getByText(/^1 signatures · alerts per rule/)).toBeInTheDocument();
	});
});

