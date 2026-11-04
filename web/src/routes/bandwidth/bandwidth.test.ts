import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { refreshPage } from '$lib/stores/pageRefresh';
import Page from './+page.svelte';

describe('Bandwidth', () => {
	it('should export a Svelte component', async () => {
		const module = await import('./+page.svelte');
		expect(module.default).toBeDefined();
	});
});

// #96: a failed request read as "0.0 GB" this month and an all-zero heatmap
const MONTHLY = {
	year: 2026,
	month: 11,
	total_bytes: 3 * 1024 ** 3,
	orig_bytes: 1024 ** 3,
	resp_bytes: 2 * 1024 ** 3,
	projection: {
		year: 2026, month: 11, current_bytes: 3 * 1024 ** 3, projected_bytes: 45 * 1024 ** 3,
		days_elapsed: 2, days_in_month: 30, daily_rate_bytes: 1.5 * 1024 ** 3,
		cap_bytes: 0, usage_percent: 0, projected_percent: 0, exceeds_cap: false,
	},
};

/** Replies by path; any path not listed answers 503. */
function stubDaemon(replies: Record<string, unknown>): void {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			const body = replies[url.split('?')[0]];
			return body
				? { ok: true, status: 200, json: async () => body }
				: { ok: false, status: 503, json: async () => ({}) };
		}),
	);
}

describe('Bandwidth — failed requests', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('says each section failed instead of 0.0 GB or an empty heatmap', async () => {
		stubDaemon({});
		render(Page);
		expect(await screen.findByText("Couldn't load this month's usage: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load the time-of-day heatmap: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load daily usage: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load per-device usage: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('0.0 GB')).not.toBeInTheDocument();
		// OLD CODE START: expect(screen.queryByText(/Time-of-Day Heatmap/)).not.toBeInTheDocument(); (the card keeps its head now; the grid is what must not show) OLD CODE END
		expect(screen.queryByRole('img', { name: /^(Busiest hour|No traffic)/ })).not.toBeInTheDocument();
		expect(document.querySelector('.kpi')).toBeNull();
	});

	it('says which time zone the heatmap hours are in', async () => {
		const heatmap = { from: '', to: '', days: [], hours: [], matrix: Array.from({ length: 7 }, () => Array(24).fill(0)) };
		stubDaemon({ '/api/bandwidth/heatmap': { ...heatmap, tz: 'America/Los_Angeles' } });
		render(Page);
		expect(await screen.findByText('Hours in America/Los_Angeles')).toBeInTheDocument();
	});

	it('labels the hours UTC when the daemon does not say it bucketed in another zone', async () => {
		const heatmap = { from: '', to: '', days: [], hours: [], matrix: Array.from({ length: 7 }, () => Array(24).fill(0)) };
		stubDaemon({ '/api/bandwidth/heatmap': heatmap });
		render(Page);
		expect(await screen.findByText('Hours in UTC')).toBeInTheDocument();
	});

	it('shows the sections that loaded when others fail', async () => {
		stubDaemon({ '/api/bandwidth/monthly': MONTHLY });
		render(Page);
		// OLD CODE START: expect(await screen.findByText('3.0 GB')).toBeInTheDocument(); (the KPI sets its unit apart: "3.0" + "GB") OLD CODE END
		await screen.findByText('Projected');
		expect(screen.getByText('This month').closest('.kpi')).toHaveTextContent('3.0GB');
		expect(screen.queryByText(/Couldn't load this month's usage/)).not.toBeInTheDocument();
		expect(screen.getByText("Couldn't load the time-of-day heatmap: the request failed.")).toBeInTheDocument();
	});
});

// ---------------------------------------------------------------------------
// Redesign: the cards with data, their loading and empty states, and the refresh contract
// ---------------------------------------------------------------------------

const GB = 1024 ** 3;
const DAILY = {
	from: '', to: '',
	daily: [
		{ date: '2026-11-01T00:00:00Z', total_bytes: 3 * GB, orig_bytes: GB, resp_bytes: 2 * GB, connections: 10 },
		{ date: '2026-11-02T00:00:00Z', total_bytes: 5 * GB, orig_bytes: GB, resp_bytes: 4 * GB, connections: 12 },
	],
};
const DEVICES = {
	from: '', to: '',
	devices: [
		{ ip: '192.168.1.9', total_bytes: 2 * GB, orig_bytes: GB, resp_bytes: GB, connection_count: 4, percent_of_total: 25 },
		{ ip: '192.168.1.10', total_bytes: 6 * GB, orig_bytes: GB, resp_bytes: 5 * GB, connection_count: 9, percent_of_total: 75 },
	],
};
const HEATMAP = {
	from: '', to: '', days: [], hours: [],
	matrix: Array.from({ length: 7 }, (_, d) => Array.from({ length: 24 }, (_, h) => (d === 3 && h === 21 ? 4 * GB : 0))),
};
const ALL = { '/api/bandwidth/monthly': MONTHLY, '/api/bandwidth/daily': DAILY, '/api/bandwidth/devices': DEVICES, '/api/bandwidth/heatmap': HEATMAP };

describe('Bandwidth — cards', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('shows the month KPIs, the daily chart, top consumers, the table and the heatmap', async () => {
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		stubDaemon(ALL);
		render(Page);
		expect((await screen.findByText('Projected')).closest('.kpi')).toHaveTextContent('45.0GB');
		expect(screen.getByText('Days remaining').closest('.kpi')).toHaveTextContent('28days');
		expect(screen.getByRole('img', { name: /^Busiest day Nov 2, with 5\.0 GB/ })).toBeInTheDocument();
		expect(screen.getByRole('link', { name: /192\.168\.1\.9/ })).toHaveAttribute('href', '/devices/192.168.1.9');
		const rows = screen.getAllByRole('row').slice(1).map((r) => r.querySelector('td')?.textContent?.trim());
		expect(rows).toEqual(['192.168.1.10', '192.168.1.9']);
		expect(screen.getByRole('img', { name: 'Busiest hour Thu 21:00, with 4.0 GB' })).toBeInTheDocument();
	});

	it('marks a projection over the cap', async () => {
		const over = { ...MONTHLY, projection: { ...MONTHLY.projection, cap_bytes: 40 * GB, usage_percent: 8, exceeds_cap: true } };
		stubDaemon({ '/api/bandwidth/monthly': over });
		render(Page);
		expect((await screen.findByText('Over your cap')).closest('.chip')).toHaveClass('is-warn');
		expect(screen.getByRole('meter', { name: '8% of your monthly cap used' })).toBeInTheDocument();
	});

	it('loading: each card says what it is loading', async () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(Page);
		const loading = (await screen.findAllByRole('status')).map((el) => el.textContent?.trim());
		expect(loading).toEqual(
			expect.arrayContaining(["Loading this month's usage", 'Loading daily usage', 'Loading top consumers', 'Loading the per-device breakdown', 'Loading the time-of-day heatmap']),
		);
	});

	it('empty: names what will appear instead of an empty chart or 0 devices', async () => {
		stubDaemon({ ...ALL, '/api/bandwidth/daily': { from: '', to: '', daily: [] }, '/api/bandwidth/devices': { from: '', to: '', devices: [] } });
		render(Page);
		expect(await screen.findByRole('heading', { name: 'No usage this month yet' })).toBeInTheDocument();
		expect(screen.getAllByRole('heading', { name: 'No devices yet' })).toHaveLength(2);
	});
});

describe('Bandwidth — refresh contract', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('ok when every request succeeds, partial when some fail, failed when all do', async () => {
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		stubDaemon(ALL);
		render(Page);
		await screen.findByText('Projected');
		expect(await refreshPage()).toBe('ok');
		stubDaemon({ '/api/bandwidth/monthly': MONTHLY });
		expect(await refreshPage()).toBe('partial');
		// the sections that failed keep their last figures and say so
		expect(screen.getByText("Couldn't refresh daily usage; showing the last figures loaded.")).toBeInTheDocument();
		stubDaemon({});
		expect(await refreshPage()).toBe('failed');
	});
});
