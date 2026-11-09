import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import * as devices from '$api/devices';
import * as registry from '$api/devices-registry';
import { refreshPage } from '$lib/stores/pageRefresh';
import Page from './+page.svelte';

// NET-201: a device opened from All devices (this IP page) has Rename and Change picture too, as
// a device opened from By type (the MAC page) does. A save shows at once; a detail read before
// the save (a refresh, a range change) gets the save laid over it, so the old name never comes back.

const { IP, IP2, page } = vi.hoisted(() => ({
	IP: '192.168.1.10',
	IP2: '192.168.1.11',
	page: { set: (_ip: string) => {} },
}));

vi.mock('$app/stores', async () => {
	const { writable } = await import('svelte/store');
	const at = (ip: string) => ({ url: new URL(`http://localhost/devices/${ip}`), params: { ip } });
	const store = writable(at(IP));
	page.set = (ip: string) => store.set(at(ip));
	return { page: store };
});
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$api/devices', () => ({
	getDeviceDetail: vi.fn(),
	getDeviceCategories: vi.fn(),
	getDevicePorts: vi.fn(),
	getDeviceRiskScore: vi.fn(),
	getDeviceConnections: vi.fn(),
}));
// NET-228: the Smart alerts empty state reads the pipeline's state; fresh unless a test says not
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
	setDeviceName: vi.fn(),
	clearDeviceName: vi.fn(),
}));

const MAC = 'd0:21:f9:5e:35:32';
const MAC2 = 'aa:bb:cc:00:00:02';

const detail = (over: Record<string, unknown> = {}) => ({
	device: {
		ip: IP, mac: MAC, hostname: 'laptop', connection_count: 3, alert_count: 0, total_bytes: 2_000_000,
		first_seen: '2026-10-29T00:00:00Z', last_seen: '2026-10-29T01:00:00Z',
		top_destinations: [], dns_queries: [], bandwidth_series: [], protocols: [],
		...over,
	},
});

/** The registry device a name save answers with (only the owner's fields matter to the page). */
const saved = (custom_name: string | null, mac = MAC.toUpperCase()) =>
	({ mac, custom_name, icon: null, picture: null, display_name: custom_name ?? 'laptop', discovered_name: 'laptop' }) as never;

function deferred<T>() {
	let resolve!: (v: T) => void;
	const promise = new Promise<T>((r) => (resolve = r));
	return { promise, resolve };
}

const h1 = () => screen.getByRole('heading', { level: 1 });
const hostname = () => screen.getByText('Hostname').nextElementSibling;
const traffic = () => screen.getAllByText('Traffic').map((el) => el.closest('.kpi')).find(Boolean)?.querySelector('.kpi-num');

async function rename(name: string) {
	await fireEvent.click(screen.getByRole('button', { name: 'Rename' }));
	await fireEvent.input(screen.getByLabelText('Name'), { target: { value: name } });
	await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
}

describe('IP device page — Rename and Change picture (NET-201)', () => {
	beforeEach(() => {
		vi.mocked(devices.getDeviceCategories).mockResolvedValue({ categories: [] } as never);
		vi.mocked(devices.getDevicePorts).mockResolvedValue({ ports: [] } as never);
		vi.mocked(devices.getDeviceRiskScore).mockResolvedValue({ score: 12, level: 'low', factors: [] } as never);
		vi.mocked(devices.getDeviceConnections).mockResolvedValue({ connections: [], page: 1, total_pages: 0, total: 0 } as never);
	});
	afterEach(() => {
		vi.clearAllMocks();
		page.set(IP);
	});

	it('offers Rename and Change picture for a device with a MAC, and not for one without', async () => {
		vi.mocked(devices.getDeviceDetail).mockResolvedValue(detail() as never);
		const view = render(Page);
		expect(await screen.findByRole('button', { name: 'Rename' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Change picture' })).toBeInTheDocument();
		view.unmount();

		vi.mocked(devices.getDeviceDetail).mockResolvedValue(detail({ mac: null }) as never);
		render(Page);
		await vi.waitFor(() => expect(screen.getByText('MAC').nextElementSibling).toHaveTextContent('—'));
		expect(screen.queryByRole('button', { name: 'Rename' })).not.toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Change picture' })).not.toBeInTheDocument();
	});

	it("names the network's name in the Name hint, before and after the owner names it", async () => {
		vi.mocked(devices.getDeviceDetail).mockResolvedValue(detail() as never);
		const view = render(Page);
		await fireEvent.click(await screen.findByRole('button', { name: 'Rename' }));
		expect(screen.getByText(/in place of the name the network gives it/)).toHaveTextContent('(laptop)');
		view.unmount();

		vi.mocked(devices.getDeviceDetail).mockResolvedValue(detail({ hostname: 'Study', custom_name: 'Study', discovered_name: 'laptop' }) as never);
		render(Page);
		await fireEvent.click(await screen.findByRole('button', { name: 'Rename' }));
		expect(screen.getByText(/in place of the name the network gives it/)).toHaveTextContent('(laptop)');
	});

	it("saves a name by the device's MAC, heads the page with it, and keeps the real hostname", async () => {
		vi.mocked(devices.getDeviceDetail).mockResolvedValue(detail() as never);
		vi.mocked(registry.setDeviceName).mockResolvedValue(saved('Study'));
		render(Page);
		await screen.findByRole('button', { name: 'Rename' });
		await rename('Study');
		await vi.waitFor(() => expect(h1()).toHaveTextContent('Study'));
		expect(registry.setDeviceName).toHaveBeenCalledWith(MAC, 'Study');
		expect(hostname()).toHaveTextContent('laptop');
	});

	it('puts the discovered name back when the name is cleared', async () => {
		vi.mocked(devices.getDeviceDetail).mockResolvedValue(detail({ hostname: 'Study', custom_name: 'Study', discovered_name: 'laptop' }) as never);
		vi.mocked(registry.clearDeviceName).mockResolvedValue(saved(null));
		render(Page);
		await vi.waitFor(() => expect(h1()).toHaveTextContent('Study'));
		await fireEvent.click(screen.getByRole('button', { name: 'Rename' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Use the discovered name' }));
		await vi.waitFor(() => expect(h1()).toHaveTextContent(IP));
		expect(hostname()).toHaveTextContent('laptop');
	});

	it('never shows the owner\'s name as the hostname of a device the network gives no name', async () => {
		vi.mocked(devices.getDeviceDetail).mockResolvedValue(detail({ hostname: null }) as never);
		vi.mocked(registry.setDeviceName).mockResolvedValue(saved('Study'));
		vi.mocked(registry.clearDeviceName).mockResolvedValue(saved(null));
		render(Page);
		await screen.findByRole('button', { name: 'Rename' });
		await rename('Study');
		await vi.waitFor(() => expect(h1()).toHaveTextContent('Study'));
		expect(hostname()).toHaveTextContent('—');
		await fireEvent.click(screen.getByRole('button', { name: 'Rename' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Use the discovered name' }));
		await vi.waitFor(() => expect(h1()).toHaveTextContent(IP));
		expect(hostname()).toHaveTextContent('—');
	});

	it('shows "—" for the hostname of a named device the daemon sent no discovered name for', async () => {
		vi.mocked(devices.getDeviceDetail).mockResolvedValue(detail({ hostname: 'Study', custom_name: 'Study', discovered_name: null }) as never);
		render(Page);
		await vi.waitFor(() => expect(h1()).toHaveTextContent('Study'));
		expect(hostname()).toHaveTextContent('—');
	});

	it('keeps the saved name when a refresh that began before the save lands after it, and takes its new traffic', async () => {
		vi.mocked(devices.getDeviceDetail).mockResolvedValue(detail() as never);
		vi.mocked(registry.setDeviceName).mockResolvedValue(saved('Study'));
		render(Page);
		await screen.findByRole('button', { name: 'Rename' });

		const stale = deferred<unknown>();
		vi.mocked(devices.getDeviceDetail).mockReturnValueOnce(stale.promise as never);
		const refreshing = refreshPage();
		await rename('Study');
		await vi.waitFor(() => expect(h1()).toHaveTextContent('Study'));

		stale.resolve(detail({ total_bytes: 5_000_000 }));
		await refreshing;
		await vi.waitFor(() => expect(traffic()).toHaveTextContent('5.0'));
		expect(h1()).toHaveTextContent('Study');
		expect(hostname()).toHaveTextContent('laptop');
	});

	it('shows another MAC that a refresh finds at the address as it is, without the save', async () => {
		vi.mocked(devices.getDeviceDetail).mockResolvedValue(detail() as never);
		vi.mocked(registry.setDeviceName).mockResolvedValue(saved('Study'));
		render(Page);
		await screen.findByRole('button', { name: 'Rename' });

		const stale = deferred<unknown>();
		vi.mocked(devices.getDeviceDetail).mockReturnValueOnce(stale.promise as never);
		const refreshing = refreshPage();
		await rename('Study');
		await vi.waitFor(() => expect(h1()).toHaveTextContent('Study'));

		stale.resolve(detail({ mac: MAC2, hostname: 'printer' }));
		await refreshing;
		await vi.waitFor(() => expect(screen.getByText('MAC').nextElementSibling).toHaveTextContent(MAC2));
		expect(h1()).toHaveTextContent(IP);
		expect(hostname()).toHaveTextContent('printer');
	});

	it('keeps a save that finishes while a range change reloads the device', async () => {
		vi.mocked(devices.getDeviceDetail).mockResolvedValue(detail() as never);
		const save = deferred<never>();
		vi.mocked(registry.setDeviceName).mockReturnValueOnce(save.promise);
		render(Page);
		await screen.findByRole('button', { name: 'Rename' });
		await rename('Study');

		const stale = deferred<unknown>();
		vi.mocked(devices.getDeviceDetail).mockReturnValueOnce(stale.promise as never);
		await fireEvent.click(within(screen.getByRole('group', { name: 'Time range' })).getByRole('button', { name: '7d' }));
		save.resolve(saved('Study'));
		await Promise.resolve();
		stale.resolve(detail());
		await vi.waitFor(() => expect(h1()).toHaveTextContent('Study'));
		expect(hostname()).toHaveTextContent('laptop');
	});

	it('refuses a second save for the same device until the first one settles', async () => {
		vi.mocked(devices.getDeviceDetail).mockResolvedValue(detail() as never);
		const first = deferred<never>();
		vi.mocked(registry.setDeviceName).mockReturnValueOnce(first.promise).mockResolvedValue(saved('Study'));
		render(Page);
		await screen.findByRole('button', { name: 'Rename' });
		await rename('Office');

		// a range change remounts the panel, so its own one-save lock starts afresh
		await fireEvent.click(within(screen.getByRole('group', { name: 'Time range' })).getByRole('button', { name: '7d' }));
		await screen.findByRole('button', { name: 'Rename' });
		await rename('Study');
		expect(await screen.findByText('A change to this device is still saving. Try again in a moment.')).toBeInTheDocument();
		expect(registry.setDeviceName).toHaveBeenCalledTimes(1);

		first.resolve(saved('Office'));
		await vi.waitFor(() => expect(h1()).toHaveTextContent('Office'));
		await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
		await vi.waitFor(() => expect(h1()).toHaveTextContent('Study'));
		expect(registry.setDeviceName).toHaveBeenCalledTimes(2);
	});

	it("keeps each device's own save when saves for two devices finish out of order", async () => {
		vi.mocked(devices.getDeviceDetail).mockImplementation(async (ip: string) =>
			(ip === IP2 ? detail({ ip: IP2, mac: MAC2, hostname: 'desk' }) : detail()) as never,
		);
		const saveA = deferred<never>();
		vi.mocked(registry.setDeviceName).mockImplementation((mac: string) =>
			mac === MAC ? saveA.promise : Promise.resolve(saved('Study', MAC2.toUpperCase())),
		);
		render(Page);
		await screen.findByRole('button', { name: 'Rename' });
		await rename('Office'); // A's save hangs

		page.set(IP2);
		await vi.waitFor(() => expect(screen.getByText('MAC').nextElementSibling).toHaveTextContent(MAC2));
		const staleB = deferred<unknown>();
		vi.mocked(devices.getDeviceDetail).mockReturnValueOnce(staleB.promise as never);
		const refreshing = refreshPage(); // B's refresh starts before B's save
		await rename('Study');
		await vi.waitFor(() => expect(h1()).toHaveTextContent('Study'));

		saveA.resolve(saved('Office'));
		await Promise.resolve();
		staleB.resolve(detail({ ip: IP2, mac: MAC2, hostname: 'desk' }));
		await refreshing;
		expect(h1()).toHaveTextContent('Study');
		expect(hostname()).toHaveTextContent('desk');
	});
});
