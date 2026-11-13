import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { goto } from '$app/navigation';
import DnsPage from './+page.svelte';

// NET-249 slice 2 (T5, plan §1a): the DNS timeline asks for the owner's buckets, a pick narrows
// this page to the picked window (Custom), every card follows it, and the page says when its own
// chart's total differs from the queries picked.

const nav = vi.hoisted(() => ({ set: (_query: string) => {} }));
vi.mock('$app/stores', async () => {
	const { writable } = await import('svelte/store');
	const page = writable({ url: new URL('http://localhost/dns') });
	nav.set = (query) => page.set({ url: new URL(`http://localhost/dns${query}`) });
	return { page };
});
vi.mock('$app/navigation', () => ({ goto: vi.fn(async () => {}) }));

const F = '2026-11-13T10:00:00.000Z';
const T = '2026-11-13T10:04:59.999Z';
const WINDOW_PATHS = ['/api/dns/stats', '/api/dns/top-domains', '/api/dns/nxdomain', '/api/dns/types', '/api/dns/timeline', '/api/dns/suspicious'];

type Timeline = (url: URL) => unknown;
let timeline: Timeline;
let urls: URL[] = [];

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const FAIL = { ok: false, status: 503, json: async () => ({}) };
/** A timeline reply over the request's own window, one slot per count */
const slots = (counts: number[], interval = '1m') => (u: URL) => ({
	from: u.searchParams.get('from'),
	to: u.searchParams.get('to'),
	interval,
	series: counts.map((count, i) => ({ timestamp: new Date(Date.parse(F) + i * 60_000).toISOString(), count })),
});

function stubDaemon() {
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	vi.stubGlobal(
		'fetch',
		vi.fn(async (raw: string) => {
			const u = new URL(raw, 'http://localhost');
			urls.push(u);
			switch (u.pathname) {
				case '/api/dns/timeline': {
					const body = await timeline(u);
					return body === 'fail' ? FAIL : ok(body);
				}
				case '/api/dns/stats':
					return ok({ total_queries: 11, unique_domains: 2, nxdomain_count: 0, avg_resolution_ms: 1 });
				case '/api/dns/top-domains':
					return ok({ domains: [{ domain: 'a.example', count: 11, unique_clients: 1 }] });
				case '/api/dns/nxdomain':
					return ok({ nxdomains: [] });
				case '/api/dns/types':
					return ok({ types: [{ type: 'A', count: 11 }] });
				case '/api/dns/suspicious':
					return ok({ suspicious: [], complete: true });
				default:
					return u.pathname.startsWith('/api/dns/device/') ? ok({ domains: [] }) : FAIL;
			}
		}),
	);
}

const asked = (path: string) => urls.filter((u) => u.pathname === path);
const lastTimeline = () => asked('/api/dns/timeline').at(-1)!;
const settle = () => vi.waitFor(() => expect(screen.queryByText('Loading the query timeline')).not.toBeInTheDocument());
const chart = () => screen.getByRole('group', { name: /^Busiest at/ });
const target = (n = 0) => new URL(String(vi.mocked(goto).mock.calls[n][0]), 'http://localhost');

beforeEach(() => {
	urls = [];
	timeline = slots([4, 6, 1]);
	nav.set('');
	vi.mocked(goto).mockReset();
	vi.mocked(goto).mockImplementation(async () => {});
	stubDaemon();
});
afterEach(() => vi.unstubAllGlobals());

describe('DNS page — the timeline drills into a window (NET-249)', () => {
	it("asks for each range's bucket from the owner's table", async () => {
		render(DnsPage);
		await settle();
		expect(lastTimeline().searchParams.get('interval')).toBe('5m'); // 24h
		expect(screen.getByText(/^Queries per 5 minutes · last 24 hours/)).toBeInTheDocument();
		for (const [range, bucket, words] of [['1h', '1m', 'minute'], ['6h', '5m', '5 minutes'], ['7d', '1h', 'hour'], ['30d', '3h', '3 hours']]) {
			await fireEvent.click(screen.getByRole('button', { name: range }));
			await vi.waitFor(() => expect(lastTimeline().searchParams.get('interval'), range).toBe(bucket));
			expect(screen.getByText(new RegExp(`^Queries per ${words} · `))).toBeInTheDocument();
		}
	});

	it('a pick opens this page over the picked slots, clipped to the reply, with the queries they counted', async () => {
		// the reply's window starts 30 s into its first slot and ends 10 s into its last
		timeline = () => ({
			from: '2026-11-13T10:00:30.000Z', to: '2026-11-13T10:02:10.000Z', interval: '1m',
			series: [{ timestamp: F, count: 4 }, { timestamp: '2026-11-13T10:01:00.000Z', count: 6 }, { timestamp: '2026-11-13T10:02:00.000Z', count: 1 }],
		});
		render(DnsPage);
		await settle();
		expect(screen.getByText('Click a point or drag across the chart to see this page for that time.')).toBeInTheDocument();
		await fireEvent.keyDown(chart(), { key: 'Home' });
		await fireEvent.keyDown(chart(), { key: 'Enter' });
		expect(target(0).pathname).toBe('/dns');
		expect(Object.fromEntries(target(0).searchParams)).toEqual({ from: '2026-11-13T10:00:30.000Z', to: '2026-11-13T10:00:59.999Z', range: '24h', count: '4' });
		await fireEvent.keyDown(chart(), { key: 'End', shiftKey: true });
		await fireEvent.keyDown(chart(), { key: 'Enter' });
		expect(Object.fromEntries(target(1).searchParams)).toEqual({ from: '2026-11-13T10:00:30.000Z', to: '2026-11-13T10:02:10.000Z', range: '24h', count: '11' });
	});

	it('a reply whose bucket is not on the table stays a picture', async () => {
		timeline = slots([4, 6], '10m');
		render(DnsPage);
		await settle();
		expect(screen.queryByRole('group', { name: /^Busiest at/ })).not.toBeInTheDocument();
		expect(screen.queryByText(/see this page for that time/)).not.toBeInTheDocument();
	});
});

describe('DNS page — a Custom window from the URL (NET-249 §1a)', () => {
	it("puts every card, the device lookup included, on the link's window, shown as Custom", async () => {
		nav.set(`?from=${F}&to=${T}&range=7d&count=11`);
		render(DnsPage);
		await settle();
		for (const path of WINDOW_PATHS) {
			const [u] = asked(path);
			expect([u.searchParams.get('from'), u.searchParams.get('to')], path).toEqual([F, T]);
		}
		// five minutes: the 1h range's minute slots (bucketFor)
		expect(lastTimeline().searchParams.get('interval')).toBe('1m');
		expect(screen.getByRole('button', { name: 'Custom' })).toHaveAttribute('aria-pressed', 'true');
		expect(screen.getByText(/^Queries per minute · window /)).toBeInTheDocument();
		await fireEvent.input(screen.getByLabelText('Device IP'), { target: { value: '10.0.0.5' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Lookup' }));
		await vi.waitFor(() => expect(urls.some((u) => u.pathname === '/api/dns/device/10.0.0.5')).toBe(true));
		const device = urls.find((u) => u.pathname === '/api/dns/device/10.0.0.5')!;
		expect([device.searchParams.get('from'), device.searchParams.get('to')]).toEqual([F, T]);
	});

	it('choosing a range clears the window and loads that range ending now', async () => {
		vi.mocked(goto).mockImplementation(async (href) => nav.set(String(href).replace(/^\/dns/, '')));
		nav.set(`?from=${F}&to=${T}&range=7d&count=11&domain=a.example`);
		render(DnsPage);
		await settle();
		await fireEvent.click(screen.getByRole('button', { name: '6h' }));
		expect(String(vi.mocked(goto).mock.calls[0][0])).toBe('/dns?domain=a.example');
		await vi.waitFor(() => expect(lastTimeline().searchParams.get('interval')).toBe('5m'));
		const u = lastTimeline();
		expect((Date.parse(u.searchParams.get('to')!) - Date.parse(u.searchParams.get('from')!)) / 3_600_000).toBeCloseTo(6);
		expect(screen.queryByRole('button', { name: 'Custom' })).not.toBeInTheDocument();
		expect(screen.getByRole('button', { name: '6h' })).toHaveAttribute('aria-pressed', 'true');
	});

	it('an invalid window falls back to the default range', async () => {
		nav.set(`?from=not-a-date&to=${T}&count=11`);
		render(DnsPage);
		await settle();
		const u = lastTimeline();
		expect((Date.parse(u.searchParams.get('to')!) - Date.parse(u.searchParams.get('from')!)) / 3_600_000).toBeCloseTo(24);
		expect(screen.queryByRole('button', { name: 'Custom' })).not.toBeInTheDocument();
		expect(screen.getByRole('button', { name: '24h' })).toHaveAttribute('aria-pressed', 'true');
		expect(screen.queryByText(/You clicked/)).not.toBeInTheDocument();
	});
});

describe('DNS page — the shared receiver (NET-249)', () => {
	it('says nothing when the narrowed chart totals the queries picked', async () => {
		nav.set(`?from=${F}&to=${T}&count=11`);
		render(DnsPage);
		await settle();
		expect(screen.queryByText(/You clicked/)).not.toBeInTheDocument();
	});

	it('says when the narrowed chart counts another total', async () => {
		nav.set(`?from=${F}&to=${T}&count=10`);
		render(DnsPage);
		expect(await screen.findByText(/^You clicked 10\. This window now shows 11 queries \(1 more\)\. Records can be logged/)).toBeInTheDocument();
	});

	it('says nothing when the chart request failed', async () => {
		timeline = () => 'fail';
		nav.set(`?from=${F}&to=${T}&count=10`);
		render(DnsPage);
		await screen.findByText("Couldn't load the query timeline: the request failed.");
		expect(screen.queryByText(/You clicked/)).not.toBeInTheDocument();
	});

	it("never compares with a superseded window's reply", async () => {
		const W2 = { from: '2026-11-13T11:00:00.000Z', to: '2026-11-13T11:04:59.999Z' };
		let releaseFirst: (body: unknown) => void = () => {};
		timeline = (u) =>
			u.searchParams.get('from') === F ? new Promise((resolve) => (releaseFirst = resolve)) : slots([5, 5, 1])(u);
		nav.set(`?from=${F}&to=${T}&count=11`);
		render(DnsPage);
		await vi.waitFor(() => expect(asked('/api/dns/timeline')).toHaveLength(1));
		nav.set(`?from=${W2.from}&to=${W2.to}&count=11`);
		await vi.waitFor(() => expect(asked('/api/dns/timeline')).toHaveLength(2));
		await settle();
		// the first window's reply lands last, with another total; the page compares with the second's only
		releaseFirst(slots([99])(asked('/api/dns/timeline')[0]));
		await new Promise((r) => setTimeout(r, 0));
		expect(screen.queryByText(/You clicked/)).not.toBeInTheDocument();
		expect(chart()).toHaveAccessibleName(/with 5 queries/);
	});
});
