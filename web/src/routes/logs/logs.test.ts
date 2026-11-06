import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import type { Writable } from 'svelte/store';
import { page } from '$app/stores';
import { goto } from '$app/navigation';
import { refreshPage } from '$lib/stores/pageRefresh';
import Page from './+page.svelte';
import { expectNoNestedInteractive } from '../../tests/nested-interactive';

// OLD CODE START — a fixed URL; the page now follows URL changes, so the tests move it
// vi.mock('$app/stores', () => ({
// 	page: readable({ url: new URL('http://localhost/logs') }),
// }));
// OLD CODE END
vi.mock('$app/stores', async () => {
	const { writable } = await import('svelte/store');
	return { page: writable({ url: new URL('http://localhost/logs') }) };
});
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

const pageStore = page as unknown as Writable<{ url: URL }>;
const goTo = (path: string) => pageStore.set({ url: new URL(path, 'http://localhost') });
beforeEach(() => goTo('/logs'));

describe('Log Explorer', () => {
	it('should export a Svelte component', async () => {
		const module = await import('./+page.svelte');
		expect(module.default).toBeDefined();
	});

	// NET-165: every card here counts excluded devices (Settings promises they stay visible in
	// logs), so "Top DNS queries" can rank a domain differently from the DNS page; say so
	it('says its figures include devices excluded in Settings', () => {
		stubDaemon({});
		render(Page);
		expect(screen.getByText(/Devices excluded in Settings are counted here too/)).toBeInTheDocument();
		vi.unstubAllGlobals();
	});
});

// #96: failed aggregations read as 0 events, 0 B and "No protocol data"

/**
 * Replies by path (a function reply is called with the URL); any path not listed answers 503.
 * With `tick`, each request moves the (faked) clock a second on.
 */
function stubDaemon(replies: Record<string, unknown>, tick = false): void {
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			if (tick) vi.setSystemTime(Date.now() + 1000);
			const reply = replies[url.split('?')[0]];
			const body = typeof reply === 'function' ? reply(url) : reply;
			return body
				? { ok: true, status: 200, json: async () => body }
				: { ok: false, status: 503, json: async () => ({}) };
		}),
	);
}

describe('Log Explorer — failed aggregations', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('says what failed instead of 0 events and "No protocol data"', async () => {
		stubDaemon({});
		render(Page);
		expect(await screen.findByText("Couldn't load log totals: the request failed.")).toBeInTheDocument();
		// KpiCard: sentence-case label, and the card's root is .kpi
		expect(screen.getByText('Total events').closest('.kpi')).not.toHaveTextContent('0');
		expect(screen.getByText("Couldn't load protocols: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('No protocol data')).not.toBeInTheDocument();
		expect(screen.getByText("Couldn't load the activity timeline: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load top DNS queries: the request failed.")).toBeInTheDocument();
	});

	it('still says "No protocol data" when the range really has none', async () => {
		stubDaemon({ '/api/logs/protocol-breakdown': { from: '', to: '', protocols: [] } });
		render(Page);
		expect(await screen.findByText('No protocol data')).toBeInTheDocument();
	});
});

const hit = (id: string, ip: string) => ({ _id: id, _source: { '@timestamp': '2026-11-03T10:00:00Z', source: { ip }, event: { dataset: 'conn' } } });
const AGGREGATIONS = {
	'/api/logs/stats': { total_events: 10, unique_sources: 2, protocol_count: 1, total_bytes: 1024 },
	'/api/logs/timeline': { buckets: [{ timestamp: '2026-11-03T10:00:00Z', total: 10, conn: 10 }] },
	'/api/logs/top-talkers': { talkers: [{ ip: '10.0.0.5', count: 10 }] },
	'/api/logs/protocol-breakdown': { protocols: [{ protocol: 'conn', count: 10 }] },
	'/api/logs/top-destinations': { destinations: [{ ip: '10.0.0.1', count: 10 }] },
	'/api/logs/top-dns': { queries: [{ domain: 'example.org', count: 4 }] },
};

/** The `query` parameter of every /api/logs/search request so far. */
function searchQueries(): string[] {
	return vi.mocked(fetch).mock.calls
		.map(([u]) => String(u))
		.filter((u) => u.startsWith('/api/logs/search'))
		.map((u) => new URL(u, 'http://x').searchParams.get('query') ?? '');
}

// The top-bar search hands off with goto('/logs?ip=…') or goto('/logs?query=…'), also while on /logs.
describe('Log Explorer — URL hand-off', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('runs the new search when a second hand-off arrives while mounted', async () => {
		stubDaemon({ ...AGGREGATIONS, '/api/logs/search': { hits: [], total: 0 } });
		goTo('/logs?ip=192.168.1.20');
		render(Page);
		await vi.waitFor(() => expect(searchQueries()).toHaveLength(1));
		expect(searchQueries()[0]).toBe('(source.ip:"192.168.1.20" OR destination.ip:"192.168.1.20")');

		goTo('/logs?query=google.com');
		await vi.waitFor(() => expect(searchQueries()).toHaveLength(2));
		expect(searchQueries()[1]).toBe('google.com'); // the IP filter went with the old hand-off
		expect(screen.getByLabelText('Search logs')).toHaveValue('google.com');
		expect(screen.queryByText(/IP:/)).not.toBeInTheDocument();

		goTo('/logs?ip=10.0.0.9');
		await vi.waitFor(() => expect(searchQueries()).toHaveLength(3));
		expect(searchQueries()[2]).toBe('(source.ip:"10.0.0.9" OR destination.ip:"10.0.0.9")');
		expect(screen.getByLabelText('Search logs')).toHaveValue('');
	});

	it('reads ?query= on the first load and ignores a hash-only change', async () => {
		stubDaemon({ ...AGGREGATIONS, '/api/logs/search': { hits: [], total: 0 } });
		goTo('/logs?query=dns');
		render(Page);
		await vi.waitFor(() => expect(searchQueries()).toEqual(['dns']));
		goTo('/logs?query=dns#log-table');
		await new Promise((r) => setTimeout(r, 0));
		expect(searchQueries()).toEqual(['dns']);
	});

	it('opens on the window a link carries (?range=), so its counts match the page it came from (NET-160)', async () => {
		stubDaemon({ ...AGGREGATIONS, '/api/logs/search': { hits: [], total: 0 } });
		goTo('/logs?query=dns&range=7d');
		render(Page);
		await vi.waitFor(() => expect(searchQueries()).toEqual(['dns']));
		expect(screen.getByRole('button', { name: '7d' })).toHaveAttribute('aria-pressed', 'true');
		const search = vi.mocked(fetch).mock.calls.map(([u]) => new URL(String(u), 'http://x')).find((u) => u.pathname === '/api/logs/search')!;
		const hours = (Date.parse(search.searchParams.get('from')!) - Date.parse(search.searchParams.get('to')!)) / -3_600_000;
		expect(hours).toBe(168);
		goTo('/logs');
	});
});

// PLAN §5.5: the loader is the top bar's Refresh; it reports what loaded, and older answers never win.
describe('Log Explorer — refresh contract', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('shows the cards loading, not zeros, before the first answers', () => {
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(Page);
		expect(screen.getByText('Loading the activity timeline')).toBeInTheDocument();
		expect(screen.getByText('Loading protocols')).toBeInTheDocument();
		expect(screen.getByText('Searching logs')).toBeInTheDocument();
		expect(screen.getByText('Total events').closest('.kpi')).toHaveTextContent('—');
	});

	it('reports ok, partial and failed to the top bar', async () => {
		let replies: Record<string, unknown> = { ...AGGREGATIONS, '/api/logs/search': { hits: [hit('a', '10.0.0.5')], total: 1 } };
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				const body = replies[url.split('?')[0]];
				return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 503, json: async () => ({}) };
			}),
		);
		const { container } = render(Page);
		await screen.findByRole('button', { name: /^Open log entry from/ });
		// NET-160: the row's address is a link beside the row button, never inside it
		expect(screen.getByRole('link', { name: '10.0.0.5' })).toHaveAttribute('href', '/address/10.0.0.5');
		expectNoNestedInteractive(container);
		expect(await refreshPage()).toBe('ok');

		replies = { ...AGGREGATIONS };
		expect(await refreshPage()).toBe('partial');
		expect(screen.getByText("Couldn't search the logs: the request failed.")).toBeInTheDocument();

		replies = {};
		expect(await refreshPage()).toBe('failed');
	});

	it("drops an older search's slower answer", async () => {
		const held: Array<() => void> = [];
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		vi.stubGlobal(
			'fetch',
			vi.fn((url: string) => {
				const path = url.split('?')[0];
				if (path !== '/api/logs/search') {
					const body = (AGGREGATIONS as Record<string, unknown>)[path];
					return Promise.resolve(body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 503, json: async () => ({}) });
				}
				const dns = url.includes('log_type=zeek.dns');
				searches++;
				// the first load answers at once; the next "all logs" search is the slow one
				const ip = dns ? '10.0.0.77' : searches === 1 ? '10.0.0.55' : '10.0.0.66';
				const body = { hits: [hit(ip, ip)], total: 1 };
				if (dns || searches === 1) return Promise.resolve({ ok: true, status: 200, json: async () => body });
				return new Promise((resolve) => held.push(() => resolve({ ok: true, status: 200, json: async () => body })));
			}),
		);
		let searches = 0;
		render(Page);
		await vi.waitFor(() => expect(screen.getAllByText('10.0.0.55').length).toBeGreaterThan(0));
		await new Promise((r) => setTimeout(r, 0)); // the first load has finished

		// a fresh search that is slow, then a type change that answers first
		await fireEvent.click(screen.getByRole('button', { name: 'Search' }));
		await vi.waitFor(() => expect(held).toHaveLength(1));
		await fireEvent.click(screen.getByRole('button', { name: 'DNS' }));
		await vi.waitFor(() => expect(screen.getAllByText('10.0.0.77').length).toBeGreaterThan(0));
		held[0]();
		await new Promise((r) => setTimeout(r, 0));
		expect(screen.queryByText('10.0.0.66')).not.toBeInTheDocument();
	});

	it('links a single address only, never an array or text joined into one', async () => {
		const many = { ...hit('m', ''), _source: { ...hit('m', '')._source, source: { ip: ['10.0.0.7', '10.0.0.8'] } } };
		const text = { ...hit('t', ''), _source: { ...hit('t', '')._source, source: { ip: 'unknown' } } };
		stubDaemon({ ...AGGREGATIONS, '/api/logs/search': { hits: [hit('a', '10.0.0.5'), many, text], total: 3 } });
		render(Page);
		expect(await screen.findByRole('link', { name: '10.0.0.5' })).toHaveAttribute('href', '/address/10.0.0.5');
		expect(screen.getByText('10.0.0.7, 10.0.0.8').closest('a')).toBeNull();
		expect(screen.getByText('unknown').closest('a')).toBeNull();
		expect(document.querySelector('a[href*="%2C"]')).toBeNull();
	});

	it('asks the daemon for the new order when a header is clicked', async () => {
		stubDaemon({ ...AGGREGATIONS, '/api/logs/search': { hits: [hit('a', '10.0.0.5')], total: 1 } });
		render(Page);
		await screen.findByRole('button', { name: /^Open log entry from/ });
		const header = [...document.querySelectorAll('th button')].find((b) => b.textContent === 'source.ip')!;
		await fireEvent.click(header);
		const sorts = () => vi.mocked(fetch).mock.calls.map(([u]) => String(u)).filter((u) => u.startsWith('/api/logs/search')).map((u) => new URL(u, 'http://x').searchParams.get('sort'));
		await vi.waitFor(() => expect(sorts().at(-1)).toBe('source.ip:desc'));
		await fireEvent.click(header);
		await vi.waitFor(() => expect(sorts().at(-1)).toBe('source.ip:asc'));
	});
});

describe('Log Explorer — field descriptions on the table headers (NET-146)', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('keys each description by the field name the daemon sends', async () => {
		stubDaemon({
			...AGGREGATIONS,
			'/api/logs/search': { hits: [hit('a', '10.0.0.5')], total: 1 },
			'/api/logs/fields/zeek.conn': { fields: [{ name: 'source.ip', type: 'ip', description: 'Who opened the connection' }] },
		});
		render(Page);
		const header = await screen.findByRole('columnheader', { name: 'source.ip' });
		await vi.waitFor(() => expect(header.querySelector('button')).toHaveAttribute('title', 'Who opened the connection'));
	});
});

// A busy box logs 20+ protocols: listing them all made the breakdown card three times the
// timeline's height, and the timeline sat at the top of its stretched card with a gap below.
describe('Log Explorer — protocol breakdown length', () => {
	afterEach(() => vi.unstubAllGlobals());

	const manyProtocols = Array.from({ length: 12 }, (_, i) => ({ protocol: `p${i}`, label: `Proto ${i}`, count: 1000 - i }));

	it('lists the top 10 protocols and shows the rest on request', async () => {
		stubDaemon({ ...AGGREGATIONS, '/api/logs/protocol-breakdown': { protocols: manyProtocols }, '/api/logs/search': { hits: [], total: 0 } });
		render(Page);
		expect(await screen.findByText('Proto 9')).toBeInTheDocument();
		expect(screen.queryByText('Proto 10')).not.toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Show all 12' }));
		expect(screen.getByText('Proto 11')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Show fewer' }));
		expect(screen.queryByText('Proto 11')).not.toBeInTheDocument();
	});

	it('has no show-all button when every protocol already fits', async () => {
		stubDaemon({ ...AGGREGATIONS, '/api/logs/search': { hits: [], total: 0 } });
		render(Page);
		expect(await screen.findByText('Connections')).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: /Show all/ })).not.toBeInTheDocument();
	});

	it('lets the timeline fill its card instead of leaving a gap under it', () => {
		stubDaemon({});
		render(Page);
		expect(screen.getByText('Activity timeline').closest('.card')).toHaveClass('col');
	});
});

// Accuracy audit 2026-11-06
describe('Log Explorer — figures match what the daemon counts', () => {
	afterEach(() => vi.unstubAllGlobals());

	const protocolsOf = (n: number) => Array.from({ length: n }, (_, i) => ({ protocol: `p${i}`, label: `Proto ${i}`, count: 1000 - i }));

	it('plots each slot\'s total, not only the seven named types (I5)', async () => {
		stubDaemon({
			...AGGREGATIONS,
			'/api/logs/timeline': { buckets: [{ timestamp: '2026-11-03T10:00:00Z', total: 15, conn: 10, alert: 0 }] },
			'/api/logs/search': { hits: [], total: 0 },
		});
		render(Page);
		expect(await screen.findByRole('img', { name: /^Busiest at .*, with 15 events$/ })).toBeInTheDocument();
	});

	it('names no total when the daemon\'s 20-protocol cap is reached (I5)', async () => {
		stubDaemon({ ...AGGREGATIONS, '/api/logs/protocol-breakdown': { protocols: protocolsOf(20) }, '/api/logs/search': { hits: [], total: 0 } });
		render(Page);
		expect(await screen.findByText('Showing 10 of the 20 most common')).toBeInTheDocument();
		expect(screen.queryByText(/of 20$/)).not.toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Show the 20 most common' }));
		expect(screen.getByText('The 20 most common')).toBeInTheDocument();
		expect(screen.getByText('Proto 19')).toBeInTheDocument();
	});

	it('gives the exact count between 10 and 20, and no footer under 10 (I5)', async () => {
		stubDaemon({ ...AGGREGATIONS, '/api/logs/protocol-breakdown': { protocols: protocolsOf(15) }, '/api/logs/search': { hits: [], total: 0 } });
		const { unmount } = render(Page);
		expect(await screen.findByText('Showing 10 of 15')).toBeInTheDocument();
		unmount();
		stubDaemon({ ...AGGREGATIONS, '/api/logs/protocol-breakdown': { protocols: protocolsOf(9) }, '/api/logs/search': { hits: [], total: 0 } });
		render(Page);
		expect(await screen.findByText('Proto 8')).toBeInTheDocument();
		expect(screen.queryByText(/^Showing \d+ of/)).not.toBeInTheDocument();
	});

	it('reads TLS and DHCP columns from the fields Malcolm writes (I6)', async () => {
		const tls = {
			_id: 't1',
			_source: {
				'@timestamp': '2026-11-03T10:00:00Z', source: { ip: '10.0.0.5' }, destination: { ip: '142.250.1.1' }, event: { dataset: 'ssl' },
				zeek: { ssl: { server_name: 'www.example.org', ssl_version: 'TLSv13', cipher: 'TLS_AES_128_GCM_SHA256' } },
			},
		};
		const dhcp = {
			_id: 'd1',
			_source: {
				'@timestamp': '2026-11-03T10:00:00Z', source: { ip: '192.168.1.50', mac: 'aa:bb:cc:dd:ee:ff' }, event: { dataset: 'dhcp' },
				zeek: { dhcp: { host_name: 'johns-iphone', assigned_ip: '192.168.1.50' } },
			},
		};
		stubDaemon({ ...AGGREGATIONS, '/api/logs/search': { hits: [tls, dhcp], total: 2 } });
		render(Page);
		await fireEvent.click(await screen.findByRole('button', { name: 'TLS' }));
		expect(await screen.findByText('www.example.org')).toBeInTheDocument();
		expect(screen.getByText('TLSv13')).toBeInTheDocument();
		expect(screen.getByRole('columnheader', { name: 'ssl.server_name' })).toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: 'DHCP' }));
		expect(await screen.findByText('johns-iphone')).toBeInTheDocument();
		expect(screen.getByText('aa:bb:cc:dd:ee:ff')).toBeInTheDocument();
	});
});

// NET-160 slice 2a: a count links to a list over the count's own window, so Log Explorer holds a
// link's exact window (?from=&to=, "Custom") and never moves a search's window while paging.
const DASHBOARD_PATHS = ['/api/logs/stats', '/api/logs/timeline', '/api/logs/top-talkers', '/api/logs/protocol-breakdown', '/api/logs/top-destinations', '/api/logs/top-dns'];
const requestsTo = (path: string) =>
	vi.mocked(fetch).mock.calls.map(([u]) => new URL(String(u), 'http://x')).filter((u) => u.pathname === path);
const bounds = (u: URL) => [u.searchParams.get('from'), u.searchParams.get('to')];

describe('Log Explorer — exact windows', () => {
	const FROM = '2026-11-05T09:00:00.000Z';
	const TO = '2026-11-05T10:30:00.000Z';
	/** One row per page, each with its own id, and more to come. */
	const PAGED = (url: string) => ({ hits: [hit(url, '10.0.0.5')], total: 5, search_after: [1] });

	beforeEach(() => {
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(new Date('2026-11-06T12:00:00Z'));
	});
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
	});

	it("opens on a link's exact window and pages within it, however late the next page is asked for", async () => {
		stubDaemon({ ...AGGREGATIONS, '/api/logs/search': PAGED }, true);
		goTo(`/logs?query=dns&range=24h&from=${FROM}&to=${TO}`);
		render(Page);
		const more = await screen.findByRole('button', { name: 'Load more' });
		expect(screen.getByRole('button', { name: 'Custom' })).toHaveAttribute('aria-pressed', 'true');
		// 90 minutes: the smallest standard range that covers it is 4h, bucketed by 15 minutes
		expect(screen.getByText(/^Log events per 15 minutes · window /)).toBeInTheDocument();
		expect(requestsTo('/api/logs/timeline')[0].searchParams.get('interval')).toBe('15m');

		vi.setSystemTime(Date.now() + 10 * 60_000);
		await fireEvent.click(more);
		await vi.waitFor(() => expect(requestsTo('/api/logs/search')).toHaveLength(2));
		expect(requestsTo('/api/logs/search')[1].searchParams.get('search_after')).toBe('[1]');
		for (const u of [...requestsTo('/api/logs/search'), ...DASHBOARD_PATHS.flatMap(requestsTo)]) expect(bounds(u)).toEqual([FROM, TO]);
	});

	it("pages within the first search's window when the link gave none, and the drawer reads from it", async () => {
		stubDaemon({ ...AGGREGATIONS, '/api/logs/search': PAGED }, true);
		render(Page);
		const more = await screen.findByRole('button', { name: 'Load more' });
		vi.setSystemTime(Date.now() + 10 * 60_000);
		await fireEvent.click(more);
		await vi.waitFor(() => expect(requestsTo('/api/logs/search')).toHaveLength(2));
		const [first, next] = requestsTo('/api/logs/search');
		expect(bounds(next)).toEqual(bounds(first));

		await fireEvent.click(screen.getAllByRole('button', { name: /^Open log entry from/ })[0]);
		await vi.waitFor(() => expect(requestsTo('/api/logs/search')).toHaveLength(3));
		expect(requestsTo('/api/logs/search')[2].searchParams.get('from')).toBe(first.searchParams.get('from'));
	});

	it('gives the figures and the table one window per load', async () => {
		stubDaemon({ ...AGGREGATIONS, '/api/logs/search': { hits: [], total: 0 } }, true);
		render(Page);
		await vi.waitFor(() => expect(requestsTo('/api/logs/search')).toHaveLength(1));
		const win = bounds(requestsTo('/api/logs/search')[0]);
		for (const path of DASHBOARD_PATHS) expect(bounds(requestsTo(path)[0]), path).toEqual(win);
	});

	it('reloads every card on a window-only URL change, clearing the old figures first', async () => {
		stubDaemon({ ...AGGREGATIONS, '/api/logs/search': { hits: [], total: 0 } });
		goTo('/logs?query=dns');
		render(Page);
		const total = () => screen.getByText('Total events').closest('.kpi');
		await vi.waitFor(() => expect(total()).toHaveTextContent('10'));

		// the new window's answers wait, so the old figures are seen to go before they arrive
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		goTo(`/logs?query=dns&from=${FROM}&to=${TO}`);
		await vi.waitFor(() => expect(requestsTo('/api/logs/search')).toHaveLength(1));
		expect(total()).toHaveTextContent('—');
		for (const path of DASHBOARD_PATHS) expect(requestsTo(path).map(bounds), path).toEqual([[FROM, TO]]);
		expect(bounds(requestsTo('/api/logs/search')[0])).toEqual([FROM, TO]);
		expect(requestsTo('/api/logs/search')[0].searchParams.get('query')).toBe('dns');
	});
});

describe('Log Explorer — drill-down links (NET-160 slice 2a)', () => {
	afterEach(() => vi.unstubAllGlobals());

	const named = (id: string, dataset: string, zeek: Record<string, unknown>) => ({
		_id: id,
		_source: { '@timestamp': '2026-11-03T10:00:00Z', source: { ip: '10.0.0.5' }, event: { dataset }, zeek },
	});

	it('links a host name to its domain page; addresses, host:port, empty values and lists stay text', async () => {
		const dns = (id: string, query: unknown) => named(id, 'dns', { dns: { query } });
		stubDaemon({
			...AGGREGATIONS,
			'/api/logs/search': {
				hits: [
					dns('a', 'Example.COM.'), dns('b', '203.0.113.7'), dns('c', '2001:db8::1'), dns('d', 'example.com:8080'), dns('e', ''),
					dns('f', ['a.example', 'b.example']), named('t', 'ssl', { ssl: { server_name: 'www.example.org' } }),
				],
				total: 7,
			},
		});
		const { container } = render(Page);
		await fireEvent.click(await screen.findByRole('button', { name: 'DNS' }));
		expect(await screen.findByRole('link', { name: 'Example.COM.' })).toHaveAttribute('href', '/domain/example.com');
		for (const text of ['203.0.113.7', '2001:db8::1', 'example.com:8080', 'a.example, b.example']) {
			expect(screen.getByText(text).closest('a'), text).toBeNull();
		}
		expect(container.querySelectorAll('a[href^="/domain/"]')).toHaveLength(1);
		expectNoNestedInteractive(container);

		await fireEvent.click(screen.getByRole('button', { name: 'TLS' }));
		expect(await screen.findByRole('link', { name: 'www.example.org' })).toHaveAttribute('href', '/domain/www.example.org');
	});

	it("opens the drawer's source address where it drills down: an internet address has no device page", async () => {
		const { goto } = await import('$app/navigation');
		stubDaemon({ ...AGGREGATIONS, '/api/logs/search': { hits: [hit('a', '203.0.113.7')], total: 1 } });
		render(Page);
		await fireEvent.click(await screen.findByRole('button', { name: /^Open log entry from/ }));
		await fireEvent.click(await screen.findByRole('button', { name: 'View source device' }));
		expect(goto).toHaveBeenCalledWith('/address/203.0.113.7');
	});
});

// NET-160 slice 2b-1: Home's Connections link opens the conn records its count holds, leaving out
// the sources the count left out. The URL is a one-time hand-off: every control here is local.
describe("Log Explorer — Home's Connections link and 6h (NET-160 slice 2b-1)", () => {
	const FROM = '2026-11-05T09:00:00.000Z';
	const TO = '2026-11-05T15:00:00.000Z';
	const HOME_LINK = `/logs?type=zeek.conn&exclude_src=192.168.1.199,2001:db8::199&from=${FROM}&to=${TO}&range=6h`;
	const searches = () => requestsTo('/api/logs/search');
	const last = () => searches().at(-1)!.searchParams;
	const chip = () => screen.queryByRole('button', { name: 'Remove filter: leaving out sources 192.168.1.199, 2001:db8::199' });

	afterEach(() => vi.unstubAllGlobals());

	async function openHomeLink() {
		stubDaemon({ ...AGGREGATIONS, '/api/logs/search': { hits: [], total: 0 } });
		goTo(HOME_LINK);
		render(Page);
		await vi.waitFor(() => expect(searches()).toHaveLength(1));
		// the type pills and "Clear all" act once the first load has finished, as they do for a user
		await vi.waitFor(() => expect(screen.getByText('Total events').closest('.kpi')).toHaveTextContent('10'));
		await new Promise((r) => setTimeout(r, 0));
	}

	it('makes one search for conn records without the excluded sources, on the link\'s window', async () => {
		await openHomeLink();
		const q = last();
		expect([q.get('log_type'), q.get('exclude_src'), q.get('from'), q.get('to')]).toEqual(['zeek.conn', '192.168.1.199,2001:db8::199', FROM, TO]);
		expect(within(screen.getByRole('group', { name: 'Log type' })).getByRole('button', { name: 'Connections' })).toHaveAttribute('aria-pressed', 'true');
		expect(chip()).toHaveTextContent('Leaving out sources 192.168.1.199, 2001:db8::199 (excluded in Settings, as Home counts)');
	});

	it('changing the type then clearing the chip searches everything, and the old URL never comes back', async () => {
		vi.mocked(goto).mockClear();
		await openHomeLink();
		await fireEvent.click(within(screen.getByRole('group', { name: 'Log type' })).getByRole('button', { name: 'All logs' }));
		await vi.waitFor(() => expect(searches()).toHaveLength(2));
		await fireEvent.click(chip()!);
		await vi.waitFor(() => expect(searches()).toHaveLength(3));
		expect([last().get('log_type'), last().get('exclude_src')]).toEqual([null, null]);
		expect(chip()).not.toBeInTheDocument();
		expect(goto).not.toHaveBeenCalled();
		// the same URL again is not a new hand-off, so nothing it held is put back
		goTo(HOME_LINK);
		await new Promise((r) => setTimeout(r, 0));
		expect(searches()).toHaveLength(3);
		expect(chip()).not.toBeInTheDocument();
	});

	it('a typed query survives clearing the chip', async () => {
		await openHomeLink();
		await fireEvent.input(screen.getByLabelText('Search logs'), { target: { value: 'dns' } });
		await fireEvent.click(chip()!);
		await vi.waitFor(() => expect(searches()).toHaveLength(2));
		expect([last().get('query'), last().get('exclude_src'), last().get('log_type')]).toEqual(['dns', null, 'zeek.conn']);
	});

	it('"Clear all" clears the excluded sources too', async () => {
		await openHomeLink();
		await fireEvent.click(screen.getByRole('button', { name: 'Clear all' }));
		await vi.waitFor(() => expect(searches()).toHaveLength(2));
		expect([last().get('exclude_src'), last().get('log_type')]).toEqual([null, null]);
		expect(chip()).not.toBeInTheDocument();
	});

	it('a hand-off sets its type, and one with no type of ours searches every type', async () => {
		stubDaemon({ ...AGGREGATIONS, '/api/logs/search': { hits: [], total: 0 } });
		goTo('/logs?type=zeek.dns&query=example.org');
		render(Page);
		await vi.waitFor(() => expect(searches()).toHaveLength(1));
		expect(last().get('log_type')).toBe('zeek.dns');
		goTo('/logs?type=zeek.nope&query=example.org');
		await vi.waitFor(() => expect(searches()).toHaveLength(2));
		expect(last().get('log_type')).toBeNull();
	});

	it('?range=6h opens the last 6 hours, with a 15-minute timeline', async () => {
		stubDaemon({ ...AGGREGATIONS, '/api/logs/search': { hits: [], total: 0 } });
		goTo('/logs?range=6h');
		render(Page);
		await vi.waitFor(() => expect(searches()).toHaveLength(1));
		expect(screen.getByRole('button', { name: '6h' })).toHaveAttribute('aria-pressed', 'true');
		expect(screen.getByText(/^Log events per 15 minutes · last 6 hours/)).toBeInTheDocument();
		expect(requestsTo('/api/logs/timeline')[0].searchParams.get('interval')).toBe('15m');
		const [from, to] = bounds(searches()[0]);
		expect((Date.parse(to!) - Date.parse(from!)) / 3_600_000).toBe(6);
	});
});
