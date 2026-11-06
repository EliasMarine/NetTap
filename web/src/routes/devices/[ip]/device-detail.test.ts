import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { readable } from 'svelte/store';
import { getSmartAlerts, suppressAlert } from '$api/alerts';
import Page from './+page.svelte';

const { IP } = vi.hoisted(() => ({ IP: '192.168.1.10' }));

vi.mock('$app/stores', () => ({
	page: readable({ url: new URL(`http://localhost/devices/${IP}`), params: { ip: IP } }),
}));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$api/devices', () => ({
	getDeviceDetail: vi.fn(async () => ({
		device: {
			ip: IP,
			hostname: 'laptop',
			connection_count: 3,
			alert_count: 1,
			first_seen: '2026-10-29T00:00:00Z',
			last_seen: '2026-10-29T01:00:00Z',
			top_destinations: [],
			dns_queries: [],
			bandwidth_series: [],
			protocols: [],
		},
	})),
	getDeviceCategories: vi.fn(async () => ({ categories: [] })),
	getDevicePorts: vi.fn(async () => ({ ports: [] })),
	getDeviceRiskScore: vi.fn(async () => ({ score: 0, level: 'low', factors: [] })),
	getDeviceConnections: vi.fn(async () => ({ connections: [], page: 1, total_pages: 0, total: 0 })),
}));
vi.mock('$api/alerts', () => ({
	getSmartAlerts: vi.fn(),
	suppressAlert: vi.fn(),
}));

const ALERT = {
	signature_id: 2010935,
	signature: 'ET SCAN Suspicious inbound to MSSQL port 1433',
	severity: 2,
	severity_label: 'High',
	category_label: 'Scan',
	count: 4,
	trend: 'stable',
	source_ip: IP,
	destination_ip: '10.0.0.5',
	destination_port: 1433,
	assessment: 'Someone probed a database port.',
};

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

describe('Device detail — suppress smart alert', () => {
	beforeEach(() => {
		vi.mocked(getSmartAlerts).mockResolvedValue({ alerts: [ALERT], total: 1 } as never);
	});

	afterEach(() => {
		vi.clearAllMocks();
	});

	async function clickSuppress() {
		render(Page);
		await flush();
		await fireEvent.click(await screen.findByRole('button', { name: 'Suppress' }));
		await flush();
	}

	it('keeps the alert and shows an error when the suppress fails', async () => {
		vi.mocked(suppressAlert).mockRejectedValue(new Error('HTTP 500'));
		await clickSuppress();

		expect(suppressAlert).toHaveBeenCalledWith(ALERT.signature_id, IP);
		expect(screen.getByText(ALERT.signature)).toBeInTheDocument();
		expect(screen.getByText('Suppress failed. Try again.')).toBeInTheDocument();
	});

	it('removes the alert once the daemon confirms the suppress', async () => {
		vi.mocked(suppressAlert).mockResolvedValue({ status: 'ok' } as never);
		await clickSuppress();

		expect(screen.queryByText(ALERT.signature)).not.toBeInTheDocument();
		expect(screen.queryByText('Suppress failed. Try again.')).not.toBeInTheDocument();
	});
});

describe('Device detail — time range (#87)', () => {
	beforeEach(() => {
		vi.mocked(getSmartAlerts).mockResolvedValue({ alerts: [], total: 0 } as never);
	});

	afterEach(() => {
		vi.clearAllMocks();
	});

	const HOUR = 3_600_000;
	function spanHours(opts: { from?: string; to?: string }): number {
		return (Date.parse(opts.to ?? '') - Date.parse(opts.from ?? '')) / HOUR;
	}

	it('asks for the last 24 h by default and 7 days after clicking 7d, on every request', async () => {
		const devices = await import('$api/devices');
		render(Page);
		await flush();
		expect(spanHours(vi.mocked(devices.getDeviceDetail).mock.calls[0][1] as never)).toBe(24);

		vi.clearAllMocks();
		vi.mocked(getSmartAlerts).mockResolvedValue({ alerts: [], total: 0 } as never);
		await fireEvent.click(screen.getByRole('button', { name: '7d' }));
		await flush();

		expect(screen.getByRole('button', { name: '7d' })).toHaveAttribute('aria-pressed', 'true');
		for (const fn of [
			devices.getDeviceDetail,
			devices.getDeviceCategories,
			devices.getDevicePorts,
			devices.getDeviceRiskScore,
			devices.getDeviceConnections,
		]) {
			expect(vi.mocked(fn)).toHaveBeenCalledTimes(1);
			expect(spanHours(vi.mocked(fn).mock.calls[0][1] as never)).toBe(168);
		}
		expect(spanHours(vi.mocked(getSmartAlerts).mock.calls[0][0] as never)).toBe(168);
		// Connection pages reuse the fetch's window instead of sliding with the clock
		const detailOpts = vi.mocked(devices.getDeviceDetail).mock.calls[0][1] as { from: string };
		const connOpts = vi.mocked(devices.getDeviceConnections).mock.calls[0][1] as { from: string };
		expect(connOpts.from).toBe(detailOpts.from);
	});
});

// #96: getSmartAlerts turned an HTTP error into an empty list, so the card said "No actionable
// alerts for this device" when the request had failed.
describe('Device detail — smart alerts request fails', () => {
	afterEach(() => {
		vi.clearAllMocks();
	});

	it('says the alerts could not be loaded and keeps the rest of the page', async () => {
		vi.mocked(getSmartAlerts).mockRejectedValue(new Error('Smart alerts failed: HTTP 502'));
		render(Page);
		await flush();

		expect(screen.getByText("Couldn't load alerts for this device: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('No actionable alerts for this device.')).not.toBeInTheDocument();
		expect(screen.getByText('check failed')).toBeInTheDocument();
		expect(screen.getAllByText('laptop').length).toBeGreaterThan(0);
	});

	it('still says there are none when the request succeeds empty', async () => {
		vi.mocked(getSmartAlerts).mockResolvedValue({ alerts: [], total: 0 } as never);
		render(Page);
		await flush();

		expect(screen.getByText('No actionable alerts for this device.')).toBeInTheDocument();
	});
});

// NET-158: Recent connections go both ways; the protocol filter and the upload share label
describe('Device detail — connection direction, protocol filter and upload share', () => {
	beforeEach(() => {
		vi.mocked(getSmartAlerts).mockResolvedValue({ alerts: [], total: 0 } as never);
	});
	afterEach(() => vi.clearAllMocks());

	const row = (id: string, direction: 'in' | 'out', src: string, dst: string, srcBytes: number, dstBytes: number) => ({
		_id: id, _index: 'i', direction, '@timestamp': '2026-10-29T00:30:00Z', network: { transport: 'tcp' },
		source: { ip: src, port: 50000, bytes: srcBytes }, destination: { ip: dst, port: 443, bytes: dstBytes },
	});

	it("shows DL and UL from the device's side on sessions it answered", async () => {
		const devices = await import('$api/devices');
		vi.mocked(devices.getDeviceConnections).mockResolvedValue({
			from: '', to: '', ip: IP, page: 1, size: 25, total: 2, total_pages: 1,
			connections: [
				row('a', 'out', IP, '8.8.8.8', 1024, 4096),
				row('b', 'in', '192.168.1.7', IP, 2048, 512),
			],
		});
		render(Page);
		await flush();

		expect(screen.getByText(/Sessions to or from this device/)).toBeInTheDocument();
		const table = screen.getByRole('table', { name: 'Recent connections' });
		const [, out, inbound] = Array.from(table.querySelectorAll('tr'));
		// Time, Direction, Destination, Proto, Service, Duration, DL, UL
		const cells = (tr: Element) => Array.from(tr.querySelectorAll('td'), (td) => td.textContent?.trim());
		expect(cells(out)[1]).toBe('Out');
		expect(cells(out).slice(-2)).toEqual(['4.0 KB', '1.0 KB']);
		expect(cells(inbound)[1]).toBe('In');
		// the other end sent 2 KB to the device (its download) and got 512 B back (its upload)
		expect(cells(inbound).slice(-2)).toEqual(['2.0 KB', '512 B']);
	});

	it('asks the daemon for one protocol from page 1, so the total and pager match the rows', async () => {
		const devices = await import('$api/devices');
		render(Page);
		await flush();
		vi.mocked(devices.getDeviceConnections).mockClear();

		await fireEvent.click(screen.getByRole('button', { name: 'UDP' }));
		await flush();

		expect(devices.getDeviceConnections).toHaveBeenCalledTimes(1);
		expect(vi.mocked(devices.getDeviceConnections).mock.calls[0][1]).toMatchObject({ proto: 'udp', page: 1 });
	});

	it('labels a 35% upload share as the risk factor does: elevated, not normal', async () => {
		const devices = await import('$api/devices');
		const { device } = await vi.mocked(devices.getDeviceDetail)(IP, {});
		vi.mocked(devices.getDeviceDetail).mockResolvedValueOnce({
			device: { ...device, total_bytes: 100_000, orig_bytes: 35_000, resp_bytes: 65_000 },
		} as never);
		render(Page);
		await flush();

		const kpi = screen.getAllByText('Upload share').map((el) => el.closest('.kpi')).find(Boolean) as HTMLElement;
		expect(kpi).toHaveTextContent('Elevated');
		expect(kpi).not.toHaveTextContent('Normal');
	});
});
