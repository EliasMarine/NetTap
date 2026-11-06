import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import type { Writable } from 'svelte/store';
import { page } from '$app/stores';
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

/** Replies by path; any path not listed answers 503. */
function stubDaemon(replies: Record<string, unknown>): void {
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
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
