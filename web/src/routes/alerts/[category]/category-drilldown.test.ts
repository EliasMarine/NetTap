import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { goto } from '$app/navigation';
import Page from './+page.svelte';

// NET-249 slice 2 (T2): the category timeline asks for the owner's buckets, a pick reopens this
// page over the picked slots with their count (the sub-category filter the chart ignores goes),
// and the page says when its own chart's total differs.

const nav = vi.hoisted(() => ({ set: (_query: string) => {} }));
vi.mock('$app/stores', async () => {
	const { writable } = await import('svelte/store');
	const at = (query: string) => ({ url: new URL(`http://localhost/alerts/scan${query}`), params: { category: 'scan' } });
	const page = writable(at(''));
	nav.set = (query) => page.set(at(query));
	return { page };
});
vi.mock('$app/navigation', () => ({ goto: vi.fn(async () => {}) }));

const F = '2026-11-13T10:00:00.000Z';
const T = '2026-11-13T10:04:59.999Z';
const DETAIL = {
	category: { id: 'scan', label: 'Scanning', description: '', color: 'amber', icon: 'radar' },
	stats: { total: 4, unique_sources: 1, unique_targets: 2, affected_devices: 2 },
	severity_breakdown: { critical: 0, high: 1, medium: 3, low: 0, info: 0 },
	sub_categories: [{ id: 'port_scan', label: 'Port Scan', count: 3 }],
	affected_devices: [], top_signatures: [], mitre_techniques: [], from: '', to: '',
};
const LIST = { from: '', to: '', page: 1, size: 25, total: 0, total_pages: 0, alerts: [] };
let urls: URL[] = [];
let timeline: (u: URL) => unknown;

/** The timeline over the request's own window, one minute slot per count */
const slots = (counts: number[], interval = '1m') => (u: URL) => ({
	category: 'scan', from: u.searchParams.get('from'), to: u.searchParams.get('to'), interval,
	series: counts.map((total, i) => ({ timestamp: new Date(Date.parse(F) + i * 60_000).toISOString(), total, sub_categories: {} })),
});

function stubDaemon() {
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	vi.stubGlobal(
		'fetch',
		vi.fn(async (raw: string) => {
			const u = new URL(raw, 'http://localhost');
			urls.push(u);
			const body =
				u.pathname === '/api/alerts/categories/scan' ? DETAIL
				: u.pathname === '/api/alerts/categories/scan/timeline' ? await timeline(u)
				: u.pathname === '/api/alerts' ? LIST
				: null;
			return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 503, json: async () => ({}) };
		}),
	);
}

const asked = (path: string) => urls.filter((u) => u.pathname === path);
const chart = () => screen.getByRole('group', { name: /^Busiest/ });
const loaded = () => vi.waitFor(() => expect(chart()).toBeInTheDocument());
const target = (n = 0) => new URL(String(vi.mocked(goto).mock.calls[n][0]), 'http://localhost');

beforeEach(() => {
	urls = [];
	timeline = slots([1, 3]);
	nav.set('');
	vi.mocked(goto).mockReset();
	vi.mocked(goto).mockImplementation(async (h) => nav.set(String(h).replace('/alerts/scan', '')));
	stubDaemon();
});
afterEach(() => vi.unstubAllGlobals());

describe('Alert category — the timeline drills into a window (NET-249)', () => {
	it("asks for each range's bucket from the owner's table", async () => {
		timeline = (u) => slots([1, 3], u.searchParams.get('interval')!)(u); // the daemon echoes the bucket asked for
		render(Page);
		await loaded();
		expect(asked('/api/alerts/categories/scan/timeline').at(-1)!.searchParams.get('interval')).toBe('5m');
		expect(screen.getByText(/^Alerts per 5 minutes · last 24 hours/)).toBeInTheDocument();
		for (const [range, bucket, words] of [['1h', '1m', 'minute'], ['6h', '5m', '5 minutes'], ['7d', '1h', 'hour'], ['30d', '3h', '3 hours']]) {
			await fireEvent.click(screen.getByRole('button', { name: range }));
			await vi.waitFor(() => expect(asked('/api/alerts/categories/scan/timeline').at(-1)!.searchParams.get('interval'), range).toBe(bucket));
			expect(await screen.findByText(new RegExp(`^Alerts per ${words} · `))).toBeInTheDocument();
		}
	});

	it('names the bucket the reply says it used', async () => {
		timeline = slots([1, 3], '1h');
		render(Page);
		await loaded();
		expect(asked('/api/alerts/categories/scan/timeline').at(-1)!.searchParams.get('interval')).toBe('5m');
		expect(screen.getByText(/^Alerts per hour · last 24 hours/)).toBeInTheDocument();
	});

	it('a pick reopens this page over the picked slots, with their count', async () => {
		vi.mocked(goto).mockImplementation(async () => {});
		timeline = (u) => ({ ...slots([1, 3])(u), from: '2026-11-13T10:00:20.000Z', to: '2026-11-13T10:01:40.000Z' });
		render(Page);
		await loaded();
		expect(screen.getByText('Click a point or drag across the chart to see this page for that time.')).toBeInTheDocument();
		await fireEvent.keyDown(chart(), { key: 'End' });
		await fireEvent.keyDown(chart(), { key: 'Enter' });
		expect(target(0).pathname).toBe('/alerts/scan');
		expect(Object.fromEntries(target(0).searchParams)).toEqual({ from: '2026-11-13T10:01:00.000Z', to: '2026-11-13T10:01:40.000Z', range: '24h', count: '3' });
		await fireEvent.keyDown(chart(), { key: 'Home', shiftKey: true });
		await fireEvent.keyDown(chart(), { key: 'Enter' });
		expect(Object.fromEntries(target(1).searchParams)).toEqual({ from: '2026-11-13T10:00:20.000Z', to: '2026-11-13T10:01:40.000Z', range: '24h', count: '4' });
	});

	it('a pick clears the sub-category filter, which the chart never applied', async () => {
		render(Page);
		await loaded();
		await fireEvent.click(screen.getByText('Port Scan').closest('button')!);
		await vi.waitFor(() => expect(asked('/api/alerts').at(-1)!.searchParams.get('sub')).toBe('port_scan'));
		const before = asked('/api/alerts').length;
		await fireEvent.keyDown(chart(), { key: 'Home' });
		await fireEvent.keyDown(chart(), { key: 'Enter' });
		await vi.waitFor(() => expect(asked('/api/alerts').length).toBeGreaterThan(before));
		await loaded();
		const list = asked('/api/alerts').at(-1)!;
		expect(list.searchParams.get('sub')).toBeNull();
		expect(list.searchParams.get('from')).toBe(target(0).searchParams.get('from'));
		expect(screen.queryByText(/Sub-category: /)).not.toBeInTheDocument();
	});
});

describe('Alert category — the shared receiver (NET-249)', () => {
	it('says nothing when the totals agree', async () => {
		nav.set(`?from=${F}&to=${T}&count=4`);
		render(Page);
		await loaded();
		expect(screen.queryByText(/You clicked/)).not.toBeInTheDocument();
	});

	it('says when the narrowed chart counts another total', async () => {
		nav.set(`?from=${F}&to=${T}&count=6`);
		render(Page);
		expect(await screen.findByText(/^You clicked 6\. This window now shows 4 alerts \(2 fewer\)\./)).toBeInTheDocument();
	});

	it('says so even when the window now holds no alerts', async () => {
		nav.set(`?from=${F}&to=${T}&count=6`);
		timeline = slots([0, 0]);
		const empty = { ...DETAIL, stats: { ...DETAIL.stats, total: 0 } };
		vi.mocked(fetch).mockImplementation(async (raw) => {
			const u = new URL(String(raw), 'http://localhost');
			const body = u.pathname === '/api/alerts/categories/scan' ? empty : u.pathname.endsWith('/timeline') ? timeline(u) : LIST;
			return { ok: true, status: 200, json: async () => body } as Response;
		});
		render(Page);
		await screen.findByText(/No alerts in Scanning/);
		expect(screen.getByText(/^You clicked 6\. This window now shows 0 alerts \(6 fewer\)\./)).toBeInTheDocument();
	});

	it('says nothing when the chart request failed', async () => {
		timeline = () => null;
		nav.set(`?from=${F}&to=${T}&count=6`);
		render(Page);
		await screen.findByText(/Couldn't load the alert volume over time/);
		expect(screen.queryByText(/You clicked/)).not.toBeInTheDocument();
	});

	it("never compares with a superseded window's reply", async () => {
		const W2 = { from: '2026-11-13T11:00:00.000Z', to: '2026-11-13T11:04:59.999Z' };
		let releaseFirst: (body: unknown) => void = () => {};
		timeline = (u) => (u.searchParams.get('from') === F ? new Promise((resolve) => (releaseFirst = resolve)) : slots([1, 3])(u));
		nav.set(`?from=${F}&to=${T}&count=4`);
		render(Page);
		await vi.waitFor(() => expect(asked('/api/alerts/categories/scan/timeline')).toHaveLength(1));
		nav.set(`?from=${W2.from}&to=${W2.to}&count=4`);
		await vi.waitFor(() => expect(asked('/api/alerts/categories/scan/timeline')).toHaveLength(2));
		await loaded();
		// the first window's reply lands last, with another total; the page compares with the second's only
		releaseFirst(slots([99])(asked('/api/alerts/categories/scan/timeline')[0]));
		await new Promise((r) => setTimeout(r, 0));
		expect(screen.queryByText(/You clicked/)).not.toBeInTheDocument();
		expect(chart()).toHaveAccessibleName(/with 3 alerts/);
	});
});
