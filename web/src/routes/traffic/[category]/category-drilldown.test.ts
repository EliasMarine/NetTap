import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { goto } from '$app/navigation';
import CategoryPage from './+page.svelte';

// NET-249 slice 2 (T9, plan §1a): the category's bandwidth chart asks for the owner's buckets, a
// pick narrows this page to the picked window (Custom) with the bytes picked, a Custom window
// sends no period comparison, and the page says when its own chart's total differs.

const nav = vi.hoisted(() => ({ set: (_query: string) => {} }));
vi.mock('$app/stores', async () => {
	const { writable } = await import('svelte/store');
	const at = (query: string) => ({ url: new URL(`http://localhost/traffic/streaming${query}`), params: { category: 'streaming' } });
	const page = writable(at(''));
	nav.set = (query) => page.set(at(query));
	return { page };
});
vi.mock('$app/navigation', () => ({ goto: vi.fn(async () => {}) }));

const F = '2026-11-13T10:00:00.000Z';
const T = '2026-11-13T10:04:59.999Z';
const DETAIL = {
	category: 'streaming', label: 'Streaming', device_count: 1, total_bytes: 4000, connection_count: 3, services: [],
	devices: [{ ip: '192.168.1.20', hostname: null, total_bytes: 4000, download_bytes: 3904, upload_bytes: 96, connections: 3, percent: 100 }],
};
let urls: URL[] = [];
let chartReply: (u: URL) => unknown;

/** The category's series over the request's own window, one minute slot per byte figure */
const slots = (bytes: number[], interval = '1m') => (u: URL) => ({
	category: 'streaming', from: u.searchParams.get('from'), to: u.searchParams.get('to'), interval,
	series: bytes.map((b, i) => ({ timestamp: new Date(Date.parse(F) + i * 60_000).toISOString(), download_bytes: b, upload_bytes: 0, total_bytes: b, connections: 1 })),
});

function stubDaemon() {
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	vi.stubGlobal(
		'fetch',
		vi.fn(async (raw: string) => {
			const u = new URL(raw, 'http://localhost');
			urls.push(u);
			const body =
				u.pathname === '/api/traffic/categories/streaming' ? DETAIL
				: u.pathname === '/api/traffic/categories/streaming/bandwidth' ? await chartReply(u)
				: u.pathname === '/api/traffic/summary' ? { total_bytes: 8000 }
				: u.pathname === '/api/traffic/bandwidth' ? { from: '', to: '', interval: '1h', series: [] }
				: null;
			return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 503, json: async () => ({}) };
		}),
	);
}

const asked = (path: string) => urls.filter((u) => u.pathname === path);
/** The chart's request: the category bandwidth over the detail's window (the other is the trend's) */
const chartCall = () => {
	const from = asked('/api/traffic/categories/streaming').at(-1)!.searchParams.get('from');
	return asked('/api/traffic/categories/streaming/bandwidth').filter((u) => u.searchParams.get('from') === from).at(-1)!;
};
const chart = () => screen.getByRole('group', { name: /^Busiest at/ });
const loaded = () => vi.waitFor(() => expect(chart()).toBeInTheDocument());
const target = (n = 0) => new URL(String(vi.mocked(goto).mock.calls[n][0]), 'http://localhost');
const kpi = (label: string) => screen.getByText(label).closest('.kpi') as HTMLElement;

beforeEach(() => {
	urls = [];
	chartReply = slots([1000, 3000]);
	nav.set('');
	vi.mocked(goto).mockReset();
	vi.mocked(goto).mockImplementation(async () => {});
	stubDaemon();
});
afterEach(() => vi.unstubAllGlobals());

describe('Traffic category — the chart drills into a window (NET-249)', () => {
	it("asks for each range's bucket from the owner's table", async () => {
		chartReply = (u) => slots([1000, 3000], u.searchParams.get('interval')!)(u); // the daemon echoes the bucket asked for
		render(CategoryPage);
		await loaded();
		expect(chartCall().searchParams.get('interval')).toBe('5m');
		expect(screen.getByText(/^Download and upload per 5 minutes · last 24 hours/)).toBeInTheDocument();
		for (const [range, bucket, words] of [['1h', '1m', 'minute'], ['6h', '5m', '5 minutes'], ['7d', '1h', 'hour'], ['30d', '3h', '3 hours']]) {
			await fireEvent.click(screen.getByRole('button', { name: range }));
			await vi.waitFor(() => expect(chartCall().searchParams.get('interval'), range).toBe(bucket));
			expect(await screen.findByText(new RegExp(`^Download and upload per ${words} · `))).toBeInTheDocument();
		}
	});

	it('names the bucket the reply says it used', async () => {
		chartReply = slots([1000, 3000], '1h');
		render(CategoryPage);
		await loaded();
		expect(chartCall().searchParams.get('interval')).toBe('5m');
		expect(screen.getByText(/^Download and upload per hour · last 24 hours/)).toBeInTheDocument();
	});

	it('a pick opens this page over the picked slots, with the bytes they drew', async () => {
		chartReply = (u) => ({ ...slots([1000, 3000])(u), from: F, to: '2026-11-13T10:01:20.000Z' });
		render(CategoryPage);
		await loaded();
		expect(screen.getByText('Click a point or drag across the chart to see this page for that time.')).toBeInTheDocument();
		await fireEvent.keyDown(chart(), { key: 'Home' });
		await fireEvent.keyDown(chart(), { key: 'Enter' });
		expect(target(0).pathname).toBe('/traffic/streaming');
		expect(Object.fromEntries(target(0).searchParams)).toEqual({ from: F, to: '2026-11-13T10:00:59.999Z', range: '24h', bytes: '1000' });
		await fireEvent.keyDown(chart(), { key: 'End', shiftKey: true });
		await fireEvent.keyDown(chart(), { key: 'Enter' });
		expect(Object.fromEntries(target(1).searchParams)).toEqual({ from: F, to: '2026-11-13T10:01:20.000Z', range: '24h', bytes: '4000' });
	});
});

describe('Traffic category — a Custom window from the URL (NET-249 §1a)', () => {
	it("loads every card over the link's window and sends no period comparison", async () => {
		nav.set(`?from=${F}&to=${T}&range=7d&bytes=4000`);
		render(CategoryPage);
		await loaded();
		for (const path of ['/api/traffic/categories/streaming', '/api/traffic/categories/streaming/bandwidth', '/api/traffic/summary']) {
			const all = asked(path);
			expect(all.map((u) => [u.searchParams.get('from'), u.searchParams.get('to')]), path).toEqual([[F, T]]);
		}
		expect(asked('/api/traffic/bandwidth')).toHaveLength(0);
		expect(chartCall().searchParams.get('interval')).toBe('1m');
		expect(screen.getByRole('button', { name: 'Custom' })).toHaveAttribute('aria-pressed', 'true');
		expect(kpi('Total bandwidth')).toHaveTextContent(/Window /);
		expect(kpi('Total bandwidth')).not.toHaveTextContent(/vs previous/);
		expect(kpi('Share of network')).toHaveTextContent(/Of all traffic in the window /);
	});

	it('choosing a range clears the window, and the comparison comes back', async () => {
		vi.mocked(goto).mockImplementation(async (h) => nav.set(String(h).replace('/traffic/streaming', '')));
		nav.set(`?from=${F}&to=${T}&bytes=4000`);
		render(CategoryPage);
		await loaded();
		await fireEvent.click(screen.getByRole('button', { name: '6h' }));
		expect(String(vi.mocked(goto).mock.calls[0][0])).toBe('/traffic/streaming');
		await vi.waitFor(() => expect(asked('/api/traffic/bandwidth')).toHaveLength(1));
		expect(chartCall().searchParams.get('interval')).toBe('5m');
		expect(screen.queryByRole('button', { name: 'Custom' })).not.toBeInTheDocument();
	});

	it('an invalid window falls back to the default range', async () => {
		nav.set(`?from=${F}&to=nope&bytes=4000`);
		render(CategoryPage);
		await loaded();
		const u = chartCall();
		expect((Date.parse(u.searchParams.get('to')!) - Date.parse(u.searchParams.get('from')!)) / 3_600_000).toBeCloseTo(24);
		expect(screen.getByRole('button', { name: '24h' })).toHaveAttribute('aria-pressed', 'true');
	});
});

describe('Traffic category — the shared receiver (NET-249)', () => {
	it('says nothing when the totals agree', async () => {
		nav.set(`?from=${F}&to=${T}&bytes=4000`);
		render(CategoryPage);
		await loaded();
		expect(screen.queryByText(/You clicked/)).not.toBeInTheDocument();
	});

	it('states the difference in bytes', async () => {
		nav.set(`?from=${F}&to=${T}&bytes=5000`);
		render(CategoryPage);
		expect(await screen.findByText(/^You clicked 5\.0 KB\. This window now shows 4\.0 KB \(1\.0 KB less\)\./)).toBeInTheDocument();
	});

	it('says nothing when the chart request failed', async () => {
		chartReply = () => null;
		nav.set(`?from=${F}&to=${T}&bytes=5000`);
		render(CategoryPage);
		await screen.findByText("Couldn't load bandwidth over time: the request failed.");
		expect(screen.queryByText(/You clicked/)).not.toBeInTheDocument();
	});

	it("never compares with a superseded window's reply", async () => {
		const W2 = { from: '2026-11-13T11:00:00.000Z', to: '2026-11-13T11:04:59.999Z' };
		let releaseFirst: (body: unknown) => void = () => {};
		chartReply = (u) => (u.searchParams.get('from') === F ? new Promise((resolve) => (releaseFirst = resolve)) : slots([1000, 3000])(u));
		nav.set(`?from=${F}&to=${T}&bytes=4000`);
		render(CategoryPage);
		await vi.waitFor(() => expect(asked('/api/traffic/categories/streaming/bandwidth')).toHaveLength(1));
		nav.set(`?from=${W2.from}&to=${W2.to}&bytes=4000`);
		await vi.waitFor(() => expect(asked('/api/traffic/categories/streaming/bandwidth')).toHaveLength(2));
		await loaded();
		// the first window's reply lands last, with another total; the page compares with the second's only
		releaseFirst(slots([99_000])(asked('/api/traffic/categories/streaming/bandwidth')[0]));
		await new Promise((r) => setTimeout(r, 0));
		expect(screen.queryByText(/You clicked/)).not.toBeInTheDocument();
		expect(chart()).toHaveAccessibleName(/with 3\.0 KB/);
	});
});
