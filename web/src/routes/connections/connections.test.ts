import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { readable } from 'svelte/store';
import { getConnections, getConnectionStats, getConnectionSankey } from '$api/traffic';
import { getLiveDashboard } from '$api/live';
import Page from './+page.svelte';

vi.mock('$app/stores', () => ({
	page: readable({ url: new URL('http://localhost/connections') }),
}));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$api/traffic', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/traffic')>()),
	getConnections: vi.fn(),
	getConnectionStats: vi.fn().mockRejectedValue(new Error('not under test')),
	getConnectionSankey: vi.fn().mockRejectedValue(new Error('not under test')),
	getConnectionTimeline: vi.fn().mockRejectedValue(new Error('not under test')),
}));
vi.mock('$api/live', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/live')>()),
	getLiveConnections: vi.fn().mockResolvedValue({ connections: [{}], count: 1, filters: {} }),
	getLiveDashboard: vi.fn(),
}));
vi.mock('$api/devices-registry', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/devices-registry')>()),
	getRegistryDevices: vi.fn().mockRejectedValue(new Error('not under test')),
}));

describe('Connections v3 page', () => {
	it('should export a Svelte component', async () => {
		const module = await import('./+page.svelte');
		expect(module.default).toBeDefined();
	});
});

// ---------------------------------------------------------------------------
// Rendered page tests
// ---------------------------------------------------------------------------

function connectionsPage(page: number, totalPages = 5) {
	const conn = {
		_id: `c${page}`,
		_index: 'zeek-conn',
		'@timestamp': '2026-10-29T10:00:00Z',
		source: { ip: '10.0.0.5', port: 50000 },
		destination: { ip: '8.8.8.8', port: 53 },
		network: { transport: 'udp' },
	};
	return { from: '', to: '', page, size: 50, total: totalPages * 50, total_pages: totalPages, connections: [conn] };
}

function dashboard(activeDevices: number) {
	return {
		connections: [],
		count: 1,
		stats: { connections_per_second: 3.2, bandwidth_bytes_per_second: 1000, active_devices: activeDevices, top_country: 'US' },
		protocols: {},
		top_talkers: [],
		geo_arcs: [],
	};
}

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

/** A figure in the summary strip, by its label. */
function stat(label: string): Element | undefined {
	return [...document.querySelectorAll('.stat')].find((el) => el.querySelector('.stat-k')?.textContent === label);
}

// jsdom has no ResizeObserver; the timeline/Sankey charts need one to mount
vi.stubGlobal(
	'ResizeObserver',
	class {
		observe() {}
		unobserve() {}
		disconnect() {}
	},
);

describe('Connections — Active Devices card', () => {
	beforeEach(() => {
		vi.mocked(getConnections).mockImplementation(async (opts = {}) => connectionsPage(opts.page ?? 1));
		vi.mocked(getLiveDashboard).mockResolvedValue(dashboard(17));
	});

	afterEach(() => {
		vi.clearAllMocks();
	});

	it('shows active devices from the live dashboard stats, not a 1-item list length', async () => {
		render(Page);
		await flush();

		// OLD CODE START: const card = screen.getByText('Active Devices').closest('.stat-card'); OLD CODE END
		const card = stat('Active devices');
		expect(card).toHaveTextContent('17');
		expect(getLiveDashboard).toHaveBeenCalledWith({ limit: 1 });
	});
});

describe('Connections — auto-refresh', () => {
	beforeEach(() => {
		vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
		vi.mocked(getConnections).mockImplementation(async (opts = {}) => connectionsPage(opts.page ?? 1));
		vi.mocked(getLiveDashboard).mockResolvedValue(dashboard(1));
	});

	afterEach(() => {
		vi.useRealTimers();
		vi.clearAllMocks();
	});

	it('reloads the page the user is on, not page 1', async () => {
		render(Page);
		await flush();
		// OLD CODE START — the pager's markup changed (DataTable): "Next page", and the current page is marked
		// await fireEvent.click(screen.getByRole('button', { name: 'Next' }));
		// await flush();
		// expect(screen.getByText('Page 2 of 5')).toBeInTheDocument();
		// OLD CODE END
		await fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
		await flush();
		expect(screen.getByRole('button', { name: 'Page 2' })).toHaveAttribute('aria-current', 'page');

		await fireEvent.click(screen.getByRole('button', { name: 'Auto' }));
		vi.mocked(getConnections).mockClear();
		vi.advanceTimersByTime(15_000);
		await flush();

		expect(getConnections).toHaveBeenCalledWith(expect.objectContaining({ page: 2 }));
		expect(getConnections).not.toHaveBeenCalledWith(expect.objectContaining({ page: 1 }));
		// OLD CODE START: expect(screen.getByText('Page 2 of 5')).toBeInTheDocument(); OLD CODE END
		expect(screen.getByRole('button', { name: 'Page 2' })).toHaveAttribute('aria-current', 'page');
	});
});

// #96: a failed request read as "No Connections" and 0 sessions / 0 B
describe('Connections — failed requests', () => {
	beforeEach(() => {
		vi.mocked(getLiveDashboard).mockResolvedValue(dashboard(1));
	});

	afterEach(() => {
		vi.clearAllMocks();
	});

	it('says what failed instead of "No Connections" and zero totals', async () => {
		// stats, flow and timeline are mocked to fail at the top of this file
		vi.mocked(getConnections).mockRejectedValue(new Error('Connection list failed: HTTP 503'));
		render(Page);
		await flush();

		expect(screen.getByText("Couldn't load connections: the request failed.")).toBeInTheDocument();
		// OLD CODE START — copy and markup changed: "No connections", and the stat strip's .stat
		// expect(screen.queryByText('No Connections')).not.toBeInTheDocument();
		// expect(screen.getByText("Couldn't load connection stats: the request failed.")).toBeInTheDocument();
		// expect(screen.getByText('Total Sessions').closest('.stat-card')).not.toHaveTextContent('0');
		// OLD CODE END
		expect(screen.queryByText('No connections')).not.toBeInTheDocument();
		expect(screen.getByText("Couldn't load connection stats: the request failed.")).toBeInTheDocument();
		expect(stat('Sessions')).not.toHaveTextContent('0');
		expect(stat('Data')).not.toHaveTextContent('0');
		expect(screen.getByText("Couldn't load the flow diagram: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('No flow data available')).not.toBeInTheDocument();
		expect(screen.getByText("Couldn't load the session timeline: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load top sources: the request failed.")).toBeInTheDocument();
	});

	it('shows a dash, not 0, for active devices when the live request fails', async () => {
		vi.mocked(getConnections).mockImplementation(async (opts = {}) => connectionsPage(opts.page ?? 1));
		vi.mocked(getLiveDashboard).mockRejectedValue(new Error('Live dashboard failed: HTTP 503'));
		render(Page);
		await flush();

		// OLD CODE START: const card = screen.getByText('Active Devices').closest('.stat-card'); OLD CODE END
		const card = stat('Active devices');
		expect(card).toHaveTextContent('—');
		expect(card).not.toHaveTextContent('0');
		expect(screen.getByText("Couldn't load active devices: the request failed.")).toBeInTheDocument();
	});

	it('still says "No connections" when the list is really empty', async () => {
		vi.mocked(getConnections).mockResolvedValue({ ...connectionsPage(1, 0), connections: [], total: 0 });
		render(Page);
		await flush();

		// OLD CODE START: expect(screen.getByText('No Connections')).toBeInTheDocument(); (sentence case now) OLD CODE END
		expect(screen.getByText('No connections')).toBeInTheDocument();
		expect(screen.queryByText(/Couldn't load connections/)).not.toBeInTheDocument();
	});
});

// ---------------------------------------------------------------------------
// Sorting (G11 sort sweep): Source sorts by IP, then port, both as numbers
// ---------------------------------------------------------------------------

describe('Connections — sorting', () => {
	afterEach(() => {
		vi.clearAllMocks();
	});

	// OLD CODE START — #145: the page sorted the 50 rows it had; the daemon sorts every page now
	// it('orders Source by IP and then port', async () => {
	// 	const conn = (id: string, ip: string, port: number) => ({
	// 		_id: id, _index: 'arkime_sessions3-x', '@timestamp': '2026-10-29T10:00:00Z',
	// 		source: { ip, port }, destination: { ip: '8.8.8.8', port: 53 }, network: { transport: 'udp' },
	// 	});
	// 	vi.mocked(getConnections).mockResolvedValue({
	// 		from: '', to: '', page: 1, size: 50, total: 3, total_pages: 1,
	// 		connections: [conn('a', '192.168.1.10', 80), conn('b', '192.168.1.9', 50001), conn('c', '192.168.1.9', 443)],
	// 	});
	// 	vi.mocked(getLiveDashboard).mockResolvedValue(dashboard(1));
	// 	const { container } = render(Page);
	// 	await flush();
	// 	const header = [...container.querySelectorAll('th.sortable')].find((th) => th.textContent?.trim().startsWith('Source'))!;
	// 	const sources = () => [...container.querySelectorAll('tbody tr')].map((r) => r.querySelectorAll('td')[1]?.textContent?.replace(/\s+/g, ''));

	// 	await fireEvent.click(header); // a new text column starts ascending
	// 	expect(sources()).toEqual(['192.168.1.9:443', '192.168.1.9:50001', '192.168.1.10:80']);
	// 	await fireEvent.click(header);
	// 	expect(sources()).toEqual(['192.168.1.10:80', '192.168.1.9:50001', '192.168.1.9:443']);
	// });
	// OLD CODE END

	const row = (id: string, extra: Record<string, unknown> = {}) => ({
		_id: id, _index: 'arkime_sessions3-x', '@timestamp': '2026-10-29T10:00:00Z',
		source: { ip: '192.168.1.9', port: 50001 }, destination: { ip: '8.8.8.8', port: 53 }, network: { transport: 'udp' },
		...extra,
	});

	async function renderWith(rows: ReturnType<typeof row>[]) {
		vi.mocked(getConnections).mockResolvedValue({ from: '', to: '', page: 1, size: 50, total: 900, total_pages: 18, connections: rows });
		vi.mocked(getLiveDashboard).mockResolvedValue(dashboard(1));
		const view = render(Page);
		await flush();
		return view;
	}

	it('asks the daemon to sort every page, not just the rows on screen', async () => {
		await renderWith([row('a')]);
		expect(getConnections).toHaveBeenLastCalledWith(expect.objectContaining({ sort: 'time', order: 'desc' }));
		// OLD CODE START — the DataTable's header buttons; a new column starts descending, as in every table
		// const header = [...container.querySelectorAll('th.sortable')].find((th) => th.textContent?.trim().startsWith('Source'))!;
		//
		// await fireEvent.click(header); // a new text column starts ascending
		// await flush();
		// expect(getConnections).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, sort: 'source', order: 'asc' }));
		// await fireEvent.click(header);
		// await flush();
		// expect(getConnections).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, sort: 'source', order: 'desc' }));
		// OLD CODE END
		const header = screen.getByRole('columnheader', { name: 'Source' });
		const button = within(header).getByRole('button');

		await fireEvent.click(button);
		await flush();
		expect(getConnections).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, sort: 'source', order: 'desc' }));
		expect(header).toHaveAttribute('aria-sort', 'descending');
		await fireEvent.click(button);
		await flush();
		expect(getConnections).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, sort: 'source', order: 'asc' }));
		expect(header).toHaveAttribute('aria-sort', 'ascending');
	});

	it("filters by state on the daemon and shows its rows as they come", async () => {
		const { container, getByRole } = await renderWith([row('a', { zeek: { conn: { conn_state: 'REJ' } } }), row('b')]);
		await fireEvent.click(getByRole('button', { name: 'Rejected' }));
		await flush();
		expect(getConnections).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, state: 'rejected' }));
		expect(container.querySelectorAll('tbody tr')).toHaveLength(2);
	});

	it("shows the service from network.protocol, not protocol's transport entry", async () => {
		const { container } = await renderWith([row('a', { protocol: ['udp', 'dns'], network: { transport: 'udp', protocol: ['dns'] } })]);
		expect(container.querySelector('tbody tr')?.querySelectorAll('td')[4]?.textContent?.trim()).toBe('dns');
	});
});

describe('Connections — duration', () => {
	afterEach(() => {
		vi.clearAllMocks();
	});

	it("shows Malcolm 26.x records' durations, which read -- before (#144)", async () => {
		const conn = (id: string, extra: Record<string, unknown>) => ({
			_id: id, _index: 'arkime_sessions3-x', '@timestamp': '2026-10-29T10:00:00Z',
			source: { ip: '192.168.1.9', port: 50001 }, destination: { ip: '8.8.8.8', port: 53 }, network: { transport: 'udp' },
			...extra,
		});
		vi.mocked(getConnections).mockResolvedValue({
			from: '', to: '', page: 1, size: 50, total: 2, total_pages: 1,
			connections: [
				conn('a', { event: { start: '1793683365306', end: '1793683365561', duration: 255397081 } }),
				conn('b', { length: 1500, event: { start: '1793683365306', end: '1793683366806' } }),
				// 30 min 59.6 s rounds to 31m 0s, not "30m 60s"
				conn('c', { length: 1859600 }),
			],
		});
		vi.mocked(getLiveDashboard).mockResolvedValue(dashboard(1));
		const { container } = render(Page);
		await flush();
		const durations = [...container.querySelectorAll('tbody tr')].map((r) => r.querySelectorAll('td')[5]?.textContent?.trim());
		expect(durations).toEqual(['255ms', '1.5s', '31m 0s']);
	});
});

// ---------------------------------------------------------------------------
// Accuracy audit 2026-11-06 (I2, I3, I9, I11)
// ---------------------------------------------------------------------------

describe('Connections — labels say what the figures count', () => {
	const stats = {
		from: '', to: '', total_sessions: 120, bytes_in: 2048, bytes_out: 4096, alert_sessions: 7, protocols: [],
		top_sources: [],
		top_destinations: [{ ip: '142.250.1.1', total_bytes: 5000, connections: 3, asn: 'AS15169 Google LLC', country: 'US' }],
	};

	beforeEach(() => {
		vi.mocked(getConnections).mockImplementation(async (opts = {}) => connectionsPage(opts.page ?? 1));
		vi.mocked(getLiveDashboard).mockResolvedValue(dashboard(1));
		vi.mocked(getConnectionStats).mockResolvedValue(stats);
	});

	afterEach(() => {
		vi.clearAllMocks();
		vi.mocked(getConnectionStats).mockRejectedValue(new Error('not under test'));
		vi.mocked(getConnectionSankey).mockRejectedValue(new Error('not under test'));
	});

	it('has no "Has alerts" filter, which was never sent (I2)', async () => {
		render(Page);
		await flush();
		expect(screen.queryByRole('checkbox', { name: 'Has alerts' })).not.toBeInTheDocument();
	});

	it('labels bytes by who sent them, not in/out (I3)', async () => {
		render(Page);
		await flush();
		expect(screen.getByRole('columnheader', { name: /Sent by source/ })).toBeInTheDocument();
		expect(screen.getByRole('columnheader', { name: /Sent by destination/ })).toBeInTheDocument();
		expect(screen.queryByRole('columnheader', { name: /Bytes in/ })).not.toBeInTheDocument();
		expect(screen.getByText(/sent by source, .* sent by destination/)).toBeInTheDocument();
	});

	it('counts alert events, and names each top destination by owner and IP (I9)', async () => {
		render(Page);
		await flush();
		expect(stat('Alert events')).toHaveTextContent('7');
		expect(stat('With alerts')).toBeUndefined();
		expect(screen.getByText('AS15169 Google LLC · 142.250.1.1')).toBeInTheDocument();
		expect(screen.getByText(/per destination IP/)).toBeInTheDocument();
	});

	it('the flow’s "Unknown" destination filters sessions with no owner, not the word Unknown (I11)', async () => {
		vi.mocked(getConnectionSankey).mockResolvedValue({
			from: '', to: '',
			nodes: {
				sources: [{ id: '10.0.0.5', label: '10.0.0.5', value: 100 }],
				protocols: [{ id: 'udp', label: 'UDP', value: 100 }],
				destinations: [{ id: 'Unknown', label: 'Unknown', value: 100 }],
			},
			links: [
				{ source: '10.0.0.5', target: 'udp', value: 100 },
				{ source: 'udp', target: 'Unknown', value: 100 },
			],
		});
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('tab', { name: 'Destinations' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Unknown' }));
		await flush();
		expect(getConnections).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'NOT _exists_:destination.as.full' }));
	});
});
