import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { readable, get } from 'svelte/store';
import * as devices from '$api/devices';
import { getSmartAlerts } from '$api/alerts';
import { getSystemHealth } from '$api/system';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import Page from './+page.svelte';

// PLAN.md §5.5: the loader awaits every request (connections included), reports what
// succeeded, and a slower, older range never overwrites a newer one.

const { IP } = vi.hoisted(() => ({ IP: '192.168.1.10' }));

vi.mock('$app/stores', () => ({
	page: readable({ url: new URL(`http://localhost/devices/${IP}`), params: { ip: IP } }),
}));
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

const device = (hostname: string) => ({
	device: {
		ip: IP, hostname, connection_count: 3, alert_count: 0, total_bytes: 2048,
		first_seen: '2026-10-29T00:00:00Z', last_seen: '2026-10-29T01:00:00Z',
		top_destinations: [], dns_queries: [], bandwidth_series: [], protocols: [],
	},
});
const CONNECTIONS = { connections: [], page: 1, total_pages: 0, total: 0 };
const failed = () => new Error('HTTP 503');

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

function deferred<T>() {
	let resolve!: (v: T) => void;
	const promise = new Promise<T>((r) => (resolve = r));
	return { promise, resolve };
}

describe('Device detail — page refresh contract', () => {
	beforeEach(() => {
		vi.mocked(devices.getDeviceDetail).mockResolvedValue(device('laptop') as never);
		vi.mocked(devices.getDeviceCategories).mockResolvedValue({ categories: [] } as never);
		vi.mocked(devices.getDevicePorts).mockResolvedValue({ ports: [] } as never);
		vi.mocked(devices.getDeviceRiskScore).mockResolvedValue({ score: 12, level: 'low', factors: [] } as never);
		vi.mocked(devices.getDeviceConnections).mockResolvedValue(CONNECTIONS as never);
		vi.mocked(getSmartAlerts).mockResolvedValue({ alerts: [], total: 0 } as never);
	});

	afterEach(() => {
		vi.clearAllMocks();
	});

	it('reports ok when every request succeeds, and unregisters on unmount', async () => {
		const { unmount } = render(Page);
		await flush();
		expect(get(pageRefresh).available).toBe(true);
		expect(await refreshPage()).toBe('ok');
		unmount();
		expect(get(pageRefresh).available).toBe(false);
	});

	it('reports partial when only the connections fail', async () => {
		vi.mocked(devices.getDeviceConnections).mockRejectedValue(failed());
		render(Page);
		await flush();
		expect(await refreshPage()).toBe('partial');
		expect(screen.getByText("Couldn't load connections: the request failed.")).toBeInTheDocument();
	});

	it('reports failed when every request fails', async () => {
		vi.mocked(devices.getDeviceDetail).mockRejectedValue(failed());
		vi.mocked(devices.getDeviceCategories).mockRejectedValue(failed());
		vi.mocked(devices.getDevicePorts).mockRejectedValue(failed());
		vi.mocked(devices.getDeviceRiskScore).mockRejectedValue(failed());
		vi.mocked(devices.getDeviceConnections).mockRejectedValue(failed());
		vi.mocked(getSmartAlerts).mockRejectedValue(failed());
		// OLD CODE: // NET-228: the health is a page input too (once per load: the first render and the refresh)
		// the health fails too; since review L7 it marks only the empty list's line, not the page
		vi.mocked(getSystemHealth).mockRejectedValueOnce(failed()).mockRejectedValueOnce(failed());
		render(Page);
		await flush();
		expect(await refreshPage()).toBe('failed');
		// the heading stays in the error state
		expect(screen.getByRole('heading', { level: 1, name: IP })).toBeInTheDocument();
	});

	it('does not return before the connections have loaded', async () => {
		render(Page);
		await flush();
		const pending = deferred<typeof CONNECTIONS>();
		vi.mocked(devices.getDeviceConnections).mockReturnValueOnce(pending.promise as never);
		let settled = false;
		const run = refreshPage().then((r) => ((settled = true), r));
		await flush();
		expect(settled).toBe(false);
		pending.resolve(CONNECTIONS);
		expect(await run).toBe('ok');
	});

	it('drops the older range when the newer one answers first', async () => {
		const first = deferred<ReturnType<typeof device>>();
		vi.mocked(devices.getDeviceDetail).mockReturnValueOnce(first.promise as never);
		render(Page);
		await flush();

		vi.mocked(devices.getDeviceDetail).mockResolvedValueOnce(device('seven-day-name') as never);
		await fireEvent.click(screen.getByRole('button', { name: '7d' }));
		await flush();
		expect(screen.getAllByText('seven-day-name').length).toBeGreaterThan(0);

		// the 24 h reply lands last and must write nothing
		first.resolve(device('one-day-name'));
		await flush();
		expect(screen.queryByText('one-day-name')).not.toBeInTheDocument();
		expect(screen.getByRole('button', { name: '7d' })).toHaveAttribute('aria-pressed', 'true');
	});

	it('shows the loading state in the identity card while the device loads', async () => {
		vi.mocked(devices.getDeviceDetail).mockReturnValue(new Promise(() => {}) as never);
		render(Page);
		await flush();
		expect(screen.getByRole('status')).toHaveTextContent('Loading device');
		expect(screen.getByRole('heading', { level: 1, name: IP })).toBeInTheDocument();
	});

	it('says the device was not found when the daemon has no record', async () => {
		vi.mocked(devices.getDeviceDetail).mockResolvedValue({ device: { ip: '' } } as never);
		render(Page);
		await flush();
		expect(screen.getByText(`Device not found: ${IP}`)).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'Return to devices' })).toHaveAttribute('href', '/devices');
	});
});

describe('Device detail — recent connections', () => {
	const CONN = {
		_id: 'c1', _index: 'arkime', '@timestamp': '2026-10-29T01:00:00Z',
		destination: { ip: '10.0.0.5', port: 443, bytes: 1000 }, source: { bytes: 200 },
		network: { transport: 'tcp', protocol: 'tls' },
	};

	beforeEach(() => {
		vi.mocked(devices.getDeviceDetail).mockResolvedValue(device('laptop') as never);
		vi.mocked(devices.getDeviceCategories).mockResolvedValue({ categories: [] } as never);
		vi.mocked(devices.getDevicePorts).mockResolvedValue({ ports: [] } as never);
		vi.mocked(devices.getDeviceRiskScore).mockResolvedValue({ score: 12, level: 'low', factors: [] } as never);
		vi.mocked(devices.getDeviceConnections).mockResolvedValue({ connections: [CONN], page: 1, total_pages: 3, total: 60 } as never);
		vi.mocked(getSmartAlerts).mockResolvedValue({ alerts: [], total: 0 } as never);
	});

	afterEach(() => {
		vi.clearAllMocks();
	});

	it('sorts on the daemon and pages through the same window', async () => {
		render(Page);
		await flush();
		const table = screen.getByRole('table', { name: 'Recent connections' });
		expect(within(table).getAllByRole('columnheader')).toHaveLength(8); // NET-158: + Direction

		vi.mocked(devices.getDeviceConnections).mockClear();
		await fireEvent.click(within(table).getByRole('button', { name: 'Destination' }));
		await flush();
		expect(vi.mocked(devices.getDeviceConnections).mock.calls[0][1]).toMatchObject({ page: 1, sort: 'destination', order: 'desc' });

		vi.mocked(devices.getDeviceConnections).mockClear();
		await fireEvent.click(screen.getByRole('button', { name: 'Page 2' }));
		await flush();
		const opts = vi.mocked(devices.getDeviceConnections).mock.calls[0][1] as { page: number; from: string };
		expect(opts.page).toBe(2);
		expect(opts.from).toBe((vi.mocked(devices.getDeviceDetail).mock.calls[0][1] as { from: string }).from);
	});

	it('filters by protocol on the daemon and says when nothing matches', async () => {
		// NET-158: the filter used to hide rows of the page on screen; the daemon filters now
		vi.mocked(devices.getDeviceConnections).mockImplementation(async (_ip, opts) =>
			(opts?.proto === 'udp'
				? { connections: [], page: 1, total_pages: 0, total: 0 }
				: { connections: [CONN], page: 1, total_pages: 3, total: 60 }) as never,
		);
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'UDP' }));
		await flush();
		expect(screen.getByText('No connections in this range')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'TCP' }));
		await flush();
		expect(screen.getByRole('table', { name: 'Recent connections' })).toBeInTheDocument();
	});
});
