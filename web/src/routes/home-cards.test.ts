import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import HomePage from './+page.svelte';
import { BRIDGE_NO_DEVICES } from '$api/capture';
import { refreshPage } from '$lib/stores/pageRefresh';
import { _configure } from '$lib/stores/alertSnapshot';

type Reply = (url: URL) => unknown;

/** Replies by path (a body, or a function of the URL); any path not listed answers 503. */
function stubDaemon(replies: Record<string, unknown>): ReturnType<typeof vi.fn> {
	const fetchMock = vi.fn(async (input: string) => {
		const url = new URL(input, 'http://x');
		const reply = replies[url.pathname];
		const body = typeof reply === 'function' ? (reply as Reply)(url) : reply;
		return body !== undefined
			? { ok: true, status: 200, json: async () => body }
			: { ok: false, status: 503, json: async () => ({}) };
	});
	vi.stubGlobal('fetch', fetchMock);
	return fetchMock;
}

/** The Devices KPI card. */
const devicesKpi = () => screen.getByText('Devices', { selector: '.kpi-top > span' }).closest('.kpi') as HTMLElement;

beforeEach(() => {
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	_configure({});
});

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
});

describe('Home — Devices KPI "new today"', () => {
	// The daemon counts registry devices first seen at or after `since`; is_new is not used.
	const registry = [
		{ mac: 'AA:00:00:00:00:01', first_seen: new Date(2026, 10, 2, 23, 59).toISOString(), last_seen: new Date(2026, 10, 2, 23, 59).toISOString(), is_new: true },
		{ mac: 'AA:00:00:00:00:02', first_seen: new Date(2026, 10, 3, 0, 1).toISOString(), last_seen: new Date(2026, 10, 3, 0, 1).toISOString(), is_new: true },
	];
	const newCount = (devices: typeof registry) => (url: URL) => {
		const since = new Date(url.searchParams.get('since')!).getTime();
		return { count: devices.filter((d) => new Date(d.first_seen).getTime() >= since).length, since: url.searchParams.get('since') };
	};

	beforeEach(() => {
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(new Date(2026, 10, 3, 10, 0)); // 10:00 local time
	});

	it('counts from local midnight: 00:01 today is new, 23:59 yesterday is not', async () => {
		const fetchMock = stubDaemon({
			'/api/devices/count': { from: '', to: '', count: 7 },
			'/api/devices/registry/new-count': newCount(registry),
		});
		render(HomePage);
		expect(await screen.findByText('1 new today')).toHaveClass('chip', 'is-ok');

		const asked = fetchMock.mock.calls.map(([u]) => new URL(String(u), 'http://x')).find((u) => u.pathname === '/api/devices/registry/new-count');
		expect(asked?.searchParams.get('since')).toBe(new Date(2026, 10, 3).toISOString());
		expect(devicesKpi().querySelector('.kpi-num')).toHaveTextContent('7');
	});

	it("keeps the count when a new device is later updated (the registry's is_new clears; first_seen doesn't)", async () => {
		const devices = registry.map((d) => ({ ...d }));
		const fetchMock = stubDaemon({
			'/api/devices/count': { from: '', to: '', count: 7 },
			'/api/devices/registry/new-count': newCount(devices),
			'/api/devices/registry': () => ({ devices, total: devices.length }),
		});
		render(HomePage);
		await screen.findByText('1 new today');

		devices[1] = { ...devices[1], is_new: false, last_seen: new Date(2026, 10, 3, 9, 59).toISOString() };
		await refreshPage();
		expect(screen.getByText('1 new today')).toBeInTheDocument();
		// Home never reads the capped registry list or its is_new flag
		expect(fetchMock.mock.calls.some(([u]) => new URL(String(u), 'http://x').pathname === '/api/devices/registry')).toBe(false);
	});

	it('shows no chip for zero', async () => {
		stubDaemon({
			'/api/devices/count': { from: '', to: '', count: 7 },
			'/api/devices/registry/new-count': { count: 0, since: '' },
		});
		render(HomePage);
		await vi.waitFor(() => expect(devicesKpi().querySelector('.kpi-num')).toHaveTextContent('7'));
		expect(screen.queryByText(/new today/)).not.toBeInTheDocument();
		expect(devicesKpi().querySelector('.kpi-foot')).toBeNull();
	});

	it('shows no chip and no number when the request fails, and the count is unaffected', async () => {
		stubDaemon({ '/api/devices/count': { from: '', to: '', count: 7 } });
		render(HomePage);
		await vi.waitFor(() => expect(devicesKpi().querySelector('.kpi-num')).toHaveTextContent('7'));
		await vi.waitFor(() => expect(devicesKpi()).toHaveTextContent('Devices seen on the network'));
		expect(screen.queryByText(/new today/)).not.toBeInTheDocument();
		expect(devicesKpi().querySelector('.kpi-foot')).toBeNull();
	});
});

describe('Home — card states', () => {
	it('shows each card loading while its request is pending', async () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(HomePage);
		const loading = screen.getAllByRole('status').map((el) => el.textContent?.trim());
		expect(loading).toEqual(
			expect.arrayContaining([
				'Loading bandwidth over time',
				'Loading network protocols',
				'Loading traffic categories',
				'Loading top devices',
				'Loading the severity summary',
			]),
		);
		expect(screen.getAllByText('Loading…')).toHaveLength(4); // the four KPIs, valued "—"
		// OLD CODE: …toHaveLength(4); // the four pipeline stages (F2 added the Data stage)
		expect(screen.getAllByText('Checking…')).toHaveLength(5); // the five pipeline stages
	});

	it('shows each card empty when its request succeeds with nothing', async () => {
		stubDaemon({
			'/api/traffic/bandwidth': { from: '', to: '', interval: '1h', series: [] },
			'/api/traffic/protocols': { from: '', to: '', protocols: [], services: [] },
			'/api/traffic/categories': { from: '', to: '', categories: [] },
			'/api/devices': { from: '', to: '', limit: 5, devices: [] },
			'/api/alerts/smart': { from: '', to: '', device_ip: null, alerts: [], total: 0 },
			'/api/alerts/count': { from: '', to: '', counts: { total: 0, high: 0, medium: 0, low: 0 } },
		});
		render(HomePage);
		expect(await screen.findByText('No bandwidth data for this window')).toBeInTheDocument();
		expect(screen.getByText('No protocol data for this window')).toBeInTheDocument();
		expect(screen.getByText('No category data yet')).toBeInTheDocument();
		expect(screen.getByText('No devices seen in this window')).toBeInTheDocument();
		// OLD CODE: expect(screen.getByText('No actionable alerts detected.')).toBeInTheDocument(); (NET-228: the health check didn't answer, so it can't tell)
		const summary = screen.getByRole('heading', { name: 'Alert summary' }).closest('.card') as HTMLElement;
		expect(within(summary).getByText("Can't tell if any rule matched · Data pipeline now: Couldn't check")).toBeInTheDocument();
		// a zero total still draws the gauge, with 0 in the centre
		expect(screen.getByRole('img', { name: /^0 alerts in the last 24 hours/ })).toBeInTheDocument();
	});

	// NET-225 (DEV-1): inline bridge mode sits after the router's address translation, so no devices ever appear
	it('says why no devices show in inline bridge mode, instead of promising they will appear', async () => {
		stubDaemon({
			'/api/capture/health': { mode: 'bridge', status: 'normal', capture_interface: 'br0', link_up: true, promisc_enabled: true, issues: [] },
			'/api/devices': { from: '', to: '', limit: 5, devices: [] },
			'/api/devices/count': { from: '', to: '', count: 0 },
		});
		render(HomePage);
		expect(await screen.findByText('No devices to show in inline bridge mode')).toBeInTheDocument();
		expect(screen.getByText(BRIDGE_NO_DEVICES)).toBeInTheDocument();
		expect(screen.queryByText('No devices seen in this window')).not.toBeInTheDocument();
		expect(devicesKpi()).toHaveTextContent("In bridge mode devices share the router's IPv4 address");
		expect(devicesKpi()).not.toHaveTextContent('Devices seen on the network');
	});

	it('shows the severity summary error with a retry that reloads the page', async () => {
		const fetchMock = stubDaemon({});
		render(HomePage);
		const heading = await screen.findByText("Couldn't load the severity summary: the request failed.");
		const before = fetchMock.mock.calls.length;
		await fireEvent.click(heading.closest('[role="alert"]')!.querySelector('button')!);
		expect(fetchMock.mock.calls.length).toBeGreaterThan(before);
	});
});

describe('Home — Capture pipeline packets (NET-167)', () => {
	const stats = (loss_window: unknown) => ({
		capture_interface: 'enp4s0', rx_bytes: 0, tx_bytes: 0, rx_packets: 0, tx_packets: 0, rx_dropped: 0, rx_missed_errors: 0,
		link_speed_mbps: 1000, drop_rate_pct: 0, loss_window,
	});

	it('names the interface the loss window measured and shows the last hour, not the cumulative counters', async () => {
		stubDaemon({
			'/api/capture/stats': stats({
				state: 'ok', interface: 'enp4s0',
				window: { seconds: 3480, arrived: 293_810, lost: 1_234, drop_rate_pct: 0.42 },
				cumulative: { arrived: 1_200_000, lost: 900_000, drop_rate_pct: 75 },
			}),
		});
		render(HomePage);
		expect(await screen.findByText('0.42% lost in the last 58 min · 1,234 packets')).toBeInTheDocument();
		expect(screen.getByText('Each stage at the last refresh · packets: up to the last 60 minutes on enp4s0')).toBeInTheDocument();
		expect(screen.queryByText(/75/)).not.toBeInTheDocument();
	});

	it('says "the capture interface" when the stats request failed', async () => {
		stubDaemon({});
		render(HomePage);
		expect(
			await screen.findByText('Each stage at the last refresh · packets: up to the last 60 minutes on the capture interface'),
		).toBeInTheDocument();
	});
});
