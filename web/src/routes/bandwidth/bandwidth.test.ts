import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { refreshPage } from '$lib/stores/pageRefresh';
import { hasFigures, type UsageDay, type UsageDayStatus, type UsageMonth } from '$lib/api/usage';
import Page from './+page.svelte';
import { expectNoNestedInteractive } from '../../tests/nested-interactive';

describe('Bandwidth', () => {
	it('should export a Svelte component', async () => {
		const module = await import('./+page.svelte');
		expect(module.default).toBeDefined();
	});
});

// #96: a failed request read as "0.0 GB" this month and an all-zero heatmap
// decimal GB (NET-166): 3 × 10^9 bytes reads 3.0 GB (3 GiB would read 3.2 GB)
// OLD CODE START — F4 (NET-329): the page reads the usage ledger's month (/api/usage/month), not /api/bandwidth/monthly
// const MONTHLY = {
// 	year: 2026,
// 	month: 11,
// 	total_bytes: 3e9,
// 	orig_bytes: 1e9,
// 	resp_bytes: 2e9,
// 	// NET-226: half a GB of the originators' bytes stayed on the network
// 	upload_bytes: 0.5e9,
// 	download_bytes: 2e9,
// 	local_bytes: 0.5e9,
// 	projection: {
// 		// NET-226 follow-up: the projection is internet bytes, without the local half GB
// 		year: 2026, month: 11, current_bytes: 2.5e9, projected_bytes: 37.5e9,
// 		days_elapsed: 2, days_in_month: 30, daily_rate_bytes: 1.5e9,
// 		cap_bytes: 0, usage_percent: 0, projected_percent: 0, exceeds_cap: false,
// 	},
// };
// OLD CODE END

const GB = 1e9; // decimal, as the page prints (NET-166)
const DAY_MS = 86_400_000;

/** A ledger day in UTC bounds; figures only for a status that carries them (§4.5). `total` is download + upload: local is beside it */
function ledgerDay(date: string, status: UsageDayStatus, down = 0, up = 0, local = 0): UsageDay {
	const start = `${date}T00:00:00.000Z`;
	const end = new Date(Date.parse(start) + DAY_MS).toISOString();
	const has = hasFigures({ status });
	return {
		date, start, end, status,
		cutoff: has ? end : null, counted_at: has ? end : null,
		download: has ? down : null, upload: has ? up : null, local: has ? local : null, total: has ? down + up : null,
	};
}

const future = (from: number, to = 30) => Array.from({ length: to - from + 1 }, (_, i) => ledgerDay(`2026-11-${String(from + i).padStart(2, '0')}`, 'future'));

/** The days of November 2026 in UTC: the 1st and 2nd counted (3 GB and 4 GB to the internet, 1 GB local), then future days */
const DAYS = [ledgerDay('2026-11-01', 'counted', 2 * GB, GB, 0), ledgerDay('2026-11-02', 'counted', 3 * GB, GB, GB), ...future(3)];

/** A month reply around `days`; its bytes sum the days with figures, as the ledger does */
function monthOf(days: UsageDay[], extra: Partial<UsageMonth> = {}): UsageMonth {
	const add = (k: 'download' | 'upload' | 'local' | 'total') => days.reduce((t, d) => t + (d[k] ?? 0), 0);
	return {
		tz: 'UTC', pending_tz: null, since: '2026-10-01', generation: 1, updated_at: '2026-11-02T13:00:00.000Z',
		days, bytes: { download: add('download'), upload: add('upload'), local: add('local'), total: add('total') },
		complete: days.every((d) => d.status === 'counted' || d.status === 'future'), gaps: [],
		year: 2026, month: 11, month_start: '2026-11-01T00:00:00.000Z', month_end: '2026-12-01T00:00:00.000Z',
		// NET-226 follow-up: the projection is internet bytes (the 7 GB total), without the local 1 GB
		projected: 105 * GB, daily_rate: 3.5 * GB, days_remaining: 28, sweep: null,
		...extra,
	};
}

const MONTH = monthOf(DAYS);
const NO_CAP = { monthly_cap_bytes: 0, monthly_cap_gb: 0, enabled: false, current_usage_bytes: 0, usage_percent: 0 };
const capOf = (bytes: number) => ({ ...NO_CAP, monthly_cap_bytes: bytes, monthly_cap_gb: bytes / GB, enabled: true });
const TZ_SET = { tz: 'UTC', set: true };

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
		// OLD CODE: stubDaemon({ '/api/bandwidth/monthly': MONTHLY }); (F4: the ledger's month)
		stubDaemon({ '/api/usage/month': MONTH });
		render(Page);
		// OLD CODE START: expect(await screen.findByText('3.0 GB')).toBeInTheDocument(); (the KPI sets its unit apart: "3.0" + "GB") OLD CODE END
		await screen.findByText('Projected');
		// OLD CODE: expect(screen.getByText('This month').closest('.kpi')).toHaveTextContent('3.0GB'); (NET-226 follow-up: local traffic left out)
		// OLD CODE: …toHaveTextContent('2.5GB'); and '↓ 2.0 GB down · ↑ 0.5 GB up · 0.5 GB local' (F4: the ledger fixture's figures)
		expect(screen.getByText('Internet this month').closest('.kpi')).toHaveTextContent('7.0GB');
		// OLD CODE: expect(...).toHaveTextContent('↓ 2.0 GB down · ↑ 1.0 GB up'); (NET-226: the originator's bytes, local traffic included)
		expect(screen.getByText('Internet this month').closest('.kpi')).toHaveTextContent('↓ 5.0 GB down · ↑ 2.0 GB up · 1.0 GB local');
		expect(screen.queryByText(/Couldn't load this month's usage/)).not.toBeInTheDocument();
		expect(screen.getByText("Couldn't load the time-of-day heatmap: the request failed.")).toBeInTheDocument();
	});
});

// ---------------------------------------------------------------------------
// Redesign: the cards with data, their loading and empty states, and the refresh contract
// ---------------------------------------------------------------------------

// OLD CODE START — F4 (NET-329): the daily chart reads the ledger's days (/api/usage/daily)
// const DAILY = {
// 	from: '', to: '',
// 	daily: [
// 		{ date: '2026-11-01T00:00:00Z', total_bytes: 3 * GB, orig_bytes: GB, resp_bytes: 2 * GB, upload_bytes: GB, download_bytes: 2 * GB, local_bytes: 0, connections: 10 },
// 		{ date: '2026-11-02T00:00:00Z', total_bytes: 5 * GB, orig_bytes: GB, resp_bytes: 4 * GB, upload_bytes: GB, download_bytes: 3 * GB, local_bytes: GB, connections: 12 },
// 	],
// };
// OLD CODE END
const DEVICES = {
	from: '', to: '',
	devices: [
		// OLD CODE START — NET-226: orig_bytes/resp_bytes
		// { ip: '192.168.1.9', total_bytes: 2 * GB, orig_bytes: GB, resp_bytes: GB, connection_count: 4, percent_of_total: 25 },
		// { ip: '192.168.1.10', total_bytes: 6 * GB, orig_bytes: GB, resp_bytes: 5 * GB, connection_count: 9, percent_of_total: 75 },
		// OLD CODE END
		{ ip: '192.168.1.9', total_bytes: 2 * GB, upload_bytes: 1.5 * GB, download_bytes: 0.5 * GB, connection_count: 4, percent_of_total: 25 },
		{ ip: '192.168.1.10', total_bytes: 6 * GB, upload_bytes: GB, download_bytes: 5 * GB, connection_count: 9, percent_of_total: 75 },
	],
};
const HEATMAP = {
	from: '', to: '', days: [], hours: [],
	matrix: Array.from({ length: 7 }, (_, d) => Array.from({ length: 24 }, (_, h) => (d === 3 && h === 21 ? 4 * GB : 0))),
};
/** NET-160: the daemon's LAN policy, so LAN addresses link to their device page. */
const LAN_POLICY = { version: 'v1', subnets: ['192.168.1.0/24'], source: 'env', ipv6: 'not-lan' };
// OLD CODE: const ALL = { '/api/bandwidth/monthly': MONTHLY, '/api/bandwidth/daily': DAILY, '/api/bandwidth/devices': DEVICES, '/api/bandwidth/heatmap': HEATMAP, '/api/network/lan': LAN_POLICY }; (F4)
const ALL = {
	'/api/usage/month': MONTH,
	'/api/bandwidth/devices': DEVICES,
	'/api/bandwidth/heatmap': HEATMAP,
	'/api/bandwidth/cap': NO_CAP,
	'/api/settings/timezone': TZ_SET,
	'/api/network/lan': LAN_POLICY,
};

describe('Bandwidth — cards', () => {

	// NET-368: the breakdown's count, and its kept rows, only say what a reply said
	const breakdown = () => screen.getByRole('heading', { name: 'Per-device breakdown' }).closest('.card') as HTMLElement;
	const breakdownSub = () => breakdown().querySelector('.card-sub')?.textContent;

	it('NET-368: the breakdown names no device count before its first reply or after it fails', async () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		const view = render(Page);
		expect(breakdownSub()).toBe('This month');
		view.unmount();
		stubDaemon({ '/api/usage/month': MONTH });
		render(Page);
		expect(await screen.findByText("Couldn't load the per-device breakdown: the request failed.")).toBeInTheDocument();
		expect(breakdownSub()).toBe('This month');
	});

	it('NET-368: a successful empty reply counts 0 devices', async () => {
		stubDaemon({ ...ALL, '/api/bandwidth/devices': { from: '', to: '', devices: [] } });
		render(Page);
		await vi.waitFor(() => expect(breakdownSub()).toBe('This month · 0 devices'));
	});

	it('NET-368: rows kept after a failed refresh say they are the last ones loaded, in the breakdown itself', async () => {
		stubDaemon(ALL);
		render(Page);
		await vi.waitFor(() => expect(breakdownSub()).toBe('This month · 2 devices'));
		stubDaemon({ ...ALL, '/api/bandwidth/devices': undefined });
		await refreshPage();
		await vi.waitFor(() => expect(breakdown()).toHaveTextContent("Couldn't refresh the per-device breakdown; showing the last figures loaded."));
		expect(breakdown().querySelectorAll('tbody tr')).toHaveLength(2);
		expect(breakdownSub()).toBe('This month · 2 devices');
	});
	afterEach(() => vi.unstubAllGlobals());

	it('shows the month KPIs, the daily chart, top consumers, the table and the heatmap', async () => {
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		stubDaemon(ALL);
		const { container } = render(Page);
		// OLD CODE: …toHaveTextContent('45.0GB'); (NET-226 follow-up: the projection leaves out local traffic)
		// OLD CODE: …toHaveTextContent('37.5GB'); (F4: the ledger's `projected`)
		expect((await screen.findByText('Projected')).closest('.kpi')).toHaveTextContent('105.0GB');
		expect(screen.getByText('Daily rate').closest('.kpi')).toHaveTextContent('3.5GB a day');
		expect(screen.getByText('Days remaining').closest('.kpi')).toHaveTextContent('28days');
		// OLD CODE: expect(screen.getByRole('img', { name: /^Busiest day 2 Nov, with 5\.0 GB/ })).toBeInTheDocument(); (chart gaps: a gaps chart is a group)
		// OLD CODE: expect(screen.getByRole('group', { name: /^Busiest day 2 Nov, with 5\.0 GB/ })).toBeInTheDocument(); (F4: the ledger's total leaves local out)
		expect(screen.getByRole('group', { name: /^Busiest day 2 Nov, with 4\.0 GB/ })).toBeInTheDocument();
		// OLD CODE START — NET-160: the table's address is a link now too, so there are two
		// expect(screen.getByRole('link', { name: /192\.168\.1\.9/ })).toHaveAttribute('href', '/devices/192.168.1.9');
		// OLD CODE END
		// top consumers and the table's address both drill down to the device (a LAN address)
		await vi.waitFor(() => {
			const links = screen.getAllByRole('link', { name: /192\.168\.1\.9/ });
			expect(links).toHaveLength(2);
			for (const link of links) expect(link).toHaveAttribute('href', '/devices/192.168.1.9');
		});
		expectNoNestedInteractive(container);
		const rows = screen.getAllByRole('row').slice(1).map((r) => r.querySelector('td')?.textContent?.trim());
		expect(rows).toEqual(['192.168.1.10', '192.168.1.9']);
		expect(screen.getByRole('img', { name: 'Busiest hour Thu 21:00, with 4.0 GB' })).toBeInTheDocument();
		// F4: every day is final, so nothing is marked
		expect(container.querySelector('path.flag')).toBeNull();
		expect(screen.queryByText(/^Not final yet/)).not.toBeInTheDocument();
	});

	it('NET-226: the device table reads what each device sent and received, and says what IPv6 it left out', async () => {
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		const router = { ...DEVICES.devices[1], ipv6_left_out: 12, ipv6_left_out_reason: 'router' };
		stubDaemon({ ...ALL, '/api/bandwidth/devices': { ...DEVICES, devices: [DEVICES.devices[0], router] } });
		render(Page);
		const table = await screen.findByRole('table', { name: 'Per-device breakdown' });
		const row = [...table.querySelectorAll('tbody tr')].find((r) => r.textContent?.includes('192.168.1.9'));
		const cells = [...(row?.querySelectorAll('td') ?? [])].map((td) => td.textContent?.trim());
		expect(cells.slice(2, 4)).toEqual(['1.5 GB', '500.0 MB']);
		expect(
			screen.getByText("The device at 192.168.1.10 forwards other devices' traffic (it's the router), so only its link-local IPv6 is counted."),
		).toBeInTheDocument();
	});

	it('marks a projection over the cap', async () => {
		// OLD CODE START — F4: the cap comes from /api/bandwidth/cap, the projection from the ledger
		// const over = { ...MONTHLY, projection: { ...MONTHLY.projection, cap_bytes: 40 * GB, usage_percent: 8, exceeds_cap: true } };
		// stubDaemon({ '/api/bandwidth/monthly': over });
		// OLD CODE END
		stubDaemon({ '/api/usage/month': MONTH, '/api/bandwidth/cap': capOf(70 * GB) });
		render(Page);
		expect((await screen.findByText('Over your cap')).closest('.chip')).toHaveClass('is-warn');
		// OLD CODE: expect(screen.getByRole('meter', { name: '8% of your monthly cap used' })).toBeInTheDocument(); (F4: 7 GB of 70 GB)
		expect(screen.getByRole('meter', { name: '10% of your monthly cap used' })).toBeInTheDocument();
	});

	it('NET-226 follow-up: the cap meter counts internet traffic, not traffic between your devices', async () => {
		// OLD CODE START — F4: 7 GB to and from the internet of 8 GB in all, against a 28 GB cap
		// // 2.5 GB to and from the internet of 3 GB in all, against a 10 GB cap
		// const capped = { ...MONTHLY, projection: { ...MONTHLY.projection, cap_bytes: 10e9, usage_percent: 25 } };
		// stubDaemon({ '/api/bandwidth/monthly': capped });
		// OLD CODE END
		stubDaemon({ '/api/usage/month': MONTH, '/api/bandwidth/cap': capOf(28 * GB) });
		render(Page);
		const meter = await screen.findByRole('meter', { name: '25% of your monthly cap used' });
		expect(meter).toHaveAttribute('aria-valuenow', '25');
		expect(screen.getByText('25% of your 28.0 GB cap')).toBeInTheDocument();
	});

	// F6 (NET-339): with no cap, the KPI says so and links to where it is set
	it('no cap: says "No cap set" and links to Settings › Network', async () => {
		stubDaemon({ '/api/usage/month': MONTH, '/api/bandwidth/cap': NO_CAP });
		const { container } = render(Page);
		const link = await screen.findByRole('link', { name: 'Set a monthly data cap' });
		expect(link).toHaveAttribute('href', '/settings?tab=network');
		expect(link.closest('.kpi')).toHaveTextContent('No cap set');
		expect(screen.queryByRole('meter')).not.toBeInTheDocument();
		expectNoNestedInteractive(container);
	});

	it('a cap set shows the meter, not the link', async () => {
		stubDaemon({ '/api/usage/month': MONTH, '/api/bandwidth/cap': capOf(70 * GB) });
		render(Page);
		await screen.findByRole('meter');
		expect(screen.queryByText(/No cap set/)).not.toBeInTheDocument();
		expect(screen.queryByRole('link', { name: 'Set a monthly data cap' })).not.toBeInTheDocument();
	});

	it('F4: says when the cap could not be read, instead of dropping the meter silently', async () => {
		stubDaemon({ '/api/usage/month': MONTH });
		render(Page);
		expect(await screen.findByText("Couldn't load your cap")).toBeInTheDocument();
		expect(screen.queryByRole('meter')).not.toBeInTheDocument();
		// F6: a cap that didn't load isn't "no cap"
		expect(screen.queryByText(/No cap set/)).not.toBeInTheDocument();
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
		// OLD CODE: stubDaemon({ ...ALL, '/api/bandwidth/daily': { from: '', to: '', daily: [] }, '/api/bandwidth/devices': { from: '', to: '', devices: [] } }); (F4)
		const uncounted = monthOf([ledgerDay('2026-11-01', 'not_counted'), ...future(2)]);
		stubDaemon({ ...ALL, '/api/usage/month': uncounted, '/api/bandwidth/devices': { from: '', to: '', devices: [] } });
		render(Page);
		expect(await screen.findByRole('heading', { name: 'No usage this month yet' })).toBeInTheDocument();
		expect(screen.getAllByRole('heading', { name: 'No devices yet' })).toHaveLength(2);
	});

	it('F4: a month whose days are not counted yet says it is still counting, not that there was no usage', async () => {
		const first = monthOf([ledgerDay('2026-11-01', 'pending'), ...future(2)]);
		stubDaemon({ ...ALL, '/api/usage/month': first });
		render(Page);
		expect(await screen.findByRole('heading', { name: 'Still counting' })).toBeInTheDocument();
		expect(screen.queryByRole('heading', { name: 'No usage this month yet' })).not.toBeInTheDocument();
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
		// OLD CODE: stubDaemon({ '/api/bandwidth/monthly': MONTHLY }); (F4)
		stubDaemon({ '/api/usage/month': MONTH });
		expect(await refreshPage()).toBe('partial');
		// the sections that failed keep their last figures and say so
		// OLD CODE: expect(screen.getByText("Couldn't refresh daily usage; showing the last figures loaded.")).toBeInTheDocument(); (F4: the chart's days come with the month, which loaded)
		expect(screen.getAllByText("Couldn't refresh per-device usage; showing the last figures loaded.").length).toBeGreaterThan(0);
		stubDaemon({});
		expect(await refreshPage()).toBe('failed');
		expect(screen.getByText("Couldn't refresh daily usage; showing the last figures loaded.")).toBeInTheDocument();
		// F4: with the month failed, the table still refreshed against the last month on screen
		const asked = vi.mocked(fetch).mock.calls.map(([u]) => String(u).split('?')[0]);
		expect(asked).toEqual(expect.arrayContaining(['/api/usage/month', '/api/bandwidth/devices']));
	});
});

// F4 (NET-329): the device card takes its bounds from the month on screen, and an older load never lands over a newer one
describe('Bandwidth — refreshes keep one month', () => {
	afterEach(() => vi.unstubAllGlobals());

	const deviceBounds = () =>
		vi.mocked(fetch).mock.calls.map(([u]) => String(u)).filter((u) => u.startsWith('/api/bandwidth/devices'))
			.map((u) => { const q = new URL(u, 'http://x').searchParams; return [q.get('from'), q.get('to')]; });

	it('a refresh whose month fails keeps the month on screen, and the device card asks for that same month', async () => {
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		stubDaemon(ALL);
		render(Page);
		await screen.findByText('Projected');
		const { '/api/usage/month': _month, ...withoutMonth } = ALL;
		stubDaemon(withoutMonth);
		expect(await refreshPage()).toBe('partial');
		expect(screen.getByText("Couldn't refresh this month's usage; showing the last figures loaded.")).toBeInTheDocument();
		expect(screen.getByText('Internet this month').closest('.kpi')).toHaveTextContent('November 2026, UTC');
		expect(screen.getByText('Internet this month').closest('.kpi')).toHaveTextContent('7.0GB');
		// the device card's refresh asked for the month still on screen, never a mix of two
		expect(deviceBounds()).toEqual([[MONTH.month_start, MONTH.month_end]]);
		expect(screen.getByText('This month · 2 devices')).toBeInTheDocument();
	});

	it("an older load's month landing after a newer one changes nothing", async () => {
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		const october = monthOf(DAYS.map((d) => ({ ...d, date: d.date.replace('-11-', '-10-') })), { month: 10, month_start: '2026-10-01T00:00:00.000Z', month_end: '2026-11-01T00:00:00.000Z' });
		let releaseOld: () => void = () => {};
		const oldReply = new Promise<void>((resolve) => (releaseOld = resolve));
		let monthCalls = 0;
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				const path = url.split('?')[0];
				if (path === '/api/usage/month' && ++monthCalls === 1) {
					await oldReply; // the first load's month is slow, and answers October
					return { ok: true, status: 200, json: async () => october };
				}
				const body = (ALL as Record<string, unknown>)[path];
				return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 503, json: async () => ({}) };
			}),
		);
		render(Page);
		await vi.waitFor(() => expect(monthCalls).toBe(1));
		expect(await refreshPage()).toBe('ok');
		const kpi = () => screen.getByText('Internet this month').closest('.kpi');
		expect(kpi()).toHaveTextContent('November 2026, UTC');
		releaseOld();
		await vi.waitFor(() => expect(deviceBounds()).toContainEqual([october.month_start, october.month_end]));
		await new Promise((r) => setTimeout(r, 0));
		expect(kpi()).toHaveTextContent('November 2026, UTC');
		expect(kpi()).not.toHaveTextContent('October');
	});
});

// OLD CODE: describe('Bandwidth — one month window and the device cap', () => { (F4: the owner's month, from the ledger)
describe("Bandwidth — the owner's month and the device cap", () => {
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
	});

	/** The query of every request to `path`. */
	const queries = (path: string) =>
		vi.mocked(fetch).mock.calls.map(([u]) => String(u)).filter((u) => u.startsWith(path)).map((u) => new URL(u, 'http://x').searchParams);

	// OLD CODE START — F4 (NET-329): the UTC month of the browser's clock; the ledger's month (the owner's zone) now bounds every card
	// it('O5: every request uses the UTC month of one captured now, also across a year rollover', async () => {
	// 	// 23:30 UTC on 31 December: still December in UTC, January already east of UTC
	// 	vi.useFakeTimers({ toFake: ['Date'] });
	// 	vi.setSystemTime(new Date('2026-12-31T23:30:00Z'));
	// 	stubDaemon(ALL);
	// 	render(Page);
	// 	await screen.findByText('Projected');
	// 	const [monthly] = queries('/api/bandwidth/monthly');
	// 	expect([monthly.get('year'), monthly.get('month')]).toEqual(['2026', '12']);
	// 	for (const path of ['/api/bandwidth/daily', '/api/bandwidth/devices']) {
	// 		const [q] = queries(path);
	// 		expect([q.get('from'), q.get('to')]).toEqual(['2026-12-01T00:00:00.000Z', '2026-12-31T23:30:00.000Z']);
	// 	}
	// });
	// OLD CODE END

	it('F4: the KPI row, the daily chart and the device card all cover the month the ledger names', async () => {
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		stubDaemon(ALL);
		render(Page);
		await screen.findByText('Projected');
		// the month is the daemon's to pick (the owner's zone), so the page sends none
		expect(queries('/api/usage/month')).toHaveLength(1);
		expect([...queries('/api/usage/month')[0].keys()]).toEqual([]);
		const [devices] = queries('/api/bandwidth/devices');
		expect([devices.get('from'), devices.get('to')]).toEqual([MONTH.month_start, MONTH.month_end]);
		// the chart draws the month reply's own days, so it needs no request of its own, and none counts the UTC month
		expect(screen.getByRole('group', { name: /^Busiest day 2 Nov/ })).toBeInTheDocument();
		const paths = vi.mocked(fetch).mock.calls.map(([u]) => String(u).split('?')[0]);
		expect(paths).not.toContain('/api/usage/daily');
		expect(paths).not.toContain('/api/bandwidth/monthly');
		expect(paths).not.toContain('/api/bandwidth/daily');
	});

	it('F4: at 17:00 on 30 November in Los Angeles (already December in UTC) every card is November there', async () => {
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(new Date('2026-12-01T01:00:00Z'));
		// Los Angeles days: 1 November is 25 hours (clocks back), every later day starts at 08:00 UTC
		const laDays = Array.from({ length: 30 }, (_, i): UsageDay => {
			const date = `2026-11-${String(i + 1).padStart(2, '0')}`;
			const start = i === 0 ? '2026-11-01T07:00:00.000Z' : `${date}T08:00:00.000Z`;
			const end = new Date(Date.parse(`${date}T08:00:00.000Z`) + DAY_MS).toISOString();
			const cutoff = i === 29 ? '2026-12-01T00:55:00.000Z' : end;
			return { date, start, end, cutoff, counted_at: cutoff, download: GB, upload: GB / 2, local: 0, total: 1.5 * GB, status: 'counted' };
		});
		const la = monthOf(laDays, {
			tz: 'America/Los_Angeles', month_start: '2026-11-01T00:00:00-07:00', month_end: '2026-12-01T00:00:00-08:00', days_remaining: 0.29,
		});
		stubDaemon({ ...ALL, '/api/usage/month': la });
		const { container } = render(Page);
		const kpi = (await screen.findByText('Internet this month')).closest('.kpi');
		expect(kpi).toHaveTextContent('November 2026, America/Los_Angeles');
		expect(kpi).toHaveTextContent('45.0GB');
		expect(screen.getByText('Days remaining').closest('.kpi')).toHaveTextContent('1day');
		const [devices] = queries('/api/bandwidth/devices');
		expect([devices.get('from'), devices.get('to')]).toEqual(['2026-11-01T00:00:00-07:00', '2026-12-01T00:00:00-08:00']);
		// the chart's last day is 30 November there, not 1 December
		await fireEvent.keyDown(screen.getByRole('group', { name: /^Busiest day/ }), { key: 'End' });
		expect(container.querySelector('.tip-tx')?.textContent).toMatch(/^30 Nov · /);
		expect(screen.getByText('Data per day: download, upload and local · this month, America/Los_Angeles days')).toBeInTheDocument();
	});

	it("O4: asks for the daemon's 200 and says top 200 only when the list is full", async () => {
		const full = { from: '', to: '', devices: Array.from({ length: 200 }, (_, i) => ({ ...DEVICES.devices[0], ip: `10.0.${i >> 8}.${i & 255}` })) };
		stubDaemon({ ...ALL, '/api/bandwidth/devices': full });
		render(Page);
		expect(await screen.findByText('This month · top 200 devices')).toBeInTheDocument();
		expect(queries('/api/bandwidth/devices')[0].get('limit')).toBe('200');
	});

	it('O4: a short list states its own count', async () => {
		stubDaemon(ALL);
		render(Page);
		expect(await screen.findByText('This month · 2 devices')).toBeInTheDocument();
	});
});

// F4 (NET-329): the month card says what its figure covers, and the KPIs never estimate from days that aren't final
describe('Bandwidth — the month card says how far to trust it', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('names the month and its zone, when counting began, and that it is still counting', async () => {
		const days = [ledgerDay('2026-11-01', 'not_counted'), ledgerDay('2026-11-02', 'counted', GB, GB), ledgerDay('2026-11-03', 'pending'), ...future(4)];
		stubDaemon({ ...ALL, '/api/usage/month': monthOf(days, { since: '2026-11-02', projected: null, daily_rate: null, days_remaining: null }) });
		render(Page);
		const kpi = (await screen.findByText('Internet this month')).closest('.kpi');
		expect(kpi).toHaveTextContent('November 2026, UTC · Since 2 Nov · Still counting');
	});

	it('shows no projection or daily rate while a day so far is not final, and the row closes up to three cards', async () => {
		const days = [ledgerDay('2026-11-01', 'approximate', GB, GB), ledgerDay('2026-11-02', 'counted', GB, GB), ...future(3)];
		stubDaemon({ ...ALL, '/api/usage/month': monthOf(days, { projected: null, daily_rate: null, days_remaining: null }) });
		const { container } = render(Page);
		const kpi = (await screen.findByText('Internet this month')).closest('.kpi');
		expect(kpi).toHaveTextContent('Approximate: some raw data was cleared before the day was final');
		expect(screen.queryByText('Projected')).not.toBeInTheDocument();
		expect(screen.getByText('Daily rate').closest('.kpi')).toHaveTextContent('—');
		expect(screen.getByText('Shown once every day so far is counted')).toBeInTheDocument();
		expect([...container.querySelectorAll('.kpi')].map((k) => k.classList.contains('c-4'))).toEqual([true, true, true]);
	});

	it('when counting began inside the month, says the rate waits for next month (it can never be complete)', async () => {
		const days = [ledgerDay('2026-11-01', 'not_counted'), ledgerDay('2026-11-02', 'counted', GB, GB), ...future(3)];
		stubDaemon({ ...ALL, '/api/usage/month': monthOf(days, { since: '2026-11-02', projected: null, daily_rate: null }) });
		render(Page);
		expect((await screen.findByText('Daily rate')).closest('.kpi')).toHaveTextContent('Shown from next month, the first one counted from its first day');
		expect(screen.queryByText('Shown once every day so far is counted')).not.toBeInTheDocument();
	});

	it('says when the figures were last updated, and which days count under earlier exclusions', async () => {
		const days = [ledgerDay('2026-11-01', 'old_rules', GB, GB), ledgerDay('2026-11-02', 'stale', GB, GB), ...future(3)];
		stubDaemon({ ...ALL, '/api/usage/month': monthOf(days, { projected: null, daily_rate: null }) });
		render(Page);
		const kpi = (await screen.findByText('Internet this month')).closest('.kpi');
		expect(kpi).toHaveTextContent('Counted under earlier exclusions');
		expect(kpi).toHaveTextContent(/Not updated since \d/);
	});
});

// chart gaps: a day with no connection record is "No data", never 0 B and never the busiest day
// F4: with the ledger, a day without figures is one not counted (or not yet); the tooltip says which
describe('Bandwidth — days with no record', () => {
	afterEach(() => vi.unstubAllGlobals());
	// OLD CODE START — F4: raw daily entries with a connection count; ledger days carry a status
	// const missing = (date: string) => ({ date, total_bytes: 0, orig_bytes: 0, resp_bytes: 0, upload_bytes: 0, download_bytes: 0, local_bytes: 0, connections: 0 });
	// const recordedZero = (date: string) => ({ ...missing(date), connections: 3 });
	// OLD CODE END
	const missing = (date: string) => ledgerDay(date, 'not_counted');
	const countedZero = (date: string) => ledgerDay(date, 'counted');

	// OLD CODE: it('draws a missing day as a "No data" band, and its tooltip says so', async () => { (F4: it says why)
	it('draws a day without figures as a "No data" band, and its tooltip says why', async () => {
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		// OLD CODE: stubDaemon({ ...ALL, '/api/bandwidth/daily': { ...DAILY, daily: [missing('2026-10-31T00:00:00Z'), ...DAILY.daily] } }); (F4)
		const days = [missing('2026-11-01'), ledgerDay('2026-11-02', 'counted', 2 * GB, GB), ledgerDay('2026-11-03', 'counted', 3 * GB, GB, GB)];
		stubDaemon({ ...ALL, '/api/usage/month': monthOf(days) });
		const { container } = render(Page);
		const chart = await screen.findByRole('group', { name: /^Busiest day 3 Nov, with 4\.0 GB/ });
		expect(container.querySelectorAll('rect.nodata')).toHaveLength(1);
		await fireEvent.keyDown(chart, { key: 'Home' });
		// OLD CODE: expect(container.querySelector('.tip-tx')?.textContent).toMatch(/ · no data$/); (F4: the day's status)
		expect(container.querySelector('.tip-tx')?.textContent).toBe('1 Nov · not counted');
	});

	// OLD CODE: it('shows the empty state for a month with no record at all, not a hatched chart or a busiest day', async () => { (F4)
	it('shows the empty state for a month with no counted day at all, not a hatched chart or a busiest day', async () => {
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		// OLD CODE: stubDaemon({ ...ALL, '/api/bandwidth/daily': { ...DAILY, daily: [missing('2026-11-01T00:00:00Z'), missing('2026-11-02T00:00:00Z')] } }); (F4)
		stubDaemon({ ...ALL, '/api/usage/month': monthOf([missing('2026-11-01'), missing('2026-11-02')]) });
		const { container } = render(Page);
		expect(await screen.findByText('No usage this month yet')).toBeInTheDocument();
		expect(container.querySelector('rect.nodata')).toBeNull();
		expect(screen.queryByRole('group', { name: /^Busiest day/ })).not.toBeInTheDocument();
	});

	// OLD CODE: it('a recorded 0 B day is the busiest, not the missing day before it', async () => { (F4)
	it('a counted 0 B day is the busiest, not the uncounted day before it', async () => {
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		// OLD CODE: stubDaemon({ ...ALL, '/api/bandwidth/daily': { ...DAILY, daily: [missing('2026-11-01T00:00:00Z'), recordedZero('2026-11-02T00:00:00Z')] } }); (F4)
		stubDaemon({ ...ALL, '/api/usage/month': monthOf([missing('2026-11-01'), countedZero('2026-11-02')]) });
		render(Page);
		expect(await screen.findByRole('group', { name: /^Busiest day 2 Nov, with 0 B/ })).toBeInTheDocument();
	});

	it('F4: marks each day that is not final, says what it is, and draws no future day', async () => {
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		const days = [
			ledgerDay('2026-11-01', 'counted', GB, GB),
			ledgerDay('2026-11-02', 'approximate', GB, GB),
			ledgerDay('2026-11-03', 'recount_pending', GB, GB),
			ledgerDay('2026-11-04', 'stale', GB, GB),
			...future(5),
		];
		stubDaemon({ ...ALL, '/api/usage/month': monthOf(days) });
		const { container } = render(Page);
		const chart = await screen.findByRole('group', { name: /^Busiest day/ });
		expect(container.querySelectorAll('path.flag')).toHaveLength(3);
		expect(screen.getByText('Not final yet. Approximate: 2 Nov · Waiting for a recount: 3 Nov · Not updated lately: 4 Nov')).toBeInTheDocument();
		await fireEvent.keyDown(chart, { key: 'Home' });
		await fireEvent.keyDown(chart, { key: 'ArrowRight' });
		expect(container.querySelector('.tip-tx')?.textContent).toBe('2 Nov · ↓ 1.0 GB · ↑ 1.0 GB · approximate');
		// the last point is today (4 Nov): the 26 future days aren't drawn
		await fireEvent.keyDown(chart, { key: 'End' });
		expect(container.querySelector('.tip-tx')?.textContent).toMatch(/^4 Nov · /);
	});
});

// F4 (NET-329): days are counted in UTC until the owner picks a zone; the page offers this browser's
describe('Bandwidth — the time zone', () => {
	afterEach(() => {
		vi.restoreAllMocks();
		vi.unstubAllGlobals();
	});

	const real = Intl.DateTimeFormat.prototype.resolvedOptions;
	/** This browser is in `timeZone`, whatever zone the test machine is in */
	function browserIn(timeZone: string) {
		vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions').mockImplementation(function (this: Intl.DateTimeFormat) {
			return { ...real.call(this), timeZone };
		});
	}

	/** The daemon, with the time zone's PUT answered by `put` and the month after it carrying `pending_tz` */
	function stubWithZone(owner: { tz: string; set: boolean }, put: { status: number; body: unknown }) {
		let picked: string | null = null;
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string, init?: RequestInit) => {
				const path = url.split('?')[0];
				if (path === '/api/settings/timezone' && init?.method === 'PUT') {
					if (put.status === 200) picked = JSON.parse(String(init.body)).tz;
					return { ok: put.status === 200, status: put.status, json: async () => put.body };
				}
				const replies: Record<string, unknown> = { ...ALL, '/api/settings/timezone': owner, '/api/usage/month': { ...MONTH, pending_tz: picked } };
				const body = replies[path];
				return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 503, json: async () => ({}) };
			}),
		);
	}

	it('offers to count days in this browser\'s zone, and says it is switching once asked', async () => {
		browserIn('America/Los_Angeles');
		stubWithZone({ tz: 'UTC', set: false }, { status: 200, body: { tz: 'America/Los_Angeles', set: true } });
		render(Page);
		expect(await screen.findByText('Days are counted in UTC. Count them in America/Los_Angeles?')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Count in America/Los_Angeles' }));
		expect(await screen.findByText('Switching to America/Los_Angeles…')).toBeInTheDocument();
		const put = vi.mocked(fetch).mock.calls.find(([, init]) => init?.method === 'PUT');
		expect(put?.[0]).toBe('/api/settings/timezone');
		expect(JSON.parse(String(put?.[1]?.body))).toEqual({ tz: 'America/Los_Angeles' });
		expect(screen.queryByRole('button', { name: /^Count in/ })).not.toBeInTheDocument();
	});

	it("gives the daemon's reason when it refuses the zone", async () => {
		browserIn('America/Los_Angeles');
		stubWithZone({ tz: 'UTC', set: false }, { status: 400, body: { error: "That isn't a time zone NetTap knows" } });
		render(Page);
		await fireEvent.click(await screen.findByRole('button', { name: 'Count in America/Los_Angeles' }));
		expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't change the time zone: That isn't a time zone NetTap knows");
		expect(screen.queryByText(/^Switching to/)).not.toBeInTheDocument();
	});

	it('offers nothing once the owner has picked a zone, or when this browser is already in it', async () => {
		browserIn('America/Los_Angeles');
		stubWithZone({ tz: 'Europe/London', set: true }, { status: 200, body: {} });
		const first = render(Page);
		await screen.findByText('Projected');
		expect(screen.queryByText(/^Days are counted in/)).not.toBeInTheDocument();
		first.unmount();

		browserIn('UTC');
		stubWithZone({ tz: 'UTC', set: false }, { status: 200, body: {} });
		render(Page);
		await screen.findByText('Projected');
		expect(screen.queryByText(/^Days are counted in/)).not.toBeInTheDocument();
	});

	it('Keep UTC confirms the zone in use, and the offer goes', async () => {
		browserIn('America/Los_Angeles');
		stubWithZone({ tz: 'UTC', set: false }, { status: 200, body: { tz: 'UTC', set: true } });
		render(Page);
		await fireEvent.click(await screen.findByRole('button', { name: 'Keep UTC' }));
		await vi.waitFor(() => expect(screen.queryByText(/^Days are counted in/)).not.toBeInTheDocument());
		const put = vi.mocked(fetch).mock.calls.find(([, init]) => init?.method === 'PUT');
		expect(JSON.parse(String(put?.[1]?.body))).toEqual({ tz: 'UTC' });
	});

	it("a browser in UTC under another name (Etc/UTC, Etc/Universal) isn't offered UTC again", async () => {
		for (const zone of ['Etc/UTC', 'Etc/Universal']) {
			browserIn(zone);
			stubWithZone({ tz: 'UTC', set: false }, { status: 200, body: {} });
			const view = render(Page);
			await screen.findByText('Projected');
			expect(screen.queryByText(/^Days are counted in/)).not.toBeInTheDocument();
			view.unmount();
		}
	});

	it('says it is switching while the ledger has not moved to the new zone yet', async () => {
		browserIn('America/Los_Angeles');
		stubDaemon({ ...ALL, '/api/usage/month': { ...MONTH, pending_tz: 'Europe/London' }, '/api/settings/timezone': { tz: 'Europe/London', set: true } });
		render(Page);
		expect(await screen.findByText('Switching to Europe/London…')).toBeInTheDocument();
	});
});
