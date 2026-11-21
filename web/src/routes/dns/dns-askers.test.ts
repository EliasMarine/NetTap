import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within, fireEvent } from '@testing-library/svelte';
import type { DomainSummary } from '$lib/api/drilldown';
import { refreshPage } from '$lib/stores/pageRefresh';
import { DOMAIN, LAN_POLICY } from '../../../e2e/visual/fixtures/drilldown';
import DnsPage from './+page.svelte';
import DomainAskers from './DomainAskers.svelte';

// A domain picked in any list on the DNS page shows which devices looked it up, over the window
// that list counted (GET /api/domains/{name}); the newest pick and the newest window always win.

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
const REGISTRY = { devices: [{ mac: 'aa', display_name: 'Living room TV', ips: ['192.168.1.22'], last_seen: '2026-11-05T00:00:00Z' }], total: 1 };
const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const FAIL = { ok: false, status: 503, json: async () => ({ error: 'The daemon is busy.' }) };

type Answer = (u: URL) => unknown | Promise<unknown>;
let urls: URL[] = [];
let over: Record<string, Answer> = {};

/** The domain summary for the request's own name and window, its askers as the fixture's. */
const summary = (u: URL): DomainSummary => ({
	...DOMAIN,
	name: decodeURIComponent(u.pathname.split('/').at(-1)!),
	from: u.searchParams.get('from')!,
	to: u.searchParams.get('to')!,
});
/** A reply held until `release` (or `reject`) is called */
function held() {
	let release: (body?: unknown) => void = () => {};
	const promise = new Promise((r) => (release = (body) => r(body)));
	return { answer: (u: URL) => promise.then((body) => (body === 'fail' ? FAIL : ok(body ?? summary(u)))), release };
}

function stubDaemon() {
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	vi.stubGlobal(
		'fetch',
		vi.fn(async (raw: string) => {
			const u = new URL(raw, 'http://localhost');
			urls.push(u);
			const key = u.pathname.startsWith('/api/domains/') ? '/api/domains/' : u.pathname;
			if (over[key]) return over[key](u);
			switch (key) {
				case '/api/dns/stats':
					return ok({ total_queries: 11, unique_domains: 2, nxdomain_count: 2, avg_resolution_ms: 1 });
				case '/api/dns/top-domains':
					return ok({ domains: [{ domain: 'a.example', count: 9, unique_clients: 2 }, { domain: 'b.example', count: 2, unique_clients: 1 }] });
				case '/api/dns/nxdomain':
					return ok({ nxdomains: [{ domain: 'nx.example', count: 2, clients: ['192.168.1.30'] }] });
				case '/api/dns/types':
					return ok({ types: [{ type: 'A', count: 11 }] });
				case '/api/dns/timeline':
					return ok({ series: [{ timestamp: F, count: 11 }] });
				case '/api/dns/suspicious':
					return ok({ suspicious: [], complete: true });
				case '/api/devices/registry':
					return ok(REGISTRY);
				case '/api/network/lan':
					return ok(LAN_POLICY);
				case '/api/domains/':
					return ok(summary(u));
				default:
					return FAIL;
			}
		}),
	);
}

const asked = (path: string) => urls.filter((u) => u.pathname.startsWith(path));
const lastDomain = () => asked('/api/domains/').at(-1)!;
const windowOf = (u: URL) => [u.searchParams.get('from'), u.searchParams.get('to')];
const settle = () => vi.waitFor(() => expect(screen.queryByText('Loading top domains')).not.toBeInTheDocument());
const card = () => screen.getByRole('heading', { name: 'Devices that looked it up' }).closest('.card') as HTMLElement;
/** The "Most looked-up domains" bar for a domain */
const bar = (domain: string) => within(screen.getByRole('heading', { name: 'Most looked-up domains' }).closest('.card') as HTMLElement).getByRole('button', { name: new RegExp(domain) });
const shows = (domain: string) => vi.waitFor(() => expect(card()).toHaveTextContent(`${domain} · lookups per device`));

describe('DomainAskers card', () => {
	const props = { name: 'a.example', askers: DOMAIN.dns, loading: false, failed: null, names: new Map([['192.168.1.22', 'Living room TV']]), words: 'last 24 hours', onretry: vi.fn(), onclear: vi.fn(), oncopy: vi.fn() };

	it('asks for a pick before any domain is chosen', () => {
		render(DomainAskers, { ...props, name: null, askers: null });
		expect(screen.getByText('No domain chosen')).toBeInTheDocument();
		expect(screen.getByText('Pick a domain in any list on this page to see which devices looked it up.')).toBeInTheDocument();
	});

	it('lists each device by name or address with its lookups, and links the domain page', async () => {
		render(DomainAskers, props);
		expect(screen.getByText('a.example · lookups per device · last 24 hours')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'Living room TV' }).getAttribute('href')).toContain('192.168.1.22');
		expect(screen.getByText('192.168.1.20')).toBeInTheDocument();
		expect(screen.getByText('260')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'Open domain page' })).toHaveAttribute('href', '/domain/a.example');
		await fireEvent.click(screen.getByRole('button', { name: 'Copy' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
		expect(props.oncopy).toHaveBeenCalledWith('a.example');
		expect(props.onclear).toHaveBeenCalled();
	});

	it('shows loading, an error with a retry, a stale answer, an empty and an incomplete list', async () => {
		const { rerender } = render(DomainAskers, { ...props, askers: null, loading: true });
		expect(screen.getByText('Loading the devices that looked up a.example')).toBeInTheDocument();
		// a new pick still loading never shows the last pick's error
		await rerender({ ...props, askers: null, failed: 'The daemon is busy.', loading: true });
		expect(screen.getByText('Loading the devices that looked up a.example')).toBeInTheDocument();
		expect(screen.queryByText('The daemon is busy.')).not.toBeInTheDocument();
		await rerender({ ...props, askers: null, failed: 'The daemon is busy.' });
		expect(screen.getByText("Couldn't load the devices that looked up a.example: the request failed.")).toBeInTheDocument();
		expect(screen.getByText('The daemon is busy.')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: /try again|retry/i }));
		expect(props.onretry).toHaveBeenCalled();
		await rerender({ ...props, failed: '' });
		expect(screen.getByRole('status')).toHaveTextContent("Couldn't refresh the devices that looked up a.example; showing the last figures loaded.");
		await rerender({ ...props, askers: { ...DOMAIN.dns, askers: [] } });
		expect(screen.getByText('No device looked it up in the last 24 hours')).toBeInTheDocument();
		await rerender({ ...props, askers: { ...DOMAIN.dns, askers_complete: false } });
		expect(screen.getByRole('status')).toHaveTextContent('Too many devices to list them all: showing the first 3.');
	});
});

describe('DNS page — the devices that looked a domain up', () => {
	beforeEach(() => {
		urls = [];
		over = {};
		nav.set('');
		stubDaemon();
	});
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
	});

	it('a bar, a table row or an NXDOMAIN row asks over its own list window', async () => {
		render(DnsPage);
		await settle();
		const top = asked('/api/dns/top-domains')[0];
		await fireEvent.click(bar('a.example'));
		await shows('a.example');
		expect(lastDomain().pathname).toBe('/api/domains/a.example');
		expect(windowOf(lastDomain())).toEqual(windowOf(top));
		expect(await within(card()).findByRole('link', { name: 'Living room TV' })).toBeInTheDocument();
		// the same domain again clears the pick
		await fireEvent.click(bar('a.example'));
		expect(within(card()).getByText('No domain chosen')).toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: 'Select nx.example' }));
		await shows('nx.example');
		expect(windowOf(lastDomain())).toEqual(windowOf(asked('/api/dns/nxdomain')[0]));
		await fireEvent.click(screen.getByRole('button', { name: 'Select b.example' }));
		await shows('b.example');
	});

	it('an older pick answering late never replaces the newer one', async () => {
		render(DnsPage);
		await settle();
		const slow = held();
		over['/api/domains/'] = slow.answer;
		await fireEvent.click(bar('a.example'));
		delete over['/api/domains/'];
		await fireEvent.click(bar('b.example'));
		await shows('b.example');
		await within(card()).findByRole('link', { name: 'Living room TV' });
		slow.release({ ...summary(new URL('http://x/api/domains/a.example?from=a&to=b')), dns: { ...DOMAIN.dns, askers: [] } });
		await new Promise((r) => setTimeout(r, 0));
		expect(card()).toHaveTextContent('b.example · lookups per device');
		expect(within(card()).getByRole('link', { name: 'Living room TV' })).toBeInTheDocument();
	});

	it("a Custom window's refresh asks again over that window and counts it", async () => {
		nav.set(`?from=${F}&to=${T}`);
		render(DnsPage);
		await settle();
		await fireEvent.click(bar('a.example'));
		await shows('a.example');
		expect(windowOf(lastDomain())).toEqual([F, T]);
		expect(await refreshPage()).toBe('ok');
		expect(asked('/api/domains/')).toHaveLength(2);
		expect(windowOf(lastDomain())).toEqual([F, T]);
	});

	it('a refresh whose askers fail is partial, and keeps the last askers', async () => {
		render(DnsPage);
		await settle();
		await fireEvent.click(bar('a.example'));
		await within(card()).findByRole('link', { name: 'Living room TV' });
		over['/api/domains/'] = () => FAIL;
		expect(await refreshPage()).toBe('partial');
		expect(within(card()).getByRole('status')).toHaveTextContent("Couldn't refresh the devices that looked up a.example");
		expect(within(card()).getByRole('link', { name: 'Living room TV' })).toBeInTheDocument();
	});

	it('a pick still loading when the range changes never shows over the new range', async () => {
		render(DnsPage);
		await settle();
		const slow = held();
		over['/api/domains/'] = slow.answer;
		await fireEvent.click(bar('a.example'));
		await fireEvent.click(screen.getByRole('button', { name: '7d' }));
		slow.release();
		await new Promise((r) => setTimeout(r, 0));
		expect(within(card()).getByText('No domain chosen')).toBeInTheDocument();
	});

	it('when the top list fails to refresh, a pick from it keeps the window that list still shows', async () => {
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(new Date('2026-11-13T12:00:00Z'));
		render(DnsPage);
		await settle();
		const top = asked('/api/dns/top-domains')[0];
		await fireEvent.click(bar('a.example'));
		await shows('a.example');
		vi.setSystemTime(new Date('2026-11-13T12:05:00Z'));
		over['/api/dns/top-domains'] = () => FAIL;
		expect(await refreshPage()).toBe('partial');
		expect(windowOf(asked('/api/dns/stats').at(-1)!)).not.toEqual(windowOf(top));
		expect(windowOf(lastDomain())).toEqual(windowOf(top));
	});

	it('a pick made while a refresh is out is asked again over the new window before the refresh ends', async () => {
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(new Date('2026-11-13T12:00:00Z'));
		render(DnsPage);
		await settle();
		const first = asked('/api/dns/top-domains')[0];
		vi.setSystemTime(new Date('2026-11-13T12:05:00Z'));
		const slowTop = held();
		over['/api/dns/top-domains'] = slowTop.answer;
		const done = refreshPage();
		await vi.waitFor(() => expect(asked('/api/dns/top-domains')).toHaveLength(2));
		await fireEvent.click(bar('a.example'));
		expect(windowOf(lastDomain())).toEqual(windowOf(first));
		slowTop.release({ domains: [{ domain: 'a.example', count: 9, unique_clients: 2 }] });
		expect(await done).toBe('ok');
		expect(windowOf(lastDomain())).toEqual(windowOf(asked('/api/dns/top-domains')[1]));
		expect(windowOf(lastDomain())).not.toEqual(windowOf(first));
	});
});

// NET-348: the 50 ms scroll after a pick was never cleared, so a test that ended first saw it run after
// jsdom's teardown ("ReferenceError: document is not defined", PR #345's Vitest job).
describe('DNS page — the scroll after a pick', () => {
	const original = Element.prototype.scrollIntoView;
	let scrollIntoView = vi.fn();

	beforeEach(() => {
		urls = [];
		over = {};
		nav.set('');
		stubDaemon();
		scrollIntoView = vi.fn();
		Element.prototype.scrollIntoView = scrollIntoView;
	});
	afterEach(() => {
		Element.prototype.scrollIntoView = original;
		vi.useRealTimers();
		vi.unstubAllGlobals();
	});

	it('scrolls to the askers 50 ms after a pick', async () => {
		render(DnsPage);
		await settle();
		vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
		await fireEvent.click(bar('a.example'));
		vi.advanceTimersByTime(50);
		expect(scrollIntoView).toHaveBeenCalledOnce();
	});

	it('closing the page clears a scroll still waiting, so nothing runs after teardown', async () => {
		const { unmount } = render(DnsPage);
		await settle();
		vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
		await fireEvent.click(bar('a.example'));
		unmount();
		// the element is gone either way; what must not happen is the timer reaching for `document`
		const byId = vi.spyOn(document, 'getElementById');
		vi.advanceTimersByTime(50);
		expect(byId).not.toHaveBeenCalledWith('domain-askers');
		expect(scrollIntoView).not.toHaveBeenCalled();
		byId.mockRestore();
	});

	it('a second pick within 50 ms replaces the waiting scroll', async () => {
		render(DnsPage);
		await settle();
		vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
		await fireEvent.click(bar('a.example'));
		await fireEvent.click(bar('b.example'));
		vi.advanceTimersByTime(50);
		expect(scrollIntoView).toHaveBeenCalledOnce();
	});
});
