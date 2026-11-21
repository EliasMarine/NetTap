import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/svelte';
import * as devices from '$api/devices';
import { searchRegistry, type RegistryDevice } from '$api/devices-registry';
import { refreshPage } from '$lib/stores/pageRefresh';
import { formatTime } from '$lib/utils/time';
import Page from './+page.svelte';

// NET-349: a window with no traffic has no MAC or name for the address, so the page says why and,
// when the registry lists exactly one device at the address now, links to that device's page. It
// never takes that device's name or Watch.

const { IP, IP2, page } = vi.hoisted(() => ({
	IP: '192.168.1.5',
	IP2: '192.168.1.6',
	page: { set: (_ip: string) => {} },
}));

// kit 3: $app/stores → $app/state; the store mock below now backs a $app/state page (NET-315)
vi.mock('$app/state', async () => (await import('../../../tests/app-navigation.svelte')).stateFromStores(async () => {
	const { writable } = await import('svelte/store');
	const at = (ip: string) => ({ url: new URL(`http://localhost/devices/${ip}`), params: { ip } });
	const store = writable(at(IP));
	page.set = (ip: string) => store.set(at(ip));
	return { page: store };
}));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$api/devices', () => ({
	getDeviceDetail: vi.fn(),
	getDeviceCategories: vi.fn(),
	getDevicePorts: vi.fn(),
	getDeviceRiskScore: vi.fn(),
	getDeviceConnections: vi.fn(),
}));
vi.mock('$api/system', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/system')>()),
	getSystemHealth: vi.fn(async () => ({
		uptime: 1, timestamp: '', storage: null, smart: null, opensearch_reachable: true, status: 'healthy', healthy: true,
		pipeline: { state: 'fresh', newest_record_at: '', age_seconds: 40, threshold_seconds: 900, sensors: {}, checked_at: '' },
	})),
}));
vi.mock('$api/alerts', () => ({
	getSmartAlerts: vi.fn(async () => ({ alerts: [], total: 0 })),
	suppressAlert: vi.fn(),
}));
vi.mock('$api/devices-registry', async (original) => ({
	...(await original<typeof import('$api/devices-registry')>()),
	searchRegistry: vi.fn(),
}));

const FROM = '2026-11-20T13:00:00.000Z';
const TO = '2026-11-20T14:00:00.000Z';
const between = (from: string, to: string) =>
	`No connections recorded for this address between ${formatTime(from, 'short')} and ${formatTime(to, 'short')}`;

const detail = (ip: string, over: Record<string, unknown> = {}, win: Record<string, string> = { from: FROM, to: TO }) => ({
	...win,
	device: {
		ip, mac: null, hostname: null, connection_count: 0, alert_count: 0, total_bytes: 0,
		first_seen: '', last_seen: '', top_destinations: [], dns_queries: [], bandwidth_series: [], protocols: [],
		...over,
	},
});

const registered = (mac: string, display_name: string, ips: string[]) =>
	({ mac, ips, display_name, hostnames: [], manufacturer: null, friendly_name: null, category: 'computer', first_seen: '', last_seen: '', is_new: false }) as RegistryDevice;
const BEAST = registered('AA:BB:CC:00:00:05', 'UnraidBeast', [IP]);

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

function deferred<T>() {
	let resolve!: (v: T) => void;
	const promise = new Promise<T>((r) => (resolve = r));
	return { promise, resolve };
}

/** The quiet-window notice, or undefined when the page shows none. */
const notice = () => screen.queryAllByRole('status').find((el) => el.textContent?.includes('No connections recorded'));
const words = (el: HTMLElement | undefined) => el?.textContent?.replace(/\s+/g, ' ').trim();

describe('Device detail — a window with no traffic (NET-349)', () => {
	beforeEach(() => {
		page.set(IP);
		vi.mocked(devices.getDeviceDetail).mockResolvedValue(detail(IP) as never);
		vi.mocked(devices.getDeviceCategories).mockResolvedValue({ categories: [] } as never);
		vi.mocked(devices.getDevicePorts).mockResolvedValue({ ports: [] } as never);
		vi.mocked(devices.getDeviceRiskScore).mockResolvedValue({ score: 0, level: 'low', factors: [] } as never);
		vi.mocked(devices.getDeviceConnections).mockResolvedValue({ connections: [], page: 1, total_pages: 0, total: 0 } as never);
		vi.mocked(searchRegistry).mockResolvedValue([BEAST]);
	});

	afterEach(() => {
		vi.clearAllMocks();
	});

	it("names the one registered device at the address and links to its page, without taking its name", async () => {
		render(Page);
		await flush();
		expect(searchRegistry).toHaveBeenCalledWith(IP);
		const el = notice()!;
		expect(words(el)).toBe(`${between(FROM, TO)}. The device registry lists UnraidBeast at this address now. Open UnraidBeast's page`);
		expect(within(el).getByRole('link', { name: "Open UnraidBeast's page" })).toHaveAttribute('href', '/devices/mac/AA%3ABB%3ACC%3A00%3A00%3A05');
		// the heading stays the address: the registry's name is for now, not for this window
		expect(screen.getByRole('heading', { level: 1, name: IP })).toBeInTheDocument();
	});

	it('counts only an exact address, not one the wildcard search matched by prefix', async () => {
		vi.mocked(searchRegistry).mockResolvedValue([registered('AA:BB:CC:00:00:50', 'Printer', ['192.168.1.50']), BEAST]);
		render(Page);
		await flush();
		expect(within(notice()!).getByRole('link', { name: "Open UnraidBeast's page" })).toBeInTheDocument();
		expect(screen.queryByText(/Printer/)).not.toBeInTheDocument();
	});

	it("says it can't tell when no registered device has the exact address", async () => {
		vi.mocked(searchRegistry).mockResolvedValue([registered('AA:BB:CC:00:00:50', 'Printer', ['192.168.1.50'])]);
		render(Page);
		await flush();
		expect(words(notice())).toBe(`${between(FROM, TO)}, so NetTap can't tell which device used it.`);
		expect(within(notice()!).queryByRole('link')).not.toBeInTheDocument();
	});

	it('gives no link when several registered devices have the address', async () => {
		vi.mocked(searchRegistry).mockResolvedValue([BEAST, registered('AA:BB:CC:00:00:06', 'Phone', [IP])]);
		render(Page);
		await flush();
		expect(words(notice())).toBe(`${between(FROM, TO)}, so NetTap can't tell which device used it.`);
		expect(within(notice()!).queryByRole('link')).not.toBeInTheDocument();
	});

	it('gives no link when the search came back full (50), since it may have left the holder out', async () => {
		const others = Array.from({ length: 49 }, (_, i) => registered(`AA:BB:CC:00:01:${String(i).padStart(2, '0')}`, `Other ${i}`, [`192.168.1.5${i}`]));
		vi.mocked(searchRegistry).mockResolvedValue([BEAST, ...others]);
		render(Page);
		await flush();
		expect(words(notice())).toBe(`${between(FROM, TO)}, so NetTap can't tell which device used it.`);
		expect(within(notice()!).queryByRole('link')).not.toBeInTheDocument();
	});

	it("says it can't tell when the registry lookup fails", async () => {
		vi.mocked(searchRegistry).mockRejectedValue(new Error('Registry search failed: HTTP 502'));
		render(Page);
		await flush();
		expect(words(notice())).toBe(`${between(FROM, TO)}, so NetTap can't tell which device used it.`);
	});

	it('shows no notice for an address with connections but no MAC (answer-only or routed)', async () => {
		vi.mocked(devices.getDeviceDetail).mockResolvedValue(detail(IP, { hostname: 'laptop', connection_count: 3 }) as never);
		render(Page);
		await flush();
		expect(screen.getAllByText('laptop').length).toBeGreaterThan(0);
		expect(notice()).toBeUndefined();
		expect(searchRegistry).not.toHaveBeenCalled();
	});

	it('uses the window the page asked for when the reply has no from and to', async () => {
		vi.mocked(devices.getDeviceDetail).mockResolvedValue(detail(IP, {}, {}) as never);
		render(Page);
		await flush();
		const asked = vi.mocked(devices.getDeviceDetail).mock.calls[0][1] as { from: string; to: string };
		expect(words(notice())).toContain(between(asked.from, asked.to));
	});

	it("keeps the last notice's dates when a rolling refresh fails", async () => {
		render(Page);
		await flush();
		expect(words(notice())).toContain(between(FROM, TO));

		vi.mocked(devices.getDeviceDetail).mockRejectedValue(new Error('HTTP 503'));
		await refreshPage();
		await flush();
		expect(words(notice())).toContain(between(FROM, TO));
		expect(within(notice()!).getByRole('link', { name: "Open UnraidBeast's page" })).toBeInTheDocument();
		// the answer it already had stands; a failed refresh doesn't ask again
		expect(searchRegistry).toHaveBeenCalledTimes(1);
	});

	it("never shows one device's link under another address while that one's lookup runs", async () => {
		render(Page);
		await flush();
		expect(within(notice()!).getByRole('link', { name: "Open UnraidBeast's page" })).toBeVisible();

		const lookup = deferred<RegistryDevice[]>();
		vi.mocked(searchRegistry).mockReturnValueOnce(lookup.promise);
		vi.mocked(devices.getDeviceDetail).mockResolvedValue(detail(IP2) as never);
		page.set(IP2);
		await flush();
		expect(searchRegistry).toHaveBeenLastCalledWith(IP2);
		expect(screen.getByRole('heading', { level: 1, name: IP2 })).toBeInTheDocument();
		expect(words(notice())).toBe(`${between(FROM, TO)}.`);
		expect(screen.queryByRole('link', { name: "Open UnraidBeast's page" })).not.toBeInTheDocument();

		lookup.resolve([registered('AA:BB:CC:00:00:06', 'Phone', [IP2])]);
		await flush();
		expect(within(notice()!).getByRole('link', { name: "Open Phone's page" })).toHaveAttribute('href', '/devices/mac/AA%3ABB%3ACC%3A00%3A00%3A06');
	});

	// r3-2: the answer is accepted by the load that asked, so a late one for the old address writes nothing
	it("drops an earlier address's lookup that answers after the page moved on", async () => {
		const first = deferred<RegistryDevice[]>();
		const second = deferred<RegistryDevice[]>();
		vi.mocked(searchRegistry).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
		render(Page);
		await flush();
		expect(words(notice())).toBe(`${between(FROM, TO)}.`);

		vi.mocked(devices.getDeviceDetail).mockResolvedValue(detail(IP2) as never);
		page.set(IP2);
		await flush();
		first.resolve([BEAST]);
		await flush();
		expect(words(notice())).toBe(`${between(FROM, TO)}.`);
		expect(screen.queryByRole('link', { name: "Open UnraidBeast's page" })).not.toBeInTheDocument();

		second.resolve([]);
		await flush();
		expect(words(notice())).toBe(`${between(FROM, TO)}, so NetTap can't tell which device used it.`);
	});
});
