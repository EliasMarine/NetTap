import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { goto } from '$app/navigation';
import { refreshPage } from '$lib/stores/pageRefresh';
import type { DomainSummary } from '$lib/api/drilldown';
import { DOMAIN } from '../../../../e2e/visual/fixtures/drilldown';

// NET-249 slice 2 (T8, plan §1a): the domain chart asks for the owner's buckets through the new
// `interval`, a pick narrows this page to the picked window (Custom), and the page says when its
// own chart's total differs from the lookups picked.

const nav = vi.hoisted(() => ({ set: (_query: string) => {} }));
vi.mock('$app/stores', async () => {
	const { writable } = await import('svelte/store');
	const at = (query: string) => ({ url: new URL(`http://localhost/domain/stream.example.net${query}`), params: { name: 'stream.example.net' } });
	const page = writable(at(''));
	nav.set = (query) => page.set(at(query));
	return { page };
});
vi.mock('$app/navigation', () => ({ goto: vi.fn(async () => {}) }));

const { default: Page } = await import('./+page.svelte');

const F = '2026-11-13T10:00:00.000Z';
const T = '2026-11-13T10:04:59.999Z';
let urls: URL[] = [];
let summary: (u: URL) => DomainSummary | null | Promise<DomainSummary>;

/** The domain reply over the request's own window, one minute slot per count */
const withSlots = (counts: number[], interval = '1m') => (u: URL): DomainSummary => ({
	...DOMAIN,
	from: u.searchParams.get('from')!,
	to: u.searchParams.get('to')!,
	interval,
	dns: { ...DOMAIN.dns, timeline: counts.map((n, i) => ({ t: new Date(Date.parse(F) + i * 60_000).toISOString(), n })) },
});

function stubDaemon() {
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	vi.stubGlobal(
		'fetch',
		vi.fn(async (raw: string) => {
			const u = new URL(raw, 'http://localhost');
			urls.push(u);
			const body = u.pathname.startsWith('/api/domains/') ? await summary(u) : u.pathname === '/api/devices/registry' ? { devices: [], total: 0 } : null;
			return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 502, json: async () => ({ error: 'busy' }) };
		}),
	);
}

const domainCalls = () => urls.filter((u) => u.pathname === '/api/domains/stream.example.net');
const loaded = () => vi.waitFor(() => expect(screen.getByRole('group', { name: /^Busiest at/ })).toBeInTheDocument());
const chart = () => screen.getByRole('group', { name: /^Busiest at/ });
const target = (n = 0) => new URL(String(vi.mocked(goto).mock.calls[n][0]), 'http://localhost');
const href = (name: RegExp) => new URL(screen.getByRole('link', { name }).getAttribute('href')!, 'http://localhost');

beforeEach(() => {
	urls = [];
	summary = withSlots([4, 6, 1]);
	nav.set('');
	vi.mocked(goto).mockReset();
	vi.mocked(goto).mockImplementation(async () => {});
	stubDaemon();
});
afterEach(() => vi.unstubAllGlobals());

describe('Domain page — the chart drills into a window (NET-249)', () => {
	it("asks for each range's bucket from the owner's table", async () => {
		summary = (u) => withSlots([4, 6, 1], u.searchParams.get('interval')!)(u); // the daemon echoes the bucket asked for
		render(Page);
		await loaded();
		expect(domainCalls().at(-1)!.searchParams.get('interval')).toBe('5m');
		expect(screen.getByText('DNS lookups per 5 minutes · last 24 hours')).toBeInTheDocument();
		for (const [range, bucket, words] of [['1h', '1m', 'minute'], ['6h', '5m', '5 minutes'], ['7d', '1h', 'hour'], ['30d', '3h', '3 hours']]) {
			await fireEvent.click(screen.getByRole('button', { name: range }));
			await vi.waitFor(() => expect(domainCalls().at(-1)!.searchParams.get('interval'), range).toBe(bucket));
			expect(await screen.findByText(new RegExp(`^DNS lookups per ${words} · `))).toBeInTheDocument();
		}
	});

	it('a pick opens this page over the picked slots, with the lookups they counted', async () => {
		summary = (u) => ({ ...withSlots([4, 6, 1])(u), from: '2026-11-13T10:00:30.000Z', to: '2026-11-13T10:02:10.000Z' });
		render(Page);
		await loaded();
		expect(screen.getByText('Click a point or drag across the chart to see this page for that time.')).toBeInTheDocument();
		await fireEvent.keyDown(chart(), { key: 'End' });
		await fireEvent.keyDown(chart(), { key: 'Enter' });
		expect(target(0).pathname).toBe('/domain/stream.example.net');
		expect(Object.fromEntries(target(0).searchParams)).toEqual({ from: '2026-11-13T10:02:00.000Z', to: '2026-11-13T10:02:10.000Z', range: '24h', count: '1' });
		await fireEvent.keyDown(chart(), { key: 'Home', shiftKey: true });
		await fireEvent.keyDown(chart(), { key: 'Enter' });
		expect(Object.fromEntries(target(1).searchParams)).toEqual({ from: '2026-11-13T10:00:30.000Z', to: '2026-11-13T10:02:10.000Z', range: '24h', count: '11' });
	});

	it('names the bucket the reply says it used', async () => {
		summary = withSlots([4, 6], '1h');
		render(Page);
		await loaded();
		expect(domainCalls().at(-1)!.searchParams.get('interval')).toBe('5m');
		expect(screen.getByText('DNS lookups per hour · last 24 hours')).toBeInTheDocument();
	});

	it('a reply with no known bucket (an older daemon) stays a picture', async () => {
		summary = (u) => ({ ...withSlots([4])(u), interval: undefined });
		render(Page);
		await vi.waitFor(() => expect(screen.getByRole('img', { name: /^Busiest at/ })).toBeInTheDocument());
		expect(screen.queryByText(/see this page for that time/)).not.toBeInTheDocument();
	});
});

describe('Domain page — a Custom window from the URL (NET-249 §1a)', () => {
	it("loads over the link's window and every onward link keeps it", async () => {
		nav.set(`?from=${F}&to=${T}&range=7d&count=11`);
		render(Page);
		await loaded();
		const [u] = domainCalls();
		expect([u.searchParams.get('from'), u.searchParams.get('to'), u.searchParams.get('interval')]).toEqual([F, T, '1m']);
		expect(screen.getByRole('button', { name: 'Custom' })).toHaveAttribute('aria-pressed', 'true');
		expect(screen.getByText(/^DNS lookups per minute · window /)).toBeInTheDocument();
		for (const link of [/Open alerts/, /Search Log Explorer for/, /Certificates seen for this name/]) {
			expect([href(link).searchParams.get('from'), href(link).searchParams.get('to')], String(link)).toEqual([F, T]);
		}
	});

	it('choosing a range clears the window', async () => {
		vi.mocked(goto).mockImplementation(async (h) => nav.set(String(h).replace('/domain/stream.example.net', '')));
		nav.set(`?from=${F}&to=${T}&count=11`);
		render(Page);
		await loaded();
		await fireEvent.click(screen.getByRole('button', { name: '7d' }));
		expect(String(vi.mocked(goto).mock.calls[0][0])).toBe('/domain/stream.example.net');
		await vi.waitFor(() => expect(domainCalls().at(-1)!.searchParams.get('interval')).toBe('1h'));
		const u = domainCalls().at(-1)!;
		expect((Date.parse(u.searchParams.get('to')!) - Date.parse(u.searchParams.get('from')!)) / 86_400_000).toBeCloseTo(7);
		expect(screen.queryByRole('button', { name: 'Custom' })).not.toBeInTheDocument();
	});

	it('an invalid window falls back to the default range', async () => {
		nav.set(`?from=${T}&to=${F}&count=11`); // ends before it starts
		render(Page);
		await loaded();
		const u = domainCalls().at(-1)!;
		expect((Date.parse(u.searchParams.get('to')!) - Date.parse(u.searchParams.get('from')!)) / 3_600_000).toBeCloseTo(24);
		expect(screen.getByRole('button', { name: '24h' })).toHaveAttribute('aria-pressed', 'true');
	});
});

describe('Domain page — the shared receiver (NET-249)', () => {
	it('says nothing when the totals agree, and states the difference when they do not', async () => {
		nav.set(`?from=${F}&to=${T}&count=11`);
		const view = render(Page);
		await loaded();
		expect(screen.queryByText(/You clicked/)).not.toBeInTheDocument();
		view.unmount();
		nav.set(`?from=${F}&to=${T}&count=13`);
		render(Page);
		expect(await screen.findByText(/^You clicked 13\. This window now shows 11 lookups \(2 fewer\)\./)).toBeInTheDocument();
	});

	it('drops the line when a refresh fails, while the last figures stay', async () => {
		nav.set(`?from=${F}&to=${T}&count=13`);
		render(Page);
		await screen.findByText(/^You clicked 13\./);
		summary = () => null;
		await refreshPage();
		await vi.waitFor(() => expect(screen.queryByText(/You clicked/)).not.toBeInTheDocument());
		expect(chart()).toBeInTheDocument();
	});

	it("never compares with a superseded window's reply", async () => {
		const W2 = { from: '2026-11-13T11:00:00.000Z', to: '2026-11-13T11:04:59.999Z' };
		let releaseFirst: (body: DomainSummary) => void = () => {};
		summary = (u) => (u.searchParams.get('from') === F ? new Promise((resolve) => (releaseFirst = resolve)) : withSlots([5, 5, 1])(u));
		nav.set(`?from=${F}&to=${T}&count=11`);
		render(Page);
		await vi.waitFor(() => expect(domainCalls()).toHaveLength(1));
		nav.set(`?from=${W2.from}&to=${W2.to}&count=11`);
		await vi.waitFor(() => expect(domainCalls()).toHaveLength(2));
		await loaded();
		// the first window's reply lands last, with another total; the page compares with the second's only
		releaseFirst(withSlots([99])(domainCalls()[0]));
		await new Promise((r) => setTimeout(r, 0));
		expect(screen.queryByText(/You clicked/)).not.toBeInTheDocument();
		expect(chart()).toHaveAccessibleName(/with 5 lookups/);
	});
});
