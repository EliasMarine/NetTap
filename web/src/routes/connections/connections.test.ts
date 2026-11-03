import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { readable } from 'svelte/store';
import { getConnections } from '$api/traffic';
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

		const card = screen.getByText('Active Devices').closest('.stat-card');
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
		await fireEvent.click(screen.getByRole('button', { name: 'Next' }));
		await flush();
		expect(screen.getByText('Page 2 of 5')).toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: 'Auto' }));
		vi.mocked(getConnections).mockClear();
		vi.advanceTimersByTime(15_000);
		await flush();

		expect(getConnections).toHaveBeenCalledWith(expect.objectContaining({ page: 2 }));
		expect(getConnections).not.toHaveBeenCalledWith(expect.objectContaining({ page: 1 }));
		expect(screen.getByText('Page 2 of 5')).toBeInTheDocument();
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
		expect(screen.queryByText('No Connections')).not.toBeInTheDocument();
		expect(screen.getByText("Couldn't load connection stats: the request failed.")).toBeInTheDocument();
		expect(screen.getByText('Total Sessions').closest('.stat-card')).not.toHaveTextContent('0');
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

		const card = screen.getByText('Active Devices').closest('.stat-card');
		expect(card).toHaveTextContent('—');
		expect(card).not.toHaveTextContent('0');
		expect(screen.getByText("Couldn't load active devices: the request failed.")).toBeInTheDocument();
	});

	it('still says "No Connections" when the list is really empty', async () => {
		vi.mocked(getConnections).mockResolvedValue({ ...connectionsPage(1, 0), connections: [], total: 0 });
		render(Page);
		await flush();

		expect(screen.getByText('No Connections')).toBeInTheDocument();
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

	it('orders Source by IP and then port', async () => {
		const conn = (id: string, ip: string, port: number) => ({
			_id: id, _index: 'arkime_sessions3-x', '@timestamp': '2026-10-29T10:00:00Z',
			source: { ip, port }, destination: { ip: '8.8.8.8', port: 53 }, network: { transport: 'udp' },
		});
		vi.mocked(getConnections).mockResolvedValue({
			from: '', to: '', page: 1, size: 50, total: 3, total_pages: 1,
			connections: [conn('a', '192.168.1.10', 80), conn('b', '192.168.1.9', 50001), conn('c', '192.168.1.9', 443)],
		});
		vi.mocked(getLiveDashboard).mockResolvedValue(dashboard(1));
		const { container } = render(Page);
		await flush();
		const header = [...container.querySelectorAll('th.sortable')].find((th) => th.textContent?.trim().startsWith('Source'))!;
		const sources = () => [...container.querySelectorAll('tbody tr')].map((r) => r.querySelectorAll('td')[1]?.textContent?.replace(/\s+/g, ''));

		await fireEvent.click(header); // a new text column starts ascending
		expect(sources()).toEqual(['192.168.1.9:443', '192.168.1.9:50001', '192.168.1.10:80']);
		await fireEvent.click(header);
		expect(sources()).toEqual(['192.168.1.10:80', '192.168.1.9:50001', '192.168.1.9:443']);
	});
});
